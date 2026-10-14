"""Austauschbare Schnittstellen für Quartals-Fundamentaldaten.

Jeder Provider liefert dasselbe normalisierte Schema (db.QUARTERLY_FIELDS).
Neue Quellen (z.B. EODHD, SEC EDGAR, Alpha Vantage) werden als weitere
Klasse neben yahoo.py/fmp.py ergänzt und in fundamentals.py eingehängt.
"""

from .base import FundamentalsProvider, ProviderLimitReached
from .fmp import FmpProvider
from .yahoo import YahooProvider

__all__ = ["FundamentalsProvider", "ProviderLimitReached", "FmpProvider", "YahooProvider"]
