"""Cliente HTTP contra el ERP de Shaffe — fuente de verdad de costos (ver CIOMA).

Mismo patrón que E:\\AGENTES CLAUDE\\SHAFFE CONTADOR AGENT\\core\\erp_client.py:
login JWT, relogueo automático cuando vence o el ERP devuelve 401. Este
agente NUNCA calcula costo propio (Excel, supuesto hardcodeado, etc.) —
siempre lo pide acá. Ver AUDITORIA-FASE-0.md / MEDICION-DIVERGENCIA-MARGEN.md.
"""
from __future__ import annotations

import time
import random

import requests


class ERPClientError(Exception):
    pass


class ERPClient:
    def __init__(self, base_url: str, email: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self._token = None
        self._token_expires_at = 0.0

    def _login(self):
        if not self.password:
            raise ERPClientError("ERP_PASSWORD no configurado (ver .env)")
        r = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"email": self.email, "password": self.password},
            timeout=15,
        )
        r.raise_for_status()
        self._token = r.json()["token"]
        # el token dura 12h; renovamos 10 min antes para no pisar el filo
        self._token_expires_at = time.time() + (12 * 3600) - 600
        return self._token

    def _ensure_token(self):
        if not self._token or time.time() >= self._token_expires_at:
            self._login()
        return self._token

    def _request(self, method: str, path: str, **kwargs):
        token = self._ensure_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        url = f"{self.base_url}{path}"
        r = requests.request(method, url, headers=headers, timeout=20, **kwargs)
        if r.status_code == 401:
            token = self._login()
            headers["Authorization"] = f"Bearer {token}"
            r = requests.request(method, url, headers=headers, timeout=20, **kwargs)
        r.raise_for_status()
        return r.json() if r.content else None

    def cost_by_item(self, item_ids: list) -> dict:
        """item_id (MLA) -> costo real, vía channel_product_links del ERP.
        Items sin vínculo en el ERP simplemente no aparecen en el resultado
        (el caller debe tratar eso como 'sin dato', no como costo cero).
        OJO: channel_product_links tiene huecos reales (variantes/talles que
        nunca se vincularon a su producto padre) aunque el costo del producto
        SÍ esté cargado — para no perder margen por eso, preferir
        cost_by_code() cuando el caller ya tiene el código de SKU (el costo
        se carga por SKU padre, es el mismo para todas sus variantes)."""
        item_ids = list(dict.fromkeys(item_ids))  # dedupe preservando orden
        if not item_ids:
            return {}
        resultado: dict = {}
        for i in range(0, len(item_ids), 100):
            lote = item_ids[i:i + 100]
            data = self._request(
                "GET", "/api/economics/cost-by-item",
                params={"itemIds": ",".join(lote), "channel": "mercadolibre"},
            )
            for row in (data or []):
                resultado[row["external_item_id"]] = float(row["cost"])
        return resultado

    def cost_by_code(self, codes: list) -> dict:
        """código interno de producto (SKU padre, ej. '1N981') -> costo real,
        directo de products.cost — sin pasar por channel_product_links, así
        que no depende de que cada variante/talle esté vinculada a ML. Es la
        fuente preferida para margen por SKU (ver cost_by_item)."""
        codes = list(dict.fromkeys(codes))
        if not codes:
            return {}
        resultado: dict = {}
        for i in range(0, len(codes), 100):
            lote = codes[i:i + 100]
            data = self._request("GET", "/api/economics/cost", params={"codes": ",".join(lote)})
            for row in (data or []):
                resultado[row["code"]] = float(row["cost"])
        return resultado

    def rentabilidad_sku(self, month: str) -> list:
        """Margen NETO real por producto ya calculado por el ERP (backend/routes/reports.js
        /rentabilidad-sku): IVA (venta neta de IVA, IVA_FRAC=1-1/1.21), IIBB real segun
        tax_regime/iibb_rate de la empresa, comision real, costo real, Ads y envio real por
        SKU cuando hay dato (si no, prorrateo explicito marcado con adsReal/envioReal=false).
        Fuente unica de verdad para margen - preferir esto sobre reconstruir la formula
        a mano (ver core/margin.py, que quedo mas incompleto que esto: nunca incluyo IVA
        ni IIBB real de la empresa, solo la retencion parcial que trae la liquidacion de MP).
        month: 'YYYY-MM'."""
        data = self._request("GET", "/api/reports/rentabilidad-sku", params={"month": month})
        return (data or {}).get("items", data if isinstance(data, list) else [])

    def settlement_movements(self, date_from: str, date_to: str) -> list:
        """Liquidaciones REALES de Mercado Pago ya importadas por el ERP cada 12hs
        (reporte oficial de liquidacion de MP, no reconstruido desde la API de ML) -
        fuente correcta para margen real: fee_amount/ml_fee, shipping_cost, iibb_tax
        y net_amount ya vienen conciliados con la plata que efectivamente se movio.
        Cada fila es un movimiento (Pago aprobado, Pago de envio, Reclamo, Devolucion,
        Cashback...), no una venta - una misma orden puede tener varias filas. El campo
        `sku` viene poblado solo cuando el movimiento es atribuible a una venta puntual;
        cashbacks/bonificaciones de flex agregadas de toda la cuenta vienen con sku=None
        y no se pueden repartir por producto (ver core/margin.py)."""
        return self._request(
            "GET", "/api/contador/mp/settlement-movements",
            params={"dateFrom": date_from, "dateTo": date_to},
        ) or []

    # --- Data foundation persistence (shadow mode; no ML/Ads writes) ---

    def create_ingestion_run(self, payload: dict) -> dict:
        return self._foundation_request("POST", "/api/ads-data-foundation/ingestion-runs", json=payload)

    def _foundation_request(self, method: str, path: str, **kwargs):
        """Retry policy restricted to internal Data Foundation persistence."""
        last_error = None
        for attempt in range(5):
            try:
                return self._request(method, path, **kwargs)
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as error:
                last_error = error
                response = getattr(error, "response", None)
                status = getattr(response, "status_code", None)
                retryable = status in (429, 500, 502, 503, 504) or status is None
                if not retryable or attempt == 4:
                    raise
                retry_after = response.headers.get("Retry-After") if response is not None else None
                delay = float(retry_after) if retry_after and retry_after.isdigit() else min(16, 2 ** attempt)
                time.sleep(delay + random.uniform(0, 0.25))
        raise last_error

    def foundation_source_links(self, item_ids: list) -> list:
        result = []
        for i in range(0, len(item_ids), 100):
            data = self._foundation_request(
                "GET", "/api/ads-data-foundation/source-links",
                params={"itemIds": ",".join(item_ids[i:i + 100])},
            )
            result.extend(data or [])
        return result

    def finish_ingestion_run(self, run_id: str, payload: dict) -> dict:
        return self._foundation_request("PATCH", f"/api/ads-data-foundation/ingestion-runs/{run_id}", json=payload)

    def heartbeat_ingestion_run(self, run_id: str, checkpoint: dict, metadata: dict | None = None) -> dict:
        return self._foundation_request(
            "PATCH", f"/api/ads-data-foundation/ingestion-runs/{run_id}/heartbeat",
            json={"checkpoint": checkpoint, "metadata": metadata or {}},
        )

    def persist_listing_sku_mappings(self, run_id: str, rows: list) -> dict:
        return self._foundation_request("POST", "/api/ads-data-foundation/mappings", json={"ingestionRunId": run_id, "rows": rows})

    def persist_listing_snapshots(self, run_id: str, rows: list) -> dict:
        return self._foundation_request("POST", "/api/ads-data-foundation/listing-snapshots", json={"ingestionRunId": run_id, "rows": rows})

    def persist_ads_daily_metrics(self, run_id: str, rows: list) -> dict:
        return self._foundation_request("POST", "/api/ads-data-foundation/ads-daily-metrics", json={"ingestionRunId": run_id, "rows": rows})

    def persist_actionable_units(self, run_id: str, rows: list) -> dict:
        rows = [{**row, "ingestionRunId": run_id} for row in rows]
        return self._foundation_request("POST", "/api/ads-data-foundation/actionable-units", json={"rows": rows})

    def foundation_status(self) -> dict:
        return self._foundation_request("GET", "/api/ads-data-foundation/status")

    def foundation_manual_review(self) -> list:
        return self._foundation_request("GET", "/api/ads-data-foundation/mappings/manual-review") or []

    def create_formula_version(self, payload: dict) -> dict:
        return self._request("POST", "/api/ads-data-foundation/formula-versions", json=payload)

    def create_calculation_run(self, payload: dict) -> dict:
        return self._request("POST", "/api/ads-data-foundation/calculation-runs", json=payload)

    def finish_calculation_run(self, run_id: str, payload: dict) -> dict:
        return self._request("PATCH", f"/api/ads-data-foundation/calculation-runs/{run_id}", json=payload)

    def persist_sku_daily_economics(self, run_id: str, rows: list) -> dict:
        return self._request("POST", "/api/ads-data-foundation/sku-daily-economics", json={"calculationRunId": run_id, "rows": rows})

    def pending_ads_activations(self) -> list:
        """Publicaciones nuevas que el ERP ya publicó en ML y están esperando
        que este agente intente activarlas en Ads. Cada una: {id, external_item_id,
        title, category_id, price}. Ver backend/routes/productLaunch.js del ERP."""
        return self._request("GET", "/api/product-launch/pending-ads") or []

    def reportar_ads_status(self, grupos: dict) -> dict | None:
        """Le dice al ERP en qué campaña está cada item, para la columna 'En Ads'
        de la pestaña Publicaciones de CIOMA — el ERP nunca lo adivina. grupos es
        el dict que devuelve Collector.recolectar() (family_id -> item_ids/tiers_detectados).
        No frena la corrida si el ERP no responde."""
        items = []
        for grupo in grupos.values():
            campania = " + ".join(grupo.get("tiers_detectados", [])) or None
            for item_id in grupo.get("item_ids", []):
                items.append({"externalItemId": item_id, "campaign": campania})
        if not items:
            return None
        try:
            return self._request("POST", "/api/product-launch/ads-status", json={"items": items})
        except Exception as exc:
            print(f"  [ads-status] no se pudo reportar al ERP: {exc}")
            return None

    def marcar_ads_resuelto(self, request_id: str, status: str, error_message: str | None = None) -> dict:
        """status: 'ads_activado' o 'ads_error'."""
        return self._request(
            "POST", f"/api/product-launch/pending-ads/{request_id}/resolved",
            json={"status": status, "errorMessage": error_message},
        )

    _SCOPE_CAMPANA = {"ajustar_presupuesto", "ajustar_roas_target"}

    def push_ads_queue(self, accion: dict, resultado: dict | None = None) -> dict | None:
        """Empuja una decisión ya aprobada (por León, vía Telegram) a la cola
        de CIOMA (pestaña Ads) para que Codex la ejecute por sesión de
        navegador — la escritura directa por API de Ads da 401 real hoy
        (ver core/executor.py). No frena la corrida si el ERP no responde:
        la decisión ya se guardó en Telegram/changes_history de todos modos."""
        tipo = accion.get("tipo")
        scope = "campaña" if tipo in self._SCOPE_CAMPANA else "publicacion"
        api_attempt = "no_intentado"
        api_error = None
        if resultado is not None:
            api_attempt = "ok" if resultado.get("estado") == "ejecutada" else "error"
            api_error = resultado.get("error")
        try:
            return self._request("POST", "/api/ads-queue", json={
                "actionType": tipo,
                "scope": scope,
                "title": _titulo_accion_ads_queue(accion),
                "itemIds": accion.get("item_ids", []),
                "campaignName": accion.get("campania") or accion.get("campania_destino"),
                "detail": accion,
                "reason": accion.get("motivo"),
                "apiAttempt": api_attempt,
                "apiError": api_error,
            })
        except Exception as exc:
            print(f"  [ads_queue] no se pudo empujar la acción al ERP: {exc}")
            return None


