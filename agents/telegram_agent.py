"""Agente de notificaciones: reporte semanal por Telegram con botones de aprobación."""
from __future__ import annotations

import os
import time

import requests

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramAgent:
    def __init__(self):
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        self.chat_id = os.environ["TELEGRAM_CHAT_ID"]
        self._base = f"{TELEGRAM_API_BASE}/bot{self.token}"

    def enviar_reporte(self, acciones: list) -> None:
        if not acciones:
            self._enviar_mensaje("✅ Análisis semanal SHAFFE Ads: sin acciones para revisar esta semana.")
            return

        self._enviar_mensaje(
            f"📊 *Reporte semanal SHAFFE Ads*\nDetecté {len(acciones)} acción(es) propuesta(s). Revisá cada una abajo."
        )

        for i, accion in enumerate(acciones):
            botones = {
                "inline_keyboard": [[
                    {"text": "✅ Aprobar", "callback_data": f"aprobar:{i}"},
                    {"text": "❌ Rechazar", "callback_data": f"rechazar:{i}"},
                ]]
            }
            self._enviar_mensaje(self._texto_accion(accion), reply_markup=botones)

    def _texto_accion(self, accion: dict) -> str:
        tipo = accion.get("tipo")
        nombre = accion.get("family_name") or accion.get("item_id", "")
        n_variantes = len(accion.get("item_ids", []))
        sufijo_variantes = f" ({n_variantes} variantes)" if n_variantes > 1 else ""

        if tipo == "mover_tier":
            return (
                f"🔄 *{nombre}*{sufijo_variantes}\n{accion['tier_origen']} → {accion['tier_destino']}\n"
                f"ROAS reciente: {accion.get('roas_reciente', 'N/D')}"
            )
        if tipo == "agregar_a_testeo":
            return f"🆕 *{nombre}*{sufijo_variantes}\nNueva publicación → agregar a {accion['campania']} (ROAS objetivo 3)"
        if tipo == "agregar_a_promo":
            return f"📦 *{nombre}*{sufijo_variantes}\nPoco stock → agregar a promo ML"
        if tipo == "pausar":
            return f"⏸️ *{nombre}*{sufijo_variantes}\nMotivo: {accion.get('motivo')}"
        if tipo == "alerta":
            detalle = {
                "ctr_bajo": "CTR bajo con muchas impresiones → revisar foto principal o precio",
                "cvr_bajo": "CVR bajo con buenos clics → revisar descripción o ficha",
            }.get(accion["alerta"], accion["alerta"])
            return f"⚠️ *{nombre}*{sufijo_variantes}\n{detalle}\nROAS actual: {accion.get('roas', 0):.2f}"
        if tipo == "tier_dividido":
            return (
                f"🚧 *{nombre}*\nLas variantes de este producto están repartidas en campañas distintas: "
                f"{', '.join(accion.get('tiers_detectados', []))}. Corregilo a mano — el agente no lo mueve solo."
            )
        return f"❔ *{nombre}*\n{accion}"

    def _enviar_mensaje(self, texto: str, reply_markup: dict | None = None) -> None:
        payload = {"chat_id": self.chat_id, "text": texto, "parse_mode": "Markdown"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = requests.post(f"{self._base}/sendMessage", json=payload, timeout=30)
        resp.raise_for_status()

    def obtener_aprobaciones(self, acciones: list, timeout_seg: int = 300, intervalo_seg: int = 15) -> dict:
        """Long-poll a getUpdates buscando los callback_query de los botones enviados.
        Devuelve {indice_accion: True/False} para las acciones que recibieron respuesta."""
        decisiones: dict = {}
        offset = None
        tiempo_limite = time.time() + timeout_seg

        while time.time() < tiempo_limite and len(decisiones) < len(acciones):
            params = {"timeout": intervalo_seg}
            if offset is not None:
                params["offset"] = offset
            resp = requests.get(f"{self._base}/getUpdates", params=params, timeout=intervalo_seg + 10)
            resp.raise_for_status()
            for update in resp.json().get("result", []):
                offset = update["update_id"] + 1
                callback = update.get("callback_query")
                if not callback:
                    continue
                accion_str, idx_str = callback["data"].split(":")
                decisiones[int(idx_str)] = accion_str == "aprobar"
                self._responder_callback(callback["id"])

        return decisiones

    def _responder_callback(self, callback_query_id: str) -> None:
        requests.post(
            f"{self._base}/answerCallbackQuery", json={"callback_query_id": callback_query_id}, timeout=15
        )
