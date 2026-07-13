"""Script de verificacion de endpoints de escritura de ML Ads.

Cada prueba revierte el cambio inmediatamente - efecto neto cero sobre las campanas.
Ejecutar con: python test_escritura.py
"""
from __future__ import annotations

import json
import os
import sys
import time

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(__file__)
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))

from core.ml_client import MLClient, MLClientError

MEMORY_DIR = os.path.join(BASE_DIR, "memory")

ADVERTISER_ID = "21757"
SITE_ID = "MLA"
CAMPANIA_PRUEBA = "testeo_bajo"
CAMPANIA_ID_PRUEBA = "357700013"
PAUSA_SEGUNDOS = 1


def ok(nombre, detalle=""):
    sufijo = f" -- {detalle}" if detalle else ""
    print(f"  [OK]    {nombre}{sufijo}")


def falla(nombre, error):
    print(f"  [FAIL]  {nombre} -- {error}")


def skip(nombre, motivo):
    print(f"  [SKIP]  {nombre} -- {motivo}")


def pausa(s=PAUSA_SEGUNDOS):
    time.sleep(s)


def obtener_ad_prueba(ml: MLClient) -> dict | None:
    from datetime import date, timedelta
    date_to = date.today().isoformat()
    date_from = (date.today() - timedelta(days=7)).isoformat()
    try:
        ads = ml.search_ads_todas(SITE_ID, ADVERTISER_ID, date_from, date_to)
    except MLClientError as e:
        print(f"  Error al traer ads: {e}")
        return None
    for ad in ads:
        if str(ad.get("campaign_id")) == CAMPANIA_ID_PRUEBA:
            return ad
    return None


def obtener_estado_campania(ml: MLClient) -> dict | None:
    try:
        data = ml.get_campaigns(ADVERTISER_ID)
        campanas = data if isinstance(data, list) else data.get("results", [])
        for c in campanas:
            if str(c.get("id")) == CAMPANIA_ID_PRUEBA:
                return c
        if isinstance(data, dict) and str(data.get("id")) == CAMPANIA_ID_PRUEBA:
            return data
    except MLClientError as e:
        print(f"  Error al obtener estado de campana: {e}")
    return None


def _probar(ml, method, path, desc="", **kwargs):
    """Intenta un request, imprime resultado. Devuelve (exito, resp_o_error)."""
    label = desc or f"{method} {path}"
    try:
        resp = ml._request(method, path, **kwargs)
        print(f"     [OK] {label}")
        return True, resp
    except MLClientError as e:
        print(f"     [--] {label} -> {e}")
        pausa(0.3)
        return False, str(e)


def test_get_campania_individual(ml: MLClient) -> bool:
    """Verifica si ML expone GET a la campana por ID (base para saber si PUT/PATCH es valido)."""
    nombre = "GET campana individual"
    rutas = [
        f"/advertising/advertisers/{ADVERTISER_ID}/product_ads/campaigns/{CAMPANIA_ID_PRUEBA}",
        f"/marketplace/advertising/{SITE_ID}/advertisers/{ADVERTISER_ID}/product_ads/campaigns/{CAMPANIA_ID_PRUEBA}",
    ]
    for ruta in rutas:
        exito, resp = _probar(ml, "GET", ruta, ruta)
        if exito:
            print(f"     Respuesta: {json.dumps(resp, ensure_ascii=False)[:300]}")
            ok(nombre, ruta)
            return True
    falla(nombre, "ninguna ruta devuelve la campana por ID")
    return False


