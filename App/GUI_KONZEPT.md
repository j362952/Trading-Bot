# Zielarchitektur: Eine GUI, vier Seiten, ein Daten-Hub

Vorgabe (2026-07-08): EINE GUI, Seiten strikt getrennt. Gemeinsame Basis
ist ein Daten-Hub, der alle Kategorien auf EINEN Zeitstrahl mappt.

## Daten-Hub (SQLite `data_cache/hub.db`, alles auf (datum, symbol/serie))

| Kategorie | Quelle | Rhythmus |
|---|---|---|
| Historische Kurse (EOD) | Yahoo/Tiingo (bestehender Cache → migrieren) | täglich |
| Intraday-Archiv | IBKR/Yahoo/Tiingo/FMP (bestehend) | je Abruf |
| Aktuelle Preise | Batch bei jedem Zyklus/GUI-Refresh | live |
| Fundamentaldaten (Quartale, wie reportet) | Screener-DB (FMP/Yahoo) → in Hub | quartalsweise |
| Neue Earnings + Termine (voraus!) | FMP Earnings Calendar | täglich |
| Aktuelle News + Sentiment-Score | Yahoo + FinBERT (bestehendes Archiv) | je Zyklus |
| Historische Makrodaten | Preis-Proxys (VIX, HYG/LQD) + FRED (Zinsen, Inflation, Arbeitslosigkeit; kostenlos) | täglich/monatlich |
| Ereignis-Kalender (Fed/CPI/NFP) | FMP Economic Calendar | täglich |
| Corporate Actions (Splits/Dividenden) | Yahoo | bei Kurs-Refresh |
| Index-Zugehörigkeit (Historie!) | Universen-Snapshots fortschreiben | monatlich |
| Eigene Daten: Trades, Equity, Backtest-Läufe | Bot-DB (bestehend) | laufend |
| Datenqualitäts-Metadaten (Quelle, Abrufzeit, Lücken) | alle Feeds | je Abruf |

## Seite 1 — Daten
Visualisierung der Datenlage: je Aktie aktueller Preis, Abdeckungsbalken
pro Kategorie (von wann bis wann liegen Daten vor), Frische-Ampeln,
Lücken; Universums-Überblick (x von y Titeln vollständig); Makro-Reihen
als Mini-Charts; letzte Abruffehler. Abruf-Knöpfe je Kategorie.
Dazu (Ergänzung 2026-07-10): **API-Schnittstellen-Panel** — alle
Datenquellen (Yahoo, FMP, Tiingo, FRED, Stooq, IBKR, Universen-Quellen)
mit Konfigurationsstatus, letzter erfolgreicher Lieferung, letztem
Fehler und Kursabruf-Zähler der Sitzung; jede Datenkategorie ist
manuell triggerbar (inkl. News-Archiv und Intraday). Die Ansicht
aktualisiert sich automatisch (nach jedem Abruf + jede Minute);
"APIs testen" prüft jede Schnittstelle mit einer Mini-Anfrage.
API-Robustheit: FMP läuft über einen stable/v3-Fallback
(`data/fmpapi.py` — FMP hat die v3-Endpunkte für neue Keys
abgeschaltet), FRED mit 90-s-Timeout und 2 Wiederholungen.

Backtest-Seite (Präzisierung 2026-07-10): im festen Zeitraum läuft
JEDE Strategie unabhängig mit demselben fixen Startkapital (keine
Budget-Aufteilung — Budgets gelten nur im Live-Betrieb); verglichen
wird gegen denselben Betrag in SPY UND QQQ (Buy & Hold), Ausgabe
inkl. Endkapital. Vor dem Start prüft eine Datenprüfung, ob genug
Titel ausreichende Historie haben (sonst Abbruch mit Hinweis auf die
Daten-Seite).

## Seite 2 — TradeBot
Alles zum Live-/Paper-Betrieb an EINEM Ort: Aktienquelle + Strategie(n)
(auch mehrere parallel — Kapital-Budgets je Strategie), Trading-Schalter,
Kontobalance + Equity-Kurve, offene Positionen, Trade-Übersicht,
Entscheidungs-Log. Bot-Einstellungen (Broker, Zyklus, Risiko, Keys)
hinter Zahnrad-Icon als Dialog. Eigenes Konfigurations-Profil "live".

## Seite 3 — ValueScreener
Eigenständiger Screener in derselben GUI (löst die separate
MarketScreener-GUI ab; Datenschicht wandert in den Hub): eigene
Aktienauswahl, Bewertungsalgorithmen als austauschbare Dateien in
`screening/` (Registry wie bei Bot-Strategien; Start: Value/Quality/
Growth-Score aus ANALYSE.md, weitere wählbar z.B. Piotroski, Magic
Formula), Ergebnistabelle + Score-Historie.

