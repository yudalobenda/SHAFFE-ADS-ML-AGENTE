import json
from datetime import date
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from core.data_foundation import (  # noqa: E402
    CanonicalListingSkuResolver,
    SHIPPING_SOURCE_PRIORITY,
    blocked_tax_components,
    blocked_unattributed_logistics_cashback,
    build_shadow_economics_row,
    compare_acos_to_break_even,
    derive_acos_tacos,
    derive_ads_ratios,
    economic_component,
    economic_recommendation_allowed,
    fiscal_scenarios_change_sign,
    normalize_ads_daily,
    normalize_listing_snapshot,
    stable_fingerprint,
    shipping_economic_component,
)
from core.shadow_daily_pipeline import ShadowDailyPipeline, _stock_by_location  # noqa: E402
from core.ml_client import MLClient  # noqa: E402


class DataFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = BASE / "tests" / "fixtures" / "ml001_daily_fixture.json"
        cls.fixture = json.loads(fixture.read_text(encoding="utf-8"))

    def test_same_extraction_has_same_fingerprint(self):
        first = stable_fingerprint(self.fixture)
        second = stable_fingerprint(json.loads(json.dumps(self.fixture)))
        self.assertEqual(first, second)

    def test_mapping_mla_to_parent_sku_without_title_alias(self):
        item = self.fixture["items"][0]
        ad = self.fixture["ads"][0]
        result = CanonicalListingSkuResolver().resolve(item=item, ad=ad)
        self.assertEqual(result.sku_code, "ML001")
        self.assertEqual(result.mapping_method, "item_seller_custom_field")
        self.assertEqual(result.review_status, "resolved")

    def test_multiple_mlas_can_resolve_to_same_parent_sku(self):
        resolver = CanonicalListingSkuResolver()
        skus = {
            resolver.resolve(item=item, ad=ad).sku_code
            for item, ad in zip(self.fixture["items"], self.fixture["ads"])
        }
        self.assertEqual(skus, {"ML001"})

    def test_native_variation_resolution(self):
        item = {"id": "MLA-NATIVE", "variations": [{"id": 77}]}
        variation = {"id": 77, "attributes": [{"id": "SELLER_SKU", "value_name": "PA001|42|AZUL"}]}
        result = CanonicalListingSkuResolver().resolve(item=item, variation=variation)
        self.assertEqual(result.external_variation_id, "77")
        self.assertEqual(result.sku_code, "PA001")

    def test_conflicting_mapping_is_manual_review(self):
        item = {"id": "MLA-X", "seller_custom_field": "CA004|M"}
        erp = {"id": "link-1", "sku_code": "1N019", "product_id": "product-1"}
        result = CanonicalListingSkuResolver().resolve(item=item, erp_link=erp)
        self.assertIsNone(result.sku_code)
        self.assertEqual(result.confidence, "ambiguous")
        self.assertEqual(result.review_status, "manual_review")

    def test_historical_mapping_payload_can_change_valid_from(self):
        resolver = CanonicalListingSkuResolver()
        old = resolver.resolve(item={"id": "MLA-X", "seller_custom_field": "CA004|M"}).to_api("2026-08-01T00:00:00Z")
        new = resolver.resolve(item={"id": "MLA-X", "seller_custom_field": "1N019|M"}).to_api("2026-08-26T00:00:00Z")
        self.assertNotEqual(old["skuCode"], new["skuCode"])
        self.assertLess(old["validFrom"], new["validFrom"])

    def test_missing_economic_data_is_not_zero(self):
        components = {
            "revenue": economic_component(1000, source="orders", confidence="high", coverage=1.0, estimated=False),
            "iibb": economic_component(None, source="unreconciled", confidence="blocked", coverage=None, estimated=False, blocked_reason="IIBB_NOT_RECONCILED"),
            "returns": economic_component(None, source="unreconciled", confidence="blocked", coverage=None, estimated=False, blocked_reason="RETURNS_NOT_RECONCILED"),
        }
        row = build_shadow_economics_row(date(2026, 8, 25), "ML001", components)
        self.assertIsNone(row["components"]["iibb"]["value"])
        self.assertEqual(set(row["blockedComponents"]), {"iibb", "returns"})
        self.assertEqual(row["overallConfidence"], "blocked")
        self.assertIsNone(row["contributionPostAds"])

    def test_phase1_tax_contract_is_explicit_null_and_blocked(self):
        taxes = blocked_tax_components()
        self.assertEqual(len(taxes), 7)
        for component in taxes.values():
            self.assertIsNone(component["value"])
            self.assertEqual(component["confidence"], "blocked")
            self.assertFalse(component["real"])
            self.assertIsNone(component["tax_included"])
            self.assertIsNone(component["tax_amount"])

    def test_critical_tax_uncertainty_blocks_overall_economics(self):
        components = {
            "revenue": economic_component(1000, source="orders", confidence="high", coverage=1.0, estimated=False),
            **blocked_tax_components(),
            "shipping": shipping_economic_component(100, source="REAL_SETTLEMENT", coverage=1.0),
            "cashback_logistico_no_atribuido": blocked_unattributed_logistics_cashback(),
        }
        row = build_shadow_economics_row(date(2026, 8, 25), "CA004", components)
        self.assertEqual(row["overallConfidence"], "blocked")
        self.assertFalse(row["economicRecommendationAllowed"])
        self.assertIsNone(row["contributionPreAds"])
        self.assertIsNone(row["contributionPostAds"])

    def test_component_tax_metadata_is_backward_compatible_and_explicit(self):
        old = economic_component(100, source="orders", confidence="high", coverage=1.0, estimated=False)
        self.assertIsNone(old["tax_included"])
        enriched = economic_component(
            121, source="invoice", confidence="high", coverage=1.0, estimated=False,
            tax_included=True, tax_rate=0.21, tax_amount=21, tax_source="supplier_invoice",
            allocation_method="DIRECT_SKU",
        )
        self.assertEqual(enriched["tax_amount"], 21.0)
        self.assertEqual(enriched["allocation_method"], "DIRECT_SKU")

    def test_shipping_source_hierarchy_and_base_cost_prohibition(self):
        self.assertEqual(SHIPPING_SOURCE_PRIORITY, (
            "REAL_SETTLEMENT", "ML_LIST_COST", "FLEX_INVOICE", "ACCOUNT_RATIO_ESTIMATE",
        ))
        real = shipping_economic_component(7590, source="REAL_SETTLEMENT", coverage=1.0)
        fallback = shipping_economic_component(7590, source="ML_LIST_COST", coverage=1.0)
        estimate = shipping_economic_component(
            7590, source="ACCOUNT_RATIO_ESTIMATE", coverage=0.0,
            allocation_method="ACCOUNT_RATIO",
        )
        self.assertTrue(real["real"])
        self.assertEqual(fallback["confidence"], "medium")
        self.assertTrue(estimate["estimated"])
        with self.assertRaisesRegex(ValueError, "base_cost"):
            shipping_economic_component(13814, source="SHIPPING_BASE_COST", coverage=1.0)

    def test_unattributed_cashback_is_never_silently_allocated(self):
        cashback = blocked_unattributed_logistics_cashback()
        self.assertIsNone(cashback["value"])
        self.assertEqual(cashback["confidence"], "blocked")
        self.assertIsNone(cashback["allocation_method"])

    def test_fiscal_sign_flip_forbids_automatic_economic_recommendation(self):
        scenarios = [-509410, 372418]
        self.assertTrue(fiscal_scenarios_change_sign(scenarios))
        self.assertFalse(economic_recommendation_allowed(
            overall_confidence="high", scenario_contributions=scenarios,
        ))
        self.assertFalse(economic_recommendation_allowed(
            overall_confidence="blocked", scenario_contributions=[100, 200],
        ))

    def test_real_and_estimated_ads_are_explicit(self):
        real = economic_component(100, source="ml_ads_daily", confidence="high", coverage=1.0, estimated=False)
        estimated = economic_component(100, source="account_proration", confidence="low", coverage=0.0, estimated=True)
        self.assertTrue(real["real"])
        self.assertFalse(estimated["real"])
        self.assertTrue(estimated["estimated"])

    def test_full_and_seller_stock_are_separate(self):
        full, seller = _stock_by_location({"locations": [
            {"type": "meli_facility", "quantity": 8},
            {"type": "selling_address", "quantity": 3},
        ]})
        self.assertEqual((full, seller), (8, 3))
        self.assertEqual(_stock_by_location({"unexpected": []}), (None, None))

    def test_daily_reconstruction_derives_ratios_from_base_facts(self):
        rows = [normalize_ads_daily(ad, self.fixture["date"], "ML_PADS_DEFAULT") for ad in self.fixture["ads"]]
        derived = derive_ads_ratios(rows)
        self.assertEqual(derived["prints"], 3145)
        self.assertEqual(derived["clicks"], 21)
        self.assertEqual(derived["revenue"], 52800)
        self.assertAlmostEqual(derived["roas"], 52800 / 2411.81)

    def test_listing_snapshot_preserves_nulls(self):
        row = normalize_listing_snapshot(
            item=self.fixture["items"][0], ad=self.fixture["ads"][0],
            snapshot_date=self.fixture["date"], visits=None, visits_window_days=1,
            stock_full=None, stock_seller=None,
        )
        self.assertIsNone(row["visits"])
        self.assertIsNone(row["stockFull"])
        self.assertIsNone(row["stockSeller"])

    def test_visits_raw_buckets_are_preserved(self):
        visits_payload = {
            "date_from": "2026-08-25T00:00:00Z", "date_to": "2026-08-26T00:00:00Z",
            "total_visits": 99,
            "results": [{"date": "2026-08-25T00:00:00Z", "total": 73}, {"date": "2026-08-26T00:00:00Z", "total": 26}],
        }
        row = normalize_listing_snapshot(
            item=self.fixture["items"][0], ad=self.fixture["ads"][0],
            snapshot_date=self.fixture["date"], visits=99, visits_window_days=1,
            visits_payload=visits_payload,
        )
        self.assertEqual(len(row["sourcePayload"]["visits"]["results"]), 2)
        self.assertEqual(row["sourcePayload"]["visits"]["results"][0]["total"], 73)

    def test_centralized_foundation_endpoints_are_read_only(self):
        client = object.__new__(MLClient)
        calls = []
        client._request = lambda method, path, **kwargs: calls.append((method, path, kwargs)) or {}
        client.get_item_visits("MLA1", 1)
        client.get_shipment("SHIP1")
        client.get_listing_prices(1000, "MLA-CAT")
        client.get_user_product("UP1")
        client.get_distributed_stock("UP1")
        client.get_item_promotions("MLA1")
        self.assertTrue(calls)
        self.assertEqual({method for method, _, _ in calls}, {"GET"})
        promotion_call = next(call for call in calls if "seller-promotions" in call[1])
        self.assertEqual(promotion_call[2]["params"]["app_version"], "v2")

    def test_reversible_migration_has_matching_create_drop_tables(self):
        migrations = Path(r"C:\Users\Diseño\Downloads\shaffe-erp\backend\db\migrations")
        up = (migrations / "20260826_ads_data_foundation.up.sql").read_text(encoding="utf-8")
        down = (migrations / "20260826_ads_data_foundation.down.sql").read_text(encoding="utf-8")
        tables = {
            "data_ingestion_runs", "listing_sku_assignment_history", "ml_listing_daily_snapshots",
            "ml_ads_daily_metrics", "calculation_formula_versions", "calculation_runs", "sku_daily_economics",
        }
        for table in tables:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", up)
            self.assertIn(f"DROP TABLE IF EXISTS {table}", down)

    def test_ml001_acos_and_tacos_are_distinct(self):
        # Control real documentado: ROAS 6.03x, ACOS 16.58%, TACOS 8.44%.
        ads_spend = 1658.0
        ratios = derive_acos_tacos(
            ads_spend=ads_spend,
            ads_attributed_revenue=10000.0,
            total_product_revenue=ads_spend / 0.0844,
        )
        self.assertAlmostEqual(ratios["acos"].value, 0.1658, places=4)
        self.assertAlmostEqual(ratios["tacos"].value, 0.0844, places=4)
        self.assertNotEqual(ratios["acos"].denominator, ratios["tacos"].denominator)
        result = compare_acos_to_break_even(ratios["acos"], 0.32)
        self.assertTrue(result["sustainable"])

    def test_tacos_cannot_be_used_as_acos_or_break_even_input(self):
        ratios = derive_acos_tacos(
            ads_spend=100, ads_attributed_revenue=500, total_product_revenue=1000,
        )
        with self.assertRaisesRegex(ValueError, "TACOS"):
            compare_acos_to_break_even(ratios["tacos"], 0.32)

    def test_acos_never_uses_total_revenue_denominator(self):
        ratios = derive_acos_tacos(
            ads_spend=100, ads_attributed_revenue=400, total_product_revenue=1000,
        )
        self.assertEqual(ratios["acos"].value, 0.25)
        self.assertEqual(ratios["tacos"].value, 0.10)
        self.assertEqual(ratios["acos"].denominator, "ads_attributed_revenue")
        self.assertEqual(ratios["tacos"].denominator, "total_product_revenue")

    def test_ads_ratios_reconstruct_cpc_from_base_facts(self):
        ratios = derive_ads_ratios([{
            "prints": 1000, "clicks": 20, "cost": 500,
            "directAmount": 2000, "indirectAmount": 1000,
            "directUnits": 2, "indirectUnits": 1,
        }])
        self.assertEqual(ratios["cpc"], 25)

    def test_optional_source_circuit_marks_missing_without_aborting(self):
        pipeline = ShadowDailyPipeline(None, None)
        def unavailable():
            raise RuntimeError("400 Invalid app_version")
        self.assertIsNone(pipeline._read("promotions", unavailable, optional=True))
        self.assertIsNone(pipeline._read("promotions", unavailable, optional=True))
        self.assertIsNone(pipeline._read("promotions", unavailable, optional=True))
        before = pipeline.call_stats["calls"]
        self.assertIsNone(pipeline._read("promotions", unavailable, optional=True))
        self.assertEqual(pipeline.call_stats["calls"], before)
        self.assertIn("promotions", pipeline._disabled_optional_sources)

    def test_persist_is_batched_checkpointed_and_partial_is_visible(self):
        class FakeERP:
            def __init__(self): self.heartbeats = []
            def create_ingestion_run(self, _payload): return {"id": "run-1"}
            def persist_listing_sku_mappings(self, _run, rows): return {"written": len(rows)}
            def persist_listing_snapshots(self, _run, rows): return {"written": len(rows)}
            def persist_ads_daily_metrics(self, _run, rows): return {"written": len(rows)}
            def persist_actionable_units(self, _run, rows): return {"written": len(rows)}
            def heartbeat_ingestion_run(self, _run, checkpoint): self.heartbeats.append(checkpoint)
            def finish_ingestion_run(self, _run, payload): self.finished = payload
        erp = FakeERP()
        pipeline = ShadowDailyPipeline(None, erp, batch_size=1)
        payload = {"date": "2026-08-27", "fingerprint": "fp", "mappings": [{}, {}],
                   "listingSnapshots": [{}], "adsDailyMetrics": [{}],
                   "collectionMetadata": {"partialErrors": [{"stage": "visits"}]}}
        result = pipeline.persist(payload)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(erp.heartbeats), 4)
        self.assertEqual(erp.finished["checkpoint"], {"stage": "done"})

    def test_ads_backfill_does_not_fabricate_listing_history(self):
        class FakeML:
            def search_ads_daily_foundation_todas(self, *_args):
                return [{"item_id": "MLA1", "campaign_id": 1, "ad_group_id": 2,
                         "metrics": {"prints": 5, "clicks": None, "cost": None}}]
        payload = ShadowDailyPipeline(FakeML(), None).collect_ads_only(date(2026, 8, 1))
        self.assertEqual(payload["mappings"], [])
        self.assertEqual(payload["listingSnapshots"], [])
        self.assertEqual(len(payload["adsDailyMetrics"]), 1)
        self.assertIsNone(payload["adsDailyMetrics"][0]["clicks"])


if __name__ == "__main__":
    unittest.main()
