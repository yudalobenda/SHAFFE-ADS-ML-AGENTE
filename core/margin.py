"""Margen real por SKU: net real de liquidacion MP - costo ERP real - Ads real.

Reemplaza la tabla MARGIN hardcodeada que tenia generar_panel_decisiones_2026_08_12.py
(escrita a mano en otra sesion, sin fuente reproducible). Auditada el 12/08/2026 contra
datos reales: 13/38 SKUs diferian 8+ puntos porcentuales, siempre subestimando el margen
real (ver memory/feedback_panel_ads_economia_2026_08_12.md y
reportes_manuales/2026-08-12/notas_auditoria_margen_real.md).

El costo se pide por CODIGO de SKU padre (ERPClient.cost_by_code), no por item_id via
channel_product_links: el costo del ERP se carga una vez por producto padre y es el mismo
para todas sus variantes de talle/color, pero el vinculo item_id->producto tiene huecos
reales (variantes nunca vinculadas a ML aunque el producto si tenga costo cargado).

REESCRITO DE RAIZ EL 25/08/2026 — segundo bug estructural encontrado en el mismo dia:
la version anterior reconstruia fee/envio pieza por pieza desde la API de items/shipments
de ML, y cada intento de "arreglarlo" (restar shipment.base_cost entero, despues restar
shipping_option.cost) seguia sin coincidir con la plata real que muestra el panel de
ventas de ML. Se detecto con casos reales (venta de 5N999, order 2000018110556756): la
API de Shipments no expone "Costo fijo" (SI esta incluido en sale_fee, verificado igual)
ni "Bonificacion por envio" (un cashback real de +$4.490 que ML no liga a la orden en
NINGUN campo de esa API). La UNICA fuente que reconcilia con la plata real es el reporte
oficial de liquidacion de Mercado Pago que el ERP ya importa solo cada 12hs
(mp_settlement_movements, ver ERPClient.settlement_movements) - gross_amount/ml_fee/
shipping_cost/iibb_tax/net_amount ahi SI vienen conciliados contra lo que efectivamente
se cobro. Ya no se llama a ml.search_orders_todas para revenue/fee/envio (ni a
/shipments/{id}, que ya no hace falta) - solo para las UNIDADES reales vendidas por SKU
(necesarias para el costo de mercaderia), porque mp_settlement_movements no trae cantidad.

LIMITACION REAL QUE QUEDA (no es un bug, es un hueco real del dato): las bonificaciones/
cashback de Mercado Envios Flex llegan como un monto agregado de TODA la cuenta
(sale_detail="bonificaciones_flex_fc", sku=None, order_id=None) - Mercado Pago no las
liga a una venta puntual, asi que NO se pueden repartir de forma exacta por SKU. Esos
montos quedan aparte en result["_sin_asignar"] (accountwide, no por producto) en vez de
prorratearse a ciegas - el margen por SKU es por lo tanto un piso conservador (real,
verificado, pero levemente menor al beneficio real total de la cuenta).

Regla que este modulo respeta (obligatoria, ver el MD de arriba): si el SKU no tiene costo
cargado en el ERP, o no hubo liquidaciones reales en la ventana, el SKU queda en status
distinto de "ok" y margin_value/margin_pct son None. Nunca completar con una tabla manual
ni una formula generica.
"""
from __future__ import annotations

from collections import defaultdict


def base_sku(value):
    if not value:
        return None
    return str(value).split("|")[0].strip().upper()


