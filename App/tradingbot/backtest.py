"""Backtester: spielt eine Strategie gegen historische Daten durch.

Wichtigstes Detail: das Signal von Tag t wird erst am Tag t+1 umgesetzt
(position = signal.shift(1)). Ohne diese Verschiebung würde der Backtest
mit Wissen handeln, das er am Handelstag noch gar nicht hatte
(Look-Ahead-Bias) – der häufigste Fehler, der Backtests zu gut aussehen lässt.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .strategies import SignalStrategy as Strategy

TRADING_DAYS_PER_YEAR = 252


@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    equity: pd.Series          # Kapitalverlauf, startet bei 1.0
    position: pd.Series        # gehaltene Position je Tag (0/1)
    total_return: float        # Gesamtrendite, z.B. 0.85 = +85 %
    cagr: float                # annualisierte Rendite
    max_drawdown: float        # größter Verlust vom Zwischenhoch, negativ
    sharpe: float              # Rendite/Risiko-Verhältnis (annualisiert)
    num_trades: int            # Anzahl Käufe + Verkäufe

    def summary(self) -> str:
        return (
            f"{self.strategy_name} auf {self.symbol}\n"
            f"  Gesamtrendite : {self.total_return:+8.1%}\n"
            f"  CAGR          : {self.cagr:+8.1%} p.a.\n"
            f"  Max. Drawdown : {self.max_drawdown:8.1%}\n"
            f"  Sharpe-Ratio  : {self.sharpe:8.2f}\n"
            f"  Trades        : {self.num_trades:8d}"
        )


def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    symbol: str = "?",
    cost_per_trade: float = 0.001,
) -> BacktestResult:
    """Führt den Backtest aus.

    cost_per_trade: Kosten pro Kauf/Verkauf als Anteil des Kapitals
    (0.001 = 0.1 % für Gebühren + Slippage zusammen).
    """
    signal = strategy.target_position(df)
    position = signal.shift(1).fillna(0)  # Signal von gestern wird heute gehandelt

    daily_returns = df["Close"].pct_change().fillna(0)
    trades = position.diff().abs().fillna(0)  # 1.0 bei jedem Positionswechsel
    strategy_returns = position * daily_returns - trades * cost_per_trade

    equity = (1 + strategy_returns).cumprod()

    # Kalenderzeit statt Handelstage: Aktien haben ~252 Handelstage pro
    # Jahr, Krypto 365 — für die Jahresrendite zählt die echte Zeitspanne
    years = (df.index[-1] - df.index[0]).days / 365.25
    total_return = equity.iloc[-1] - 1
    cagr = equity.iloc[-1] ** (1 / years) - 1 if years > 0 else 0.0
    drawdown = equity / equity.cummax() - 1
    std = strategy_returns.std()
    sharpe = (
        strategy_returns.mean() / std * TRADING_DAYS_PER_YEAR**0.5 if std > 0 else 0.0
    )

    return BacktestResult(
        strategy_name=strategy.name,
        symbol=symbol,
        equity=equity,
        position=position,
        total_return=total_return,
        cagr=cagr,
        max_drawdown=drawdown.min(),
        sharpe=sharpe,
        num_trades=int(trades.sum()),
    )
