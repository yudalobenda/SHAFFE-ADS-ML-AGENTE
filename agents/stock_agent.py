"""Agente de stock: detecta poco stock y decide promo ML o pausa directa.

Opera sobre el producto completo (todas las variantes/item_ids del grupo),
no sobre una variante individual."""
from __future__ import annotations

import core.campaign_rules as reglas


class StockAgent:
    def evaluar(self, item_ids: list, family_name: str, campania: str, unidades_totales: int, variantes_disponibles: int, fin_de_temporada: bool) -> dict | None:
        if not reglas.es_poco_stock(unidades_totales, variantes_disponibles):
            return None

        if fin_de_temporada:
            return {
                "tipo": "pausar", "item_ids": item_ids, "family_name": family_name,
                "campania": campania, "motivo": "poco_stock_fin_temporada",
            }

        return {"tipo": "agregar_a_promo", "item_ids": item_ids, "family_name": family_name, "motivo": "poco_stock"}
