# TradingBot

Handelt anhand adaptierbarer, empirisch belegter Strategien — gesteuert
über eine GUI, abgesichert durch eine eigene Risk-Management-Schicht,
wahlweise gegen die eingebaute Simulation (PaperBroker) oder Interactive
Brokers (Paper/Live über TWS/IB Gateway).

Die Handels- und Risiko-Methodik steht in [STRATEGIE.md](STRATEGIE.md) —
diese Datei ist zugleich die Grundlage für die Weiterentwicklung.

## Start

```bash
cd App
uv run bot_gui.py            # GUI mit allen vier Seiten (empfohlen)

# einzelne Seiten separat öffnen (unabhängig voneinander)
uv run gui_1_daten.py             # Seite 1: Daten (Hub, Abrufe)
uv run gui_2_tradebot.py          # Seite 2: TradeBot (Profil "live")
uv run gui_3_valuescreener.py     # Seite 3: ValueScreener
uv run gui_4_backtest.py          # Seite 4: Backtest (Profil "test")

# CLI-Werkzeuge
uv run run_backtests.py beispiel   # alle Strategien über eine Watchlist
uv run run_validation.py           # Robustheits-Harness (Zufallsfenster)
uv run main.py SPY                 # Einzel-Backtest SMA vs. Buy & Hold
uv run news.py AAPL NOVN.SW        # News-Sentiment (FinBERT)
uv run news.py AAPL --backend claude   # … mit Claude (inkl. Begründung)
uv run run_sentiment_eval.py run   # FinBERT vs. Claude messen (evals/README.md)
uv run mcp_server.py               # MCP-Server für Claude (siehe unten)
uv run python -m unittest discover -s tests   # Tests
```

## Claude-Integration

Zwei Bausteine, beide optional — ohne Anthropic-Key läuft alles wie bisher.

### 1. MCP-Server: den Bot mit Claude befragen

