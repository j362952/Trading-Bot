"""Daten-Hub (SQLite data_cache/hub.db): alle Datenkategorien auf EINEM
Zeitstrahl, wie in GUI_KONZEPT.md beschrieben.

Kategorien und ihre Speicher:

| Kategorie                          | Speicher                          |
|------------------------------------|-----------------------------------|
| Fundamentaldaten (Quartale)        | hub.db `fundamentals` + `companies` |
| Aktuelle Preise (Batch-Snapshots)  | hub.db `quotes`                   |
| Earnings-Termine (voraus!)         | hub.db `earnings_calendar`        |
| Makro-Reihen (FRED)                | hub.db `macro_series`             |
| Ereignis-Kalender (Fed/CPI/NFP)    | hub.db `events`                   |
| Corporate Actions                  | hub.db `corporate_actions`        |
| Index-Zugehörigkeit (Historie)     | hub.db `universe_members`         |
| Screener-Score-Läufe               | hub.db `score_runs` + `scores`    |
| Datenqualitäts-Metadaten           | hub.db `fetch_log` + `price_meta` |
| Historische Kurse (EOD)            | data_cache/prices/*.csv (registriert) |
| Intraday-Archiv                    | data_cache/intraday/*.csv (registriert) |
| News + Sentiment                   | data_cache/news*/ (registriert)   |
| Trades/Equity/Entscheidungen       | bot.db (bestehend)                |

Bewusste Abweichung vom Konzept: die 642 MB EOD-Kurshistorie wird NICHT
in SQLite dupliziert — der Hub REGISTRIERT diese Bestände (price_meta,
Coverage-Abfragen) und bleibt damit die eine Sicht auf alle Kategorien,
ohne den bewährten, schnellen CSV-Kurs-Cache anzufassen. Gleiches gilt
für das append-only News-Archiv (Look-Ahead-Schutz hängt an genau
diesen Dateien).

Die Migration (MarketScreener/data/screener.db → hub.db) läuft beim
ersten connect() automatisch und ist idempotent.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import DATA_CACHE_DIR, PROJECT_ROOT

HUB_PATH = DATA_CACHE_DIR / "hub.db"
# alte Screener-DB (Migrationsquelle): archivierter Ort, dann Alt-Standort
_LEGACY_CANDIDATES = [
    PROJECT_ROOT.parent / "_archiv" / "MarketScreener" / "data" / "screener.db",
    PROJECT_ROOT.parent / "MarketScreener" / "data" / "screener.db",
]
LEGACY_SCREENER_DB = next((p for p in _LEGACY_CANDIDATES if p.exists()),
                          _LEGACY_CANDIDATES[0])

# Normalisiertes Quartals-Schema (identisch zum bisherigen Screener-Schema,
# damit die Migration 1:1 ist und die Provider unverändert liefern können)
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
CREATE TABLE IF NOT EXISTS fundamentals (
    symbol TEXT NOT NULL,
    fiscal_date TEXT NOT NULL,
    source TEXT NOT NULL,
    {", ".join(f"{f} REAL" for f in QUARTERLY_FIELDS)},
    fetched_at TEXT,
    PRIMARY KEY (symbol, fiscal_date)
);
CREATE INDEX IF NOT EXISTS idx_fund_symbol ON fundamentals(symbol, fiscal_date);
CREATE TABLE IF NOT EXISTS quotes (
    symbol TEXT NOT NULL, date TEXT NOT NULL,
    price REAL, market_cap REAL,
    PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS earnings_calendar (
    symbol TEXT NOT NULL, date TEXT NOT NULL,
    time TEXT, eps_estimate REAL, eps_actual REAL, revenue_estimate REAL,
    fetched_at TEXT,
    PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS macro_series (
    series TEXT NOT NULL, date TEXT NOT NULL,
    value REAL, source TEXT,
    PRIMARY KEY (series, date)
);
CREATE TABLE IF NOT EXISTS events (
    date TEXT NOT NULL, country TEXT, event TEXT NOT NULL, impact TEXT,
    fetched_at TEXT,
    PRIMARY KEY (date, event)
);
CREATE TABLE IF NOT EXISTS corporate_actions (
    symbol TEXT NOT NULL, date TEXT NOT NULL,
    action TEXT NOT NULL, value REAL,
    PRIMARY KEY (symbol, date, action)
);
CREATE TABLE IF NOT EXISTS universe_members (
    universe TEXT NOT NULL, month TEXT NOT NULL, symbol TEXT NOT NULL,
    name TEXT, sector TEXT,
    PRIMARY KEY (universe, month, symbol)
);
CREATE TABLE IF NOT EXISTS score_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    algo TEXT NOT NULL, universe TEXT NOT NULL, run_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
    run_id INTEGER NOT NULL, symbol TEXT NOT NULL,
    rank INTEGER, score REAL, detail TEXT,
    PRIMARY KEY (run_id, symbol)
);
CREATE TABLE IF NOT EXISTS price_meta (
    symbol TEXT PRIMARY KEY,
    first_date TEXT, last_date TEXT, rows INTEGER, mtime REAL
);
CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL, category TEXT NOT NULL, key TEXT,
    source TEXT, ok INTEGER NOT NULL, message TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(migrate: bool = True) -> sqlite3.Connection:
    DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(HUB_PATH)
    conn.executescript(_SCHEMA)
    if migrate:
        migrate_legacy(conn)
    return conn


# ------------------------------------------------------------- Migration

def migrate_legacy(conn: sqlite3.Connection) -> dict:
    """Screener-DB (companies/quarterly/snapshots/scores) in den Hub holen.

    Idempotent: bereits migrierte Bestände werden per Upsert überschrieben,
    der Abschluss wird in meta vermerkt (Migration läuft nur einmal;
    danach ist der Hub die maßgebliche DB und der Screener-Teil der GUI
    schreibt direkt hierher).
    """
    done = conn.execute("SELECT value FROM meta WHERE key='screener_migrated'").fetchone()
    if done or not LEGACY_SCREENER_DB.exists():
        return {"migrated": False}

    src = sqlite3.connect(LEGACY_SCREENER_DB)
    stats = {}
    try:
        rows = src.execute("SELECT symbol, name, sector, industry, currency, "
                           "financial_currency, fmp_backfilled, updated_at "
                           "FROM companies").fetchall()
        conn.executemany(
            "INSERT INTO companies(symbol, name, sector, industry, currency, "
            "financial_currency, fmp_backfilled, updated_at) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(symbol) DO NOTHING", rows)
        stats["companies"] = len(rows)

        cols = ["symbol", "fiscal_date", "source", *QUARTERLY_FIELDS, "fetched_at"]
        rows = src.execute(f"SELECT {', '.join(cols)} FROM quarterly").fetchall()
        conn.executemany(
            f"INSERT INTO fundamentals({', '.join(cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)}) "
            f"ON CONFLICT(symbol, fiscal_date) DO NOTHING", rows)
        stats["fundamentals"] = len(rows)

        rows = src.execute("SELECT symbol, date, price, market_cap FROM snapshots").fetchall()
        conn.executemany(
            "INSERT INTO quotes(symbol, date, price, market_cap) VALUES (?,?,?,?) "
            "ON CONFLICT(symbol, date) DO NOTHING", rows)
        stats["quotes"] = len(rows)

        # Score-Historie: alte Läufe unter dem Algo-Key 'value_score'
        for run_id, universe, run_at in src.execute(
                "SELECT id, universe, run_at FROM score_runs").fetchall():
            cur = conn.execute(
                "INSERT INTO score_runs(algo, universe, run_at) VALUES (?,?,?)",
                ("value_score", universe, run_at))
            new_id = cur.lastrowid
            old = src.execute(
                "SELECT symbol, rank, score, value, quality, growth, coverage "
                "FROM scores WHERE run_id = ?", (run_id,)).fetchall()
            conn.executemany(
                "INSERT INTO scores(run_id, symbol, rank, score, detail) "
                "VALUES (?,?,?,?,?) ON CONFLICT(run_id, symbol) DO NOTHING",
                [(new_id, s, r, sc,
                  f"value={v}, quality={q}, growth={g}, coverage={c}")
                 for s, r, sc, v, q, g, c in old])
        stats["score_runs"] = conn.execute("SELECT COUNT(*) FROM score_runs").fetchone()[0]
    finally:
        src.close()

    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('screener_migrated', ?)",
                 (_now(),))
    conn.commit()
    log_fetch(conn, "migration", "screener.db", "hub", True,
              f"Migriert: {stats}")
    return {"migrated": True, **stats}


# ------------------------------------------------------ API-Schnittstellen

# Alle Datenquellen der App an einem Ort: (Name, Log-Kennung, Key-Feld
# in den Einstellungen oder None, wofür sie liefert)
API_INTERFACES = [
    ("Yahoo Finance", "yahoo", None,
     "Kurse EOD + Intraday, Preis-Batch, News, Fundamentals-Fallback, Corporate Actions"),
    ("Financial Modeling Prep", "fmp", "fmp_api_key",
     "Fundamentals-Backfill (tiefe Historie), Earnings-Kalender, Ereignis-Kalender, Intraday-Fallback"),
    ("Tiingo", "tiingo", "tiingo_api_key",
     "Kurs-Fallback EOD, Intraday IEX (nur US-Titel)"),
    ("FRED (St. Louis Fed)", "fred", None,
     "Makro-Reihen: Zinsen, Zinskurven, Spreads, CPI, Arbeitsmarkt "
     "(Key optional — nutzt dann die offizielle API statt fredgraph)"),
    ("EZB Data Portal", "ecb", None,
     "Fallback für Europa-Reihen (Einlagenzins, HICP), ohne Key"),
    ("Stooq", "stooq", None,
     "Kurs-Fallback EOD (häufig durch Bot-Schutz blockiert)"),
    ("IBKR (TWS/Gateway)", "ibkr", None,
     "Broker für Orders; beste Kurs-/Intraday-Quelle, wenn verbunden"),
    ("Wikipedia / iShares / companiesmarketcap", "web", None,
     "Index-Universen (S&P 500, DAX, …), MSCI World, Global 2000"),
]


def api_status(conn) -> pd.DataFrame:
    """Eine Zeile je API-Schnittstelle: Konfiguration, letzte Aktivität
    (aus fetch_log + Provider-Nutzungszähler), Zweck — für die Daten-Seite."""
    from ..config import get_api_key, load_settings

    settings = load_settings()
    try:
        from .providers import USAGE as price_usage
    except Exception:
        price_usage = {}

    rows = []
    for name, tag, key_field, purpose in API_INTERFACES:
        last_ok = conn.execute(
            "SELECT MAX(time) FROM fetch_log WHERE ok=1 AND "
            "(source LIKE ? OR category = ?)", (f"%{tag}%", tag)).fetchone()[0]
        last_fail = conn.execute(
            "SELECT MAX(time) FROM fetch_log WHERE ok=0 AND "
            "(source LIKE ? OR category = ?)", (f"%{tag}%", tag)).fetchone()[0]

        if key_field:
            config = ("Key hinterlegt" if get_api_key(key_field.split("_")[0])
                      else "KEIN Key (Zahnrad → API-Keys)")
        elif tag == "ibkr":
            config = ("als Broker gewählt" if settings.get("broker") == "ibkr"
                      else "nicht gewählt (Broker: Simulation)")
        else:
            config = "kein Key nötig"

        session = price_usage.get(tag, 0)
        rows.append({
            "schnittstelle": name,
            "konfig": config,
            "letzter_ok": (last_ok or "")[:16].replace("T", " "),
            "letzter_fehler": (last_fail or "")[:16].replace("T", " "),
            "sitzung": f"{session} Kursabrufe" if session else "",
            "zweck": purpose,
        })
    return pd.DataFrame(rows)


# -------------------------------------------------------------- fetch_log

def log_fetch(conn, category: str, key: str, source: str, ok: bool, message: str = "") -> None:
    conn.execute("INSERT INTO fetch_log(time, category, key, source, ok, message) "
                 "VALUES (?,?,?,?,?,?)",
                 (_now(), category, key, source, int(ok), message))
    conn.commit()


def recent_fetch_errors(conn, limit: int = 50) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT time, category, key, source, message FROM fetch_log "
        "WHERE ok = 0 ORDER BY id DESC LIMIT ?", conn, params=(limit,))


# ---------------------------------------------------------- Fundamentals

def upsert_company(conn, symbol: str, **fields) -> None:
    allowed = {"name", "sector", "industry", "currency", "financial_currency", "fmp_backfilled"}
    fields = {k: v for k, v in fields.items() if k in allowed and v not in (None, "")}
    conn.execute("INSERT OR IGNORE INTO companies(symbol, updated_at) VALUES (?, ?)",
                 (symbol, _now()))
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE companies SET {sets}, updated_at = ? WHERE symbol = ?",
                     [*fields.values(), _now(), symbol])


def company_flags(conn, symbol: str) -> dict:
    row = conn.execute("SELECT fmp_backfilled FROM companies WHERE symbol = ?",
                       (symbol,)).fetchone()
    return {"fmp_backfilled": bool(row[0])} if row else {"fmp_backfilled": False}


def sector_map(conn) -> dict[str, str]:
    return dict(conn.execute(
        "SELECT symbol, sector FROM companies WHERE sector IS NOT NULL AND sector != ''"))


def upsert_quarterly(conn, symbol: str, df: pd.DataFrame, source: str) -> int:
    """Normalisierte Quartalszeilen schreiben. FMP überschreibt Yahoo, nie umgekehrt."""
    if df is None or df.empty:
        return 0
    written = 0
    cols = ["symbol", "fiscal_date", "source", *QUARTERLY_FIELDS, "fetched_at"]
    updates = ", ".join(f"{f} = excluded.{f}"
                        for f in [*QUARTERLY_FIELDS, "source", "fetched_at"])
    sql = (f"INSERT INTO fundamentals ({', '.join(cols)}) "
           f"VALUES ({', '.join('?' for _ in cols)}) "
           f"ON CONFLICT(symbol, fiscal_date) DO UPDATE SET {updates} "
           f"WHERE excluded.source = 'fmp' OR fundamentals.source != 'fmp'")
    for idx, row in df.iterrows():
        fiscal = pd.Timestamp(idx).date().isoformat()
        values = [None if pd.isna(v) else float(v)
                  for v in (row.get(f) for f in QUARTERLY_FIELDS)]
        if all(v is None for v in values):
            continue
        conn.execute(sql, [symbol, fiscal, source, *values, _now()])
        written += 1
    conn.commit()
    return written


def last_fetched(conn, symbol: str) -> datetime | None:
    row = conn.execute("SELECT MAX(fetched_at) FROM fundamentals WHERE symbol = ?",
                       (symbol,)).fetchone()
    if not row or not row[0]:
        return None
    return datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def quarterly_history(conn, symbols: list[str]) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()
    marks = ", ".join("?" for _ in symbols)
    return pd.read_sql_query(
        f"SELECT * FROM fundamentals WHERE symbol IN ({marks}) "
        f"ORDER BY symbol, fiscal_date",
        conn, params=list(symbols), parse_dates=["fiscal_date"])


# ---------------------------------------------------------------- Quotes

def save_quotes(conn, prices: dict[str, float], mcaps: dict[str, float]) -> None:
    today = pd.Timestamp.today().date().isoformat()
    conn.executemany(
        "INSERT INTO quotes(symbol, date, price, market_cap) VALUES (?,?,?,?) "
        "ON CONFLICT(symbol, date) DO UPDATE SET price = excluded.price, "
        "market_cap = excluded.market_cap",
        [(s, today, p, mcaps.get(s)) for s, p in prices.items()])
    conn.commit()


def latest_quotes(conn, symbols: list[str]) -> pd.DataFrame:
    """Jüngster Quote je Symbol (Index: symbol; Spalten: date, price, market_cap)."""
    if not symbols:
        return pd.DataFrame()
    marks = ", ".join("?" for _ in symbols)
    df = pd.read_sql_query(
        f"""SELECT q.symbol, q.date, q.price, q.market_cap FROM quotes q
            JOIN (SELECT symbol, MAX(date) AS d FROM quotes
                  WHERE symbol IN ({marks}) GROUP BY symbol) j
            ON q.symbol = j.symbol AND q.date = j.d""",
        conn, params=list(symbols))
    return df.set_index("symbol") if not df.empty else df


# ----------------------------------------------------------------- Makro

def save_macro_series(conn, series: str, data: pd.Series, source: str) -> int:
    rows = [(series, pd.Timestamp(d).date().isoformat(), float(v), source)
            for d, v in data.dropna().items()]
    conn.executemany(
        "INSERT INTO macro_series(series, date, value, source) VALUES (?,?,?,?) "
        "ON CONFLICT(series, date) DO UPDATE SET value = excluded.value", rows)
    conn.commit()
    return len(rows)


def load_macro_series(conn, series: str) -> pd.Series:
    df = pd.read_sql_query(
        "SELECT date, value FROM macro_series WHERE series = ? ORDER BY date",
        conn, params=(series,), parse_dates=["date"])
    return df.set_index("date")["value"] if not df.empty else pd.Series(dtype=float)


def macro_overview(conn) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT series, COUNT(*) AS punkte, MIN(date) AS von, MAX(date) AS bis, "
        "source AS quelle FROM macro_series GROUP BY series ORDER BY series", conn)


# ------------------------------------------------- Kalender & Aktionen

def save_earnings(conn, rows: list[dict]) -> int:
    conn.executemany(
        "INSERT INTO earnings_calendar(symbol, date, time, eps_estimate, eps_actual, "
        "revenue_estimate, fetched_at) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(symbol, date) DO UPDATE SET time = excluded.time, "
        "eps_estimate = excluded.eps_estimate, eps_actual = excluded.eps_actual, "
        "revenue_estimate = excluded.revenue_estimate, fetched_at = excluded.fetched_at",
        [(r["symbol"], r["date"], r.get("time"), r.get("eps_estimate"),
          r.get("eps_actual"), r.get("revenue_estimate"), _now()) for r in rows])
    conn.commit()
    return len(rows)


def upcoming_earnings(conn, symbols: list[str] | None = None, days: int = 30) -> pd.DataFrame:
    today = pd.Timestamp.today().date().isoformat()
    until = (pd.Timestamp.today() + pd.Timedelta(days=days)).date().isoformat()
    sql = ("SELECT symbol, date, time, eps_estimate FROM earnings_calendar "
           "WHERE date >= ? AND date <= ?")
    params: list = [today, until]
    if symbols:
        sql += f" AND symbol IN ({', '.join('?' for _ in symbols)})"
        params += list(symbols)
    return pd.read_sql_query(sql + " ORDER BY date", conn, params=params)


def save_events(conn, rows: list[dict]) -> int:
    conn.executemany(
        "INSERT INTO events(date, country, event, impact, fetched_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(date, event) DO UPDATE SET impact = excluded.impact, "
        "fetched_at = excluded.fetched_at",
        [(r["date"], r.get("country"), r["event"], r.get("impact"), _now())
         for r in rows])
    conn.commit()
    return len(rows)


def save_corporate_actions(conn, symbol: str, dividends: pd.Series, splits: pd.Series) -> int:
    rows = [(symbol, pd.Timestamp(d).date().isoformat(), "dividend", float(v))
            for d, v in dividends.dropna().items()]
    rows += [(symbol, pd.Timestamp(d).date().isoformat(), "split", float(v))
             for d, v in splits.dropna().items()]
    conn.executemany(
        "INSERT INTO corporate_actions(symbol, date, action, value) VALUES (?,?,?,?) "
        "ON CONFLICT(symbol, date, action) DO UPDATE SET value = excluded.value", rows)
    conn.commit()
    return len(rows)


# --------------------------------------------------- Universen-Historie

def snapshot_universe(conn, key: str, df: pd.DataFrame) -> int:
    """Aktuelle Mitgliederliste als Monats-Snapshot fortschreiben —
    baut über die Zeit die Index-Zugehörigkeits-Historie auf
    (gegen den Survivorship-Bias künftiger Backtests)."""
    month = pd.Timestamp.today().strftime("%Y-%m")
    conn.executemany(
        "INSERT INTO universe_members(universe, month, symbol, name, sector) "
        "VALUES (?,?,?,?,?) ON CONFLICT(universe, month, symbol) DO NOTHING",
        [(key, month, r["symbol"], str(r.get("name", "")), str(r.get("sector", "")))
         for _, r in df.iterrows()])
    conn.commit()
    return len(df)


# ------------------------------------------------------------ Score-Läufe

def save_score_run(conn, algo: str, universe: str, result: pd.DataFrame) -> int:
    """result: Index = symbol, Spalte 'score' + beliebige Detail-Spalten."""
    cur = conn.execute("INSERT INTO score_runs(algo, universe, run_at) VALUES (?,?,?)",
                       (algo, universe, _now()))
    run_id = cur.lastrowid
    detail_cols = [c for c in result.columns if c != "score"]
    for rank, (symbol, row) in enumerate(result.iterrows(), 1):
        detail = ", ".join(f"{c}={row[c]}" for c in detail_cols[:8])
        conn.execute(
            "INSERT INTO scores(run_id, symbol, rank, score, detail) VALUES (?,?,?,?,?)",
            (run_id, symbol, rank, float(row["score"]), detail))
    conn.commit()
    return run_id


def score_history(conn, symbol: str, algo: str | None = None) -> pd.DataFrame:
    sql = ("SELECT r.run_at, r.algo, r.universe, s.rank, s.score FROM scores s "
           "JOIN score_runs r ON r.id = s.run_id WHERE s.symbol = ?")
    params: list = [symbol]
    if algo:
        sql += " AND r.algo = ?"
        params.append(algo)
    return pd.read_sql_query(sql + " ORDER BY r.run_at", conn, params=params)


def list_score_runs(conn, limit: int = 30) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT id, algo, universe, run_at, "
        "(SELECT COUNT(*) FROM scores WHERE run_id = score_runs.id) AS titel "
        "FROM score_runs ORDER BY id DESC LIMIT ?", conn, params=(limit,))


def load_score_run(conn, run_id: int) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT symbol, rank, score, detail FROM scores WHERE run_id = ? ORDER BY rank",
        conn, params=(run_id,))


# ----------------------------------- Registrierte Datei-Bestände (Kurse …)

def refresh_price_meta(conn) -> int:
    """Kurs-Cache (CSV je Symbol) in die Metadaten-Tabelle spiegeln.
    Liest nur Kopf/Ende geänderter Dateien — kein Voll-Scan von 600 MB."""
    from .prices import PRICE_CACHE_DIR

    known = dict(conn.execute("SELECT symbol, mtime FROM price_meta").fetchall())
    updated = 0
    seen = set()
    for f in PRICE_CACHE_DIR.glob("*.csv") if PRICE_CACHE_DIR.exists() else []:
        seen.add(f.stem)
        mtime = f.stat().st_mtime
        if known.get(f.stem) == mtime:
            continue
        first, last, rows = _csv_range(f)
        conn.execute(
            "INSERT INTO price_meta(symbol, first_date, last_date, rows, mtime) "
            "VALUES (?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET "
            "first_date=excluded.first_date, last_date=excluded.last_date, "
            "rows=excluded.rows, mtime=excluded.mtime",
            (f.stem, first, last, rows, mtime))
        updated += 1
    stale = set(known) - seen
    if stale:
        conn.executemany("DELETE FROM price_meta WHERE symbol = ?",
                         [(s,) for s in stale])
    conn.commit()
    return updated


def _csv_range(path: Path) -> tuple[str | None, str | None, int]:
    """(erstes Datum, letztes Datum, Zeilenzahl) einer Kurs-CSV — effizient."""
    try:
        with open(path, "rb") as fh:
            fh.readline()  # Header
            first_line = fh.readline().decode("utf-8", "ignore")
            rows = 1 + sum(1 for _ in fh)
            fh.seek(max(0, path.stat().st_size - 300))
            last_line = fh.read().decode("utf-8", "ignore").strip().splitlines()[-1]
        first = first_line.split(",", 1)[0].strip() or None
        last = last_line.split(",", 1)[0].strip() or None
        return first, last, rows
    except Exception:
        return None, None, 0


def price_coverage(conn, refresh: bool = False) -> pd.DataFrame:
    if refresh:
        refresh_price_meta(conn)
    return pd.read_sql_query(
        "SELECT symbol, first_date, last_date, rows FROM price_meta ORDER BY symbol",
        conn)


def news_coverage() -> pd.DataFrame:
    """Abdeckung des News-Archivs (Datei-basiert, append-only)."""
    from .news import NEWS_CACHE_DIR

    rows = []
    if NEWS_CACHE_DIR.exists():
        for f in sorted(NEWS_CACHE_DIR.glob("*.csv")):
            try:
                df = pd.read_csv(f, usecols=["published"])
                rows.append({"symbol": f.stem, "meldungen": len(df),
                             "von": str(df["published"].min())[:10],
                             "bis": str(df["published"].max())[:10]})
            except Exception:
                continue
    return pd.DataFrame(rows)


def intraday_coverage() -> pd.DataFrame:
    from .intraday import INTRADAY_CACHE_DIR

    rows = []
    if INTRADAY_CACHE_DIR.exists():
        for f in sorted(INTRADAY_CACHE_DIR.glob("*.csv")):
            first, last, n = _csv_range(f)
            rows.append({"datei": f.stem, "kerzen": n, "von": first, "bis": last})
    return pd.DataFrame(rows)


def category_summary(conn) -> pd.DataFrame:
    """Eine Zeile je Datenkategorie: Umfang, Zeitraum, letzter Abruf —
    die Grundlage der Daten-Seite."""
    def _last_fetch(category: str) -> str:
        row = conn.execute("SELECT MAX(time) FROM fetch_log WHERE category = ? AND ok = 1",
                           (category,)).fetchone()
        return (row[0] or "")[:16].replace("T", " ")

    def _row(sql: str) -> tuple:
        return conn.execute(sql).fetchone()

    rows = []
    n, lo, hi = _row("SELECT COUNT(*), MIN(first_date), MAX(last_date) FROM price_meta")
    rows.append(("Kurse EOD (CSV-Cache)", f"{n} Symbole", lo, hi, _last_fetch("prices")))
    n, lo, hi = _row("SELECT COUNT(*), MIN(fiscal_date), MAX(fiscal_date) FROM fundamentals")
    sym = _row("SELECT COUNT(DISTINCT symbol) FROM fundamentals")[0]
    rows.append(("Fundamentaldaten (Quartale)", f"{n} Quartale / {sym} Symbole",
                 lo, hi, _last_fetch("fundamentals")))
    n, lo, hi = _row("SELECT COUNT(*), MIN(date), MAX(date) FROM quotes")
    rows.append(("Aktuelle Preise (Snapshots)", f"{n} Einträge", lo, hi, _last_fetch("quotes")))
    n, lo, hi = _row("SELECT COUNT(*), MIN(date), MAX(date) FROM earnings_calendar")
    rows.append(("Earnings-Kalender", f"{n} Termine", lo, hi, _last_fetch("earnings")))
    n, lo, hi = _row("SELECT COUNT(*), MIN(date), MAX(date) FROM macro_series")
    ser = _row("SELECT COUNT(DISTINCT series) FROM macro_series")[0]
    rows.append(("Makro-Reihen (FRED)", f"{ser} Reihen / {n} Punkte", lo, hi,
                 _last_fetch("macro")))
    n, lo, hi = _row("SELECT COUNT(*), MIN(date), MAX(date) FROM events")
    rows.append(("Ereignis-Kalender (Fed/CPI/NFP)", f"{n} Termine", lo, hi,
                 _last_fetch("events")))
    n, lo, hi = _row("SELECT COUNT(*), MIN(date), MAX(date) FROM corporate_actions")
    rows.append(("Corporate Actions", f"{n} Einträge", lo, hi, _last_fetch("actions")))
    n = _row("SELECT COUNT(DISTINCT universe || month) FROM universe_members")[0]
    lo, hi = _row("SELECT MIN(month), MAX(month) FROM universe_members")
    rows.append(("Index-Zugehörigkeit (Snapshots)", f"{n} Snapshots", lo, hi,
                 _last_fetch("universe")))
    news = news_coverage()
    rows.append(("News-Archiv (CSV, append-only)",
                 f"{len(news)} Symbole / {int(news['meldungen'].sum()) if not news.empty else 0} Meldungen",
                 news["von"].min() if not news.empty else None,
                 news["bis"].max() if not news.empty else None, ""))
    intra = intraday_coverage()
    rows.append(("Intraday-Archiv (CSV)", f"{len(intra)} Dateien",
                 intra["von"].min() if not intra.empty else None,
                 intra["bis"].max() if not intra.empty else None, ""))
    return pd.DataFrame(rows, columns=["kategorie", "umfang", "von", "bis", "letzter_abruf"])


def symbol_coverage(conn, symbols: list[str]) -> pd.DataFrame:
    """Je Symbol: Kurs-Zeitraum, Quartale, jüngster Quote, News-Anzahl —
    für die Detail-Tabelle der Daten-Seite."""
    if not symbols:
        return pd.DataFrame()
    marks = ", ".join("?" for _ in symbols)
    prices = pd.read_sql_query(
        f"SELECT symbol, first_date, last_date, rows FROM price_meta "
        f"WHERE symbol IN ({marks})", conn, params=list(symbols)).set_index("symbol")
    fund = pd.read_sql_query(
        f"SELECT symbol, COUNT(*) AS quartale, MAX(fiscal_date) AS letztes_quartal "
        f"FROM fundamentals WHERE symbol IN ({marks}) GROUP BY symbol",
        conn, params=list(symbols)).set_index("symbol")
    quotes = latest_quotes(conn, symbols)
    news = news_coverage()
    news = news.set_index("symbol") if not news.empty else news

    rows = []
    for s in symbols:
        p = prices.loc[s] if s in prices.index else None
        f = fund.loc[s] if s in fund.index else None
        q = quotes.loc[s] if len(quotes) and s in quotes.index else None
        n = news.loc[s] if len(news) and s in news.index else None
        rows.append({
            "symbol": s,
            "kurse_von": p["first_date"] if p is not None else "",
            "kurse_bis": p["last_date"] if p is not None else "",
            "quartale": int(f["quartale"]) if f is not None else 0,
            "letztes_quartal": str(f["letztes_quartal"])[:10] if f is not None else "",
            "preis": round(float(q["price"]), 2) if q is not None and q["price"] else "",
            "preis_datum": q["date"] if q is not None else "",
            "news": int(n["meldungen"]) if n is not None else 0,
        })
    return pd.DataFrame(rows)
