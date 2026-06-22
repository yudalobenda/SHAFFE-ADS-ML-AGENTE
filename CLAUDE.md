# SHAFFE ADS AGENT — Contexto del proyecto

## Quién soy / contexto del negocio
- Marca: **SHAFFE** (SHF S.A.) — ropa urbana/streetwear argentina
- Canal principal: MercadoLibre Argentina (Seller Platinum)
- Seller ID: `262443439`
- Client ID y Client Secret: ver `.env` (no commitear, ya están seteados localmente)
- Redirect URI: `https://shaffecompany.com.ar/meli/callback`
- Auth URL: `https://auth.mercadolibre.com.ar/authorization?response_type=code&client_id=2900560376757443&redirect_uri=https%3A%2F%2Fshaffecompany.com.ar%2Fmeli%2Fcallback&scope=offline_access+read+write+advertising`

## Qué hace este agente
Sistema multi-agente que gestiona campañas de MercadoLibre Ads automáticamente.
Corre cada **martes a las 9am (Argentina, UTC-3)** vía GitHub Actions.
Modo: **human-in-the-loop** — genera reporte, envía a Telegram, espera aprobación antes de ejecutar.

---

## Estructura de campañas (9 campañas fijas)

| Tier | Ticket | ROAS objetivo |
|------|--------|---------------|
| Oro  | Alto (+$40.000)    | >6.5 |
| Oro  | Medio ($19.000–$39.999) | >6.5 |
| Oro  | Bajo (hasta $18.999)   | >6.5 |
| Plata | Alto  | 4–6.5 |
| Plata | Medio | 4–6.5 |
| Plata | Bajo  | 4–6.5 |
| Testeo | Alto  | <4 (entrada) |
| Testeo | Medio | <4 (entrada) |
| Testeo | Bajo  | <4 (entrada) |

### Clasificación de ticket por precio de venta
- **Alto:** precio > $40.000
- **Medio:** $19.000 – $39.999
- **Bajo:** hasta $18.999

---

## Lógica de movimiento de publicaciones

### Subir tier
- Testeo → Plata: ROAS 4–6.5 sostenido ≥12 días
- Testeo → Oro: ROAS ≥6.5 ó crecimiento muy acelerado (puede saltear Plata)
- Plata → Oro: ROAS ≥6.5 sostenido ≥1 semana

### Bajar tier / pausar
- Si ROAS cae por debajo del objetivo >1 semana: bajar un tier
- Analizar causa antes de bajar: ¿temporada? ¿poco stock? ¿competencia?
- Poco stock + buenas ventas → NO bajar, sino agregar a promo ML

### Publicaciones en testeo sin resultados
- 10–15 días sin conversiones → "último intento": el agente sugiere cambiar foto principal, título o descripción
- Si después del último intento sigue sin resultados → pausar y notificar

### Publicaciones nuevas (detección automática)
- Cada martes el agente compara pubs activas en ML vs pubs en campañas
- Las que no están en ninguna campaña = "nuevas"
- Se agregan automáticamente a la campaña de **Testeo** según su precio (ticket)
- ROAS objetivo inicial conservador: 3
- Presupuesto mínimo al entrar
- Notifica en Telegram para aprobación: "Detecté X publicaciones nuevas, ¿las subo a testeo?"
- Excepción: si tiene stock insuficiente o precio fuera de rango → solo avisa, no sube

---

## Métricas que analiza por publicación

### Las tres métricas clave
1. **Impresiones** → si son muchas, ML está mostrando bien el título/categoría
2. **CTR (clics / impresiones)** → si es bajo con muchas impresiones: problema de foto principal o precio
3. **CVR (conversiones / clics)** → si es bajo con buenos clics: problema de descripción o ficha

### Alertas automáticas
- CTR < 2% con muchas impresiones → alerta "revisar foto principal o precio"
- CVR < 1% con buenos clics → alerta "revisar descripción o ficha"
- Crecimiento acelerado de ROAS → alerta positiva, candidata a subir tier

---

## Gestión de stock

### Definición de "poco stock"
- Menos de 5 unidades totales del producto, **O**
- Solo quedan 1–2 talles / colores disponibles (aunque haya más unidades de otros)

### Acción con poco stock
- Agregar publicación a **promo ML** (adhiere a una de las promos activas del seller)
- Puede mantenerse en ads simultáneamente
- Si es fin de temporada o se discontinúa → pausar ads directamente

---

