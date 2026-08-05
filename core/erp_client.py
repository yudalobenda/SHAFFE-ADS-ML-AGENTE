"""Cliente HTTP contra el ERP de Shaffe — fuente de verdad de costos (ver CIOMA).

Mismo patrón que E:\\AGENTES CLAUDE\\SHAFFE CONTADOR AGENT\\core\\erp_client.py:
login JWT, relogueo automático cuando vence o el ERP devuelve 401. Este
agente NUNCA calcula costo propio (Excel, supuesto hardcodeado, etc.) —
siempre lo pide acá. Ver AUDITORIA-FASE-0.md / MEDICION-DIVERGENCIA-MARGEN.md.
"""
from __future__ import annotations

import time

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
        (el caller debe tratar eso como 'sin dato', no como costo cero)."""
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
