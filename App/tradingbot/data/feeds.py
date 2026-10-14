"""Feeds: füllen den Daten-Hub — je Kategorie eine Funktion.

Alle Funktionen sind einzeln aufrufbar (Abruf-Knöpfe der Daten-Seite),
loggen Erfolg/Fehler ins fetch_log des Hubs und sind gegen fehlende
Keys/Netzprobleme tolerant (sie werfen nicht, sie protokollieren).

Quellen:
- Aktuelle Preise:   Yahoo-Batch (wie bisher der Screener)
- Makro:             FRED (fredgraph.csv, kostenlos, kein Key) +
                     Preis-Proxys (VIX/HYG/LQD) in den Kurs-Cache
- Earnings-Termine:  FMP Earnings Calendar (Key nötig)
- Ereignis-Kalender: FMP Economic Calendar (Key nötig)
- Corporate Actions: Yahoo (Dividenden/Splits je Symbol)
- Universen:         bestehende Universums-Lader → Monats-Snapshot
"""

from __future__ import annotations

from typing import Callable

import pandas as pd
import requests

from ..config import get_api_key
from . import hub

ProgressFn = Callable[[str], None]


def _say(progress: ProgressFn | None, msg: str) -> None:
    if progress:
        progress(msg)


# ------------------------------------------------------- Aktuelle Preise

def update_quotes(conn, symbols: list[str], progress: ProgressFn | None = None) -> int:
    """Letzte Schlusskurse als Batch + Marktkapitalisierung aus Aktienzahl."""
    if not symbols:
        return 0
    try:
        import yfinance as yf

        _say(progress, f"Preis-Batch für {len(symbols)} Symbole …")
        data = yf.download(symbols, period="5d", interval="1d", auto_adjust=False,
                           progress=False, threads=True, group_by="ticker")
        prices: dict[str, float] = {}
        for s in symbols:
            try:
                closes = (data[s]["Close"] if len(symbols) > 1 else data["Close"]).dropna()
            except (KeyError, TypeError):
                continue
            if closes.empty:
                continue
            price = float(closes.iloc[-1])
            if s.endswith(".L"):
                price /= 100.0  # GBp → GBP
            prices[s] = price

        history = hub.quarterly_history(conn, list(prices))
        mcaps: dict[str, float] = {}
        if not history.empty:
            shares = (history.dropna(subset=["shares_outstanding"])
                      .groupby("symbol")["shares_outstanding"].last())
            for s, n in shares.items():
                if s in prices and n and n > 0:
                    mcaps[s] = prices[s] * float(n)
        hub.save_quotes(conn, prices, mcaps)
        hub.log_fetch(conn, "quotes", f"{len(prices)}/{len(symbols)}", "yahoo", True)
        return len(prices)
    except Exception as exc:
        hub.log_fetch(conn, "quotes", str(len(symbols)), "yahoo", False, str(exc))
        return 0


# ------------------------------------------------------------ Kurse EOD

def refresh_prices(conn, symbols: list[str], start: str = "2015-01-01",
                   progress: ProgressFn | None = None,
                   cancelled: Callable[[], bool] | None = None) -> int:
    """Kurs-Cache für die Symbole auffrischen (lädt fehlende/alte Historie)."""
    from . import load_daily
    from .providers import USAGE

    before = dict(USAGE)
    ok = 0
    for i, s in enumerate(symbols, 1):
        if cancelled and cancelled():
            break
        try:
            load_daily(s, start=start)
            ok += 1
        except Exception as exc:
            hub.log_fetch(conn, "prices", s, "yahoo/tiingo/stooq", False, str(exc))
        if i % 10 == 0 or i == len(symbols):
            _say(progress, f"Kurse: {i}/{len(symbols)} …")
    hub.refresh_price_meta(conn)
    # sichtbar machen, WELCHER Provider tatsächlich geliefert hat
    for name in ("yahoo", "tiingo", "stooq"):
        delta = USAGE.get(name, 0) - before.get(name, 0)
        if delta > 0:
            hub.log_fetch(conn, "prices", f"{delta} Abrufe", name, True)
    hub.log_fetch(conn, "prices", f"{ok}/{len(symbols)}", "cache", True)
    return ok


# ----------------------------------------------------- News + Intraday

