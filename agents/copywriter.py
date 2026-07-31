"""Agente redactor: sugiere cambios de foto/título/descripción para publicaciones
de testeo sin conversiones (el "último intento" antes de pausar)."""
from __future__ import annotations

import os

import core.campaign_rules as reglas

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

_MODELO_DEFAULT = "gpt-5.2"


class Copywriter:
    def __init__(self, model: str = _MODELO_DEFAULT):
        api_key = os.environ.get("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key) if (OpenAI and api_key) else None
        self.model = model

    def en_ventana_ultimo_intento(self, dias_sin_conversion: int) -> bool:
        minimo, maximo = reglas.DIAS_SIN_CONVERSION_ULTIMO_INTENTO
        return minimo <= dias_sin_conversion <= maximo

    def sugerir_ultimo_intento(self, titulo_actual: str, descripcion_actual: str) -> str:
        if self.client is None:
            return (
                f"Último intento para '{titulo_actual}': probar otra foto principal "
                "(producto puesto, mejor luz), revisar que el título incluya marca + "
                "tipo de prenda + color, y dejar talles disponibles claros en la descripción."
            )

        respuesta = self.client.chat.completions.create(
            model=self.model,
            messages=[{
                "role": "user",
                "content": (
                    "Sos un especialista en MercadoLibre Ads para la marca de ropa SHAFFE. "
                    "Esta publicación lleva 10-15 días en testeo sin conversiones.\n"
                    f"Título actual: {titulo_actual}\n"
                    f"Descripción actual: {descripcion_actual}\n\n"
                    "Sugerí en 3 bullets concretos qué cambiar en foto principal, título y "
                    "descripción para el 'último intento' antes de pausar la publicación."
                ),
            }],
        )
        return respuesta.choices[0].message.content