`mcp_server.py` stellt Daten-Hub, Kurs-Cache, News-Archiv und Bot-Protokoll
als [MCP](https://modelcontextprotocol.io)-Werkzeuge bereit. Damit lassen sich in
Claude Desktop oder Claude Code Fragen stellen wie *„Warum hat MoQu diesen Monat
genau diese Titel gewählt?"*, *„Würde das Sentiment-Gate bei SAP gerade blockieren?"*
oder *„Welche DAX-Titel haben die höchste operative Marge?"*.

| Werkzeug | liefert |
|---|---|
| `data_overview` | Tabellen/Spalten beider DBs, Universen, Datenfrische, letzte Abruffehler |
| `run_sql` | eine lesende SQL-Abfrage auf hub.db oder bot.db |
| `company_profile` | Stammdaten, Quartale, TTM-ROE/Marge/Wachstum, Kursstatistik, Screener-Scores |
| `price_history` | Kursreihe (D/W/M) mit Rendite, Volatilität, Max-Drawdown |
| `moqu_ranking` | MoQu-Auswahl zum Stichtag mit allen Ranking-Bausteinen je Titel + ausgeschlossene Titel mit Grund |
| `news_sentiment` | Schlagzeilen mit FinBERT- und Claude-Scores, Gate-Schwelle |
| `bot_activity` | Entscheidungs-Log, Orders, Equity, Stops, relevante Einstellungen (ohne Keys) |

**Bewusst nur lesend:** Datenbanken werden schreibgeschützt geöffnet, `run_sql`
erlaubt per SQLite-Authorizer nur Lese-Operationen (mit Zeit- und Zeilenlimit),
Kurse kommen nur aus dem lokalen Cache. Der Server kann weder handeln noch
Einstellungen ändern. `moqu_ranking` rechnet mit denselben Formeln und Parametern
wie die Strategie — ein Test (`tests/test_mcp_tools.py`) prüft, dass die Auswahl
an Rebalance-Tagen exakt übereinstimmt.

Einrichten — Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "tradingbot": {
      "command": "uv",
      "args": ["--directory", "C:\\SW\\TradingBot\\App", "run", "mcp_server.py"]
    }
  }
}
```

Claude Code: `claude mcp add tradingbot -- uv --directory C:\SW\TradingBot\App run mcp_server.py`

### 2. Claude als Sentiment-Modell (Alternative zu FinBERT)

Zahnrad → *Sentiment & Makro* → Modell `claude`, Key unter *API-Keys*
(oder Umgebungsvariable `ANTHROPIC_API_KEY`). Unterschiede zu FinBERT:

- bewertet **mit Bezug zur Firma**: Meldungen, die gar nicht von der Aktie handeln
  (im Yahoo-Feed häufig), zählen als neutral statt die Stimmung zu verfälschen
- liefert je Schlagzeile eine **Kurzbegründung** — blockiert das Gate einen Einstieg,
  steht die auslösende Meldung samt Begründung im Entscheidungs-Log
- strukturierte Ausgabe über ein erzwungenes Tool (JSON-Schema), Schlagzeilen als
  untrusted Input gekapselt, jede Antwort validiert
- **fällt bei Fehlern automatisch auf FinBERT zurück** (Key fehlt, API nicht
  erreichbar) — das Gate bleibt scharf, statt still offen zu stehen
- eigener Score-Cache (`data_cache/news_scores_claude/`), jede Schlagzeile wird nur
  einmal bewertet

Welches Modell besser ist, misst `run_sentiment_eval.py` auf handgelabelten
Schlagzeilen (Accuracy, Macro-F1, erkannte negative Meldungen, Fehlblockaden,
Token-Verbrauch) — Anleitung und Label-Regeln in [evals/README.md](evals/README.md).

## GUI-Kurzanleitung (eine GUI, vier Seiten — GUI_KONZEPT.md)

1. **Daten**: API-Schnittstellen-Übersicht (welche Quelle liefert was,
   Konfiguration, letzte erfolgreiche Lieferung/letzter Fehler als Ampel),
   Datenlage des Hubs (Abdeckung, Frische-Ampeln, Makro-Minicharts,
   Abruffehler) + **manuelle Abruf-Knöpfe für jede Kategorie**: Kurse EOD,
   aktuelle Preise, Fundamentals, FRED-Makro, Earnings, Ereignis-Kalender,
   Corporate Actions, News-Archiv, Intraday, Universum-Snapshot.
2. **TradeBot** (Profil "live"): Aktienquelle + Strategie(n) — auch
   mehrere parallel mit Kapital-Budgets —, Trading-Schalter, Equity-Kurve,
   Positionen (mit besitzender Strategie), Orders, Entscheidungs-Log.
   Broker/Zyklus/Risiko/Keys hinter dem Zahnrad.
3. **ValueScreener**: Universum + Algorithmus (Value/Quality/Growth-Score,
   Piotroski F-Score, Magic Formula) wählen → "Daten aktualisieren +
   Analyse" bzw. "Nur Analyse"; Ergebnis + Score-Historie je Titel.
   Löst die separate MarketScreener-GUI ab.
4. **Backtest** (Profil "test", unabhängig vom Live-Betrieb): fester
   Zeitraum (mit Segment-Auswertung der Trades) oder randomisierte
   Zeitfenster (Robustheits-Harness mit Marktphasen-Analyse); immer mit
   Kosten und Risk-Schicht, Benchmark SPY.

## Broker & Daten

| Modus | Voraussetzung | Datenquelle |
|---|---|---|
| Simulation (Default) | keine | Yahoo-Tagesdaten (Cache) |
| IBKR Paper | TWS/Gateway läuft, API aktiviert, Port 7497/4002 | Yahoo (1d) oder IBKR (`fetch_bars`, auch Intraday) |
| IBKR Live | expliziter Live-Schalter in den Einstellungen | wie Paper |

Kostenlose Yahoo-Daten reichen für Backtests und den täglichen
Swing-Betrieb; jedes Intraday-Intervall verlangt die IBKR-Verbindung
(Details: STRATEGIE.md §1). IBKR-Anbindung über
[ib_async](https://github.com/ib-api-reloaded/ib_async).

## API-Schnittstellen (alle auf der Daten-Seite live einsehbar)

| Schnittstelle | Key | liefert |
|---|---|---|
| Yahoo Finance | nein | Kurse EOD + Intraday, Preis-Batch, News, Fundamentals-Fallback, Corporate Actions |
| Financial Modeling Prep | ja (Zahnrad → API-Keys) | Fundamentals-Backfill (tiefe Historie), Earnings-Kalender, Ereignis-Kalender, Intraday-Fallback |
| Tiingo | ja (Zahnrad → API-Keys) | Kurs-Fallback EOD, Intraday IEX (US) |
| FRED (St. Louis Fed) | optional (empfohlen) | Makro-Reihen; ohne Key via fredgraph.csv (teils bot-gedrosselt), mit kostenlosem Key via offizieller API |
| EZB Data Portal | nein | Fallback für Europa-Reihen (EZB-Einlagenzins, HICP) |
| Stooq | nein | Kurs-Fallback EOD (oft blockiert) |
| IBKR (TWS/Gateway) | Verbindung | Broker + beste Kurs-/Intraday-Quelle, wenn verbunden |
| Wikipedia / iShares / companiesmarketcap | nein | Index-Universen, MSCI World, Global 2000 |

Das Panel oben auf der Daten-Seite zeigt je Schnittstelle den Status:
grün = hat zuletzt erfolgreich geliefert, rot = letzter Kontakt schlug
fehl, gelb = nutzbar, aber kein Key hinterlegt, grau = noch nie
kontaktiert — dazu Zeitpunkt der letzten Lieferung und die Zahl der
Kursabrufe der laufenden Sitzung je Provider.

## Architektur

```
App/
├── bot_gui.py               # Start: eine GUI, alle vier Seiten
├── gui_1_daten.py           # Seite 1 einzeln öffnen
├── gui_2_tradebot.py        # Seite 2 einzeln öffnen
├── gui_3_valuescreener.py   # Seite 3 einzeln öffnen
├── gui_4_backtest.py        # Seite 4 einzeln öffnen
├── run_backtests.py         # CLI: Strategie-Suite über ein Universum
├── run_validation.py        # CLI: Robustheits-Harness (Zufallsfenster)
├── run_sentiment_eval.py    # CLI: FinBERT vs. Claude auf gelabelten Schlagzeilen
├── mcp_server.py            # MCP-Server (lesender Zugriff für Claude)
├── evals/                   # Label-Datensatz + Anleitung Sentiment-Evaluation
├── tests/                   # unittest: Claude-Sentiment, MCP-Werkzeuge, Eval-Metriken
├── STRATEGIE.md             # Methodik + Backtest-Protokoll (maßgeblich)
├── GUI_KONZEPT.md           # Zielarchitektur GUI + Daten-Hub (+ Stand)
├── tradingbot/
│   ├── config.py            # Pfade + Einstellungen (Profile "live"/"test")
│   ├── botdb.py             # SQLite: Entscheidungen, Orders, Equity, Stops
│   ├── engine.py            # Zyklus: Daten → Signale → Risk → Orders
│   │                        #   (mehrere Strategien parallel mit Budgets)
│   ├── risk.py              # 1%-Regel, ATR-Stops, Limits, Kill-Switch
│   ├── portfolio_backtest.py# Mehrsymbol-Backtester (identische Logik)
│   ├── backtest.py          # Einzel-Backtester (main.py)
│   ├── validation.py        # Robustheits-Harness + Phasen-/Segment-Analyse
│   ├── strategies/          # Registry; neue Strategie = neue Datei
│   ├── screening/           # Registry der Screener-Algorithmen (Seite 3)
│   ├── broker/              # Interface + PaperBroker + IBKR (ib_async)
│   ├── data/                # hub.py (Daten-Hub), feeds.py, fundamentals.py,
│   │                        #   Kurse (CSV-Cache), News-Archiv, Universen
│   ├── mcp_tools.py         # Werkzeuge des MCP-Servers (rein lesend)
│   ├── sentiment/           # FinBERT, Claude + Sentiment-Historie (gecacht, Fallback)
│   └── ui/                  # GUI: app.py + seite1_daten.py … seite4_backtest.py
├── data_cache/              # hub.db, Kurse, News, Bot-DB, Profile (unversioniert)
├── reports/                 # Backtest-/Screener-/News-CSVs
└── watchlists/              # eigene Symbol-Listen
```

## Roadmap

- [x] Strategien-Framework mit GUI-editierbaren Parametern
- [x] Risk-Management (1%-Regel, Trailing-Stops, Regime-Filter, Kill-Switch)
- [x] Portfolio-Backtester mit Kosten
- [x] News-Sentiment als Entry-Gate (FinBERT, lokal)
- [x] PaperBroker (persistent) + IBKR-Adapter (Paper/Live)
- [x] Steuerungs-GUI mit Auto-Modus
- [x] Daten-Hub (hub.db) + eine GUI mit 4 Seiten (GUI_KONZEPT.md)
- [x] Mehrere Strategien parallel mit Kapital-Budgets
- [x] ValueScreener in der Bot-GUI (Screening-Registry, Hub-Datenbasis)
- [x] Equity-Kurve als Grafik (TradeBot-Seite)
- [x] MCP-Server: Bot-Daten und MoQu-Ranking in Claude abfragbar
- [x] Claude als alternatives Sentiment-Modell (mit Fallback auf FinBERT)
- [ ] Sentiment-Evaluation mit ≥200 gelabelten Schlagzeilen durchführen → Modellwahl begründen
- [ ] Backtest-Suite über DAX/SMI/eigene Watchlists → STRATEGIE.md §4
- [ ] Wochen im Paper-Betrieb (erst Simulation, dann IBKR Paper)
- [ ] Screener-Ranking als Watchlist-Quelle für den Bot (Kopplung Seite 3 → Seite 2)
- [ ] Live mit kleinem Betrag (allow_live), Kill-Switch enger

**Disclaimer:** Experimentier- und Lernprojekt. Keine Anlageberatung;
Live-Handel nur mit Geld, dessen Verlust verkraftbar ist.
