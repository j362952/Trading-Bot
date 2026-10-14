"""PaperBroker: Simulation gegen aktuelle Kurse, kein Konto nötig.

Kontostand und Positionen liegen persistent in
data_cache/paper_account.json — der Paper-Track-Record überlebt also
Neustarts. Gebührenmodell wie IBKR (max(1 USD, 0.005 USD/Aktie)) plus
konfigurierbare Slippage, damit die Simulation nicht schmeichelt.

Zum Zurücksetzen: reset() aufrufen (GUI-Knopf) oder die JSON-Datei löschen.
"""

from __future__ import annotations

import json
from datetime import datetime

from ..config import DATA_CACHE_DIR
from .base import Broker, Fill, Position

STATE_FILE = DATA_CACHE_DIR / "paper_account.json"


class PaperBroker(Broker):
    name = "Simulation (Paper)"

    def __init__(self, start_cash: float = 100_000.0,
                 commission_per_share: float = 0.005,
                 commission_min: float = 1.0,
                 slippage_bps: float = 5.0):
        self.start_cash = start_cash
        self.commission_per_share = commission_per_share
        self.commission_min = commission_min
        self.slippage_bps = slippage_bps
        self._state = self._load()

    # ------------------------------------------------------------ Zustand

    def _load(self) -> dict:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {"cash": self.start_cash, "positions": {}, "history": []}

    def _save(self) -> None:
        DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def reset(self, start_cash: float | None = None) -> None:
        self._state = {"cash": start_cash or self.start_cash, "positions": {}, "history": []}
        self._save()

    # ------------------------------------------------------------ Broker-API

    def cash(self) -> float:
        return float(self._state["cash"])

    def equity(self) -> float:
        """Bargeld + Positionen zum letzten bekannten Kurs (avg_price als
        Fallback; die Engine bewertet Positionen selbst mit frischen Kursen)."""
        value = sum(
            p["quantity"] * p.get("last_price", p["avg_price"])
            for p in self._state["positions"].values()
        )
        return self.cash() + value

    def positions(self) -> list[Position]:
        return [
            Position(symbol, p["quantity"], p["avg_price"])
            for symbol, p in self._state["positions"].items()
            if p["quantity"] != 0
        ]

    def mark_price(self, symbol: str, price: float) -> None:
        """Aktuellen Kurs für die Equity-Bewertung hinterlegen."""
        if symbol in self._state["positions"]:
            self._state["positions"][symbol]["last_price"] = price
            self._save()

    def market_order(self, symbol: str, quantity: float,
                     price_hint: float | None = None) -> Fill:
        if not price_hint or price_hint <= 0:
            raise ValueError(f"PaperBroker braucht einen Kurs (price_hint) für {symbol}")
        # Slippage: Käufe etwas teurer, Verkäufe etwas billiger
        direction = 1 if quantity > 0 else -1
        price = price_hint * (1 + direction * self.slippage_bps / 10_000)
        commission = max(self.commission_min, self.commission_per_share * abs(quantity))

        cost = quantity * price + commission
        if quantity > 0 and cost > self.cash():
            raise ValueError(f"Nicht genug Bargeld für {quantity} × {symbol}")

        pos = self._state["positions"].setdefault(
            symbol, {"quantity": 0.0, "avg_price": 0.0}
        )
        new_qty = pos["quantity"] + quantity
        if quantity > 0:  # Kauf: Durchschnittspreis fortschreiben
            total_cost = pos["quantity"] * pos["avg_price"] + quantity * price
            pos["avg_price"] = total_cost / new_qty if new_qty else 0.0
        pos["quantity"] = new_qty
        pos["last_price"] = price
        if new_qty == 0:
            del self._state["positions"][symbol]

        self._state["cash"] -= cost
        self._state["history"].append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "symbol": symbol, "quantity": quantity,
            "price": round(price, 4), "commission": round(commission, 2),
        })
        self._save()
        return Fill(symbol, quantity, price, commission)
