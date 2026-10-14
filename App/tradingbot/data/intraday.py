"""Intraday-Kurse (Minuten-/Stundenkerzen) mit wachsendem Archiv.

Das Grundproblem: kostenlose Quellen liefern nur BEGRENZTE Intraday-
Historie (Yahoo: ~60 Tage bei 5/15 Min, ~2 Jahre bei 1 Stunde; FMP-Free
und Tiingo-IEX: jeweils nur jüngere Abschnitte). Für seriöse Intraday-
Backtests über Jahre braucht es Bezahldaten (IBKR-Marktdaten, Polygon,
Databento).

Unser Ansatz wie beim News-Archiv: jeder Abruf wird in
data_cache/intraday/{symbol}_{freq}.csv GEMERGT (append, dedupliziert) —
die Historie wächst mit jedem Lauf über die Fenster der Gratis-Quellen
hinaus. Provider-Kette (alle optional, beste zuerst):

1. IBKR       — über den Broker (broker.fetch_bars), wenn verbunden
2. Yahoo      — ohne Key, größtes Gratis-Fenster
3. Tiingo IEX — kostenloser Key (TIINGO_API_KEY / Einstellungen)
4. FMP        — kostenloser Key (FMP_API_KEY / Einstellungen)

Alle liefern OHLCV mit tz-freiem Zeitindex.
"""

from __future__ import annotations

import pandas as pd
import requests

from ..config import DATA_CACHE_DIR, get_api_key

INTRADAY_CACHE_DIR = DATA_CACHE_DIR / "intraday"

# Engine-Intervall → (yfinance-Intervall, max. yfinance-Zeitraum,
#                     FMP-Pfad, Tiingo-resampleFreq)
FREQ_MAP = {
    "5 mins":  ("5m",  "60d",  "5min",  "5min"),
    "15 mins": ("15m", "60d",  "15min", "15min"),
    "1 hour":  ("60m", "730d", "1hour", "1hour"),
}


def load_intraday(symbol: str, interval: str, broker=None) -> pd.DataFrame:
    """Intraday-Kerzen: Archiv + frische Daten aller verfügbaren Quellen."""
    if interval not in FREQ_MAP:
        raise ValueError(f"Unbekanntes Intraday-Intervall {interval!r} "
                         f"(bekannt: {', '.join(FREQ_MAP)})")
    yf_int, yf_period, fmp_path, tiingo_freq = FREQ_MAP[interval]

    frames = [_read_cache(symbol, yf_int)]

    # 1) IBKR, falls verbunden (beste Qualität, auch für den Live-Betrieb)
    if broker is not None and getattr(broker, "connected", False):
        try:
            frames.append(broker.fetch_bars(symbol, duration="30 D", bar_size=interval))
        except Exception:
            pass

    # 2) Yahoo (größtes Gratis-Fenster)
    try:
        frames.append(_fetch_yahoo(symbol, yf_int, yf_period))
    except Exception:
        pass

    # 3) Tiingo IEX (nur US-Titel)
    try:
        frames.append(_fetch_tiingo(symbol, tiingo_freq))
    except Exception:
        pass

    # 4) FMP (nur, wenn noch nichts brauchbar — Request-Budget schonen)
    if sum(len(f) for f in frames) == 0:
        try:
            frames.append(_fetch_fmp(symbol, fmp_path))
        except Exception:
            pass

    merged = pd.concat([f for f in frames if f is not None and not f.empty])
    if merged.empty:
        raise ValueError(f"Keine Intraday-Daten für {symbol} ({interval}) — "
                         f"Quellen nicht erreichbar oder Symbol nicht abgedeckt")
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    _write_cache(symbol, yf_int, merged)
    return merged


# ------------------------------------------------------------------ Cache

def _cache_file(symbol: str, freq: str):
    return INTRADAY_CACHE_DIR / f"{symbol}_{freq}.csv"


def _read_cache(symbol: str, freq: str) -> pd.DataFrame:
    f = _cache_file(symbol, freq)
    if not f.exists():
        return pd.DataFrame()
    return pd.read_csv(f, index_col=0, parse_dates=True)


def _write_cache(symbol: str, freq: str, df: pd.DataFrame) -> None:
    INTRADAY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(_cache_file(symbol, freq))


# --------------------------------------------------------------- Provider

def _fetch_yahoo(symbol: str, yf_interval: str, period: str) -> pd.DataFrame:
    import yfinance as yf

    df = yf.download(symbol, interval=yf_interval, period=period,
                     auto_adjust=False, progress=False)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def _fetch_tiingo(symbol: str, freq: str) -> pd.DataFrame:
    key = get_api_key("tiingo")
    if not key:
        return pd.DataFrame()
    start = (pd.Timestamp.today() - pd.Timedelta(days=30)).date().isoformat()
    resp = requests.get(
        f"https://api.tiingo.com/iex/{symbol}/prices",
        params={"startDate": start, "resampleFreq": freq,
                "columns": "open,high,low,close,volume", "token": key},
        timeout=30)
    if resp.status_code == 404:
        return pd.DataFrame()
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.set_index("date")[["open", "high", "low", "close", "volume"]]
    df.columns = ["Open", "High", "Low", "Close", "Volume"]
    return df.sort_index()


def _fetch_fmp(symbol: str, path: str) -> pd.DataFrame:
    key = get_api_key("fmp")
    if not key:
        return pd.DataFrame()
    from .fmpapi import fmp_get

    rows = fmp_get(f"historical-chart/{path}?symbol={symbol}",
                   f"historical-chart/{path}/{symbol}", {}, key)
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")[["open", "high", "low", "close", "volume"]]
    df.columns = ["Open", "High", "Low", "Close", "Volume"]
    return df.sort_index()
