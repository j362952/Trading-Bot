# MarketScreener

> **ARCHIVIERT (2026-07-10):** Die Screener-Funktionalität lebt jetzt als
> **ValueScreener-Seite in der TradingBot-GUI** (`cd ../../App &&
> uv run bot_gui.py` bzw. `uv run gui_3_valuescreener.py`), mit dem
> Daten-Hub (`App/data_cache/hub.db`) als Datenbasis — die
> `data/screener.db` hier wurde dorthin migriert. Die Methodik-Datei
> ANALYSE.md ist nach `App/ANALYSE.md` umgezogen (neben
> STRATEGIE.md) und bleibt dort maßgeblich (implementiert in
> `App/tradingbot/screening/value_score.py`). Dieser Ordner ist
> nur noch Referenz; das venv wurde entfernt (`uv run` erzeugt bei
> Bedarf ein neues).

Value-Investing-Analyse ganzer Aktien-Universen — eigenständiges Tool mit
GUI, Quartals-Fundamentaldaten in SQLite und einem Score je Aktie.
Die Analyse-Methodik steht in [../../App/ANALYSE.md](../../App/ANALYSE.md).

## Start

```bash
cd MarketScreener
uv run screener_gui.py
```

In der GUI: Universum wählen → **"Daten aktualisieren + Analyse"**. Der
erste Lauf über ein großes Universum dauert (1 Abruf je Aktie); abgebrochene
Läufe machen beim nächsten Start dort weiter, wo sie waren. Danach reicht
meist **"Nur Analyse"** — Fundamentaldaten gelten 30 Tage als frisch, die
Kurse werden bei jedem Lauf mit "Daten aktualisieren" als Batch erneuert.

## Universen

S&P 500, Nasdaq 100, DAX, SMI, EuroStoxx 50, FTSE 100 (Wikipedia,
monatlich gecacht), MSCI World (~1.400 Titel, aus den iShares-ETF-Holdings)
sowie eigene Watchlists: Textdatei in `watchlists/` anlegen, ein Symbol pro
Zeile (Yahoo-Schreibweise), `#` beginnt einen Kommentar — erscheint beim
nächsten Start in der GUI.

## Datenquellen (austauschbare Provider)

| Provider | Historie | Key | Rolle |
|---|---|---|---|
| Yahoo Finance | ~5 Quartale | nein | Basis/Fallback, alle Börsen |
| Financial Modeling Prep | bis ~15 Jahre | kostenlos ([Registrierung](https://site.financialmodelingprep.com)) | Historien-Backfill, v.a. US-Titel |

FMP-Key: Umgebungsvariable `FMP_API_KEY` oder GUI → Einstellungen.
Gratis-Tarif: ~250 Requests/Tag = ~80 Aktien Backfill pro Tag; einmal
gefüllte Aktien werden markiert, der Rest folgt beim nächsten Lauf
automatisch (bei Limit übernimmt Yahoo den Rest des Laufs).
Weitere Quellen (SEC EDGAR, EODHD, …) lassen sich als zusätzliche Klasse in
`marketscreener/providers/` einhängen.

## Speicherung

Alles in einer SQLite-Datei `data/screener.db`:

| Tabelle | Inhalt |
|---|---|
| `quarterly` | eine Zeile je Aktie und Fiskalquartal, wie reportet (GuV/Bilanz/Cashflow, normalisiert), Quelle je Zeile |
| `companies` | Stammdaten je Aktie |
| `snapshots` | Preis + Marktkapitalisierung je Aktie und Tag |
| `score_runs` / `scores` | jedes Analyse-Ergebnis, dauerhaft (Score-Historie) |

Jeder Lauf landet zusätzlich als CSV in `reports/`. Die Quartals-Historie
wächst mit jedem Lauf — auch ohne FMP-Key baut sich so über die Zeit eine
eigene Historie auf.

## Architektur

```
MarketScreener/
├── screener_gui.py          # Start: uv run screener_gui.py
├── ANALYSE.md               # Methodik + Änderungsprotokoll (maßgeblich)
├── marketscreener/
│   ├── config.py            # Pfade, Einstellungen (data/settings.json)
│   ├── db.py                # SQLite-Schema und Zugriffe
│   ├── universe.py          # Indizes, MSCI World, Watchlists
│   ├── providers/           # austauschbare Fundamentaldaten-Quellen
│   │   ├── base.py          #   Interface (normalisiertes Quartals-Schema)
│   │   ├── yahoo.py         #   Yahoo Finance (ohne Key)
│   │   └── fmp.py           #   Financial Modeling Prep (API-Key)
│   ├── fundamentals.py      # Abruf-Orchestrierung (Resume, Fallback)
│   ├── prices.py            # Kurs-Batch + Marktkapitalisierung
│   ├── scoring.py           # TTM-Kennzahlen + Perzentil-Score
│   └── gui.py               # Tkinter-Oberfläche
├── data/                    # DB + Einstellungen (nicht versioniert)
├── reports/                 # CSV je Analyse-Lauf
└── watchlists/              # eigene Symbol-Listen
```

**Disclaimer:** Screening-Werkzeug, keine Anlageberatung.
