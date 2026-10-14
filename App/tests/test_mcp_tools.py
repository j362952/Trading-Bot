"""MCP-Werkzeuge: Schreibschutz und Treue des MoQu-Rankings zur Strategie."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from tradingbot import mcp_tools
from tradingbot.strategies.momo_quality import VolAdjMomentumQuality


class RunSqlTest(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "hub.db"
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE companies (symbol TEXT, name TEXT)")
        conn.execute("INSERT INTO companies VALUES ('AAA', 'Alpha')")
        conn.commit()
        conn.close()
        self.p = mock.patch.dict(mcp_tools.DATABASES, {"hub": self.db})
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_select_works(self):
        out = mcp_tools.run_sql("SELECT * FROM companies")
        self.assertEqual(out["rows"], [["AAA", "Alpha"]])

    def test_writes_are_rejected(self):
        for sql in ["DELETE FROM companies",
                    "WITH x AS (SELECT 1) INSERT INTO companies VALUES ('B','b')",
                    "SELECT 1; DROP TABLE companies",
                    "SELECT * FROM companies WHERE 1=1 UNION SELECT load_extension('x'), 1"]:
            with self.assertRaises(Exception, msg=sql):
                mcp_tools.run_sql(sql)
        out = mcp_tools.run_sql("SELECT COUNT(*) FROM companies")
        self.assertEqual(out["rows"], [[1]])

    def test_row_limit(self):
        out = mcp_tools.run_sql("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 "
                                "FROM n WHERE i < 50) SELECT i FROM n", max_rows=10)
        self.assertEqual(len(out["rows"]), 10)
        self.assertTrue(out["truncated"])


class MoquFidelityTest(unittest.TestCase):
    """Die Momentaufnahme muss an Rebalance-Tagen exakt die Titel wählen,
    die die Strategie selbst wählt (ohne Halte-Puffer)."""

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        rng = np.random.default_rng(7)
        dates = pd.bdate_range("2016-01-01", "2020-12-31")
        self.bars = {}
        for k in range(8):
            drift = rng.normal(0.0003, 0.0004)
            px = 100 * np.exp(np.cumsum(rng.normal(drift, 0.015, len(dates))))
            df = pd.DataFrame({"Open": px, "High": px, "Low": px, "Close": px,
                               "Volume": 1}, index=pd.Index(dates, name="Date"))
            df.to_csv(tmp / f"S{k}.csv")
            self.bars[f"S{k}"] = df
        self.patches = [
            mock.patch.object(mcp_tools, "PRICE_DIR", tmp),
            mock.patch.object(mcp_tools, "HUB_DB", tmp / "none.db"),
            mock.patch("tradingbot.strategies.momo_quality.HUB_DB", tmp / "none.db"),
            mock.patch("tradingbot.strategies.momo_quality.SCREENER_DB", tmp / "none.db"),
            mock.patch.object(mcp_tools, "load_settings", lambda *a, **k: {}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_matches_strategy_on_rebalance_days(self):
        strat = VolAdjMomentumQuality(top_n=3, exit_rank_mult=1.0)
        matrix = strat.target_matrix(self.bars)
        checked = 0
        for i in range(273, len(matrix), 21 * 4):   # 273 = 13 × 21 → Rebalance-Tag
            day = matrix.index[i]
            expected = sorted(matrix.columns[matrix.loc[day] > 0])
            out = mcp_tools.moqu_ranking(symbols=list(self.bars), as_of=str(day.date()), top_n=3)
            got = sorted(r["symbol"] for r in out["ranking"] if r["selected"])
            self.assertEqual(expected, got, msg=str(day.date()))
            checked += 1
        self.assertGreater(checked, 5)


if __name__ == "__main__":
    unittest.main()
