"""Screening-Registry: Bewertungsalgorithmen als austauschbare Dateien —
gleiches Muster wie tradingbot/strategies (GUI_KONZEPT.md, Seite 3).

Ein Screener ist eine Klasse mit
    key   — Registry-Schlüssel
    label — Anzeigename in der GUI
    score(conn, symbols) -> DataFrame (Index symbol, Spalte 'score' +
                            Detail-Spalten, absteigend nach score)

Neue Algorithmen: Datei in diesem Paket anlegen, Klasse hier registrieren.
Datenbasis ist immer der Daten-Hub (fundamentals + quotes).
"""

from .value_score import ValueQualityGrowth
from .piotroski import PiotroskiFScore
from .magic_formula import MagicFormula

SCREENERS: dict[str, type] = {
    "value_score": ValueQualityGrowth,
    "piotroski": PiotroskiFScore,
    "magic_formula": MagicFormula,
}

SCREENER_LABELS: dict[str, str] = {
    "value_score": "Value/Quality/Growth-Score (ANALYSE.md)",
    "piotroski": "Piotroski F-Score (0–9)",
    "magic_formula": "Magic Formula (Greenblatt, angenähert)",
}

__all__ = ["SCREENERS", "SCREENER_LABELS",
           "ValueQualityGrowth", "PiotroskiFScore", "MagicFormula"]
