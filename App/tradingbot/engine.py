"""Trading-Engine: ein Zyklus = Daten → Signale → Risk-Checks → Orders.

Dieselbe Logik wie im Portfolio-Backtest, nur gegen einen echten Broker:
1. Kurse der Watchlist laden (Tagesdaten: Yahoo-Cache; Intraday: IBKR)
2. Strategie(n) rechnen die Ziel-Positionen (letzte abgeschlossene Kerze) —
   auch mehrere parallel, jede mit eigenem Kapital-Budget (GUI_KONZEPT.md)
3. Risk-Schicht: Kill-Switch → Trailing-Stops → Exits → Regime-Filter
   → Sentiment-Gate → Positionsgröße
4. Jede Entscheidung (auch jedes NEIN) landet begründet in der Bot-DB

Die Engine ist zustandsarm: Positionen kommen vom Broker, Stop-Level,
Peak-Equity und Positions-Eigentümer (welche Strategie hält was) aus der
Bot-DB — ein Neustart ändert am Verhalten nichts.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from . import botdb
from .broker.base import Broker
from .data import load_daily
from .risk import RiskConfig, atr, position_size
from .strategies import STRATEGIES, make_strategy, position_matrix


def resolve_symbols(settings: dict) -> list[str]:
    """Aktienquelle auflösen: Universums-Key (Index/Watchlist-Datei) oder
    manuelle Watchlist aus den Einstellungen."""
    key = settings.get("universe", "manual")
    if key in (None, "", "manual"):
        return list(settings.get("watchlist", []))
    from .data.universe import load_universe

    return list(load_universe(key)["symbol"])


def resolve_strategies(settings: dict) -> list[tuple[str, object, float]]:
    """Konfigurierte Strategien als [(key, Instanz, Budget 0–1)].

    settings["strategies"] (Liste mit key/params/budget) hat Vorrang;
    leer = die einzelne settings["strategy"] mit Budget 1.0. Budgets > 1
    in Summe werden proportional herunterskaliert.
    """
    entries = settings.get("strategies") or [{
        "key": settings.get("strategy", "sma_cross"),
        "params": settings.get("strategy_params", {}),
        "budget": 1.0,
    }]
    result = []
    for e in entries:
        key = e.get("key")
        if key not in STRATEGIES:
            continue
        strat = make_strategy(STRATEGIES[key], e.get("params", {}))
        result.append([key, strat, max(0.0, float(e.get("budget", 1.0)))])
    total = sum(b for _, _, b in result)
    if total > 1.0001 and total > 0:
        result = [[k, s, b / total] for k, s, b in result]
    return [tuple(r) for r in result] or [("sma_cross",
                                           make_strategy(STRATEGIES["sma_cross"], {}), 1.0)]


class TradingEngine:
    def __init__(self, settings: dict, broker: Broker,
                 status: Callable[[str], None] | None = None):
        self.settings = settings
        self.broker = broker
        self.risk = RiskConfig.from_dict(settings.get("risk", {}))
        self.conn = botdb.connect()
        self._status = status or (lambda msg: None)

    # ------------------------------------------------------------ Helfer

    def _log(self, message: str, level: str = "info") -> None:
        botdb.log_event(self.conn, message, level)
        self._status(message)

    def _load_bars(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        interval = self.settings.get("interval", "1d")
        bars = {}
        for symbol in symbols:
            try:
                if interval == "1d":
                    bars[symbol] = load_daily(symbol, start="2018-01-01")
                else:
                    # Intraday: IBKR (falls verbunden) → Yahoo → Tiingo → FMP
                    from .data.intraday import load_intraday

                    bars[symbol] = load_intraday(symbol, interval, broker=self.broker)
            except Exception as exc:
                self._log(f"{symbol}: keine Kursdaten ({exc})", "warn")
        return bars

    def _held(self, symbols: list[str] | None = None) -> dict[str, float]:
        tracked = set(symbols if symbols is not None else resolve_symbols(self.settings))
        return {p.symbol: p.quantity for p in self.broker.positions()
                if p.symbol in tracked and p.quantity > 0}

    def _sell_all(self, symbol: str, qty: float, price: float, reason: str) -> None:
        fill = self.broker.market_order(symbol, -qty, price_hint=price)
        botdb.log_order(self.conn, symbol, fill.quantity, fill.price,
                        fill.commission, reason)
        botdb.clear_stop(self.conn, symbol)
        botdb.set_meta(self.conn, f"owner_{symbol}", "")
        self._log(f"{symbol}: VERKAUF {qty:g} Stk @ {fill.price:.2f} ({reason})")

    # ------------------------------------------------------------ Zyklus

    def kill_switch_active(self) -> bool:
        return botdb.get_meta(self.conn, "killed") == "1"

    def reset_kill_switch(self) -> None:
        botdb.set_meta(self.conn, "killed", "0")
        botdb.set_meta(self.conn, "peak_equity", "0")
        self._log("Kill-Switch manuell zurückgesetzt", "warn")

    def run_cycle(self) -> str:
        if self.kill_switch_active():
            self._log("Zyklus verweigert: Kill-Switch ist aktiv "
                      "(Reset nur manuell nach Analyse)", "warn")
            return "Kill-Switch aktiv — keine Aktion."

        try:
            symbols = resolve_symbols(self.settings)
        except Exception as exc:
            self._log(f"Aktienquelle nicht ladbar: {exc}", "error")
            return "Aktienquelle nicht ladbar."
        if not symbols:
            return "Aktienquelle ist leer."
        self._log(f"Zyklus über {len(symbols)} Titel "
                  f"(Quelle: {self.settings.get('universe', 'manual')}, "
                  f"Intervall {self.settings.get('interval', '1d')})")
        self._status("Lade Kursdaten …")
        bars = self._load_bars(symbols)
        if not bars:
            return "Keine Kursdaten — Zyklus abgebrochen."

        # Daten-Hub-Feeds (Quotes; 1× täglich Makro/Earnings/Events) —
        # Fehler dürfen den Zyklus nie blockieren
        try:
            from .data import feeds, hub

            feeds.cycle_update(hub.connect(), list(bars), self._status)
        except Exception as exc:
            self._log(f"Hub-Feeds übersprungen ({exc})", "warn")

        # Strategien (eine oder mehrere parallel mit Kapital-Budgets)
        strategies = resolve_strategies(self.settings)
        desired_by: dict[str, pd.Series] = {}
        for key, strategy, budget in strategies:
            m = position_matrix(strategy, bars)
            desired_by[key] = m.iloc[-1]  # Signal der letzten abgeschlossenen Kerze
        # kombiniert: ein Titel ist gewünscht, wenn IRGENDEINE Strategie ihn will
        desired = pd.concat(desired_by.values(), axis=1).max(axis=1)

        last_close = {s: float(df["Close"].iloc[-1]) for s, df in bars.items()}
        last_atr = {s: float(atr(df, self.risk.atr_n).iloc[-1]) for s, df in bars.items()}

        # Paper-Broker: Positionen mit frischen Kursen bewerten
        if hasattr(self.broker, "mark_price"):
            for s, p in last_close.items():
                self.broker.mark_price(s, p)

        equity = self.broker.equity()
        held = self._held(symbols)

        # ---- Kill-Switch (Peak-Equity überlebt Neustarts in der Bot-DB)
        peak = max(float(botdb.get_meta(self.conn, "peak_equity", "0")), equity)
        botdb.set_meta(self.conn, "peak_equity", str(peak))
        if peak > 0 and equity / peak - 1 < -self.risk.max_drawdown:
            for symbol, qty in held.items():
                self._sell_all(symbol, qty, last_close.get(symbol, 0), "kill-switch")
            botdb.set_meta(self.conn, "killed", "1")
            self._log(f"KILL-SWITCH: Drawdown {equity / peak - 1:.1%} "
                      f"überschreitet {self.risk.max_drawdown:.0%} — alles verkauft, "
                      f"Bot deaktiviert", "error")
            botdb.log_equity(self.conn, self.broker.equity(), self.broker.cash())
            return "KILL-SWITCH ausgelöst — Bot deaktiviert."

        # ---- Trailing-Stops
        stops = botdb.get_stops(self.conn)
        for symbol, qty in list(held.items()):
            price, a = last_close.get(symbol), last_atr.get(symbol)
            if price is None:
                continue
            level = stops.get(symbol, 0.0)
            if a and not np.isnan(a):
                level = max(level, price - self.risk.atr_stop_mult * a)
                botdb.set_stop(self.conn, symbol, level)
            if price < level:
                self._sell_all(symbol, qty, price, "trailing-stop")
                held.pop(symbol)
                until = (pd.Timestamp.today().normalize()
                         + pd.Timedelta(days=int(self.risk.cooldown_days * 1.5)))
                botdb.set_meta(self.conn, f"cooldown_{symbol}", until.date().isoformat())

        # ---- Strategie-Exits: die BESITZENDE Strategie entscheidet über den
        # Ausstieg; unbekannter Besitzer (Altbestand) → kombiniertes Signal
        for symbol, qty in list(held.items()):
            owner = botdb.get_meta(self.conn, f"owner_{symbol}") or ""
            sig = (desired_by[owner].get(symbol, 0) if owner in desired_by
                   else desired.get(symbol, 0))
            if sig <= 0:
                reason = f"signal:{owner}" if owner in desired_by else "signal"
                self._sell_all(symbol, qty, last_close.get(symbol, 0), reason)
                held.pop(symbol)

        # ---- Regime-Filter für neue Käufe
        regime_allows = True
        if self.risk.regime_sma > 0:
            try:
                rdf = load_daily(self.risk.regime_symbol, start="2018-01-01")
                sma = rdf["Close"].rolling(self.risk.regime_sma).mean().iloc[-1]
                regime_allows = bool(rdf["Close"].iloc[-1] > sma)
            except Exception as exc:
                self._log(f"Regime-Filter ohne Daten ({exc}) — Käufe erlaubt", "warn")
        if not regime_allows:
            self._log(f"Regime-Filter: {self.risk.regime_symbol} unter "
                      f"{self.risk.regime_sma}-Tage-Schnitt — keine neuen Käufe")

        # ---- Makro-Ampel (VIX, Kreditrisiko, Index-Trend) für neue Käufe
        if regime_allows and self.settings.get("macro_filter", True):
            try:
                from .macro import current_status

                macro = current_status()
                if not macro.pop("risk_on", True):
                    regime_allows = False
                    detail = ", ".join(f"{k}: {v}" for k, v in macro.items())
                    self._log(f"Makro-Ampel ROT ({detail}) — keine neuen Käufe")
            except Exception as exc:
                self._log(f"Makro-Ampel ohne Daten ({exc}) — Käufe erlaubt", "warn")

        # ---- Ereignis-Blackout (Fed/CPI/Arbeitsmarkt): heute keine Einstiege
        if regime_allows and self.settings.get("event_blackout", False):
            try:
                from .macro import high_impact_event_today

                event = high_impact_event_today()
                if event:
                    regime_allows = False
                    self._log(f"Ereignis-Blackout: heute {event} — keine neuen Käufe")
            except Exception:
                pass

        # ---- Einstiege: je Strategie mit ihrem Kapital-Budget; die zuerst
        # konfigurierte Strategie hat bei knappen Positions-Slots Vorrang
        if regime_allows:
            for key, _, budget in strategies:
                sub_desired = desired_by[key]
                entries = [s for s in symbols
                           if sub_desired.get(s, 0) > 0 and s not in held
                           and s in last_close]
                for symbol in entries:
                    if len(held) >= self.risk.max_positions:
                        self._log(f"{symbol}: Einstieg ausgelassen — Limit "
                                  f"{self.risk.max_positions} Positionen erreicht")
                        continue
                    cool = botdb.get_meta(self.conn, f"cooldown_{symbol}")
                    if cool and cool >= pd.Timestamp.today().date().isoformat():
                        self._log(f"{symbol}: Einstieg ausgelassen — Abkühlphase nach "
                                  f"Stop-Out (bis {cool})")
                        continue
                    if not self._sentiment_ok(symbol):
                        continue
                    price, a = last_close[symbol], last_atr.get(symbol, np.nan)
                    qty = position_size(equity * budget, price, a, self.risk)
                    if qty <= 0:
                        self._log(f"{symbol}: Positionsgröße 0 (Kurs/ATR/Limits/"
                                  f"Budget {budget:.0%}) — kein Kauf")
                        continue
                    cost = qty * price
                    if cost > self.broker.cash():
                        self._log(f"{symbol}: nicht genug Bargeld für {qty} Stk — kein Kauf")
                        continue
                    fill = self.broker.market_order(symbol, qty, price_hint=price)
                    botdb.log_order(self.conn, symbol, fill.quantity, fill.price,
                                    fill.commission, f"signal:{key}")
                    if a and not np.isnan(a):
                        botdb.set_stop(self.conn, symbol,
                                       fill.price - self.risk.atr_stop_mult * a)
                    botdb.set_meta(self.conn, f"owner_{symbol}", key)
                    held[symbol] = qty
                    self._log(f"{symbol}: KAUF {qty} Stk @ {fill.price:.2f} "
                              f"({key}, Budget {budget:.0%}, "
                              f"Risiko {self.risk.risk_per_trade:.1%}, "
                              f"Stop {self.risk.atr_stop_mult:g}×ATR)")

        if hasattr(self.broker, "mark_price"):
            for s, p in last_close.items():
                self.broker.mark_price(s, p)
        botdb.log_equity(self.conn, self.broker.equity(), self.broker.cash())
        summary = (f"Zyklus fertig: {len(held)} Positionen, "
                   f"Equity {self.broker.equity():,.0f}")
        self._log(summary)
        return summary

    def _sentiment_ok(self, symbol: str) -> bool:
        if not self.settings.get("sentiment_enabled", False):
            return True
        days = int(self.settings.get("sentiment_days", 7))
        backend = self.settings.get("sentiment_backend", "finbert")
        try:
            from .sentiment import history

            score = history.current_sentiment(symbol, days=days, backend=backend)
        except Exception as exc:
            self._log(f"{symbol}: Sentiment nicht verfügbar ({exc}) — Gate offen", "warn")
            return True
        if score is None:
            return True  # keine News = neutral
        used = history.last_backend.get(symbol, backend)
        if used != backend:
            self._log(f"{symbol}: Sentiment-Backend {backend} nicht verfügbar — "
                      f"Fallback {used}", "warn")
        if score < float(self.settings.get("sentiment_min", -0.2)):
            why = ""
            try:  # Claude liefert Begründungen: die negativste Meldung ins Log
                worst = history.recent_scored(symbol, days=days, backend=used).iloc[0]
                why = f" — z.B. \"{str(worst['title'])[:80]}\""
                if isinstance(worst.get("reason"), str) and worst["reason"]:
                    why += f" ({worst['reason']})"
            except Exception:
                pass
            self._log(f"{symbol}: Einstieg blockiert — News-Sentiment {score:+.2f} ({used}) "
                      f"unter Schwelle {self.settings.get('sentiment_min')}{why}")
            return False
        return True
