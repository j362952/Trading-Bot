"""Pfade und lokale Einstellungen (API-Keys etc.).

Einstellungen liegen in data/settings.json — die Datei ist per .gitignore
vom Versionieren ausgeschlossen, damit der API-Key nicht im Repo landet.
Umgebungsvariablen haben Vorrang vor der Datei.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "screener.db"
REPORTS_DIR = PROJECT_ROOT / "reports"
WATCHLIST_DIR = PROJECT_ROOT / "watchlists"
ANALYSE_MD = PROJECT_ROOT / "ANALYSE.md"

SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULT_SETTINGS = {
    # Financial Modeling Prep: kostenloser Key von https://site.financialmodelingprep.com
    "fmp_api_key": "",
    # Fundamentaldaten gelten so viele Tage als frisch und werden nicht neu geladen
    "max_age_days": 30,
}


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def save_settings(settings: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def get_fmp_key() -> str:
    """FMP-API-Key: Umgebungsvariable FMP_API_KEY schlägt settings.json."""
    return os.environ.get("FMP_API_KEY", "").strip() or load_settings()["fmp_api_key"].strip()