## Seite 4 — Backtest
Eigenes Profil "test", unabhängig vom Live-Betrieb: eigene Aktienauswahl,
alle Strategien (auch neue/mehrere kombinierbar), Modus wählbar:
(a) fester Zeitraum (von–bis) oder (b) randomisierte Zeitfenster
(Anzahl einstellbar, Längen 3 Monate–4 Jahre, zufällige Startdaten +
Teiluniversen = bestehender Robustheits-Harness) — Ergebnis als
Verteilung inkl. Marktphasen-/Segment-Auswertung.

## Umsetzungsreihenfolge
1. ✅ Daten-Hub-Schema + Migration bestehender Bestände; Feeds Preise/News/
   Earnings/Makro (FRED) in den Zyklus integrieren
2. ✅ GUI-Gerüst mit 4 Seiten; TradeBot-Seite (Zahnrad, Profil "live")
3. ✅ Daten-Seite (Visualisierung aus Hub-Metadaten)
4. ✅ Backtest-Seite (Profil "test", fester Zeitraum + Zufallsfenster)
5. ✅ ValueScreener-Seite (Screening-Registry, MarketScreener-Ablösung)

## Stand der Umsetzung (2026-07-10)

Alle fünf Schritte sind umgesetzt. Struktur:

- **Daten-Hub**: `tradingbot/data/hub.py` (SQLite `data_cache/hub.db`) mit
  Tabellen für Fundamentaldaten (+ Migration aus der alten Screener-DB,
  idempotent beim ersten Start), Quotes, Earnings-/Ereignis-Kalender,
  Makro-Reihen (FRED), Corporate Actions, Universen-Snapshots,
  Score-Historie und Abruf-Protokoll (`fetch_log`).
- **Feeds**: `tradingbot/data/feeds.py` (Quotes-Batch, FRED, FMP-Kalender,
  Corporate Actions, Universen-Snapshots, Kurs-Refresh) — einzeln über die
  Daten-Seite abrufbar und als leichter `cycle_update` in jedem Bot-Zyklus
  (Quotes immer, Makro/Earnings/Events 1× täglich).
  Fundamentaldaten: `tradingbot/data/fundamentals.py` (Yahoo + FMP,
  portiert aus dem MarketScreener).
- **GUI**: `tradingbot/ui/` — nach Seiten geordnet
  (`seite1_daten.py` … `seite4_backtest.py`; gemeinsame Bausteine
  app.py/widgets.py/source_panel.py/settings_dialog.py).
  `tradingbot/gui.py` bleibt als Kompatibilitäts-Einstieg für
  `bot_gui.py`. **Jede Seite ist einzeln startbar** (Einzelstarter
  `gui_1_daten.py` … `gui_4_backtest.py` bzw. `ui.app.main("daten")`) —
  die Seiten sind unabhängig, gekoppelt nur über Daten-Hub und
  Einstellungs-Profile. Profile: "live" = `bot_settings.json`
  (unverändert), "test" = `bot_settings_test.json` (erbt beim Erststart
  vom Live-Profil).
- **Mehrere Strategien parallel**: `engine.resolve_strategies()` —
  Liste `strategies` in den Einstellungen (key/params/budget); Sizing je
  Strategie mit `equity × budget`, Positions-Eigentümer in der Bot-DB
  (`owner_<symbol>`), Exits entscheidet die besitzende Strategie.
- **Screening-Registry**: `tradingbot/screening/` mit `value_score`
  (Value/Quality/Growth aus ANALYSE.md), `piotroski` (F-Score, braucht
  ≥ 8 Quartale Historie) und `magic_formula` (Greenblatt, angenähert).

Bewusste Abweichungen vom Konzept (begründet):

- **EOD-Kurse bleiben im CSV-Cache** (`data_cache/prices/`, ~640 MB):
  eine Duplizierung in SQLite brächte keinen Funktionsgewinn und fasst
  den bewährten, backtest-kritischen Speicher nicht an. Der Hub
  REGISTRIERT die Bestände stattdessen (`price_meta`, Coverage-Abfragen)
  und bleibt damit die eine Sicht auf alle Kategorien. Gleiches gilt für
  das append-only News-Archiv (der Look-Ahead-Schutz hängt an genau
  diesen Dateien) und das Intraday-Archiv.
- Die separate MarketScreener-GUI ist abgelöst; das Projekt liegt als
  Referenz in `_archiv/MarketScreener/` (venv entfernt), seine Daten
  wurden in den Hub migriert, neue Screener-Läufe schreiben nur noch in
  den Hub. Die Methodik-Datei ANALYSE.md ist nach `TradingBot/ANALYSE.md`
  umgezogen.
