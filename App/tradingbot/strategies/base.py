"""Basis des Strategien-Frameworks.

Zwei Strategie-Arten, beide reine Funktionen über Kursdaten (dadurch läuft
exakt derselbe Code im Backtest, Paper- und Live-Betrieb, auf Tages- wie
auf Intraday-Kerzen):

1. Signal-Strategien  — je Symbol: target_position(df) → Serie 0/1
2. Rotations-Strategien — über das ganze Universum: target_matrix(bars)
   → DataFrame (Datum × Symbol) mit 0/1

position_matrix() vereinheitlicht beide zur Matrix — Backtester und
Live-Engine kennen nur diese eine Form.

Alle Strategien sind dataclasses mit numerischen Feldern; die GUI liest
Parameter (Name, Default, Typ) direkt aus den Feldern aus — neue
Strategie-Parameter erscheinen dort automatisch.
"""

from __future__ import annotations

import dataclasses
from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class SignalStrategy(Protocol):
    name: str

    def target_position(self, df: pd.DataFrame) -> pd.Series:
        """Ziel-Position (0 oder 1) je Kerze, nur aus Daten bis zu dieser Kerze."""
        ...


@runtime_checkable
class MatrixStrategy(Protocol):
    name: str

    def target_matrix(self, bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Ziel-Positionen (0/1) als DataFrame Datum × Symbol."""
        ...


def position_matrix(strategy, bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Vereinheitlicht: jede Strategie wird zur Matrix Datum × Symbol (0/1)."""
    if hasattr(strategy, "target_matrix"):
        matrix = strategy.target_matrix(bars).fillna(0)
        return matrix[matrix.index.notna()]

    columns = {}
    for symbol, df in bars.items():
        columns[symbol] = strategy.target_position(df)
    matrix = pd.DataFrame(columns).sort_index()
    matrix = matrix[matrix.index.notna()]
    return matrix.ffill().fillna(0)


MAX_FILL_DAYS = 5  # so viele Kalender-Lücken in Folge werden überbrückt


def aligned_closes(bars: dict[str, pd.DataFrame],
                   max_fill: int = MAX_FILL_DAYS) -> pd.DataFrame:
    """Schlusskurse aller Titel auf EINEM Kalender (Vereinigung aller Handelstage).

    Gemischte Universen (z.B. US + Europa + Asien) haben verschiedene
    Feiertage. Ohne Auffüllen hat jeder Titel an fremden Feiertagen NaN —
    pct_change() erzeugt dort Lücken, und rolling(n).std() wird für das ganze
    Fenster NaN. Folge: Titel fallen aus Rankings (bei Global 2000 praktisch
    alle). Deshalb: letzten Kurs bis zu max_fill Tage fortschreiben (= an
    einem Feiertag ändert sich der Kurs nicht). Vor dem ersten und lange nach
    dem letzten Kurs wird nichts erfunden.
    """
    closes = pd.DataFrame({s: df["Close"] for s, df in bars.items()}).sort_index()
    closes = closes[closes.index.notna()]
    closes = closes[~closes.index.duplicated(keep="last")]
    return closes.ffill(limit=max_fill)


def param_fields(strategy_cls) -> list[dataclasses.Field]:
    """Einstellbare Parameter einer Strategie (für GUI und Doku)."""
    return [f for f in dataclasses.fields(strategy_cls)
            if f.type in ("int", "float", int, float)]


def make_strategy(strategy_cls, params: dict):
    """Instanziert eine Strategie mit (validierten) GUI-Parametern."""
    valid = {f.name: f.type for f in dataclasses.fields(strategy_cls)}
    kwargs = {}
    for key, value in params.items():
        if key in valid:
            caster = int if valid[key] in ("int", int) else float
            kwargs[key] = caster(value)
    return strategy_cls(**kwargs)
