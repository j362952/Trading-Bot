"""Sentiment-Historie je Symbol: Schlagzeilen aus dem News-Archiv scoren.

Scores werden je Symbol UND Modell gecacht, das Modell rechnet also nur
neue, noch ungescorte Schlagzeilen:

    data_cache/news_scores/{symbol}.csv          FinBERT (wie bisher)
    data_cache/news_scores_claude/{symbol}.csv   Claude (+ Label, Begründung)

Ergebnis ist eine Tages-Serie: Ø Sentiment aller Meldungen des Tages.

Backend-Wahl: Parameter `backend` ("finbert"/"claude"), sonst die
Einstellung `sentiment_backend`. Fällt Claude aus (kein Key, API-Fehler),
wird automatisch mit FinBERT gerechnet — das Gate bleibt also scharf,
statt bei einem API-Ausfall stillschweigend offen zu stehen.

Wichtig für Backtests: das News-Archiv ist append-only mit Original-
Zeitstempeln — eine Meldung wirkt erst ab dem Tag, an dem sie bekannt
war (kein Look-Ahead). Die Historie ist so lang, wie das Archiv gepflegt
wurde; davor gibt es schlicht kein Sentiment (= Gate inaktiv).
"""

from __future__ import annotations

import logging

import pandas as pd

from ..config import DATA_CACHE_DIR

log = logging.getLogger(__name__)

BACKENDS = ("finbert", "claude")
SCORE_CACHE_DIRS = {
    "finbert": DATA_CACHE_DIR / "news_scores",
    "claude": DATA_CACHE_DIR / "news_scores_claude",
}
SCORE_CACHE_DIR = SCORE_CACHE_DIRS["finbert"]  # Rückwärtskompatibilität

# zuletzt tatsächlich genutztes Backend je Symbol (für Log-Ausgaben der Engine)
last_backend: dict[str, str] = {}


def resolve_backend(backend: str | None = None) -> str:
    if backend is None:
        from ..config import load_settings

        backend = load_settings().get("sentiment_backend", "finbert")
    backend = str(backend).lower()
    return backend if backend in BACKENDS else "finbert"


def daily_sentiment(symbol: str, refresh: bool = True,
                    backend: str | None = None) -> pd.Series:
    """Ø-Sentiment je Kalendertag (Index: Datum, tz-frei). Leer, wenn kein Archiv."""
    scored = _scored_headlines(symbol, refresh=refresh, backend=resolve_backend(backend))
    if scored.empty:
        return pd.Series(dtype=float)
    days = scored["published"].dt.tz_convert("UTC").dt.date
    daily = scored.groupby(days)["sentiment"].mean()
    daily.index = pd.to_datetime(daily.index)
    return daily.sort_index()


def current_sentiment(symbol: str, days: int = 7,
                      backend: str | None = None) -> float | None:
    """Ø-Sentiment der letzten `days` Tage; None, wenn keine Meldungen."""
    daily = daily_sentiment(symbol, backend=backend)
    if daily.empty:
        return None
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
    window = daily[daily.index >= cutoff]
    return float(window.mean()) if len(window) else None


def recent_scored(symbol: str, days: int = 7, backend: str | None = None) -> pd.DataFrame:
    """Gescorte Schlagzeilen der letzten `days` Tage (für Begründungen im Log)."""
    scored = _scored_headlines(symbol, refresh=False, backend=resolve_backend(backend))
    if scored.empty:
        return scored
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
    return scored[scored["published"] >= cutoff].sort_values("sentiment")


def _subject(symbol: str) -> str:
    """Symbol + Firmenname aus dem Hub (falls vorhanden) als Bezug für Claude."""
    try:
        import sqlite3

        from ..data.hub import HUB_PATH

        conn = sqlite3.connect(f"file:{HUB_PATH}?mode=ro", uri=True)
        row = conn.execute("SELECT name FROM companies WHERE symbol = ?", (symbol,)).fetchone()
        conn.close()
        if row and row[0]:
            return f"{row[0]} ({symbol})"
    except Exception:
        pass
    return symbol


def _score(todo_titles: list[str], symbol: str, backend: str) -> pd.DataFrame:
    """Scores (+ bei Claude Label/Begründung) für neue Schlagzeilen."""
    if backend == "claude":
        from ..config import load_settings
        from .claude import classify_headlines

        model = load_settings().get("claude_model") or None
        results = classify_headlines(todo_titles, subject=_subject(symbol), model=model)
        return pd.DataFrame({
            "title": todo_titles,
            "sentiment": [r["score"] for r in results],
            "label": [r["label"] for r in results],
            "reason": [r["reason"] for r in results],
        })
    from .finbert import score_headlines

    return pd.DataFrame({"title": todo_titles, "sentiment": score_headlines(todo_titles)})


def _scored_headlines(symbol: str, refresh: bool, backend: str = "finbert") -> pd.DataFrame:
    """Archiv-Schlagzeilen mit Sentiment-Spalte; scored nur Neues."""
    from ..data.news import NEWS_CACHE_DIR, load_news

    if refresh:
        try:
            load_news(symbol)  # holt frische Meldungen ins Archiv
        except Exception:
            pass  # Quelle down — Archivstand reicht

    archive_file = NEWS_CACHE_DIR / f"{symbol}.csv"
    if not archive_file.exists():
        return pd.DataFrame()
    archive = pd.read_csv(archive_file)
    if archive.empty:
        return pd.DataFrame()
    archive["published"] = pd.to_datetime(archive["published"], utc=True)

    cache_file = SCORE_CACHE_DIRS[backend] / f"{symbol}.csv"
    cached = pd.DataFrame(columns=["title", "sentiment"])
    if cache_file.exists():
        cached = pd.read_csv(cache_file)

    merged = archive.merge(cached.drop_duplicates("title"), on="title", how="left")
    todo = merged[merged["sentiment"].isna()]
    if not todo.empty:
        try:
            new = _score(list(todo["title"]), symbol, backend)
        except Exception as exc:
            if backend == "finbert":
                raise
            log.warning("%s: Claude-Sentiment fehlgeschlagen (%s) — Fallback FinBERT",
                        symbol, exc)
            return _scored_headlines(symbol, refresh=False, backend="finbert")
        cached = pd.concat([cached, new], ignore_index=True).drop_duplicates("title", keep="last")
        SCORE_CACHE_DIRS[backend].mkdir(parents=True, exist_ok=True)
        cached.to_csv(cache_file, index=False)
        merged = archive.merge(cached, on="title", how="left")

    last_backend[symbol] = backend
    return merged.dropna(subset=["sentiment"])
