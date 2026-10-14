"""Werkzeuge für den MCP-Server (mcp_server.py): lesender Zugriff auf
Daten-Hub, Bot-Protokoll, Kurs-Cache und News-Sentiment.

Bewusst getrennt vom Server-Code: reine Funktionen, die Dicts liefern —
dadurch ohne MCP testbar und auch aus Skripten nutzbar.

Sicherheitsprinzip "least privilege": NICHTS hier kann handeln, Orders
senden, Einstellungen ändern oder Daten aus dem Netz holen.
- Datenbanken werden schreibgeschützt geöffnet (SQLite mode=ro)
- run_sql lässt per Authorizer nur lesende Operationen zu, bricht lange
  Abfragen ab und begrenzt die Zeilenzahl
- Kurse kommen ausschließlich aus dem lokalen CSV-Cache
"""

from __future__ import annotations

import math
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DATA_CACHE_DIR, load_settings

HUB_DB = DATA_CACHE_DIR / "hub.db"
BOT_DB = DATA_CACHE_DIR / "bot.db"
PRICE_DIR = DATA_CACHE_DIR / "prices"
NEWS_DIR = DATA_CACHE_DIR / "news"
SCORE_DIRS = {"finbert": DATA_CACHE_DIR / "news_scores",
              "claude": DATA_CACHE_DIR / "news_scores_claude"}

DATABASES = {"hub": HUB_DB, "bot": BOT_DB}
MAX_ROWS = 500
QUERY_TIMEOUT_S = 5.0


# ------------------------------------------------------------- Hilfen

