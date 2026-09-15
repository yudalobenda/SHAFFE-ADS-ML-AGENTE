from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from core.test_engine import (  # noqa: E402
    SAMPLE_CORRECT,
    SAMPLE_INSUFFICIENT,
    SAMPLE_STOP_ADS,
    SAMPLE_WINNER,
    classify_test,
)


class TestEngineTests(unittest.TestCase):
    def test_no_sample_and_no_organic_sales_is_insufficient_not_a_verdict(self):
        r = classify_test(spend=200, visits=10, roas=None, units_sold=0, clicks=0)
        self.assertEqual(r.sample_status, SAMPLE_INSUFFICIENT)
        self.assertIsNone(r.suggested_decision)

    def test_organic_sales_without_ads_is_correct_not_insufficient(self):
        r = classify_test(spend=None, visits=40, roas=None, units_sold=5, clicks=None)
        self.assertEqual(r.sample_status, SAMPLE_CORRECT)
        self.assertEqual(r.suggested_decision, "mantener")

    def test_high_roas_with_real_sample_is_winner(self):
        r = classify_test(spend=8000, visits=150, roas=6.0, units_sold=4, clicks=50)
        self.assertEqual(r.sample_status, SAMPLE_WINNER)
        self.assertEqual(r.suggested_decision, "escalar")

    def test_very_low_roas_with_real_sample_is_stop_ads(self):
        r = classify_test(spend=8000, visits=150, roas=0.8, units_sold=0, clicks=50)
        self.assertEqual(r.sample_status, SAMPLE_STOP_ADS)
        self.assertEqual(r.suggested_decision, "revertir")

    def test_sufficient_sample_never_stays_without_a_suggested_decision(self):
        """Un test con muestra suficiente SIEMPRE recibe una sugerencia
        (aunque sea 'repetir' por ambigua) -- nunca queda indefinido."""
        for roas in (None, 0.5, 1.9, 2.0, 3.0, 3.9, 4.0, 10.0):
            r = classify_test(spend=6000, visits=200, roas=roas, units_sold=1, clicks=40)
            self.assertNotEqual(r.sample_status, SAMPLE_INSUFFICIENT)
            self.assertIsNotNone(r.suggested_decision)


if __name__ == "__main__":
    unittest.main()
