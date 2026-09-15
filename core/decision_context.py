"""Arma el `context` dict real que core/decision_engine.decide() necesita
para una ActionableUnit, a partir de datos ya traidos de ML Ads y del ERP
(fuente canonica de costo/stock, ver core/erp_client.py). Este modulo hace
I/O (ML + ERP), pero deja el calculo de ratios a
core/data_foundation.derive_ads_ratios (ya testeado) en vez de reinventarlo.

No calcula total_revenue/TACOS todavia (requeriria ventas totales reales por
SKU en la misma ventana, no solo lo atribuido a Ads) -- limitacion explicita
de esta primera version, ver core/decision_engine.py. coverage_days tampoco
se calcula todavia (requeriria velocity real de ventas 30d/60d por SKU, que
el ERP no expone hoy en un endpoint directo) -- queda None, nunca inventado."""
from __future__ import annotations

from core.data_foundation import derive_ads_ratios


def index_ads_by_item(ads_rows: list) -> dict:
    """ads_rows: resultado de MLClient.search_ads_todas (una fila por
    item_id/dia agregado por ML, con metrics ya planas segun ADS_METRICS).
    Devuelve item_id -> lista de rows (puede haber mas de una fila por
    item_id si search_ads_todas no viene ya agregado por dia)."""
    index: dict[str, list] = {}
    for row in ads_rows:
        item_id = str(row.get("item_id") or row.get("id") or "")
        if not item_id:
            continue
        index.setdefault(item_id, []).append(row)
    return index


def _row_to_ratio_input(row: dict) -> dict:
    metrics = row.get("metrics") or row
    return {
        "prints": metrics.get("prints"),
        "clicks": metrics.get("clicks"),
        "cost": metrics.get("cost"),
        "directAmount": metrics.get("direct_amount"),
        "indirectAmount": metrics.get("indirect_amount"),
        "directUnits": metrics.get("direct_items_quantity") or metrics.get("direct_units_quantity"),
        "indirectUnits": metrics.get("indirect_items_quantity") or metrics.get("indirect_units_quantity"),
    }


def aggregate_ads_metrics(affected_mlas: tuple, ads_by_item: dict) -> dict:
    rows = [_row_to_ratio_input(r) for item_id in affected_mlas for r in ads_by_item.get(item_id, [])]
    ratios = derive_ads_ratios(rows)
    return {
        "spend_30d": ratios["cost"],
        "prints_30d": ratios["prints"],
        "clicks_30d": ratios["clicks"],
        "units_ads_30d": ratios["units"],
        "roas": ratios["roas"],
        "acos": ratios["acos"],
        "revenue_ads_30d": ratios["revenue"],
    }


def compute_margin_break_even(*, revenue_ads_30d: float | None, units_ads_30d: float | None,
                               cost: float | None) -> dict:
    """ROAS/ACOS de equilibrio real de la unidad, a partir de su margen
    bruto (precio efectivo realizado - costo ERP). Un ROAS de 10x con margen
    bruto de 8% ES UNA PÉRDIDA, no un éxito: para ganar plata con Ads hay que
    superar el ROAS de equilibrio (1 / margen_bruto_pct), no un umbral fijo
    igual para todos los productos.

    LIMITACIÓN EXPLÍCITA: esto es margen BRUTO (precio - COGS), no la
    contribución operativa completa que pide el proyecto (que también resta
    comisión real de ML y shipping real) — esa versión completa necesita
    settlement_movements por SKU, que todavía no está conectado acá. Por eso
    es un piso conservador *optimista*: el break-even REAL (con comisión y
    envío restados) es más exigente que el que devuelve esta función, nunca
    menos. Devuelve None en todo si falta precio o costo — nunca inventa un
    margen."""
    precio_efectivo = None
    if revenue_ads_30d is not None and units_ads_30d:
        precio_efectivo = revenue_ads_30d / units_ads_30d
    if precio_efectivo is None or cost is None or precio_efectivo <= 0:
        return {"precio_efectivo": precio_efectivo, "margin_pct": None, "acos_break_even": None, "roas_break_even": None}
    margin_pct = (precio_efectivo - cost) / precio_efectivo
    if margin_pct <= 0:
        # Margen bruto ya negativo antes de gastar un peso en Ads: no hay
        # ROAS que lo salve, cualquier gasto en Ads profundiza la pérdida.
        return {"precio_efectivo": precio_efectivo, "margin_pct": margin_pct, "acos_break_even": 0.0, "roas_break_even": float("inf")}
    return {
        "precio_efectivo": precio_efectivo,
        "margin_pct": margin_pct,
        "acos_break_even": margin_pct,
        "roas_break_even": 1 / margin_pct,
    }


