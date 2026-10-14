"""MCP-Server: macht Daten-Hub, Bot-Protokoll und MoQu-Ranking für Claude
abfragbar (Claude Desktop, Claude Code oder jeder andere MCP-Client).

    uv run mcp_server.py          # stdio-Transport (so starten ihn die Clients)

Claude Desktop (claude_desktop_config.json) bzw. Claude Code:

    {"mcpServers": {"tradingbot": {"command": "uv",
        "args": ["--directory", "C:\\\\SW\\\\TradingBot\\\\App", "run", "mcp_server.py"]}}}

    claude mcp add tradingbot -- uv --directory C:\\SW\\TradingBot\\App run mcp_server.py

Alle Werkzeuge sind rein lesend (Details: tradingbot/mcp_tools.py) — der
Server kann weder handeln noch Einstellungen ändern. Wichtig bei stdio:
nichts auf stdout schreiben, das gehört dem MCP-Protokoll.
"""

from __future__ import annotations

import sqlite3

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from tradingbot import mcp_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                            idempotent_hint=True, open_world_hint=False)

def _call(func, *args, **kwargs):
    """Erwartbare Fehler (falsches Symbol, unerlaubtes SQL, Timeout …) als
    lesbare Tool-Fehler an Claude geben, damit es sich selbst korrigieren kann."""
    try:
        return func(*args, **kwargs)
    except (ValueError, FileNotFoundError, TimeoutError, sqlite3.Error) as exc:
        raise ToolError(str(exc)) from exc


server = MCPServer(
    name="tradingbot",
    version="0.1.0",
    instructions=(
        "Lesender Zugriff auf einen privaten Trading-Bot: Daten-Hub (Fundamentaldaten, "
        "Kurs-Snapshots, Index-Universen, Screener-Scores), lokaler Kurs-Cache, "
        "News-Archiv mit Sentiment-Scores (FinBERT/Claude) und das Protokoll des Bots "
        "(Entscheidungen, Orders, Equity). Starte bei offenen Fragen mit data_overview. "
        "Für 'warum hat der Bot X gekauft/nicht gekauft' kombiniere moqu_ranking, "
        "news_sentiment und bot_activity. Kennzahlen sind Dezimalzahlen (0.12 = 12 %). "
        "Keine Anlageberatung formulieren; der Server kann nicht handeln."),
)


@server.tool(annotations=READ_ONLY)
def data_overview() -> dict:
    """Überblick: Tabellen beider Datenbanken (hub, bot) mit Spalten und Zeilenzahl,
    verfügbare Universen, Datenfrische, letzte Abruffehler, News-Archiv-Symbole."""
    return _call(mcp_tools.data_overview)


@server.tool(annotations=READ_ONLY)
def run_sql(query: str, database: str = "hub", max_rows: int = 200) -> dict:
    """Führt EINE lesende SQL-Abfrage (SELECT/WITH, SQLite-Dialekt) aus.

    database: "hub" (companies, fundamentals, quotes, universe_members, score_runs,
    scores, macro_series, events, earnings_calendar, price_meta, fetch_log) oder
    "bot" (events, orders, equity, stops). Schema vorher mit data_overview ansehen.
    max_rows: höchstens 500. Lange Abfragen werden nach 5 s abgebrochen."""
    return _call(mcp_tools.run_sql, query, database=database, max_rows=max_rows)


@server.tool(annotations=READ_ONLY)
def company_profile(symbol: str) -> dict:
    """Steckbrief eines Titels (Yahoo-Symbol, z.B. "SAP.DE", "AAPL"): Stammdaten,
    letzte 8 Quartale, TTM-Kennzahlen (ROE, operative Marge, Umsatzwachstum),
    letzter Kurs-Snapshot, Screener-Scores und Kursstatistik (1J-Rendite,
    Volatilität, Max-Drawdown)."""
    return _call(mcp_tools.company_profile, symbol)


@server.tool(annotations=READ_ONLY)
def price_history(symbol: str, start: str | None = None, end: str | None = None,
                  frequency: str = "W") -> dict:
    """Schlusskurse aus dem lokalen Cache. start/end als YYYY-MM-DD,
    frequency "D" (täglich), "W" (wöchentlich) oder "M" (monatlich); max. 400 Punkte."""
    return _call(mcp_tools.price_history, symbol, start=start, end=end, frequency=frequency)


@server.tool(annotations=READ_ONLY)
def moqu_ranking(symbols: list[str] | None = None, universe: str | None = None,
                 as_of: str | None = None, top_n: int | None = None) -> dict:
    """Erklärt die Titelauswahl der Hauptstrategie MoQu (vol-adjustiertes Momentum +
    Qualität): je Titel 12M-Momentum, Volatilität, Momentum-Rang, Qualitätsrang,
    Gesamtscore, Rang und ob er ausgewählt würde — plus ausgeschlossene Titel mit Grund.

    symbols: explizite Liste ODER universe (z.B. "dax", "sp500", Watchlist-Name);
    ohne beides die Aktienquelle des Live-Profils. as_of: Stichtag YYYY-MM-DD
    (Default: letzter Handelstag im Cache)."""
    return _call(mcp_tools.moqu_ranking, symbols=symbols, universe=universe, as_of=as_of,
                 top_n=top_n)


@server.tool(annotations=READ_ONLY)
def news_sentiment(symbol: str, days: int = 30) -> dict:
    """Schlagzeilen eines Titels aus dem News-Archiv mit den gecachten Sentiment-
    Scores beider Modelle (FinBERT, Claude inkl. Label und Begründung) sowie der
    aktuellen Gate-Schwelle des Bots."""
    return _call(mcp_tools.news_sentiment, symbol, days=days)


@server.tool(annotations=READ_ONLY)
def bot_activity(limit: int = 50) -> dict:
    """Protokoll des Bots: letzte Entscheidungen (inkl. blockierter Einstiege mit
    Grund), Orders, Equity-Verlauf, aktive Stops und die relevanten Einstellungen
    (ohne API-Keys)."""
    return _call(mcp_tools.bot_activity, limit=limit)


@server.prompt()
def explain_portfolio(universe: str = "dax") -> str:
    """Vorlage: aktuelle MoQu-Auswahl eines Universums erklären."""
    return (
        f"Erkläre mir die aktuelle Auswahl der MoQu-Strategie für das Universum '{universe}'. "
        "Nutze moqu_ranking für das Ranking, company_profile für die ausgewählten Titel und "
        "news_sentiment, um zu prüfen, ob das Sentiment-Gate einen Kauf blockieren würde. "
        "Fasse am Ende in einer Tabelle zusammen: Titel, Rang, Momentum, Qualität, "
        "Sentiment, Hinweise. Weise auf Datenlücken hin.")


if __name__ == "__main__":
    server.run()  # stdio
