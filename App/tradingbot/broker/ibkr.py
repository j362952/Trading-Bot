"""Interactive-Brokers-Adapter über ib_async (Nachfolger von ib_insync).

Voraussetzungen:
1. IBKR-Konto mit aktiviertem Paper-Trading-Konto
2. Trader Workstation (TWS) oder IB Gateway läuft lokal, API aktiviert
   (TWS: Einstellungen → API → Settings → "Enable ActiveX and Socket Clients")
3. `uv add ib_async` (bereits in pyproject.toml)

Ports (Standard):        Paper    Live
  TWS                    7497     7496
  IB Gateway             4002     4001

Sicherung: Live-Ports werden nur akzeptiert, wenn allow_live=True
explizit gesetzt ist — versehentliches Live-Trading ist damit
ausgeschlossen.

IBKR ist nach Verbindung auch DATENQUELLE: fetch_bars() liefert
historische Kerzen bis hinunter zu 1 Minute (Basis für den
Intraday-Ausbau); ohne Marktdaten-Abo verzögert (15 Min), mit Abo
in Echtzeit.
"""

from __future__ import annotations

import pandas as pd

from .base import Broker, Fill, Position

PAPER_PORTS = {7497, 4002}
LIVE_PORTS = {7496, 4001}

# Yahoo-Suffix → (IBKR-Börse, Währung)
EXCHANGE_MAP = {
    "": ("SMART", "USD"),
    ".DE": ("IBIS", "EUR"),      # Xetra
    ".SW": ("EBS", "CHF"),       # SIX
    ".PA": ("SBF", "EUR"),       # Euronext Paris
    ".AS": ("AEB", "EUR"),       # Euronext Amsterdam
    ".MI": ("BVME", "EUR"),      # Borsa Italiana
    ".L": ("LSE", "GBP"),        # London
    ".TO": ("TSE", "CAD"),       # Toronto
    ".T": ("TSEJ", "JPY"),       # Tokio
}


def _to_contract(symbol: str):
    """Yahoo-Symbol → IBKR-Stock-Contract (best effort)."""
    from ib_async import Stock

    for suffix, (exchange, currency) in sorted(
        EXCHANGE_MAP.items(), key=lambda kv: -len(kv[0])
    ):
        if suffix and symbol.endswith(suffix):
            local = symbol[: -len(suffix)]
            return Stock(local, exchange, currency)
    return Stock(symbol.replace("-", " "), "SMART", "USD")  # BRK-B → "BRK B"


class IbkrBroker(Broker):
    name = "Interactive Brokers"

    def __init__(self, host: str = "127.0.0.1", port: int = 7497,
                 client_id: int = 7, allow_live: bool = False):
        if port in LIVE_PORTS and not allow_live:
            raise ValueError(
                f"Port {port} ist ein LIVE-Port. Live-Trading erst freigeben, "
                f"wenn der Paper-Betrieb überzeugt hat (allow_live=True)."
            )
        self.host, self.port, self.client_id = host, port, client_id
        self._ib = None

    # ------------------------------------------------------------ Verbindung

    def connect(self) -> None:
        import asyncio

        from ib_async import IB

        # ib_async braucht einen Event-Loop — in GUI-Hintergrund-Threads
        # existiert keiner, also bei Bedarf einen anlegen
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

        if self._ib and self._ib.isConnected():
            return
        self._ib = IB()
        self._ib.connect(self.host, self.port, clientId=self.client_id, timeout=10)
        mode = "PAPER" if self.port in PAPER_PORTS else "LIVE"
        self.name = f"Interactive Brokers ({mode})"

    def disconnect(self) -> None:
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()

    @property
    def connected(self) -> bool:
        return bool(self._ib and self._ib.isConnected())

    def _require(self):
        if not self.connected:
            raise ConnectionError("Nicht mit TWS/IB Gateway verbunden — läuft die TWS und ist die API aktiviert?")
        return self._ib

    # ------------------------------------------------------------ Konto

    def _account_value(self, tag: str) -> float:
        ib = self._require()
        for value in ib.accountSummary():
            if value.tag == tag:
                return float(value.value)
        return 0.0

    def cash(self) -> float:
        return self._account_value("TotalCashValue")

    def equity(self) -> float:
        return self._account_value("NetLiquidation")

    def positions(self) -> list[Position]:
        ib = self._require()
        return [
            Position(p.contract.symbol, p.position, p.avgCost)
            for p in ib.positions()
        ]

    # ------------------------------------------------------------ Orders

    def market_order(self, symbol: str, quantity: float,
                     price_hint: float | None = None) -> Fill:
        from ib_async import MarketOrder

        ib = self._require()
        contract = _to_contract(symbol)
        ib.qualifyContracts(contract)

        action = "BUY" if quantity > 0 else "SELL"
        trade = ib.placeOrder(contract, MarketOrder(action, abs(quantity)))
        # auf Ausführung warten (Market-Orders füllen normalerweise sofort)
        for _ in range(60):
            ib.sleep(0.5)
            if trade.isDone():
                break
        if not trade.fills:
            raise RuntimeError(f"Order für {symbol} nicht ausgeführt: {trade.orderStatus.status}")

        filled_qty = sum(f.execution.shares for f in trade.fills)
        avg_price = (
            sum(f.execution.shares * f.execution.price for f in trade.fills) / filled_qty
        )
        commission = sum(
            f.commissionReport.commission for f in trade.fills if f.commissionReport
        )
        signed = filled_qty if quantity > 0 else -filled_qty
        return Fill(symbol, signed, avg_price, commission)

    # ------------------------------------------------------------ Marktdaten

    def fetch_bars(self, symbol: str, duration: str = "1 Y",
                   bar_size: str = "1 day") -> pd.DataFrame:
        """Historische Kerzen von IBKR (OHLCV, Index = Zeit).

        bar_size z.B. "1 day", "1 hour", "5 mins" — die Grundlage für den
        späteren Intraday-Betrieb. Ohne Marktdaten-Abo: verzögerte Daten.
        """
        from ib_async import util

        ib = self._require()
        contract = _to_contract(symbol)
        ib.qualifyContracts(contract)
        bars = ib.reqHistoricalData(
            contract, endDateTime="", durationStr=duration,
            barSizeSetting=bar_size, whatToShow="TRADES", useRTH=True,
        )
        df = util.df(bars)
        if df is None or df.empty:
            raise ValueError(f"Keine IBKR-Kursdaten für {symbol}")
        df = df.rename(columns={"date": "Date", "open": "Open", "high": "High",
                                "low": "Low", "close": "Close", "volume": "Volume"})
        return df.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]]
