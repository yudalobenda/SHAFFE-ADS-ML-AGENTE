import json
import os
import sys
import time

BASE_DIR = r"E:\AGENTES CLAUDE\ANGENTE MERCADO ADS"
sys.path.insert(0, BASE_DIR)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(os.path.join(BASE_DIR, ".env"))

from core.ml_client import MLClient

MEMORY_DIR = os.path.join(BASE_DIR, "memory")
with open(os.path.join(MEMORY_DIR, "ml_tokens.json"), encoding="utf-8") as f:
    tokens = json.load(f)
ml = MLClient(tokens)

OLD_OPENING_CORTE_CHINO = (
    "Pantalón de vestir hombre en gabardina elastizada Shaffe — elegancia y comodidad "
    "para la oficina, reuniones y el día a día. Versátil y de excelente caída, combina "
    "con todo: desde una camisa formal hasta una remera y zapatillas."
)
NEW_OPENING_CORTE_CHINO = (
    "Pantalón de vestir hombre en gabardina elastizada Shaffe — el corte chino que no te "
    "vas a sacar. Tan cómodo que lo vas a usar todos los días, tan prolijo que entra sin "
    "problema a la oficina o una reunión. Con zapatillas para el día a día o con zapatos "
    "para algo más formal: combina con todo."
)

OLD_OPENING_CHUPIN = (
    "Pantalón chino de gabardina para hombre — el clásico infaltable con el plus "
    "elastizado que buscás en cada prenda. Corte chupin prolijo, perfecto para la "
    "oficina, una salida o el día a día con estilo."
)
NEW_OPENING_CHUPIN = (
    "Pantalón chino de gabardina para hombre, corte chupin — el infaltable que combina "
    "con todo tu guardarropa. Elastizado para que te acompañe cómodo todo el día, con la "
    "caída prolija que necesitás para la oficina, una salida o el uso diario."
)

with open(os.path.join(BASE_DIR, "resultado_promos_30_07.json"), encoding="utf-8") as f:
    promos_resultado = json.load(f)

chupin_item_ids = [
    r["item_id"] for r in promos_resultado["Pantalon Gabardina Hombre De Vestir Clasico Chupin Shaffe"]["ok"]
]

TAREAS = [("MLA1221195023", OLD_OPENING_CORTE_CHINO, NEW_OPENING_CORTE_CHINO, "Corte Chino")]
TAREAS += [(iid, OLD_OPENING_CHUPIN, NEW_OPENING_CHUPIN, "Chupin") for iid in chupin_item_ids]

resultados = {"ok": [], "sin_match": [], "error": []}

for item_id, old_opening, new_opening, etiqueta in TAREAS:
    try:
        desc = ml.get_item_description(item_id)
        texto = desc.get("plain_text", "")
    except Exception as e:
        resultados["error"].append({"item_id": item_id, "etapa": "get", "error": repr(e)})
        print(f"[{etiqueta}] {item_id}: ERROR get {e}")
        continue

    if old_opening not in texto:
        resultados["sin_match"].append(item_id)
        print(f"[{etiqueta}] {item_id}: apertura NO coincide con la esperada, SALTEADO (no se tocó)")
        continue

    nuevo_texto = texto.replace(old_opening, new_opening, 1)
    try:
        ml.update_item_description(item_id, nuevo_texto)
        resultados["ok"].append(item_id)
        print(f"[{etiqueta}] {item_id}: OK")
    except Exception as e:
        resultados["error"].append({"item_id": item_id, "etapa": "put", "error": repr(e)})
        print(f"[{etiqueta}] {item_id}: ERROR put {e}")
    time.sleep(0.3)

with open(os.path.join(BASE_DIR, "resultado_descripciones_30_07.json"), "w", encoding="utf-8") as f:
    json.dump(resultados, f, ensure_ascii=False, indent=2)

with open(os.path.join(MEMORY_DIR, "ml_tokens.json"), "w", encoding="utf-8") as f:
    json.dump(ml.tokens_actuales(), f, ensure_ascii=False, indent=2)

print(f"\nOK: {len(resultados['ok'])} | sin_match: {len(resultados['sin_match'])} | error: {len(resultados['error'])}")
