"""Entry point. Modos:
  python main.py collect          -> análisis semanal (lunes 9am ART), genera reporte Excel y lo envía
  python main.py check-approvals  -> revisa aprobaciones pendientes en Telegram y ejecuta lo aprobado
"""
from __future__ import annotations

import json
import os
import sys

from datetime import date, timedelta

from dotenv import load_dotenv

import core.campaign_rules as reglas
from agents.analyst import Analyst
from agents.collector import Collector
from agents.copywriter import Copywriter
from agents.report_agent import ReportAgent
from agents.stock_agent import StockAgent
from agents.structurer import Structurer
from agents.telegram_agent import TelegramAgent
from core.executor import Executor
from core.ml_client import MLClient

BASE_DIR = os.path.dirname(__file__)
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
LOGS_DIR = os.path.join(BASE_DIR, "logs")


def _cargar_json(nombre: str):
    with open(os.path.join(MEMORY_DIR, nombre), "r", encoding="utf-8") as f:
        return json.load(f)


def _guardar_json(nombre: str, datos) -> None:
    with open(os.path.join(MEMORY_DIR, nombre), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


def _crear_ml_client() -> MLClient:
    return MLClient(_cargar_json("ml_tokens.json"))


def _guardar_tokens_ml(ml: MLClient) -> None:
    """El refresh_token de ML puede rotar en cada uso: persistir siempre."""
    _guardar_json("ml_tokens.json", ml.tokens_actuales())


VENTANA_HISTORIAL_DIAS = 60


def _actualizar_historial(historial_por_grupo: dict, grupo_id, roas: float) -> list:
    """Agrega/actualiza la entrada de hoy y devuelve la serie completa como lista de floats."""
    clave = str(grupo_id)
    historial = historial_por_grupo.setdefault(clave, [])
    hoy = date.today().isoformat()
    if historial and historial[-1]["fecha"] == hoy:
        historial[-1]["roas"] = roas
    else:
        historial.append({"fecha": hoy, "roas": roas})
    del historial[:-VENTANA_HISTORIAL_DIAS]
    return [h["roas"] for h in historial]


def _calcular_dias_en_oro(fecha_entrada_oro: dict, clave: str) -> int:
    """Días transcurridos desde que el producto entró a una campaña Oro."""
    fecha_str = fecha_entrada_oro.get(clave)
    if not fecha_str:
        return 999  # producto que siempre estuvo en oro: no bloquearlo
    try:
        return (date.today() - date.fromisoformat(fecha_str)).days
    except ValueError:
        return 999


def modo_collect() -> None:
    load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))

    campaign_ids = _cargar_json("campaign_ids.json")
    learnings = _cargar_json("learnings.json")
    state = _cargar_json("state.json")
    historial_roas = _cargar_json("roas_history.json")
    changes_history = _cargar_json("changes_history.json")

    advertiser_id = campaign_ids.get("advertiser_id")
    site_id = campaign_ids.get("site_id")
    if advertiser_id is None or site_id is None:
        raise RuntimeError("Falta advertiser_id o site_id en memory/campaign_ids.json")

    fecha_entrada_oro: dict = state.setdefault("fecha_entrada_oro", {})

    ml = _crear_ml_client()
    collector = Collector(ml, site_id, advertiser_id)
    analyst = Analyst(learnings)
    structurer = Structurer()
    stock_agent = StockAgent()
    copywriter = Copywriter()

    grupos = collector.recolectar(campaign_ids["campañas"])

    acciones: list = []
    alertas_urgentes: list = []

    for family_id, grupo in grupos.items():
        if len(grupo["tiers_detectados"]) > 1:
            acciones.append({
                "tipo": "tier_dividido",
                "item_ids": grupo["item_ids"],
                "family_name": grupo["family_name"],
                "tiers_detectados": grupo["tiers_detectados"],
            })
            continue

        nombre_campania_actual = grupo["tiers_detectados"][0]
        tier_actual, ticket = reglas.tier_y_ticket(nombre_campania_actual)
        roas_objetivo = reglas.roas_target_campania(nombre_campania_actual)

        analisis = analyst.analizar_item(family_id, nombre_campania_actual, grupo["metricas"])

        for alerta in analisis["alertas"]:
            # Filtrar CTR/CVR cuando el ROAS ya supera el objetivo: el funnel rinde bien
            if alerta in ("ctr_bajo", "cvr_bajo") and analisis["roas"] >= roas_objetivo:
                continue
            acciones.append({
                "tipo": "alerta",
                "item_ids": grupo["item_ids"],
                "family_name": grupo["family_name"],
                "alerta": alerta,
                "roas": analisis["roas"],
                "acos": analisis["acos"],
                "campania": nombre_campania_actual,
                "recomendacion": reglas.recomendacion_alerta(alerta, analisis["roas"], nombre_campania_actual),
            })

        serie_roas = _actualizar_historial(historial_roas, family_id, analisis["roas"])

        # Detección de caída urgente (alerta fuera del ciclo semanal normal)
        if analyst.detectar_caida_urgente(family_id, nombre_campania_actual, serie_roas):
            roas_historico_previo = serie_roas[:-reglas.DIAS_CAIDA_URGENTE]
            roas_prom_historico = sum(roas_historico_previo) / len(roas_historico_previo) if roas_historico_previo else 0.0
            caida_pct = ((roas_prom_historico - analisis["roas"]) / roas_prom_historico * 100) if roas_prom_historico > 0 else 0.0
            alertas_urgentes.append({
                "tipo": "alerta_urgente",
                "item_ids": grupo["item_ids"],
                "family_name": grupo["family_name"],
                "campania": nombre_campania_actual,
                "roas_historico_prom": round(roas_prom_historico, 2),
                "roas_ultimos_dias": serie_roas[-reglas.DIAS_CAIDA_URGENTE:],
                "roas_actual": analisis["roas"],
                "caida_pct": round(caida_pct, 1),
                "dias_cayendo": reglas.DIAS_CAIDA_URGENTE,
                "acos_actual": analisis["acos"],
            })

        unidades_totales, variantes_disponibles = collector.obtener_stock(grupo["item_ids"])
        poco_stock = reglas.es_poco_stock(unidades_totales, variantes_disponibles)

        dias_en_oro = _calcular_dias_en_oro(fecha_entrada_oro, str(family_id))
        decision = analyst.decidir_movimiento_tier(family_id, nombre_campania_actual, serie_roas, dias_en_oro)

        if decision:
            if decision["accion"] == "pausar":
                acciones.append({
                    "tipo": "pausar",
                    "item_ids": grupo["item_ids"],
                    "family_name": grupo["family_name"],
                    "motivo": decision["motivo"],
                    "roas_reciente": decision["roas_reciente"],
                    "campania": nombre_campania_actual,
                })
            else:
                accion_mover = structurer.construir_movimiento(
                    grupo["item_ids"], grupo["family_name"], ticket,
                    decision["tier_origen"], decision["tier_destino"], decision["roas_reciente"],
                )
                # Asegurarse de que campania_destino venga del analyst (ya tiene el nombre completo correcto)
                accion_mover["campania_destino"] = decision["campania_destino"]
                if poco_stock and reglas.es_subida_tier(decision["tier_origen"], decision["tier_destino"]):
                    accion_mover["poco_stock"] = True
                acciones.append(accion_mover)

        accion_stock = stock_agent.evaluar(
            grupo["item_ids"], grupo["family_name"], nombre_campania_actual,
            unidades_totales, variantes_disponibles, fin_de_temporada=False,
        )
        if accion_stock:
            acciones.append(accion_stock)

    nuevas = collector.items_activos_sin_campania(campaign_ids["campañas"])
    candidatas_sin_ads = {}
    for family_id, grupo in nuevas.items():
        item_ids = grupo["item_ids"]
        try:
            items_data = ml.get_items_multiget(
                item_ids[:20],
                attributes="id,title,price,available_quantity,status,shipping",
            )
        except Exception:
            items_data = []

        precio = 0
        titulo = grupo.get("family_name", "")
        unidades = 0
        variantes_disp = 0
        envio_gratis = False

        if items_data:
            precios = [i.get("price", 0) for i in items_data if i.get("price")]
            precio = max(precios) if precios else 0
            titulo = items_data[0].get("title") or titulo
            unidades = sum(i.get("available_quantity", 0) for i in items_data)
            variantes_disp = sum(1 for i in items_data if i.get("available_quantity", 0) > 0)
            envio_gratis = any(
                (i.get("shipping") or {}).get("free_shipping", False) for i in items_data
            )

        ticket = reglas.clasificar_ticket(precio) if precio else "medio"
        campania_rec = f"testeo_{ticket}"

        if unidades >= 10:
            prioridad = "Alta"
            motivo = (
                f"Publicación activa sin Ads — {unidades} uds en {variantes_disp} talles/colores disponibles. "
                f"Stock suficiente. Entrar a {campania_rec} con presupuesto mínimo."
            )
        elif unidades >= 5:
            prioridad = "Media"
            motivo = (
                f"Publicación activa sin Ads — {unidades} uds en {variantes_disp} talles/colores. "
                f"Stock justo. Reponer antes de escalar; entrar a {campania_rec} solo si repone."
            )
        else:
            prioridad = "Baja"
            motivo = (
                f"Publicación activa sin Ads — solo {unidades} uds disponibles. "
                f"Reponer stock primero. No conviene poner en Ads con tan poco inventario."
            )

        candidatas_sin_ads[str(family_id)] = {
            "family_name": titulo,
            "item_ids": item_ids,
            "precio": precio,
            "ticket": ticket,
            "campania_recomendada": campania_rec,
            "stock_total": unidades,
            "variantes_disponibles": variantes_disp,
            "envio_gratis": "✅ Sí" if envio_gratis else "No",
            "prioridad": prioridad,
            "motivo": motivo,
        }

    semana_str = date.today().strftime("%d/%m/%Y")
    telegram = TelegramAgent()

    # Alertas urgentes van primero, sin esperar el batch semanal
    if alertas_urgentes:
        telegram.enviar_alertas_urgentes(alertas_urgentes)

    telegram.enviar_reporte(acciones)

    # Reporte Excel
    report_agent = ReportAgent()
    ruta_xlsx = report_agent.generar(
        grupos=grupos,
        acciones=acciones,
        alertas_urgentes=alertas_urgentes,
        candidatas_sin_ads=candidatas_sin_ads,
        changes_history=changes_history,
        semana=semana_str,
    )
    telegram.enviar_archivo(ruta_xlsx, caption=f"📊 Reporte semanal SHAFFE Ads — {semana_str}")

    state["acciones_pendientes"] = acciones
    state["ultima_corrida"] = "collect"
    _guardar_json("state.json", state)
    _guardar_json("roas_history.json", historial_roas)
    _guardar_tokens_ml(ml)


