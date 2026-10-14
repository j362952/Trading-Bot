"""NEUE Strategie: Vol-adjustiertes Momentum mit Qualitäts-Overlay ("MoQu").

Was ist neu gegenüber der einfachen Momentum-Rotation?

1. **Risikoadjustiertes Momentum**: gerankt wird nicht die rohe Rendite,
   sondern Rendite ÷ realisierte Volatilität. Zwei Aktien mit +30 % sind
   nicht gleich — die ruhig gestiegene setzt ihren Trend statistisch
   verlässlicher fort als die wild schwankende (vol-skaliertes Momentum,
   u.a. Barroso/Santa-Clara 2015: verbessert Sharpe und entschärft
   Momentum-Crashs).
2. **Qualitäts-Overlay aus reporteten Quartalszahlen** (Daten-Hub,
   sofern vorhanden): profitable Firmen (ROE, operative Marge) werden im
   Ranking bevorzugt — Momentum in Qualität statt Momentum in Schrott
   (AQR "Quality Minus Junk"). Point-in-Time-sauber: je Stichtag zählen
   nur Quartale, deren Ende ≥ reporting_lag Tage zurückliegt. Ohne
   Fundamentaldaten läuft die Strategie unverändert (neutraler Rang).
3. **Krisenbremse doppelt**: Titel brauchen positives absolutes Momentum
   (sonst Kasse), und der Regime-Filter der Risk-Schicht (SPY > SMA200)
   blockiert Neueinstiege im Bärenmarkt.

Erwartungsprofil: wie Momentum-Rotation, aber ruhigere Titelauswahl und
weniger Absturzrisiko. Alle Parameter GUI-editierbar.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import DATA_CACHE_DIR, PROJECT_ROOT
from .base import aligned_closes

# Fundamentaldaten: primär der Daten-Hub, sonst die alte (archivierte) Screener-DB
HUB_DB = DATA_CACHE_DIR / "hub.db"
SCREENER_DB = PROJECT_ROOT.parent / "_archiv" / "MarketScreener" / "data" / "screener.db"


@dataclass
class VolAdjMomentumQuality:
    """Hält die top_n Titel nach (Momentum ÷ Volatilität), optional mit
    Qualitäts-Overlay; Rebalance alle rebalance_days Handelstage."""

    lookback: int = 252        # Momentum-Fenster (12 Monate — Sweep-Sieger)
    skip: int = 5              # jüngste Woche ausklammern (Reversal)
    vol_n: int = 60            # Fenster der realisierten Volatilität
    top_n: int = 8
    rebalance_days: int = 21   # ~monatlich
    quality_weight: float = 0.25   # 0 = reines Momentum
    reporting_lag: int = 60    # Tage bis Quartalszahlen als bekannt gelten
    second_lookback: int = 0   # 0 = aus; sonst Blend mit zweitem Momentum-Fenster
    exit_rank_mult: float = 2.0  # Halte-Puffer: Titel fliegt erst raus, wenn sein
                                 # Rang schlechter als top_n × mult ist (senkt Turnover)

    @property
    def name(self) -> str:
        q = f", Q{self.quality_weight:g}" if self.quality_weight > 0 else ""
        return f"MoQu Top{self.top_n} ({self.lookback}d/vol{self.vol_n}{q})"

    def target_matrix(self, bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
        closes = aligned_closes(bars)  # ein Kalender, Feiertagslücken überbrückt

        momentum = closes.shift(self.skip) / closes.shift(self.lookback) - 1
        vol = closes.pct_change(fill_method=None).rolling(self.vol_n).std()
        risk_adj = momentum / vol.replace(0, np.nan)
        if self.second_lookback > 0:
            mom2 = closes.shift(self.skip) / closes.shift(self.second_lookback) - 1
            risk_adj = (risk_adj + mom2 / vol.replace(0, np.nan)) / 2

        quality = self._quality_ranks(list(closes.columns), closes.index)

        values = risk_adj.to_numpy()
        mom_v = momentum.to_numpy()
        out = np.zeros(values.shape)
        current = np.zeros(values.shape[1], dtype=bool)
        for i in range(values.shape[0]):
            if i % self.rebalance_days == 0:
                row = values[i]
                ok = (np.nan_to_num(mom_v[i], nan=-1.0) > 0) & ~np.isnan(row)
                idx = np.where(ok)[0]
                prev = current
                current = np.zeros(values.shape[1], dtype=bool)
                if len(idx):
                    # Ränge 0..1 innerhalb der Kandidaten
                    order = np.argsort(np.argsort(row[idx]))
                    mom_rank = order / max(len(idx) - 1, 1)
                    score = mom_rank
                    if quality is not None and self.quality_weight > 0:
                        q_row = quality[min(i // self.rebalance_days, len(quality) - 1)][idx]
                        score = (1 - self.quality_weight) * mom_rank + self.quality_weight * q_row
                    ranked = idx[np.argsort(score)[::-1]]  # beste zuerst
                    if self.exit_rank_mult > 1.0 and prev.any():
                        # Halte-Puffer: gehaltene Titel innerhalb top_n×mult bleiben
                        keep_zone = set(ranked[: int(self.top_n * self.exit_rank_mult)])
                        kept = [j for j in np.where(prev)[0] if j in keep_zone][: self.top_n]
                        fill = [j for j in ranked if j not in kept][: self.top_n - len(kept)]
                        current[kept + fill] = True
                    else:
                        current[ranked[: self.top_n]] = True
            out[i] = current
        return pd.DataFrame(out, index=closes.index, columns=closes.columns)

    # ------------------------------------------------- Qualitäts-Overlay

    def _quality_ranks(self, symbols: list[str], dates) -> np.ndarray | None:
        """Qualitätsränge (0..1) je Rebalance-Periode × Symbol, Point-in-Time.

        Quelle: Daten-Hub (fundamentals) bzw. alte Screener-DB. Symbole ohne
        Daten bekommen den neutralen Rang 0,5. None, wenn gar keine Daten.
        """
        if self.quality_weight <= 0:
            return None
        db_path, table = ((HUB_DB, "fundamentals") if HUB_DB.exists()
                          else (SCREENER_DB, "quarterly"))
        if not db_path.exists():
            return None
        import sqlite3

        try:
            conn = sqlite3.connect(db_path)
            marks = ",".join("?" for _ in symbols)
            q = pd.read_sql_query(
                f"SELECT symbol, fiscal_date, net_income, total_equity, "
                f"operating_income, revenue FROM {table} WHERE symbol IN ({marks})",
                conn, params=symbols, parse_dates=["fiscal_date"])
            conn.close()
        except Exception:
            return None
        if q.empty:
            return None

        n_periods = len(dates) // self.rebalance_days + 1
        ranks = np.full((n_periods, len(symbols)), 0.5)
        col = {s: j for j, s in enumerate(symbols)}
        for p in range(n_periods):
            asof = dates[min(p * self.rebalance_days, len(dates) - 1)]
            known = q[q["fiscal_date"] <= asof - pd.Timedelta(days=self.reporting_lag)]
            if known.empty:
                continue
            scores = {}
            for symbol, grp in known.groupby("symbol"):
                grp = grp.sort_values("fiscal_date").tail(4)  # TTM
                ni, rev = grp["net_income"].sum(), grp["revenue"].sum()
                oi = grp["operating_income"].sum()
                eq = grp["total_equity"].iloc[-1]
                roe = ni / eq if eq and eq > 0 else np.nan
                margin = oi / rev if rev and rev > 0 else np.nan
                parts = [x for x in (roe, margin) if not np.isnan(x)]
                if parts:
                    scores[symbol] = float(np.mean(parts))
            if len(scores) >= 3:  # unter 3 Titeln ist ein Rang sinnlos
                s = pd.Series(scores).rank(pct=True)
                for symbol, r in s.items():
                    ranks[p, col[symbol]] = r
        return ranks
