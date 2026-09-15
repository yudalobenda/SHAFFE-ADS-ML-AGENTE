from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from core.decision_context import (  # noqa: E402
    aggregate_ads_metrics,
    compute_margin_break_even,
    compute_settled_break_even,
    index_ads_by_item,
)


class DecisionContextTests(unittest.TestCase):
    def test_index_groups_rows_by_item_id(self):
        rows = [{"item_id": "MLA1", "metrics": {}}, {"item_id": "MLA2", "metrics": {}}, {"item_id": "MLA1", "metrics": {}}]
        idx = index_ads_by_item(rows)
        self.assertEqual(len(idx["MLA1"]), 2)
        self.assertEqual(len(idx["MLA2"]), 1)

    def test_aggregate_sums_metrics_across_all_affected_mlas_of_the_group(self):
        """La agregacion es a nivel de TODA la unidad (todas las variantes),
        nunca de un item suelto -- es el punto central de ADS_ACTIONABLE_UNIT
        aplicado a metricas."""
        ads_by_item = {
            "MLA1": [{"metrics": {"cost": 1000, "direct_amount": 5000, "prints": 100, "clicks": 5, "direct_items_quantity": 1}}],
            "MLA2": [{"metrics": {"cost": 500, "direct_amount": 2500, "prints": 50, "clicks": 2, "direct_items_quantity": 1}}],
        }
        ctx = aggregate_ads_metrics(("MLA1", "MLA2"), ads_by_item)
        self.assertEqual(ctx["spend_30d"], 1500)
        self.assertEqual(ctx["units_ads_30d"], 2)
        self.assertAlmostEqual(ctx["roas"], 7500 / 1500)

    def test_item_without_ads_rows_does_not_crash_and_yields_none_roas(self):
        ctx = aggregate_ads_metrics(("MLA_SIN_DATOS",), {})
        self.assertIsNone(ctx["roas"])
        self.assertIsNone(ctx["spend_30d"])

    def test_roas_10_with_8pct_margin_is_below_break_even_not_a_winner(self):
        """Ejemplo real planteado por el usuario: ROAS 10x con margen bruto
        8% -- el ROAS de equilibrio es 1/0.08=12.5x, así que un ROAS de 10x
        (que a simple vista se ve espectacular) en realidad todavía pierde
        plata neta en cada venta hecha vía Ads."""
        # precio efectivo $10.000, costo $9.200 -> margen bruto 8%
        r = compute_margin_break_even(revenue_ads_30d=100_000, units_ads_30d=10, cost=9200)
        self.assertAlmostEqual(r["margin_pct"], 0.08, places=4)
        self.assertAlmostEqual(r["roas_break_even"], 12.5, places=2)
        roas_real = 10.0
        self.assertLess(roas_real, r["roas_break_even"], "ROAS 10x debe quedar POR DEBAJO de su propio break-even (12.5x)")

    def test_negative_gross_margin_has_infinite_break_even(self):
        """Si ya se pierde plata sin gastar en Ads (costo > precio), ningún
        ROAS por alto que sea lo salva -- break-even infinito, nunca 0."""
        r = compute_margin_break_even(revenue_ads_30d=50_000, units_ads_30d=10, cost=6000)  # precio efectivo 5000 < costo
        self.assertEqual(r["roas_break_even"], float("inf"))

    def test_missing_price_or_cost_yields_none_never_a_guessed_break_even(self):
        self.assertIsNone(compute_margin_break_even(revenue_ads_30d=None, units_ads_30d=None, cost=9200)["roas_break_even"])
        self.assertIsNone(compute_margin_break_even(revenue_ads_30d=100_000, units_ads_30d=10, cost=None)["roas_break_even"])

    def test_settled_break_even_uses_pre_ads_net_contribution(self):
        rows = {
            "1N001": {
                "status": "ok", "revenue": 100_000, "net_real": 70_000,
                "cogs": 50_000, "ads_cost": 9_000, "margin_value": 11_000,
            }
        }
        r = compute_settled_break_even(margin_by_sku=rows, parent_skus=["1N001"])
        self.assertEqual(r["economic_confidence"], "high")
        self.assertEqual(r["margin_basis"], "settlement_mp_pre_ads")
        self.assertAlmostEqual(r["margin_pct"], 0.20)
        self.assertAlmostEqual(r["roas_break_even"], 5.0)

    def test_incomplete_settlement_blocks_instead_of_guessing(self):
        rows = {"1N001": {"status": "liquidacion_incompleta", "revenue": 100_000}}
        r = compute_settled_break_even(margin_by_sku=rows, parent_skus=["1N001"])
        self.assertEqual(r["economic_confidence"], "blocked")
        self.assertIsNone(r["roas_break_even"])
        self.assertIn("liquidacion_incompleta", r["economic_issue"])


if __name__ == "__main__":
    unittest.main()