## Presupuesto y ROAS objetivo

- Cada campaña tiene presupuesto propio (diario, como lo maneja ML)
- Si ROAS es bueno y hay ventas → el agente sugiere subir presupuesto
- Si ROAS es malo → sugiere bajar presupuesto o pausar
- El agente también evalúa ajustar el ROAS objetivo de la campaña una vez que está funcionando bien
- Nunca gasta por gastar: toda inversión tiene que tener retorno visible

### Nota técnica importante
ML Ads deprecó `acos_target` en diciembre 2025. Usar `roas_target`.
Conversión: `roas_target = 1 / (acos_target / 100)`

---

## Sistema de aprendizaje (memoria del agente)

Cuando el usuario rechaza una recomendación:
1. El agente pregunta el motivo vía Telegram
2. Si el motivo no cierra con los datos → el agente lo cuestiona con la data concreta
3. Si el motivo es válido → lo guarda en `memory/learnings.json`
4. La próxima semana tiene en cuenta ese contexto

Estructura de un aprendizaje guardado:
```json
{
  "item_id": "MLB123456",
  "fecha": "2026-06-10",
  "accion_rechazada": "subir_tier_oro",
  "motivo": "se discontinua en 2 semanas",
  "no_sugerir": ["subir_tier"],
  "expira": "2026-07-10"
}
```

---

## Notificaciones Telegram

- Bot exclusivo para este agente (no mezclar con otros bots)
- Token y Chat ID: configurar en `.env` antes de correr
- Reporte cada martes ~9:05am (después del análisis)
- Formato: resumen ejecutivo + lista de acciones con botones inline (✅ Aprobar / ❌ Rechazar)
- El agente ejecuta **solo** las acciones aprobadas

---

## Estructura de archivos del proyecto

```
shaffe-ads-agent/
├── CLAUDE.md                  # Este archivo
├── .env                       # Credenciales (no commitear)
├── .env.example               # Template de variables
├── requirements.txt
├── main.py                    # Entry point (GitHub Actions llama esto)
│
├── agents/
│   ├── collector.py           # Fetch métricas ML Ads API
│   ├── analyst.py             # Análisis ROAS/CTR/CVR + decisiones
│   ├── structurer.py          # Movimientos entre campañas
│   ├── stock_agent.py         # Monitoreo stock + promos
│   ├── copywriter.py          # Sugerencias foto/título/descripción
│   └── telegram_agent.py      # Reporte + botones aprobación
│
├── core/
│   ├── ml_client.py           # Cliente ML Ads API + auth
│   ├── campaign_rules.py      # Reglas de negocio (umbrales, tiers)
│   └── executor.py            # Ejecuta acciones aprobadas
│
├── memory/
│   ├── learnings.json         # Aprendizajes de rechazos del usuario
│   ├── campaign_ids.json      # IDs de las 9 campañas en ML
│   └── state.json             # Estado último ciclo
│
└── .github/
    └── workflows/
        └── weekly_run.yml     # Cron martes 9am UTC-3
```

---

## Variables de entorno necesarias (.env)

```
ML_CLIENT_ID=2900560376757443
ML_CLIENT_SECRET=r9WZJNZxxe9fUOjbEgNmAOFgxlXZVEBe
ML_SELLER_ID=262443439
ML_REDIRECT_URI=https://shaffecompany.com.ar/meli/callback
ML_ACCESS_TOKEN=        # Se renueva automáticamente con refresh token
ML_REFRESH_TOKEN=       # Obtener con el primer auth manual

TELEGRAM_BOT_TOKEN=     # Token del bot exclusivo para este agente
TELEGRAM_CHAT_ID=       # Tu chat ID personal

ANTHROPIC_API_KEY=      # Para el agente analista y redactor
```

---

## Reglas para Claude Code

- Siempre usar `roas_target` (nunca `acos_target`)
- El token de ML expira cada 6 horas → implementar auto-refresh con refresh_token
- Nunca ejecutar acciones sin aprobación explícita del usuario vía Telegram
- Guardar logs de cada corrida en `logs/YYYY-MM-DD.json`
- Si la API de ML falla → notificar en Telegram y no ejecutar nada
- Idioma del código: inglés. Idioma de los reportes/mensajes Telegram: español rioplatense
- El agente cuestiona al usuario cuando rechaza recomendaciones con datos sólidos
- Período de gracia para nuevas pubs: 12 días antes de tomar decisiones definitivas
