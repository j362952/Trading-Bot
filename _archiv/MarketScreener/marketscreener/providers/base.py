"""Provider-Interface für Quartals-Fundamentaldaten."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class ProviderLimitReached(Exception):
    """Tages-/Ratenlimit der API erreicht — Provider für diesen Lauf abschalten."""


class FundamentalsProvider(ABC):
    """Liefert Quartalszahlen im normalisierten Schema (db.QUARTERLY_FIELDS).

    fetch_quarterly gibt einen DataFrame zurück:
    Index = Fiskalquartals-Enddatum, Spalten ⊆ QUARTERLY_FIELDS.
    Leerer DataFrame = keine Daten für dieses Symbol.
    """

    name: str

    def available(self) -> bool:
        return True

    @abstractmethod
    def fetch_quarterly(self, symbol: str) -> pd.DataFrame: ...

    def fetch_profile(self, symbol: str) -> dict:
        """Optionale Stammdaten: name, sector, industry, currency, financial_currency."""
        return {}
