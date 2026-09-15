import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from core.shadow_daily_pipeline import ShadowDailyPipeline  # noqa: E402


class ShadowActionableUnitsTests(unittest.TestCase):
    """El shadow pipeline diario descubre ads_actionable_units (ver
    core/ads_actionable_unit.py) a partir de un solo get_ad_groups paginado,
    en vez del N+1 de discover_actionable_unit_for_item. Usa los mismos
    payloads reales capturados en vivo 2026-08-28 que test_ads_actionable_unit.py
    para que ambos tests describan la misma cuenta real."""

    @classmethod
    def setUpClass(cls):
        fixture = BASE / "tests" / "fixtures" / "actionable_unit_real_cases.json"
        cls.data = json.loads(fixture.read_text(encoding="utf-8"))

    def test_family_ad_group_overrides_zero_campaign_id_from_ads_by_item(self):
        """Caso real: get_ad_group devuelve campaign_id=0 para la Camisa
        (grupo FAMILY recien creado), pero el search de ads diario SI trae el
        campaign_id real por item -- el pipeline debe usar ese override, no
        quedarse con el 0."""
        data = self.data
        self.assertEqual(data["ad_group_camisa_family"]["campaign_id"], 0)
        details = {item["id"]: item for item in data["camisa_family_items"]}
        links = [{"external_item_id": item_id} for item_id in details]
        pipeline = ShadowDailyPipeline(None, None)

        units = pipeline._build_actionable_units(
            details, links, data["camisa_ad_by_item"], [data["ad_group_camisa_family"]], "2026-08-28",
        )

        self.assertEqual(len(units), 1)
        unit = units[0]
        self.assertEqual(unit["adGroupId"], "2723481184")
        self.assertEqual(unit["campaignId"], "294904181")
        self.assertEqual(unit["actionScope"], "GROUP")
        self.assertEqual(unit["confidence"], "high")
        self.assertTrue(unit["integrityOk"])
        self.assertEqual(set(unit["affectedMlas"]), set(data["camisa_ad_by_item"].keys()))

    def test_item_type_ad_group_needs_no_family_catalog(self):
        """1N019 hombre: ad_group tipo ITEM, sin variantes -- no depende de
        family_catalog ni de ads_by_item para resolver su campaign_id real."""
        pipeline = ShadowDailyPipeline(None, None)
        ad_group = self.data["ad_group_1n019_hombre_item"]

        units = pipeline._build_actionable_units({}, [], {}, [ad_group], "2026-08-28")

        self.assertEqual(len(units), 1)
        unit = units[0]
        self.assertEqual(unit["actionScope"], "SINGLE")
        self.assertEqual(unit["campaignId"], "357702416")
        self.assertEqual(unit["affectedMlas"], ["MLA1420436886"])

    def test_family_ad_group_without_catalog_is_low_confidence_not_invented(self):
        """Si el item_id del ad_group FAMILY no aparece en el catalogo de
        detalles que trajo este collect() (p.ej. quedo fuera del filtro de la
        corrida), la unidad no inventa affected_mlas: baja confidence."""
        pipeline = ShadowDailyPipeline(None, None)
        ad_group = self.data["ad_group_camisa_family"]

        units = pipeline._build_actionable_units({}, [], {}, [ad_group], "2026-08-28")

        self.assertEqual(units[0]["confidence"], "low")
        self.assertFalse(units[0]["integrityOk"])
        self.assertEqual(units[0]["integrityIssue"], "FAMILY_ITEMS_NOT_PROVIDED")

    def test_collect_ad_groups_paginates_until_total_reached(self):
        class FakeML:
            def __init__(self):
                self.calls = []

            def get_ad_groups(self, site_id, advertiser_id, limit=50, offset=0):
                self.calls.append(offset)
                page = [{"id": str(offset + i)} for i in range(min(limit, 3 - offset))] if offset < 3 else []
                return {"results": page, "paging": {"total": 3}}

        ml = FakeML()
        pipeline = ShadowDailyPipeline(ml, None)
        ad_groups = pipeline._collect_ad_groups()

        self.assertEqual([g["id"] for g in ad_groups], ["0", "1", "2"])

    def test_collect_ad_groups_stops_on_empty_page_even_if_total_lies(self):
        class FakeML:
            def get_ad_groups(self, site_id, advertiser_id, limit=50, offset=0):
                return {"results": [], "paging": {"total": 999}}

        pipeline = ShadowDailyPipeline(FakeML(), None)
        self.assertEqual(pipeline._collect_ad_groups(), [])


if __name__ == "__main__":
    unittest.main()