def modo_check_approvals() -> None:
    load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))

    state = _cargar_json("state.json")
    acciones = state.get("acciones_pendientes", [])
    if not acciones:
        print("No hay acciones pendientes de aprobación.")
        return

    campaign_ids = _cargar_json("campaign_ids.json")
    changes_history = _cargar_json("changes_history.json")
    telegram = TelegramAgent()
    decisiones = telegram.obtener_aprobaciones(acciones, timeout_seg=240)

    aprobadas = [acciones[i] for i, aprobado in decisiones.items() if aprobado]
    if aprobadas:
        ml = _crear_ml_client()
        executor = Executor(ml, campaign_ids)
        resultados = executor.ejecutar(aprobadas)
        _guardar_tokens_ml(ml)

        # Registrar en historial los movimientos ejecutados
        hoy = date.today().isoformat()
        fecha_entrada_oro: dict = state.setdefault("fecha_entrada_oro", {})
        for accion in aprobadas:
            if accion.get("tipo") == "mover_tier":
                entrada = {
                    "fecha": hoy,
                    "mla": accion["item_ids"][0] if accion["item_ids"] else "",
                    "publicacion": accion.get("family_name", ""),
                    "cambio": f"{accion.get('campania_origen', accion.get('tier_origen', ''))} → {accion.get('campania_destino', accion.get('tier_destino', ''))}",
                    "roas_antes": accion.get("roas_reciente"),
                    "roas_despues_7d": None,
                    "resultado": "pendiente",
                    "tier_origen": accion.get("tier_origen", ""),
                    "tier_destino": accion.get("tier_destino", ""),
                }
                changes_history.append(entrada)
                # Registrar fecha de entrada a oro para respetar los 15 días
                if accion.get("tier_destino") == "oro":
                    for item_id in accion.get("item_ids", []):
                        fecha_entrada_oro[item_id] = hoy
                    # También por family_id si está disponible
                    if "grupo_id" in accion:
                        fecha_entrada_oro[str(accion["grupo_id"])] = hoy

        _guardar_json("changes_history.json", changes_history)
        print(f"Ejecutadas {len(resultados)} acciones aprobadas.")
    else:
        print("Sin aprobaciones nuevas todavía.")

    pendientes_restantes = [a for i, a in enumerate(acciones) if i not in decisiones]
    state["acciones_pendientes"] = pendientes_restantes
    _guardar_json("state.json", state)


def main() -> None:
    load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))
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
