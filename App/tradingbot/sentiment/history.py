"""Sentiment-Historie je Symbol: Schlagzeilen aus dem News-Archiv scoren.

Scores werden je Symbol gecacht (data_cache/news_scores/{symbol}.csv),
FinBERT rechnet also nur neue, noch ungescorte Schlagzeilen. Ergebnis
ist eine Tages-Serie: Ø Sentiment aller Meldungen des Tages.

Wichtig für Backtests: das News-Archiv ist append-only mit Original-
Zeitstempeln — eine Meldung wirkt erst ab dem Tag, an dem sie bekannt
war (kein Look-Ahead). Die Historie ist so lang, wie das Archiv gepflegt
wurde; davor gibt es schlicht kein Sentiment (= Gate inaktiv).
"""

from __future__ import annotations

import pandas as pd

from ..config import DATA_CACHE_DIR

SCORE_CACHE_DIR = DATA_CACHE_DIR / "news_scores"


def daily_sentiment(symbol: str, refresh: bool = True) -> pd.Series:
    """Ø-Sentiment je Kalendertag (Index: Datum, tz-frei). Leer, wenn kein Archiv."""
    scored = _scored_headlines(symbol, refresh=refresh)
    if scored.empty:
        return pd.Series(dtype=float)
    days = scored["published"].dt.tz_convert("UTC").dt.date
    daily = scored.groupby(days)["sentiment"].mean()
    daily.index = pd.to_datetime(daily.index)
    return daily.sort_index()


def current_sentiment(symbol: str, days: int = 7) -> float | None:
    """Ø-Sentiment der letzten `days` Tage; None, wenn keine Meldungen."""
    daily = daily_sentiment(symbol)
    if daily.empty:
        return None
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
    window = daily[daily.index >= cutoff]
    return float(window.mean()) if len(window) else None


def _scored_headlines(symbol: str, refresh: bool) -> pd.DataFrame:
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

    cache_file = SCORE_CACHE_DIR / f"{symbol}.csv"
    cached = pd.DataFrame(columns=["title", "sentiment"])
    if cache_file.exists():
        cached = pd.read_csv(cache_file)

    merged = archive.merge(cached.drop_duplicates("title"), on="title", how="left")
    todo = merged[merged["sentiment"].isna()]
    if not todo.empty:
        from .finbert import score_headlines

        merged.loc[todo.index, "sentiment"] = score_headlines(list(todo["title"]))
        SCORE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        merged[["title", "sentiment"]].to_csv(cache_file, index=False)

    return merged.dropna(subset=["sentiment"])
