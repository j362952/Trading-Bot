"""SQLite-Datenbank: Quartals-Fundamentaldaten, Markt-Snapshots, Score-Läufe.

Eine Datei (data/screener.db), vier Kern-Tabellen:

- companies   — Stammdaten je Aktie
- quarterly   — eine Zeile je Aktie und Fiskalquartal (wie reportet);
                Quelle je Zeile gespeichert, FMP-Daten überschreiben
                Yahoo-Daten, nie umgekehrt (FMP ist detaillierter/tiefer)
- snapshots   — Preis/Marktkapitalisierung je Aktie und Tag
- score_runs / scores — Ergebnis jedes Analyse-Laufs (Historie bleibt erhalten)
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

import pandas as pd

from .config import DB_PATH, DATA_DIR

# Normalisiertes Quartals-Schema — jeder Provider liefert genau diese Spalten
QUARTERLY_FIELDS = [
    "revenue", "gross_profit", "operating_income", "net_income", "ebitda", "eps",
    "total_assets", "total_equity", "total_debt", "cash",
    "current_assets", "current_liabilities", "shares_outstanding",
    "operating_cashflow", "capex", "free_cashflow",
]

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS companies (
    symbol TEXT PRIMARY KEY,
    name TEXT, sector TEXT, industry TEXT,
    currency TEXT, financial_currency TEXT,
    fmp_backfilled INTEGER DEFAULT 0,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS quarterly (
    symbol TEXT NOT NULL,
    fiscal_date TEXT NOT NULL,
    source TEXT NOT NULL,
    {", ".join(f"{f} REAL" for f in QUARTERLY_FIELDS)},
    fetched_at TEXT,
    PRIMARY KEY (symbol, fiscal_date)
);
CREATE TABLE IF NOT EXISTS snapshots (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    price REAL, market_cap REAL,
    PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS score_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    universe TEXT NOT NULL,
    run_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
    run_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    rank INTEGER, score REAL, value REAL, quality REAL, growth REAL, coverage REAL,
    PRIMARY KEY (run_id, symbol)
);
CREATE INDEX IF NOT EXISTS idx_quarterly_symbol ON quarterly(symbol, fiscal_date);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(_SCHEMA)
    return conn


# ---------------------------------------------------------------- companies

def upsert_company(conn: sqlite3.Connection, symbol: str, **fields) -> None:
    """Legt die Aktie an bzw. aktualisiert nur die übergebenen Felder."""
    allowed = {"name", "sector", "industry", "currency", "financial_currency", "fmp_backfilled"}
    fields = {k: v for k, v in fields.items() if k in allowed and v not in (None, "")}
    conn.execute("INSERT OR IGNORE INTO companies(symbol, updated_at) VALUES (?, ?)", (symbol, _now()))
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE companies SET {sets}, updated_at = ? WHERE symbol = ?",
            [*fields.values(), _now(), symbol],
        )


def company_flags(conn: sqlite3.Connection, symbol: str) -> dict:
    row = conn.execute(
        "SELECT fmp_backfilled FROM companies WHERE symbol = ?", (symbol,)
    ).fetchone()
    return {"fmp_backfilled": bool(row[0])} if row else {"fmp_backfilled": False}


# ---------------------------------------------------------------- quarterly

def upsert_quarterly(conn: sqlite3.Connection, symbol: str, df: pd.DataFrame, source: str) -> int:
    """Schreibt normalisierte Quartalszeilen. FMP überschreibt Yahoo, nie umgekehrt.

    df: Index = Fiskalquartals-Enddatum (datetime oder ISO-String),
        Spalten ⊆ QUARTERLY_FIELDS.
    """
    if df is None or df.empty:
        return 0
    written = 0
    cols = ["symbol", "fiscal_date", "source", *QUARTERLY_FIELDS, "fetched_at"]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{f} = excluded.{f}" for f in [*QUARTERLY_FIELDS, "source", "fetched_at"])
    sql = (
        f"INSERT INTO quarterly ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(symbol, fiscal_date) DO UPDATE SET {updates} "
        # bestehende FMP-Zeile nur durch FMP ersetzen
        f"WHERE excluded.source = 'fmp' OR quarterly.source != 'fmp'"
    )
    for idx, row in df.iterrows():
        fiscal = pd.Timestamp(idx).date().isoformat()
        values = [None if pd.isna(v) else float(v) for v in (row.get(f) for f in QUARTERLY_FIELDS)]
        if all(v is None for v in values):
            continue
        conn.execute(sql, [symbol, fiscal, source, *values, _now()])
        written += 1
    conn.commit()
    return written


def last_fetched(conn: sqlite3.Connection, symbol: str) -> datetime | None:
    row = conn.execute(
        "SELECT MAX(fetched_at) FROM quarterly WHERE symbol = ?", (symbol,)
    ).fetchone()
    if not row or not row[0]:
        return None
    return datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def quarterly_history(conn: sqlite3.Connection, symbols: list[str]) -> pd.DataFrame:
    """Alle Quartalszeilen der Symbole, aufsteigend nach fiscal_date."""
    if not symbols:
        return pd.DataFrame()
    marks = ", ".join("?" for _ in symbols)
    df = pd.read_sql_query(
        f"SELECT * FROM quarterly WHERE symbol IN ({marks}) ORDER BY symbol, fiscal_date",
        conn, params=symbols, parse_dates=["fiscal_date"],
    )
    return df


# ---------------------------------------------------------------- snapshots

def save_snapshots(conn: sqlite3.Connection, prices: dict[str, float], mcaps: dict[str, float]) -> None:
    today = date.today().isoformat()
    for symbol, price in prices.items():
        conn.execute(
            "INSERT INTO snapshots(symbol, date, price, market_cap) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(symbol, date) DO UPDATE SET price = excluded.price, "
            "market_cap = excluded.market_cap",
            (symbol, today, price, mcaps.get(symbol)),
        )
    conn.commit()


def latest_snapshots(conn: sqlite3.Connection, symbols: list[str]) -> pd.DataFrame:
    """Jüngster Snapshot je Symbol (Index: symbol; Spalten: date, price, market_cap)."""
    if not symbols:
        return pd.DataFrame()
    marks = ", ".join("?" for _ in symbols)
    df = pd.read_sql_query(
        f"""SELECT s.symbol, s.date, s.price, s.market_cap FROM snapshots s
            JOIN (SELECT symbol, MAX(date) AS d FROM snapshots
                  WHERE symbol IN ({marks}) GROUP BY symbol) j
            ON s.symbol = j.symbol AND s.date = j.d""",
        conn, params=symbols,
    )
    return df.set_index("symbol")


# ---------------------------------------------------------------- scores

def save_score_run(conn: sqlite3.Connection, universe: str, result: pd.DataFrame) -> int:
    cur = conn.execute("INSERT INTO score_runs(universe, run_at) VALUES (?, ?)", (universe, _now()))
    run_id = cur.lastrowid
    for rank, (symbol, row) in enumerate(result.iterrows(), 1):
        conn.execute(
            "INSERT INTO scores(run_id, symbol, rank, score, value, quality, growth, coverage) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, symbol, rank, row.get("score"), row.get("value"),
             row.get("quality"), row.get("growth"), row.get("coverage")),
        )
    conn.commit()
    return run_id