def update_news(conn, symbols: list[str], progress: ProgressFn | None = None,
                cancelled: Callable[[], bool] | None = None) -> int:
    """Frische Schlagzeilen je Symbol ins append-only News-Archiv mergen."""
    from .news import load_news

    total = 0
    for i, s in enumerate(symbols, 1):
        if cancelled and cancelled():
            break
        try:
            total += len(load_news(s))
        except Exception as exc:
            hub.log_fetch(conn, "news", s, "yahoo", False, str(exc))
        if i % 10 == 0 or i == len(symbols):
            _say(progress, f"News: {i}/{len(symbols)} …")
    hub.log_fetch(conn, "news", f"{len(symbols)} Symbole", "yahoo", True,
                  f"{total} Meldungen im 14-Tage-Fenster")
    return total


def update_intraday(conn, symbols: list[str], interval: str = "1 hour",
                    progress: ProgressFn | None = None,
                    cancelled: Callable[[], bool] | None = None) -> int:
    """Intraday-Archiv füllen (Yahoo → Tiingo → FMP; wächst je Abruf)."""
    from .intraday import load_intraday

    ok = 0
    for i, s in enumerate(symbols, 1):
        if cancelled and cancelled():
            break
        try:
            load_intraday(s, interval)
            ok += 1
        except Exception as exc:
            hub.log_fetch(conn, "intraday", s, "yahoo/tiingo/fmp", False, str(exc))
        if i % 5 == 0 or i == len(symbols):
            _say(progress, f"Intraday ({interval}): {i}/{len(symbols)} …")
    hub.log_fetch(conn, "intraday", f"{ok}/{len(symbols)} ({interval})",
                  "yahoo/tiingo/fmp", ok > 0)
    return ok


# ----------------------------------------------------------------- Makro

# FRED-Reihen (kostenlos, ohne Key): Kürzel → Beschreibung.
# FRED spiegelt auch Nicht-Fed-Quellen (BLS, BEA, ICE/BofA, Uni Michigan) —
# eine Reihe ergänzen = eine Zeile hier.
FRED_SERIES = {
    # Zinsen & Zinskurve — USA
    "FEDFUNDS": "US-Leitzins (effektiv, monatlich)",
    "DFF": "US-Leitzins (effektiv, täglich — für Strategie-Signale)",
    "DGS2": "US-Staatsanleihen 2J Rendite (täglich)",
    "DGS10": "US-Staatsanleihen 10J Rendite (täglich)",
    "T10Y2Y": "Zinskurve 10J−2J (täglich)",
    "T10Y3M": "Zinskurve 10J−3M (täglich, klassischer Rezessionsindikator)",
    # Zinsen & Inflation — Europa (EZB/Eurostat/OECD, via FRED gespiegelt)
    "ECBDFR": "EZB-Einlagenzins (täglich)",
    "IRLTLT01DEM156N": "Deutschland 10J-Rendite (monatlich, OECD)",
    "CP0000EZ19M086NEST": "Euroraum HICP-Preisindex (monatlich)",
    # Kreditrisiko (direkter als der HYG/LQD-Proxy)
    "BAMLH0A0HYM2": "High-Yield-Spread ICE/BofA (täglich)",
    # Konjunktur & Arbeitsmarkt
    "CPIAUCSL": "US-Verbraucherpreise CPI (monatlich)",
    "UNRATE": "US-Arbeitslosenquote (monatlich)",
    "PAYEMS": "US-Beschäftigte ex Agrar, NFP-Niveau (monatlich)",
    "INDPRO": "US-Industrieproduktion (monatlich)",
    "UMCSENT": "Konsumentenstimmung Uni Michigan (monatlich)",
    # Märkte & Rohstoffe
    "DTWEXBGS": "Handelsgewichteter US-Dollar-Index (täglich)",
    "DCOILWTICO": "Ölpreis WTI (täglich)",
    "VIXCLS": "VIX Schlusskurs (täglich, redundant zum Yahoo-Proxy)",
}

MACRO_PROXIES = ["^VIX", "HYG", "LQD", "SPY"]  # Preis-Proxys der Makro-Ampel

# EZB-Direkt-API (offiziell, kostenlos, ohne Key) als Fallback für Europa-Reihen
ECB_FALLBACK = {
    "ECBDFR": ("FM", "B.U2.EUR.4F.KR.DFR.LEV"),          # Einlagenzins
    "CP0000EZ19M086NEST": ("ICP", "M.U2.N.000000.4.INX"),  # HICP-Index
}

