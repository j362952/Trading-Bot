"""Stooq (stooq.com): kostenlose Tageskurse per CSV-Download, kein API-Key.

Fallback-Quelle, wenn Yahoo klemmt. Einschränkung: Kurse sind splitbereinigt,
aber NICHT dividendenbereinigt — Backtests auf Stooq-Daten unterschätzen die
Rendite von Dividendenzahlern etwas.
"""

from __future__ import annotations

from datetime import date
from io import StringIO

import pandas as pd
import requests

# Yahoo-Suffix → Stooq-Suffix (nur die verlässlich gemappten Börsen)
_SUFFIX_MAP = {".DE": ".de", ".L": ".uk", ".T": ".jp"}


def _to_stooq_symbol(symbol: str) -> str:
    for yahoo_suffix, stooq_suffix in _SUFFIX_MAP.items():
        if symbol.endswith(yahoo_suffix):
            return symbol.removesuffix(yahoo_suffix).lower() + stooq_suffix
    if "." not in symbol and "-" not in symbol:
        return symbol.lower() + ".us"  # US-Aktien tragen bei Stooq .us
    return symbol.lower()


def fetch(symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
    end = end or date.today().isoformat()
    url = (
        f"https://stooq.com/q/d/l/?s={_to_stooq_symbol(symbol)}&i=d"
        f"&d1={start.replace('-', '')}&d2={end.replace('-', '')}"
    )
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()

    try:
        df = pd.read_csv(StringIO(resp.text), index_col=0, parse_dates=True)
    except Exception:
        return pd.DataFrame()  # Stooq antwortet bei unbekannten Symbolen mit "No data"
    if df.empty or "Close" not in df.columns:
        return pd.DataFrame()

    if "Volume" not in df.columns:
        df["Volume"] = 0
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    df.index.name = "Date"
    return df
