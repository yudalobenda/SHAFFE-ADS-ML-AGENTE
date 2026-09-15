"""Phase 1 daily collector in shadow mode.

It is not imported by main.py and has no scheduler. Calling ``collect`` only
reads ML/ERP and returns base rows; calling ``persist`` writes those rows to the
ERP foundation tables, never to Mercado Ads.
"""
from __future__ import annotations

from datetime import date
from concurrent.futures import ThreadPoolExecutor
import random
import time

from core.ads_actionable_unit import AD_GROUP_TYPE_FAMILY, build_actionable_unit
from core.data_foundation import (
    CanonicalListingSkuResolver,
    normalize_ads_daily,
    normalize_listing_snapshot,
    stable_fingerprint,
)


def _stock_by_location(payload: dict | None) -> tuple[int | None, int | None]:
    """Returns (full, seller). Unknown shapes stay None instead of becoming 0."""
    if not isinstance(payload, dict) or not isinstance(payload.get("locations"), list):
        return None, None
    full = seller = 0
    saw_full = saw_seller = False
    for location in payload["locations"]:
        quantity = location.get("quantity")
        if not isinstance(quantity, (int, float)):
            continue
        location_type = location.get("type")
        if location_type == "meli_facility":
            full += int(quantity); saw_full = True
        elif location_type == "selling_address":
            seller += int(quantity); saw_seller = True
    return (full if saw_full else None, seller if saw_seller else None)