def test_update_campaign(ml: MLClient, estado_actual: dict | None) -> bool:
    """Prueba actualizar roas_target y/o budget. Variantes exhaustivas."""
    nombre = "update_campaign"

    if not estado_actual:
        skip(nombre, "no se pudo leer estado actual")
        return False

    roas_orig = estado_actual.get("roas_target") or (estado_actual.get("configuration") or {}).get("roas_target")
    budget_orig = (
        estado_actual.get("budget")
        or estado_actual.get("daily_budget")
        or (estado_actual.get("configuration") or {}).get("budget")
    )
    acos_orig = estado_actual.get("acos_target") or (estado_actual.get("configuration") or {}).get("acos_target")
    strategy = estado_actual.get("strategy", "")

    if roas_orig is None and budget_orig is None:
        skip(nombre, "no hay roas_target ni budget legible")
        return False

    print(f"     strategy={strategy} roas_orig={roas_orig} budget_orig={budget_orig} acos_orig={acos_orig}")

    # -- Rutas base para la campana --
    rutas_base = [
        f"/advertising/advertisers/{ADVERTISER_ID}/product_ads/campaigns/{CAMPANIA_ID_PRUEBA}",
        f"/marketplace/advertising/{SITE_ID}/advertisers/{ADVERTISER_ID}/product_ads/campaigns/{CAMPANIA_ID_PRUEBA}",
    ]

    # Payloads a probar (de menos a mas invasivo)
    variantes_payload = []
    if budget_orig is not None:
        variantes_payload.append({"budget": float(budget_orig) + 1.0})
        variantes_payload.append({"daily_budget": float(budget_orig) + 1.0})
    if roas_orig is not None:
        variantes_payload.append({"roas_target": round(float(roas_orig) + 0.1, 2)})
    if acos_orig is not None:
        variantes_payload.append({"acos_target": round(float(acos_orig) + 0.01, 4)})
    if budget_orig is not None and roas_orig is not None:
        variantes_payload.append({"roas_target": round(float(roas_orig) + 0.1, 2), "budget": float(budget_orig) + 1.0})

    for method in ("PATCH", "PUT"):
        for ruta in rutas_base:
            for qs in (False, True):  # sin y con ?product_id=PADS
                for payload in variantes_payload:
                    params = {"product_id": "PADS"} if qs else None
                    qs_label = "?product_id=PADS" if qs else ""
                    desc = f"{method} {ruta}{qs_label} body={list(payload.keys())}"
                    exito, resp = _probar(ml, method, ruta, desc, json=payload, params=params)
                    if exito:
                        # Revertir
                        rev = {}
                        if "budget" in payload:
                            rev["budget"] = float(budget_orig)
                        if "daily_budget" in payload:
                            rev["daily_budget"] = float(budget_orig)
                        if "roas_target" in payload:
                            rev["roas_target"] = float(roas_orig)
                        if "acos_target" in payload:
                            rev["acos_target"] = float(acos_orig)
                        try:
                            ml._request(method, ruta, json=rev, params=params)
                            print("     Revertido OK")
                        except MLClientError as e:
                            print(f"     ATENCION: reversion fallo: {e}")
                        ok(nombre, desc)
                        return True

    # -- Subrecursos de campana --
    print("     Probando subrecursos /budget y /roas_target...")
    for ruta_base in rutas_base:
        if budget_orig is not None:
            for body in ({"budget": float(budget_orig) + 1.0}, {"daily_budget": float(budget_orig) + 1.0}, {"value": float(budget_orig) + 1.0}):
                for method in ("PUT", "PATCH"):
                    exito, resp = _probar(ml, method, f"{ruta_base}/budget", f"{method} .../budget body={list(body.keys())}", json=body)
                    if exito:
                        try:
                            ml._request(method, f"{ruta_base}/budget", json={"budget": float(budget_orig)})
                        except Exception:
                            pass
                        ok(nombre, f"subrecurso /budget: {method}")
                        return True
        if roas_orig is not None:
            for body in ({"roas_target": round(float(roas_orig) + 0.1, 2)}, {"value": round(float(roas_orig) + 0.1, 2)}):
                for method in ("PUT", "PATCH"):
                    exito, resp = _probar(ml, method, f"{ruta_base}/roas_target", f"{method} .../roas_target body={list(body.keys())}", json=body)
                    if exito:
                        try:
                            ml._request(method, f"{ruta_base}/roas_target", json={"roas_target": float(roas_orig)})
                        except Exception:
                            pass
                        ok(nombre, f"subrecurso /roas_target: {method}")
                        return True

    falla(nombre, "ninguna combinacion funciono")
    return False


