"""Aktien-Universen: welche Titel analysiert werden.

Drei Arten, alle über load_universe(key) erreichbar:

1. Index-Universen — Mitgliederlisten von Wikipedia, monatlich gecacht
   (S&P 500, Nasdaq 100, DAX, SMI, EuroStoxx 50, FTSE 100).
2. MSCI World — aus den veröffentlichten Holdings des iShares Core MSCI
   World UCITS ETF (~1.400 Titel), monatlich gecacht. Ticker werden über
   die Börsen-Spalte bestmöglich in Yahoo-Schreibweise übersetzt.
3. Eigene Watchlists — Textdateien in watchlists/, ein Symbol pro Zeile
   (Yahoo-Schreibweise), '#' beginnt einen Kommentar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from io import StringIO

import pandas as pd
import requests

from .config import DATA_DIR, WATCHLIST_DIR

UNIVERSE_CACHE_DIR = DATA_DIR / "universe_cache"

_UA = {"User-Agent": "Mozilla/5.0"}

_SYMBOL_KEYWORDS = ("ticker", "symbol")
_NAME_KEYWORDS = ("company", "security", "name")
_SECTOR_KEYWORDS = ("sector", "industry", "country")


@dataclass
class UniverseSpec:
    label: str                 # Anzeigename in der GUI
    url: str = ""
    suffix: str = ""           # Yahoo-Suffix für die Börse, z.B. ".DE" für Xetra
    dot_to_dash: bool = False  # Yahoo schreibt Klassenaktien BRK.B als BRK-B


UNIVERSES: dict[str, UniverseSpec] = {
    "sp500": UniverseSpec(
        "S&P 500 (USA)",
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", dot_to_dash=True,
    ),
    "nasdaq100": UniverseSpec(
        "Nasdaq 100 (USA)",
        "https://en.wikipedia.org/wiki/Nasdaq-100", dot_to_dash=True,
    ),
    "dax": UniverseSpec("DAX (Deutschland)", "https://en.wikipedia.org/wiki/DAX", suffix=".DE"),
    "smi": UniverseSpec(
        "SMI (Schweiz)", "https://en.wikipedia.org/wiki/Swiss_Market_Index", suffix=".SW"
    ),
    "eurostoxx50": UniverseSpec(
        "EuroStoxx 50 (Europa)", "https://en.wikipedia.org/wiki/EURO_STOXX_50"
    ),
    "ftse100": UniverseSpec(
        "FTSE 100 (UK)", "https://en.wikipedia.org/wiki/FTSE_100_Index",
        suffix=".L", dot_to_dash=True,
    ),
    "msci_world": UniverseSpec("MSCI World (~1.400 Titel)"),
}

# iShares Core MSCI World UCITS ETF (IWDA) — veröffentlichte Holdings als CSV
MSCI_WORLD_URL = (
    "https://www.ishares.com/uk/individual/en/products/251882/"
    "ishares-msci-world-ucits-etf-acc-fund/1506575576011.ajax"
    "?fileType=csv&fileName=IWDA_holdings&dataType=fund"
)

# Börse (iShares-Schreibweise) → Yahoo-Suffix. Bewusst best effort:
# nicht zuordenbare Börsen werden übersprungen und gezählt.
EXCHANGE_SUFFIX = {
    "nasdaq": "", "new york stock exchange": "", "nyse": "", "cboe bzx": "",
    "toronto stock exchange": ".TO",
    "london stock exchange": ".L",
    "xetra": ".DE", "deutsche boerse": ".DE",
    "six swiss exchange": ".SW",
    "euronext amsterdam": ".AS", "euronext paris": ".PA",
    "euronext brussels": ".BR", "euronext lisbon": ".LS",
    "borsa italiana": ".MI", "milan stock exchange": ".MI",
    "bolsa de madrid": ".MC", "madrid stock exchange": ".MC",
    "wiener boerse": ".VI", "vienna stock exchange": ".VI",
    "irish stock exchange": ".IR", "euronext dublin": ".IR",
    "omx nordic exchange stockholm": ".ST", "stockholm stock exchange": ".ST",
    "omx nordic exchange helsinki": ".HE", "helsinki stock exchange": ".HE",
    "omx nordic exchange copenhagen": ".CO", "copenhagen stock exchange": ".CO",
    "oslo bors": ".OL", "oslo stock exchange": ".OL",
    "tokyo stock exchange": ".T", "tokyo": ".T",
    "hong kong stock exchange": ".HK", "hong kong exchanges": ".HK",
    "asx": ".AX", "australian securities exchange": ".AX",
    "new zealand stock exchange": ".NZ",
    "singapore exchange": ".SI",
    "tel aviv stock exchange": ".TA",
}


def universe_labels() -> dict[str, str]:
    """key → Anzeigename, für die GUI-Auswahl (inkl. Watchlists)."""
    labels = {key: spec.label for key, spec in UNIVERSES.items()}
    if WATCHLIST_DIR.exists():
        for f in sorted(WATCHLIST_DIR.glob("*.txt")):
            labels[f.stem] = f"Watchlist: {f.stem}"
    return labels


def load_universe(key: str) -> pd.DataFrame:
    """Titel eines Universums als DataFrame mit symbol, name, sector."""
    if key == "msci_world":
        return _load_msci_world()
    if key in UNIVERSES:
        return _load_wikipedia_index(key)

    watchlist_file = WATCHLIST_DIR / f"{key}.txt"
    if watchlist_file.exists():
        return _load_watchlist(watchlist_file)

    known = ", ".join(sorted(UNIVERSES))
    raise ValueError(f"Unbekanntes Universum {key!r}. Bekannt: {known} sowie Watchlists in {WATCHLIST_DIR}.")


def _load_watchlist(path) -> pd.DataFrame:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        code, _, comment = line.partition("#")
        symbol = code.strip()
        if symbol:
            rows.append({"symbol": symbol, "name": comment.strip(), "sector": ""})
    if not rows:
        raise ValueError(f"Watchlist {path} enthält keine Symbole")
    return pd.DataFrame(rows).drop_duplicates(subset=["symbol"])


def _cache_path(key: str):
    return UNIVERSE_CACHE_DIR / f"{key}_{date.today():%Y-%m}.csv"


def _load_wikipedia_index(key: str) -> pd.DataFrame:
    spec = UNIVERSES[key]
    cache_file = _cache_path(key)
    if cache_file.exists():
        return pd.read_csv(cache_file)

    resp = requests.get(spec.url, headers=_UA, timeout=30)
    resp.raise_for_status()
    df = _pick_components_table(pd.read_html(StringIO(resp.text)))

    symbols = df[_find_col(df, _SYMBOL_KEYWORDS)].astype(str).str.strip()
    if spec.dot_to_dash:
        symbols = symbols.str.rstrip(".").str.replace(".", "-", regex=False)
    # Suffix nur anhängen, wenn noch keiner dransteht (Airbus steht z.B.
    # als AIR.PA in der DAX-Liste — Heimatbörse Paris)
    has_exchange = symbols.str.contains(".", regex=False)
    symbols = symbols.where(has_exchange, symbols + spec.suffix)

    sector_col = _find_col(df, _SECTOR_KEYWORDS)
    result = pd.DataFrame(
        {
            "symbol": symbols,
            "name": df[_find_col(df, _NAME_KEYWORDS)],
            "sector": df[sector_col] if sector_col else "",
        }
    ).dropna(subset=["symbol"]).drop_duplicates(subset=["symbol"])

    UNIVERSE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(cache_file, index=False)
    return result


def _load_msci_world() -> pd.DataFrame:
    cache_file = _cache_path("msci_world")
    if cache_file.exists():
        return pd.read_csv(cache_file)

    resp = requests.get(MSCI_WORLD_URL, headers=_UA, timeout=120)
    resp.raise_for_status()

    # iShares-CSV hat einige Metadaten-Zeilen vor dem Header
    lines = resp.text.splitlines()
    header_idx = next(
        (i for i, line in enumerate(lines) if line.lower().startswith("ticker")), None
    )
    if header_idx is None:
        raise ValueError("iShares-Holdings-CSV: Header nicht gefunden — Format geändert?")
    df = pd.read_csv(StringIO("\n".join(lines[header_idx:])))
    df.columns = [str(c).strip().lower() for c in df.columns]

    if not {"ticker", "name"} <= set(df.columns):
        raise ValueError("iShares-Holdings-CSV: erwartete Spalten fehlen — Format geändert?")
    # nur Aktien, kein Cash/Futures
    if "asset class" in df.columns:
        df = df[df["asset class"].astype(str).str.lower().str.contains("equity")]

    rows, skipped = [], set()
    for _, r in df.iterrows():
        ticker = str(r.get("ticker", "")).strip()
        if not ticker or ticker == "-" or ticker.lower() == "nan":
            continue
        exchange = str(r.get("exchange", "")).strip().lower()
        suffix = _match_exchange(exchange)
        if suffix is None:
            skipped.add(exchange or "?")
            continue
        symbol = ticker.replace(" ", "-")
        if suffix == "":
            symbol = symbol.rstrip(".").replace(".", "-")  # US-Klassenaktien BRK.B → BRK-B
        elif "." not in symbol:
            symbol = symbol + suffix
        rows.append(
            {"symbol": symbol, "name": r.get("name", ""), "sector": r.get("sector", "")}
        )
    if skipped:
        print(f"MSCI World: {len(skipped)} Börsen ohne Yahoo-Zuordnung übersprungen: "
              f"{', '.join(sorted(skipped))}")

    result = pd.DataFrame(rows).drop_duplicates(subset=["symbol"])
    UNIVERSE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(cache_file, index=False)
    return result


def _match_exchange(exchange: str) -> str | None:
    for key, suffix in EXCHANGE_SUFFIX.items():
        if key in exchange:
            return suffix
    return None


def _find_col(df: pd.DataFrame, keywords: tuple[str, ...]) -> str | None:
    for keyword in keywords:
        for col in df.columns:
            if keyword in str(col).lower():
                return col
    return None


def _pick_components_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    """Wikipedia-Seiten haben viele Tabellen; wir suchen die Mitgliederliste:
    die erste mit Symbol- und Namensspalte und genug Zeilen."""
    for table in tables:
        table.columns = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c)
                         for c in table.columns]
        if len(table) >= 10 and _find_col(table, _SYMBOL_KEYWORDS) and _find_col(table, _NAME_KEYWORDS):
            return table
    raise ValueError("Keine Mitgliederliste auf der Seite gefunden – Layout geändert?")
