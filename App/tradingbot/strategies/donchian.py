"""Donchian-Breakout (Turtle-Stil): kaufe neue Hochs, verkaufe neue Tiefs.

Beleg: Kern der dokumentiert profitablen Turtle-Trader-Systeme (Dennis/
Eckhardt, 1980er) und bis heute Standardbaustein systematischer
Trendfolger (Carver, "Systematic Trading"). Logik: Ausbrüche auf neue
N-Perioden-Hochs setzen sich häufiger fort als sie scheitern, wenn man
Verlierer schnell und Gewinner spät schließt.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class DonchianBreakout:
    """Einstieg über dem Hoch der letzten entry_n Kerzen,
    Ausstieg unter dem Tief der letzten exit_n Kerzen (asymmetrisch)."""

    entry_n: int = 55
    exit_n: int = 20

    @property
    def name(self) -> str:
        return f"Donchian-Breakout {self.entry_n}/{self.exit_n}"

    def target_position(self, df: pd.DataFrame) -> pd.Series:
        upper = df["High"].rolling(self.entry_n).max().shift(1)
        lower = df["Low"].rolling(self.exit_n).min().shift(1)
        close = df["Close"]

        entries = close > upper
        exits = close < lower

        # vektorisierter Zustandsautomat: 1 bei Entry, 0 bei Exit, dazwischen
        # letzten Zustand fortschreiben (Entry und Exit schließen sich aus)
        state = pd.Series(np.nan, index=df.index)
        state[entries] = 1.0
        state[exits] = 0.0
        return state.ffill().fillna(0).astype(int)
