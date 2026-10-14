"""Piotroski F-Score (2000): 9 binäre Qualitäts-/Momentum-Checks aus den
Fundamentaldaten — je erfüllter Check ein Punkt. Klassisch auf günstige
Aktien angewandt (hoher Buchwert/Preis); hier als eigenständiges Ranking
über das gewählte Universum (stand im Ideen-Backlog von ANALYSE.md).

Umsetzung auf Quartalsbasis: TTM vs. Vorjahres-TTM (statt Geschäftsjahre) —
das nutzt die wachsende Quartals-Historie des Hubs direkt.

Die 9 Checks:
Profitabilität: (1) ROA > 0, (2) operativer Cashflow > 0,
(3) ΔROA > 0, (4) OCF > Nettogewinn (Accruals).
Verschuldung/Liquidität: (5) Verschuldungsgrad gesunken,
(6) Current Ratio gestiegen, (7) keine Verwässerung (Aktienzahl ≤ Vorjahr).
Effizienz: (8) Bruttomarge gestiegen, (9) Kapitalumschlag gestiegen.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..data import hub

MAX_STALENESS_DAYS = 300


@dataclass
class PiotroskiFScore:
    key = "piotroski"
    label = "Piotroski F-Score"
    min_quarters: int = 8   # ohne Vorjahres-TTM kein Vergleich

    def score(self, conn, symbols: list[str]) -> pd.DataFrame:
        history = hub.quarterly_history(conn, symbols)
        if history.empty:
            return pd.DataFrame()

        cutoff = pd.Timestamp.today() - pd.Timedelta(days=MAX_STALENESS_DAYS)
        rows = {}
        for symbol, q in history.groupby("symbol"):
            q = q.sort_values("fiscal_date").set_index("fiscal_date")
            if q.index[-1] < cutoff or q["revenue"].notna().sum() < self.min_quarters:
                continue
            checks = _checks(q)
            if checks is None:
                continue
            rows[symbol] = checks

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame.from_dict(rows, orient="index")
        df.index.name = "symbol"
        df["score"] = df[[c for c in df.columns if c.startswith("f")]].sum(axis=1)
        cols = ["score"] + [c for c in df.columns if c != "score"]
        return df[cols].sort_values("score", ascending=False)


def _ttm(q: pd.DataFrame, field: str, offset: int = 0) -> float:
    s = q[field].dropna()
    end = len(s) - offset
    if end < 4:
        return np.nan
    return float(s.iloc[end - 4:end].sum())


def _latest(q, field, offset: int = 0) -> float:
    s = q[field].dropna()
    if len(s) <= offset:
        return np.nan
    return float(s.iloc[-1 - offset])


def _checks(q: pd.DataFrame) -> dict | None:
    ni, ni_prev = _ttm(q, "net_income"), _ttm(q, "net_income", 4)
    ocf = _ttm(q, "operating_cashflow")
    assets, assets_prev = _latest(q, "total_assets"), _latest(q, "total_assets", 4)
    debt, debt_prev = _latest(q, "total_debt"), _latest(q, "total_debt", 4)
    ca, ca_prev = _latest(q, "current_assets"), _latest(q, "current_assets", 4)
    cl, cl_prev = _latest(q, "current_liabilities"), _latest(q, "current_liabilities", 4)
    shares, shares_prev = _latest(q, "shares_outstanding"), _latest(q, "shares_outstanding", 4)
    gross, gross_prev = _ttm(q, "gross_profit"), _ttm(q, "gross_profit", 4)
    rev, rev_prev = _ttm(q, "revenue"), _ttm(q, "revenue", 4)

    if np.isnan(ni) or np.isnan(assets) or assets <= 0:
        return None

    roa = ni / assets
    roa_prev = ni_prev / assets_prev if not np.isnan(ni_prev) and assets_prev and assets_prev > 0 else np.nan
    lev = debt / assets if not np.isnan(debt) else np.nan
    lev_prev = debt_prev / assets_prev if not np.isnan(debt_prev) and assets_prev and assets_prev > 0 else np.nan
    cr = ca / cl if not np.isnan(ca) and cl and cl > 0 else np.nan
    cr_prev = ca_prev / cl_prev if not np.isnan(ca_prev) and cl_prev and cl_prev > 0 else np.nan
    gm = gross / rev if not np.isnan(gross) and rev and rev > 0 else np.nan
    gm_prev = gross_prev / rev_prev if not np.isnan(gross_prev) and rev_prev and rev_prev > 0 else np.nan
    at = rev / assets if rev and not np.isnan(rev) else np.nan
    at_prev = rev_prev / assets_prev if rev_prev and not np.isnan(rev_prev) and assets_prev and assets_prev > 0 else np.nan

    def check(cond) -> int:
        return int(bool(cond)) if cond is not None and not (isinstance(cond, float) and np.isnan(cond)) else 0

    return {
        "f1_roa_pos": check(roa > 0),
        "f2_ocf_pos": check(ocf > 0 if not np.isnan(ocf) else None),
        "f3_roa_up": check(roa > roa_prev if not np.isnan(roa_prev) else None),
        "f4_accruals": check(ocf > ni if not np.isnan(ocf) else None),
        "f5_leverage_down": check(lev < lev_prev if not (np.isnan(lev) or np.isnan(lev_prev)) else None),
        "f6_liquidity_up": check(cr > cr_prev if not (np.isnan(cr) or np.isnan(cr_prev)) else None),
        "f7_no_dilution": check(shares <= shares_prev * 1.01
                                if not (np.isnan(shares) or np.isnan(shares_prev)) else None),
        "f8_margin_up": check(gm > gm_prev if not (np.isnan(gm) or np.isnan(gm_prev)) else None),
        "f9_turnover_up": check(at > at_prev if not (np.isnan(at) or np.isnan(at_prev)) else None),
        "roa": round(roa, 4),
        "quarters": int(q["revenue"].notna().sum()),
        "last_quarter": q.index[-1].date().isoformat(),
    }
