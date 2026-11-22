"""Evals for pricing: the rules a customer relies on, checked over a range of video lengths.

Run: python -m unittest discover -s evals -p "eval_*.py" -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pricing  # noqa: E402

LENGTHS = [1, 5, 30, 60, 180, 300, 600, 900, 1200, 1800]


class PricingRules(unittest.TestCase):
    def test_price_is_exactly_the_sum_of_what_the_customer_sees(self):
        for secs in LENGTHS:
            q = pricing.quote(pricing.estimate(secs))
            total = sum(l["display"] for l in q["lines"]) + q["shown"]["margin"] + q["shown"]["card_fee"]
            self.assertAlmostEqual(q["price"], round(total, 2), places=2, msg=f"{secs}s")

    def test_no_shown_amount_is_zero(self):
        for secs in LENGTHS:
            q = pricing.quote(pricing.estimate(secs))
            for l in q["lines"]:
                self.assertGreaterEqual(l["display"], 0.01, f"{secs}s {l['short']}")
            self.assertGreaterEqual(q["shown"]["margin"], 0.01)
            self.assertGreaterEqual(q["shown"]["card_fee"], 0.01)

    def test_price_never_falls_as_the_video_gets_longer(self):
        prices = [pricing.quote(pricing.estimate(s))["price"] for s in LENGTHS]
        self.assertEqual(prices, sorted(prices))

    def test_margin_is_close_to_ten_percent_of_cost(self):
        for secs in LENGTHS:
            q = pricing.quote(pricing.estimate(secs))
            # costs are shown rounded up, so the margin on the shown costs is at least 10%
            self.assertGreaterEqual(q["shown"]["margin"], round(q["cost"] * 0.10, 2) - 0.01, f"{secs}s")

    def test_packs_are_whole_dollars_and_buy_whole_videos(self):
        for secs in LENGTHS:
            for pack in pricing.package_estimates(secs):
                self.assertEqual(pack["pays"], int(pack["pays"]))
                self.assertEqual(pack["videos"], int(pack["pays"] // pack["credit_per_video"]))
                self.assertGreater(pack["net_to_us"], 0, f"{secs}s pack {pack['pays']}")

    def test_bigger_packs_give_more_videos(self):
        for secs in LENGTHS:
            videos = [p["videos"] for p in pricing.package_estimates(secs)]
            self.assertEqual(videos, sorted(videos))

    def test_customer_is_told_what_is_kept(self):
        text = " ".join(pricing.quote(pricing.estimate(120))["assumptions"])
        self.assertIn("deliverables only", text)
        self.assertIn("not delivered", text)


if __name__ == "__main__":
    unittest.main()
