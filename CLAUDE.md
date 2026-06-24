# SHAFFE ADS AGENT — Contexto del proyecto

## Quién soy / contexto del negocio
- Marca: **SHAFFE** (SHF S.A.) — ropa urbana/streetwear argentina
- Canal principal: MercadoLibre Argentina (Seller Platinum)
- Seller ID: `262443439`
- Client ID y Client Secret: ver `.env` (no commitear)
- Redirect URI: `https://shaffecompany.com.ar/meli/callback`
- Auth URL: `https://auth.mercadolibre.com.ar/authorization?response_type=code&client_id=2900560376757443&redirect_uri=https%3A%2F%2Fshaffecompany.com.ar%2Fmeli%2Fcallback&scope=offline_access+read+write+advertising`
- Objetivo: **$80.000.000/mes** de facturación (y creciendo)

## Qué hace este agente
Sistema multi-agente que gestiona campañas de MercadoLibre Ads automáticamente.
Corre cada **lunes a las 9am (Argentina, UTC-3)** vía GitHub Actions.
Modo: **human-in-the-loop** — genera reporte + Excel, envía a Telegram, espera aprobación.

---

## Estructura de campañas (9 campañas fijas)

| Tier | Ticket | ROAS objetivo | ACOS máximo | Lógica |
|------|--------|---------------|-------------|--------|
| Oro  | Alto ($33k+)         | 7.5+ | 13–15% | Productos probados, escalar |
| Oro  | Medio ($18k–$32.999) | 6.5+ | 15–18% | Campaña principal de crecimiento |
| Oro  | Bajo (< $18k)        | 8.0+ | 12–15% | Alta rotación, cuidar CPC vs margen |
| Plata | Recuperación        | 4.0+ | hasta 25% | Sala de observación, no es permanente |
| Testeo | Productos nuevos  | 2.5–3.5 tolerado | Alto tolerado | Laboratorio presupuesto chico |

### Clasificación de ticket por precio de venta
- **Bajo:** precio < $18.000
- **Medio:** $18.000 – $32.999
- **Alto:** $33.000+

---

## Semáforo general para decidir

| Situación | ROAS | ACOS | Acción |
|-----------|------|------|--------|
| GANADOR | > 6.5 | < 15% | Escalar o mover a Oro |
| OBSERVACIÓN | 4 a 6.5 | 15%–25% | Dejar 72hs más antes de decidir |
| PROBLEMA | < 4 | > 25% | Sacar si ya gastó suficiente para decidir |
| SIN DATOS | sin ventas | — | Dar 48–72hs si gastó poco; si gastó mucho sin vender, sacar |

---

## Lógica de movimiento de publicaciones

### Subir tier
- **Testeo → Plata:** ROAS > 3.5 sostenido 3 días consecutivos (≈ 72hs)
- **Testeo → Oro (salto directo):** ROAS ≥ 6.5 sostenido 3 días
- **Plata → Oro:** ROAS ≥ 6.5 sostenido 3 días → mover a Oro del ticket correcto

### Estabilidad en Oro
- Una vez confirmado en Oro y funcionando: **NO tocar por mínimo 15 días**
- Solo ajustar presupuesto leve si hay stock y ACOS está dentro del objetivo
- `memory/state.json` guarda `fecha_entrada_oro` por family_id para respetar esta regla

### Bajar tier / pausar
- **Oro → Plata:** ROAS < 5.5 sostenido 3 días (con gasto real)
- **Plata → pausar/sacar:** ROAS < 4.0 sostenido 3 días (con gasto real)
- Nunca degradar por un solo día malo: esperar 3 días de datos consistentes
- Analizar causa antes de bajar: ¿stock? ¿temporada? ¿competencia?

### Publicaciones nuevas
- **48 horas de gracia sin publicidad:** ML la indexa orgánicamente primero
- Recién después entrar a Ads en la campaña de Testeo del ticket correspondiente
- Notifica en Telegram para aprobación antes de subirla

### Publicaciones en testeo sin resultados
- 10–15 días sin conversiones → "último intento": sugerir cambio de foto, título o descripción
- Si después del último intento sigue sin resultados → pausar y notificar

---

## Alertas urgentes (fuera del ciclo semanal)
- Si un producto que venía bien (ROAS ≥ objetivo) cae 3 días consecutivos → **alerta inmediata por Telegram**
- Aparece también en la hoja "Alertas Urgentes" del Excel semanal
- No espera al ciclo de lunes; se envía en el mismo `modo_collect` al detectarlo

---

## Publicaciones sin publicidad — candidatas a ingresar
Analizar cada semana las publicaciones activas fuera de Ads:
- **Umbral de prioridad:** 20+ ventas orgánicas en 30 días (requiere orders API — por ahora marcadas manualmente)
- **Stock mínimo:** 10+ unidades para escalar con confianza; con menos de 5, no entrar
- **Precio/ticket:** definir campaña de Oro correcta según rango de precio
- Estas publicaciones aparecen en la hoja "Sin Ads - Candidatas" del Excel

---

## Métricas que analiza por publicación

### Las tres métricas clave
1. **ROAS** (ingresos atribuidos / costo): métrica principal de evaluación de tier
2. **ACOS** (costo / ingresos): si supera el máximo del tier → alerta
3. **CTR** (clics / impresiones): si es bajo con muchas impresiones → problema de foto o precio
4. **CVR** (conversiones / clics): si es bajo con buenos clics → problema de descripción o ficha