def calcular_margen_real(ml, erp, date_from: str, date_to: str, sku_ads: dict) -> dict:
    """Devuelve {sku: {status, margin_value, margin_pct, units, revenue, note, ...}},
    mas una clave especial "_sin_asignar" con el total de bonificaciones/cashback reales
    de la cuenta que Mercado Pago no liga a ningun SKU (ver nota del modulo).

    status:
      - "ok": net_amount real (liquidacion MP) - costo_erp - ads_cost calculado.
      - "sin_ventas": no hubo liquidaciones reales del SKU en la ventana.
      - "sin_costo_erp": el código de SKU no tiene costo cargado en products.cost del ERP.
    """
    movimientos = erp.settlement_movements(date_from, date_to)

    sku_gross: dict = defaultdict(float)
    sku_fee: dict = defaultdict(float)
    sku_envio: dict = defaultdict(float)
    sku_tax: dict = defaultdict(float)
    sku_net: dict = defaultdict(float)
    sku_ventas_liquidadas: dict = defaultdict(int)
    sin_asignar = 0.0

    for m in movimientos:
        sku = base_sku(m.get("sku"))
        net = float(m.get("net_amount") or 0)
        if not sku:
            sin_asignar += net
            continue
        sku_gross[sku] += float(m.get("gross_amount") or 0)
        sku_fee[sku] += float(m.get("ml_fee") or m.get("fee_amount") or 0)
        sku_envio[sku] += float(m.get("shipping_cost") or 0)
        sku_tax[sku] += float(m.get("iibb_tax") or 0)
        sku_net[sku] += net
        if m.get("operation_type") == "Pago aprobado":
            sku_ventas_liquidadas[sku] += 1

    # unidades reales: mp_settlement_movements no trae cantidad, asi que se pide aparte
    # a la API de ordenes de ML solo para esto (costo de mercaderia = unit_cost * units).
    orders = ml.search_orders_todas(date_from, date_to, status="paid")
    sku_units: dict = defaultdict(float)
    sku_ordenes_ml = defaultdict(int)
    for order in orders:
        for line in order.get("order_items", []):
            item = line.get("item") or {}
            sku = base_sku(item.get("seller_sku") or item.get("seller_custom_field"))
            qty = float(line.get("quantity") or 0)
            if sku and qty > 0:
                sku_units[sku] += qty
                sku_ordenes_ml[sku] += 1

    # SALVAGUARDA (agregada 25/08/2026 tras el caso 6N002): la liquidacion de MP se
    # asienta con demora real, sobre todo en pagos en cuotas (semanas/meses) - un SKU
    # puede tener 74 unidades reales vendidas segun la API de ordenes pero solo 3
    # liquidadas todavia, lo que da un margen catastrofico FALSO (cogs de 74 unidades
    # contra revenue de solo 3). Si la cobertura de liquidacion real es baja, el SKU
    # queda en "liquidacion_incompleta" en vez de un numero engañoso.
    cobertura_liquidacion = {
        sku: (sku_ventas_liquidadas.get(sku, 0) / sku_ordenes_ml[sku]) if sku_ordenes_ml.get(sku) else 1.0
        for sku in sku_ordenes_ml
    }
    UMBRAL_COBERTURA_MINIMA = 0.5

    todos_los_skus = set(sku_gross.keys()) | set(sku_units.keys())
    cost_by_code = erp.cost_by_code(sorted(todos_los_skus))

    result: dict = {"_sin_asignar": sin_asignar}
    for sku in todos_los_skus:
        revenue = sku_gross.get(sku, 0.0)
        units = sku_units.get(sku, 0.0)
        ads_cost = float(sku_ads.get(sku, 0.0) or 0.0)

        if revenue <= 0:
            result[sku] = {
                "status": "sin_ventas", "margin_value": None, "margin_pct": None,
                "units": units, "revenue": revenue,
                "note": "Sin liquidaciones reales de MP en la ventana; no hay base para calcular margen.",
            }
            continue

        cobertura = cobertura_liquidacion.get(sku, 1.0)
        if cobertura < UMBRAL_COBERTURA_MINIMA:
            result[sku] = {
                "status": "liquidacion_incompleta", "margin_value": None, "margin_pct": None,
                "units": units, "revenue": revenue, "cobertura_liquidacion_pct": cobertura * 100,
                "note": (
                    f"Solo el {cobertura*100:.0f}% de las ventas de {sku} en la ventana ya liquidaron en MP "
                    f"(el resto probablemente en cuotas, liquida mas adelante) - calcular margen ahora "
                    f"compararia el costo de TODAS las unidades contra el revenue de solo las liquidadas, "
                    f"dando un numero falso. Reintentar mas adelante o acotar la ventana a fechas mas viejas."
                ),
            }
            continue

        unit_cost = cost_by_code.get(sku)
        if unit_cost is None:
            result[sku] = {
                "status": "sin_costo_erp", "margin_value": None, "margin_pct": None,
                "units": units, "revenue": revenue,
                "note": f"El SKU {sku} no tiene costo cargado en el ERP (products.cost); cargarlo antes de confirmar margen.",
            }
            continue

        cogs = unit_cost * units
        net_real = sku_net.get(sku, 0.0)  # ya neto de fee ML + envio + impuestos, conciliado con MP
        margin_value = net_real - cogs - ads_cost
        margin_pct = margin_value / revenue * 100 if revenue else None
        result[sku] = {
            "status": "ok", "margin_value": margin_value, "margin_pct": margin_pct,
            "units": units, "revenue": revenue, "fee": sku_fee.get(sku, 0.0), "envio": sku_envio.get(sku, 0.0),
            "tax": sku_tax.get(sku, 0.0), "net_real": net_real, "cogs": cogs, "ads_cost": ads_cost,
            "unit_cost": unit_cost,
            "note": f"liquidacion real MP (fee+envio+impuestos ya netos) - costo ERP (${unit_cost:,.0f}/u) - Ads, {date_from} a {date_to}.".replace(",", "."),
        }

    return result
