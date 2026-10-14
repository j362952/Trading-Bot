"""Yahoo Finance (via yfinance): Primärquelle.

Kurse sind um Splits UND Dividenden bereinigt (auto_adjust) — die
sauberste kostenlose Basis für Renditeberechnungen im Backtest.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf


def fetch(symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
    df = yf.Ticker(symbol).history(start=start, end=end, auto_adjust=True)
    if df.empty:
        return pd.DataFrame()

    df = df[["Open", "High", "Low", "Close", "Volume"]]
    df.index = df.index.tz_localize(None)  # Tagesdaten brauchen keine Zeitzone
    df.index.name = "Date"
    return df
