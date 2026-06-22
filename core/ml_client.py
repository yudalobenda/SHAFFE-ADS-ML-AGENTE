"""Cliente de la API de MercadoLibre Ads: auth con refresh token + operaciones.

NOTA: los paths/payloads de la Ads API (PADS) son el contrato esperado a partir
de la documentación pública de MercadoLibre; verificar contra la doc vigente
antes de la primera corrida en producción, porque ML las versiona seguido.
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

    def get_campaigns(self, advertiser_id: str) -> dict:
        return self._request("GET", f"/advertising/advertisers/{advertiser_id}/product_ads/campaigns")

    def get_campaign_items(self, advertiser_id: str, campaign_id: str) -> dict:
        return self._request(
            "GET", f"/advertising/advertisers/{advertiser_id}/product_ads/campaigns/{campaign_id}/items"
        )

    def get_item_metrics(self, advertiser_id: str, item_id: str, date_from: str, date_to: str) -> dict:
        return self._request(
            "GET",
            f"/advertising/advertisers/{advertiser_id}/product_ads/items/{item_id}",
            params={
                "date_from": date_from,
                "date_to": date_to,
                "metrics": "clicks,prints,cost,direct_amount,indirect_amount",
            },
        )

    def update_campaign_roas_target(self, advertiser_id: str, campaign_id: str, roas_target: float) -> dict:
        return self._request(
            "PUT",
            f"/advertising/advertisers/{advertiser_id}/product_ads/campaigns/{campaign_id}",
            json={"strategy": "profitability", "roas_target": roas_target},
        )

    def update_campaign_budget(self, advertiser_id: str, campaign_id: str, daily_budget: float) -> dict:
        return self._request(
            "PUT",
            f"/advertising/advertisers/{advertiser_id}/product_ads/campaigns/{campaign_id}",
            json={"budget": daily_budget},
        )

    def add_item_to_campaign(self, advertiser_id: str, campaign_id: str, item_id: str) -> dict:
        return self._request(
            "POST",
            f"/advertising/advertisers/{advertiser_id}/product_ads/campaigns/{campaign_id}/items",
            json={"id": item_id},
        )

    def remove_item_from_campaign(self, advertiser_id: str, campaign_id: str, item_id: str) -> dict:
        return self._request(
            "DELETE",
            f"/advertising/advertisers/{advertiser_id}/product_ads/campaigns/{campaign_id}/items/{item_id}",
        )

    def pause_item(self, advertiser_id: str, campaign_id: str, item_id: str) -> dict:
        return self._request(
            "PUT",
            f"/advertising/advertisers/{advertiser_id}/product_ads/campaigns/{campaign_id}/items/{item_id}",
            json={"status": "paused"},
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

    def get_seller_items(self, status: str = "active") -> dict:
        return self._request(
            "GET", f"/users/{self.seller_id}/items/search", params={"status": status, "limit": 100}
        )
