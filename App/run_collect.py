"""Headless-Datensammler: holt über ALLE Schnittstellen so viele Daten wie
möglich und speichert sie im Daten-Hub bzw. den registrierten Beständen.

    uv run run_collect.py                 # Universum aus dem Live-Profil
    uv run run_collect.py --universe sp500
    uv run run_collect.py --no-news --no-actions   # nur Kernkategorien
    uv run run_collect.py --intraday      # zusätzlich Intraday-Archiv (langsam)
    uv run run_collect.py --limit 300     # nur die ersten 300 Titel

Reihenfolge (jede Stufe protokolliert ins fetch_log; Fehler stoppen den
Lauf nicht): Universum-Snapshot → Kurse EOD → aktuelle Preise → Makro
(FRED-API/fredgraph/EZB/Yahoo-Kette) → Earnings → Ereignis-Kalender →
Fundamentaldaten (FMP bis Tageslimit, Rest Yahoo; resume-fähig) →
News-Archiv → Corporate Actions → optional Intraday.

Mehrfach laufen lassen ist erwünscht: alles ist idempotent, Fundamentals
machen beim nächsten Lauf dort weiter, wo das FMP-Limit sie stoppte.
Auch als täglicher Job geeignet (Windows-Aufgabenplanung → collect_data.bat).
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description="Datensammler für den Daten-Hub")
    parser.add_argument("--universe", default=None,
                        help="Universums-Key (Default: Live-Profil)")
    parser.add_argument("--limit", type=int, default=0,
                        help="max. Anzahl Titel (0 = alle)")
    parser.add_argument("--no-news", action="store_true", help="News-Archiv überspringen")
    parser.add_argument("--no-actions", action="store_true",
                        help="Corporate Actions überspringen")
    parser.add_argument("--no-fundamentals", action="store_true",
                        help="Fundamentaldaten überspringen")
    parser.add_argument("--intraday", action="store_true",
                        help="zusätzlich Intraday-Archiv (1 Std) — langsam")
    args = parser.parse_args()

    from tradingbot.config import load_settings
    from tradingbot.data import feeds, hub
    from tradingbot.data.universe import load_universe

    settings = load_settings()
    key = args.universe or settings.get("universe", "manual")

    print(f"=== Datensammler — Universum: {key} ===")
    if key in ("", "manual"):
        symbols = list(settings.get("watchlist", []))
        universe = pd.DataFrame({"symbol": symbols, "name": "", "sector": ""})
    else:
        universe = load_universe(key)
        symbols = list(universe["symbol"])
    if args.limit:
        universe = universe.head(args.limit)
        symbols = symbols[: args.limit]
    print(f"{len(symbols)} Titel\n")

    conn = hub.connect()
    say = lambda m: print(f"  {m}", flush=True)
    t0 = time.time()

    def step(name: str, fn) -> None:
        print(f"--- {name} ---", flush=True)
        try:
            result = fn()
            print(f"    fertig: {result}\n", flush=True)
        except Exception as exc:
            print(f"    FEHLER: {exc}\n", flush=True)

    if key not in ("", "manual"):
        step("Universum-Snapshot", lambda: feeds.snapshot_universe(conn, key, say))
    step("Kurse EOD (Cache auffrischen)",
         lambda: f"{feeds.refresh_prices(conn, symbols, progress=say)} Titel")
    step("Aktuelle Preise (Batch)",
         lambda: f"{feeds.update_quotes(conn, symbols, progress=say)} Quotes")
    step("Makro-Reihen (FRED/EZB/Yahoo-Kette)",
         lambda: f"{feeds.update_macro(conn, progress=say)} Punkte")
    step("Earnings-Kalender (FMP)",
         lambda: f"{feeds.update_earnings(conn, symbols, progress=say)} Termine")
    step("Ereignis-Kalender (FMP)",
         lambda: f"{feeds.update_events(conn, progress=say)} Termine")
    if not args.no_fundamentals:
        from tradingbot.data.fundamentals import update_fundamentals

        step("Fundamentaldaten (FMP bis Tageslimit, Rest Yahoo)",
             lambda: update_fundamentals(
                 universe, conn,
                 progress=lambda i, n, s, st: say(f"{i}/{n} {s}: {st}")))
    if not args.no_news:
        step("News-Archiv (Yahoo)",
             lambda: f"{feeds.update_news(conn, symbols, progress=say)} Meldungen")
    if not args.no_actions:
        step("Corporate Actions (Yahoo)",
             lambda: f"{feeds.update_corporate_actions(conn, symbols, progress=say)} Einträge")
    if args.intraday:
        step("Intraday-Archiv (1 Std)",
             lambda: f"{feeds.update_intraday(conn, symbols, progress=say)} Titel")

    hub.refresh_price_meta(conn)
    print(f"=== Lauf fertig in {(time.time() - t0) / 60:.1f} Min ===\n")
    print("Datenbestand jetzt:")
    print(hub.category_summary(conn).to_string(index=False, max_colwidth=40))
    errors = hub.recent_fetch_errors(conn, 10)
    if len(errors):
        print("\nLetzte Fehler (Details: Daten-Seite):")
        print(errors.to_string(index=False, max_colwidth=60))
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