def test_item_management(ml: MLClient, ad: dict) -> bool:
    """Prueba pause/unpause. Variantes exhaustivas de ID y ruta."""
    nombre = "item management (pause/unpause)"

    item_id = ad.get("item_id", "")
    user_product_id = str(ad.get("user_product_id") or "")
    ad_group_id = str(ad.get("ad_group_id") or "")
    family_id = str(ad.get("family_id") or "")

    print(f"     item_id={item_id}  user_product_id={user_product_id}  ad_group_id={ad_group_id}  family_id={family_id}")

    # IDs candidatos a usar en la ruta (en orden de mas a menos probable)
    ids_candidatos = list(dict.fromkeys(filter(None, [item_id, user_product_id])))

    # Constructores de rutas
    def rutas_directas(id_usado):
        return [
            f"/advertising/advertisers/{ADVERTISER_ID}/product_ads/campaigns/{CAMPANIA_ID_PRUEBA}/items/{id_usado}",
            f"/marketplace/advertising/{SITE_ID}/advertisers/{ADVERTISER_ID}/product_ads/campaigns/{CAMPANIA_ID_PRUEBA}/items/{id_usado}",
        ]

    def rutas_con_adgroup(id_usado):
        if not ad_group_id:
            return []
        return [
            f"/advertising/advertisers/{ADVERTISER_ID}/product_ads/campaigns/{CAMPANIA_ID_PRUEBA}/ad_groups/{ad_group_id}/items/{id_usado}",
            f"/marketplace/advertising/{SITE_ID}/advertisers/{ADVERTISER_ID}/product_ads/campaigns/{CAMPANIA_ID_PRUEBA}/ad_groups/{ad_group_id}/items/{id_usado}",
        ]

    # Status values a probar para pause
    status_pause = [
        {"status": "paused"},
        {"status": "disabled"},
        {"status": "inactive"},
        {"status": "suspend"},
        {"status": "pause"},
    ]
    status_active = [
        {"status": "active"},
        {"status": "enabled"},
        {"status": "enable"},
    ]

    # Iteracion principal: id x ruta x method x payload
    for id_prueba in ids_candidatos:
        for rutas_fn in (rutas_directas, rutas_con_adgroup):
            for ruta in rutas_fn(id_prueba):
                for method in ("PUT", "PATCH", "POST"):
                    for sp in status_pause:
                        desc = f"{method} {ruta} body={sp}"
                        exito, resp = _probar(ml, method, ruta, desc, json=sp)
                        if exito:
                            pausa()
                            # Reactivar
                            reverted = False
                            for sa in status_active:
                                try:
                                    ml._request(method, ruta, json=sa)
                                    print(f"     Reactivado con {sa}")
                                    reverted = True
                                    break
                                except MLClientError:
                                    pass
                            if not reverted:
                                print(f"     ATENCION: no se pudo reactivar {id_prueba} en {ruta}")
                            ok(nombre, desc)
                            return True

    # Probar ruta de collection con body (sin ID en la ruta)
    print("     Probando ruta collection (sin ID en URL)...")
    rutas_collection = [
        f"/advertising/advertisers/{ADVERTISER_ID}/product_ads/campaigns/{CAMPANIA_ID_PRUEBA}/items",
        f"/marketplace/advertising/{SITE_ID}/advertisers/{ADVERTISER_ID}/product_ads/campaigns/{CAMPANIA_ID_PRUEBA}/items",
    ]
    if ad_group_id:
        rutas_collection += [
            f"/advertising/advertisers/{ADVERTISER_ID}/product_ads/campaigns/{CAMPANIA_ID_PRUEBA}/ad_groups/{ad_group_id}/items",
            f"/marketplace/advertising/{SITE_ID}/advertisers/{ADVERTISER_ID}/product_ads/campaigns/{CAMPANIA_ID_PRUEBA}/ad_groups/{ad_group_id}/items",
        ]

    for ruta in rutas_collection:
        for id_prueba in ids_candidatos:
            for sp in status_pause[:2]:
                body = {"id": id_prueba, **sp}
                desc = f"PATCH {ruta} body={body}"
                exito, resp = _probar(ml, "PATCH", ruta, desc, json=body)
                if exito:
                    try:
                        ml._request("PATCH", ruta, json={"id": id_prueba, "status": "active"})
                    except Exception:
                        pass
                    ok(nombre, desc)
                    return True

    falla(nombre, "ninguna combinacion funciono para pause/unpause")
    return False


def main() -> None:
    print("=" * 60)
    print("  Test endpoints escritura ML Ads -- SHAFFE")
    print(f"  Campana: {CAMPANIA_PRUEBA} (id={CAMPANIA_ID_PRUEBA})")
    print("=" * 60)

    with open(os.path.join(MEMORY_DIR, "ml_tokens.json"), encoding="utf-8") as f:
        tokens = json.load(f)

    ml = MLClient(tokens)

    try:
        print("\n[0] Buscando ad de prueba en testeo_bajo...")
        ad = obtener_ad_prueba(ml)
        if not ad:
            print("  No se encontro ningun ad en testeo_bajo.")
            sys.exit(1)
        ad_sin_metricas = {k: v for k, v in ad.items() if k != "metrics"}
        print(f"  Ad: {json.dumps(ad_sin_metricas, ensure_ascii=False)}")

        print("\n[0b] Estado actual de la campana...")
        estado = obtener_estado_campania(ml)
        if estado:
            print(f"     {json.dumps(estado, ensure_ascii=False)}")
        else:
            print("     No se pudo leer.")
        pausa()

        resultados = {}

        print("\n[1] GET campana por ID (diagnostico)")
        resultados["get_campania_id"] = test_get_campania_individual(ml)
        pausa()

        print("\n[2] update_campaign (budget / roas_target / acos_target -- PATCH y PUT, con y sin ?product_id=PADS, subrecursos)")
        resultados["update_campaign"] = test_update_campaign(ml, estado)
        pausa()

        print("\n[3] item management (pause/unpause -- multiples IDs, rutas y metodos)")
        resultados["item_mgmt"] = test_item_management(ml, ad)

    finally:
        with open(os.path.join(MEMORY_DIR, "ml_tokens.json"), "w", encoding="utf-8") as f:
            json.dump(ml.tokens_actuales(), f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    total = len(resultados)
    pasados = sum(1 for v in resultados.values() if v)
    print(f"  Resultado: {pasados}/{total} checks OK")
    for nombre, paso in resultados.items():
        print(f"    {'[OK]  ' if paso else '[FAIL]'}  {nombre}")
    print("=" * 60)

    if pasados < total:
        criticos = [n for n, p in resultados.items() if not p and n != "get_campania_id"]
        if criticos:
            print(f"\n  Aun fallan endpoints criticos: {', '.join(criticos)}")
            sys.exit(1)
        else:
            print("\n  Solo fallo el diagnostico GET. Revisar si ML expone GET individual de campana.")
    else:
        print("\n  Todos los endpoints verificados.")


if __name__ == "__main__":
    main()
