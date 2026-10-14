import unittest

import run_sentiment_eval as ev


class MetricsTest(unittest.TestCase):
    def test_perfect_and_gate_metrics(self):
        gold = ["positive", "negative", "neutral", "negative"]
        m = ev.metrics(gold, gold, [0.5, -0.6, 0.0, -0.1], threshold=-0.2)
        self.assertEqual(m["accuracy"], 1.0)
        self.assertAlmostEqual(m["macro_f1"], 1.0)
        self.assertEqual(m["neg_caught"], 0.5)    # -0.1 liegt über der Schwelle
        self.assertEqual(m["false_block"], 0.0)

    def test_kappa(self):
        a = ["positive", "negative", "neutral", "neutral"]
        self.assertAlmostEqual(ev.cohen_kappa(a, a), 1.0)
        self.assertLess(ev.cohen_kappa(a, ["neutral"] * 4), 0.01)


if __name__ == "__main__":
    unittest.main()
