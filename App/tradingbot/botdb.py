"""Bot-Datenbank (SQLite): lückenloses Protokoll des Bot-Betriebs.

- events   — jede Entscheidung mit Begründung ("MSFT: Einstieg blockiert,
             Sentiment -0.45") — nachvollziehen können, WARUM der Bot
             etwas (nicht) getan hat
- orders   — jede ausgeführte Order mit Preis und Gebühren
- equity   — Kapitalverlauf je Zyklus (der echte Track-Record)
- stops    — aktive Trailing-Stop-Level (überleben Neustarts)
- meta     — Kleinzeug wie Peak-Equity für den Kill-Switch
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pandas as pd

from .config import DATA_CACHE_DIR

DB_PATH = DATA_CACHE_DIR / "bot.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL, symbol TEXT NOT NULL,
    quantity REAL NOT NULL, price REAL NOT NULL,
    commission REAL, reason TEXT
);
CREATE TABLE IF NOT EXISTS equity (
    time TEXT PRIMARY KEY, equity REAL NOT NULL, cash REAL
);
CREATE TABLE IF NOT EXISTS stops (
    symbol TEXT PRIMARY KEY, level REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY, value TEXT
);
"""


def connect() -> sqlite3.Connection:
    DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log_event(conn, message: str, level: str = "info") -> None:
    conn.execute("INSERT INTO events(time, level, message) VALUES (?, ?, ?)",
                 (_now(), level, message))
    conn.commit()


def log_order(conn, symbol: str, quantity: float, price: float,
              commission: float, reason: str) -> None:
    conn.execute(
        "INSERT INTO orders(time, symbol, quantity, price, commission, reason) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_now(), symbol, quantity, price, commission, reason))
    conn.commit()


def log_equity(conn, equity: float, cash: float) -> None:
    conn.execute("INSERT OR REPLACE INTO equity(time, equity, cash) VALUES (?, ?, ?)",
                 (_now(), equity, cash))
    conn.commit()


def recent_events(conn, limit: int = 200) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT time, level, message FROM events ORDER BY id DESC LIMIT ?",
        conn, params=(limit,))


def recent_orders(conn, limit: int = 100) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT time, symbol, quantity, price, commission, reason "
        "FROM orders ORDER BY id DESC LIMIT ?", conn, params=(limit,))


def equity_curve(conn) -> pd.DataFrame:
    return pd.read_sql_query("SELECT time, equity, cash FROM equity ORDER BY time",
                             conn, parse_dates=["time"])


# ------------------------------------------------------------- Stops & Meta

def get_stops(conn) -> dict[str, float]:
    return dict(conn.execute("SELECT symbol, level FROM stops").fetchall())


def set_stop(conn, symbol: str, level: float) -> None:
    conn.execute("INSERT OR REPLACE INTO stops(symbol, level) VALUES (?, ?)",
                 (symbol, level))
    conn.commit()


def clear_stop(conn, symbol: str) -> None:
    conn.execute("DELETE FROM stops WHERE symbol = ?", (symbol,))
    conn.commit()


def get_meta(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(conn, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))
    conn.commit()
