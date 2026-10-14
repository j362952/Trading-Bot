"""Aktuelle Marktpreise, als Batch bei jedem Analyse-Lauf.

Ein einziger yfinance-Batch-Download statt 500 Einzelabfragen. Die
Marktkapitalisierung wird aus Preis × jüngster Aktienzahl (Bilanz)
berechnet — das vermeidet die langsame info-Abfrage je Symbol.

Londoner Notierungen (.L) liefert Yahoo in Pence; sie werden durch 100
geteilt, damit Preis und Bilanzwährung (GBP) zusammenpassen.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

from . import db


def update_prices(symbols: list[str], conn) -> dict[str, float]:
    """Holt letzte Schlusskurse für alle Symbole und speichert Snapshots."""
    if not symbols:
        return {}

    data = yf.download(
        symbols, period="5d", interval="1d",
        auto_adjust=False, progress=False, threads=True, group_by="ticker",
    )

    prices: dict[str, float] = {}
    for symbol in symbols:
        try:
            closes = data[symbol]["Close"].dropna() if len(symbols) > 1 else data["Close"].dropna()
        except (KeyError, TypeError):
            continue
        if closes.empty:
            continue
        price = float(closes.iloc[-1])
        if symbol.endswith(".L"):
            price /= 100.0  # GBp → GBP
        prices[symbol] = price

    # Marktkapitalisierung = Preis × jüngste bekannte Aktienzahl
    history = db.quarterly_history(conn, list(prices))
    mcaps: dict[str, float] = {}
    if not history.empty:
        latest_shares = (
            history.dropna(subset=["shares_outstanding"])
            .groupby("symbol")["shares_outstanding"].last()
        )
        for symbol, shares in latest_shares.items():
            if symbol in prices and shares and shares > 0:
                mcaps[symbol] = prices[symbol] * float(shares)

    db.save_snapshots(conn, prices, mcaps)
    return prices
