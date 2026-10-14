"""Strategien-Registry: hier registrierte Strategien erscheinen automatisch
in GUI und Backtest-Skripten. Belege und Regeln je Strategie: STRATEGIE.md."""

from .base import (MatrixStrategy, SignalStrategy, make_strategy, param_fields,
                   position_matrix)
from .classic import BuyAndHold, SmaCrossover
from .donchian import DonchianBreakout
from .macro_rotation import MacroRegionalRotation
from .meanrev import RsiMeanReversion
from .momentum import MomentumRotation
from .momo_quality import VolAdjMomentumQuality
from .sentiment_gate import apply_sentiment_gate

STRATEGIES: dict[str, type] = {
    "sma_cross": SmaCrossover,
    "donchian": DonchianBreakout,
    "meanrev": RsiMeanReversion,
    "momentum": MomentumRotation,
    "momo_quality": VolAdjMomentumQuality,
    "macro_rotation": MacroRegionalRotation,
}

STRATEGY_LABELS: dict[str, str] = {
    "sma_cross": "Trendfolge: SMA-Crossover",
    "donchian": "Trendfolge: Donchian-Breakout",
    "meanrev": "Mean-Reversion: RSI-Rücksetzer",
    "momentum": "Momentum-Rotation (Universum)",
    "momo_quality": "Vol-adj. Momentum + Qualität (MoQu)",
    "macro_rotation": "NEU: Regionale Makro-Rotation (Fed/EZB)",
}

__all__ = [
    "STRATEGIES", "STRATEGY_LABELS",
    "SignalStrategy", "MatrixStrategy", "position_matrix", "param_fields",
    "make_strategy", "apply_sentiment_gate",
    "SmaCrossover", "BuyAndHold", "DonchianBreakout", "RsiMeanReversion",
    "MomentumRotation", "VolAdjMomentumQuality", "MacroRegionalRotation",
]
