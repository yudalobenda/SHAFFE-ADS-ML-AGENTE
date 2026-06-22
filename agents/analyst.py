"""Agente analista: calcula ROAS/CTR/CVR, detecta alertas y decide movimientos de tier."""
from __future__ import annotations

from datetime import date

import core.campaign_rules as reglas


class Analyst:
    def __init__(self, learnings: list):
        self.learnings = learnings

    def analizar_item(self, item_id: str, metricas: dict) -> dict:
        impresiones = metricas.get("prints", 0)
        clics = metricas.get("clicks", 0)
        costo = metricas.get("cost", 0.0)
        ingresos = metricas.get("direct_amount", 0.0) + metricas.get("indirect_amount", 0.0)
        conversiones = metricas.get("conversions", 0)

        roas = (ingresos / costo) if costo > 0 else 0.0
        alertas = reglas.alertas_metricas(impresiones, clics, conversiones)

        return {
            "item_id": item_id,
            "roas": roas,
            "impresiones": impresiones,
            "clics": clics,
            "conversiones": conversiones,
            "alertas": alertas,
        }

    def decidir_movimiento_tier(self, item_id: str, tier_actual: str, historial_roas: list) -> dict | None:
        if self._tiene_aprendizaje_bloqueante(item_id, "subir_tier") or self._tiene_aprendizaje_bloqueante(
            item_id, "bajar_tier"
        ):
            return None

        tier_destino = reglas.evaluar_movimiento_tier(tier_actual, historial_roas)
        if tier_destino is None or tier_destino == tier_actual:
            return None

        return {
            "item_id": item_id,
            "tier_origen": tier_actual,
            "tier_destino": tier_destino,
            "roas_reciente": historial_roas[-1] if historial_roas else None,
        }

    def _tiene_aprendizaje_bloqueante(self, item_id: str, no_sugerir: str) -> bool:
        hoy = date.today().isoformat()
        return any(
            a["item_id"] == item_id and no_sugerir in a.get("no_sugerir", []) and a.get("expira", "9999-99-99") >= hoy
            for a in self.learnings
        )
