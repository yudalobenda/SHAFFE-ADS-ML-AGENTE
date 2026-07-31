"""Agente analista vía OpenAI.

Aplica el criterio consolidado en `ANALISIS_INSTRUCCIONES.md` (agrupación por
family_id, chequeo de status hold/pausado, ventanas semanales para detectar
saturación, etc. — todo lo pulido a mano en sesiones anteriores) sobre los
datos que YA recolectó `Collector`/`main.py` en la misma corrida. No vuelve a
llamar a la API de ML: consume `grupos` y `campanias` ya en memoria, para no
arriesgar una segunda rotación del refresh_token en la misma corrida.

Es opcional: si no hay OPENAI_API_KEY configurada, `disponible()` devuelve
False y el resto del pipeline sigue funcionando igual sin este paso (mismo
patrón que `agents/copywriter.py`, que también usa OPENAI_API_KEY).
"""
from __future__ import annotations

import json
import os

import core.campaign_rules as reglas

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

_INSTRUCCIONES_PATH = os.path.join(os.path.dirname(__file__), "ANALISIS_INSTRUCCIONES.md")
_MODELO_DEFAULT = "gpt-4.1"


class AIAnalyst:
    def __init__(self, model: str = _MODELO_DEFAULT):
        api_key = os.environ.get("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key) if (OpenAI and api_key) else None
        self.model = model
        with open(_INSTRUCCIONES_PATH, encoding="utf-8") as f:
            self._instrucciones = f.read()

    def disponible(self) -> bool:
        return self.client is not None

    def generar_analisis(
        self, campanias: list[dict], grupos: dict, ventas_reales_por_item: dict | None = None
    ) -> str | None:
        """campanias: salida de ml.get_campaigns (lista de dicts con id/name/
        budget/roas_target/acos_target/status). grupos: salida de
        Collector.recolectar() (family_id -> family_name/item_ids/
        tiers_detectados/metricas). ventas_reales_por_item: salida de
        ml.ventas_reales_por_item() (item_id -> unidades vendidas reales en
        los últimos 14 días, todas las órdenes, no solo las de Ads) — permite
        aplicar la regla 7 de las instrucciones (cruzar con ventas reales
        antes de recomendar sacar un producto). Si se omite, el modelo va a
        avisar cuando le falte ese dato en vez de asumir. Devuelve el análisis
        en markdown, o None si no hay API key configurada."""
        if not self.disponible():
            return None

        ventas_reales_por_item = ventas_reales_por_item or {}

        datos = {
            "campanias": [
                {
                    "id": c.get("id"),
                    "nombre": c.get("name"),
                    "budget": c.get("budget"),
                    # OJO: roas_objetivo_negocio es el umbral real de evaluación
                    # (tabla de tiers en CLAUDE.md/campaign_rules.py). roas_target_lever_ml
                    # es solo la palanca algorítmica cargada en ML (arranca baja a
                    # propósito) — nunca usar este segundo valor como objetivo de evaluación.
                    "roas_objetivo_negocio": reglas.roas_target_campania(
                        (c.get("name") or "").strip().lower().replace(" ", "_")
                    ),
                    "roas_target_lever_ml": c.get("roas_target"),
                    "acos_target_lever_ml": c.get("acos_target"),
                    "status": c.get("status"),
                }
                for c in campanias
            ],
            "productos": [
                {
                    "family_id": str(family_id),
                    "nombre": grupo.get("family_name"),
                    "campanias_detectadas": grupo.get("tiers_detectados"),
                    "n_items": len(grupo.get("item_ids", [])),
                    "metricas": grupo.get("metricas"),
                    "ventas_reales_14d": sum(
                        ventas_reales_por_item.get(item_id, 0)
                        for item_id in grupo.get("item_ids", [])
                    ),
                }
                for family_id, grupo in grupos.items()
            ],
        }

        respuesta = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self._instrucciones},
                {
                    "role": "user",
                    "content": (
                        "Analizá estos datos de la cuenta de SHAFFE en Mercado Libre Ads "
                        "siguiendo el criterio del system prompt. Datos de la corrida de hoy (JSON):\n\n"
                        f"{json.dumps(datos, ensure_ascii=False)}\n\n"
                        "Devolvé el análisis en el 'Formato de salida esperado' de las instrucciones, "
                        "en español rioplatense, como texto markdown legible (no JSON) — "
                        "va directo a un mensaje de Telegram."
                    ),
                },
            ],
        )
        return respuesta.choices[0].message.content
