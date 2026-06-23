"""Entry point. Modos:
  python main.py collect          -> corre el análisis semanal y envía el reporte (martes 9am ART)
  python main.py check-approvals  -> revisa aprobaciones pendientes en Telegram y ejecuta lo aprobado
"""
from __future__ import annotations

import json
import os
import sys

from datetime import date

from dotenv import load_dotenv

import core.campaign_rules as reglas
from agents.analyst import Analyst
from agents.collector import Collector
from agents.copywriter import Copywriter
from agents.stock_agent import StockAgent
from agents.structurer import Structurer
from agents.telegram_agent import TelegramAgent
from core.executor import Executor
from core.ml_client import MLClient

BASE_DIR = os.path.dirname(__file__)
MEMORY_DIR = os.path.join(BASE_DIR, "memory")


def _cargar_json(nombre: str):
    with open(os.path.join(MEMORY_DIR, nombre), "r", encoding="utf-8") as f:
        return json.load(f)


def _guardar_json(nombre: str, datos) -> None:
    with open(os.path.join(MEMORY_DIR, nombre), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


def _crear_ml_client() -> MLClient:
    return MLClient(_cargar_json("ml_tokens.json"))


def _guardar_tokens_ml(ml: MLClient) -> None:
    """El refresh_token de ML puede rotar en cada uso: hay que releerlo del
    cliente después de cada corrida y persistirlo, o la próxima corrida falla."""
    _guardar_json("ml_tokens.json", ml.tokens_actuales())


VENTANA_HISTORIAL_DIAS = 60


def _actualizar_historial(historial_por_grupo: dict, grupo_id, roas: float) -> list:
    """Agrega/actualiza la entrada de hoy en el historial de ROAS del grupo y
    devuelve la serie completa (lista de floats, más reciente al final)."""
    clave = str(grupo_id)
    historial = historial_por_grupo.setdefault(clave, [])
    hoy = date.today().isoformat()
    if historial and historial[-1]["fecha"] == hoy:
        historial[-1]["roas"] = roas
    else:
        historial.append({"fecha": hoy, "roas": roas})
    del historial[:-VENTANA_HISTORIAL_DIAS]
    return [h["roas"] for h in historial]


def modo_collect() -> None:
    campaign_ids = _cargar_json("campaign_ids.json")
    learnings = _cargar_json("learnings.json")
    state = _cargar_json("state.json")
    historial_roas = _cargar_json("roas_history.json")

    advertiser_id = campaign_ids.get("advertiser_id")
    site_id = campaign_ids.get("site_id")
    if advertiser_id is None or site_id is None:
        raise RuntimeError("Falta advertiser_id o site_id en memory/campaign_ids.json")

    ml = _crear_ml_client()
    collector = Collector(ml, site_id, advertiser_id)
    analyst = Analyst(learnings)
    structurer = Structurer()
    stock_agent = StockAgent()
    copywriter = Copywriter()

    grupos = collector.recolectar(campaign_ids["campañas"])

    acciones: list = []
    for family_id, grupo in grupos.items():
        if len(grupo["tiers_detectados"]) > 1:
            acciones.append({
                "tipo": "tier_dividido",
                "item_ids": grupo["item_ids"],
                "family_name": grupo["family_name"],
                "tiers_detectados": grupo["tiers_detectados"],
            })
            continue  # no se evalúan alertas/movimientos hasta que esté en una sola campaña

        analisis = analyst.analizar_item(family_id, grupo["metricas"])
        for alerta in analisis["alertas"]:
            acciones.append({
                "tipo": "alerta", "item_ids": grupo["item_ids"], "family_name": grupo["family_name"],
                "alerta": alerta, "roas": analisis["roas"],
            })

        nombre_campania_actual = grupo["tiers_detectados"][0]
        tier_actual, ticket = reglas.tier_y_ticket(nombre_campania_actual)
        serie_roas = _actualizar_historial(historial_roas, family_id, analisis["roas"])

        unidades_totales, variantes_disponibles = collector.obtener_stock(grupo["item_ids"])
        poco_stock = reglas.es_poco_stock(unidades_totales, variantes_disponibles)

        decision = analyst.decidir_movimiento_tier(family_id, tier_actual, serie_roas)
        if decision:
            accion_mover = structurer.construir_movimiento(
                grupo["item_ids"], grupo["family_name"], ticket,
                decision["tier_origen"], decision["tier_destino"], decision["roas_reciente"],
            )
            if poco_stock and reglas.es_subida_tier(decision["tier_origen"], decision["tier_destino"]):
                # No se frena la subida solo: el usuario decide si puede
                # reponer. Pero no tiene sentido aprobarla sin saber que el
                # producto tiene poco stock, así que va anotado en la misma
                # propuesta en vez de en un mensaje aparte sin contexto.
                accion_mover["poco_stock"] = True
            acciones.append(accion_mover)

        accion_stock = stock_agent.evaluar(
            grupo["item_ids"], grupo["family_name"], nombre_campania_actual,
            unidades_totales, variantes_disponibles, fin_de_temporada=False,
        )
        if accion_stock:
            acciones.append(accion_stock)
        # TODO: copywriter.sugerir_ultimo_intento() para pubs de testeo sin
        # conversiones 10-15 días: falta wirear "días sin conversión" (no viene
        # directo de ads/search, hay que derivarlo de units_quantity=0 sostenido
        # en el historial) y el título/descripción real del producto.

    nuevas = collector.items_activos_sin_campania(campaign_ids["campañas"])
    for family_id, grupo in nuevas.items():
        # TODO: clasificar_ticket(precio real del producto, vía ml.get_item) y
        # validar stock antes de proponer el alta con
        # structurer.construir_alta_testeo(...).
        pass

    telegram = TelegramAgent()
    telegram.enviar_reporte(acciones)

    state["acciones_pendientes"] = acciones
    state["ultima_corrida"] = "collect"
    _guardar_json("state.json", state)
    _guardar_json("roas_history.json", historial_roas)
    _guardar_tokens_ml(ml)


def modo_check_approvals() -> None:
    state = _cargar_json("state.json")
    acciones = state.get("acciones_pendientes", [])
    if not acciones:
        print("No hay acciones pendientes de aprobación.")
        return

    campaign_ids = _cargar_json("campaign_ids.json")
    telegram = TelegramAgent()
    decisiones = telegram.obtener_aprobaciones(acciones, timeout_seg=240)

    aprobadas = [acciones[i] for i, aprobado in decisiones.items() if aprobado]
    if aprobadas:
        ml = _crear_ml_client()
        executor = Executor(ml, campaign_ids)
        resultados = executor.ejecutar(aprobadas)
        _guardar_tokens_ml(ml)
        print(f"Ejecutadas {len(resultados)} acciones aprobadas.")
    else:
        print("Sin aprobaciones nuevas todavía.")

    pendientes_restantes = [a for i, a in enumerate(acciones) if i not in decisiones]
    state["acciones_pendientes"] = pendientes_restantes
    _guardar_json("state.json", state)


def main() -> None:
    load_dotenv()
    modo = sys.argv[1] if len(sys.argv) > 1 else "collect"
    if modo == "collect":
        modo_collect()
    elif modo == "check-approvals":
        modo_check_approvals()
    else:
        print(f"Modo desconocido: {modo}. Usar 'collect' o 'check-approvals'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
