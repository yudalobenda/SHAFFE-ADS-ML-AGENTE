from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from run_decision_engine_shadow import _rehydrate_unit  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
