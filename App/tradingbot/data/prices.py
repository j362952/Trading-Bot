"""Kurshistorie: eine Datei pro Symbol, inkrementell fortgeschrieben.

Speicherkonzept: data_cache/prices/{symbol}.csv hält die komplette
Tageshistorie ab HISTORY_START, egal welcher Zeitraum gerade angefragt
wird — Anfragen werden aus dieser einen Datei geschnitten. Neue
Handelstage werden angehängt statt alles neu zu laden.

Weil Yahoo-Kurse dividenden-/splitbereinigt sind, ändern sich bei einem
Split auch die ALTEN Kurse rückwirkend. Deshalb wird die Historie einmal
pro Woche komplett neu geladen; dazwischen reichen die billigen
Tages-Inkremente.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from ..config import DATA_CACHE_DIR
from .providers import fetch_daily

PRICE_CACHE_DIR = DATA_CACHE_DIR / "prices"
HISTORY_START = "2010-01-01"          # so weit zurück reicht unsere Historie
STALE_AFTER = timedelta(hours=12)     # danach neue Handelstage nachladen
FULL_REFRESH_AFTER = timedelta(days=7)  # danach komplett neu (Split-Korrekturen)


def load_daily(symbol: str, start: str = "2015-01-01", end: str | None = None) -> pd.DataFrame:
    """Tageskerzen (OHLCV) für ein Symbol im angefragten Zeitraum."""
    df = _load_history(symbol)
    result = df.loc[start:end] if end else df.loc[start:]
    if result.empty:
        raise ValueError(f"Keine Kursdaten für {symbol!r} im Zeitraum ab {start}")
    return result.copy()


def _load_history(symbol: str) -> pd.DataFrame:
    cache_file = PRICE_CACHE_DIR / f"{symbol}.csv"

    if not cache_file.exists():
        return _full_fetch(symbol)

    # st_ctime ist unter Windows die Erstellungszeit — sie markiert den
    # letzten Komplett-Download (Datei wird dabei neu angelegt)
    stat = cache_file.stat()
    created = datetime.fromtimestamp(stat.st_ctime)
    modified = datetime.fromtimestamp(stat.st_mtime)

    if datetime.now() - created > FULL_REFRESH_AFTER:
        return _full_fetch(symbol)

    df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
    df = df[df.index.notna()]  # defekte Zeilen (leeres Datum) verwerfen
    if datetime.now() - modified > STALE_AFTER and df.index[-1].date() < date.today():
        next_day = (df.index[-1] + pd.Timedelta(days=1)).date().isoformat()
        try:
            fresh = fetch_daily(symbol, start=next_day)
            df = pd.concat([df, fresh])
            df = df[df.index.notna()]
            df = df[~df.index.duplicated(keep="last")].sort_index()
        except ValueError:
            pass  # Wochenende/Feiertag oder Quelle down — alter Stand bleibt nutzbar
        df.to_csv(cache_file)  # aktualisiert mtime, auch wenn nichts Neues kam
    return df


def _full_fetch(symbol: str) -> pd.DataFrame:
    df = fetch_daily(symbol, HISTORY_START)
    PRICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = PRICE_CACHE_DIR / f"{symbol}.csv"
    cache_file.unlink(missing_ok=True)  # neu anlegen, damit die Erstellungszeit zählt
    df.to_csv(cache_file)
    return df