# Yahoo-Renditeindizes als letzte Stufe für die US-Zinsreihen
# (^IRX = 13-Wochen-T-Bill in %, ^TNX = 10J-Rendite in %)
YAHOO_YIELD_PROXY = {
    "DFF": "IRX",      # Leitzins-RICHTUNG ≈ 3M-T-Bill (folgt der Fed eng)
    "DGS10": "TNX",
    "T10Y3M": "TNX-IRX",
}


def _fred_api(series: str, key: str) -> pd.Series:
    """Offizielle FRED-API (api.stlouisfed.org) — der zuverlässige Weg;
    kostenloser Key: https://fred.stlouisfed.org/docs/api/api_key.html"""
    resp = requests.get("https://api.stlouisfed.org/fred/series/observations",
                        params={"series_id": series, "api_key": key,
                                "file_type": "json"}, timeout=60)
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    if not obs:
        raise ValueError("keine Beobachtungen")
    df = pd.DataFrame(obs)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.set_index(pd.to_datetime(df["date"]))["value"].dropna()


def _fred_csv(series: str) -> pd.Series:
    """fredgraph.csv (Website-Endpunkt) — mit Timeout/Wiederholungen;
    wird von FRED zunehmend per Bot-Schutz gedrosselt."""
    from io import StringIO

    last_exc: Exception = RuntimeError("kein Versuch")
    for attempt in range(2):
        try:
            resp = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                                params={"id": series}, timeout=90,
                                headers={"User-Agent": "Mozilla/5.0",
                                         "Accept": "text/csv,*/*"})
            resp.raise_for_status()
            df = pd.read_csv(StringIO(resp.text))
            df.columns = ["date", "value"]
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            return df.set_index(pd.to_datetime(df["date"]))["value"]
        except Exception as exc:
            last_exc = exc
    raise last_exc


