"""NEUE Strategie: Regionale Makro-Rotation ("MacroRot").

Kern ist die bewährte vol-adjustierte Momentum-Rotation (wie MoQu, §2.6) —
NEU ist eine **marktspezifische Makro-Schicht** aus dem Daten-Hub
(FRED-Reihen, Seite 1 → "Makro"): jeder Titel wird über sein Börsen-Suffix
einer Region zugeordnet, und jede Region bekommt zu jedem Rebalance-Termin
einen Makro-Score aus 0/1-Voten (verfügbare Voten werden gemittelt,
fehlende Reihen stimmen nicht mit ab — kein Datenzwang):

| Region | Vote | Reihe (FRED) | grün wenn |
|---|---|---|---|
| USA | Fed-Zinsrichtung | DFF | heute ≤ vor rate_lookback Tagen (keine Straffung) |
| USA | Zinskurve | T10Y3M | > 0 (nicht invertiert) |
| USA | Kreditrisiko | BAMLH0A0HYM2 | Spread < SMA(200) |
| USA | Inflationstrend | CPIAUCSL | Jahresrate fällt (3-Monats-Vergleich) |
| Europa | EZB-Zinsrichtung | ECBDFR | heute ≤ vor rate_lookback Tagen |
| Europa | Zinskurve | IRLTLT01DEM156N − ECBDFR | > 0 (DE-10J über Einlagenzins) |
| Europa | Inflationstrend | CP0000EZ19M086NEST | HICP-Jahresrate fällt |
| Andere | — | — | Mittel aus USA/Europa (kein eigener Datensatz) |

Wirkung — zwei Hebel, beide GUI-editierbar:
1. **Tilt**: Ranking = (1−macro_weight)·Momentum-Rang + macro_weight·Regions-Score.
2. **Entry-Gate**: Titel aus Regionen mit Score < gate_threshold werden nicht
   NEU gekauft; Bestände bleiben (Halte-Puffer) — Exits regeln Stops/Signale.

Point-in-Time-Ehrlichkeit:
- Zins-/Spread-/Kurven-Reihen sind Marktdaten (nicht revidiert) und werden
  um 1 Tag verzögert verwendet.
- CPI/HICP sind REVIDIERTE Monatsreihen; sie wirken erst stats_lag_days
  (Default 45) nach Monatsende — das nähert den Publikationstermin an,
  die Revisionsproblematik bleibt (dokumentiert in STRATEGIE.md §2.8).
- Regionszuordnung über Börsen-Suffix ist eine Näherung: CH/UK/Nordics
  laufen unter "Europa" (EZB/Bund als Proxy), Asien/Sonstige neutral.

Ohne hub.db oder ohne Makro-Reihen läuft die Strategie unverändert als
reine vol-adjustierte Momentum-Rotation (alle Scores neutral 0,5).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import DATA_CACHE_DIR

HUB_DB = DATA_CACHE_DIR / "hub.db"

# Marktdaten-Reihen (1 Tag Lag) und Statistik-Reihen (Publikations-Lag)
_MARKET_SERIES = ["DFF", "T10Y3M", "BAMLH0A0HYM2", "ECBDFR", "IRLTLT01DEM156N"]
_STATS_SERIES = ["CPIAUCSL", "CP0000EZ19M086NEST"]

# Börsen-Suffix → Region "europe" (Näherung; CH/UK/Nordics unter EZB/Bund-Proxy)
EUROPE_SUFFIXES = {
    "DE", "F", "PA", "AS", "BR", "LS", "MI", "MC", "VI", "IR",
    "ST", "HE", "CO", "OL", "SW", "L", "WA", "AT",
}


def symbol_region(symbol: str) -> str:
    if "." in symbol:
        suffix = symbol.rsplit(".", 1)[1].upper()
        return "europe" if suffix in EUROPE_SUFFIXES else "other"
    return "us"


@dataclass
class MacroRegionalRotation:
    """Vol-adjustiertes Momentum + regionaler Makro-Score (Fed/EZB)."""

    lookback: int = 252          # Momentum-Fenster (12M, Sweep-Sieger aus §4.1)
    skip: int = 5                # jüngste Woche ausklammern (Reversal)
    vol_n: int = 60              # realisierte Volatilität
    top_n: int = 8
    rebalance_days: int = 21     # ~monatlich
    exit_rank_mult: float = 2.0  # Halte-Puffer (§4.2, robust bestätigt)
    macro_weight: float = 0.25   # Gewicht des Regions-Scores im Ranking (0 = aus)
    gate_threshold: float = 0.3  # Region unter diesem Score → keine NEUEN Käufe
    rate_lookback: int = 126     # Handelstage für die Zinsrichtungs-Frage (~6M)
    stats_lag_days: int = 45     # Publikations-Lag für CPI/HICP (Kalendertage)

    @property
    def name(self) -> str:
        return (f"MacroRot Top{self.top_n} ({self.lookback}d, "
                f"Makro {self.macro_weight:g}/Gate {self.gate_threshold:g})")

    # ------------------------------------------------------------ Signale

    def target_matrix(self, bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
        closes = pd.DataFrame({s: df["Close"] for s, df in bars.items()}).sort_index()
        closes = closes[closes.index.notna()]

        momentum = closes.shift(self.skip) / closes.shift(self.lookback) - 1
        vol = closes.pct_change(fill_method=None).rolling(self.vol_n).std()
        risk_adj = momentum / vol.replace(0, np.nan)

        regions = [symbol_region(s) for s in closes.columns]
        macro = self._region_scores(closes.index)   # DataFrame date × region | None

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
                    order = np.argsort(np.argsort(row[idx]))
                    mom_rank = order / max(len(idx) - 1, 1)
                    if macro is not None and self.macro_weight > 0:
                        m_row = macro.iloc[i]
                        sym_macro = np.array([m_row[regions[j]] for j in idx])
                        score = ((1 - self.macro_weight) * mom_rank
                                 + self.macro_weight * sym_macro)
                        entry_ok = sym_macro >= self.gate_threshold
                    else:
                        score = mom_rank
                        entry_ok = np.ones(len(idx), dtype=bool)
                    ranked_pos = np.argsort(score)[::-1]        # Positionen in idx
                    ranked = idx[ranked_pos]                    # beste zuerst
                    allowed = dict(zip(idx, entry_ok))
                    if self.exit_rank_mult > 1.0 and prev.any():
                        keep_zone = set(ranked[: int(self.top_n * self.exit_rank_mult)])
                        kept = [j for j in np.where(prev)[0] if j in keep_zone][: self.top_n]
                        fill = [j for j in ranked
                                if j not in kept and allowed.get(j, False)
                                ][: self.top_n - len(kept)]
                        current[kept + fill] = True
                    else:
                        picks = [j for j in ranked if allowed.get(j, False)][: self.top_n]
                        current[picks] = True
            out[i] = current
        return pd.DataFrame(out, index=closes.index, columns=closes.columns)

    # -------------------------------------------------- Makro aus dem Hub

    def _load_series(self) -> dict[str, pd.Series]:
        if not HUB_DB.exists():
            return {}
        import sqlite3

        wanted = _MARKET_SERIES + _STATS_SERIES
        try:
            conn = sqlite3.connect(HUB_DB)
            marks = ",".join("?" for _ in wanted)
            df = pd.read_sql_query(
                f"SELECT series, date, value FROM macro_series "
                f"WHERE series IN ({marks}) ORDER BY date",
                conn, params=wanted, parse_dates=["date"])
            conn.close()
        except Exception:
            return {}
        return {name: grp.set_index("date")["value"].dropna()
                for name, grp in df.groupby("series") if len(grp) > 10}

    def _region_scores(self, dates: pd.DatetimeIndex) -> pd.DataFrame | None:
        """Score je Handelstag × Region (0..1); None = keine Makro-Daten."""
        raw = self._load_series()
        if not raw:
            return None

        def aligned(name: str) -> pd.Series | None:
            s = raw.get(name)
            if s is None:
                return None
            if name in _STATS_SERIES:  # Publikations-Lag für revidierte Statistiken
                s = s.copy()
                s.index = s.index + pd.Timedelta(days=self.stats_lag_days)
            union = dates.union(s.index)
            return s.reindex(union).ffill().reindex(dates).shift(1)  # +1 Tag Lag

        def not_rising(s: pd.Series) -> pd.Series:
            return (s <= s.shift(self.rate_lookback) + 1e-9).astype(float)

        def yoy_falling(s: pd.Series) -> pd.Series:
            yoy = s / s.shift(252) - 1
            return (yoy < yoy.shift(63)).astype(float)

        us_votes, eu_votes = [], []
        dff = aligned("DFF")
        if dff is not None:
            us_votes.append(not_rising(dff))
        curve = aligned("T10Y3M")
        if curve is not None:
            us_votes.append((curve > 0).astype(float))
        hy = aligned("BAMLH0A0HYM2")
        if hy is not None:
            us_votes.append((hy < hy.rolling(200, min_periods=50).mean()).astype(float))
        cpi = aligned("CPIAUCSL")
        if cpi is not None:
            us_votes.append(yoy_falling(cpi))

        ecb = aligned("ECBDFR")
        if ecb is not None:
            eu_votes.append(not_rising(ecb))
        de10 = aligned("IRLTLT01DEM156N")
        if de10 is not None and ecb is not None:
            eu_votes.append(((de10 - ecb) > 0).astype(float))
        hicp = aligned("CP0000EZ19M086NEST")
        if hicp is not None:
            eu_votes.append(yoy_falling(hicp))

        def mean_votes(votes: list[pd.Series]) -> pd.Series:
            if not votes:
                return pd.Series(0.5, index=dates)
            return pd.concat(votes, axis=1).mean(axis=1).fillna(0.5)

        us = mean_votes(us_votes)
        eu = mean_votes(eu_votes)
        other = (us + eu) / 2
        return pd.DataFrame({"us": us, "europe": eu, "other": other}, index=dates)
