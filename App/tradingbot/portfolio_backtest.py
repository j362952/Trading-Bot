"""Portfolio-Backtester: Strategie + Risk-Management über viele Symbole.

Simuliert Tag für Tag genau das, was die Live-Engine tut — gleiche
Strategie-Matrix, gleiche Risk-Schicht (Positionsgrößen, Trailing-Stops,
Regime-Filter, Kill-Switch), gleiche Kostenlogik. Ausführung immer zur
NÄCHSTEN Kerze nach dem Signal (kein Look-Ahead).

Kosten: IBKR-artige Kommission (max(1 USD, 0.005/Aktie)) plus Slippage
in Basispunkten auf den Handelswert.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .risk import KillSwitch, RiskConfig, TrailingStop, atr, position_size, regime_ok
from .strategies import apply_sentiment_gate, position_matrix

TRADING_DAYS_PER_YEAR = 252


@dataclass
class Trade:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    exit_date: pd.Timestamp | None = None
    exit_price: float | None = None
    reason: str = ""

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.shares

    @property
    def ret(self) -> float:
        if self.exit_price is None or self.entry_price == 0:
            return 0.0
        return self.exit_price / self.entry_price - 1


@dataclass
class PortfolioResult:
    strategy_name: str
    equity: pd.Series
    trades: list[Trade]
    start_equity: float
    killed: bool = False

    # ---- Kennzahlen
    @property
    def total_return(self) -> float:
        return self.equity.iloc[-1] / self.start_equity - 1

    @property
    def cagr(self) -> float:
        years = (self.equity.index[-1] - self.equity.index[0]).days / 365.25
        if years <= 0:
            return 0.0
        return (self.equity.iloc[-1] / self.start_equity) ** (1 / years) - 1

    @property
    def max_drawdown(self) -> float:
        dd = self.equity / self.equity.cummax() - 1
        return float(dd.min())

    @property
    def sharpe(self) -> float:
        r = self.equity.pct_change().dropna()
        if r.std() == 0 or len(r) < 2:
            return 0.0
        return float(r.mean() / r.std() * TRADING_DAYS_PER_YEAR**0.5)

    @property
    def closed_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.exit_price is not None]

    @property
    def win_rate(self) -> float:
        closed = self.closed_trades
        if not closed:
            return 0.0
        return sum(1 for t in closed if t.pnl > 0) / len(closed)

    def summary(self) -> str:
        killed = "  ⚠ KILL-SWITCH ausgelöst\n" if self.killed else ""
        return (
            f"{self.strategy_name}\n"
            f"  Gesamtrendite : {self.total_return:+8.1%}\n"
            f"  CAGR          : {self.cagr:+8.1%} p.a.\n"
            f"  Max. Drawdown : {self.max_drawdown:8.1%}\n"
            f"  Sharpe-Ratio  : {self.sharpe:8.2f}\n"
            f"  Trades        : {len(self.trades):5d}  (Trefferquote "
            f"{self.win_rate:.0%} von {len(self.closed_trades)} geschlossenen)\n"
            f"{killed}"
        )

    def metrics(self) -> dict:
        return {
            "strategy": self.strategy_name,
            "total_return": round(self.total_return, 4),
            "cagr": round(self.cagr, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe": round(self.sharpe, 2),
            "trades": len(self.trades),
            "win_rate": round(self.win_rate, 3),
            "killed": self.killed,
        }


def run_portfolio_backtest(
    bars: dict[str, pd.DataFrame],
    strategy,
    risk: RiskConfig | None = None,
    sentiment: dict[str, pd.Series] | None = None,
    regime_df: pd.DataFrame | None = None,
    regime_series: pd.Series | None = None,
    start_equity: float = 100_000.0,
    commission_per_share: float = 0.005,
    commission_min: float = 1.0,
    slippage_bps: float = 5.0,
) -> PortfolioResult:
    risk = risk or RiskConfig()

    matrix = position_matrix(strategy, bars)
    if sentiment:
        matrix = apply_sentiment_gate(matrix, sentiment)
    desired = matrix.shift(1).fillna(0)  # Signal von gestern → heute handeln

    closes = pd.DataFrame({s: df["Close"] for s, df in bars.items()}).reindex(desired.index)
    atrs = pd.DataFrame({s: atr(df, risk.atr_n) for s, df in bars.items()}).reindex(desired.index)

    regime = regime_ok(regime_df, risk)
    if isinstance(regime, pd.Series):
        regime = regime.astype(float).shift(1).reindex(desired.index).fillna(0.0) > 0
    if regime_series is not None:
        extra = (regime_series.astype(float).shift(1)
                 .reindex(desired.index).ffill().fillna(1.0) > 0)
        regime = extra if isinstance(regime, bool) and regime else (
            regime & extra if isinstance(regime, pd.Series) else extra)

    cash = start_equity
    shares: dict[str, int] = {}
    stops: dict[str, TrailingStop] = {}
    trades: dict[str, Trade] = {}
    closed: list[Trade] = []
    kill = KillSwitch(risk.max_drawdown)
    killed = False
    equity_curve = []

    def commission(qty: int, price: float) -> float:
        return max(commission_min, commission_per_share * qty) + qty * price * slippage_bps / 10_000

    def sell(symbol: str, date, price: float, reason: str) -> None:
        nonlocal cash
        qty = shares.pop(symbol)
        stops.pop(symbol, None)
        cash += qty * price - commission(qty, price)
        t = trades.pop(symbol)
        t.exit_date, t.exit_price, t.reason = date, price, reason
        closed.append(t)

    # NumPy-Fastpath: Zeilenzugriffe über Arrays statt .loc (bei 500 Titeln
    # und 3000 Tagen der Unterschied zwischen Minuten und Sekunden)
    symbols_list = list(desired.columns)
    col = {s: j for j, s in enumerate(symbols_list)}
    desired_v = desired.to_numpy(dtype=float)
    closes_v = closes.to_numpy(dtype=float)
    atrs_v = atrs.to_numpy(dtype=float)
    regime_v = (regime.to_numpy() if isinstance(regime, pd.Series)
                else np.full(len(desired), bool(regime)))
    dates = desired.index

    last_price = np.full(len(symbols_list), np.nan)
    cooldown_until = np.full(len(symbols_list), -1)  # Bar-Index je Symbol

    for i in range(len(dates)):
        date = dates[i]
        row_close = closes_v[i]
        row_atr = atrs_v[i]
        fresh = ~np.isnan(row_close)
        last_price[fresh] = row_close[fresh]

        # Mark-to-Market
        equity = cash + sum(
            q * (last_price[col[s]] if not np.isnan(last_price[col[s]]) else 0.0)
            for s, q in shares.items())
        equity_curve.append((date, equity))

        if killed:
            continue

        # Kill-Switch: alles verkaufen, Bot aus
        if kill.check(equity):
            for symbol in list(shares):
                price = last_price[col[symbol]]
                if not np.isnan(price) and price > 0:
                    sell(symbol, date, float(price), "kill-switch")
            killed = True
            continue

        # Trailing-Stops pflegen und prüfen
        for symbol in list(shares):
            j = col[symbol]
            price, a = row_close[j], row_atr[j]
            if np.isnan(price):
                continue
            stop = stops[symbol]
            if not np.isnan(a) and a > 0:
                stop.update(float(price), float(a), risk.atr_stop_mult)
            if stop.hit(float(price)):
                sell(symbol, date, float(price), "trailing-stop")
                cooldown_until[j] = i + risk.cooldown_days

        # Strategie-Exits
        for symbol in list(shares):
            j = col[symbol]
            if desired_v[i, j] <= 0 and not np.isnan(row_close[j]):
                sell(symbol, date, float(row_close[j]), "signal")

        # Einstiege (Regime-Filter, Limits, Positionsgröße)
        if regime_v[i]:
            candidates = np.where((desired_v[i] > 0) & ~np.isnan(row_close)
                                  & (cooldown_until < i))[0]
            for j in candidates:
                symbol = symbols_list[j]
                if symbol in shares:
                    continue
                if len(shares) >= risk.max_positions:
                    break
                price = float(row_close[j])
                a = row_atr[j]
                qty = position_size(equity, price,
                                    float(a) if not np.isnan(a) else np.nan, risk)
                cost = qty * price + commission(qty, price) if qty else 0.0
                if qty <= 0 or cost > cash:
                    continue
                cash -= cost
                shares[symbol] = qty
                stop = TrailingStop()
                stop.update(price, float(a), risk.atr_stop_mult)
                stops[symbol] = stop
                trades[symbol] = Trade(symbol, date, price, qty)

    equity_series = pd.Series(dict(equity_curve)).sort_index()
    all_trades = closed + list(trades.values())
    return PortfolioResult(
        strategy_name=getattr(strategy, "name", str(strategy)),
        equity=equity_series,
        trades=all_trades,
        start_equity=start_equity,
        killed=killed,
    )