def _titulo_accion_ads_queue(accion: dict) -> str:
    """Resumen legible para la cola de Ads del ERP — misma lógica de
    TelegramAgent._linea_accionable pero en texto plano (sin markdown)."""
    tipo = accion.get("tipo")
    nombre = accion.get("family_name") or ((accion.get("item_ids") or [""])[0])
    n_variantes = len(accion.get("item_ids", []))
    sufijo = f" ({n_variantes} var.)" if n_variantes > 1 else ""
    if tipo == "mover_tier":
        origen = accion.get("campania_origen") or accion.get("tier_origen", "")
        destino = accion.get("campania_destino") or accion.get("tier_destino", "")
        roas = accion.get("roas_reciente") or 0
        return f"{nombre}{sufijo}: {origen} → {destino} (ROAS {roas:.2f})"
    if tipo == "agregar_a_testeo":
        return f"{nombre}{sufijo}: activar en testeo ({accion.get('campania', 'testeo')})"
    if tipo == "agregar_a_promo":
        return f"{nombre}{sufijo}: agregar a promo ML (poco stock)"
    if tipo == "pausar":
        motivo = (accion.get("motivo") or "").replace("_", " ")
        roas = accion.get("roas_reciente") or 0
        return f"{nombre}{sufijo}: pausar / sacar de ads (ROAS {roas:.2f}, {motivo})"
    if tipo == "ajustar_presupuesto":
        return f"Campaña {accion.get('campania', '')}: presupuesto → ${accion.get('presupuesto_nuevo')}"
    if tipo == "ajustar_roas_target":
        return f"Campaña {accion.get('campania', '')}: ROAS objetivo → {accion.get('roas_target_nuevo')}"
    return f"{nombre}: {tipo}"
