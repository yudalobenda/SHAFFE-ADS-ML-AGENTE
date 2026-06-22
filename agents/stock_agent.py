"""Agente de stock: detecta poco stock y decide promo ML o pausa directa."""
from __future__ import annotations

import core.campaign_rules as reglas


class StockAgent:
    def evaluar(self, item_id: str, campania: str, unidades_totales: int, variantes_disponibles: int, fin_de_temporada: bool) -> dict | None:
        if not reglas.es_poco_stock(unidades_totales, variantes_disponibles):
            return None

        if fin_de_temporada:
            return {"tipo": "pausar", "item_id": item_id, "campania": campania, "motivo": "poco_stock_fin_temporada"}

        return {"tipo": "agregar_a_promo", "item_id": item_id, "motivo": "poco_stock"}
