"""Broker-Schicht: Interface + Implementierungen (Paper-Simulation, IBKR)."""

from .base import Broker, Fill, Position
from .paper import PaperBroker

__all__ = ["Broker", "Fill", "Position", "PaperBroker", "make_broker"]


def make_broker(kind: str, **kwargs) -> Broker:
    """Broker nach Konfiguration bauen: 'paper' oder 'ibkr'.

    Der IBKR-Import passiert erst hier, damit der Bot ohne installiertes
    ib_async voll simulationsfähig bleibt.
    """
    if kind == "ibkr":
        from .ibkr import IbkrBroker

        return IbkrBroker(**kwargs)
    valid = {k: v for k, v in kwargs.items()
             if k in ("start_cash", "commission_per_share", "commission_min", "slippage_bps")}
    return PaperBroker(**valid)
