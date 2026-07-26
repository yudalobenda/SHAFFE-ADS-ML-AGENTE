"""Script de analisis manual (solo lectura) para generar un reporte ad-hoc
campana por campana. NO envia Telegram, NO ejecuta acciones, NO modifica
memory/state.json ni roas_history.json -- solo lee y vuelca todo a un JSON
para poder armar el reporte fuera de este script."""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(__file__)
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))

import core.campaign_rules as reglas
from agents.analyst import Analyst
from agents.collector import Collector
from agents.stock_agent import StockAgent
from core.ml_client import MLClient

MEMORY_DIR = os.path.join(BASE_DIR, "memory")


def _cargar_json(nombre):
    with open(os.path.join(MEMORY_DIR, nombre), encoding="utf-8") as f:
        return json.load(f)


def _dias_desde(fecha_dict, clave):
    fecha_str = fecha_dict.get(clave)
    if not fecha_str:
        return 999
    try:
        return (date.today() - date.fromisoformat(fecha_str)).days
    except ValueError:
        return 999


def main():
    campaign_ids = _cargar_json("campaign_ids.json")
    learnings = _cargar_json("learnings.json")
    state = _cargar_json("state.json")

    advertiser_id = campaign_ids["advertiser_id"]
    site_id = campaign_ids["site_id"]

    ml = MLClient(_cargar_json("ml_tokens.json"))
    collector = Collector(ml, site_id, advertiser_id)
    analyst = Analyst(learnings)
    stock_agent = StockAgent()

    fecha_entrada_oro = state.get("fecha_entrada_oro", {})
    fecha_entrada_campania = state.get("fecha_entrada_campania", {})

    grupos = collector.recolectar(campaign_ids["campañas"], dias=30)

    salida_por_campania = {c: [] for c in campaign_ids["campañas"]}
    tier_dividido = []

    for family_id, grupo in grupos.items():
        item_ids = grupo["item_ids"]
        unidades_totales, variantes_disp = collector.obtener_stock(item_ids)

        if len(grupo["tiers_detectados"]) > 1:
            tier_dividido.append({
                "family_id": str(family_id),
                "family_name": grupo["family_name"],
                "item_ids": item_ids,
                "tiers_detectados": grupo["tiers_detectados"],
                "metricas": grupo["metricas"],
                "stock": unidades_totales,
                "variantes_disp": variantes_disp,
            })
            continue

        nombre_campania = grupo["tiers_detectados"][0]
        analisis = analyst.analizar_item(family_id, nombre_campania, grupo["metricas"])
        roas = analisis["roas"]
        gasto = grupo["metricas"].get("cost", 0.0)
        tiene_presupuesto = reglas.tiene_presupuesto_real(gasto, analisis["impresiones"])

        dias_en_oro = _dias_desde(fecha_entrada_oro, str(family_id))
        dias_en_tier = _dias_desde(fecha_entrada_campania, str(family_id))

        decision = None
        if tiene_presupuesto:
            decision = analyst.decidir_movimiento_tier(
                family_id, nombre_campania, [roas], dias_en_oro, dias_en_tier
            )

        poco_stock = reglas.es_poco_stock(unidades_totales, variantes_disp, len(item_ids))
        accion_stock_normal = stock_agent.evaluar(
            item_ids, grupo["family_name"], nombre_campania,
            unidades_totales, variantes_disp, fin_de_temporada=False,
        )

        salida_por_campania[nombre_campania].append({
            "family_id": str(family_id),
            "family_name": grupo["family_name"],
            "item_ids": item_ids,
            "metricas": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in grupo["metricas"].items()},
            "impresiones": analisis["impresiones"],
            "clics": analisis["clics"],
            "unidades_vendidas_atrib": analisis["conversiones"],
            "alertas": analisis["alertas"],
            "recomendaciones_alertas": [
                reglas.recomendacion_alerta(a, roas, nombre_campania) for a in analisis["alertas"]
            ],
            "tiene_presupuesto_real": tiene_presupuesto,
            "stock_total": unidades_totales,
            "variantes_disponibles": variantes_disp,
            "poco_stock": poco_stock,
            "accion_stock_sugerida": accion_stock_normal,
            "dias_en_tier_actual": dias_en_tier,
            "dias_en_oro": dias_en_oro,
            "decision_tier": decision,
            "roas_target_campania": reglas.roas_target_campania(nombre_campania),
            "acos_max_campania": reglas.acos_max_campania(nombre_campania),
        })

    # Candidatas sin ads (activas fuera de campanas conocidas)
    nuevas = collector.items_activos_sin_campania(campaign_ids["campañas"])
    candidatas = []
    for family_id, grupo in nuevas.items():
        item_ids = grupo["item_ids"]
        try:
            items_data = ml.get_items_multiget(
                item_ids[:20],
                attributes="id,title,price,available_quantity,status,shipping,sold_quantity,listing_type_id,catalog_listing",
            )
        except Exception as e:
            items_data = []
            print(f"error multiget {family_id}: {e}")

        precio = max((i.get("price", 0) for i in items_data if i.get("price")), default=0)
        titulo = items_data[0].get("title") if items_data else grupo.get("family_name", "")
        unidades = sum(i.get("available_quantity", 0) for i in items_data)
        variantes_disp = sum(1 for i in items_data if i.get("available_quantity", 0) > 0)
        envio_gratis = any((i.get("shipping") or {}).get("free_shipping", False) for i in items_data)
        sold_total = sum(i.get("sold_quantity", 0) for i in items_data)
        listing_type = items_data[0].get("listing_type_id", "") if items_data else ""
        ticket = reglas.clasificar_ticket(precio) if precio else "medio"

        candidatas.append({
            "family_id": str(family_id),
            "family_name": titulo,
            "item_ids": item_ids,
            "precio_max": precio,
            "ticket": ticket,
            "campania_recomendada": f"testeo_{ticket}",
            "stock_total": unidades,
            "variantes_disponibles": variantes_disp,
            "envio_gratis": envio_gratis,
            "sold_quantity_historico": sold_total,
            "listing_type": listing_type,
        })

    resultado = {
        "fecha": date.today().isoformat(),
        "campañas": salida_por_campania,
        "tier_dividido": tier_dividido,
        "candidatas_sin_ads": candidatas,
    }

    out_path = os.path.join(BASE_DIR, "analisis_manual_output.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    # NO guardamos tokens actualizados en ml_tokens.json a proposito para no
    # interferir -- en realidad SI hay que guardarlos porque el refresh_token
    # rota; si no se guarda, la proxima corrida real puede fallar el refresh.
    with open(os.path.join(MEMORY_DIR, "ml_tokens.json"), "w", encoding="utf-8") as f:
        json.dump(ml.tokens_actuales(), f, ensure_ascii=False, indent=2)

    print(f"OK -> {out_path}")
    print(f"Campanas con productos: {sum(1 for v in salida_por_campania.values() if v)}/9")
    print(f"Total productos activos en ads: {sum(len(v) for v in salida_por_campania.values())}")
    print(f"Tier dividido: {len(tier_dividido)}")
    print(f"Candidatas sin ads: {len(candidatas)}")


if __name__ == "__main__":
    main()
