"""Abruf-Orchestrierung: Universum → Provider → Datenbank.

Ablauf je Symbol:
1. Frische-Check: Daten jünger als max_age_days → überspringen (Resume-
   Verhalten: abgebrochene Läufe machen dort weiter, wo sie waren).
2. FMP (falls Key vorhanden und Symbol noch nie per FMP gefüllt):
   tiefe Quartals-Historie. Bei Tageslimit wird FMP für den Rest des
   Laufs abgeschaltet — die restlichen Symbole holt Yahoo.
3. Yahoo als Basis/Fallback (~5 Quartale, ohne Key).

FMP-Zeilen überschreiben Yahoo-Zeilen in der DB, nie umgekehrt (db.py).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Callable

import pandas as pd

from . import db
from .config import get_fmp_key, load_settings
from .providers import FmpProvider, ProviderLimitReached, YahooProvider

ProgressFn = Callable[[int, int, str, str], None]  # (i, n, symbol, status)


def update_fundamentals(
    universe: pd.DataFrame,
    conn,
    progress: ProgressFn | None = None,
    cancelled: Callable[[], bool] | None = None,
    force: bool = False,
    pause: float = 0.1,
) -> dict:
    """Lädt Quartalszahlen für alle Titel des Universums in die DB.

    Rückgabe: Statistik {"updated", "skipped", "failed", "fmp_used", "fmp_limit"}.
    """
    settings = load_settings()
    max_age = timedelta(days=int(settings.get("max_age_days", 30)))
    yahoo = YahooProvider()
    fmp = FmpProvider(get_fmp_key())
    fmp_active = fmp.available()

    stats = {"updated": 0, "skipped": 0, "failed": 0, "fmp_used": 0, "fmp_limit": False}
    symbols = list(universe["symbol"])
    lookup = universe.set_index("symbol")

    for i, symbol in enumerate(symbols, 1):
        if cancelled and cancelled():
            break

        # Stammdaten aus dem Universum sind gratis — immer mitschreiben
        meta = lookup.loc[symbol]
        db.upsert_company(conn, symbol, name=_s(meta.get("name")), sector=_s(meta.get("sector")))

        last = db.last_fetched(conn, symbol)
        if not force and last and datetime.now(timezone.utc) - last < max_age:
            stats["skipped"] += 1
            _report(progress, i, len(symbols), symbol, "übersprungen (frisch)")
            continue

        written = 0
        # 1) FMP: tiefe Historie, einmal pro Symbol
        if fmp_active and not db.company_flags(conn, symbol)["fmp_backfilled"]:
            try:
                written = db.upsert_quarterly(conn, symbol, fmp.fetch_quarterly(symbol), "fmp")
                if written:
                    db.upsert_company(conn, symbol, fmp_backfilled=1)
                    stats["fmp_used"] += 1
            except ProviderLimitReached:
                fmp_active = False
                stats["fmp_limit"] = True
            except Exception:
                pass  # FMP kennt viele Nicht-US-Symbole nicht → Yahoo übernimmt

        # 2) Yahoo: Basis bzw. Fallback
        if written == 0:
            try:
                written = db.upsert_quarterly(conn, symbol, yahoo.fetch_quarterly(symbol), "yahoo")
            except Exception as exc:
                stats["failed"] += 1
                _report(progress, i, len(symbols), symbol, f"Fehler: {exc}")
                continue

        if written:
            stats["updated"] += 1
            _report(progress, i, len(symbols), symbol, f"{written} Quartale")
        else:
            stats["failed"] += 1
            _report(progress, i, len(symbols), symbol, "keine Daten")
        time.sleep(pause)  # die Quellen nicht mit Anfragen bombardieren

    return stats


def _report(progress: ProgressFn | None, i: int, n: int, symbol: str, status: str) -> None:
    if progress:
        progress(i, n, symbol, status)


def _s(value) -> str:
    return "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
