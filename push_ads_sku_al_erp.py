"""Calcula el gasto real de Ads por SKU del mes en curso (misma lógica de
mapeo item_id->sku que reportes_manuales/2026-08-11/extraer_rentabilidad.py:
primero por venta real del item en el mes, si no por seller_custom_field del
item) y lo empuja al ERP (POST /api/economics/ad-spend-by-sku) para que
/api/reports/rentabilidad-sku deje de prorratear el Ads de este SKU y use el
dato real.

Solo lectura sobre ML, solo escritura sobre la tabla ad_spend_by_sku del ERP
(no toca precios, campañas ni nada de la cuenta real de ML).
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from core.ml_client import MLClient  # noqa: E402
from core.erp_client import ERPClient  # noqa: E402


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


def main():
    today = date.today()
    month = f"{today.year:04d}-{today.month:02d}"
    date_from = f"{month}-01"
    date_to = today.isoformat()

    tokens = json.loads((BASE / "memory" / "ml_tokens.json").read_text(encoding="utf-8"))
    ml = MLClient(tokens)

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
    for order in orders:
        for line in order.get("order_items", []):
            item = line.get("item") or {}
            item_id = str(item.get("id") or "")
            sku = base_sku(item.get("seller_sku") or item.get("seller_custom_field"))
            qty = float(line.get("quantity") or 0)
            unit_price = float(line.get("unit_price") or line.get("full_unit_price") or 0)
            if item_id and sku:
                item_to_skus[item_id][sku] += (qty * unit_price) or qty

    ids = [str(r.get("item_id") or r.get("id")) for r in spenders]
    details = {}
    for i in range(0, len(ids), 20):
        for it in ml.get_items_multiget(ids[i:i + 20], attributes="id,title,seller_custom_field"):
            details[str(it.get("id"))] = it

    sku_ads: dict = defaultdict(float)
    sin_mapear = 0
    for row in spenders:
        item_id = str(row.get("item_id") or row.get("id"))
        detail = details.get(item_id, {})
        sku_weights = item_to_skus.get(item_id, {})
        sku = max(sku_weights, key=sku_weights.get) if sku_weights else base_sku(detail.get("seller_custom_field"))
        if not sku:
            sku = sku_from_title(detail.get("title") or row.get("title"))
        cost = float((row.get("metrics") or {}).get("cost") or 0)
        if sku:
            sku_ads[sku] += cost
        else:
            sin_mapear += cost

    rows_payload = [{"code": sku, "cost": round(cost, 2)} for sku, cost in sku_ads.items()]

    erp = ERPClient(os.environ["ERP_BASE_URL"], os.environ["ERP_EMAIL"], os.environ["ERP_PASSWORD"])
    resp = erp._request(
        "POST", "/api/economics/ad-spend-by-sku",
        json={"month": month, "channel": "ml_ads", "source": f"agente_ads_ml_{today.isoformat()}", "rows": rows_payload},
    )

    (BASE / "memory" / "ml_tokens.json").write_text(json.dumps(ml.tokens_actuales(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "month": month, "periodo": [date_from, date_to],
        "skus_con_ads": len(rows_payload), "gasto_sin_mapear": round(sin_mapear, 2),
        "erp_response": resp,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
