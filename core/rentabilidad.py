"""Cruce en vivo de gasto de Ads por SKU con ventas reales del mismo período.

Extraído de reportes_manuales/2026-08-11/extraer_rentabilidad.py (que tenía el
período 01-11/08 hardcodeado) para que generar_panel_decisiones_2026_08_12.py
y push_ads_sku_al_erp.py dejen de depender de un archivo estático de un día
puntual — cada corrida recalcula con datos reales del rango que se le pida.
"""
from __future__ import annotations

from collections import defaultdict


def base_sku(value):
    if not value:
        return None
    return str(value).split("|")[0].strip().upper()


TITLE_ALIASES = {
    "remera termica hombre manga larga primera piel": "MLX001",
    "remera termica niño manga larga super abrigada": "MLX002",
    "pantalon jean baggy niño denim algodon": "MLX005",
    "campera hombre inflable liviana abrigada tipo uniqlo": "CA004",
    "pantalon hombre corte chino gabardina semi recto": "1N981",
    "piloto lluvia impermeable hombre": "ML001",
}


def sku_from_title(title):
    normalized = (title or "").lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    for needle, sku in TITLE_ALIASES.items():
        if needle.replace("ó", "o").replace("í", "i") in normalized:
            return sku
    return None


def calcular_rentabilidad_cruzada(ml, date_from: str, date_to: str) -> dict:
    """{"period", "ads_rows", "sku_ads", "sku_sales"} — mismo shape que el
    rentabilidad_cruce.json histórico, calculado en vivo para [date_from, date_to]."""
    ads_raw = ml.search_ads_todas("MLA", "21757", date_from, date_to)
    dedup = {}
    for row in ads_raw:
        item_id = str(row.get("item_id") or row.get("id") or "")
        if not item_id:
            continue
        old = dedup.get(item_id)
        if old is None or (old.get("status") != "active" and row.get("status") == "active"):
            dedup[item_id] = row
    spenders = [r for r in dedup.values() if float((r.get("metrics") or {}).get("cost") or 0) > 0]

    orders = ml.search_orders_todas(date_from, date_to, status="paid")
    item_to_skus: dict = defaultdict(lambda: defaultdict(float))
    sku_sales: dict = defaultdict(lambda: {"units": 0.0, "revenue": 0.0, "fee": 0.0, "premium_revenue": 0.0, "classic_revenue": 0.0})
    for order in orders:
        for line in order.get("order_items", []):
            item = line.get("item") or {}
            item_id = str(item.get("id") or "")
            sku = base_sku(item.get("seller_sku") or item.get("seller_custom_field"))
            qty = float(line.get("quantity") or 0)
            unit_price = float(line.get("unit_price") or line.get("full_unit_price") or 0)
            revenue = qty * unit_price
            fee = float(line.get("sale_fee") or 0)
            listing = item.get("listing_type_id") or ""
            if item_id and sku:
                item_to_skus[item_id][sku] += revenue or qty
                rec = sku_sales[sku]
                rec["units"] += qty
                rec["revenue"] += revenue
                rec["fee"] += fee
                if listing == "gold_pro":
                    rec["premium_revenue"] += revenue
                else:
                    rec["classic_revenue"] += revenue

    ids = [str(r.get("item_id") or r.get("id")) for r in spenders]
    details_by_id = {}
    for i in range(0, len(ids), 20):
        for it in ml.get_items_multiget(ids[i:i + 20], attributes="id,title,status,price,listing_type_id,seller_custom_field,category_id,family_name"):
            details_by_id[str(it.get("id"))] = it

    ads_rows = []
    sku_ads: dict = defaultdict(float)
    for row in spenders:
        item_id = str(row.get("item_id") or row.get("id"))
        detail = details_by_id.get(item_id, {})
        sku_weights = item_to_skus.get(item_id, {})
        method = "venta_item"
        sku = max(sku_weights, key=sku_weights.get) if sku_weights else base_sku(detail.get("seller_custom_field"))
        if not sku:
            sku = sku_from_title(detail.get("title") or row.get("title"))
            method = "alias_titulo" if sku else "sin_mapear"
        elif not sku_weights:
            method = "seller_custom_field"
        metrics = row.get("metrics") or {}
        cost = float(metrics.get("cost") or 0)
        if sku:
            sku_ads[sku] += cost
        ads_rows.append({
            "item_id": item_id,
            "title": detail.get("title") or row.get("title") or "",
            "listing_type_id": detail.get("listing_type_id") or row.get("listing_type_id") or "",
            "status": row.get("status") or detail.get("status") or "",
            "cost": cost,
            "direct_amount": float(metrics.get("direct_amount") or 0),
            "indirect_amount": float(metrics.get("indirect_amount") or 0),
            "total_amount": float(metrics.get("total_amount") or 0),
            "sku": sku,
            "mapping_method": method,
        })

    return {
        "period": [date_from, date_to],
        "ads_rows": sorted(ads_rows, key=lambda x: x["cost"], reverse=True),
        "sku_ads": dict(sku_ads),
        "sku_sales": dict(sku_sales),
    }
