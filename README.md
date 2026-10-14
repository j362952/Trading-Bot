# Trading-Werkzeuge

Ein aktives Projekt, ein Archiv:

| Ordner | Inhalt | Start |
|---|---|---|
| [`App/`](App) | **Das aktive Projekt**: eine GUI mit vier Seiten (Daten · TradeBot · ValueScreener · Backtest) über einem gemeinsamen Daten-Hub; Handelsstrategien + Risk-Management, Backtests/Robustheits-Harness, Screening, Broker-Anbindung (Paper/IBKR) | `cd App && uv run bot_gui.py` |
| [`_archiv/MarketScreener/`](_archiv/MarketScreener) | Ursprüngliches Screener-Tool — abgelöst durch die ValueScreener-Seite; Daten in den Hub migriert, Code als Referenz archiviert (venv entfernt; `uv run` legt bei Bedarf ein neues an) | — |

Claude-Integration (optional): ein MCP-Server macht Bot-Daten und MoQu-Ranking in
Claude abfragbar, Claude kann FinBERT als Sentiment-Modell ersetzen — inklusive
Evaluation beider Modelle. Details: [App/README.md](App/README.md#claude-integration).

Einzelne GUI-Seiten lassen sich auch separat öffnen:
`gui_1_daten.py` … `gui_4_backtest.py` im App-Ordner.

Maßgebliche Methodik-Dokumente (beide in `App/`):
[`STRATEGIE.md`](App/STRATEGIE.md) (Handel/Risiko) und
[`ANALYSE.md`](App/ANALYSE.md) (Screening-Score).
Die Zielarchitektur der GUI und der Umsetzungsstand stehen in
[`GUI_KONZEPT.md`](App/GUI_KONZEPT.md); alle Datenquellen/API-Schnittstellen
sind dort und auf der Daten-Seite der GUI dokumentiert.

Hinweis: Wer den Tageszyklus über die Windows-Aufgabenplanung eingerichtet
hat (run_cycle.bat), muss den Pfad dort einmalig auf `App\run_cycle.bat`
anpassen (Ordner hieß früher `TradingBot\`).

## Haftungsausschluss

Dies ist ein Experimentier- und Lernprojekt. **Keine Anlageberatung.**
Backtest-Ergebnisse sind keine Garantie für künftige Renditen. Die Nutzung –
insbesondere mit echtem Geld – erfolgt auf eigenes Risiko.
