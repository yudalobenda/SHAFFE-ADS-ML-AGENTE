import json
import os
import sys
import time
from datetime import date, timedelta

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

with open(os.path.join(BASE_DIR, "ctr_cvr_bajo_30_07.json"), encoding="utf-8") as f:
    data = json.load(f)

FAMILIAS = {
    "Remera Termica Ni\u00f1o Manga Larga Super Abrigada Escolar": None,
    "Pantalon Gabardina Hombre De Vestir Clasico Chupin Shaffe": None,
}

hoy = date.today()
fin = hoy + timedelta(days=14)
start_date = f"{hoy.isoformat()}T00:00:00"
finish_date = f"{fin.isoformat()}T23:59:59"

resultados = {}

for nombre in FAMILIAS:
    fila = next(x for x in data if x["nombre"] == nombre)
    item_ids = list(dict.fromkeys(fila["item_ids"]))
    items = ml.get_items_multiget(item_ids, attributes="id,status")
    activos = [i["id"] for i in items if i["status"] == "active"]
    print(f"=== {nombre}: {len(activos)}/{len(item_ids)} activos ===")

    resultados[nombre] = {"ok": [], "sin_price_discount": [], "error": []}

    for item_id in activos:
        try:
            promos = ml._request("GET", f"/seller-promotions/items/{item_id}", params={"app_version": "v2"})
        except Exception as e:
            resultados[nombre]["error"].append({"item_id": item_id, "etapa": "get_promos", "error": repr(e)})
            print(f"  {item_id}: ERROR get_promos {e}")
            continue

        candidata = next((p for p in promos if p.get("type") == "PRICE_DISCOUNT" and p.get("status") == "candidate"), None)
        if not candidata:
            resultados[nombre]["sin_price_discount"].append(item_id)
            print(f"  {item_id}: sin candidata PRICE_DISCOUNT")
            continue

        deal_price = candidata["suggested_discounted_price"]
        body = {
            "promotion_type": "PRICE_DISCOUNT",
            "deal_price": deal_price,
            "start_date": start_date,
            "finish_date": finish_date,
        }
        try:
            resp = ml._request("POST", f"/seller-promotions/items/{item_id}", params={"app_version": "v2"}, json=body)
            resultados[nombre]["ok"].append({"item_id": item_id, "deal_price": deal_price, "original_price": candidata["original_price"]})
            print(f"  {item_id}: OK deal_price={deal_price} (original {candidata['original_price']})")
        except Exception as e:
            resultados[nombre]["error"].append({"item_id": item_id, "etapa": "post", "error": repr(e), "body": body})
            print(f"  {item_id}: ERROR post {e}")
        time.sleep(0.3)

with open(os.path.join(BASE_DIR, "resultado_promos_30_07.json"), "w", encoding="utf-8") as f:
    json.dump(resultados, f, ensure_ascii=False, indent=2)

with open(os.path.join(MEMORY_DIR, "ml_tokens.json"), "w", encoding="utf-8") as f:
    json.dump(ml.tokens_actuales(), f, ensure_ascii=False, indent=2)

print("\nOK -> resultado_promos_30_07.json")
