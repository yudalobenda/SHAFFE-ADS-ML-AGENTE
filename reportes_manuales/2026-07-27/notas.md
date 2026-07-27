# Reporte manual — 2026-07-27

Panel publicado como Artifact:
https://claude.ai/code/artifact/6a978190-d7be-4b13-9ad3-2d618afec53c

## Contenido de esta carpeta
- `reporte.html` — copia exacta del HTML publicado como Artifact ese día.
- `panel_data.json` — resumen condensado (KPIs, campañas, necesitan_accion con severidad, candidatas sin ads, tier_dividido) que arma el panel.
- `analisis_manual_output.json` — snapshot crudo de `analisis_reporte_manual.py` (30 días, todas las campañas).
- `campanias_reales.json` — budget/roas_target/status real de las 9+ campañas (vía `ml.get_campaigns`).
- `analisis_ia.md` — análisis narrativo generado por `agents/ai_analyst.py` (OpenAI) sobre estos mismos datos, primera corrida con cuenta completa (antes solo se había probado con 2 campañas).

## Contexto de esta corrida
Primera vez que se genera el panel manual usando el `ai_analyst.py` recién armado (ver commits del 26-27/07 en el repo) en vez de análisis 100% manual en el chat. El cron semanal automático está pausado a pedido del usuario (27/07) — el reporte se pide a demanda por ahora, este es uno de esos pedidos.

## Hallazgos de esta corrida (para no repetir el análisis de cero la próxima vez)
- **Cuenta general:** gasto 30d $6.362.706, ingresos atribuidos $30.430.694, ROAS de cuenta 4.78x. 7/9 campañas activas, 39 productos activos en ads.
- **`necesitan_accion` se calculó aplicando el MISMO filtro que usa `main.py::modo_collect()` real**: alertas ctr_bajo/cvr_bajo se descartan si el ROAS del producto ya supera el objetivo de su campaña — el script `analisis_reporte_manual.py` NO aplicaba este filtro (guarda `alertas` crudo), así que sin este ajuste habrían aparecido 34 "necesitan acción" en vez de 23 reales, la mayoría ruido (ctr_bajo en productos con ROAS excelente). **Si se vuelve a usar `analisis_reporte_manual.py` para armar un panel, replicar este filtro a mano** (ver `build_panel.py` en el scratchpad de la sesión, no está en el repo).
- **9 críticos reales**: Pantalón Jogging Recto (oro_medio, ROAS 2.75 vs objetivo 6.5 — la campaña está pausada pero el producto seguiría mal si se reactiva) y 8 productos con 0 ventas reales pese a tener gasto (Jean Baggy Mujer, 2 Buzos Hoodie, Sweater Oversize, 2 Remeras Oversize, Bermuda, Pantalón Cargo Parachute Mujer con ROAS 0.67).
- **7 oportunidades reales** (candidatas a subir de tier, ROAS ya por encima del objetivo): Remera Lisa Algodón (19.55x), Remera Oversize (27.38x), Polera Morley (10.21x), Pack X2 Gorro Lana, Pantalón Jean Baggy Nena/Niño, Buzo Crop Mujer.
- **Tier dividido sin resolver**: Vaso Térmico Acero Inoxidable sigue repartido entre plata_medio y testeo_bajo (ya detectado en sesiones previas, ver [[project_shaffe_ads_agent]]) — en ambas campañas rinde mal (ROAS 2.66x), la IA coincidió en recomendar pausarlo directamente en las dos.
- **Campaña nueva "prueba pantalon" (id 358374832) IDENTIFICADA**: 19 variantes de un Pantalón Corte Chino Gabardina Semi Recto (beige/negro/verde, talles 38-50). Gasto real 30d $601.422, ingresos $3.645.683 — nada chico. Sigue sin estar en `memory/campaign_ids.json`, así que todo el sistema (determinístico y este panel) la ignora por completo. Pendiente: agregarla y clasificar el ticket según precio.
- **La IA (OpenAI) coincidió en general con el análisis determinístico** pero agrega contexto que el sistema de reglas no tiene (estacionalidad de abrigos, "confirmar talle único real" en productos con 1 sola variante — la misma trampa de `variations` ocultas ya documentada en [[feedback_ads_analisis]]). No reemplaza el chequeo de `get_item().variations`, solo lo señala como sospecha.

## Corrección post-publicación (mismo día, el usuario cruzó contra el panel real de ML)
- **El usuario mostró un screenshot del panel oficial de ML Ads**: mostraba Inversión $7.898.881 e Ingresos $36.980.523 (30 días) — bastante por encima de lo que este reporte calculó ($6.362.706 / $30.430.694). Se investigó en vez de asumir.
- **Causa real, cuantificada**: el total de cuenta de ML incluye (a) la campaña "prueba pantalon" de arriba ($601.422, sin registrar en `campaign_ids.json`) y (b) **2 campañas eliminadas** (ids `294904181` y `356558673`) que ya no aparecen en `get_campaigns()` ni `get_campaign()` individual (404 en ambos) pero **sí** siguen sumando en `ads/search` — el propio dashboard de ML lo aclara con una nota al pie: "las métricas incluyen los datos de tus campañas eliminadas". Una de esas dos (`294904181`) tuvo $795.866 de gasto real en 30 días, la otra $0. Sumando todo: $6.398.564 + $601.422 + $795.866 = $7.795.852, contra los $7.898.881 de ML (~1,3% de diferencia residual, probablemente por el corte exacto de huso horario del día).
- **Ver [[project_shaffe_ads_agent]] y `core/ml_client.py`**: si se necesita que un reporte cuadre exacto con el total oficial de ML, hay que sumar aparte el historial de campañas eliminadas (no hay endpoint para listarlas, solo aparecen si ya se sabe el campaign_id de antes por `ads/search`) — no hay forma de "descubrirlas" de cero.
- **Bug propio encontrado y corregido en el mismo momento**: la tabla de "ROAS real vs objetivo" de este panel comparaba contra `campanias_reales.json[].roas_target` (la palanca algorítmica que carga ML, ej. Oro Medio en 3.8x) en vez del objetivo de negocio real (`campaign_rules.roas_target_campania()`, ej. Oro Medio = 6.5x) — la tabla de "Qué cambiar ahora" sí usaba el valor correcto desde el principio, quedó inconsistente entre las dos secciones del mismo panel. Corregido: ahora ambas tablas usan el objetivo de negocio, y la palanca de ML se muestra aparte como dato de referencia ("palanca ML: X"). **Regla para no repetir el error**: nunca usar el `roas_target` que devuelve la API de ML como el objetivo de evaluación — siempre `campaign_rules.roas_target_campania(nombre_campania)`.

## Pendiente de decisión del usuario
Los mismos puntos que en `HANDOFF.md` del 25/07 siguen abiertos (ticket de soporte ML, roas_target de testeo_bajo, fotos del Buzo Canguro), más lo nuevo de esta sesión: agregar "prueba pantalon" a `campaign_ids.json`.
