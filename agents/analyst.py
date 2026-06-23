"""Agente analista: calcula ROAS/CTR/CVR, detecta alertas y decide movimientos de tier.

Todo se evalúa a nivel producto (grupo de variantes por family_id), nunca por
item_id individual. Los aprendizajes en memory/learnings.json también deben
quedar guardados con el family_id (como string) en el campo "item_id"."""
from __future__ import annotations

from datetime import date

import core.campaign_rules as reglas


class Analyst:
    def __init__(self, learnings: list):
        self.learnings = learnings

    def analizar_item(self, grupo_id, metricas: dict) -> dict:
        impresiones = metricas.get("prints", 0)
        clics = metricas.get("clicks", 0)
        conversiones = metricas.get("units_quantity", 0)
        roas = metricas.get("roas", 0.0)  # ML ya lo calcula, no hace falta recomputarlo

        alertas = reglas.alertas_metricas(impresiones, clics, conversiones)

        return {
            "grupo_id": grupo_id,
            "roas": roas,
            "impresiones": impresiones,
            "clics": clics,
            "conversiones": conversiones,
            "alertas": alertas,
        }

    def decidir_movimiento_tier(self, grupo_id, tier_actual: str, historial_roas: list) -> dict | None:
        if self._tiene_aprendizaje_bloqueante(grupo_id, "subir_tier") or self._tiene_aprendizaje_bloqueante(
            grupo_id, "bajar_tier"
        ):
            return None

        tier_destino = reglas.evaluar_movimiento_tier(tier_actual, historial_roas)
        if tier_destino is None or tier_destino == tier_actual:
            return None

        return {
            "grupo_id": grupo_id,
            "tier_origen": tier_actual,
            "tier_destino": tier_destino,
            "roas_reciente": historial_roas[-1] if historial_roas else None,
        }

    def _tiene_aprendizaje_bloqueante(self, grupo_id, no_sugerir: str) -> bool:
        hoy = date.today().isoformat()
        grupo_id = str(grupo_id)
        return any(
            str(a["item_id"]) == grupo_id and no_sugerir in a.get("no_sugerir", []) and a.get("expira", "9999-99-99") >= hoy
            for a in self.learnings
        )
