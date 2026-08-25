"""Cliente de la API de MercadoLibre Ads: auth con refresh token + operaciones.

Verificado en vivo contra la cuenta real de SHAFFE (advertiser_id=21757, site MLA):
- get_advertisers, get_campaigns, get_campaign, get_ad: confirmados, funcionan.
- search_ads / search_ads_todas: confirmado. OJO: los filtros de query
  (campaign_id, status, item_id, text) NO funcionan en este endpoint — siempre
  devuelve los ads de toda la cuenta paginados. Hay que pedir todo y filtrar
  por campaign_id en nuestro propio código (así lo hace collector.py).
  metrics válidas confirmadas: clicks, prints, cost, direct_amount,
  indirect_amount, total_amount, direct_items_quantity,
  indirect_items_quantity, units_quantity (trae direct/indirect/total),
  acos, roas. NO válidas: cvr, ctr, conversions, impressions, sold_quantity.
  date_from/date_to: máximo 90 días de diferencia.

IMPORTANTE (21/07/2026) — ML deprecó las rutas legacy de campañas (sin /search)
en algún momento entre feb y mayo 2026; devuelven 404 "resource not found" para
CUALQUIER método (GET incluido), lo que hizo parecer por mucho tiempo que todo
el recurso estaba caído o sin permisos. Las rutas correctas actuales:
  - Lista:      GET  /marketplace/advertising/{site_id}/advertisers/{advertiser_id}/product_ads/campaigns/search
  - Individual:  GET  /marketplace/advertising/{site_id}/product_ads/campaigns/{campaign_id}   (SIN /advertisers/{id} en el medio)
  - Ad/item:     GET  /marketplace/advertising/{site_id}/product_ads/ads/{item_id}             (SIN /advertisers/{id} ni campaign_id)
Con estas rutas, la LECTURA de campañas y ads individuales funciona perfecto.

ESCRITURA — ya no es un problema de ruta, es un problema de permiso real:
- PUT a /marketplace/advertising/{site_id}/product_ads/campaigns/{campaign_id}
  (budget o roas_target) devuelve 401 explícito: {"error":"mclics.campaigns.exceptions.UnauthorizedException",
  "message":"User does not have permission to write."} — la app (client_id de
  este proyecto) no tiene el permiso de escritura habilitado para Product Ads.
  Hay que gestionarlo en el panel de Developers de ML (revisar si el producto
  "Advertising"/Product Ads necesita aprobación o certificación aparte del
  scope de OAuth genérico "write" que ya se pide en la auth URL).
- PUT a /marketplace/advertising/{site_id}/product_ads/ads/{item_id} (pausar/
  activar) devuelve 503 de forma consistente (probado 5 veces en distintos
  momentos, no parece un timeout puntual) — ruta correcta pero el backend de
  ML está fallando o el permiso da un error distinto (503 en vez de 401) para
  este endpoint puntual. Revisar de nuevo más adelante por si es transitorio.

add_item_to_campaign, remove_item_from_campaign: TODAVÍA sin verificar (no se
probaron rutas alternativas post-deprecación). Antes de usarlos, aplicar la
misma lógica: probar primero GET/HEAD de algo relacionado para encontrar la
ruta viva, después recién probar escritura.
"""
from __future__ import annotations

import os
import time

import requests

ML_API_BASE = "https://api.mercadolibre.com"
ML_OAUTH_TOKEN_URL = f"{ML_API_BASE}/oauth/token"


class MLClientError(Exception):
    pass