def _ecb_csv(flow: str, series_key: str) -> pd.Series:
    """EZB Data Portal API (data-api.ecb.europa.eu), CSV-Format, ohne Key."""
    from io import StringIO

    resp = requests.get(
        f"https://data-api.ecb.europa.eu/service/data/{flow}/{series_key}",
        params={"format": "csvdata"}, timeout=60,
        headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    if "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
        raise ValueError("EZB-CSV: erwartete Spalten fehlen")
    idx = pd.to_datetime(df["TIME_PERIOD"], errors="coerce")
    return (pd.Series(pd.to_numeric(df["OBS_VALUE"], errors="coerce").values, index=idx)
            .dropna().sort_index())


def _yahoo_yield(series: str) -> pd.Series:
    """US-Zinsreihe aus Yahoo-Renditeindizes ableiten (kein Key nötig)."""
    from . import load_daily

    spec = YAHOO_YIELD_PROXY[series]
    if spec == "TNX-IRX":
        tnx = load_daily("^TNX", start="2010-01-01")["Close"]
        irx = load_daily("^IRX", start="2010-01-01")["Close"]
        return (tnx - irx).dropna()
    return load_daily(f"^{spec}", start="2010-01-01")["Close"].dropna()


def fetch_macro_series(series: str) -> tuple[pd.Series, str]:
    """Eine Makro-Reihe über die Quellen-Kette holen:
    FRED-API (Key) → fredgraph → EZB-API → Yahoo-Zinsproxy.
    Rückgabe: (Serie, Quellen-Label). Wirft, wenn alle Stufen scheitern."""
    errors = []
    fred_key = get_api_key("fred")
    if fred_key:
        try:
            return _fred_api(series, fred_key), "fred-api"
        except Exception as exc:
            errors.append(f"fred-api: {exc}")
    try:
        return _fred_csv(series), "fred"
    except Exception as exc:
        errors.append(f"fredgraph: {exc}")
    if series in ECB_FALLBACK:
        try:
            return _ecb_csv(*ECB_FALLBACK[series]), "ecb"
        except Exception as exc:
            errors.append(f"ecb: {exc}")
    if series in YAHOO_YIELD_PROXY:
        try:
            return _yahoo_yield(series), "yahoo-proxy"
        except Exception as exc:
            errors.append(f"yahoo-proxy: {exc}")
    raise RuntimeError(" | ".join(errors))


def update_macro(conn, progress: ProgressFn | None = None) -> int:
    """Makro-Reihen in den Hub (Quellen-Kette je Reihe) +
    Makro-Preis-Proxys in den Kurs-Cache."""
    total = 0
    for series, label in FRED_SERIES.items():
        try:
            _say(progress, f"Makro {series} ({label}) …")
            s, source = fetch_macro_series(series)
            n = hub.save_macro_series(conn, series, s, source)
            hub.log_fetch(conn, "macro", series, source, True, f"{n} Punkte")
            total += n
        except Exception as exc:
            hub.log_fetch(conn, "macro", series, "fred", False, str(exc))

    # Preis-Proxys der Makro-Ampel in den Kurs-Cache holen (STRATEGIE.md §4.3)
    from . import load_daily

    for s in MACRO_PROXIES:
        try:
            _say(progress, f"Makro-Proxy {s} …")
            load_daily(s, start="2010-01-01")
            hub.log_fetch(conn, "macro", s, "prices", True)
        except Exception as exc:
            hub.log_fetch(conn, "macro", s, "prices", False, str(exc))
    hub.refresh_price_meta(conn)
    return total


# ------------------------------------------------------ Earnings-Termine

def update_earnings(conn, symbols: list[str], days_ahead: int = 90,
                    progress: ProgressFn | None = None) -> int:
    """Kommende Earnings-Termine (FMP). Ohne Key: protokolliert und 0."""
    key = get_api_key("fmp")
    if not key:
        hub.log_fetch(conn, "earnings", "-", "fmp", False, "kein FMP-Key hinterlegt")
        return 0
    try:
        _say(progress, "FMP Earnings-Kalender …")
        from .fmpapi import fmp_get

        today = pd.Timestamp.today().date()
        data = fmp_get("earnings-calendar", "earning_calendar",
                       {"from": today.isoformat(),
                        "to": (today + pd.Timedelta(days=days_ahead)).date().isoformat()},
                       key)
        wanted = set(symbols) if symbols else None
        rows = []
        for e in data or []:
            s = e.get("symbol", "")
            if wanted and s not in wanted:
                continue
            rows.append({"symbol": s, "date": e.get("date"), "time": e.get("time"),
                         "eps_estimate": e.get("epsEstimated", e.get("epsEstimate")),
                         "eps_actual": e.get("eps", e.get("epsActual")),
                         "revenue_estimate": e.get("revenueEstimated",
                                                   e.get("revenueEstimate"))})
        n = hub.save_earnings(conn, rows)
        hub.log_fetch(conn, "earnings", f"{n} Termine", "fmp", True)
        return n
    except Exception as exc:
        hub.log_fetch(conn, "earnings", "-", "fmp", False, str(exc))
        return 0


# ---------------------------------------------------- Ereignis-Kalender

def update_events(conn, days_ahead: int = 30, progress: ProgressFn | None = None) -> int:
    """Makro-Ereignisse (Fed/CPI/NFP …) der nächsten Tage (FMP)."""
    key = get_api_key("fmp")
    if not key:
        hub.log_fetch(conn, "events", "-", "fmp", False, "kein FMP-Key hinterlegt")
        return 0
    try:
        _say(progress, "FMP Economic Calendar …")
        from .fmpapi import fmp_get

        today = pd.Timestamp.today().date()
        data = fmp_get("economic-calendar", "economic_calendar",
                       {"from": today.isoformat(),
                        "to": (today + pd.Timedelta(days=days_ahead)).date().isoformat()},
                       key)
        rows = [{"date": str(e.get("date", ""))[:10], "country": e.get("country"),
                 "event": e.get("event", "?"), "impact": e.get("impact")}
                for e in data or [] if e.get("event")]
        n = hub.save_events(conn, rows)
        hub.log_fetch(conn, "events", f"{n} Termine", "fmp", True)
        return n
    except Exception as exc:
        hub.log_fetch(conn, "events", "-", "fmp", False, str(exc))
        return 0


# ---------------------------------------------------- Corporate Actions

def update_corporate_actions(conn, symbols: list[str],
                             progress: ProgressFn | None = None,
                             cancelled: Callable[[], bool] | None = None) -> int:
    """Dividenden/Splits je Symbol (Yahoo) — ein Abruf je Titel, daher
    gezielt für Watchlist/Universum aufrufen, nicht im Zyklus."""
    try:
        import yfinance as yf
    except ImportError as exc:
        hub.log_fetch(conn, "actions", "-", "yahoo", False, str(exc))
        return 0
    total = 0
    for i, s in enumerate(symbols, 1):
        if cancelled and cancelled():
            break
        try:
            t = yf.Ticker(s)
            total += hub.save_corporate_actions(conn, s, t.dividends, t.splits)
        except Exception as exc:
            hub.log_fetch(conn, "actions", s, "yahoo", False, str(exc))
        if i % 10 == 0 or i == len(symbols):
            _say(progress, f"Corporate Actions: {i}/{len(symbols)} …")
    hub.log_fetch(conn, "actions", f"{len(symbols)} Symbole", "yahoo", True,
                  f"{total} Einträge")
    return total


# -------------------------------------------------- Universen-Snapshots

def snapshot_universe(conn, key: str, progress: ProgressFn | None = None) -> int:
    """Aktuelle Index-Mitgliederliste als Monats-Snapshot fortschreiben."""
    from .universe import load_universe

    try:
        _say(progress, f"Universum {key} laden …")
        df = load_universe(key)
        n = hub.snapshot_universe(conn, key, df)
        # Sektor-Stammdaten mitschreiben (für Segment-Analysen)
        for _, r in df.iterrows():
            hub.upsert_company(conn, r["symbol"], name=str(r.get("name", "")),
                               sector=str(r.get("sector", "")))
        hub.log_fetch(conn, "universe", key, "web", True, f"{n} Titel")
        return n
    except Exception as exc:
        hub.log_fetch(conn, "universe", key, "web", False, str(exc))
        return 0


# ----------------------------------------------------- API-Verbindungstest

def test_apis(conn, progress: ProgressFn | None = None) -> dict[str, str]:
    """Jede Schnittstelle mit einer Mini-Anfrage prüfen; Ergebnis je API
    ins fetch_log (→ Ampeln im API-Panel) und als Dict zurück."""
    from ..config import get_api_key

    results: dict[str, str] = {}

    def check(name: str, source: str, fn) -> None:
        _say(progress, f"API-Test {name} …")
        try:
            detail = fn()
            results[name] = f"OK ({detail})"
            hub.log_fetch(conn, "apitest", name, source, True, str(detail))
        except Exception as exc:
            results[name] = f"FEHLER: {exc}"
            hub.log_fetch(conn, "apitest", name, source, False, str(exc))

    def _yahoo():
        import yfinance as yf

        df = yf.download("SPY", period="5d", progress=False, auto_adjust=False)
        if df is None or df.empty:
            raise ValueError("keine Daten für SPY")
        return f"{len(df)} Kerzen SPY"

    def _fmp():
        key = get_api_key("fmp")
        if not key:
            raise ValueError("kein Key hinterlegt (Zahnrad → API-Keys)")
        from .fmpapi import fmp_get

        data = fmp_get("profile?symbol=AAPL", "profile/AAPL", {}, key, timeout=20)
        if not data:
            raise ValueError("leere Antwort")
        return "Profil AAPL geliefert"

    def _tiingo():
        key = get_api_key("tiingo")
        if not key:
            raise ValueError("kein Key hinterlegt (Zahnrad → API-Keys)")
        resp = requests.get("https://api.tiingo.com/tiingo/daily/AAPL/prices",
                            params={"token": key}, timeout=20)
        resp.raise_for_status()
        if not resp.json():
            raise ValueError("leere Antwort")
        return "Tageskurs AAPL geliefert"

    def _fred():
        s, source = fetch_macro_series("DFF")
        return f"{len(s)} Punkte DFF via {source}"

    def _stooq():
        from .providers import stooq

        df = stooq.fetch("SPY", "2026-01-01")
        if df is None or df.empty:
            raise ValueError("keine Daten")
        return f"{len(df)} Kerzen SPY"

    check("Yahoo Finance", "yahoo", _yahoo)
    check("Financial Modeling Prep", "fmp", _fmp)
    check("Tiingo", "tiingo", _tiingo)
    check("FRED", "fred", _fred)
    check("Stooq", "stooq", _stooq)
    return results


# ------------------------------------------------------- Zyklus-Anbindung

def cycle_update(conn, symbols: list[str], progress: ProgressFn | None = None) -> None:
    """Leichter Feed-Lauf für den täglichen Zyklus: Quotes + (1× täglich)
    Makro/Earnings/Events. Fehler blockieren den Zyklus nie."""
    today = pd.Timestamp.today().date().isoformat()
    update_quotes(conn, symbols, progress)
    done = conn.execute("SELECT value FROM meta WHERE key='daily_feeds'").fetchone()
    if done and done[0] == today:
        return
    update_macro(conn, progress)
    update_earnings(conn, symbols, progress=progress)
    update_events(conn, progress=progress)
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('daily_feeds', ?)",
                 (today,))
    conn.commit()
