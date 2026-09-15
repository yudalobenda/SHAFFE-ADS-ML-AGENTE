"""Read-only normalization primitives for the Ads data foundation.

This module is intentionally disconnected from main.py. It transforms already
fetched API payloads into auditable base rows and never mutates MercadoLibre.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, Iterable


CONFIDENCE_RANK = {"ambiguous": 0, "low": 1, "medium": 2, "high": 3}

TAX_COMPONENT_NAMES = (
    "iva_debito_ventas", "iva_credito_cogs", "iva_credito_comision_ml",
    "iva_credito_logistica", "iva_credito_ads", "iva_credito_otros", "iva_neto",
)
SHIPPING_SOURCE_PRIORITY = (
    "REAL_SETTLEMENT", "ML_LIST_COST", "FLEX_INVOICE", "ACCOUNT_RATIO_ESTIMATE",
)
PROHIBITED_SHIPPING_SOURCES = {"BASE_COST", "SHIPPING_BASE_COST", "shipping.base_cost"}
DEFAULT_CRITICAL_ECONOMIC_COMPONENTS = frozenset({
    *TAX_COMPONENT_NAMES, "shipping", "cashback_logistico_no_atribuido",
})


@dataclass(frozen=True)
class NamedRatio:
    name: str
    value: float | None
    numerator: str
    denominator: str


def base_sku(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).split("|")[0].strip().upper()
    return normalized or None


def stable_fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _attributes_sku(attributes: Iterable[dict] | None) -> str | None:
    for attr in attributes or []:
        if str(attr.get("id") or "").upper() == "SELLER_SKU":
            return base_sku(attr.get("value_name") or attr.get("value_id"))
    return None


@dataclass(frozen=True)
class MappingCandidate:
    sku_code: str
    product_id: str | None
    method: str
    confidence: str
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MappingResolution:
    external_item_id: str
    external_variation_id: str
    campaign_id: str | None
    ad_group_id: str | None
    family_id: str | None
    sku_code: str | None
    product_id: str | None
    mapping_method: str
    confidence: str
    review_status: str
    evidence: dict

    def to_api(self, valid_from: str | None = None, connection_id: str | None = None) -> dict:
        return {
            "connectionId": connection_id,
            "campaignId": self.campaign_id,
            "adGroupId": self.ad_group_id,
            "externalItemId": self.external_item_id,
            "externalVariationId": self.external_variation_id,
            "familyId": self.family_id,
            "skuCode": self.sku_code,
            "productId": self.product_id,
            "validFrom": valid_from or datetime.now(timezone.utc).isoformat(),
            "mappingMethod": self.mapping_method,
            "confidence": self.confidence,
            "reviewStatus": self.review_status,
            "evidence": self.evidence,
        }


class CanonicalListingSkuResolver:
    """Resolves campaign -> ad_group -> MLA -> variation -> parent SKU.

    Title aliases are deliberately not accepted. Conflicting candidates are
    preserved as an ambiguous result for manual review.
    """

    def resolve(
        self,
        *,
        item: dict,
        ad: dict | None = None,
        variation: dict | None = None,
        user_product: dict | None = None,
        erp_link: dict | None = None,
        order_skus: Iterable[str] | None = None,
    ) -> MappingResolution:
        ad = ad or {}
        variation = variation or {}
        candidates: list[MappingCandidate] = []

        def add(raw_sku, product_id, method, confidence, evidence):
            sku = base_sku(raw_sku)
            if sku:
                candidates.append(MappingCandidate(sku, product_id, method, confidence, evidence))

        if erp_link:
            add(erp_link.get("sku_code") or erp_link.get("product_code"), erp_link.get("product_id"),
                "erp_channel_link", "high", {"link_id": erp_link.get("id")})
        for sku in order_skus or []:
            add(sku, None, "paid_order_seller_sku", "high", {"source": "orders"})
        add(variation.get("seller_custom_field"), None, "variation_seller_custom_field", "high", {})
        add(_attributes_sku(variation.get("attributes") or variation.get("attribute_combinations")), None,
            "variation_seller_sku_attribute", "high", {})
        add(item.get("seller_custom_field"), None, "item_seller_custom_field", "high", {})
        add(_attributes_sku(item.get("attributes")), None, "item_seller_sku_attribute", "high", {})

        if user_product:
            add(user_product.get("seller_custom_field"), None, "user_product_seller_custom_field", "medium", {})
            add(_attributes_sku(user_product.get("attributes")), None, "user_product_seller_sku_attribute", "medium", {})
            for up_variation in user_product.get("variations") or []:
                requested = str(variation.get("id") or "")
                if requested and str(up_variation.get("id") or "") != requested:
                    continue
                add(up_variation.get("seller_custom_field"), None, "user_product_variation_custom_field", "medium", {})
                add(_attributes_sku(up_variation.get("attributes") or up_variation.get("attribute_combinations")),
                    None, "user_product_variation_sku_attribute", "medium", {})

        by_sku: dict[str, list[MappingCandidate]] = {}
        for candidate in candidates:
            by_sku.setdefault(candidate.sku_code, []).append(candidate)

        evidence = {
            "candidates": [asdict(c) for c in candidates],
            "item_id": str(item.get("id") or ad.get("item_id") or ""),
            "variation_id": str(variation.get("id") or ""),
        }
        if not by_sku:
            return self._result(item, ad, variation, None, None, "unresolved", "low", "manual_review", evidence)
        if len(by_sku) > 1:
            evidence["conflicting_skus"] = sorted(by_sku)
            return self._result(item, ad, variation, None, None, "conflicting_sources", "ambiguous", "manual_review", evidence)

        sku = next(iter(by_sku))
        choices = sorted(by_sku[sku], key=lambda c: CONFIDENCE_RANK[c.confidence], reverse=True)
        selected = choices[0]
        product_ids = {c.product_id for c in choices if c.product_id}
        if len(product_ids) > 1:
            evidence["conflicting_product_ids"] = sorted(product_ids)
            return self._result(item, ad, variation, sku, None, "conflicting_product_links", "ambiguous", "manual_review", evidence)
        product_id = next(iter(product_ids), selected.product_id)
        return self._result(item, ad, variation, sku, product_id, selected.method, selected.confidence, "resolved", evidence)

    @staticmethod
    def _result(item, ad, variation, sku, product_id, method, confidence, review, evidence):
        return MappingResolution(
            external_item_id=str(item.get("id") or ad.get("item_id") or ""),
            external_variation_id=str(variation.get("id") or ""),
            campaign_id=str(ad.get("campaign_id")) if ad.get("campaign_id") is not None else None,
            ad_group_id=str(ad.get("ad_group_id")) if ad.get("ad_group_id") is not None else None,
            family_id=str(ad.get("family_id") or item.get("family_id")) if (ad.get("family_id") or item.get("family_id")) is not None else None,
            sku_code=sku,
            product_id=product_id,
            mapping_method=method,
            confidence=confidence,
            review_status=review,
            evidence=evidence,
        )


def normalize_ads_daily(ad: dict, metric_date: str, attribution_window: str) -> dict:
    metrics = ad.get("metrics") or {}
    return {
        "metricDate": metric_date,
        "campaignId": str(ad.get("campaign_id")) if ad.get("campaign_id") is not None else None,
        "adGroupId": str(ad.get("ad_group_id")) if ad.get("ad_group_id") is not None else None,
        "externalItemId": str(ad.get("item_id") or ad.get("id") or ""),
        "externalVariationId": str(ad.get("variation_id") or ""),
        "prints": metrics.get("prints"),
        "clicks": metrics.get("clicks"),
        "cost": metrics.get("cost"),
        "directAmount": metrics.get("direct_amount"),
        "indirectAmount": metrics.get("indirect_amount"),
        "directUnits": metrics.get("direct_units_quantity"),
        "indirectUnits": metrics.get("indirect_units_quantity"),
        "attributionWindow": attribution_window,
        "sourcePayload": ad,
    }


def derive_ads_ratios(rows: Iterable[dict]) -> dict:
    """Reconstructs ratios from persisted base facts; never treats None as 0."""
    rows = list(rows)
    fields = ("prints", "clicks", "cost", "directAmount", "indirectAmount", "directUnits", "indirectUnits")
    sums = {}
    for field_name in fields:
        values = [row.get(field_name) for row in rows if row.get(field_name) is not None]
        sums[field_name] = sum(values) if values else None
    revenue = None
    if sums["directAmount"] is not None or sums["indirectAmount"] is not None:
        revenue = (sums["directAmount"] or 0) + (sums["indirectAmount"] or 0)
    units = None
    if sums["directUnits"] is not None or sums["indirectUnits"] is not None:
        units = (sums["directUnits"] or 0) + (sums["indirectUnits"] or 0)
    cost, prints, clicks = sums["cost"], sums["prints"], sums["clicks"]
    return {
        **sums,
        "revenue": revenue,
        "units": units,
        "roas": revenue / cost if revenue is not None and cost not in (None, 0) else None,
        "acos": cost / revenue if cost is not None and revenue not in (None, 0) else None,
        "ctr": clicks / prints if clicks is not None and prints not in (None, 0) else None,
        "cpc": cost / clicks if cost is not None and clicks not in (None, 0) else None,
        "cvr": units / clicks if units is not None and clicks not in (None, 0) else None,
    }


def derive_acos_tacos(
    *, ads_spend: float | None, ads_attributed_revenue: float | None,
    total_product_revenue: float | None,
) -> dict[str, NamedRatio]:
    """ACOS and TACOS are separate metrics with different denominators."""
    acos = None
    if ads_spend is not None and ads_attributed_revenue not in (None, 0):
        acos = ads_spend / ads_attributed_revenue
    tacos = None
    if ads_spend is not None and total_product_revenue not in (None, 0):
        tacos = ads_spend / total_product_revenue
    return {
        "acos": NamedRatio("ACOS", acos, "ads_spend", "ads_attributed_revenue"),
        "tacos": NamedRatio("TACOS", tacos, "ads_spend", "total_product_revenue"),
    }


def compare_acos_to_break_even(metric: NamedRatio, acos_break_even: float) -> dict:
    """Economic break-even accepts ACOS only; TACOS is contextual."""
    if metric.name != "ACOS" or metric.denominator != "ads_attributed_revenue":
        raise ValueError("ACOS_BREAK_EVEN solo puede compararse contra ACOS; TACOS es contextual")
    return {
        "acos": metric.value,
        "acos_break_even": acos_break_even,
        "sustainable": None if metric.value is None else metric.value <= acos_break_even,
    }


def normalize_listing_snapshot(
    *, item: dict, snapshot_date: str, visits: int | None, visits_window_days: int | None,
    ad: dict | None = None, variation: dict | None = None, promotion: dict | None = None,
    stock_full: int | None = None, stock_seller: int | None = None,
    visits_payload: dict | None = None,
) -> dict:
    ad = ad or {}
    variation = variation or {}
    available = variation.get("available_quantity") if variation else item.get("available_quantity")
    return {
        "snapshotDate": snapshot_date,
        "externalItemId": str(item.get("id") or ""),
        "externalVariationId": str(variation.get("id") or ""),
        "status": variation.get("status") or item.get("status"),
        "listingTypeId": item.get("listing_type_id"),
        "price": variation.get("price") if variation.get("price") is not None else item.get("price"),
        "originalPrice": item.get("original_price"),
        "promotion": promotion,
        "logisticType": (item.get("shipping") or {}).get("logistic_type"),
        "stockAvailable": available,
        "stockFull": stock_full,
        "stockSeller": stock_seller,
        "visits": visits,
        "visitsWindowDays": visits_window_days,
        "campaignId": str(ad.get("campaign_id")) if ad.get("campaign_id") is not None else None,
        "adGroupId": str(ad.get("ad_group_id")) if ad.get("ad_group_id") is not None else None,
        "familyId": str(ad.get("family_id") or item.get("family_id")) if (ad.get("family_id") or item.get("family_id")) is not None else None,
        "sourcePayload": {
            "item": item, "variation": variation or None, "ad": ad or None,
            # last=1 is a moving UTC interval and can contain two calendar
            # buckets. Persist the raw series so a future formula can rebuild
            # calendar-day facts without using total_visits blindly.
            "visits": visits_payload,
        },
    }


def economic_component(
    value: Decimal | float | int | None,
    *, source: str,
    confidence: str,
    coverage: float | None,
    estimated: bool,
    blocked_reason: str | None = None,
    tax_included: bool | None = None,
    tax_rate: Decimal | float | int | None = None,
    tax_amount: Decimal | float | int | None = None,
    tax_source: str | None = None,
    allocation_method: str | None = None,
) -> dict:
    """Missing is represented by value=None. It is never coerced to zero."""
    if confidence not in {"high", "medium", "low", "blocked"}:
        raise ValueError("confidence inválida")
    return {
        "value": float(value) if value is not None else None,
        "source": source,
        "confidence": confidence,
        "coverage": coverage,
        "estimated": bool(estimated),
        "real": value is not None and not estimated,
        "blocked_reason": blocked_reason,
        "tax_included": tax_included,
        "tax_rate": float(tax_rate) if tax_rate is not None else None,
        "tax_amount": float(tax_amount) if tax_amount is not None else None,
        "tax_source": tax_source,
        "allocation_method": allocation_method,
    }


def blocked_tax_components() -> dict:
    """Explicit IVA contract for Phase 1: unknown evidence is NULL/BLOCKED."""
    return {
        name: economic_component(
            None, source="UNRECONCILED", confidence="blocked", coverage=None,
            estimated=False, blocked_reason=f"{name.upper()}_NOT_RECONCILED",
        )
        for name in TAX_COMPONENT_NAMES
    }


def shipping_economic_component(
    value: Decimal | float | int | None,
    *, source: str,
    coverage: float | None,
    allocation_method: str | None = None,
    blocked_reason: str | None = None,
) -> dict:
    """Build shipping economics using only the audited source hierarchy."""
    if source in PROHIBITED_SHIPPING_SOURCES or "BASE_COST" in source.upper():
        raise ValueError("shipping.base_cost esta prohibido como costo economico seller")
    if source not in SHIPPING_SOURCE_PRIORITY and source != "UNRECONCILED":
        raise ValueError("fuente logistica invalida")
    if value is None:
        return economic_component(
            None, source=source, confidence="blocked", coverage=coverage,
            estimated=False, blocked_reason=blocked_reason or "SHIPPING_NOT_RECONCILED",
            allocation_method=allocation_method,
        )
    estimated = source == "ACCOUNT_RATIO_ESTIMATE"
    confidence = "low" if estimated else ("high" if source == "REAL_SETTLEMENT" else "medium")
    return economic_component(
        value, source=source, confidence=confidence, coverage=coverage,
        estimated=estimated, allocation_method=allocation_method,
    )


def blocked_unattributed_logistics_cashback() -> dict:
    """Account-level cashback must not be silently allocated to a SKU."""
    return economic_component(
        None, source="UNRECONCILED", confidence="blocked", coverage=None,
        estimated=False, blocked_reason="LOGISTICS_CASHBACK_NOT_ATTRIBUTABLE_TO_SKU",
        allocation_method=None,
    )


def fiscal_scenarios_change_sign(contributions: Iterable[Decimal | float | int | None]) -> bool:
    """True when plausible known scenarios cross zero; missing is not zero."""
    known = [Decimal(str(value)) for value in contributions if value is not None]
    return bool(known) and min(known) < 0 < max(known)


def economic_recommendation_allowed(
    *, overall_confidence: str,
    scenario_contributions: Iterable[Decimal | float | int | None] = (),
) -> bool:
    """Safety gate only; it does not classify or recommend an action."""
    return overall_confidence != "blocked" and not fiscal_scenarios_change_sign(scenario_contributions)


def build_shadow_economics_row(
    metric_date: date,
    sku_code: str,
    components: dict,
    product_id: str | None = None,
    critical_components: Iterable[str] | None = None,
) -> dict:
    blocked = [name for name, component in components.items() if component.get("value") is None]
    known = [component for component in components.values() if component.get("value") is not None]
    critical = set(DEFAULT_CRITICAL_ECONOMIC_COMPONENTS if critical_components is None else critical_components)
    critical_blocked = sorted(
        name for name in critical
        if name not in components
        or components[name].get("value") is None
        or components[name].get("confidence") == "blocked"
    )
    if critical_blocked or not known:
        confidence = "blocked"
    elif blocked:
        confidence = "low"
    else:
        confidence = min(
            (component.get("confidence", "low") for component in known),
            key=lambda value: CONFIDENCE_RANK.get(value, 0),
            default="low",
        )
    return {
        "metricDate": metric_date.isoformat(),
        "productId": product_id,
        "skuCode": base_sku(sku_code),
        "components": components,
        "contributionPreAds": None,
        "contributionPostAds": None,
        "blockedComponents": blocked,
        "criticalBlockedComponents": critical_blocked,
        "overallConfidence": confidence,
        "economicRecommendationAllowed": False,
    }
