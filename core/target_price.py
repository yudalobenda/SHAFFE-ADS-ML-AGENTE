"""Precio objetivo real por SKU: generaliza calcular_precio_objetivo.py (que
vivía hardcodeado a 10 códigos puntuales de "comisión alta") en una función
reutilizable, para cualquier SKU, con margen objetivo configurable (no solo
"empatar en cero").

Usa la MISMA fórmula oficial que erp.rentabilidad_sku (IVA + IIBB real +
comisión real + costo real + envío real + Ads real) -- nunca un % de
comisión estimado: la comisión se recalcula con el simulador real de ML
(/sites/MLA/listing_prices) para cada precio candidato, porque la comisión
de ML no es un % fijo (depende de precio y categoría).

Supuestos explícitos, heredados del script original (no repetir el error de
mezclar componentes sin decirlo):
  - unidades vendidas: se asume la MISMA cantidad que el mes de referencia
    -- no se puede predecir cómo cambia la demanda real si sube el precio,
    eso requeriría un test real (ver Recovery Engine / retest).
  - envío y Ads: se mantiene el monto ABSOLUTO real del mes (no dependen
    directamente del precio de venta).
  - costo de mercadería: fijo.
  - IVA e IIBB: escalan proporcionalmente al nuevo precio, igual que la
    fórmula oficial del ERP."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

IVA_FRAC = 1 - 1 / 1.21


@dataclass(frozen=True)
class TargetPriceResult:
    found: bool
    precio_objetivo: float | None
    margen_neto_pct_a_ese_precio: float | None
    incremento_pct_vs_actual: float | None
    precio_actual: float
    margen_neto_actual: float
    margen_neto_objetivo_pct: float
    iteraciones: int
    motivo: str | None = None  # cuando found=False


def find_target_price(
    *,
    precio_actual: float,
    unidades: float,
    costo_total: float,
    envio_fijo: float,
    ads_fijo: float,
    iibb_rate_efectiva: float,
    comision_por_precio: Callable[[float], float | None],
    margen_neto_actual: float,
    margen_neto_objetivo_pct: float = 0.0,
    max_incremento_pct: float = 1.0,
    paso_pct: float = 0.05,
) -> TargetPriceResult:
    """comision_por_precio(precio) -> comisión real de ML por unidad a ese
    precio, o None si el simulador no devolvió nada (I/O ya resuelto por el
    caller -- esta función es pura para poder testearse sin red)."""
    if unidades <= 0 or precio_actual <= 0:
        return TargetPriceResult(
            False, None, None, None, precio_actual, margen_neto_actual, margen_neto_objetivo_pct, 0,
            motivo="sin unidades vendidas o precio actual inválido para proyectar",
        )

    precio_test = precio_actual
    iteraciones = 0
    max_iter = int(max_incremento_pct / paso_pct) + 1
    while iteraciones < max_iter:
        iteraciones += 1
        facturacion_test = precio_test * unidades
        comision_unit = comision_por_precio(precio_test)
        if comision_unit is None:
            return TargetPriceResult(
                False, None, None, None, precio_actual, margen_neto_actual, margen_neto_objetivo_pct, iteraciones,
                motivo="el simulador de comisión de ML no devolvió dato para ese precio/categoría",
            )
        comision_total_test = comision_unit * unidades
        iva_test = facturacion_test * IVA_FRAC
        iibb_test = facturacion_test * iibb_rate_efectiva
        margen_bruto_test = facturacion_test - iva_test - comision_total_test - costo_total
        margen_neto_test = margen_bruto_test - ads_fijo - envio_fijo - iibb_test
        margen_neto_pct_test = (margen_neto_test / facturacion_test) if facturacion_test else None
        if margen_neto_pct_test is not None and margen_neto_pct_test >= margen_neto_objetivo_pct:
            return TargetPriceResult(
                True, precio_test, margen_neto_pct_test, (precio_test / precio_actual - 1),
                precio_actual, margen_neto_actual, margen_neto_objetivo_pct, iteraciones,
            )
        precio_test *= 1 + paso_pct

    return TargetPriceResult(
        False, None, None, None, precio_actual, margen_neto_actual, margen_neto_objetivo_pct, iteraciones,
        motivo=f"no alcanza ni subiendo el precio {max_incremento_pct*100:.0f}% — el problema no es de precio, es estructural",
    )


def resolve_target_price_for_code(
    erp, ml, *, code: str, month: str, category_id: str, margen_neto_objetivo_pct: float = 0.0,
) -> TargetPriceResult | None:
    """I/O real: erp.rentabilidad_sku (fuente única de verdad de margen NETO
    real, ya con IVA/IIBB/comisión/costo/envío/Ads reales del mes) + el
    simulador oficial de comisión de ML por precio. category_id lo resuelve
    el caller (normalmente ya lo tiene del catálogo cacheado) para no volver
    a traer todo el catálogo por cada SKU. Devuelve None si el SKU no tiene
    fila en rentabilidad_sku ese mes (sin ventas, o sin costo cargado)."""
    filas = {r["code"]: r for r in erp.rentabilidad_sku(month)}
    r = filas.get(code)
    if not r or not r.get("unidades") or not r.get("precioPromedio"):
        return None
    iibb_rate_efectiva = (r["iibbPropio"] / r["facturacion"]) if r.get("facturacion") else 0

    def comision_por_precio(precio: float) -> float | None:
        resp = ml._request("GET", "/sites/MLA/listing_prices", params={"price": precio, "category_id": category_id})
        fila = next((x for x in resp if x.get("listing_type_id") == "gold_special"), None)
        return fila["sale_fee_amount"] if fila else None

    return find_target_price(
        precio_actual=r["precioPromedio"], unidades=r["unidades"], costo_total=r["costoTotal"],
        envio_fijo=r["envio"], ads_fijo=r["ads"], iibb_rate_efectiva=iibb_rate_efectiva,
        comision_por_precio=comision_por_precio, margen_neto_actual=r["margenNeto"],
        margen_neto_objetivo_pct=margen_neto_objetivo_pct,
    )
