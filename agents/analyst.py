"""Agente analista: calcula ROAS/CTR/CVR/ACOS, detecta alertas y decide movimientos de tier.

Todo se evalúa a nivel producto (grupo de variantes por family_id), nunca por
item_id individual. Los aprendizajes en memory/learnings.json también deben
quedar guardados con el family_id (como string) en el campo "item_id"."""
from __future__ import annotations

from datetime import date

import core.campaign_rules as reglas


class Analyst:
    def __init__(self, learnings: list):
        self.learnings = learnings

    def analizar_item(self, grupo_id, nombre_campania: str, metricas: dict) -> dict:
        impresiones = metricas.get("prints", 0)
        clics = metricas.get("clicks", 0)
        conversiones = metricas.get("units_quantity", 0)
        roas = metricas.get("roas", 0.0)
        acos = metricas.get("acos")

        alertas = reglas.alertas_metricas(impresiones, clics, conversiones, acos, nombre_campania)

        return {
            "grupo_id": grupo_id,
            "roas": roas,
            "acos": acos,
            "impresiones": impresiones,
            "clics": clics,
            "conversiones": conversiones,
            "alertas": alertas,
        }

    def decidir_movimiento_tier(self, grupo_id, nombre_campania: str, historial_roas: list, dias_en_oro: int = 0) -> dict | None:
        if self._tiene_aprendizaje_bloqueante(grupo_id, "subir_tier") or self._tiene_aprendizaje_bloqueante(grupo_id, "bajar_tier"):
            return None

        destino = reglas.evaluar_movimiento_tier(nombre_campania, historial_roas, dias_en_oro)
        if destino is None or destino == nombre_campania:
            return None

        tier_actual, _ = reglas.tier_y_ticket(nombre_campania)
        roas_reciente = historial_roas[-1] if historial_roas else None

        if destino == "pausar":
            return {
                "grupo_id": grupo_id,
                "accion": "pausar",
                "campania_origen": nombre_campania,
                "tier_origen": tier_actual,
                "motivo": "roas_bajo_sostenido",
                "roas_reciente": roas_reciente,
            }

        tier_destino, _ = reglas.tier_y_ticket(destino)
        return {
            "grupo_id": grupo_id,
            "accion": "mover_tier",
            "campania_origen": nombre_campania,
            "campania_destino": destino,
            "tier_origen": tier_actual,
            "tier_destino": tier_destino,
            "roas_reciente": roas_reciente,
        }

    def detectar_caida_urgente(self, grupo_id, nombre_campania: str, historial_roas: list) -> bool:
        """True si el producto venía con buen ROAS y lleva 3+ días cayendo."""
        roas_target = reglas.roas_target_campania(nombre_campania)
        return reglas.es_caida_urgente(historial_roas, roas_target)

    def _tiene_aprendizaje_bloqueante(self, grupo_id, no_sugerir: str) -> bool:
        hoy = date.today().isoformat()
        grupo_id = str(grupo_id)
        return any(
            str(a["item_id"]) == grupo_id and no_sugerir in a.get("no_sugerir", []) and a.get("expira", "9999-99-99") >= hoy
            for a in self.learnings
        )