class MLClient:
    def __init__(self, tokens: dict | None = None):
        """tokens: {"access_token", "refresh_token", "expires_at"} persistido en
        memory/ml_tokens.json. Se actualiza solo en memoria; quien llama es
        responsable de releer tokens_actuales() y guardarlo después de usar el cliente,
        porque el refresh_token de ML puede rotar en cada refresh."""
        self.client_id = os.environ["ML_CLIENT_ID"]
        self.client_secret = os.environ["ML_CLIENT_SECRET"]
        self.seller_id = os.environ["ML_SELLER_ID"]
        self.redirect_uri = os.environ["ML_REDIRECT_URI"]
        tokens = tokens or {}
        self.access_token = tokens.get("access_token", "")
        self.refresh_token = tokens.get("refresh_token", "")
        self._token_expires_at = tokens.get("expires_at", 0.0)

    def tokens_actuales(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self._token_expires_at,
        }

    def _refresh_access_token(self) -> None:
        resp = requests.post(
            ML_OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise MLClientError(f"No se pudo refrescar el token ML: {resp.status_code} {resp.text}")
        data = resp.json()
        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        self._token_expires_at = time.time() + data.get("expires_in", 21600) - 60

    def _ensure_token(self) -> None:
        if not self.access_token or time.time() >= self._token_expires_at:
            self._refresh_access_token()

    def _headers(self) -> dict:
        self._ensure_token()
        return {"Authorization": f"Bearer {self.access_token}"}

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{ML_API_BASE}{path}"
        resp = requests.request(method, url, headers=self._headers(), timeout=30, **kwargs)
        if resp.status_code >= 400:
            raise MLClientError(f"{method} {path} -> {resp.status_code} {resp.text}")
        return resp.json() if resp.content else {}

    # --- Ads API (PADS) ---

    def get_advertisers(self) -> dict:
        return self._request("GET", "/advertising/advertisers", params={"product_id": "PADS"})

    def get_campaigns(self, site_id: str, advertiser_id: str) -> dict:
        """Lista todas las campañas del advertiser con budget/roas_target/status
        reales. Requiere /search al final (la ruta legacy sin /search fue
        deprecada por ML, devuelve 404). Confirmado en vivo 21/07/2026."""
        return self._request(
            "GET",
            f"/marketplace/advertising/{site_id}/advertisers/{advertiser_id}/product_ads/campaigns/search",
        )

    def get_campaign(self, site_id: str, campaign_id: str) -> dict:
        """Campaña individual. OJO: esta ruta NO lleva /advertisers/{id} en el
        medio (a diferencia de get_campaigns) - confirmado en vivo 21/07/2026."""
        return self._request("GET", f"/marketplace/advertising/{site_id}/product_ads/campaigns/{campaign_id}")

    def get_ad(self, site_id: str, item_id: str) -> dict:
        """Detalle de un ad individual (status, campaign_id, price, etc.), sin
        pasar por advertisers ni campaign_id en la ruta. Confirmado en vivo
        21/07/2026 - trae el status real (active/hold/paused) de una sola
        variante, útil para no tener que traer todo ads/search."""
        return self._request("GET", f"/marketplace/advertising/{site_id}/product_ads/ads/{item_id}")

    ADS_METRICS = "clicks,prints,cost,direct_amount,indirect_amount,units_quantity,acos,roas"

    def search_ads(
        self, site_id: str, advertiser_id: str, date_from: str, date_to: str, limit: int = 200, offset: int = 0
    ) -> dict:
        """Una página de ads con métricas. NO filtra por campaign_id: trae todos
        los ads de la cuenta (ver nota de la clase). date_from/date_to: máximo
        90 días de diferencia."""
        return self._request(
            "GET",
            f"/marketplace/advertising/{site_id}/advertisers/{advertiser_id}/product_ads/ads/search",
            params={
                "date_from": date_from,
                "date_to": date_to,
                "metrics": self.ADS_METRICS,
                "limit": limit,
                "offset": offset,
            },
        )

    def search_ads_todas(self, site_id: str, advertiser_id: str, date_from: str, date_to: str) -> list:
        """Pagina search_ads hasta traer todos los ads de la cuenta."""
        resultados: list = []
        offset = 0
        limit = 200
        while True:
            pagina = self.search_ads(site_id, advertiser_id, date_from, date_to, limit=limit, offset=offset)
            resultados.extend(pagina.get("results", []))
            total = pagina.get("paging", {}).get("total", len(resultados))
            offset += limit
            if offset >= total:
                break
        return resultados

    def update_campaign_roas_target(self, site_id: str, campaign_id: str, roas_target: float) -> dict:
        """Ruta confirmada correcta (el GET del mismo endpoint funciona), pero
        el PUT devuelve 401 'User does not have permission to write' -
        confirmado en vivo 21/07/2026. La app todavía no tiene el permiso de
        escritura habilitado para Product Ads (gestionar en ML Developers).
        roas_target documentado entre 1x y 35x."""
        return self._request(
            "PUT",
            f"/marketplace/advertising/{site_id}/product_ads/campaigns/{campaign_id}",
            json={"roas_target": roas_target},
        )

    def update_campaign_budget(self, site_id: str, campaign_id: str, daily_budget: float) -> dict:
        """Mismo endpoint y mismo bloqueo de permiso (401) que update_campaign_roas_target."""
        return self._request(
            "PUT",
            f"/marketplace/advertising/{site_id}/product_ads/campaigns/{campaign_id}",
            json={"budget": daily_budget},
        )

    def add_item_to_campaign(self, advertiser_id: str, campaign_id: str, item_id: str) -> dict:
        """OBSOLETO: ruta legacy por item_id, confirmado 404 (no existe más).
        Ver get_ad_groups/move_ad_group — ML gestiona por ad_group_id ahora."""
        return self._request(
            "POST",
            f"/advertising/advertisers/{advertiser_id}/product_ads/campaigns/{campaign_id}/items",
            json={"id": item_id},
        )

    def remove_item_from_campaign(self, advertiser_id: str, campaign_id: str, item_id: str) -> dict:
        """OBSOLETO: ruta legacy por item_id, confirmado 404 (no existe más)."""
        return self._request(
            "DELETE",
            f"/advertising/advertisers/{advertiser_id}/product_ads/campaigns/{campaign_id}/items/{item_id}",
        )

    def get_ad_groups(self, site_id: str, advertiser_id: str, limit: int = 50, offset: int = 0) -> dict:
        """Confirmado en vivo 2026-08-05/06: GET funciona. Reemplaza el modelo
        viejo por item_id — SHAFFE tiene 442 ad_groups (tipo FAMILY, uno por
        producto/family_id, no por talle/color individual)."""
        return self._request(
            "GET",
            f"/marketplace/advertising/{site_id}/advertisers/{advertiser_id}/product_ads/ad_groups/search",
            params={"limit": limit, "offset": offset},
        )

    def get_ad_group(self, site_id: str, ad_group_id: str) -> dict:
        """Confirmado en vivo: GET individual funciona, devuelve status/campaign_id/title."""
        return self._request("GET", f"/marketplace/advertising/{site_id}/product_ads/ad_groups/{ad_group_id}")

    def move_ad_group(self, site_id: str, ad_group_id: str, campaign_id: str, status: str = "active") -> dict:
        """Mover un ad_group a otra campaña (o cambiar su status) en un solo PUT
        — no requiere DELETE+POST como el modelo viejo. CONFIRMADO BLOQUEADO:
        401 'User does not have permission to write' (probado 2026-08-06,
        mismo bloqueo que update_campaign_roas_target, no es específico de
        este endpoint). No usar en producción hasta que ML habilite escritura
        — verificar con get_ad_group después y hacer rollback si hiciera falta."""
        return self._request(
            "PUT",
            f"/marketplace/advertising/{site_id}/product_ads/ad_groups/{ad_group_id}",
            json={"status": status, "campaign_id": campaign_id},
        )

    def move_ad_groups_bulk(self, site_id: str, advertiser_id: str, ad_group_ids: list, campaign_id: str, status: str = "active") -> dict:
        """Versión en lote de move_ad_group. Mismo bloqueo 401 confirmado."""
        return self._request(
            "PUT",
            f"/marketplace/advertising/{site_id}/advertisers/{advertiser_id}/product_ads/ad_groups",
            json={"ad_groups": ad_group_ids, "status": status, "campaign_id": campaign_id},
        )

    def remove_ad_group(self, site_id: str, campaign_id: str, ad_group_id: str) -> dict:
        """NO PROBAR mientras move_ad_group siga dando 401 — si el DELETE
        funcionara mientras el PUT no, se podría sacar un ad_group de Ads sin
        forma confirmada de reponerlo por API."""
        return self._request(
            "DELETE",
            f"/marketplace/advertising/{site_id}/product_ads/campaigns/{campaign_id}/ad_groups/{ad_group_id}",
        )

    def pause_item(self, site_id: str, item_id: str, status: str = "paused") -> dict:
        """Ruta confirmada correcta (el GET del mismo endpoint -- get_ad --
        funciona), pero el PUT devuelve 503 de forma consistente (probado 5
        veces en momentos distintos, no parece un timeout puntual) -
        confirmado en vivo 21/07/2026. Sin campaign_id en la ruta: el ad se
        identifica solo por item_id + site_id."""
        return self._request(
            "PUT",
            f"/marketplace/advertising/{site_id}/product_ads/ads/{item_id}",
            json={"status": status},
        )

    # --- Items / stock (API de Items estándar, no Ads) ---

    def add_item_to_promotion(self, item_id: str, promotion_id: str, promotion_type: str = "PRICE_DISCOUNT") -> dict:
        """Adhiere el item a una promoción activa del seller (Seller Promotions API).
        Verificar promotion_type y payload exacto según el tipo de promo real
        que tenga activa SHAFFE antes de usar en producción."""
        return self._request(
            "POST",
            f"/seller-promotions/items/{item_id}",
            params={"promotion_id": promotion_id, "promotion_type": promotion_type},
        )

    def get_item(self, item_id: str) -> dict:
        return self._request("GET", f"/items/{item_id}")

    def get_item_description(self, item_id: str) -> dict:
        """Confirmado en vivo 21/07 y 27/07: devuelve {"text", "plain_text", ...}."""
        return self._request("GET", f"/items/{item_id}/description")

    def update_item_description(self, item_id: str, plain_text: str) -> dict:
        """Confirmado en vivo: PUT /items/{id}/description con {"plain_text": ...}
        reemplaza la descripción completa del item (API de Items estándar, no
        Ads — nada que ver con el bloqueo de escritura de Product Ads)."""
        return self._request("PUT", f"/items/{item_id}/description", json={"plain_text": plain_text})

    def get_items_multiget(self, item_ids: list, attributes: str = "id,status,available_quantity,price") -> list:
        """Confirmado en vivo: GET /items?ids=A,B,C (máx. 20 ids por llamada),
        devuelve [{"code": 200, "body": {...}}, ...]. SHAFFE publica cada
        talle/color como item_id separado (variations=[] siempre), así que el
        stock real de un producto es la suma de available_quantity de todos
        los item_ids de su family_id."""
        resultados: list = []
        for i in range(0, len(item_ids), 20):
            lote = item_ids[i:i + 20]
            data = self._request("GET", "/items", params={"ids": ",".join(lote), "attributes": attributes})
            resultados.extend(r["body"] for r in data if r.get("code") == 200)
        return resultados

    def get_seller_items(self, status: str = "active") -> dict:
        return self._request(
            "GET", f"/users/{self.seller_id}/items/search", params={"status": status, "limit": 100}
        )

    def search_orders_todas(self, date_from: str, date_to: str, status: str = "paid") -> list:
        """Todas las órdenes del seller en el rango de fechas (paginado).
        Confirmado en vivo 26/07/2026: GET /orders/search con seller + rango
        de order.date_created, cada resultado trae order_items[].item.id y
        .quantity. date_from/date_to: fecha ISO (YYYY-MM-DD), se les agrega
        horario UTC automáticamente. Se usa para cruzar con las métricas de
        Ads antes de recomendar sacar un producto (ver regla 7 de
        agents/ANALISIS_INSTRUCCIONES.md): "ventas directas" en Ads no cuenta
        ventas indirectas ni orgánicas, un producto con 0 en Ads puede estar
        vendiendo bien igual."""
        resultados: list = []
        offset = 0
        limit = 50
        while True:
            data = self._request(
                "GET",
                "/orders/search",
                params={
                    "seller": self.seller_id,
                    "order.status": status,
                    "order.date_created.from": f"{date_from}T00:00:00.000-00:00",
                    "order.date_created.to": f"{date_to}T23:59:59.000-00:00",
                    "limit": limit,
                    "offset": offset,
                },
            )
            resultados.extend(data.get("results", []))
            total = data.get("paging", {}).get("total", len(resultados))
            offset += limit
            if offset >= total:
                break
        return resultados

    def ventas_reales_por_item(self, date_from: str, date_to: str, status: str = "paid") -> dict:
        """item_id -> unidades vendidas reales (todas las órdenes, sea que
        vengan de un click de Ads o no) en el rango de fechas."""
        unidades: dict = {}
        for orden in self.search_orders_todas(date_from, date_to, status=status):
            for item_orden in orden.get("order_items", []):
                item_id = (item_orden.get("item") or {}).get("id")
                if not item_id:
                    continue
                unidades[item_id] = unidades.get(item_id, 0) + item_orden.get("quantity", 0)
        return unidades
