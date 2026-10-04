"""A quote cannot replace a missing exposure total with a premium or a partial sum."""
import copy
import unittest

import quote


class MissingExposureTotal(unittest.TestCase):
    def setUp(self):
        self.exposure = {
            "perspective": "acme", "currency": "GBP", "total": None,
            "attachment": {"amount": 100.0, "currency": "GBP"},
            "regimes": [
                {"name": "known", "amount": 1_000.0, "controls": []},
                {"name": "unpriced", "amount": None, "controls": []},
            ],
        }
        self.terms = {
            "currency": "GBP", "limit": {"amount": 500.0, "currency": "GBP"},
            "rate": 0.04, "load": 0.25, "exclusions": [],
        }

    def test_unknown_total_refuses_without_pricing_or_mutating_the_input(self):
        before = copy.deepcopy(self.exposure)
        with self.assertRaisesRegex(quote.Refused, r"missing instrument:.*acme.*exposure.*total"):
            quote.price(self.exposure, self.terms)
        self.assertEqual(self.exposure, before)

    def test_known_subset_and_excluded_unpriced_regime_cannot_supply_missing_total(self):
        terms = dict(self.terms, exclusions=[{"regime": "unpriced", "control_ids": []}])
        with self.assertRaisesRegex(quote.Refused, r"missing instrument:.*exposure.*total"):
            quote.price(self.exposure, terms)

    def test_known_zero_total_is_distinct_from_a_missing_instrument(self):
        exposure = dict(self.exposure, total=0.0, regimes=[])
        worked = quote.price(exposure, self.terms)
        self.assertEqual(worked["insured"], 0.0)
        self.assertEqual(worked["layer"], 0.0)
        self.assertEqual(worked["premium"], 0.0)

    def test_known_total_preserves_the_existing_exclusion_and_layer_formula(self):
        exposure = dict(self.exposure, total=1_000.0, regimes=[{"name": "known", "amount": 200.0, "controls": []}])
        terms = dict(self.terms, exclusions=[{"regime": "known", "control_ids": []}])
        self.assertEqual(quote.price(exposure, terms), {
            "excluded": 200.0, "insured": 800.0, "attachment": 100.0,
            "limit": 500.0, "layer": 500.0, "premium": 25.0,
        })


if __name__ == "__main__":
    unittest.main()
