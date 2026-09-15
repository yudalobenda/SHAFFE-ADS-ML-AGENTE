"""OPERADOR ML Fase 2 (15/09): corre core/decision_engine.decide() contra
las ActionableUnits YA persistidas por el shadow pipeline diario (ver
run_data_foundation.py) y empuja las recomendaciones accionables a
ads_queue del ERP -- reusa la cola existente (dedup + espejo automático a
operator_tasks vía espejarEnOperatorTasks) en vez de inventar un camino
paralelo. 100% shadow: push_ads_queue jamás escribe en Mercado Libre, solo
deja una fila pendiente_aprobacion para que León (o ChatGPT vía MCP, si
tiene permiso) la apruebe.

Pensado para correr como paso extra del cron diario, después de que
run_data_foundation.py ya publicó las actionable_units del día.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from core.ads_actionable_unit import ActionableUnit, VariantRef
from core.decision_context import build_context, index_ads_by_item
from core.decision_engine import (
    CAMPAIGN_CORREGIR, CAMPAIGN_MOTORES, CAMPAIGN_POTENCIALES, CAMPAIGN_RECUPERAR, CAMPAIGN_RENTABLES, decide,
)
from core.erp_client import ERPClient
from core.margin import calcular_margen_real
from core.ml_client import MLClient

BASE = Path(__file__).resolve().parent

# Mismos 5 campaign_id reales que ya usa el ERP (operatorTasksCore.js
# CAMPANIAS_ADS_REAL), invertido id->nombre para current_campaign.
CAMPANIAS_ADS_REAL = {
    "359121717": CAMPAIGN_MOTORES, "359130777": CAMPAIGN_POTENCIALES,
    "359121756": CAMPAIGN_CORREGIR, "359147661": CAMPAIGN_RENTABLES, "359147625": CAMPAIGN_RECUPERAR,
}


def _rehydrate_unit(row: dict) -> ActionableUnit:
    variants = tuple(
        VariantRef(
            item_id=v.get("itemId"), sku_code=v.get("skuCode"),
            talle=v.get("talle"), color=v.get("color"), user_product_id=v.get("userProductId"),
        )
        for v in (row.get("affected_variants") or [])
    )
    return ActionableUnit(
        actionable_unit_id=f"ad_group:{row['ad_group_id']}",
        ad_group_id=str(row["ad_group_id"]),
        ad_group_type=row["ad_group_type"],
        ad_group_external_id=row.get("ad_group_external_id") or "",
        campaign_id=row.get("campaign_id"),
        action_scope=row["action_scope"],
        affected_mlas=tuple(row.get("affected_mlas") or []),
        affected_variants=variants,
        affected_user_products=tuple(row.get("affected_user_products") or []),
        parent_skus=tuple(row.get("parent_skus") or []),
        source=row.get("source") or "erp_persisted",
        confidence=row["confidence"],
        verified_at=row["verified_at"],
        integrity_ok=bool(row.get("integrity_ok")),
        integrity_issue=row.get("integrity_issue"),
        evidence=row.get("evidence") or {},
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Procesar solo las primeras N unidades (debug)")
    parser.add_argument("--dry-run", action="store_true", help="Decide pero no empuja nada a ads_queue")
    args = parser.parse_args()

    load_dotenv(BASE / ".env")
    tokens = json.loads((BASE / "memory" / "ml_tokens.json").read_text(encoding="utf-8"))
    ml = MLClient(tokens)
    erp = ERPClient(
        os.environ.get("ERP_BASE_URL", "http://127.0.0.1:3000"),
        os.environ.get("ERP_EMAIL", ""), os.environ.get("ERP_PASSWORD", ""),
    )

    units_raw = erp._request("GET", "/api/ads-data-foundation/actionable-units")
    if args.limit:
        units_raw = units_raw[:args.limit]
    print(f"[decision-engine-shadow] {len(units_raw)} actionable units a evaluar")

    today = date.today().isoformat()
    ads_rows = ml.search_ads_daily_foundation_todas("MLA", "21757", today)
    ads_by_item = index_ads_by_item(ads_rows)
    erp_token = erp._ensure_token()

    # Contribución real pre-Ads por SKU (liquidación MP conciliada - COGS
    # ERP), ventana 30d -- sin esto decide() bloquea el 100% de las unidades
    # (economic_confidence siempre 'blocked'), confirmado en vivo hoy con
    # margin_by_sku=None. sku_ads={} a propósito: decision_engine usa
    # net_real/cogs crudos (contribución PRE-Ads), nunca margin_value/pct
    # (esos sí restan ads_cost y darían una base circular).
    date_from = (date.today() - timedelta(days=30)).isoformat()
    print(f"[decision-engine-shadow] calculando margen real conciliado {date_from} a {today}...")
    real_margin_by_sku = calcular_margen_real(ml, erp, date_from, today, sku_ads={})
    ok_skus = sum(1 for v in real_margin_by_sku.values() if isinstance(v, dict) and v.get("status") == "ok")
    print(f"[decision-engine-shadow] margen real: {ok_skus} SKUs con status=ok de {len(real_margin_by_sku) - 1}")

    counts = {"KEEP_TESTING": 0, "NO_ACTION": 0, "BLOCKED": 0, "REPLENISH_BEFORE_SCALE": 0, "pushed": 0, "push_failed": 0}
    for row in units_raw:
        try:
            unit = _rehydrate_unit(row)
            ctx = build_context(
                unit, ads_by_item=ads_by_item, erp=erp,
                erp_base_url=erp.base_url, erp_token=erp_token,
                campaign_name_by_id=CAMPANIAS_ADS_REAL, real_margin_by_sku=real_margin_by_sku,
            )
            rec = decide(unit, ctx)
        except Exception as exc:
            print(f"  [{row.get('ad_group_id')}] ERROR evaluando: {exc}")
            continue

        accion = rec.to_legacy_accion()
        if accion is None:
            counts[rec.recommended_action] = counts.get(rec.recommended_action, 0) + 1
            continue

        if args.dry_run:
            print(f"  [{unit.actionable_unit_id}] {rec.recommended_action}: {rec.reason}")
            counts["pushed"] += 1
            continue

        result = erp.push_ads_queue(accion)
        if result is not None:
            counts["pushed"] += 1
        else:
            counts["push_failed"] += 1

    print(f"[decision-engine-shadow] resultado: {counts}")


if __name__ == "__main__":
    main()
