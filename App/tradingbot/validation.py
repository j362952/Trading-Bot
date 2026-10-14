"""Robustheits-Validierung: eine Strategie immer wieder gegen die Historie.

Kernidee: EIN Backtest über EINEN Zeitraum beweist nichts — er kann
Glück, Survivorship oder Überanpassung sein. Dieser Harness zieht viele
ZUFÄLLIGE Stichproben:

- zufällige Zeitfenster (Monate bis Jahre, zufälliger Startpunkt),
- zufällige Teil-Universen (Stichprobe der verfügbaren Titel),

und lässt die Strategie jedes Mal mit voller Risk-Schicht und Kosten
antreten. Bewertet wird die VERTEILUNG der Ergebnisse: Median-Rendite,
Anteil positiver Fenster, Anteil Fenster über der Equal-Weight-Benchmark
desselben Teiluniversums, schlechtestes Fenster. Eine Strategie, die
"unterm Strich Geld verdient", muss hier über viele Stichproben
funktionieren — nicht in einem handverlesenen Chart.

Datenbasis: der lokale Kurs-Cache (data_cache/prices/) — kein Netzwerk
nötig, reproduzierbar per Seed.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from .data.prices import PRICE_CACHE_DIR
from .portfolio_backtest import run_portfolio_backtest
from .risk import RiskConfig

WINDOW_CHOICES = {          # Handelstage → Beschreibung
    63: "3 Monate", 126: "6 Monate", 252: "1 Jahr", 504: "2 Jahre", 1008: "4 Jahre",
}
WARMUP_DAYS = 300           # Vorlauf für Indikatoren (SMA200, Momentum-Lookback)


def load_cached_bars(min_days: int = 700) -> dict[str, pd.DataFrame]:
    """Alle Symbole aus dem Kurs-Cache mit ausreichend Historie."""
    bars = {}
    for f in sorted(PRICE_CACHE_DIR.glob("*.csv")):
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        df = df[df.index.notna()]
        if len(df) >= min_days:
            bars[f.stem] = df
    return bars


def robustness_test(
    strategy_factory: Callable[[], object],
    bars_all: dict[str, pd.DataFrame],
    n_runs: int = 40,
    subset_range: tuple[int, int] = (40, 150),
    risk: RiskConfig | None = None,
    regime_symbol: str = "SPY",
    macro_series: pd.Series | None = None,
    seed: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    """Viele zufällige (Fenster × Teiluniversum)-Backtests; eine Zeile je Lauf."""
    rng = np.random.default_rng(seed)
    risk = risk or RiskConfig()
    say = progress or (lambda m: None)

    symbols = [s for s in bars_all if s != regime_symbol]
    calendar = bars_all[regime_symbol].index if regime_symbol in bars_all else (
        max(bars_all.values(), key=len).index)
    regime_df = bars_all.get(regime_symbol)

    rows = []
    for run in range(n_runs):
        window = int(rng.choice(list(WINDOW_CHOICES)))
        # Startpunkt so, dass Warmup UND Fenster in die Historie passen
        max_start = len(calendar) - window - 1
        if max_start <= WARMUP_DAYS:
            raise ValueError("Historie zu kurz für dieses Fenster")
        start_i = int(rng.integers(WARMUP_DAYS, max_start))
        win_start, win_end = calendar[start_i], calendar[start_i + window]

        n_subset = int(rng.integers(*subset_range))
        picks = list(rng.choice(symbols, size=min(n_subset, len(symbols)), replace=False))

        warm_start = calendar[start_i - WARMUP_DAYS]
        bars = {}
        for s in picks:
            df = bars_all[s].loc[warm_start:win_end]
            # Titel muss im Fenster überwiegend handelbar gewesen sein
            if len(df.loc[win_start:win_end]) >= window * 0.8:
                bars[s] = df
        if len(bars) < 10:
            continue

        result = run_portfolio_backtest(
            bars, strategy_factory(), risk=risk,
            regime_df=regime_df.loc[warm_start:win_end] if regime_df is not None else None,
            regime_series=macro_series,
        )
        eq = result.equity.loc[win_start:]
        if len(eq) < 2 or eq.iloc[0] <= 0:
            continue
        ret = float(eq.iloc[-1] / eq.iloc[0] - 1)
        years = (eq.index[-1] - eq.index[0]).days / 365.25
        dd = float((eq / eq.cummax() - 1).min())

        # Benchmark: Equal-Weight Buy & Hold desselben Teiluniversums
        closes = pd.DataFrame({s: df["Close"] for s, df in bars.items()}).loc[win_start:win_end]
        norm = closes / closes.bfill().iloc[0]
        bench_ret = float(norm.mean(axis=1).iloc[-1] - 1)

        spy_ret = np.nan
        if regime_df is not None:
            spy_win = regime_df["Close"].loc[win_start:win_end]
            if len(spy_win) > 1:
                spy_ret = float(spy_win.iloc[-1] / spy_win.iloc[0] - 1)

        trades_in_window = sum(1 for t in result.trades
                               if t.entry_date is not None and t.entry_date >= win_start)
        rows.append({
            "window": WINDOW_CHOICES[window],
            "start": win_start.date().isoformat(),
            "n_symbols": len(bars),
            "return": round(ret, 4),
            "return_pa": round((1 + ret) ** (1 / years) - 1, 4) if years > 0 else np.nan,
            "benchmark": round(bench_ret, 4),
            "excess": round(ret - bench_ret, 4),
            "spy": round(spy_ret, 4) if not np.isnan(spy_ret) else np.nan,
            "excess_spy": round(ret - spy_ret, 4) if not np.isnan(spy_ret) else np.nan,
            "max_dd": round(dd, 4),
            "trades": trades_in_window,
            "killed": result.killed,
        })
        say(f"[{run + 1}/{n_runs}] {WINDOW_CHOICES[window]} ab {win_start.date()} "
            f"({len(bars)} Titel): {ret:+.1%} (Benchmark {bench_ret:+.1%})")
    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame) -> dict:
    """Verdichtet die Läufe zur Robustheits-Bilanz."""
    if results.empty:
        return {}
    return {
        "runs": len(results),
        "median_return_pa": float(results["return_pa"].median()),
        "pct_positive": float((results["return"] > 0).mean()),
        "pct_beat_benchmark": float((results["excess"] > 0).mean()),
        "pct_beat_spy": float((results["excess_spy"] > 0).mean()) if "excess_spy" in results else np.nan,
        "median_excess_spy": float(results["excess_spy"].median()) if "excess_spy" in results else np.nan,
        "median_excess": float(results["excess"].median()),
        "worst_window": float(results["return"].min()),
        "median_max_dd": float(results["max_dd"].median()),
        "killed_runs": int(results["killed"].sum()),
    }


PHASE_LABELS = {"bull": "Bulle (SPY >+10 % p.a.)", "seit": "Seitwärts",
                "bear": "Bär (SPY <−5 % p.a.)"}


def tag_phases(results: pd.DataFrame) -> pd.DataFrame:
    """Jede Zeile (= ein Zufallsfenster) nach Marktphase einordnen —
    Basis ist die annualisierte SPY-Rendite im selben Fenster."""
    days = {v: k for k, v in WINDOW_CHOICES.items()}
    out = results.copy()
    years = out["window"].map(days) / 252
    spy_pa = (1 + out["spy"]) ** (1 / years) - 1
    out["phase"] = np.where(spy_pa > 0.10, "bull",
                            np.where(spy_pa < -0.05, "bear", "seit"))
    return out


def summarize_by_phase(results: pd.DataFrame) -> pd.DataFrame:
    """Robustheits-Bilanz getrennt nach Marktphase — zeigt, WANN eine
    Strategie ihr Geld verdient (Auftrag: Marktphasen-Outperformance)."""
    tagged = tag_phases(results)
    rows = []
    for phase, grp in tagged.groupby("phase"):
        rows.append({"phase": PHASE_LABELS.get(phase, phase), "fenster": len(grp),
                     "median_pa": grp["return_pa"].median(),
                     "pct_pos": (grp["return"] > 0).mean(),
                     "excess_spy": grp["excess_spy"].median(),
                     "med_dd": grp["max_dd"].median()})
    order = {v: i for i, v in enumerate(PHASE_LABELS.values())}
    return (pd.DataFrame(rows).sort_values("phase", key=lambda s: s.map(order))
            .set_index("phase"))


def trade_segments(result, bars: dict[str, pd.DataFrame],
                   sectors: dict[str, str] | None = None) -> pd.DataFrame:
    """Geschlossene Trades nach Aktiengruppe auswerten (Auftrag: für welche
    Gruppe funktioniert die Strategie besonders gut?).

    Gruppen: Sektor (falls bekannt) und Volatilitäts-Drittel des Titels.
    """
    closed = result.closed_trades
    if not closed:
        return pd.DataFrame()
    vols = {s: float(df["Close"].pct_change(fill_method=None).std())
            for s, df in bars.items()}
    terciles = pd.Series(vols).rank(pct=True)

    rows = []
    for t in closed:
        v = terciles.get(t.symbol, np.nan)
        vol_grp = ("volatil (oberes Drittel)" if v > 2 / 3 else
                   "mittel" if v > 1 / 3 else "ruhig (unteres Drittel)")
        rows.append({"sektor": (sectors or {}).get(t.symbol, "?"),
                     "vol_gruppe": vol_grp, "ret": t.ret, "pnl": t.pnl})
    df = pd.DataFrame(rows)

    def agg(by: str) -> pd.DataFrame:
        g = df.groupby(by).agg(trades=("ret", "count"),
                               treffer=("ret", lambda x: (x > 0).mean()),
                               median_ret=("ret", "median"),
                               pnl_summe=("pnl", "sum"))
        g["gruppe_art"] = by
        return g.reset_index().rename(columns={by: "gruppe"})

    out = pd.concat([agg("sektor"), agg("vol_gruppe")], ignore_index=True)
    return out[out["trades"] >= 5].sort_values("pnl_summe", ascending=False)


def summary_text(name: str, s: dict) -> str:
    if not s:
        return f"{name}: keine auswertbaren Läufe"
    return (f"{name}\n"
            f"  Läufe                  : {s['runs']}\n"
            f"  Median-Rendite p.a.    : {s['median_return_pa']:+7.1%}\n"
            f"  Fenster positiv        : {s['pct_positive']:7.0%}\n"
            f"  Fenster > EW-Benchmark : {s['pct_beat_benchmark']:7.0%} "
            f"(Median-Exzess {s['median_excess']:+.1%})\n"
            f"  Fenster > SPY          : {s['pct_beat_spy']:7.0%} "
            f"(Median-Exzess {s['median_excess_spy']:+.1%})\n"
            f"  Schlechtestes Fenster  : {s['worst_window']:+7.1%}\n"
            f"  Median Max-Drawdown    : {s['median_max_dd']:7.1%}\n"
            f"  Kill-Switch-Läufe      : {s['killed_runs']}")
