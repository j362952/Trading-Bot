"""Gemischte Börsenkalender: Feiertagslücken dürfen Titel nicht aus dem Ranking werfen."""

import unittest

import numpy as np
import pandas as pd

from tradingbot.strategies.base import aligned_closes
from tradingbot.strategies.momentum import MomentumRotation
from tradingbot.strategies.momo_quality import VolAdjMomentumQuality


def _bars(dates, seed):
    rng = np.random.default_rng(seed)
    px = 100 * np.exp(np.cumsum(rng.normal(0.0008, 0.01, len(dates))))
    return pd.DataFrame({"Close": px}, index=dates)


class AlignedClosesTest(unittest.TestCase):
    def test_fills_short_gaps_only(self):
        d = pd.bdate_range("2024-01-01", periods=20)
        a = pd.DataFrame({"Close": range(20)}, index=d)
        b = pd.DataFrame({"Close": [1.0] * 20}, index=d).drop(d[[3, 10, 11, 12, 13, 14, 15, 16]])
        b = b.iloc[1:]                                   # beginnt einen Tag später
        out = aligned_closes({"A": a, "B": b}, max_fill=5)
        self.assertTrue(np.isnan(out.loc[d[0], "B"]))    # nichts vor dem ersten Kurs erfinden
        self.assertEqual(out.loc[d[3], "B"], 1.0)        # Feiertag überbrückt
        self.assertTrue(np.isnan(out.loc[d[16], "B"]))   # 7er-Lücke: nur 5 Tage gefüllt


class MixedCalendarStrategyTest(unittest.TestCase):
    def setUp(self):
        days = pd.bdate_range("2018-01-01", "2021-12-31")
        rng = np.random.default_rng(1)
        us_hol = days[rng.choice(len(days), 40, replace=False)]
        de_hol = days[rng.choice(len(days), 40, replace=False)]
        self.bars = {}
        for k in range(4):
            self.bars[f"US{k}"] = _bars(days, k).drop(us_hol, errors="ignore")
            self.bars[f"DE{k}.DE"] = _bars(days, 10 + k).drop(de_hol, errors="ignore")

    def test_moqu_holds_positions(self):
        m = VolAdjMomentumQuality(top_n=3, quality_weight=0).target_matrix(self.bars)
        held = m.loc["2019":].sum(axis=1)
        self.assertGreater(held.mean(), 2.5)             # vorher: meist 0–1 Positionen

    def test_momentum_holds_positions(self):
        m = MomentumRotation(top_n=3).target_matrix(self.bars)
        self.assertGreater(m.loc["2019":].sum(axis=1).mean(), 2.5)


if __name__ == "__main__":
    unittest.main()
