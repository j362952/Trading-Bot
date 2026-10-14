"""Quartals-Fundamentaldaten in den Hub laden (portiert aus dem
MarketScreener — dessen Datenschicht lebt jetzt hier, siehe GUI_KONZEPT.md).

Ablauf je Symbol:
1. Frische-Check: Daten jünger als max_age_days → überspringen (Resume).
2. FMP (Key + noch nie backfilled): tiefe Quartals-Historie; bei
   Tageslimit übernimmt Yahoo den Rest des Laufs.
3. Yahoo als Basis/Fallback (~5 Quartale, ohne Key).

FMP-Zeilen überschreiben Yahoo-Zeilen, nie umgekehrt (hub.upsert_quarterly).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Callable

import pandas as pd
import requests

from ..config import get_api_key
from . import hub
from .fmpapi import ProviderLimitReached, fmp_get

ProgressFn = Callable[[int, int, str, str], None]  # (i, n, symbol, status)


# ------------------------------------------------------------ Yahoo

_INCOME = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "gross_profit": ["Gross Profit"],
    "operating_income": ["Operating Income", "Total Operating Income As Reported"],
    "net_income": ["Net Income", "Net Income Common Stockholders",
                   "Net Income Continuous Operations"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "eps": ["Diluted EPS", "Basic EPS"],
}
_BALANCE = {
    "total_assets": ["Total Assets"],
    "total_equity": ["Stockholders Equity", "Common Stock Equity",
                     "Total Equity Gross Minority Interest"],
    "total_debt": ["Total Debt"],
    "cash": ["Cash And Cash Equivalents",
             "Cash Cash Equivalents And Short Term Investments"],
    "current_assets": ["Current Assets"],
    "current_liabilities": ["Current Liabilities"],
    "shares_outstanding": ["Ordinary Shares Number", "Share Issued"],
}
_CASHFLOW = {
    "operating_cashflow": ["Operating Cash Flow",
                           "Cash Flow From Continuing Operating Activities"],
    "capex": ["Capital Expenditure"],
    "free_cashflow": ["Free Cash Flow"],
}


def _yahoo_quarterly(symbol: str) -> pd.DataFrame:
    import yfinance as yf

    t = yf.Ticker(symbol)
    parts = [_extract(stmt, mapping) for stmt, mapping in [
        (t.quarterly_income_stmt, _INCOME),
        (t.quarterly_balance_sheet, _BALANCE),
        (t.quarterly_cashflow, _CASHFLOW),
    ]]
    df = pd.concat(parts, axis=1).sort_index().dropna(how="all")
    if "free_cashflow" in df and "operating_cashflow" in df and "capex" in df:
        df["free_cashflow"] = df["free_cashflow"].fillna(
            df["operating_cashflow"] + df["capex"])  # Capex ist bei Yahoo negativ
    return df


def _extract(stmt: pd.DataFrame, mapping: dict[str, list[str]]) -> pd.DataFrame:
    out = {}
    if stmt is None or stmt.empty:
        return pd.DataFrame(columns=list(mapping))
    for field, candidates in mapping.items():
        for candidate in candidates:
            if candidate in stmt.index:
                out[field] = stmt.loc[candidate]
                break
    df = pd.DataFrame(out)
    df.index = pd.to_datetime(df.index)
    return df.groupby(level=0).first()


# -------------------------------------------------------------- FMP

_FMP_FIELDS = {
    # normalisiert → (endpoint, FMP-Feld)
    "revenue": ("income", "revenue"),
    "gross_profit": ("income", "grossProfit"),
    "operating_income": ("income", "operatingIncome"),
    "net_income": ("income", "netIncome"),
    "ebitda": ("income", "ebitda"),
    "eps": ("income", "epsdiluted"),
    "total_assets": ("balance", "totalAssets"),
    "total_equity": ("balance", "totalStockholdersEquity"),
    "total_debt": ("balance", "totalDebt"),
    "cash": ("balance", "cashAndCashEquivalents"),
    "current_assets": ("balance", "totalCurrentAssets"),
    "current_liabilities": ("balance", "totalCurrentLiabilities"),
    "shares_outstanding": ("balance", "commonStock"),  # Fallback, s.u.
    "operating_cashflow": ("cashflow", "operatingCashFlow"),
    "capex": ("cashflow", "capitalExpenditure"),
    "free_cashflow": ("cashflow", "freeCashFlow"),
}
_FMP_ENDPOINTS = {
    "income": "income-statement", "balance": "balance-sheet-statement",
    "cashflow": "cash-flow-statement",
}


def _fmp_quarterly(symbol: str, key: str, limit: int = 60) -> pd.DataFrame:
    frames = {}
    for ep_key, path in _FMP_ENDPOINTS.items():
        # neue Keys: /stable/…?symbol=X — alte Keys: /api/v3/…/X
        rows = fmp_get(f"{path}?symbol={symbol}", f"{path}/{symbol}",
                       {"period": "quarter", "limit": limit}, key)
        if not isinstance(rows, list) or not rows:
            continue
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        frames[ep_key] = df.set_index("date").sort_index()

    if not frames:
        return pd.DataFrame()
    out = pd.DataFrame()
    for field, (ep_key, col) in _FMP_FIELDS.items():
        if ep_key in frames and col in frames[ep_key]:
            out[field] = frames[ep_key][col]
    # bessere Aktienzahl aus dem Income-Statement, falls vorhanden
    if "income" in frames and "weightedAverageShsOutDil" in frames["income"]:
        out["shares_outstanding"] = frames["income"]["weightedAverageShsOutDil"]
    return out.dropna(how="all")


# ------------------------------------------------------ Orchestrierung

def update_fundamentals(
    universe: pd.DataFrame,
    conn,
    progress: ProgressFn | None = None,
    cancelled: Callable[[], bool] | None = None,
    force: bool = False,
    max_age_days: int = 30,
    pause: float = 0.1,
) -> dict:
    """Quartalszahlen für alle Titel des Universums in den Hub laden."""
    max_age = timedelta(days=max_age_days)
    fmp_key = get_api_key("fmp")
    fmp_active = bool(fmp_key)

    stats = {"updated": 0, "skipped": 0, "failed": 0, "fmp_used": 0, "fmp_limit": False}
    symbols = list(universe["symbol"])
    lookup = universe.set_index("symbol")

    for i, symbol in enumerate(symbols, 1):
        if cancelled and cancelled():
            break
        meta = lookup.loc[symbol]
        hub.upsert_company(conn, symbol, name=_s(meta.get("name")),
                           sector=_s(meta.get("sector")))

        last = hub.last_fetched(conn, symbol)
        if not force and last and datetime.now(timezone.utc) - last < max_age:
            stats["skipped"] += 1
            _report(progress, i, len(symbols), symbol, "übersprungen (frisch)")
            continue

        written = 0
        if fmp_active and not hub.company_flags(conn, symbol)["fmp_backfilled"]:
            try:
                written = hub.upsert_quarterly(conn, symbol,
                                               _fmp_quarterly(symbol, fmp_key), "fmp")
                if written:
                    hub.upsert_company(conn, symbol, fmp_backfilled=1)
                    stats["fmp_used"] += 1
            except ProviderLimitReached:
                fmp_active = False
                stats["fmp_limit"] = True
            except Exception:
                pass  # FMP kennt viele Nicht-US-Symbole nicht → Yahoo übernimmt

        if written == 0:
            try:
                written = hub.upsert_quarterly(conn, symbol, _yahoo_quarterly(symbol),
                                               "yahoo")
            except Exception as exc:
                stats["failed"] += 1
                _report(progress, i, len(symbols), symbol, f"Fehler: {exc}")
                continue

        if written:
            stats["updated"] += 1
            _report(progress, i, len(symbols), symbol, f"{written} Quartale")
        else:
            stats["failed"] += 1
            _report(progress, i, len(symbols), symbol, "keine Daten")
        time.sleep(pause)

    hub.log_fetch(conn, "fundamentals", f"{stats['updated']} aktualisiert",
                  "fmp+yahoo", stats["failed"] < max(1, len(symbols)) / 2, str(stats))
    return stats


def _report(progress: ProgressFn | None, i: int, n: int, symbol: str, status: str) -> None:
    if progress:
        progress(i, n, symbol, status)


def _s(value) -> str:
    return "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
