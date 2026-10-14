"""Backtest-Suite: alle Strategien über eine Watchlist/ein Universum.

    uv run run_backtests.py beispiel                # Watchlist
    uv run run_backtests.py dax --start 2016-01-01  # Index
    uv run run_backtests.py beispiel --sentiment    # mit News-Gate (FinBERT)
    uv run run_backtests.py beispiel --sentiment --sentiment-backend claude

Vergleicht jede registrierte Strategie (mit Default-Parametern und
aktivem Risk-Management) gegen Buy & Hold über dasselbe Universum.
Ergebnis als Tabelle + CSV in reports/. Ergebnisse gehören ins
Backtest-Protokoll in STRATEGIE.md.
"""

from __future__ import annotations

import argparse
from datetime import date

import pandas as pd

from tradingbot.config import REPORTS_DIR
from tradingbot.data import load_daily
from tradingbot.data.universe import load_universe
from tradingbot.portfolio_backtest import run_portfolio_backtest
from tradingbot.risk import RiskConfig
from tradingbot.strategies import STRATEGIES, BuyAndHold


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest-Suite über ein Universum")
    parser.add_argument("universe", help="Watchlist- oder Index-Name (z.B. beispiel, dax, smi)")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--equity", type=float, default=100_000)
    parser.add_argument("--sentiment", action="store_true",
                        help="News-Sentiment-Gate aktivieren")
    parser.add_argument("--sentiment-backend", choices=["finbert", "claude"],
                        default=None, help="Sentiment-Modell (Default: Einstellung)")
    args = parser.parse_args()

    symbols = list(load_universe(args.universe)["symbol"])
    print(f"{len(symbols)} Titel, lade Kurse ab {args.start} ...")
    bars = {}
    for symbol in symbols:
        try:
            bars[symbol] = load_daily(symbol, start=args.start)
        except ValueError as exc:
            print(f"  {symbol} übersprungen: {exc}")
    try:
        regime_df = load_daily(RiskConfig().regime_symbol, start=args.start)
    except ValueError:
        regime_df = None

    sentiment = None
    if args.sentiment:
        from tradingbot.sentiment.history import daily_sentiment
        print(f"Score News-Archiv ({args.sentiment_backend or 'laut Einstellung'}) ...")
        sentiment = {s: daily_sentiment(s, refresh=False, backend=args.sentiment_backend)
                     for s in bars}

    rows = []
    for key, cls in STRATEGIES.items():
        result = run_portfolio_backtest(
            bars, cls(), risk=RiskConfig(), sentiment=sentiment,
            regime_df=regime_df, start_equity=args.equity,
        )
        rows.append({"key": key, **result.metrics()})
        print(result.summary())

    # Benchmark: Buy & Hold gleichgewichtet ohne Risk-Schicht
    bench = run_portfolio_backtest(
        bars, BuyAndHold(),
        risk=RiskConfig(max_positions=len(bars), max_weight=1 / max(len(bars), 1),
                        regime_sma=0, atr_stop_mult=1e9, max_drawdown=1.0,
                        risk_per_trade=1.0),
        start_equity=args.equity,
    )
    rows.append({"key": "buy_and_hold", **bench.metrics()})
    print(bench.summary())

    df = pd.DataFrame(rows).set_index("key")
    REPORTS_DIR.mkdir(exist_ok=True)
    out = REPORTS_DIR / f"backtests_{args.universe}_{date.today().isoformat()}.csv"
    df.to_csv(out)
    print(f"\nErgebnistabelle: {out}")


if __name__ == "__main__":
    main()
