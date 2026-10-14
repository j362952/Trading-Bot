"""Nachrichten je Aktie (Quelle: Yahoo Finance) mit Append-only-Archiv.

Yahoo liefert nur die jüngsten ~10-20 Meldungen und kein Archiv. Deshalb
archiviert jeder Abruf die Schlagzeilen in data_cache/news/{symbol}.csv —
mit Zeitstempel, dedupliziert, nie überschrieben. So wächst mit jedem Lauf
eine eigene News-Historie, die spätere Backtests ohne Look-Ahead-Bias
erlaubt (man weiß, WANN eine Meldung bekannt wurde).
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

from ..config import DATA_CACHE_DIR

NEWS_CACHE_DIR = DATA_CACHE_DIR / "news"

COLUMNS = ["published", "title", "publisher", "link"]


def load_news(symbol: str, max_age_days: int = 14) -> pd.DataFrame:
    """Frische News holen, ins Archiv mergen, die letzten max_age_days liefern."""
    fresh = _fetch_yahoo_news(symbol)
    archive = _merge_into_archive(symbol, fresh)
    if archive.empty:
        return archive
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=max_age_days)
    return archive[archive["published"] >= cutoff].reset_index(drop=True)


def _fetch_yahoo_news(symbol: str) -> pd.DataFrame:
    try:
        items = yf.Ticker(symbol).news or []
    except Exception:
        items = []
    rows = [row for item in items if (row := _normalize(item)) is not None]
    return pd.DataFrame(rows, columns=COLUMNS)


def _normalize(item: dict) -> dict | None:
    """Bringt beide yfinance-News-Formate (alt: flach, neu: unter 'content')
    auf ein einheitliches Schema."""
    content = item.get("content") if isinstance(item.get("content"), dict) else item

    title = content.get("title")
    if not title:
        return None

    timestamp = content.get("pubDate") or item.get("providerPublishTime")
    if timestamp is None:
        return None
    if isinstance(timestamp, (int, float)):
        published = pd.Timestamp(timestamp, unit="s", tz="UTC")
    else:
        published = pd.Timestamp(timestamp)
        published = published.tz_localize("UTC") if published.tz is None else published.tz_convert("UTC")

    provider = content.get("provider")
    publisher = provider.get("displayName") if isinstance(provider, dict) else item.get("publisher", "")

    url = content.get("canonicalUrl")
    link = url.get("url") if isinstance(url, dict) else item.get("link", "")

    return {"published": published, "title": str(title).strip(), "publisher": publisher or "", "link": link or ""}


def _merge_into_archive(symbol: str, fresh: pd.DataFrame) -> pd.DataFrame:
    archive_file = NEWS_CACHE_DIR / f"{symbol}.csv"

    old = pd.DataFrame(columns=COLUMNS)
    if archive_file.exists():
        old = pd.read_csv(archive_file)
        old["published"] = pd.to_datetime(old["published"], utc=True)

    merged = pd.concat([old, fresh], ignore_index=True)
    if merged.empty:
        return merged
    merged = (
        merged.drop_duplicates(subset=["title"])
        .sort_values("published", ascending=False)
        .reset_index(drop=True)
    )

    NEWS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    merged.to_csv(archive_file, index=False)
    return merged
