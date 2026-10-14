"""Gemeinsame Pfade und Bot-Einstellungen.

Die Bot-Konfiguration (Aktienquelle, Strategie, Risiko, Broker, API-Keys)
liegt in data_cache/bot_settings.json — die GUI liest und schreibt sie
darüber, die Engine bekommt sie als Dict. data_cache/ ist nicht
versioniert, API-Keys landen also nicht im Repo.

Konfigurations-Profile (GUI_KONZEPT.md): "live" ist das Profil der
TradeBot-Seite (bestehende bot_settings.json), "test" das unabhängige
Profil der Backtest-Seite (bot_settings_test.json).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_CACHE_DIR = PROJECT_ROOT / "data_cache"
REPORTS_DIR = PROJECT_ROOT / "reports"
STRATEGIE_MD = PROJECT_ROOT / "STRATEGIE.md"

SETTINGS_FILE = DATA_CACHE_DIR / "bot_settings.json"

PROFILE_FILES = {
    "live": SETTINGS_FILE,                              # bestehende Datei bleibt "live"
    "test": DATA_CACHE_DIR / "bot_settings_test.json",
}

DEFAULT_SETTINGS: dict = {
    # Aktienquelle: "manual" = Watchlist-Feld, sonst Universums-Key
    # (sp500, nasdaq100, dax, smi, eurostoxx50, ftse100, global2000,
    #  msci_world oder Name einer Watchlist-Datei)
    "universe": "manual",
    "watchlist": ["SPY", "AAPL", "MSFT"],
    # Strategie (Key aus strategies.STRATEGIES) + Parameter-Overrides
    "strategy": "sma_cross",
    "strategy_params": {},
    # Mehrere Strategien parallel mit Kapital-Budgets (Anteil 0–1).
    # Leer = die einzelne Strategie oben mit Budget 1.0.
    # Beispiel: [{"key": "momentum", "params": {}, "budget": 0.6},
    #            {"key": "meanrev",  "params": {}, "budget": 0.4}]
    "strategies": [],
    # News-Sentiment-Gate
    "sentiment_enabled": True,
    "sentiment_min": -0.2,
    "sentiment_days": 7,
    # Risk-Management (Felder von risk.RiskConfig)
    "risk": {},
    # Broker: "paper" oder "ibkr"
    "broker": "paper",
    "paper_start_cash": 100000.0,
    "ibkr_host": "127.0.0.1",
    "ibkr_port": 7497,           # 7497 = TWS Paper, 4002 = Gateway Paper
    "ibkr_client_id": 7,
    "allow_live": False,         # Live-Ports nur mit explizitem Ja
    # Makro-Schicht: Ampel (Index-Trend, VIX, Kredit) + Ereignis-Blackout
    "macro_filter": True,
    "event_blackout": False,
    # Zyklus: "1d" = einmal täglich; Intraday-Intervalle nutzen IBKR
    # (falls verbunden) oder die Intraday-Provider (Yahoo/Tiingo/FMP)
    "interval": "1d",
    "auto_run_time": "22:15",    # Uhrzeit für den automatischen Tageszyklus
    # API-Keys (Umgebungsvariablen FMP_API_KEY/TIINGO_API_KEY haben Vorrang)
    "fmp_api_key": "",
    "tiingo_api_key": "",
    # FRED-API-Key (optional, kostenlos: fred.stlouisfed.org/docs/api/api_key.html)
    # — macht den Makro-Abruf zuverlässig, wenn fredgraph.csv blockiert
    "fred_api_key": "",
}


def load_settings(profile: str = "live") -> dict:
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))  # tiefe Kopie
    file = PROFILE_FILES.get(profile, SETTINGS_FILE)
    if file.exists():
        try:
            settings.update(json.loads(file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    elif profile == "test" and SETTINGS_FILE.exists():
        # Erststart des Test-Profils: vom Live-Profil erben (ohne Schalter)
        try:
            settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
            settings["trading_active"] = False
        except (json.JSONDecodeError, OSError):
            pass
    _export_keys_to_env(settings)
    return settings


def save_settings(settings: dict, profile: str = "live") -> None:
    DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    file = PROFILE_FILES.get(profile, SETTINGS_FILE)
    file.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    _export_keys_to_env(settings)


def get_api_key(name: str) -> str:
    """API-Key: Umgebungsvariable schlägt settings.json.

    name: "fmp" oder "tiingo".
    """
    env = os.environ.get(f"{name.upper()}_API_KEY", "").strip()
    return env or str(load_settings().get(f"{name}_api_key", "")).strip()


def _export_keys_to_env(settings: dict) -> None:
    """Keys aus den Settings in die Umgebung spiegeln, damit auch Module,
    die nur Umgebungsvariablen lesen (z.B. der Tiingo-Kursprovider),
    sie sehen. Bereits gesetzte Umgebungsvariablen gewinnen."""
    for name in ("fmp", "tiingo", "fred"):
        env_name = f"{name.upper()}_API_KEY"
        value = str(settings.get(f"{name}_api_key", "")).strip()
        if value and not os.environ.get(env_name):
            os.environ[env_name] = value
