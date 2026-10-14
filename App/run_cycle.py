"""Ein Trading-Zyklus ohne GUI — für die Windows-Aufgabenplanung.

    uv run run_cycle.py          (oder Doppelklick auf run_cycle.bat)

Respektiert denselben Trading-Schalter wie die GUI (trading_active in
den Einstellungen): steht er auf Pause, passiert nichts. Alle
Entscheidungen landen wie immer in der Bot-DB — die GUI zeigt sie beim
nächsten Öffnen an. So läuft das Trading auch bei GESCHLOSSENER GUI,
solange der Rechner an ist.

Einrichtung (einmalig): Windows-Aufgabenplanung → "Einfache Aufgabe
erstellen" → täglich 22:15 → Programm starten → run_cycle.bat.
"""

from tradingbot import botdb
from tradingbot.broker import make_broker
from tradingbot.config import load_settings
from tradingbot.engine import TradingEngine


def main() -> None:
    settings = load_settings()
    if not settings.get("trading_active"):
        print("Trading steht auf PAUSE (Schalter in der GUI) — kein Zyklus.")
        botdb.log_event(botdb.connect(),
                        "Geplanter Zyklus übersprungen: Trading pausiert")
        return

    if settings.get("broker") == "ibkr":
        broker = make_broker("ibkr", host=settings["ibkr_host"],
                             port=int(settings["ibkr_port"]),
                             client_id=int(settings["ibkr_client_id"]),
                             allow_live=bool(settings.get("allow_live")))
        broker.connect()
    else:
        broker = make_broker("paper",
                             start_cash=float(settings.get("paper_start_cash", 5000)))

    engine = TradingEngine(settings, broker, status=print)
    print(engine.run_cycle())


if __name__ == "__main__":
    main()
