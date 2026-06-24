"""Agente de notificaciones: reporte semanal por Telegram con botones de aprobación.

Mensajes enviados cada lunes:
1. Resumen ejecutivo (sin botones)
2. Alertas urgentes si las hay (sin botones, se envían inmediatamente al detectarlas)
3. Alertas informativas CTR/CVR/tier_dividido (sin botones)
4. Acciones de CAMPAÑAS — mover tier, presupuesto (con botones)
5. Acciones de STOCK/PROMOS — agregar a promo, pausar (con botones)
6. Archivo Excel como documento adjunto"""
from __future__ import annotations

import os
import time

import requests

TELEGRAM_API_BASE = "https://api.telegram.org"

TIPOS_CAMPANAS  = {"mover_tier", "ajustar_presupuesto", "ajustar_roas_target"}
TIPOS_PROMOS    = {"agregar_a_promo", "pausar", "agregar_a_testeo"}
TIPOS_ACCIONABLES = TIPOS_CAMPANAS | TIPOS_PROMOS

MAX_LARGO_MENSAJE = 3500


def _esc(text: str) -> str:
    """Escapa guiones bajos y caracteres especiales en valores dinámicos
    para que Telegram Markdown v1 no los interprete como cursiva."""
    return str(text).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")


class TelegramAgent:
    def __init__(self):
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        self.chat_id = os.environ["TELEGRAM_CHAT_ID"]
        self._base = f"{TELEGRAM_API_BASE}/bot{self.token}"

    # ------------------------------------------------------------------ #
    # Punto de entrada principal
    # ------------------------------------------------------------------ #
    def enviar_reporte(self, acciones: list, run_id: str = "") -> None:
        informativas = [a for a in acciones if a.get("tipo") not in TIPOS_ACCIONABLES]
        campanas = [(i, a) for i, a in enumerate(acciones) if a.get("tipo") in TIPOS_CAMPANAS]
        promos   = [(i, a) for i, a in enumerate(acciones) if a.get("tipo") in TIPOS_PROMOS]

        n_accionables = len(campanas) + len(promos)
        if not acciones:
            self._enviar_mensaje("✅ Análisis semanal SHAFFE Ads: sin acciones para revisar esta semana.")
            return

        self._enviar_mensaje(
            f"📊 *Reporte semanal SHAFFE Ads*\n"
            f"{len(informativas)} alerta(s) informativa(s) y {n_accionables} propuesta(s) para aprobar."
        )

        if informativas:
            self._enviar_alertas(informativas)

        if campanas:
            self._enviar_accionables(campanas, titulo="🔄 *Acciones de CAMPAÑAS — aprobá o rechazá*", run_id=run_id)

        if promos:
            self._enviar_accionables(promos, titulo="📦 *Acciones de STOCK y PROMOS — aprobá o rechazá*", run_id=run_id)

    def enviar_alertas_urgentes(self, alertas_urgentes: list) -> None:
        """Mensaje separado, enviado inmediatamente al detectar caídas sostenidas."""
        if not alertas_urgentes:
            return
        lineas = [f"⚠️ *ALERTAS URGENTES* — {len(alertas_urgentes)} producto(s) cayendo hace {alertas_urgentes[0].get('dias_cayendo', 3)}+ días:"]
        for a in alertas_urgentes:
            roas_ult = a.get("roas_ultimos_dias", [])
            roas_str = " → ".join(f"{r:.2f}" for r in roas_ult)
            lineas.append(
                f"• *{_esc(a['family_name'])}* ({_esc(a.get('campania', ''))}): "
                f"ROAS histórico {a.get('roas_historico_prom', 0):.2f} → últimos días {roas_str} "
                f"(caída {a.get('caida_pct', 0):.0f}%)"
            )
        lineas.append("\n_Revisá el Excel adjunto: hoja \"Alertas Urgentes\"._")
        self._enviar_digest("\n".join(lineas[:1]), lineas[1:])

    def enviar_archivo(self, ruta: str, caption: str = "") -> None:
        with open(ruta, "rb") as f:
            resp = requests.post(
                f"{self._base}/sendDocument",
                data={"chat_id": self.chat_id, "caption": caption, "parse_mode": "Markdown"},
                files={"document": f},
                timeout=60,
            )
        resp.raise_for_status()

    # ------------------------------------------------------------------ #
    # Alertas informativas (CTR/CVR/ACOS/tier_dividido)
    # ------------------------------------------------------------------ #
    def _enviar_alertas(self, informativas: list) -> None:
        divididos = [a for a in informativas if a["tipo"] == "tier_dividido"]
        ctr  = sorted((a for a in informativas if a.get("alerta") == "ctr_bajo"),  key=lambda a: a["roas"])
        cvr  = sorted((a for a in informativas if a.get("alerta") == "cvr_bajo"),  key=lambda a: a["roas"])
        acos = sorted((a for a in informativas if a.get("alerta") == "acos_alto"), key=lambda a: a.get("acos") or 0, reverse=True)

        if divididos:
            self._enviar_digest(
                "🚧 *Variantes repartidas entre campañas* — corregir a mano:",
                [f"• *{_esc(a['family_name'])}*: en {_esc(', '.join(a.get('tiers_detectados', [])))}" for a in divididos],
            )
        if ctr:
            self._enviar_digest(
                f"📷 *CTR bajo* ({len(ctr)}) — pocos clics para las impresiones que tienen:",
                [
                    f"• *{_esc(a['family_name'])}* (ROAS {a['roas']:.2f})\n"
                    f"  → {a.get('recomendacion', 'revisar foto o precio')}"
                    for a in ctr
                ],
            )
        if cvr:
            self._enviar_digest(
                f"📝 *CVR bajo* ({len(cvr)}) — entran pero no compran:",
                [
                    f"• *{_esc(a['family_name'])}* (ROAS {a['roas']:.2f})\n"
                    f"  → {a.get('recomendacion', 'revisar descripción o ficha')}"
                    for a in cvr
                ],
            )
        if acos:
            self._enviar_digest(
                f"💸 *ACOS alto* ({len(acos)}) — costo de publicidad supera el máximo del tier:",
                [
                    f"• *{_esc(a['family_name'])}* ({_esc(a.get('campania', ''))}) ACOS {a.get('acos', 0)*100:.1f}%\n"
                    f"  → {a.get('recomendacion', 'revisar puja o pausar')}"
                    for a in acos
                ],
            )

    def _enviar_digest(self, titulo: str, lineas: list) -> None:
        bloque = titulo
        for linea in lineas:
            if len(bloque) + len(linea) + 1 > MAX_LARGO_MENSAJE:
                self._enviar_mensaje(bloque)
                bloque = titulo
            bloque += "\n" + linea
        self._enviar_mensaje(bloque)

    # ------------------------------------------------------------------ #
    # Accionables con botones inline
    # ------------------------------------------------------------------ #
    def _enviar_accionables(self, accionables: list, titulo: str, run_id: str = "") -> None:
        """accionables: [(indice_original, accion), ...]. Un mensaje con todas las
        propuestas numeradas + una fila de botones por cada una.
        run_id se embebe en callback_data para filtrar callbacks de corridas viejas."""
        inicio = 0
        while inicio < len(accionables):
            lote = []
            texto = titulo
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

            prefix = f"{run_id}:" if run_id else ""
            botones = [
                [
                    {"text": f"✅ {n}", "callback_data": f"aprobar:{prefix}{i}"},
                    {"text": f"❌ {n}", "callback_data": f"rechazar:{prefix}{i}"},
                ]
                for n, (i, _) in enumerate(lote, start=1)
            ]
            self._enviar_mensaje(texto, reply_markup={"inline_keyboard": botones})
            inicio = fin

    def _linea_accionable(self, accion: dict) -> str:
        tipo = accion.get("tipo")
        nombre = accion.get("family_name") or accion.get("item_id", "")
        n_variantes = len(accion.get("item_ids", []))
        sufijo = f" ({n_variantes} var.)" if n_variantes > 1 else ""

        nombre_e = _esc(nombre)
        if tipo == "mover_tier":
            origen  = _esc(accion.get("campania_origen") or accion.get("tier_origen", ""))
            destino = _esc(accion.get("campania_destino") or accion.get("tier_destino", ""))
            base = f"🔄 *{nombre_e}*{sufijo}: {origen} → {destino} (ROAS {accion.get('roas_reciente', 0):.2f})"
            if accion.get("poco_stock"):
                base += "\n   ⚠️ tiene poco stock — aprobá solo si vas a reponer"
            return base
        if tipo == "agregar_a_testeo":
            return f"🆕 *{nombre_e}*{sufijo}: nueva → {_esc(accion.get('campania', 'testeo'))} (ROAS objetivo {accion.get('roas_target_inicial', 3.0)})"
        if tipo == "agregar_a_promo":
            return f"📦 *{nombre_e}*{sufijo}: poco stock → agregar a promo ML"
        if tipo == "pausar":
            motivo = accion.get("motivo", "").replace("_", " ")
            roas = accion.get("roas_reciente", 0) or 0
            return f"⏸️ *{nombre_e}*{sufijo}: pausar / sacar de ads (ROAS {roas:.2f}, {motivo})"
        if tipo == "ajustar_presupuesto":
            return f"💰 *{nombre_e}*: presupuesto → {accion.get('presupuesto_nuevo')}"
        if tipo == "ajustar_roas_target":
            return f"🎯 *{nombre_e}*: roas\\_target → {accion.get('roas_target_nuevo')}"
        return f"❔ *{nombre_e}*: {tipo}"

    # ------------------------------------------------------------------ #
    # Aprobaciones
    # ------------------------------------------------------------------ #
    def obtener_aprobaciones(
        self, acciones: list, run_id: str = "", offset: int | None = None
    ) -> tuple[dict, int | None]:
        """Drena callbacks pendientes (non-blocking, timeout=0).
        Solo acepta callbacks cuyo run_id coincida con el de la corrida actual.
        Devuelve (decisiones, nuevo_offset).
        Persistir el offset en state.json para no re-procesar updates anteriores."""
        decisiones: dict = {}

        params: dict = {"timeout": 0, "allowed_updates": ["callback_query"]}
        if offset is not None:
            params["offset"] = offset

        resp = requests.get(f"{self._base}/getUpdates", params=params, timeout=30)
        resp.raise_for_status()

        new_offset = offset
        for update in resp.json().get("result", []):
            new_offset = update["update_id"] + 1
            callback = update.get("callback_query")
            if not callback:
                continue
            data = callback["data"]
            parts = data.split(":")

            # Formato con run_id: "aprobar:RUN_ID:INDEX" (3 partes)
            # Formato legacy sin run_id: "aprobar:INDEX" (2 partes)
            if len(parts) == 3:
                accion_str, cb_run_id, idx_str = parts
                if run_id and cb_run_id != run_id:
                    # Callback de una corrida anterior — avisar y descartar
                    self._responder_callback(callback["id"], "⚠️ Acción vieja, volvé a presionar en el mensaje de hoy")
                    continue
            elif len(parts) == 2:
                accion_str, idx_str = parts
            else:
                continue

            try:
                idx = int(idx_str)
                decisiones[idx] = accion_str == "aprobar"
                self._responder_callback(callback["id"])
            except (ValueError, KeyError):
                pass

        return decisiones, new_offset

    def _responder_callback(self, callback_query_id: str, texto: str = "") -> None:
        payload: dict = {"callback_query_id": callback_query_id}
        if texto:
            payload["text"] = texto
            payload["show_alert"] = True
        requests.post(f"{self._base}/answerCallbackQuery", json=payload, timeout=15)

    # ------------------------------------------------------------------ #
    # Envío base
    # ------------------------------------------------------------------ #
    def _enviar_mensaje(self, texto: str, reply_markup: dict | None = None) -> None:
        payload = {"chat_id": self.chat_id, "text": texto, "parse_mode": "Markdown"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = requests.post(f"{self._base}/sendMessage", json=payload, timeout=30)
        resp.raise_for_status()
