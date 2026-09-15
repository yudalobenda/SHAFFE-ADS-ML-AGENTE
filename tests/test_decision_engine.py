from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from core.ads_actionable_unit import ActionableUnit  # noqa: E402
from core.decision_engine import (  # noqa: E402
    CAMPAIGN_CORREGIR,
    CAMPAIGN_MOTORES,
    CAMPAIGN_RECUPERAR,
    CAMPAIGN_RENTABLES,
    decide,
)


def make_unit(integrity_ok=True, integrity_issue=None):
    return ActionableUnit(
        actionable_unit_id="ad_group:999", ad_group_id="999", ad_group_type="FAMILY",
        ad_group_external_id="fam-1", campaign_id="357700008", action_scope="GROUP",
        affected_mlas=("MLA1", "MLA2"), affected_variants=(), affected_user_products=(),
        parent_skus=("1N999",), source="ml_ad_group_api", confidence="high",
        verified_at="2026-08-28T00:00:00Z", integrity_ok=integrity_ok, integrity_issue=integrity_issue,
    )


class DecisionEngineTests(unittest.TestCase):

    def test_unverified_unit_is_blocked_never_guessed(self):
        unit = make_unit(integrity_ok=False, integrity_issue="FAMILY_ITEMS_NOT_PROVIDED")
        rec = decide(unit, {})
        self.assertEqual(rec.recommended_action, "BLOCKED")
        self.assertIsNone(rec.to_legacy_accion())

    def test_no_real_budget_keeps_testing_not_a_verdict(self):
        unit = make_unit()
        rec = decide(unit, {"spend_30d": 300, "prints_30d": 50, "roas": 0})
        self.assertEqual(rec.recommended_action, "KEEP_TESTING")
        self.assertEqual(rec.sample_confidence, "insufficient")
        self.assertIsNone(rec.to_legacy_accion())

    def test_blocked_economic_confidence_never_recommends_scale(self):
        unit = make_unit()
        rec = decide(unit, {"spend_30d": 5000, "roas": 8.0, "units_ads_30d": 5, "economic_confidence": "blocked"})
        self.assertEqual(rec.recommended_action, "BLOCKED")

    def test_high_roas_with_volume_but_critical_stock_replenishes_instead_of_scaling(self):
        """No escalar aunque el ROAS sea excelente si el stock es crítico."""
        unit = make_unit()
        rec = decide(unit, {
            "spend_30d": 10000, "roas": 9.0, "units_ads_30d": 6,
            "economic_confidence": "high", "stock_total": 3,
        })
        self.assertEqual(rec.recommended_action, "REPLENISH_BEFORE_SCALE")
        self.assertIsNone(rec.to_legacy_accion())  # no genera fila en ads_queue, es una sugerencia de compra

    def test_high_roas_with_volume_and_stock_moves_to_motores(self):
        unit = make_unit()
        rec = decide(unit, {
            "spend_30d": 10000, "roas": 9.0, "units_ads_30d": 6,
            "economic_confidence": "high", "stock_total": 200, "current_campaign": "TESTEO",
        })
        self.assertEqual(rec.recommended_action, "MOVE_TO_MOTORES")
        self.assertEqual(rec.recommended_campaign, CAMPAIGN_MOTORES)
        accion = rec.to_legacy_accion()
        self.assertEqual(accion["tipo"], "mover_tier")
        self.assertEqual(accion["campania_destino"], CAMPAIGN_MOTORES)
        self.assertEqual(accion["item_ids"], ["MLA1", "MLA2"])

    def test_moderate_roas_without_volume_moves_to_rentables_not_motores(self):
        """ROAS alto aislado NO alcanza para escalar -- regla explícita del proyecto."""
        unit = make_unit()
        rec = decide(unit, {"spend_30d": 10000, "roas": 5.0, "units_ads_30d": 1, "economic_confidence": "high"})
        self.assertEqual(rec.recommended_action, "MOVE_TO_RENTABLES")
        self.assertEqual(rec.recommended_campaign, CAMPAIGN_RENTABLES)
        self.assertIn("volumen insuficiente", rec.reason)

    def test_rentables_reason_never_blames_volume_when_volume_is_actually_high(self):
        """Bug real encontrado en la corrida en vivo 28/08 (caso real: ROAS
        4.68x con 95 unidades/30d cayó en RENTABLES pero el mensaje decía
        '95 unidades/30d < 3', contradictorio). El motivo real ahí es que el
        ROAS no llega al umbral de MOTORES, no falta de volumen."""
        unit = make_unit()
        rec = decide(unit, {"spend_30d": 50000, "roas": 4.68, "units_ads_30d": 95, "economic_confidence": "high"})
        self.assertEqual(rec.recommended_action, "MOVE_TO_RENTABLES")
        self.assertNotIn("volumen insuficiente", rec.reason)
        self.assertIn("no alcanza el umbral de escala", rec.reason)

    def test_low_ctr_with_real_traffic_moves_to_corregir_not_remove(self):
        unit = make_unit()
        rec = decide(unit, {
            "spend_30d": 10000, "roas": 1.5, "units_ads_30d": 1, "economic_confidence": "high",
            "prints_30d": 2000, "clicks_30d": 20,  # CTR = 1% < 2%
        })
        self.assertEqual(rec.recommended_action, "MOVE_TO_CORREGIR")
        self.assertEqual(rec.recommended_campaign, CAMPAIGN_CORREGIR)

    def test_high_coverage_low_roas_moves_to_recuperar_capital(self):
        unit = make_unit()
        rec = decide(unit, {
            "spend_30d": 10000, "roas": 1.0, "units_ads_30d": 0, "economic_confidence": "high",
            "stock_total": 500, "coverage_days": 300,
        })
        self.assertEqual(rec.recommended_action, "MOVE_TO_RECUPERAR")
        self.assertEqual(rec.recommended_campaign, CAMPAIGN_RECUPERAR)

    def test_2n997_real_case_removes_from_ads(self):
        """Caso real 2N997 (ver reporte): 60d ventas $299.204,50, COGS
        $98.000, comisión $45.210,09, shipping real $51.326,48, pre-Ads
        $104.667,93, Ads $195.080,30, post-Ads -$90.412,37, ACOS 54,7%.
        ROAS = 1/ACOS ≈ 1.83x. Debe resultar en salida de Ads, sin señal de
        que sea un problema de foto/ficha corregible ni de capital
        inmovilizado -- simplemente no sostiene el gasto."""
        unit = make_unit()
        roas_real = 1 / 0.547
        rec = decide(unit, {
            "spend_30d": 195080.30, "roas": roas_real, "units_ads_30d": 2,
            "economic_confidence": "high", "stock_total": 100,
            "prints_30d": 200, "clicks_30d": 10,  # tráfico insuficiente para diagnosticar CTR/CVR
        })
        self.assertEqual(rec.recommended_action, "REMOVE_FROM_ADS")
        accion = rec.to_legacy_accion()
        self.assertEqual(accion["tipo"], "pausar")

    def test_roas_10_with_8pct_margin_never_scales_end_to_end(self):
        """Caso planteado por el usuario, de punta a punta a través de
        decide(): ROAS 10x que a simple vista parece un ganador, pero con
        margen bruto 8% (break-even real 12,5x) NUNCA debe terminar en
        MOVE_TO_MOTORES ni MOVE_TO_RENTABLES -- el umbral fijo viejo (4.0x)
        lo hubiera aprobado como rentable; el umbral real de margen, no."""
        unit = make_unit()
        rec = decide(unit, {
            "spend_30d": 10000, "roas": 10.0, "units_ads_30d": 10,
            "economic_confidence": "high", "stock_total": 200,
            "roas_break_even": 12.5, "margin_pct": 0.08,
            "prints_30d": 50, "clicks_30d": 2,  # tráfico insuficiente para diagnosticar CTR/CVR
        })
        self.assertNotIn(rec.recommended_action, ("MOVE_TO_MOTORES", "MOVE_TO_RENTABLES"))
        self.assertIn("break-even", rec.reason)

    def test_roas_above_break_even_with_safety_margin_still_scales(self):
        """Contraparte: un ROAS que SÍ supera el break-even con margen de
        sobra debe poder escalar igual, break-even no es un freno per se."""
        unit = make_unit()
        rec = decide(unit, {
            "spend_30d": 10000, "roas": 15.0, "units_ads_30d": 10,
            "economic_confidence": "high", "stock_total": 200,
            "roas_break_even": 5.0, "margin_pct": 0.20,  # break-even bajo, margen sano
        })
        self.assertEqual(rec.recommended_action, "MOVE_TO_MOTORES")

    def test_correct_recommendation_surfaces_real_target_price_as_a_lever(self):
        """Cuando el caller ya resolvió el precio objetivo real (costo ERP +
        comisión real de ML), CORREGIR debe ofrecer subir precio como
        palanca concreta, no solo "cambiar foto"."""
        unit = make_unit()
        rec = decide(unit, {
            "spend_30d": 10000, "roas": 1.5, "units_ads_30d": 1, "economic_confidence": "high",
            "prints_30d": 2000, "clicks_30d": 20,
            "target_price_result": {"found": True, "precio_objetivo": 50550, "incremento_pct_vs_actual": 0.16},
        })
        self.assertEqual(rec.recommended_action, "MOVE_TO_CORREGIR")
        self.assertIn("50550", rec.reason)
        self.assertIn("+16%", rec.reason)

    def test_no_signal_is_no_action_not_a_forced_move(self):
        unit = make_unit()
        rec = decide(unit, {"spend_30d": 3000, "roas": None, "economic_confidence": "high"})
        self.assertEqual(rec.recommended_action, "NO_ACTION")
        self.assertIsNone(rec.to_legacy_accion())


if __name__ == "__main__":
    unittest.main()
