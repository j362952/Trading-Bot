"""Value/Quality/Growth-Score — der Kern-Algorithmus des früheren
MarketScreeners, portiert auf den Daten-Hub. Methodik maßgeblich in
ANALYSE.md (im Projektordner, neben STRATEGIE.md):

- Flussgrößen als TTM (Summe der letzten 4 reporteten Quartale),
  Bestandsgrößen aus dem jüngsten Quartal; älter als 300 Tage → raus.
- 12 Kennzahlen in drei Säulen: Value 45 % / Quality 40 % / Growth 15 %.
- Perzentil-Ränge innerhalb des Universums, Säulen = Mittel ihrer
  Kennzahlen, Score = gewichtetes Säulen-Mittel; < 50 % Abdeckung → raus.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..data import hub

MAX_STALENESS_DAYS = 300
MIN_COVERAGE = 0.5


@dataclass
class Metric:
    pillar: str
    higher_is_better: bool = True


METRICS: dict[str, Metric] = {
    "earnings_yield": Metric("value"),
    "fcf_yield": Metric("value"),
    "ebitda_ev_yield": Metric("value"),
    "book_to_price": Metric("value"),
    "return_on_equity": Metric("quality"),
    "operating_margin": Metric("quality"),
    "gross_margin": Metric("quality"),
    "debt_to_equity": Metric("quality", higher_is_better=False),
    "current_ratio": Metric("quality"),
    "margin_stability": Metric("quality", higher_is_better=False),
    "revenue_growth": Metric("growth"),
    "earnings_growth": Metric("growth"),
}

PILLAR_WEIGHTS = {"value": 0.45, "quality": 0.40, "growth": 0.15}


@dataclass
class ValueQualityGrowth:
    key = "value_score"
    label = "Value/Quality/Growth-Score"

    def score(self, conn, symbols: list[str]) -> pd.DataFrame:
        metrics = compute_metrics(conn, symbols)
        if metrics.empty:
            return metrics

        metric_cols = list(METRICS)
        coverage = metrics[metric_cols].notna().mean(axis=1)
        metrics = metrics[coverage >= MIN_COVERAGE]
        if metrics.empty:
            return pd.DataFrame()

        ranks = pd.DataFrame(index=metrics.index)
        for name, spec in METRICS.items():
            ranks[name] = metrics[name].rank(pct=True, ascending=spec.higher_is_better) * 100

        pillars = pd.DataFrame(index=metrics.index)
        for pillar in PILLAR_WEIGHTS:
            cols = [n for n, spec in METRICS.items() if spec.pillar == pillar]
            pillars[pillar] = ranks[cols].mean(axis=1)

        weights = pd.Series(PILLAR_WEIGHTS)
        weighted = (pillars * weights).sum(axis=1)
        weight_present = pillars.notna().mul(weights).sum(axis=1)
        total = weighted / weight_present

        result = pd.DataFrame({
            "score": total.round(1),
            "value": pillars["value"].round(1),
            "quality": pillars["quality"].round(1),
            "growth": pillars["growth"].round(1),
            "coverage": coverage[metrics.index].round(2),
        })
        extra = metrics[["quarters", "last_quarter"]]
        return (result.join(metrics[metric_cols].astype(float).round(4)).join(extra)
                .sort_values("score", ascending=False))


def compute_metrics(conn, symbols: list[str]) -> pd.DataFrame:
    """Kennzahlen je Symbol aus Hub-Quartalshistorie + jüngstem Quote."""
    history = hub.quarterly_history(conn, symbols)
    quotes = hub.latest_quotes(conn, symbols)
    if history.empty or len(quotes) == 0:
        return pd.DataFrame()

    rows = {}
    cutoff = pd.Timestamp.today() - pd.Timedelta(days=MAX_STALENESS_DAYS)
    for symbol, q in history.groupby("symbol"):
        if symbol not in quotes.index:
            continue
        mcap = quotes.loc[symbol, "market_cap"]
        if not mcap or pd.isna(mcap) or mcap <= 0:
            continue
        q = q.sort_values("fiscal_date").set_index("fiscal_date")
        if q.index[-1] < cutoff:
            continue
        rows[symbol] = _symbol_metrics(q, float(mcap))

    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "symbol"
    return df


def _ttm(q: pd.DataFrame, field: str, offset: int = 0) -> float:
    series = q[field].dropna()
    end = len(series) - offset
    if end < 4:
        return np.nan
    return float(series.iloc[end - 4:end].sum())


def _latest(q: pd.DataFrame, field: str) -> float:
    series = q[field].dropna()
    return float(series.iloc[-1]) if len(series) else np.nan


def _symbol_metrics(q: pd.DataFrame, mcap: float) -> dict:
    ni = _ttm(q, "net_income")
    fcf = _ttm(q, "free_cashflow")
    ebitda = _ttm(q, "ebitda")
    revenue = _ttm(q, "revenue")
    gross = _ttm(q, "gross_profit")
    op_income = _ttm(q, "operating_income")

    equity = _latest(q, "total_equity")
    debt = _latest(q, "total_debt")
    cash = _latest(q, "cash")
    cur_assets = _latest(q, "current_assets")
    cur_liab = _latest(q, "current_liabilities")

    ev = mcap + (0 if np.isnan(debt) else debt) - (0 if np.isnan(cash) else cash)
    eq_series = q["total_equity"].dropna()
    avg_equity = float(eq_series.iloc[-5:].mean()) if len(eq_series) else np.nan

    with np.errstate(divide="ignore", invalid="ignore"):
        q_margin = (q["operating_income"] / q["revenue"].where(q["revenue"] > 0)).dropna()
    margin_stability = float(q_margin.iloc[-8:].std()) if len(q_margin) >= 4 else np.nan

    revenue_prev = _ttm(q, "revenue", offset=4)
    ni_prev = _ttm(q, "net_income", offset=4)

    return {
        "earnings_yield": _div(ni, mcap),
        "fcf_yield": _div(fcf, mcap),
        "ebitda_ev_yield": _div(ebitda, ev) if ev > 0 else np.nan,
        "book_to_price": _div(equity, mcap) if equity and equity > 0 else np.nan,
        "return_on_equity": _div(ni, avg_equity) if avg_equity and avg_equity > 0 else np.nan,
        "operating_margin": _div(op_income, revenue) if revenue and revenue > 0 else np.nan,
        "gross_margin": _div(gross, revenue) if revenue and revenue > 0 else np.nan,
        "debt_to_equity": _div(debt, equity) if equity and equity > 0 else np.nan,
        "current_ratio": _div(cur_assets, cur_liab) if cur_liab and cur_liab > 0 else np.nan,
        "margin_stability": margin_stability,
        "revenue_growth": _div(revenue, revenue_prev) - 1 if revenue_prev and revenue_prev > 0 else np.nan,
        "earnings_growth": _div(ni, ni_prev) - 1 if ni_prev and ni_prev > 0 else np.nan,
        "quarters": int(q["revenue"].notna().sum()),
        "last_quarter": q.index[-1].date().isoformat(),
    }


def _div(a: float, b: float) -> float:
    if a is None or b is None or np.isnan(a) or np.isnan(b) or b == 0:
        return np.nan
    return a / b
