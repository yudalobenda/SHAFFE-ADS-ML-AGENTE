# Sesión manual — 2026-07-30

Sin Artifact publicado esta vez — sesión de auditoría + ejecución directa, no de reporte visual.

## Contenido de esta carpeta
- `analisis_manual_output.json` — snapshot de `analisis_reporte_manual.py` (30 días), corrido DESPUÉS del fix de paginación de `search_orders_todas` (commit `407b9ae`, 28/07).
- `campanias_reales_30_07.json` — budget/roas_target/status real de las 11 campañas (`ml.get_campaigns`).
- `ventas_reales_14d_30_07.json` — `ml.ventas_reales_por_item()` últimos 14 días, usado para cruzar contra Ads.
- `analisis_ia_30_07.md` — narrativa de `agents/ai_analyst.py` (modelo `gpt-4.1`) sobre estos datos.
- `ctr_cvr_bajo_30_07.json`/`.txt` — los 16 productos que dispararon alerta `ctr_bajo`/`cvr_bajo` real (aplicando el mismo filtro que `main.py::modo_collect()`: se descartan si el ROAS ya supera el objetivo).
- `check_items_30_07.json` — foto/descripción/promos real de los 7 productos de mayor gasto de esa lista de 16 (`ml.get_item`, `ml.get_item_description`, `GET seller-promotions/items`).
- `promo_full_check.txt` — respuesta completa (sin truncar) de promos candidatas para 2 items de referencia.
- `resultado_promos_30_07.json` / `_activar_promos.py` — resultado de activar PRICE_DISCOUNT en Remera Térmica Niño (11 variantes) y Chupin (27 variantes).
- `resultado_descripciones_30_07.json` / `_actualizar_descripciones.py` — resultado de reescribir la apertura de descripción en Corte Chino (1 item, usa `variations` nativo) y Chupin (27 item_ids).

## Motivo de la sesión
El usuario vio el panel del 27/07 y sospechó (con razón) que la recomendación "cambiar foto" repetida en toda la lista era genérica, no un chequeo real. Pidió además que a futuro siempre se ofrezcan foto/descripción/promo como opciones concretas, se le pregunte cuál aplicar, y se ejecute directo. Ver [[feedback_ml_ads_acciones_reales]] (memoria nueva creada en esta sesión).

## Hallazgo confirmado sobre el panel
`core/campaign_rules.py::recomendacion_alerta()` devuelve texto fijo por el ratio ROAS/objetivo — nunca mira la foto real. Auditando los 7 productos de mayor gasto de la lista de 16 con `ctr_bajo`/`cvr_bajo`:
- **Solo 2 de 7 (Corte Chino, Chupin) tenían un problema de foto real** — el mismo defecto ya detectado el 21/07 (recorte a la cintura, sin cabeza, calzado que no combina con "de vestir"), nunca corregido en 9 días.
- **4 de 7 (Piloto Lluvia, Remera Térmica Niño, Pantalón Baggy Babucha, Cargo Parachute) tenían la foto perfectamente bien** — la alerta ahí era ruido de plantilla.
- **1 de 7 (Campera Mujer Deportiva) era un falso positivo total**: las 26 variantes están pausadas o cerradas, 0 unidades disponibles para vender. El gasto de $131k que mostraba el panel es histórico (de cuando sí estaba activa). No hay nada que optimizar ahí.
- **Cargo Parachute** (el peor ROAS real, 1.26/3.0) ya tenía una promo PRICE_DISCOUNT activa desde el 19/07 y una foto sin problemas — su bajo rendimiento no es de marketing, es de producto/precio/demanda. Decisión del usuario: esperar unos días más antes de tocar nada.

## Fix de paginación (28/07) — impacto real verificado
Se corrió `analisis_reporte_manual.py` con el fix ya aplicado: 41 productos activos en ads (vs. 34 el 27/07, 39 antes). El "Vaso Térmico" que llevaba semanas marcado con 0 ventas reales **sigue en 0** tras el fix — no era el bug de paginación, es un producto real sin tracción. Ningún otro "crítico" de sesiones previas cambió de diagnóstico por este fix en esta corrida puntual.

## Acciones ejecutadas (con aprobación explícita del usuario, item por item)
1. **Promo PRICE_DISCOUNT activada** en Remera Térmica Niño (11/12 variantes activas — 1 ya la tenía de la prueba previa) y Chupin (27/45 variantes activas con candidata disponible) — precio sugerido por ML (`suggested_discounted_price`), ventana 30/07 al 13/08. **Ojo**: en Chupin el descuento sugerido varió fuerte entre talles (16% a 50% off según variante) — vale la pena que el usuario revise `resultado_promos_30_07.json` para confirmar que los descuentos más agresivos (~50%) le sirven, no se filtró ni se le preguntó por variante individual, solo se usó el valor que sugiere ML.
2. **Descripción reescrita** (solo apertura, resto intacto) en Corte Chino (1 item, usa `variations` nativo — 21 talles/colores en el mismo item_id) y las 27 variantes activas de Chupin. 0 errores, 0 sin-match.
3. **No se tocó** Piloto Lluvia ni Pantalón Baggy Babucha (el usuario no las seleccionó para promo) ni Cargo Parachute (decisión: esperar).

## Pendiente de esta sesión
- Confirmar con el usuario si los descuentos de ~50% en algunas variantes de Chupin son aceptables o hay que ajustarlos a mano (ML no deja elegir el % exacto por API sin volver a leer `min_discounted_price`/`max_discounted_price` y mandar un `deal_price` propio).
- Corte Chino y Chupin: la foto real sigue sin corregirse (era el pendiente desde el 21/07) — la descripción nueva es un parche mientras se consigue la sesión de fotos.
- Sin commitear a git — quedó pendiente confirmar con el usuario (ver estado de git heredado de sesiones previas: migración de `copywriter.py`/`ai_analyst.py` de Anthropic a OpenAI, más el script de comparación de modelos, todavía sin decidir el modelo default).
