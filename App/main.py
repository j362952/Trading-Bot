"""Backtest ausführen: uv run main.py [SYMBOL]

Beispiele:
    uv run main.py                      # Standard: SPY (S&P-500-ETF)
    uv run main.py BTC-USD              # funktioniert auch mit Krypto
    uv run main.py SPY --fast 20 --slow 100
"""

import argparse

from tradingbot.backtest import run_backtest
from tradingbot.data import load_daily
from tradingbot.strategies import BuyAndHold, SmaCrossover


def main() -> None:
    parser = argparse.ArgumentParser(description="Trading-Bot Backtest")
    parser.add_argument("symbol", nargs="?", default="SPY", help="Ticker-Symbol (Yahoo Finance)")
    parser.add_argument("--start", default="2015-01-01", help="Startdatum (YYYY-MM-DD)")
    parser.add_argument("--fast", type=int, default=50, help="Schneller SMA in Tagen")
    parser.add_argument("--slow", type=int, default=200, help="Langsamer SMA in Tagen")
    args = parser.parse_args()

    strategy = SmaCrossover(args.fast, args.slow)
    backtest_single(args.symbol, args, strategy)


def backtest_single(symbol: str, args: argparse.Namespace, strategy: SmaCrossover) -> None:
    df = load_daily(symbol, start=args.start)
    print(f"{len(df)} Handelstage geladen: {df.index[0]:%Y-%m-%d} bis {df.index[-1]:%Y-%m-%d}\n")

    print(run_backtest(df, strategy, symbol=symbol).summary())
    print()
    print(run_backtest(df, BuyAndHold(), symbol=symbol).summary())


if __name__ == "__main__":
    main()
