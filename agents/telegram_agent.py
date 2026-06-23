"""Agente de notificaciones: reporte semanal por Telegram con botones de aprobación.

Formato pensado para no inundar el chat: un mensaje resumen, un digest de lo
informativo (alertas CTR/CVR, tier dividido — sin botones, no hay nada para
aprobar ahí), y un único mensaje con todo lo accionable (mover tier, agregar
a promo, pausar, etc.), cada propuesta numerada con su propio par de botones
Aprobar/Rechazar dentro del mismo mensaje."""
from __future__ import annotations

import os
import time

import requests

TELEGRAM_API_BASE = "https://api.telegram.org"
TIPOS_ACCIONABLES = {"mover_tier", "agregar_a_testeo", "agregar_a_promo", "pausar", "ajustar_presupuesto", "ajustar_roas_target"}
MAX_LARGO_MENSAJE = 3500  # margen bajo el límite real de Telegram (4096)


class TelegramAgent:
    def __init__(self):
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        self.chat_id = os.environ["TELEGRAM_CHAT_ID"]
        self._base = f"{TELEGRAM_API_BASE}/bot{self.token}"

    def enviar_reporte(self, acciones: list) -> None:
        if not acciones:
            self._enviar_mensaje("✅ Análisis semanal SHAFFE Ads: sin acciones para revisar esta semana.")
            return

        informativas = [a for a in acciones if a.get("tipo") not in TIPOS_ACCIONABLES]
        accionables = [(i, a) for i, a in enumerate(acciones) if a.get("tipo") in TIPOS_ACCIONABLES]

        self._enviar_mensaje(
            f"📊 *Reporte semanal SHAFFE Ads*\n"
            f"{len(informativas)} alerta(s) informativa(s) y {len(accionables)} propuesta(s) para aprobar."
        )

        if informativas:
            lineas = [self._linea_informativa(a) for a in informativas]
            self._enviar_digest("⚠️ *Alertas (informativo, no requieren acción)*", lineas)

        if accionables:
            self._enviar_accionables(accionables)

    def _enviar_digest(self, titulo: str, lineas: list) -> None:
        bloque = titulo
        for linea in lineas:
            if len(bloque) + len(linea) + 1 > MAX_LARGO_MENSAJE:
                self._enviar_mensaje(bloque)
                bloque = titulo
            bloque += "\n" + linea
        self._enviar_mensaje(bloque)

    def _enviar_accionables(self, accionables: list) -> None:
        """accionables: [(indice_original, accion), ...]. Un mensaje con todas
        las propuestas numeradas y, debajo, una fila de botones por cada una
        (el número del botón corresponde al número de la línea de texto)."""
        inicio = 0
        while inicio < len(accionables):
            lote = []
            texto = "✅ *Acciones propuestas — aprobá o rechazá cada una*"
            fin = inicio
            while fin < len(accionables):
                _, accion = accionables[fin]
                num = len(lote) + 1
                linea = f"\n{num}) {self._linea_accionable(accion)}"
                if len(texto) + len(linea) > MAX_LARGO_MENSAJE and lote:
                    break
                texto += linea
                lote.append(accionables[fin])
                fin += 1

            botones = [
                [
                    {"text": f"✅ {n}", "callback_data": f"aprobar:{i}"},
                    {"text": f"❌ {n}", "callback_data": f"rechazar:{i}"},
                ]
                for n, (i, _) in enumerate(lote, start=1)
            ]
            self._enviar_mensaje(texto, reply_markup={"inline_keyboard": botones})
            inicio = fin

    def _linea_informativa(self, accion: dict) -> str:
        tipo = accion.get("tipo")
        nombre = accion.get("family_name") or ""
        if tipo == "tier_dividido":
            return f"🚧 *{nombre}*: variantes repartidas en {', '.join(accion.get('tiers_detectados', []))} — corregir a mano."
        if tipo == "alerta":
            detalle = {"ctr_bajo": "CTR bajo → revisar foto/precio", "cvr_bajo": "CVR bajo → revisar descripción/ficha"}.get(
                accion["alerta"], accion["alerta"]
            )
            return f"⚠️ *{nombre}*: {detalle} (ROAS {accion.get('roas', 0):.2f})"
        return f"❔ *{nombre}*: {tipo}"

    def _linea_accionable(self, accion: dict) -> str:
        tipo = accion.get("tipo")
        nombre = accion.get("family_name") or accion.get("item_id", "")
        n_variantes = len(accion.get("item_ids", []))
        sufijo = f" ({n_variantes} var.)" if n_variantes > 1 else ""

        if tipo == "mover_tier":
            base = f"🔄 *{nombre}*{sufijo}: {accion['tier_origen']} → {accion['tier_destino']} (ROAS {accion.get('roas_reciente', 0):.2f})"
            if accion.get("poco_stock"):
                base += "\n   ⚠️ tiene poco stock — aprobá solo si vas a reponer"
            return base
        if tipo == "agregar_a_testeo":
            return f"🆕 *{nombre}*{sufijo}: nueva → {accion['campania']} (ROAS objetivo 3)"
        if tipo == "agregar_a_promo":
            return f"📦 *{nombre}*{sufijo}: poco stock → agregar a promo ML"
        if tipo == "pausar":
            return f"⏸️ *{nombre}*{sufijo}: pausar ({accion.get('motivo')})"
        if tipo == "ajustar_presupuesto":
            return f"💰 *{nombre}*: presupuesto → {accion.get('presupuesto_nuevo')}"
        if tipo == "ajustar_roas_target":
            return f"🎯 *{nombre}*: roas_target → {accion.get('roas_target_nuevo')}"
        return f"❔ *{nombre}*: {tipo}"

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
