"""Agente estructurador: traduce decisiones de tier en movimientos concretos entre campañas.

Las acciones siempre llevan item_ids (todas las variantes del grupo/family_id),
nunca un item_id suelto: en SHAFFE no se puede mover/pausar una sola variante
de un producto sin tocar el resto."""
from __future__ import annotations

import core.campaign_rules as reglas


class Structurer:
    def construir_movimiento(self, item_ids: list, family_name: str, ticket: str, tier_origen: str, tier_destino: str, roas_reciente) -> dict:
        return {
            "tipo": "mover_tier",
            "item_ids": item_ids,
            "family_name": family_name,
            "campania_origen": reglas.nombre_campania(tier_origen, ticket),
            "campania_destino": reglas.nombre_campania(tier_destino, ticket),
            "tier_origen": tier_origen,
            "tier_destino": tier_destino,
            "roas_reciente": roas_reciente,
        }

    def construir_alta_testeo(self, item_ids: list, family_name: str, ticket: str) -> dict:
        return {
            "tipo": "agregar_a_testeo",
            "item_ids": item_ids,
            "family_name": family_name,
            "campania": reglas.nombre_campania("testeo", ticket),
            "roas_target_inicial": reglas.ROAS_TARGET.get(f"testeo_{ticket}", 3.0),
        }
