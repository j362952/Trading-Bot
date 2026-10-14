"""Magic Formula (Greenblatt, "The Little Book That Beats the Market"):
Rang(Gewinnrendite) + Rang(Kapitalrendite), niedrigere Summe = besser.

Angenäherte Umsetzung auf unserem Quartals-Schema (ehrlich dokumentiert):
- Gewinnrendite = TTM-EBIT / Enterprise Value (Original identisch)
- Kapitalrendite = TTM-EBIT / (Nettoumlaufvermögen + Anlagevermögen);
  Anlagevermögen fehlt im Schema → Näherung
  investiertes Kapital ≈ total_assets − current_liabilities − cash.
- Finanzwerte ranken hier systematisch schief (wie beim Original, das
  Banken/Versicherer ausschließt) — Sektor 'Financials' wird ausgelassen.

Score wird als 100 − Perzentil der Rangsumme ausgegeben (höher = besser),
damit alle Screener dieselbe Lesart haben.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..data import hub

MAX_STALENESS_DAYS = 300


@dataclass
class MagicFormula:
    key = "magic_formula"
    label = "Magic Formula"
    exclude_financials: bool = True

    def score(self, conn, symbols: list[str]) -> pd.DataFrame:
        history = hub.quarterly_history(conn, symbols)
        quotes = hub.latest_quotes(conn, symbols)
        if history.empty or len(quotes) == 0:
            return pd.DataFrame()

        sectors = hub.sector_map(conn)
        cutoff = pd.Timestamp.today() - pd.Timedelta(days=MAX_STALENESS_DAYS)
        rows = {}
        for symbol, q in history.groupby("symbol"):
            if symbol not in quotes.index:
                continue
            if self.exclude_financials and "financ" in str(sectors.get(symbol, "")).lower():
                continue
            mcap = quotes.loc[symbol, "market_cap"]
            if not mcap or pd.isna(mcap) or mcap <= 0:
                continue
            q = q.sort_values("fiscal_date").set_index("fiscal_date")
            if q.index[-1] < cutoff:
                continue

            ebit = float(q["operating_income"].dropna().iloc[-4:].sum()) \
                if q["operating_income"].notna().sum() >= 4 else np.nan
            debt = _latest(q, "total_debt")
            cash = _latest(q, "cash")
            assets = _latest(q, "total_assets")
            cl = _latest(q, "current_liabilities")
            if np.isnan(ebit) or np.isnan(assets):
                continue

            ev = float(mcap) + (0 if np.isnan(debt) else debt) - (0 if np.isnan(cash) else cash)
            capital = assets - (0 if np.isnan(cl) else cl) - (0 if np.isnan(cash) else cash)
            rows[symbol] = {
                "earnings_yield": ebit / ev if ev > 0 else np.nan,
                "return_on_capital": ebit / capital if capital > 0 else np.nan,
                "last_quarter": q.index[-1].date().isoformat(),
            }

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame.from_dict(rows, orient="index")
        df.index.name = "symbol"
        df = df.dropna(subset=["earnings_yield", "return_on_capital"])
        if df.empty:
            return df
        rank_sum = (df["earnings_yield"].rank(ascending=False)
                    + df["return_on_capital"].rank(ascending=False))
        df["score"] = ((1 - rank_sum.rank(pct=True)) * 100).round(1)
        df["earnings_yield"] = df["earnings_yield"].round(4)
        df["return_on_capital"] = df["return_on_capital"].round(4)
        return df.sort_values("score", ascending=False)


def _latest(q: pd.DataFrame, field: str) -> float:
    s = q[field].dropna()
    return float(s.iloc[-1]) if len(s) else np.nan
