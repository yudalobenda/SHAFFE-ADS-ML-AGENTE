from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from run_decision_engine_shadow import _economics_rows, _rehydrate_unit, reclamos_devoluciones_por_sku  # noqa: E402


class RehydrateUnitTests(unittest.TestCase):
    """El runner reconstruye la ActionableUnit desde el JSON persistido por
    el ERP (GET /api/ads-data-foundation/actionable-units, camelCase en los
    campos de variante, snake_case en la fila) -- si el mapeo de campos se
    rompe, decide()/build_context() fallan silenciosamente contra atributos
    inexistentes."""

    def test_rehydrates_family_unit_with_variants(self):
        row = {
            "ad_group_id": "2723481184", "ad_group_type": "FAMILY",
            "ad_group_external_id": "5835601663700178", "campaign_id": "294904181",
            "action_scope": "GROUP", "affected_mlas": ["MLA1", "MLA2"],
            "affected_variants": [
                {"itemId": "MLA1", "skuCode": "1N019", "talle": "M", "color": "Negro", "userProductId": "UP1"},
                {"itemId": "MLA2", "skuCode": "1N019", "talle": "L", "color": "Negro", "userProductId": None},
            ],
            "affected_user_products": ["UP1"], "parent_skus": ["1N019"],
            "source": "shadow_daily_pipeline", "confidence": "high", "verified_at": "2026-09-15T00:00:00Z",
            "integrity_ok": True, "integrity_issue": None, "evidence": {"foo": "bar"},
        }
        unit = _rehydrate_unit(row)
        self.assertEqual(unit.actionable_unit_id, "ad_group:2723481184")
        self.assertEqual(unit.campaign_id, "294904181")
        self.assertEqual(unit.affected_mlas, ("MLA1", "MLA2"))
        self.assertEqual(len(unit.affected_variants), 2)
        self.assertEqual(unit.affected_variants[0].item_id, "MLA1")
        self.assertEqual(unit.affected_variants[0].sku_code, "1N019")
        self.assertEqual(unit.affected_variants[0].talle, "M")
        self.assertTrue(unit.integrity_ok)
        self.assertEqual(unit.parent_skus, ("1N019",))

    def test_rehydrates_item_unit_without_variants_or_campaign(self):
        row = {
            "ad_group_id": "204050174", "ad_group_type": "ITEM", "ad_group_external_id": "MLA1420436886",
            "campaign_id": None, "action_scope": "SINGLE", "affected_mlas": ["MLA1420436886"],
            "affected_variants": [], "affected_user_products": [], "parent_skus": [],
            "source": "shadow_daily_pipeline", "confidence": "high", "verified_at": "2026-09-15T00:00:00Z",
            "integrity_ok": True, "integrity_issue": None, "evidence": {},
        }
        unit = _rehydrate_unit(row)
        self.assertIsNone(unit.campaign_id)
        self.assertEqual(unit.affected_variants, ())
        self.assertEqual(unit.action_scope, "SINGLE")

    def test_low_integrity_unit_preserves_the_issue(self):
        row = {
            "ad_group_id": "999", "ad_group_type": "FAMILY", "ad_group_external_id": "fam1",
            "campaign_id": None, "action_scope": "UNKNOWN", "affected_mlas": [],
            "affected_variants": [], "affected_user_products": [], "parent_skus": [],
            "source": "x", "confidence": "low", "verified_at": "2026-09-15T00:00:00Z",
            "integrity_ok": False, "integrity_issue": "FAMILY_ITEMS_NOT_PROVIDED", "evidence": {},
        }
        unit = _rehydrate_unit(row)
        self.assertFalse(unit.integrity_ok)
        self.assertEqual(unit.integrity_issue, "FAMILY_ITEMS_NOT_PROVIDED")