def compute_settled_break_even(*, margin_by_sku: dict | None, parent_skus: list[str]) -> dict:
    """Calcula el ACOS/ROAS máximo sostenible con economía conciliada.

    ``core.margin.calcular_margen_real`` ya trae, por SKU, el neto real de
    Mercado Pago (comisión, envío e impuestos descontados) y el COGS del
    ERP. Para decidir Ads importa la contribución *antes* de Ads:

        contribucion_pre_ads = net_real - cogs
        acos_break_even = contribucion_pre_ads / revenue

    No usa ``margin_value`` porque ese campo ya resta Ads y produciría una
    circularidad. Si falta aunque sea un SKU o su liquidación no está en
    status=ok, bloquea la economía en vez de completar con promedios.
    """
    empty = {
        "margin_basis": "settlement_mp_pre_ads",
        "margin_pct": None,
        "acos_break_even": None,
        "roas_break_even": None,
        "economic_confidence": "blocked",
        "economic_issue": None,
    }
    if not margin_by_sku or not parent_skus:
        return {**empty, "economic_issue": "Falta economía conciliada por SKU."}

    rows = []
    missing = []
    for sku in parent_skus:
        row = margin_by_sku.get(sku)
        if not row or row.get("status") != "ok":
            missing.append(f"{sku}:{(row or {}).get('status', 'sin_dato')}")
        else:
            rows.append(row)
    if missing:
        return {**empty, "economic_issue": "Economía no conciliada: " + ", ".join(missing)}

    revenue = sum(float(row.get("revenue") or 0) for row in rows)
    net_real = sum(float(row.get("net_real") or 0) for row in rows)
    cogs = sum(float(row.get("cogs") or 0) for row in rows)
    if revenue <= 0:
        return {**empty, "economic_issue": "La liquidación conciliada no tiene facturación positiva."}

    margin_pct = (net_real - cogs) / revenue
    if margin_pct <= 0:
        return {
            **empty,
            "margin_pct": margin_pct,
            "acos_break_even": 0.0,
            "roas_break_even": float("inf"),
            "economic_confidence": "high",
            "economic_issue": None,
        }
    return {
        **empty,
        "margin_pct": margin_pct,
        "acos_break_even": margin_pct,
        "roas_break_even": 1 / margin_pct,
        "economic_confidence": "high",
        "economic_issue": None,
    }


def resolve_parent_sku_and_costs(erp, affected_mlas: list) -> dict:
    """Devuelve {"parent_skus": [...], "cost": float|None}. Usa
    foundation_source_links (ya expuesto por el ERP, /api/ads-data-foundation
    /source-links) para resolver MLA -> sku_code real, y cost_by_code (fuente
    canonica de costo) -- nunca inventa un costo si el link no existe."""
    try:
        links = erp.foundation_source_links(affected_mlas)
    except Exception:
        links = []
    parent_skus = sorted({row["sku_code"] for row in links if row.get("sku_code")})
    cost = None
    if parent_skus:
        costs = erp.cost_by_code(parent_skus)
        known = [costs[s] for s in parent_skus if s in costs]
        if known:
            cost = sum(known) / len(known)  # promedio simple si hay >1 SKU (caso ambiguo, poco común)
    return {"parent_skus": parent_skus, "cost": cost}


def resolve_stock_by_sku(erp_base_url: str, token: str, sku_code: str) -> int | None:
    """Stock total real vía GET /api/products?search=<sku> del ERP -- misma
    fuente que usa la UI de Articulos. Import local de requests para no
    acoplar este modulo a un cliente HTTP concreto."""
    import requests
    r = requests.get(
        f"{erp_base_url}/api/products", params={"search": sku_code},
        headers={"Authorization": f"Bearer {token}"}, timeout=20,
    )
    r.raise_for_status()
    rows = r.json()
    for row in rows:
        if row.get("code") == sku_code:
            return int(row.get("total_stock") or 0)
    return None


def build_context(unit, *, ads_by_item: dict, erp, erp_base_url: str, erp_token: str,
                   campaign_name_by_id: dict, real_margin_by_sku: dict | None = None) -> dict:
    ctx = aggregate_ads_metrics(unit.affected_mlas, ads_by_item)
    ctx["current_campaign"] = campaign_name_by_id.get(unit.campaign_id)
    sku_info = resolve_parent_sku_and_costs(erp, list(unit.affected_mlas))
    stock_total = None
    if sku_info["parent_skus"]:
        stocks = [
            s for s in (resolve_stock_by_sku(erp_base_url, erp_token, sku) for sku in sku_info["parent_skus"])
            if s is not None
        ]
        if stocks:
            stock_total = sum(stocks)
    ctx["stock_total"] = stock_total
    ctx["evidence_cost"] = sku_info["cost"]
    ctx["evidence_parent_skus"] = sku_info["parent_skus"]
    # La decisión usa exclusivamente liquidación MP conciliada. El cálculo
    # bruto se conserva como evidencia diagnóstica, nunca como permiso para
    # escalar o declarar rentabilidad.
    gross = compute_margin_break_even(
        revenue_ads_30d=ctx.get("revenue_ads_30d"), units_ads_30d=ctx.get("units_ads_30d"), cost=sku_info["cost"],
    )
    ctx["gross_margin_evidence"] = gross
    ctx.update(compute_settled_break_even(
        margin_by_sku=real_margin_by_sku, parent_skus=sku_info["parent_skus"],
    ))
    return ctx
