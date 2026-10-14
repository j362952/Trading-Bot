"""Risk-Management: entscheidet WIE VIEL gehandelt wird und wann NICHT.

Das oberste Ziel — langfristig regelmäßig Gewinn — wird in der Praxis
selten an der Signalqualität verfehlt, sondern am Risiko: eine einzige
zu große Position oder ein ungebremster Drawdown zerstört Jahre an
Erträgen. Deshalb liegt das Risk-Management NICHT in den Strategien,
sondern als eigene Schicht dazwischen: Strategien sagen WAS und WANN,
diese Schicht sagt WIE VIEL und notfalls NEIN.

Regeln (Details und Belege: STRATEGIE.md):
1. Positionsgröße nach der 1%-Regel: pro Trade wird höchstens
   risk_per_trade des Kapitals riskiert; Abstand zum Stop = ATR-Vielfaches.
2. Trailing-Stop auf ATR-Basis (Chandelier): begrenzt jeden Einzeltrade.
3. Konzentrations-Limits: max. Positionen, max. Gewicht je Position.
4. Marktregime-Filter: neue Käufe nur, wenn der Referenzindex über
   seinem 200-Tage-Schnitt liegt ("don't fight the tape").
5. Kill-Switch: überschreitet der Drawdown des Bot-Kapitals das Limit,
   wird alles verkauft und der Bot deaktiviert sich (manueller Neustart
   nach Analyse — bewusst unbequem).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.01        # 1 % des Kapitals Risiko je Trade
    atr_n: int = 14                     # ATR-Periode
    atr_stop_mult: float = 3.0          # Stop-Abstand = 3 × ATR (Chandelier)
    max_positions: int = 10             # nie mehr offene Positionen
    max_weight: float = 0.20            # max. 20 % des Kapitals je Position
    regime_symbol: str = "SPY"          # Referenzindex für den Regime-Filter
    regime_sma: int = 200               # Käufe nur über diesem Schnitt (0 = aus)
    max_drawdown: float = 0.25          # Kill-Switch bei 25 % Drawdown
    cooldown_days: int = 10             # nach Stop-Out: so lange kein Wiedereinstieg
                                        # (verhindert die Rebuy-Schleife im Abverkauf)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d: dict) -> "RiskConfig":
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range (Wilder) — das Standardmaß für Schwankungsbreite."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, min_periods=n).mean()


def position_size(
    equity: float, price: float, atr_value: float, cfg: RiskConfig
) -> int:
    """Stückzahl nach 1%-Regel: (Kapital × Risiko) / Stop-Abstand,
    gedeckelt durch das Maximalgewicht je Position."""
    if price <= 0 or np.isnan(price):
        return 0
    stop_distance = cfg.atr_stop_mult * atr_value
    if not stop_distance or np.isnan(stop_distance) or stop_distance <= 0:
        shares_by_risk = 0
    else:
        shares_by_risk = int(equity * cfg.risk_per_trade / stop_distance)
    shares_by_weight = int(equity * cfg.max_weight / price)
    return max(0, min(shares_by_risk, shares_by_weight))


def regime_ok(regime_df: pd.DataFrame | None, cfg: RiskConfig) -> pd.Series | bool:
    """True, wo der Referenzindex über seinem SMA liegt (Käufe erlaubt).

    Mit DataFrame → Serie je Tag (Backtest); ohne Daten/deaktiviert → True.
    """
    if cfg.regime_sma <= 0 or regime_df is None or regime_df.empty:
        return True
    close = regime_df["Close"]
    return close > close.rolling(cfg.regime_sma).mean()


@dataclass
class TrailingStop:
    """Chandelier-Stop: hängt atr_stop_mult × ATR unter dem höchsten
    Schlusskurs seit Einstieg und wandert nur nach oben."""

    level: float = 0.0

    def update(self, close: float, atr_value: float, mult: float) -> None:
        candidate = close - mult * atr_value
        self.level = max(self.level, candidate)

    def hit(self, close: float) -> bool:
        return close < self.level


@dataclass
class KillSwitch:
    """Deaktiviert den Bot, wenn der Drawdown des Bot-Kapitals das Limit reißt."""

    max_drawdown: float
    peak_equity: float = 0.0
    triggered: bool = False

    def check(self, equity: float) -> bool:
        """True = soeben ausgelöst (alles verkaufen, Bot stoppen)."""
        self.peak_equity = max(self.peak_equity, equity)
        if self.triggered:
            return False
        if self.peak_equity > 0 and equity / self.peak_equity - 1 < -self.max_drawdown:
            self.triggered = True
            return True
        return False
