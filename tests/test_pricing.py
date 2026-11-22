"""Cost calculator: margin, rounding and monotonic pricing. Pure functions, no network."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pricing as p  # noqa: E402


class Quote(unittest.TestCase):
    def test_margin_is_ten_percent_of_cost(self):
        q = p.quote(p.estimate(306.4))
        self.assertAlmostEqual(q["margin"], q["cost"] * 0.10, places=5)

    def test_price_covers_cost_plus_margin_and_rounds_up_to_cents(self):
        q = p.quote(p.estimate(306.4))
        self.assertGreaterEqual(q["price"], q["cost"] * 1.10)
        self.assertEqual(round(q["price"], 2), q["price"])
        self.assertEqual(q["price"], math.ceil(round((q["cost"] + q["margin"] + q["card_fee_estimate"]) * 100, 6)) / 100)

    def test_longer_video_costs_more(self):
        short, long_ = p.quote(p.estimate(60)), p.quote(p.estimate(600))
        self.assertGreater(long_["cost"], short["cost"])
        self.assertGreater(long_["price"], short["price"])

    def test_every_line_has_a_detail_and_every_rate_a_source(self):
        q = p.quote(p.estimate(120))
        self.assertEqual(len(q["lines"]), 4)
        self.assertTrue(all(line["detail"] for line in q["lines"]))
        self.assertTrue(all(r["source"] for r in q["rates"].values()))

    def test_customer_is_told_what_is_kept(self):
        q = p.quote(p.estimate(120))
        text = " ".join(q["assumptions"])
        self.assertIn("deliverables only", text)
        self.assertIn("not delivered", text)
        labels = [line["label"] for line in q["lines"]]
        self.assertTrue(any("Fly.io" in l for l in labels))
        self.assertTrue(any("Azure" in l for l in labels))

    def test_storyboard_panels_capped(self):
        self.assertLessEqual(p.estimate(3000)["panels"], p.STORYBOARD_SHOTS)
        self.assertEqual(p.estimate(120, storyboard=False)["panels"], 0)


if __name__ == "__main__":
    unittest.main()
