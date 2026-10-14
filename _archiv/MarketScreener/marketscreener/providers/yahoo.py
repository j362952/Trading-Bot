"""Yahoo Finance (yfinance): Quartalszahlen ohne API-Key.

Reicht typischerweise ~5 Quartale zurück. Die Historie in der Datenbank
wächst mit jedem Quartal, in dem das Tool läuft — für tiefe Historie ab
dem ersten Tag den FMP-Provider mit API-Key nutzen.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

from .base import FundamentalsProvider

# normalisiertes Feld → Yahoo-Zeilennamen (erster Treffer gewinnt)
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


class YahooProvider(FundamentalsProvider):
    name = "yahoo"

    def fetch_quarterly(self, symbol: str) -> pd.DataFrame:
        t = yf.Ticker(symbol)
        parts = []
        for stmt, mapping in [
            (t.quarterly_income_stmt, _INCOME),
            (t.quarterly_balance_sheet, _BALANCE),
            (t.quarterly_cashflow, _CASHFLOW),
        ]:
            parts.append(_extract(stmt, mapping))
        df = pd.concat(parts, axis=1).sort_index()
        df = df.dropna(how="all")
        # FCF notfalls selbst rechnen (Capex ist bei Yahoo negativ)
        if "free_cashflow" in df and "operating_cashflow" in df and "capex" in df:
            fallback = df["operating_cashflow"] + df["capex"]
            df["free_cashflow"] = df["free_cashflow"].fillna(fallback)
        return df

    def fetch_profile(self, symbol: str) -> dict:
        try:
            info = yf.Ticker(symbol).info or {}
        except Exception:
            return {}
        return {
            "name": info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "currency": info.get("currency"),
            "financial_currency": info.get("financialCurrency"),
        }


def _extract(stmt: pd.DataFrame, mapping: dict[str, list[str]]) -> pd.DataFrame:
    """Yahoo-Statement (Zeilen = Posten, Spalten = Quartalsdaten) → normalisierte Spalten."""
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
    # Duplikate (gleiche Spalte doppelt geliefert) zusammenfassen
    return df.groupby(level=0).first()
