"""Makro-Schicht: Marktumfeld messen statt Meinungen raten.

Statt vager "Makro-Analysen" nutzt der Bot drei MESSBARE, täglich
verfügbare und im Backtest Point-in-Time-saubere Indikatoren (alles
Preiszeitreihen — keine revidierten Statistiken, kein Look-Ahead):

1. **Index-Trend**: SPY über seiner 200-Tage-Linie — der klassische
   Bullen-/Bärenmarkt-Schalter (deckt Konjunktur-Erwartungen ab).
2. **Angstprämie**: VIX unter seinem 50-Tage-Schnitt × 1,15 — steigende
   implizite Volatilität geht Abverkäufen typischerweise voraus.
3. **Kreditrisiko**: High-Yield- vs. Investment-Grade-Anleihen
   (HYG/LQD-Verhältnis über seinem 100-Tage-Schnitt) — der Bond-Markt
   riecht Stress oft früher als der Aktienmarkt.
4. **Realisierte Volatilität**: 20-Tage-Schwankung des Index unter dem
   1,25-fachen ihres 50-Tage-Schnitts — braucht KEINE Zusatzdaten und
   macht die Ampel damit überall funktionsfähig (Crashs kündigen sich
   fast immer durch einen Vol-Anstieg an; Proxy für den VIX, wenn der
   fehlt).

Risk-on = Mehrheit der verfügbaren Ampeln grün. Fehlt eine Zeitreihe,
stimmt sie nicht mit ab (neutral). Die Ampel begrenzt nur NEUE Käufe —
Exits/Stops laufen immer.

Dazu (nur Live-Betrieb): **Ereignis-Blackout** — an Tagen mit
Hochrisiko-Terminen (Fed-Entscheid, CPI, Arbeitsmarktbericht) keine
Neueinstiege. Quelle: FMP Economic Calendar (API-Key nötig); im Backtest
nicht verfügbar (kein freier Point-in-Time-Kalender), daher bewusst nur
als Live-Schutz umgesetzt.
"""

from __future__ import annotations

import pandas as pd

from .config import get_api_key

MACRO_SYMBOLS = {"vix": "^VIX", "hy": "HYG", "ig": "LQD", "index": "SPY"}


def _try_load(symbol: str, start: str) -> pd.Series | None:
    from .data import load_daily

    try:
        return load_daily(symbol, start=start)["Close"]
    except Exception:
        return None


def risk_on_series(start: str = "2012-01-01",
                   index_sma: int = 200, vix_sma: int = 50,
                   vix_tolerance: float = 1.15, credit_sma: int = 100,
                   rvol_n: int = 20, rvol_sma: int = 50, rvol_tol: float = 1.25,
                   closes: dict[str, pd.Series] | None = None) -> pd.Series | None:
    """Tages-Serie True/False: Mehrheit der verfügbaren Makro-Ampeln grün.

    closes: optional vorgeladene Close-Serien je Makro-Symbol (Backtests/
    Offline) — sonst wird über load_daily geladen. None, wenn gar keine
    Komponente verfügbar ist (Filter dann inaktiv).
    """
    def get(key: str) -> pd.Series | None:
        if closes is not None:
            return closes.get(MACRO_SYMBOLS[key])
        return _try_load(MACRO_SYMBOLS[key], start)

    votes: list[pd.Series] = []

    index = get("index")
    if index is not None:
        votes.append(index > index.rolling(index_sma).mean())
        # Realisierte Volatilität des Index — braucht keine Zusatzdaten
        rvol = index.pct_change(fill_method=None).rolling(rvol_n).std()
        votes.append(rvol < rvol.rolling(rvol_sma).mean() * rvol_tol)

    vix = get("vix")
    if vix is not None:
        votes.append(vix < vix.rolling(vix_sma).mean() * vix_tolerance)

    hy, ig = get("hy"), get("ig")
    if hy is not None and ig is not None:
        ratio = (hy / ig).dropna()
        votes.append(ratio > ratio.rolling(credit_sma).mean())

    if not votes:
        return None
    df = pd.concat(votes, axis=1).astype(float)
    # Mehrheit der an diesem Tag verfügbaren Stimmen
    return df.mean(axis=1, skipna=True) >= 0.5


def current_status(start: str = "2024-01-01") -> dict:
    """Aktueller Ampel-Stand je Komponente (fürs Log/Dashboard)."""
    status: dict[str, str] = {}
    series = {
        "Index-Trend (SPY>SMA200)": None,
        "Volatilität (VIX)": None,
        "Kredit (HYG/LQD)": None,
        "Realisierte Vola (Index)": None,
    }
    index = _try_load(MACRO_SYMBOLS["index"], start)
    if index is not None and len(index) > 200:
        series["Index-Trend (SPY>SMA200)"] = bool(index.iloc[-1] > index.rolling(200).mean().iloc[-1])
    vix = _try_load(MACRO_SYMBOLS["vix"], start)
    if vix is not None and len(vix) > 50:
        series["Volatilität (VIX)"] = bool(vix.iloc[-1] < vix.rolling(50).mean().iloc[-1] * 1.15)
    hy, ig = _try_load(MACRO_SYMBOLS["hy"], start), _try_load(MACRO_SYMBOLS["ig"], start)
    if hy is not None and ig is not None:
        ratio = (hy / ig).dropna()
        if len(ratio) > 100:
            series["Kredit (HYG/LQD)"] = bool(ratio.iloc[-1] > ratio.rolling(100).mean().iloc[-1])
    if index is not None and len(index) > 80:
        rvol = index.pct_change(fill_method=None).rolling(20).std()
        series["Realisierte Vola (Index)"] = bool(
            rvol.iloc[-1] < rvol.rolling(50).mean().iloc[-1] * 1.25)
    for name, val in series.items():
        status[name] = "grün" if val else ("rot" if val is not None else "keine Daten")
    avail = [v for v in series.values() if v is not None]
    status["risk_on"] = bool(sum(avail) * 2 >= len(avail)) if avail else True
    return status


def high_impact_event_today() -> str | None:
    """Live-Schutz: Name des heutigen Hochrisiko-Termins (USA) oder None.

    Quelle FMP Economic Calendar; ohne Key oder bei Fehlern: None (offen).
    """
    key = get_api_key("fmp")
    if not key:
        return None
    from .data.fmpapi import fmp_get

    today = pd.Timestamp.today().date().isoformat()
    try:
        data = fmp_get("economic-calendar", "economic_calendar",
                       {"from": today, "to": today}, key, timeout=15)
        for event in data or []:
            if (event.get("country") in ("US", "USA")
                    and str(event.get("impact", "")).lower() == "high"):
                return str(event.get("event", "Hochrisiko-Termin"))
    except Exception:
        return None
    return None
