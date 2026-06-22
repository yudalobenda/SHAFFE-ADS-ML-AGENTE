"""Agente recolector: trae métricas de ML Ads para todas las campañas/items."""
from __future__ import annotations

from datetime import date, timedelta

from core.ml_client import MLClient


class Collector:
    def __init__(self, ml_client: MLClient, advertiser_id: str):
        self.ml = ml_client
        self.advertiser_id = advertiser_id

    def recolectar(self, campaign_ids: dict, dias: int = 30) -> dict:
        """Devuelve {item_id: {"campania": nombre, "metricas": {...}}}"""
        date_to = date.today()
        date_from = date_to - timedelta(days=dias)

        datos_por_item: dict = {}
        for nombre_campania, campania_id in campaign_ids.items():
            if campania_id is None:
                continue
            items = self.ml.get_campaign_items(self.advertiser_id, campania_id)
            for item in items.get("results", []):
                item_id = item["id"]
                metricas = self.ml.get_item_metrics(
                    self.advertiser_id, item_id, date_from.isoformat(), date_to.isoformat()
                )
                datos_por_item[item_id] = {"campania": nombre_campania, "metricas": metricas}
        return datos_por_item

    def items_activos_sin_campania(self, campaign_ids: dict) -> list:
        """Publicaciones activas en ML que no están en ninguna de las 9 campañas (nuevas)."""
        items_en_campanias = set()
        for campania_id in campaign_ids.values():
            if campania_id is None:
                continue
            items = self.ml.get_campaign_items(self.advertiser_id, campania_id)
            items_en_campanias.update(i["id"] for i in items.get("results", []))

        activos = self.ml.get_seller_items(status="active")
        return [item_id for item_id in activos.get("results", []) if item_id not in items_en_campanias]