### Alertas automáticas
- CTR < 2% con ≥ 100 impresiones AND ROAS bajo objetivo → alerta "revisar foto/precio"
- CVR < 1% con ≥ 30 clics AND ROAS bajo objetivo → alerta "revisar descripción/ficha"
- ACOS > máximo del tier → alerta "acos_alto" (siempre, independiente del ROAS)
- Si CTR/CVR bajo pero ROAS bueno → **no alertar** (el funnel ya rinde bien para su tier)

---

## Gestión de stock

### Definición de "poco stock"
- Menos de 5 unidades totales del producto, **O**
- Solo quedan 1–2 talles / colores disponibles

### Con stock < 10 unidades: precaución al escalar
- No subir presupuesto si hay menos de 10 unidades
- Si viene de Plata queriendo subir a Oro y tiene poco stock → proponer igualmente pero con ⚠️ aviso

### Acción con poco stock
- Agregar publicación a **promo ML** (adhiere a promo activa del seller)
- Si es fin de temporada o se discontinúa → pausar ads directamente

---

## Presupuesto y ROAS objetivo

### Importante: roas_target configurado en ML ≠ ROAS real de evaluación
El `roas_target` que se envía a la API de ML es una **palanca algorítmica**, no el umbral real:
- Arranca **bajo a propósito**: si se pone alto desde el principio, ML no compite la campaña
- Las decisiones de tier **siempre** se evalúan contra el ROAS real logrado
- Ajustes de `roas_target` deben ser incrementales y conservadores

### ML Ads deprecó `acos_target` (diciembre 2025)
Usar `roas_target`. Conversión: `roas_target = 1 / (acos_target / 100)`

---

## Reporte semanal (cada lunes)

### Por Telegram (mensajes separados):
1. Resumen ejecutivo (totales de cuenta)
2. ⚠️ Alertas urgentes si las hay (enviadas inmediatamente al detectarlas)
3. Alertas informativas (CTR/CVR/ACOS/tier_dividido) — sin botones
4. Acciones de CAMPAÑAS (mover_tier, presupuesto) — **con botones ✅/❌**
5. Acciones de STOCK/PROMOS (promo, pausar) — **con botones ✅/❌**

### Excel (.xlsx):
- Generado automáticamente en `logs/shaffe_ads_reporte_YYYY-MM-DD.xlsx`
- Hojas: Resumen Ejecutivo, Publicaciones Problema, Alertas Urgentes, Sin Ads Candidatas, Acciones Semana, Historial Cambios
- Enviado como archivo adjunto por Telegram junto con el reporte

---

## Research mensual (tendencias ML Argentina)
- Categorías y productos en tendencia en MercadoLibre Argentina
- Hoja "Tendencias Research" del Excel (completar manualmente o via API de tendencias ML)
- Objetivo: identificar oportunidades de catálogo para SHAFFE

---

## Sistema de aprendizaje (memoria del agente)

Cuando el usuario rechaza una recomendación:
1. El agente pregunta el motivo vía Telegram
2. Si el motivo no cierra con los datos → cuestiona con la data concreta
3. Si el motivo es válido → guarda en `memory/learnings.json`

```json
{
  "item_id": "123456",
  "fecha": "2026-06-10",
  "accion_rechazada": "subir_tier_oro",
  "motivo": "se discontinua en 2 semanas",
  "no_sugerir": ["subir_tier"],
  "expira": "2026-07-10"
}
```

---

## Estructura de archivos

```
shaffe-ads-agent/
├── CLAUDE.md
├── .env                        # Credenciales (no commitear)
├── requirements.txt
├── main.py
│
├── agents/
│   ├── collector.py            # Fetch métricas ML Ads API
│   ├── analyst.py              # ROAS/ACOS/CTR/CVR + decisiones de tier
│   ├── structurer.py           # Construye dicts de acciones
│   ├── stock_agent.py          # Stock + promos
│   ├── report_agent.py         # Genera Excel semanal (.xlsx)
│   ├── copywriter.py           # Sugerencias foto/título/descripción
│   └── telegram_agent.py       # Reporte + botones aprobación
│
├── core/
│   ├── ml_client.py            # Cliente ML Ads API + auth
│   ├── campaign_rules.py       # Reglas de negocio (umbrales, tiers)
│   └── executor.py             # Ejecuta acciones aprobadas
│
├── memory/
│   ├── learnings.json
│   ├── campaign_ids.json       # IDs de las 9 campañas
│   ├── state.json              # Estado + fecha_entrada_oro por family_id
│   ├── roas_history.json       # Historial ROAS diario (60 días)
│   ├── changes_history.json    # Registro de todos los cambios ejecutados
│   └── ml_tokens.json          # Tokens ML (repo privado, no exponer)
│
└── .github/workflows/
    └── weekly_run.yml          # Cron lunes 9am ART
```

---

## Variables de entorno (.env)

```
ML_CLIENT_ID=2900560376757443
ML_CLIENT_SECRET=...
ML_SELLER_ID=262443439
ML_REDIRECT_URI=https://shaffecompany.com.ar/meli/callback

TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

ANTHROPIC_API_KEY=   # Para copywriter (opcional, usa template si está vacío)
```

---

## Reglas para Claude Code

- Siempre usar `roas_target` (nunca `acos_target`, fue deprecado)
- Nunca ejecutar acciones sin aprobación explícita del usuario vía Telegram
- Guardar logs de cada corrida en `logs/YYYY-MM-DD.json`
- Si la API de ML falla → notificar en Telegram y no ejecutar nada
- Idioma del código: inglés. Mensajes Telegram y reporte: español rioplatense
- El agente opera por family_id (grupo de variantes), nunca por item_id individual
- No mover publicaciones todos los días: cambios fuertes solo los lunes
- Nunca escalar con stock < 5 unidades
