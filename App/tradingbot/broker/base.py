"""Broker-Schnittstelle für den Trading Bot.

Der Bot (Engine/GUI) wird ausschließlich gegen dieses Interface
programmiert, nie gegen eine konkrete Broker-API. Dadurch läuft derselbe
Bot-Code gegen die Simulation (PaperBroker), das IBKR-Paper-Konto und
später das Live-Konto — nur die Broker-Instanz wird ausgetauscht.

Implementierungen:
- PaperBroker (paper.py): Simulation gegen aktuelle Kurse, kein Konto nötig
- IbkrBroker (ibkr.py): Interactive Brokers über ib_async (TWS/IB Gateway)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Position:
    symbol: str
    quantity: float
    avg_price: float


@dataclass
class Fill:
    """Ergebnis einer ausgeführten Order."""

    symbol: str
    quantity: float      # >0 Kauf, <0 Verkauf
    price: float
    commission: float


class Broker(ABC):
    name: str = "?"

    def connect(self) -> None:
        """Verbindung aufbauen (falls nötig)."""

    def disconnect(self) -> None:
        """Verbindung trennen (falls nötig)."""

    @property
    def connected(self) -> bool:
        return True

    @abstractmethod
    def cash(self) -> float:
        """Verfügbares Bargeld auf dem Konto."""

    @abstractmethod
    def equity(self) -> float:
        """Gesamtwert des Kontos (Bargeld + Positionen)."""

    @abstractmethod
    def positions(self) -> list[Position]:
        """Alle offenen Positionen."""

    @abstractmethod
    def market_order(self, symbol: str, quantity: float,
                     price_hint: float | None = None) -> Fill:
        """Market-Order: quantity > 0 kauft, quantity < 0 verkauft.

        price_hint: aktueller Kurs für Simulations-Broker; echte Broker
        ignorieren ihn und liefern den tatsächlichen Ausführungskurs.
        """
