# Reporte manual — 2026-07-21

Artifact publicado (versión final del día, con todas las correcciones aplicadas en la conversación):
https://claude.ai/code/artifact/fa89c643-4d2c-4df6-8f60-2f82323d0d71

## Contenido de esta carpeta
- `reporte.html` — copia exacta del HTML publicado como Artifact ese día.
- `analisis_manual_output.json` — snapshot de métricas/decisiones por producto y campaña.
- `candidatas_agrupadas.json` — publicaciones activas sin Ads, agrupadas por nombre.
- `estado_items.json` — status real (active/hold/paused) por family_id.
- `ctr_potencial.json` — ranking de CTR más bajo con potencial de venta.
- `gasto_semanal.json` — gasto/ingresos por campaña en 4 ventanas de ~7 días.
- `presupuestos_v2.json` — presupuesto sugerido por campaña con diagnóstico y motivo.

## Resumen de correcciones hechas en esta sesión (para no repetirlas)
1. Presupuesto: pasó de promedio 30d/30 a ventanas semanales (detecta saturación real).
2. Estado hold/pausado: se agregó chequeo de `status` por item — antes se confundía "0 ventas por estar pausado" con "0 ventas por mala foto".
3. "Bajar puja" no existe por publicación en ML Ads — corregido a nivel campaña.
4. Desglose por producto dentro de una campaña antes de fijar presupuesto (caso Plata Medio: Campera Guata es 80% del gasto y la que satura sola).
5. Se encontraron las rutas API correctas de campañas (`/search`) — el endpoint no estaba caído, era una ruta legacy deprecada por ML. Escritura sigue bloqueada por permiso real (401), no por ruta.
6. Bug de "talle único" en `es_poco_stock()` corregido en el código (`core/campaign_rules.py`) — pero ojo, el primer intento de corrección también tuvo un error (ver siguiente punto).
7. Algunos productos usan el campo nativo `variations` de ML (talles/colores dentro de 1 item_id) en vez de item_ids separados — el pipeline no lo detecta solo, hay que verificar con `get_item()` antes de asumir "talle único" por el conteo de item_ids.

Detalle completo de todo esto en la memoria del proyecto (`project_shaffe_ads_agent`) y en `feedback_ads_analisis`.

## Permisos de escritura Ads (mismo día, más tarde)
- Usuario habilitó "Publicidad de un producto: Lectura y escritura" en el panel de Developers (antes "Sin acceso") y reautorizó la app (nuevo `refresh_token` con scope `urn:ml:mktp:ads:/read-write`).
- Aun así, `PUT` a campañas sigue dando 401 "User does not have permission to write" (`mclics.campaigns.exceptions.UnauthorizedException`) — probamos headers alternativos (`Api-Version`, `x-format-new`), nada cambió. Puede ser demora de propagación o un permiso adicional específico de Mercado Ads (no de Developers). Pendiente reintentar más adelante.

## Descripciones actualizadas — primeros renglones (mismo día)
Se reescribieron los primeros renglones de la descripción de los 11 productos con peor CTR (ver `ctr_potencial.json`), con foco en refrescar keywords y, donde tenía sentido (Campera Inflable Guata, Buzo Canguro Friza, Pantalón Jogging Rústico), sumar la búsqueda "vacaciones de invierno". De paso se sacó texto viejo de "Día del Padre" (de junio) que había quedado en 2 productos, y se completó una descripción que estaba vacía (Jogger Básico).

**180 de 205 publicaciones actualizadas** (las 25 que fallaron son talles/colores con status `closed` en esos mismos 2 productos con texto de Día del Padre — no editables por API, no visibles para clientes, no hace falta arreglarlas). Detalle línea por línea del antes/después en `resultado_descripciones.json` (item_ids actualizados) y el criterio completo en `resumen_cambios.md` de esta misma carpeta.

Productos tocados: Pantalón Gabardina Chupin, Pack X3 Remeras, Pantalón De Vestir Gabardina, Pantalón Jogging Babucha Rústico, Campera Inflable Guata, Pantalón Urbano Jogger Lycra, Buzo Canguro Friza Hoodie, Pantalón Babucha Recto Deportivo, Buzo Crop Mujer, Jogger Básico, Remera Oversize Streetwear.
