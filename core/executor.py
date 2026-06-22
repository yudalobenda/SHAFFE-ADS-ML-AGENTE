"""Ejecuta las acciones aprobadas por el usuario y guarda el log de cada corrida.

Las acciones operan sobre item_ids (lista de variantes de un mismo producto):
en SHAFFE no se puede mover/pausar una variante sola, así que cada acción
intenta aplicarse a todas las variantes del grupo. Si alguna variante falla,
se sigue con el resto (para no dejar el producto en un estado peor a medias)
y se reporta el detalle de qué falló."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone

from core.ml_client import MLClient

LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")


class Executor:
    def __init__(self, ml_client: MLClient, campaign_ids: dict):
        self.ml = ml_client
        self.campaign_ids = campaign_ids
        self.advertiser_id = campaign_ids.get("advertiser_id")

    def ejecutar(self, acciones_aprobadas: list) -> list:
        resultados = [self._ejecutar_una(accion) for accion in acciones_aprobadas]
        self._guardar_log(resultados)
        return resultados

    def _ejecutar_una(self, accion: dict) -> dict:
        tipo = accion["tipo"]
        try:
            if tipo == "mover_tier":
                self._mover_tier(accion)
            elif tipo == "ajustar_presupuesto":
                self._ajustar_presupuesto(accion)
            elif tipo == "ajustar_roas_target":
                self._ajustar_roas_target(accion)
            elif tipo == "agregar_a_testeo":
                self._agregar_a_campania(accion)
            elif tipo == "agregar_a_promo":
                self._agregar_a_promo(accion)
            elif tipo == "pausar":
                self._pausar(accion)
            else:
                raise ValueError(f"Tipo de acción desconocido: {tipo}")
            return {**accion, "estado": "ejecutada", "timestamp": datetime.now(timezone.utc).isoformat()}
        except Exception as exc:
            return {**accion, "estado": "error", "error": str(exc), "timestamp": datetime.now(timezone.utc).isoformat()}

    def _por_cada_item(self, item_ids: list, fn) -> None:
        errores = []
        for item_id in item_ids:
            try:
                fn(item_id)
            except Exception as exc:
                errores.append(f"{item_id}: {exc}")
        if errores:
            raise RuntimeError(f"Fallaron {len(errores)}/{len(item_ids)} variantes: {'; '.join(errores)}")

    def _mover_tier(self, accion: dict) -> None:
        campania_origen = self.campaign_ids["campañas"][accion["campania_origen"]]
        campania_destino = self.campaign_ids["campañas"][accion["campania_destino"]]

        def mover(item_id: str) -> None:
            self.ml.remove_item_from_campaign(self.advertiser_id, campania_origen, item_id)
            self.ml.add_item_to_campaign(self.advertiser_id, campania_destino, item_id)

        self._por_cada_item(accion["item_ids"], mover)

    def _ajustar_presupuesto(self, accion: dict) -> None:
        campania_id = self.campaign_ids["campañas"][accion["campania"]]
        self.ml.update_campaign_budget(self.advertiser_id, campania_id, accion["presupuesto_nuevo"])

    def _ajustar_roas_target(self, accion: dict) -> None:
        campania_id = self.campaign_ids["campañas"][accion["campania"]]
        self.ml.update_campaign_roas_target(self.advertiser_id, campania_id, accion["roas_target_nuevo"])

    def _agregar_a_campania(self, accion: dict) -> None:
        campania_id = self.campaign_ids["campañas"][accion["campania"]]
        self._por_cada_item(accion["item_ids"], lambda item_id: self.ml.add_item_to_campaign(self.advertiser_id, campania_id, item_id))

    def _agregar_a_promo(self, accion: dict) -> None:
        promotion_id = self.campaign_ids.get("promotion_id")
        if not promotion_id:
            raise ValueError("Falta promotion_id en memory/campaign_ids.json")
        self._por_cada_item(accion["item_ids"], lambda item_id: self.ml.add_item_to_promotion(item_id, promotion_id))

    def _pausar(self, accion: dict) -> None:
        campania_id = self.campaign_ids["campañas"][accion["campania"]]
        self._por_cada_item(accion["item_ids"], lambda item_id: self.ml.pause_item(self.advertiser_id, campania_id, item_id))

    def _guardar_log(self, resultados: list) -> None:
        os.makedirs(LOGS_DIR, exist_ok=True)
        path = os.path.join(LOGS_DIR, f"{date.today().isoformat()}.json")
        existentes = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                existentes = json.load(f)
        existentes.extend(resultados)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existentes, f, ensure_ascii=False, indent=2)
