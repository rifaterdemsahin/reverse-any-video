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

    def test_price_is_exactly_what_the_customer_sees(self):
        q = p.quote(p.estimate(306.4))
        self.assertEqual(q["price"], round(sum(l["display"] for l in q["lines"]) + q["shown"]["margin"] + q["shown"]["card_fee"], 2))
        self.assertEqual(round(q["price"], 2), q["price"])
        self.assertGreater(q["price"], q["cost"])

    def test_no_line_is_shown_as_zero(self):
        q = p.quote(p.estimate(5))                      # very short video: every line is tiny
        self.assertTrue(all(l["display"] >= 0.01 for l in q["lines"]))
        self.assertGreaterEqual(q["shown"]["margin"], 0.01)

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

    def test_packages_give_whole_videos_and_cover_our_fee(self):
        pk = {x["pays"]: x for x in p.package_estimates(300)}
        self.assertEqual(set(pk), {5.00, 20.00, 50.00})
        for amount, x in pk.items():
            self.assertEqual(x["videos"], int(amount // x["credit_per_video"]))
            self.assertGreater(x["net_to_us"], 0)
            self.assertLess(x["card_fee"], amount)
        self.assertLess(pk[5.00]["videos"], pk[20.00]["videos"])
        self.assertLess(pk[20.00]["videos"], pk[50.00]["videos"])

    def test_storyboard_panels_capped(self):
        self.assertLessEqual(p.estimate(3000)["panels"], p.STORYBOARD_SHOTS)
        self.assertEqual(p.estimate(120, storyboard=False)["panels"], 0)


if __name__ == "__main__":
    unittest.main()
