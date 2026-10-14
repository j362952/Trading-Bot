"""Datenschicht des Trading Bots (Kurse, News, Universen)."""

from .prices import load_daily

__all__ = ["load_daily"]
