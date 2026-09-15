"""Caracterización del motor legado; no expresa thresholds aprobados."""

import unittest

from agents.analyst import Analyst
from core import campaign_rules as rules


class LegacyCampaignRulesTests(unittest.TestCase):
    def test_one_day_thresholds_are_frozen_as_legacy_not_policy(self):
        self.assertEqual(rules.DIAS_SOSTENIDO_SUBIR, 1)
        self.assertEqual(rules.DIAS_CAIDA_BAJAR, 1)

    def test_testeo_moves_after_one_current_sample_when_tier_age_allows(self):
        self.assertEqual(
            rules.evaluar_movimiento_tier('testeo', [6.5], dias_en_tier_actual=7, ticket_actual='bajo'),
            'oro_bajo',
        )

    def test_minimum_tier_age_blocks_normal_promotion(self):
        self.assertIsNone(
            rules.evaluar_movimiento_tier('testeo', [4.0], dias_en_tier_actual=6, ticket_actual='alto')
        )

    def test_oro_cooldown_blocks_degradation(self):
        self.assertIsNone(rules.evaluar_movimiento_tier('oro_bajo', [1.0], dias_en_oro=14))
        self.assertEqual(rules.evaluar_movimiento_tier('oro_bajo', [1.0], dias_en_oro=15), 'plata_bajo')

    def test_metric_alert_contract(self):
        self.assertEqual(
            rules.alertas_metricas(100, 1, 0, 0.30, 'oro_bajo'),
            ['ctr_bajo', 'acos_alto'],
        )

    def test_budget_signal_is_cost_or_impressions(self):
        self.assertFalse(rules.tiene_presupuesto_real(1999, 499))
        self.assertTrue(rules.tiene_presupuesto_real(2000, 0))
        self.assertTrue(rules.tiene_presupuesto_real(0, 500))

    def test_single_variant_is_not_low_stock_when_total_variants_is_known(self):
        self.assertFalse(rules.es_poco_stock(100, 1, total_variantes=1))
        self.assertTrue(rules.es_poco_stock(4, 1, total_variantes=1))

    def test_analyst_operates_on_group_id_and_preserves_legacy_action_shape(self):
        action = Analyst([]).decidir_movimiento_tier(
            'family-1', 'plata_bajo', [3.0], dias_en_tier_actual=999
        )
        self.assertEqual(action['grupo_id'], 'family-1')
        self.assertEqual(action['accion'], 'pausar')
        self.assertEqual(action['motivo'], 'roas_bajo_sostenido')


if __name__ == '__main__':
    unittest.main()