def _connect_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"Datenbank fehlt: {path.name} (erst Daten in der GUI laden)")
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _clean(value):
    """JSON-taugliche Python-Werte (NaN → None, numpy → Python)."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dict("records")]


def _query(path: Path, sql: str, params=()) -> pd.DataFrame:
    conn = _connect_ro(path)
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def _closes(symbol: str) -> pd.Series | None:
    """Schlusskurse aus dem lokalen Cache (kein Netzabruf)."""
    file = PRICE_DIR / f"{symbol}.csv"
    if not file.exists():
        return None
    df = pd.read_csv(file, index_col=0, parse_dates=True)
    df = df[df.index.notna()]
    if "Close" not in df or df.empty:
        return None
    return df["Close"].astype(float).sort_index()


def _price_stats(close: pd.Series) -> dict:
    rets = close.pct_change(fill_method=None).dropna()
    last = close.iloc[-1]
    year_ago = close[close.index <= close.index[-1] - pd.Timedelta(days=365)]
    dd = close / close.cummax() - 1
    return {
        "last_date": close.index[-1].date().isoformat(),
        "last_close": _clean(last),
        "return_1y": _clean(last / year_ago.iloc[-1] - 1) if len(year_ago) else None,
        "volatility_60d_ann": _clean(rets.tail(60).std() * math.sqrt(252)),
        "max_drawdown": _clean(dd.min()),
    }


# ------------------------------------------------------------- Überblick

def data_overview() -> dict:
    """Welche Daten liegen vor? Tabellen, Zeilenzahlen, Abdeckung, Frische."""
    out: dict = {"databases": {}}
    for name, path in DATABASES.items():
        if not path.exists():
            out["databases"][name] = "fehlt"
            continue
        conn = _connect_ro(path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        info = {}
        for t in tables:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info('{t}')")]
            count = conn.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
            info[t] = {"rows": count, "columns": cols}
        out["databases"][name] = info
        conn.close()

    if HUB_DB.exists():
        out["universes"] = _records(_query(HUB_DB,
            "SELECT universe, MAX(month) AS latest_month, COUNT(DISTINCT symbol) AS symbols "
            "FROM universe_members GROUP BY universe"))
        out["freshness"] = _records(_query(HUB_DB, """
            SELECT 'fundamentals' AS category, MAX(fiscal_date) AS latest FROM fundamentals
            UNION ALL SELECT 'quotes', MAX(date) FROM quotes
            UNION ALL SELECT 'prices (EOD cache)', MAX(last_date) FROM price_meta
            UNION ALL SELECT 'macro_series', MAX(date) FROM macro_series
            UNION ALL SELECT 'score_runs', MAX(run_at) FROM score_runs"""))
        out["recent_fetch_errors"] = _records(_query(HUB_DB,
            "SELECT time, category, key, source, message FROM fetch_log "
            "WHERE ok = 0 ORDER BY id DESC LIMIT 10"))
    out["price_cache_files"] = len(list(PRICE_DIR.glob("*.csv"))) if PRICE_DIR.exists() else 0
    out["news_archive_symbols"] = sorted(p.stem for p in NEWS_DIR.glob("*.csv")) \
        if NEWS_DIR.exists() else []
    return out


# ------------------------------------------------------------- SQL

_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):
    _ALLOWED_ACTIONS.add(sqlite3.SQLITE_RECURSIVE)


def _authorizer(action, *_):
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def run_sql(query: str, database: str = "hub", max_rows: int = 200) -> dict:
    """Eine lesende SQL-Abfrage (SELECT/WITH) gegen hub.db oder bot.db."""
    if database not in DATABASES:
        raise ValueError(f"database muss eines von {sorted(DATABASES)} sein")
    if not query.lstrip().lower().startswith(("select", "with")):
        raise ValueError("Nur lesende Abfragen (SELECT … oder WITH …) sind erlaubt")
    max_rows = max(1, min(int(max_rows), MAX_ROWS))
    conn = _connect_ro(DATABASES[database])
    deadline = time.monotonic() + QUERY_TIMEOUT_S
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    conn.set_authorizer(_authorizer)
    try:
        cur = conn.execute(query)
        columns = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(max_rows + 1)
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc):
            raise TimeoutError(f"Abfrage nach {QUERY_TIMEOUT_S:.0f} s abgebrochen") from exc
        raise
    finally:
        conn.close()
    return {
        "columns": columns,
        "rows": [[_clean(v) for v in r] for r in rows[:max_rows]],
        "truncated": len(rows) > max_rows,
    }


# ------------------------------------------------------------- Einzeltitel

def company_profile(symbol: str) -> dict:
    """Stammdaten, letzte Quartale (+TTM-Kennzahlen), Kurs-Statistik, Scores."""
    symbol = symbol.strip()
    out: dict = {"symbol": symbol}
    if HUB_DB.exists():
        comp = _query(HUB_DB, "SELECT name, sector, industry, currency, updated_at "
                              "FROM companies WHERE symbol = ?", (symbol,))
        out["company"] = _records(comp)[0] if len(comp) else None
        fund = _query(HUB_DB,
            "SELECT fiscal_date, source, revenue, operating_income, net_income, eps, "
            "total_equity, total_debt, free_cashflow FROM fundamentals "
            "WHERE symbol = ? ORDER BY fiscal_date DESC LIMIT 8", (symbol,))
        out["quarters"] = _records(fund)
        if len(fund) >= 4:
            ttm = fund.head(4)
            rev, oi, ni = ttm["revenue"].sum(), ttm["operating_income"].sum(), ttm["net_income"].sum()
            eq = fund["total_equity"].iloc[0]
            out["ttm"] = {
                "revenue": _clean(rev), "net_income": _clean(ni),
                "operating_margin": _clean(oi / rev) if rev else None,
                "roe": _clean(ni / eq) if eq and eq > 0 else None,
            }
            if len(fund) >= 8 and fund["revenue"].iloc[4:8].sum():
                out["ttm"]["revenue_growth_yoy"] = _clean(rev / fund["revenue"].iloc[4:8].sum() - 1)
        quote = _query(HUB_DB, "SELECT date, price, market_cap FROM quotes WHERE symbol = ? "
                               "ORDER BY date DESC LIMIT 1", (symbol,))
        out["latest_quote"] = _records(quote)[0] if len(quote) else None
        out["screener_scores"] = _records(_query(HUB_DB,
            "SELECT r.algo, r.universe, r.run_at, s.rank, s.score, s.detail "
            "FROM scores s JOIN score_runs r ON r.id = s.run_id WHERE s.symbol = ? "
            "ORDER BY r.run_at DESC LIMIT 5", (symbol,)))
    close = _closes(symbol)
    out["price"] = _price_stats(close) if close is not None and len(close) > 1 else None
    return out


def price_history(symbol: str, start: str | None = None, end: str | None = None,
                  frequency: str = "W") -> dict:
    """Schlusskurse aus dem Cache, verdichtet (D/W/M), max. 400 Punkte."""
    close = _closes(symbol.strip())
    if close is None:
        raise ValueError(f"Keine Kurse für {symbol!r} im Cache (Daten-Seite → Kurse EOD)")
    close = close.loc[start:end] if (start or end) else close
    if close.empty:
        raise ValueError("Keine Kurse im angefragten Zeitraum")
    freq = {"D": None, "W": "W-FRI", "M": "ME"}.get(frequency.upper(), "W-FRI")
    series = close if freq is None else close.resample(freq).last().dropna()
    series = series.tail(400)
    return {
        "symbol": symbol, "frequency": frequency.upper(),
        "stats": _price_stats(close),
        "points": [[d.date().isoformat(), _clean(v)] for d, v in series.items()],
    }


# ------------------------------------------------------------- MoQu

def _symbols_for(universe: str | None) -> list[str]:
    """Universum aus dem Hub (letzter Monats-Snapshot) oder Watchlist-Datei;
    ohne Angabe die Aktienquelle des Live-Profils."""
    settings = load_settings()
    universe = universe or settings.get("universe", "manual")
    if universe == "manual":
        return list(settings.get("watchlist", []))
    if HUB_DB.exists():
        df = _query(HUB_DB,
            "SELECT symbol FROM universe_members WHERE universe = ? AND month = "
            "(SELECT MAX(month) FROM universe_members WHERE universe = ?)",
            (universe, universe))
        if len(df):
            return list(df["symbol"])
    from .data.universe import UNIVERSE_CACHE_DIR, WATCHLIST_DIR, _load_watchlist

    file = WATCHLIST_DIR / f"{universe}.txt"
    if file.exists():
        return list(_load_watchlist(file)["symbol"])
    # zuletzt geladene Index-Liste (data_cache/universe/{name}_YYYY-MM.csv), ohne Netzabruf
    cached = sorted(UNIVERSE_CACHE_DIR.glob(f"{universe}_*.csv"))
    if cached:
        return list(pd.read_csv(cached[-1])["symbol"].dropna().astype(str))
    raise ValueError(f"Universum {universe!r} weder im Hub noch als Watchlist/Index-Cache "
                     "vorhanden (Daten-Seite → Universum laden)")


def moqu_ranking(symbols: list[str] | None = None, universe: str | None = None,
                 as_of: str | None = None, top_n: int | None = None) -> dict:
    """Erklärt die MoQu-Auswahl: Ranking-Bausteine je Titel zu einem Stichtag.

    Rechnet mit exakt den Formeln und Parametern der Strategie
    (VolAdjMomentumQuality, Parameter aus dem Live-Profil, falls MoQu dort
    konfiguriert ist) — als Momentaufnahme eines Rebalance-Tages.
    """
    from .strategies.base import MAX_FILL_DAYS, aligned_closes, make_strategy
    from .strategies.momo_quality import VolAdjMomentumQuality

    settings = load_settings()
    params = {}
    if settings.get("strategy") == "momo_quality":
        params = dict(settings.get("strategy_params") or {})
    for entry in settings.get("strategies") or []:
        if entry.get("key") == "momo_quality":
            params = dict(entry.get("params") or {})
    fields = VolAdjMomentumQuality.__dataclass_fields__
    strat = make_strategy(VolAdjMomentumQuality, params)  # GUI speichert Strings
    if top_n:
        strat.top_n = int(top_n)

    syms = [s.strip() for s in symbols] if symbols else _symbols_for(universe)
    excluded: list[dict] = []
    closes = {}
    for s in syms:
        c = _closes(s)
        if c is None:
            excluded.append({"symbol": s, "reason": "keine Kurse im Cache"})
        else:
            closes[s] = c
    if not closes:
        raise ValueError("Für keinen Titel liegen Kurse vor")
    # derselbe Kalender-Abgleich wie in der Strategie (Feiertagslücken überbrückt)
    frame = aligned_closes({s: c.to_frame("Close") for s, c in closes.items()})
    if as_of:
        frame = frame.loc[:as_of]
    # Stichtag: jüngster Tag, an dem mind. die Hälfte der Titel einen Kurs hat
    counts = frame.notna().sum(axis=1)
    valid = counts[counts >= max(1, len(frame.columns) // 2)]
    if valid.empty:
        raise ValueError("Kein gemeinsamer Handelstag mit ausreichend Kursen")
    frame = frame.loc[:valid.index[-1]]
    day = frame.index[-1]

    momentum = frame.shift(strat.skip) / frame.shift(strat.lookback) - 1
    vol = frame.pct_change(fill_method=None).rolling(strat.vol_n).std()
    risk_adj = momentum / vol.replace(0, np.nan)
    if strat.second_lookback > 0:
        mom2 = frame.shift(strat.skip) / frame.shift(strat.second_lookback) - 1
        risk_adj = (risk_adj + mom2 / vol.replace(0, np.nan)) / 2
    mom_d, vol_d, ra_d = momentum.loc[day], vol.loc[day], risk_adj.loc[day]

    cols = list(frame.columns)
    quality = strat._quality_ranks(cols, pd.DatetimeIndex([day]))
    q_row = quality[0] if quality is not None else None

    rows, cand = [], []
    for j, s in enumerate(cols):
        m, ra = mom_d[s], ra_d[s]
        if pd.isna(ra):
            excluded.append({"symbol": s, "reason": "kein Wert am Stichtag (zu kurze Historie "
                             "oder Kurslücke im 60-Tage-Fenster)"})
            continue
        if not (m > 0):
            excluded.append({"symbol": s, "reason": f"negatives Momentum über {strat.lookback} Tage ({m:+.1%}) → Kasse"})
            continue
        cand.append((j, s))
    if cand:
        values = np.array([ra_d[s] for _, s in cand])
        order = np.argsort(np.argsort(values))
        mom_rank = order / max(len(cand) - 1, 1)
        for k, (j, s) in enumerate(cand):
            q = float(q_row[j]) if q_row is not None else None
            score = mom_rank[k]
            if q is not None and strat.quality_weight > 0:
                score = (1 - strat.quality_weight) * mom_rank[k] + strat.quality_weight * q
            rows.append({
                "symbol": s,
                "momentum": _clean(mom_d[s]),
                "volatility_ann": _clean(vol_d[s] * math.sqrt(252)),
                "risk_adj_momentum": _clean(ra_d[s]),
                "momentum_rank": _clean(mom_rank[k]),
                "quality_rank": _clean(q),
                "score": _clean(score),
            })
    rows.sort(key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["selected"] = i <= strat.top_n

    if HUB_DB.exists() and rows:
        names = _query(HUB_DB, "SELECT symbol, name, sector FROM companies WHERE symbol IN (%s)"
                       % ",".join("?" * len(rows)), [r["symbol"] for r in rows])
        meta = names.set_index("symbol").to_dict("index")
        for r in rows:
            r.update({k: meta.get(r["symbol"], {}).get(k) for k in ("name", "sector")})

    warnings = []
    gaps = sum(1 for e in excluded if e["reason"].startswith("kein Wert am Stichtag"))
    if gaps > 0.3 * len(cols):
        warnings.append(
            f"{gaps} von {len(cols)} Titeln haben am Stichtag keinen Wert. Lücken bis "
            f"{MAX_FILL_DAYS} Tage werden überbrückt — häufige Ursache sind veraltete "
            "Kursdateien (Daten-Seite → Kurse EOD aktualisieren) oder zu kurze Historie.")

    return {
        "strategy": strat.name,
        "parameters": {k: getattr(strat, k) for k in fields},
        "as_of": day.date().isoformat(),
        "quality_data": q_row is not None,
        "ranking": rows,
        "excluded": excluded,
        "warnings": warnings,
        "method": (
            "score = (1-quality_weight)·Rang(Momentum/Volatilität) + quality_weight·Qualitätsrang; "
            "Momentum = Kurs vor `skip` Tagen / Kurs vor `lookback` Tagen − 1; "
            "nur Titel mit positivem Momentum. Qualitätsrang aus TTM-ROE und operativer Marge "
            "(nur Quartale, die ≥ reporting_lag Tage alt sind). Hinweis: Im laufenden Betrieb "
            "behält die Strategie gehaltene Titel, solange sie in den Top top_n×exit_rank_mult "
            "liegen, und rebalanciert nur alle rebalance_days Handelstage — die tatsächlichen "
            "Positionen können daher von dieser Momentaufnahme abweichen."),
    }


# ------------------------------------------------------------- News

def news_sentiment(symbol: str, days: int = 30) -> dict:
    """Schlagzeilen aus dem Archiv mit gecachten FinBERT-/Claude-Scores."""
    symbol = symbol.strip()
    file = NEWS_DIR / f"{symbol}.csv"
    if not file.exists():
        return {"symbol": symbol, "headlines": [], "note": "kein News-Archiv für diesen Titel"}
    news = pd.read_csv(file)
    news["published"] = pd.to_datetime(news["published"], utc=True)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=int(days))
    news = news[news["published"] >= cutoff].sort_values("published", ascending=False)
    for backend, folder in SCORE_DIRS.items():
        cache = folder / f"{symbol}.csv"
        if cache.exists():
            scores = pd.read_csv(cache).drop_duplicates("title")
            keep = ["title", "sentiment"] + [c for c in ("label", "reason") if c in scores]
            scores = scores[keep].rename(columns={
                "sentiment": f"{backend}_score", "label": f"{backend}_label",
                "reason": f"{backend}_reason"})
            news = news.merge(scores, on="title", how="left")
    news["published"] = news["published"].dt.strftime("%Y-%m-%d %H:%M")
    summary = {}
    for backend in SCORE_DIRS:
        col = f"{backend}_score"
        if col in news and news[col].notna().any():
            summary[backend] = {"mean": _clean(news[col].mean()),
                                "scored": int(news[col].notna().sum())}
    return {
        "symbol": symbol, "days": days, "headlines": _records(news.drop(columns=["link"],
                                                                         errors="ignore")),
        "mean_scores": summary,
        "gate": {"min_score": load_settings().get("sentiment_min", -0.2),
                 "window_days": load_settings().get("sentiment_days", 7)},
        "note": "Scores aus dem Cache; neue Schlagzeilen scoren: uv run news.py SYMBOL [--backend claude]",
    }


# ------------------------------------------------------------- Bot

def bot_activity(limit: int = 50) -> dict:
    """Entscheidungs-Log, Orders, Equity-Verlauf und aktive Stops des Bots."""
    limit = max(1, min(int(limit), MAX_ROWS))
    if not BOT_DB.exists():
        return {"note": "bot.db fehlt — der Bot ist noch nie gelaufen"}
    return {
        "events": _records(_query(BOT_DB, "SELECT time, level, message FROM events "
                                          "ORDER BY id DESC LIMIT ?", (limit,))),
        "orders": _records(_query(BOT_DB, "SELECT time, symbol, quantity, price, commission, "
                                          "reason FROM orders ORDER BY id DESC LIMIT ?", (limit,))),
        "equity": _records(_query(BOT_DB, "SELECT time, equity, cash FROM equity "
                                          "ORDER BY time DESC LIMIT ?", (limit,))),
        "stops": _records(_query(BOT_DB, "SELECT symbol, level FROM stops")),
        "settings": {k: load_settings().get(k) for k in (
            "strategy", "strategies", "universe", "broker", "sentiment_enabled",
            "sentiment_backend", "macro_filter", "risk")},
    }
