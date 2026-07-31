"""Comparación puntual de modelos de OpenAI para agents/copywriter.py.

Corre el mismo prompt de `Copywriter.sugerir_ultimo_intento` con varios modelos
sobre una publicación real (el Jogger Básico de testeo_medio, MLA1719339758,
marcado en HANDOFF.md como candidato a 'último intento') para elegir cuál
dejar como default en `_MODELO_DEFAULT`. Script de uso puntual, no se integra
al pipeline de main.py.
"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from agents.copywriter import Copywriter  # noqa: E402
from main import _crear_ml_client  # noqa: E402

ITEM_ID = "MLA1719339758"  # Jogger Hombre Babucha, testeo_medio — ver HANDOFF.md §1.3

MODELOS = [
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-5-mini",
    "gpt-5.2",
    "gpt-5.5",
]


def main():
    ml = _crear_ml_client()
    item = ml.get_item(ITEM_ID)
    desc = ml.get_item_description(ITEM_ID)
    titulo = item.get("title", "")
    descripcion = desc.get("plain_text", "")

    print("=" * 70)
    print(f"PUBLICACIÓN DE REFERENCIA: {ITEM_ID}")
    print(f"Título: {titulo}")
    print(f"Descripción: {descripcion}")
    print("=" * 70)

    for modelo in MODELOS:
        cw = Copywriter(model=modelo)
        if cw.client is None:
            print(f"\n[{modelo}] SALTEADO — falta OPENAI_API_KEY")
            continue
        inicio = time.time()
        try:
            resultado = cw.sugerir_ultimo_intento(titulo, descripcion)
            duracion = time.time() - inicio
            print(f"\n--- {modelo} ({duracion:.1f}s) ---")
            print(resultado)
        except Exception as e:
            print(f"\n--- {modelo} — ERROR ---")
            print(repr(e))


if __name__ == "__main__":
    main()