class EconomicsRowsTests(unittest.TestCase):
    """_economics_rows traduce core.margin.calcular_margen_real ->
    sku_daily_economics. contributionPreAds siempre real cuando status=ok;
    contributionPostAds SOLO cuando hay gasto de Ads real sincronizado --
    nunca asume $0 para un mes sin sincronizar (eso sería inventar dato)."""

    def test_status_ok_with_real_ads_cost_fills_both_contributions(self):
        margin_by_sku = {"1N019": {"status": "ok", "net_real": 10000.0, "cogs": 4000.0, "ads_cost": 1500.0, "revenue": 12000.0}}
        rows = _economics_rows(margin_by_sku, skus_with_real_ads_cost={"1N019"}, reclamos_por_sku={}, metric_date_str="2026-09-15")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["contributionPreAds"], 6000.0)
        self.assertEqual(row["contributionPostAds"], 4500.0)
        self.assertEqual(row["overallConfidence"], "high")
        self.assertEqual(row["blockedComponents"], [])

    def test_status_ok_without_synced_ads_cost_leaves_post_ads_null(self):
        margin_by_sku = {"1N019": {"status": "ok", "net_real": 10000.0, "cogs": 4000.0, "ads_cost": 0.0, "revenue": 12000.0}}
        rows = _economics_rows(margin_by_sku, skus_with_real_ads_cost=set(), reclamos_por_sku={}, metric_date_str="2026-09-15")
        row = rows[0]
        self.assertEqual(row["contributionPreAds"], 6000.0)
        self.assertIsNone(row["contributionPostAds"], "sin ad_spend_by_sku sincronizado no debe inventar $0 de gasto")
        self.assertIn("ads_cost_mes", row["blockedComponents"])

    def test_status_not_ok_produces_blocked_row_without_numbers(self):
        margin_by_sku = {"2N997": {"status": "liquidacion_incompleta", "revenue": 500.0, "units": 2}}
        rows = _economics_rows(margin_by_sku, skus_with_real_ads_cost=set(), reclamos_por_sku={}, metric_date_str="2026-09-15")
        row = rows[0]
        self.assertIsNone(row["contributionPreAds"])
        self.assertIsNone(row["contributionPostAds"])
        self.assertEqual(row["overallConfidence"], "blocked")

    def test_sin_asignar_key_is_skipped(self):
        margin_by_sku = {"_sin_asignar": 1234.5}
        rows = _economics_rows(margin_by_sku, skus_with_real_ads_cost=set(), reclamos_por_sku={}, metric_date_str="2026-09-15")
        self.assertEqual(rows, [])

    def test_reclamos_devoluciones_component_se_agrega_sin_pisar_la_contribucion(self):
        margin_by_sku = {"1N019": {"status": "ok", "net_real": 10000.0, "cogs": 4000.0, "ads_cost": 0.0, "revenue": 12000.0}}
        reclamos = {"1N019": {"netoArs": -1500.0, "cantidad": 2}}
        rows = _economics_rows(margin_by_sku, skus_with_real_ads_cost=set(), reclamos_por_sku=reclamos, metric_date_str="2026-09-15")
        comp = rows[0]["components"]["reclamos_devoluciones_30d"]
        self.assertEqual(comp["value"], -1500.0)
        self.assertEqual(comp["cantidad"], 2)
        # net_real YA incluye el reclamo -- la contribución no se recalcula acá, solo se expone aparte.
        self.assertEqual(rows[0]["contributionPreAds"], 6000.0)

    def test_sku_sin_reclamos_no_agrega_el_componente(self):
        margin_by_sku = {"1N019": {"status": "ok", "net_real": 10000.0, "cogs": 4000.0, "ads_cost": 0.0, "revenue": 12000.0}}
        rows = _economics_rows(margin_by_sku, skus_with_real_ads_cost=set(), reclamos_por_sku={}, metric_date_str="2026-09-15")
        self.assertNotIn("reclamos_devoluciones_30d", rows[0]["components"])


class ReclamosDevolucionesPorSkuTests(unittest.TestCase):
    """reclamos_devoluciones_por_sku recorta del mismo movimiento real que
    ya usa core.margin -- reclamos/devoluciones CON sku van por producto,
    SIN sku quedan explícitos en sinAsignarArs, nunca prorrateados."""

    def test_agrupa_por_sku_solo_reclamo_y_devolucion(self):
        movimientos = [
            {"operation_type": "Reclamo", "sku": "1N019|Negro", "net_amount": "-500"},
            {"operation_type": "Reclamo", "sku": "1N019", "net_amount": "-300"},
            {"operation_type": "Devolución de dinero", "sku": "2N997", "net_amount": "-1000"},
            {"operation_type": "Pago aprobado", "sku": "1N019", "net_amount": "50000"},  # no es reclamo/devolución
            {"operation_type": "Cashback", "sku": None, "net_amount": "-200"},  # no es reclamo/devolución
        ]
        result = reclamos_devoluciones_por_sku(movimientos)
        self.assertEqual(result["porSku"]["1N019"]["netoArs"], -800.0)
        self.assertEqual(result["porSku"]["1N019"]["cantidad"], 2)
        self.assertEqual(result["porSku"]["2N997"]["netoArs"], -1000.0)
        self.assertEqual(result["sinAsignarArs"], 0.0)

    def test_sin_sku_queda_explicito_nunca_prorrateado(self):
        movimientos = [
            {"operation_type": "Reclamo", "sku": None, "net_amount": "-700"},
            {"operation_type": "Devolución de dinero", "sku": "", "net_amount": "-300"},
        ]
        result = reclamos_devoluciones_por_sku(movimientos)
        self.assertEqual(result["porSku"], {})
        self.assertEqual(result["sinAsignarArs"], -1000.0)


if __name__ == "__main__":
    unittest.main()
