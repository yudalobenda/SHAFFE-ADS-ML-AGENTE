"""Agente estructurador: traduce decisiones de tier en movimientos concretos entre campañas."""
from __future__ import annotations

import core.campaign_rules as reglas


class Structurer:
    def construir_movimiento(self, item_id: str, ticket: str, tier_origen: str, tier_destino: str, roas_reciente) -> dict:
        return {
            "tipo": "mover_tier",
            "item_id": item_id,
            "campania_origen": reglas.nombre_campania(tier_origen, ticket),
            "campania_destino": reglas.nombre_campania(tier_destino, ticket),
            "tier_origen": tier_origen,
            "tier_destino": tier_destino,
            "roas_reciente": roas_reciente,
        }

    def construir_alta_testeo(self, item_id: str, ticket: str) -> dict:
        return {
            "tipo": "agregar_a_testeo",
            "item_id": item_id,
            "campania": reglas.nombre_campania("testeo", ticket),
            "roas_target_inicial": reglas.ROAS_TARGET["testeo"],
        }
