"""Querschnitts-Momentum: die stärksten Aktien des Universums halten.

Beleg: der am besten dokumentierte Kapitalmarkt-Effekt überhaupt
(Jegadeesh/Titman 1993; Fama/French nennen Momentum "the premier
anomaly"): Aktien, die über 3–12 Monate am stärksten gestiegen sind,
schlagen die schwächsten im Folgemonat systematisch. Der jüngste Monat
wird übersprungen (kurzfristige Umkehr-Effekte).

Rotations-Strategie: braucht das ganze Universum, nicht ein einzelnes
Symbol — liefert daher direkt die Matrix Datum × Symbol.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .base import aligned_closes


@dataclass
class MomentumRotation:
    """Hält die top_n Aktien nach lookback-Tage-Rendite (ohne die letzten
    skip Tage), Neusortierung alle rebalance_days Handelstage."""

    lookback: int = 126      # ~6 Monate
    skip: int = 5            # jüngste Woche ausklammern (Reversal-Effekt)
    top_n: int = 5
    rebalance_days: int = 21  # ~monatlich

    @property
    def name(self) -> str:
        return f"Momentum-Rotation Top{self.top_n} ({self.lookback}d)"

    def target_matrix(self, bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
        closes = aligned_closes(bars)  # ein Kalender, Feiertagslücken überbrückt
        # Momentum: Rendite von t-lookback bis t-skip
        momentum = closes.shift(self.skip) / closes.shift(self.lookback) - 1

        values = momentum.to_numpy()
        out = np.zeros(values.shape, dtype=float)
        current = np.zeros(values.shape[1], dtype=bool)
        for i in range(values.shape[0]):
            if i % self.rebalance_days == 0:
                row = values[i]
                # nur Titel mit positivem Momentum — in breiten Abschwüngen
                # lieber (teilweise) Kasse als "die am wenigsten Schlechten"
                valid = np.where(np.nan_to_num(row, nan=-1.0) > 0)[0]
                order = valid[np.argsort(row[valid])[::-1][: self.top_n]]
                current = np.zeros(values.shape[1], dtype=bool)
                current[order] = True
            out[i] = current
        return pd.DataFrame(out, index=closes.index, columns=closes.columns)
