"""Financial Modeling Prep: tiefe Quartals-Historie (mehrere Jahre), API-Key nötig.

Kostenloser Key: https://site.financialmodelingprep.com → Registrieren.
Key als Umgebungsvariable FMP_API_KEY setzen oder in der GUI unter
Einstellungen eintragen.

Grenzen des Gratis-Tarifs (Stand Mitte 2026):
- ~250 Requests/Tag; pro Aktie brauchen wir 3 (GuV, Bilanz, Cashflow),
  also ~80 Aktien/Tag Backfill. Der Abruf ist resume-fähig: einmal per
  FMP gefüllte Aktien werden markiert und nicht erneut abgefragt, beim
  nächsten Lauf geht es mit den restlichen weiter.
- überwiegend US-Titel; für europäische Symbole scheitert FMP oft und
  es greift automatisch der Yahoo-Fallback.
"""

from __future__ import annotations

import pandas as pd
import requests

from .base import FundamentalsProvider, ProviderLimitReached

_BASE = "https://financialmodelingprep.com/api/v3"
_QUARTERS = 60  # bis zu 15 Jahre Historie

_INCOME_MAP = {
    "revenue": "revenue",
    "gross_profit": "grossProfit",
    "operating_income": "operatingIncome",
    "net_income": "netIncome",
    "ebitda": "ebitda",
    "eps": "epsdiluted",
    "shares_outstanding": "weightedAverageShsOutDil",
}
_BALANCE_MAP = {
    "total_assets": "totalAssets",
    "total_equity": "totalStockholdersEquity",
    "total_debt": "totalDebt",
    "cash": "cashAndCashEquivalents",
    "current_assets": "totalCurrentAssets",
    "current_liabilities": "totalCurrentLiabilities",
}
_CASHFLOW_MAP = {
    "operating_cashflow": "operatingCashFlow",
    "capex": "capitalExpenditure",
    "free_cashflow": "freeCashFlow",
}


class FmpProvider(FundamentalsProvider):
    name = "fmp"

    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    def available(self) -> bool:
        return bool(self.api_key)

    def fetch_quarterly(self, symbol: str) -> pd.DataFrame:
        income = self._get(f"income-statement/{symbol}")
        balance = self._get(f"balance-sheet-statement/{symbol}")
        cashflow = self._get(f"cash-flow-statement/{symbol}")

        parts = [
            _extract(income, _INCOME_MAP),
            _extract(balance, _BALANCE_MAP),
            _extract(cashflow, _CASHFLOW_MAP),
        ]
        df = pd.concat(parts, axis=1).sort_index()
        return df.dropna(how="all")

    def _get(self, path: str) -> list[dict]:
        resp = requests.get(
            f"{_BASE}/{path}",
            params={"period": "quarter", "limit": _QUARTERS, "apikey": self.api_key},
            timeout=30,
        )
        if resp.status_code == 429:
            raise ProviderLimitReached("FMP: Tageslimit erreicht (HTTP 429)")
        if resp.status_code in (401, 403):
            body = resp.text[:200]
            if "Limit Reach" in body:  # FMP meldet das Limit teils als 403
                raise ProviderLimitReached("FMP: Tageslimit erreicht")
            raise ValueError(f"FMP: Zugriff verweigert (HTTP {resp.status_code}) — API-Key prüfen")
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "Error Message" in str(data):
            raise ValueError(f"FMP: {data}")
        return data if isinstance(data, list) else []


def _extract(records: list[dict], mapping: dict[str, str]) -> pd.DataFrame:
    rows = {}
    for record in records:
        fiscal = record.get("date")
        if not fiscal:
            continue
        rows[pd.Timestamp(fiscal)] = {
            field: record.get(src) for field, src in mapping.items()
        }
    df = pd.DataFrame.from_dict(rows, orient="index")
    return df.groupby(level=0).first() if not df.empty else df
