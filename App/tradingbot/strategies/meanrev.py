"""Kurzfrist-Mean-Reversion: Rücksetzer im Aufwärtstrend kaufen.

Beleg: Connors/Alvarez ("Short Term Trading Strategies That Work"):
stark überverkaufte Aktien (RSI(2) sehr niedrig) ÜBER ihrem 200-Tage-
Schnitt erholen sich in Aktienmärkten überdurchschnittlich oft binnen
weniger Tage. Profil: hohe Trefferquote, viele kleine Gewinne, kurze
Haltedauer — komplementär zur Trendfolge (die selten trifft, aber groß
gewinnt). Funktioniert empirisch v.a. bei Aktien/Aktien-ETFs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def rsi(close: pd.Series, n: int) -> pd.Series:
    """Relative Strength Index (Wilder-Glättung)."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


@dataclass
class RsiMeanReversion:
    """Kauft überverkaufte Rücksetzer (RSI(rsi_n) < entry_rsi) oberhalb
    des trend_n-Schnitts; Ausstieg, wenn der Kurs den exit_sma-Schnitt
    zurückerobert oder der RSI über exit_rsi dreht."""

    rsi_n: int = 2
    entry_rsi: float = 10.0
    exit_rsi: float = 70.0
    trend_n: int = 200
    exit_sma: int = 5

    @property
    def name(self) -> str:
        return f"RSI({self.rsi_n})-MeanReversion <{self.entry_rsi:g}"

    def target_position(self, df: pd.DataFrame) -> pd.Series:
        close = df["Close"]
        r = rsi(close, self.rsi_n)
        trend_ok = close > close.rolling(self.trend_n).mean()
        exit_ma = close.rolling(self.exit_sma).mean()

        entries = (r < self.entry_rsi) & trend_ok
        exits = ((close > exit_ma) & (r > self.exit_rsi)) | ~trend_ok

        # vektorisierter Zustandsautomat (Entry verlangt trend_ok, Exit-Fälle
        # widersprechen dem Entry — kein Konflikt am selben Tag möglich)
        state = pd.Series(np.nan, index=df.index)
        state[exits] = 0.0
        state[entries] = 1.0
        return state.ffill().fillna(0).astype(int)
