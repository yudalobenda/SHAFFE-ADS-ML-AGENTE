"""Reglas de negocio: tiers, umbrales de ROAS, clasificación de ticket, alertas."""
from __future__ import annotations

TIERS = ("testeo", "plata", "oro")
TIERS_ORDEN = {"testeo": 0, "plata": 1, "oro": 2}

TICKET_BAJO_MAX = 18999
TICKET_MEDIO_MAX = 39999

ROAS_TARGET = {
    "oro": 6.5,
    "plata": 4.0,
    "testeo": 3.0,
}
ROAS_PLATA_RANGE = (4.0, 6.5)

DIAS_SOSTENIDO_TESTEO_A_PLATA = 12
DIAS_SOSTENIDO_PLATA_A_ORO = 7
DIAS_CAIDA_PARA_BAJAR_TIER = 7
DIAS_GRACIA_NUEVA_PUB = 12
DIAS_SIN_CONVERSION_ULTIMO_INTENTO = (10, 15)

CTR_ALERTA_MIN = 0.02
CVR_ALERTA_MIN = 0.01

STOCK_BAJO_UNIDADES = 5
STOCK_BAJO_VARIANTES_DISPONIBLES = 2


def clasificar_ticket(precio: float) -> str:
    if precio <= TICKET_BAJO_MAX:
        return "bajo"
    if precio <= TICKET_MEDIO_MAX:
        return "medio"
    return "alto"


def nombre_campania(tier: str, ticket: str) -> str:
    return f"{tier}_{ticket}"


def tier_y_ticket(nombre_campania: str) -> tuple:
    tier, _, ticket = nombre_campania.partition("_")
    return tier, ticket


def es_subida_tier(tier_origen: str, tier_destino: str) -> bool:
    return TIERS_ORDEN[tier_destino] > TIERS_ORDEN[tier_origen]


def roas_target_to_acos_target(roas_target: float) -> float:
    return (1 / roas_target) * 100


def acos_target_to_roas_target(acos_target: float) -> float:
    return 1 / (acos_target / 100)


def evaluar_movimiento_tier(tier_actual: str, historial_roas: list) -> str | None:
    """historial_roas: ROAS diarios, más reciente al final.
    Devuelve el tier destino si corresponde mover, o None si se mantiene."""
    if not historial_roas:
        return None

    if tier_actual == "testeo":
        if historial_roas[-1] >= ROAS_TARGET["oro"]:
            return "oro"
        sostenido = historial_roas[-DIAS_SOSTENIDO_TESTEO_A_PLATA:]
        if len(sostenido) >= DIAS_SOSTENIDO_TESTEO_A_PLATA and all(
            ROAS_PLATA_RANGE[0] <= r <= ROAS_PLATA_RANGE[1] for r in sostenido
        ):
            return "plata"
        return None

    if tier_actual == "plata":
        sostenido_oro = historial_roas[-DIAS_SOSTENIDO_PLATA_A_ORO:]
        if len(sostenido_oro) >= DIAS_SOSTENIDO_PLATA_A_ORO and all(
            r >= ROAS_TARGET["oro"] for r in sostenido_oro
        ):
            return "oro"
        caida = historial_roas[-DIAS_CAIDA_PARA_BAJAR_TIER:]
        if len(caida) >= DIAS_CAIDA_PARA_BAJAR_TIER and all(
            r < ROAS_PLATA_RANGE[0] for r in caida
        ):
            return "testeo"
        return None

    if tier_actual == "oro":
        caida = historial_roas[-DIAS_CAIDA_PARA_BAJAR_TIER:]
        if len(caida) >= DIAS_CAIDA_PARA_BAJAR_TIER and all(
            r < ROAS_TARGET["oro"] for r in caida
        ):
            return "plata"
        return None

    return None


def alertas_metricas(impresiones: int, clics: int, conversiones: int) -> list:
    alertas = []
    if impresiones == 0:
        return alertas
    ctr = clics / impresiones
    if ctr < CTR_ALERTA_MIN and impresiones >= 100:
        alertas.append("ctr_bajo")
    if clics > 0:
        cvr = conversiones / clics
        if cvr < CVR_ALERTA_MIN and clics >= 30:
            alertas.append("cvr_bajo")
    return alertas


def es_poco_stock(unidades_totales: int, variantes_disponibles: int) -> bool:
    return (
        unidades_totales < STOCK_BAJO_UNIDADES
        or variantes_disponibles <= STOCK_BAJO_VARIANTES_DISPONIBLES
    )
