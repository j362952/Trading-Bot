"""Trendfolge-Klassiker: SMA-Crossover und Buy & Hold als Maßstab.

Beleg: Trendfolge über gleitende Durchschnitte ist eine der ältesten und
robustesten Anomalien (Faber 2007, "A Quantitative Approach to Tactical
Asset Allocation"): ähnliche Rendite wie Buy & Hold, aber deutlich
kleinere Drawdowns — der Gewinn liegt im Risikoprofil, nicht in der
Spitzenrendite.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class SmaCrossover:
    """Investiert, solange der schnelle SMA über dem langsamen liegt."""

    fast: int = 50
    slow: int = 200

    @property
    def name(self) -> str:
        return f"SMA-Crossover {self.fast}/{self.slow}"

    def target_position(self, df: pd.DataFrame) -> pd.Series:
        fast_ma = df["Close"].rolling(self.fast).mean()
        slow_ma = df["Close"].rolling(self.slow).mean()
        return (fast_ma > slow_ma).astype(int)


@dataclass
class BuyAndHold:
    """Vergleichsmaßstab: einfach kaufen und liegen lassen."""

    name: str = "Buy & Hold"

    def target_position(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=df.index)
