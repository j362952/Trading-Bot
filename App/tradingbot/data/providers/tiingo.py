"""Tiingo (tiingo.com): solide kostenlose Alternative zu Yahoo.

Braucht einen kostenlosen API-Key (Konto auf tiingo.com anlegen, Key unter
Account → API). Den Key als Umgebungsvariable TIINGO_API_KEY setzen:

    setx TIINGO_API_KEY "dein-key"     (PowerShell, wirkt ab der nächsten Shell)

Ohne Key wird dieser Provider einfach übersprungen. Free-Tier: 1000
Abrufe/Tag. Kurse sind split- und dividendenbereinigt (adj*-Felder),
also konsistent mit Yahoo. Abdeckung: vor allem US-Titel.
"""

from __future__ import annotations

import os
from datetime import date

import pandas as pd
import requests


def fetch(symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
    api_key = os.environ.get("TIINGO_API_KEY")
    if not api_key:
        return pd.DataFrame()  # kein Key gesetzt → Provider überspringen

    end = end or date.today().isoformat()
    resp = requests.get(
        f"https://api.tiingo.com/tiingo/daily/{symbol}/prices",
        params={"startDate": start, "endDate": end, "token": api_key},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    if resp.status_code == 404:
        return pd.DataFrame()  # Symbol bei Tiingo unbekannt
    resp.raise_for_status()

    rows = resp.json()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.set_index("Date")[["adjOpen", "adjHigh", "adjLow", "adjClose", "adjVolume"]]
    df.columns = ["Open", "High", "Low", "Close", "Volume"]
    return df.sort_index()