class ShadowDailyPipeline:
    def __init__(self, ml, erp, resolver=None, batch_size=100, max_retries=4, circuit_breaker=20, read_concurrency=4):
        self.ml = ml
        self.erp = erp
        self.resolver = resolver or CanonicalListingSkuResolver()
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.circuit_breaker = circuit_breaker
        self.read_concurrency = max(1, min(int(read_concurrency), 4))
        self.call_stats = {"calls": 0, "retries": 0, "errors": []}
        self._disabled_optional_sources = set()

    def _read(self, label, function, *args, optional=False, **kwargs):
        if optional and label in self._disabled_optional_sources:
            return None
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                self.call_stats["calls"] += 1
                return function(*args, **kwargs)
            except Exception as error:
                last_error = error
                message = str(error)
                retryable = any(code in message for code in ("429", "500", "502", "503", "504", "timeout", "timed out"))
                if not retryable or attempt >= self.max_retries:
                    self.call_stats["errors"].append({"stage": label, "error": message})
                    source_errors = sum(1 for item in self.call_stats["errors"] if item["stage"] == label)
                    if optional:
                        if source_errors >= 3:
                            self._disabled_optional_sources.add(label)
                        return None
                    if len(self.call_stats["errors"]) >= self.circuit_breaker:
                        raise RuntimeError(f"circuit_breaker:{label}:{len(self.call_stats['errors'])}") from error
                    raise
                self.call_stats["retries"] += 1
                time.sleep(min(16, 2 ** attempt) + random.uniform(0, 0.25))
        raise last_error

    def _collect_ad_groups(self) -> list:
        results, offset, limit = [], 0, 50
        while True:
            page = self._read("ad_groups", self.ml.get_ad_groups, "MLA", "21757", limit=limit, offset=offset)
            rows = (page or {}).get("results") or []
            results.extend(rows)
            total = (page or {}).get("paging", {}).get("total", len(results))
            offset += limit
            if not rows or offset >= total:
                break
        return results

    def _build_actionable_units(self, details: dict, links: list, ads_by_item: dict, ad_groups: list, day: str) -> list:
        """ADS_ACTIONABLE_UNIT (ver core/ads_actionable_unit.py): un solo
        get_ad_groups paginado en vez de get_ad+get_ad_group por item -- el
        campaign_id real por ad_group ya viaja en ads_by_item (search de ads
        diario), asi que no hace falta el N+1 de get_ad por item que usa
        discover_actionable_unit_for_item. Pura (sin I/O) para poder testearla
        con fixtures en memoria."""
        family_catalog: dict[str, list] = {}
        for item in details.values():
            family_id = str(item.get("family_id") or "")
            if family_id:
                family_catalog.setdefault(family_id, []).append(item)
        sku_by_item = {str(row["external_item_id"]): row.get("sku_code") for row in links if row.get("sku_code")}
        user_product_by_item = {
            str(item_id): str(item.get("user_product_id"))
            for item_id, item in details.items() if item.get("user_product_id")
        }
        campaign_id_by_ad_group = {}
        for ad in ads_by_item.values():
            ad_group_id, campaign_id = ad.get("ad_group_id"), ad.get("campaign_id")
            if ad_group_id is not None and campaign_id not in (None, 0):
                campaign_id_by_ad_group[str(ad_group_id)] = str(campaign_id)

        actionable_units = []
        for ad_group in ad_groups:
            ad_group_id = str(ad_group.get("id"))
            family_items = None
            if ad_group.get("ad_group_type") == AD_GROUP_TYPE_FAMILY:
                family_id = str(ad_group.get("ad_group_external_id") or "")
                family_items = family_catalog.get(family_id)
            unit = build_actionable_unit(
                ad_group,
                family_items=family_items,
                sku_by_item=sku_by_item,
                user_product_by_item=user_product_by_item,
                campaign_id_override=campaign_id_by_ad_group.get(ad_group_id),
                verified_at=f"{day}T00:00:00+00:00",
                source="shadow_daily_pipeline",
            )
            actionable_units.append(unit.to_api())
        return actionable_units

    def collect(self, capture_date: date, target_skus=None, campaign_ids=None, explicit_item_ids=None) -> dict:
        day = capture_date.isoformat()
        self.call_stats = {"calls": 0, "retries": 0, "errors": []}
        self._disabled_optional_sources = set()
        ads = self._read("ads_daily", self.ml.search_ads_daily_foundation_todas, "MLA", "21757", day)
        ads_by_item = {}
        for ad in ads:
            item_id = str(ad.get("item_id") or ad.get("id") or "")
            if not item_id:
                continue
            old = ads_by_item.get(item_id)
            if old is None or (old.get("status") != "active" and ad.get("status") == "active"):
                ads_by_item[item_id] = ad

        all_item_ids = self._read("seller_items", self.ml.get_seller_items_todos, status="active")
        links = self.erp.foundation_source_links(all_item_ids)
        target_skus = {str(x).upper() for x in (target_skus or [])}
        campaign_ids = {str(x) for x in (campaign_ids or [])}
        selected = set(str(x) for x in (explicit_item_ids or []))
        if target_skus:
            selected.update(str(row["external_item_id"]) for row in links if str(row.get("sku_code") or "").upper() in target_skus)
        if campaign_ids:
            selected.update(str(item_id) for item_id, ad in ads_by_item.items() if str(ad.get("campaign_id")) in campaign_ids)
        item_ids = sorted(selected) if (target_skus or campaign_ids or explicit_item_ids) else list(all_item_ids)
        details = {}
        for i in range(0, len(item_ids), 20):
            attrs = "id,title,status,listing_type_id,price,original_price,shipping,available_quantity,variations,attributes,seller_custom_field,user_product_id,family_id"
            page = self._read("items_multiget", self.ml.get_items_multiget, item_ids[i:i + 20], attributes=attrs)
            for item in page:
                details[str(item.get("id"))] = item

        links = [row for row in links if str(row.get("external_item_id")) in set(item_ids)]
        links_by_key = {(str(row["external_item_id"]), str(row.get("external_variation_id") or "")): row for row in links}
        mappings, snapshots = [], []

        def enrich(item_id):
            item = details.get(str(item_id))
            if not item:
                return str(item_id), {}
            user_product = distributed = None
            user_product_id = item.get("user_product_id")
            if user_product_id:
                user_product = self._read("user_product", self.ml.get_user_product, str(user_product_id), optional=True)
                distributed = self._read("distributed_stock", self.ml.get_distributed_stock, str(user_product_id), optional=True)
            visits_payload = self._read("visits", self.ml.get_item_visits, str(item_id), 1, "day", optional=True)
            promotion_payload = self._read("promotions", self.ml.get_item_promotions, str(item_id), optional=True)
            return str(item_id), {
                "userProduct": user_product, "distributed": distributed,
                "visits": visits_payload, "promotion": promotion_payload,
            }

        with ThreadPoolExecutor(max_workers=self.read_concurrency) as executor:
            enrichment = dict(executor.map(enrich, item_ids))

        for item_id in item_ids:
            item = details.get(str(item_id))
            if not item:
                continue
            ad = ads_by_item.get(str(item_id), {})
            native_variations = item.get("variations") or []
            variations = native_variations or [None]
            enriched = enrichment.get(str(item_id), {})
            user_product = enriched.get("userProduct")
            distributed = enriched.get("distributed")
            stock_full, stock_seller = _stock_by_location(distributed)
            visits_payload = enriched.get("visits")
            visits = visits_payload.get("total_visits") if isinstance(visits_payload, dict) else None
            promotion_payload = enriched.get("promotion")

            # One MLA-level row owns visits and distributed stock. Native
            # variation rows below keep those fields NULL to avoid double count.
            parent_snapshot = normalize_listing_snapshot(
                item=item, variation=None, ad=ad, snapshot_date=day, visits=visits,
                visits_window_days=1, promotion=promotion_payload,
                stock_full=stock_full, stock_seller=stock_seller,
                visits_payload=visits_payload if isinstance(visits_payload, dict) else None,
            )
            parent_snapshot["connectionId"] = (links_by_key.get((str(item_id), "")) or {}).get("connection_id")
            snapshots.append(parent_snapshot)

            for variation in variations:
                variation = variation or {}
                variation_id = str(variation.get("id") or "")
                erp_link = links_by_key.get((str(item_id), variation_id)) or links_by_key.get((str(item_id), ""))
                resolution = self.resolver.resolve(
                    item=item, ad=ad, variation=variation, user_product=user_product, erp_link=erp_link,
                )
                mappings.append(resolution.to_api(valid_from=f"{day}T00:00:00+00:00", connection_id=(erp_link or {}).get("connection_id")))
                if native_variations:
                    snapshot = normalize_listing_snapshot(
                        item=item, variation=variation, ad=ad, snapshot_date=day, visits=None,
                        visits_window_days=None, promotion=promotion_payload,
                        stock_full=None, stock_seller=None,
                    )
                    snapshot["connectionId"] = (erp_link or {}).get("connection_id")
                    snapshots.append(snapshot)

        metrics_by_key = {}
        selected_item_ids = {str(value) for value in item_ids}
        for ad in ads:
            row = normalize_ads_daily(ad, day, "ML_PADS_DEFAULT")
            if (target_skus or campaign_ids or explicit_item_ids) and row["externalItemId"] not in selected_item_ids:
                continue
            key = (row["metricDate"], row["campaignId"], row["adGroupId"], row["externalItemId"], row["externalVariationId"], row["attributionWindow"])
            old = metrics_by_key.get(key)
            if old is None or (old["sourcePayload"].get("status") != "active" and ad.get("status") == "active"):
                metrics_by_key[key] = row
        metrics = list(metrics_by_key.values())
        ad_groups = self._collect_ad_groups()
        actionable_units = self._build_actionable_units(details, links, ads_by_item, ad_groups, day)

        payload = {
            "date": day, "mappings": mappings, "listingSnapshots": snapshots, "adsDailyMetrics": metrics,
            "actionableUnits": actionable_units,
            "collectionMetadata": {
                "activeSellerItems": len(all_item_ids), "selectedItems": len(item_ids),
                "calls": self.call_stats["calls"], "retries": self.call_stats["retries"],
                "partialErrors": self.call_stats["errors"], "methods": ["GET"],
                "disabledOptionalSources": sorted(self._disabled_optional_sources),
                "readConcurrency": self.read_concurrency,
            },
        }
        payload["fingerprint"] = stable_fingerprint(payload)
        return payload

    def collect_ads_only(self, capture_date: date) -> dict:
        """Safe historical backfill: Ads exposes dated facts; listings do not."""
        day = capture_date.isoformat()
        self.call_stats = {"calls": 0, "retries": 0, "errors": []}
        self._disabled_optional_sources = set()
        ads = self._read("ads_daily", self.ml.search_ads_daily_foundation_todas, "MLA", "21757", day)
        metrics_by_key = {}
        for ad in ads:
            row = normalize_ads_daily(ad, day, "ML_PADS_DEFAULT")
            key = (row["metricDate"], row["campaignId"], row["adGroupId"], row["externalItemId"], row["externalVariationId"], row["attributionWindow"])
            old = metrics_by_key.get(key)
            if old is None or (old["sourcePayload"].get("status") != "active" and ad.get("status") == "active"):
                metrics_by_key[key] = row
        payload = {
            "date": day, "mappings": [], "listingSnapshots": [], "actionableUnits": [],
            "adsDailyMetrics": list(metrics_by_key.values()),
            "collectionMetadata": {
                "backfill": True, "sources": ["ads"], "calls": self.call_stats["calls"],
                "retries": self.call_stats["retries"], "partialErrors": self.call_stats["errors"],
                "methods": ["GET"], "ratiosPersisted": False,
            },
        }
        payload["fingerprint"] = stable_fingerprint(payload)
        return payload

    def persist(self, payload: dict) -> dict:
        day = payload["date"]
        is_backfill = bool(payload.get("collectionMetadata", {}).get("backfill"))
        run = self.erp.create_ingestion_run({
            "source": "mercadolibre_ads_backfill" if is_backfill else "mercadolibre_ads_daily_foundation",
            "idempotencyKey": f"{day}:{payload['fingerprint']}",
            "extractorVersion": "foundation-v1",
            "mode": "shadow",
            "dateFrom": day,
            "dateTo": day,
            "inputFingerprint": payload["fingerprint"],
            "sourceTimezone": "America/Argentina/Buenos_Aires",
            "checkpoint": {},
            "metadata": {"mode": "shadow", "ratiosPersisted": False, **payload.get("collectionMetadata", {})},
        })
        run_id = run["id"]
        try:
            results = []
            stages = (
                ("mappings", payload["mappings"], self.erp.persist_listing_sku_mappings),
                ("listing_snapshots", payload["listingSnapshots"], self.erp.persist_listing_snapshots),
                ("ads_daily_metrics", payload["adsDailyMetrics"], self.erp.persist_ads_daily_metrics),
                ("actionable_units", payload.get("actionableUnits", []), self.erp.persist_actionable_units),
            )
            for stage, rows, writer in stages:
                for offset in range(0, len(rows), self.batch_size):
                    batch = rows[offset:offset + self.batch_size]
                    results.append(writer(run_id, batch))
                    self.erp.heartbeat_ingestion_run(run_id, {
                        "stage": stage, "nextOffset": offset + len(batch), "total": len(rows),
                    })
            written = sum(int(x.get("written", 0)) for x in results)
            final_status = "partial" if payload.get("collectionMetadata", {}).get("partialErrors") else "completed"
            self.erp.finish_ingestion_run(run_id, {
                "status": final_status,
                "recordsRead": len(payload["mappings"]) + len(payload["adsDailyMetrics"]) + len(payload.get("actionableUnits", [])),
                "recordsWritten": written,
                "sourceWatermark": day,
                "checkpoint": {"stage": "done"},
                "metadata": payload.get("collectionMetadata", {}),
                "errorDetail": {"partialErrors": payload["collectionMetadata"]["partialErrors"]} if final_status == "partial" else None,
            })
            return {"runId": run_id, "status": final_status, "recordsWritten": written}
        except Exception as error:
            self.erp.finish_ingestion_run(run_id, {"status": "failed", "errorDetail": {"message": str(error)}})
            raise
