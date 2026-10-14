"""Kursdaten-Provider: austauschbare Datenquellen hinter einem Schema.

Jeder Provider liefert dasselbe normalisierte Format (Index "Date",
Spalten Open/High/Low/Close/Volume). fetch_daily probiert die Provider
der Reihe nach durch — fällt Yahoo aus, springt Stooq ein. Neue Quellen
(z.B. mit API-Key: Alpha Vantage, Finnhub, EODHD) werden als weiteres
Modul ergänzt und hier eingetragen; der Rest des Codes bleibt unberührt.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from . import stooq, tiingo, yahoo

_PROVIDERS = [
    ("yahoo", yahoo.fetch),
    ("tiingo", tiingo.fetch),  # springt nur an, wenn TIINGO_API_KEY gesetzt ist
    ("stooq", stooq.fetch),    # aktuell hinter Bot-Schutz; bleibt als Versuch drin
]

# Zähler: welcher Provider hat in dieser Sitzung wie oft geliefert —
# macht auf der Daten-Seite sichtbar, WOHER die Kurse aktiv kommen
USAGE: Counter = Counter()


def fetch_daily(symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
    errors = []
    for name, fetch in _PROVIDERS:
        try:
            df = fetch(symbol, start, end)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            continue
        if not df.empty:
            USAGE[name] += 1
            return df
        errors.append(f"{name}: keine Daten")
    raise ValueError(f"Keine Kursdaten für {symbol!r} — {'; '.join(errors)}")
