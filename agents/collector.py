"""Agente recolector: trae métricas de ML Ads para todas las campañas/items.

El endpoint de ads/search de ML no filtra por campaign_id ni status (ver
core/ml_client.py), así que acá se trae todo paginado y se filtra localmente.

IMPORTANTE: SHAFFE publica cada variante (talle/color) como un item_id de ML
separado, pero no se puede pausar/mover una variante sola — o se mueve todo
el producto o no se mueve nada. Por eso acá se agrupa todo por `family_id`
(el id de "familia" que ML ya usa para agrupar variantes del mismo producto)
antes de calcular cualquier métrica. El resto del pipeline trabaja sobre
estos grupos, nunca sobre un item_id individual."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from core.ml_client import MLClient

METRICAS_SUMABLES = (
    "clicks", "prints", "cost", "direct_amount", "indirect_amount", "total_amount",
    "direct_units_quantity", "indirect_units_quantity", "units_quantity",
    "advertising_items_quantity", "direct_items_quantity", "indirect_items_quantity",
)


class Collector:
    def __init__(self, ml_client: MLClient, site_id: str, advertiser_id: str):
        self.ml = ml_client
        self.site_id = site_id
        self.advertiser_id = advertiser_id

    def recolectar(self, campaign_ids: dict, dias: int = 30) -> dict:
        """Devuelve {family_id: {"family_name", "item_ids", "tiers_detectados", "metricas"}}.
        tiers_detectados son los nombres de campaña (oro_alto, etc.) en los que
        aparece al menos una variante del grupo: si tiene más de uno, las
        variantes de ese producto están repartidas en campañas distintas
        (inconsistencia real, no la resuelve el agente solo)."""
        date_to = date.today()
        date_from = date_to - timedelta(days=min(dias, 90))
        id_a_nombre = {cid: nombre for nombre, cid in campaign_ids.items() if cid is not None}

        ads = self.ml.search_ads_todas(self.site_id, self.advertiser_id, date_from.isoformat(), date_to.isoformat())

        grupos: dict = {}
        for ad in ads:
            nombre_campania = id_a_nombre.get(ad.get("campaign_id"))
            if nombre_campania is None:
                continue
            family_id = ad.get("family_id") or ad["item_id"]
            grupo = grupos.setdefault(family_id, {
                "family_name": ad.get("family_name") or ad.get("title", ""),
                "item_ids": [],
                "tiers_detectados": set(),
                "metricas": defaultdict(float),
            })
            grupo["item_ids"].append(ad["item_id"])
            grupo["tiers_detectados"].add(nombre_campania)
            for campo, valor in (ad.get("metrics") or {}).items():
                if campo in METRICAS_SUMABLES and isinstance(valor, (int, float)):
                    grupo["metricas"][campo] += valor

        for grupo in grupos.values():
            metricas = grupo["metricas"]
            costo = metricas.get("cost", 0.0)
            ingresos = metricas.get("direct_amount", 0.0) + metricas.get("indirect_amount", 0.0)
            metricas["roas"] = (ingresos / costo) if costo > 0 else 0.0
            grupo["metricas"] = dict(metricas)
            grupo["tiers_detectados"] = sorted(grupo["tiers_detectados"])

        return grupos

    def items_activos_sin_campania(self, campaign_ids: dict) -> dict:
        """Productos (agrupados por family_id) con al menos un item activo en ML
        que no está en ninguna de las 9 campañas conocidas (candidatos a "nuevos")."""
        date_to = date.today()
        date_from = date_to - timedelta(days=7)

        ids_conocidos = {c for c in campaign_ids.values() if c is not None}
        ads = self.ml.search_ads_todas(self.site_id, self.advertiser_id, date_from.isoformat(), date_to.isoformat())
        items_en_campanias_conocidas = {ad["item_id"] for ad in ads if ad.get("campaign_id") in ids_conocidos}

        activos = self.ml.get_seller_items(status="active")
        sin_campania = [item_id for item_id in activos.get("results", []) if item_id not in items_en_campanias_conocidas]

        # Agrupar por family_id usando lo que ya sabemos de ads/search; si un item
        # activo no aparece ni siquiera ahí (nunca se publicitó), queda solo.
        family_por_item = {ad["item_id"]: (ad.get("family_id") or ad["item_id"]) for ad in ads}
        nombre_por_family = {ad.get("family_id") or ad["item_id"]: (ad.get("family_name") or ad.get("title", "")) for ad in ads}

        grupos: dict = {}
        for item_id in sin_campania:
            family_id = family_por_item.get(item_id, item_id)
            grupo = grupos.setdefault(family_id, {"family_name": nombre_por_family.get(family_id, ""), "item_ids": []})
            grupo["item_ids"].append(item_id)
        return grupos
