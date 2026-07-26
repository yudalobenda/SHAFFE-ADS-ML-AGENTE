# HANDOFF — Agente ML Ads SHAFFE

Última actualización: 2026-07-25. Este archivo es para que cualquier agente/sesión nueva entienda en qué quedó todo sin tener que releer el chat completo. Contexto de fondo (spec del sistema, reglas de negocio) está en `CLAUDE.md`. Decisiones y aprendizajes históricos del proyecto están en la memoria persistente (`project_shaffe_ads_agent` y notas relacionadas) — este doc es solo el estado de la sesión en curso, léelo antes de esa memoria porque es más reciente.

---

## 1. Qué se hizo en esta sesión (22 al 25/07/2026)

### 1.1 Ticket de soporte a Mercado Libre (401 en escritura) — SIN RESOLVER
- El 21/07 se redactó `reportes_manuales/2026-07-21/ticket_soporte_ml.md` con el detalle completo del problema: el permiso "Publicidad de un producto: Lectura y escritura" está habilitado en el panel de Developers, la app fue reautorizada (scope `urn:ml:mktp:ads:/read-write` confirmado en el token), la lectura funciona perfecto, pero **todo `PUT` de escritura a campañas sigue dando 401** `mclics.campaigns.exceptions.UnauthorizedException`.
- Se buscó el canal para enviar ese ticket (`developers.mercadolibre.com.ar` → sección Soporte). El usuario no lo encontró navegando el panel. **No se pudo verificar el contenido exacto de esa página por fetch automático (bloquea con 403, requiere sesión logueada)**.
- **Pendiente real:** el usuario tiene que entrar logueado a developers.mercadolibre.com.ar y buscar manualmente el link de soporte/contacto (puede estar en el footer, o en la sección de la app "openclaw"/"clawleon"). Backup si no aparece: cuenta de X @MeliDevelopers.
- El texto completo del ticket para copiar/pegar sigue en `reportes_manuales/2026-07-21/ticket_soporte_ml.md`, no se tocó.
- **La escritura por API en `product_ads/campaigns` (budget/roas_target) sigue bloqueada. Cualquier ajuste de presupuesto o roas_target hay que hacerlo a mano en el panel de ML.**

### 1.2 Descubrimiento: el usuario ya ajustó varias campañas a mano desde el 21/07
Se volvió a leer el estado real de las 9+ campañas vía API (`ml.get_campaigns('MLA', '21757')`) porque no había que asumir que los valores de la memoria (21/07) seguían vigentes. Cambiaron bastante:

| Campaña | roas_target 21/07 → 25/07 | budget 21/07 → 25/07 |
|---|---|---|
| oro_alto (357702416) | 4.0 → **5.5** | $45.000 → $38.000 |
| plata_medio (357700023) | 3.3 → **4.2** | $90.000 → $45.000 |
| testeo_bajo (357700013) | 2.8 (sin cambio) | $85.000 → $50.000 |
| testeo_medio (357700008) | 2.8 (sin cambio) | $30.000 → $23.000 |
| oro_bajo (357702510) | 3.8 → **6.0** | $10.000 → $12.000 |
| plata_bajo (357700015) | 3.3 (sin cambio) | $30.000 (sin cambio) |
| oro_medio (357709533) | 3.8 | $35.000 — sigue **paused** |

Además apareció una campaña nueva no registrada en `memory/campaign_ids.json`: **"prueba pantalon"** (id `358374832`, budget $5.500, roas_target 4.0, activa). **No se preguntó todavía qué es** — pendiente aclarar con el usuario y decidir si hay que sumarla a `campaign_ids.json`.

También existen 2 campañas viejas pausadas no registradas (ya sabidas de antes, sin cambios): "Campaña 5 ESCOLAR" (id 355938146) y "Campaña A Accesorios Invierno" (id 356310769).

### 1.3 Análisis testeo_bajo vs testeo_medio (a pedido del usuario, "punto 2")
Se calculó ROAS real por ventana semanal (4 ventanas de 7 días) y desglose por producto dentro de campaña, con `search_ads_todas`.

**testeo_bajo → recomendado subir roas_target 2.8 → 3.0 (un escalón).**
ROAS semanal sano y estable: 3.02x → 3.64x → 2.79x → 3.54x (últimas 4 semanas). El 91% del gasto es un solo producto (Pantalón Cargo Convertible Trekking) con ROAS 3.30x, dentro del rango tolerado de testeo (2.5-3.5x). Sin señal de saturación pese a que el gasto subió a ~$80k/día la última semana. **No se aplicó el cambio** (escritura API bloqueada) — hay que hacerlo a mano en el panel.

**testeo_medio → NO subir roas_target. Hay un producto puntual arruinando el promedio.**
ROAS de la campaña se desplomó: 3.57x → 3.84x → 2.81x → **1.75x** (última semana). Al desglosar por producto: **"Jogger Hombre Babucha Con Bolsillos Liso Básico Shaffe"** (item `MLA1719339758`, sin variantes, no agrupado por family_id) se comió **43% del gasto de la campaña ($68.655) con ROAS 1.07x** — muy por debajo del piso tolerado. Tiene stock de sobra (147 u), no es problema de stock. El resto de los productos de la campaña rinde bien (Buzo Canguro Friza 3.54x, Pantalón Babucha 2.17x).
**Pendiente de decisión del usuario:** pausar ese ítem puntual dentro de la campaña (a mano, ya que pausar por API sigue dando 503) o esperar unos días más si recién entró a testeo — no se pudo determinar la fecha de entrada desde `state.json` (no está registrada bajo ese item_id, la estructura del archivo no lo cubre para items sin family_id).

### 1.4 Foto de portada — Buzo Canguro Hombre Friza Hoodie (testeo_medio)
Se retomó el pendiente de fotos del 21/07 ("reordenar galería, la foto #2 ya sirve de portada gratis"). **Se verificó y la nota original estaba sobre-optimista:**
- Se bajaron y revisaron las 10 fotos de la galería (family_id `3859373507095129`, item de referencia `MLA3347547530`). **Las 10 tienen overlay de texto/infografía** ("MÁXIMA COMODIDAD", "BOLSILLO CANGURO", "CALIDAD QUE SE SIENTE", etc.) — ninguna es una foto de producto limpia sirviendo de portada. La única foto "limpia" es la portada actual (modelo mirando al costado).
- Fotos guardadas en el scratchpad de esta sesión (puede no persistir entre sesiones): `foto0_actual.jpg` (portada real) y `foto1_candidata.jpg` (la propuesta como reemplazo, con el texto superpuesto) + `foto2.jpg` a `foto9.jpg` (resto de la galería). Si hace falta volver a verlas, se pueden re-descargar de las URLs (quedaron en el log de esta sesión) o desde `ml.get_item(item_id).get("pictures")`.
- **Hallazgo estructural importante:** este producto NO usa el sistema de variantes nativo de ML. Son **16 publicaciones (item_id) completamente separadas** — 4 colores (Gris/Beige/Marrón/Negro) × 4 talles (S/M/L/XL) — cada una con su propio permalink. Los talles del mismo color comparten las mismas 10 fotos, pero son avisos independientes: **cambiar la portada de un talle no cambia la de los otros 3 talles del mismo color.** Para arreglar un solo color hay que repetir el cambio en sus 4 publicaciones; los 4 colores completos son 16 ediciones manuales.
- **Recomendación dada, sin decisión final del usuario:** no tocar todavía. Pedir al diseñador la foto original sin el texto agregado (probablemente existe antes de pasar por Canva/Photoshop), en vez de forzar una de las infografías como portada. Alternativa si no hay foto limpia: probar igual con una publicación de prueba (talle L gris) a ver si ML la acepta, antes de replicar a las 16.
- **No se tocó nada en el listado real — es 100% pendiente de decisión y ejecución manual.**

### 1.5 Pendiente de arquitectura — SIN RESOLVER, quedó cortado
El usuario pidió que el propio agente ML (el pipeline automatizado de `main.py`/GitHub Actions), no Claude manualmente en el chat, sea el que "revise y analice" — y mencionó hacerlo "vía API con OpenAI" en vez de Claude. **Esto quedó sin aclarar antes de la interrupción para pedir este handoff.** Preguntas abiertas que había que resolver con el usuario:
1. ¿"OpenAI" es literal (reemplazar/agregar GPT en el agente) o fue un error de autocorrección por otra cosa?
2. Alcance: ¿solo el componente `agents/copywriter.py` (ya tiene soporte opcional a Claude vía `ANTHROPIC_API_KEY`, cae a un template fijo si no hay key — ver código abajo), o un analista nuevo más amplio que automatice el tipo de análisis manual que se hizo en esta sesión (desglose ROAS por producto, detección de saturación, revisión de fotos, decisiones semanales)?

`agents/copywriter.py` actual (para referencia rápida, no se tocó):
```python
class Copywriter:
    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(api_key=api_key) if (anthropic and api_key) else None
    ...
    def sugerir_ultimo_intento(self, titulo_actual, descripcion_actual):
        if self.client is None:
            return "<template fijo>"
        # si hay client, llama a claude-sonnet-4-6
```
**No se escribió código nuevo para esto. Falta retomar la conversación con el usuario para definir alcance antes de tocar nada.**

---

## 2. Estado de git — cambios sin commitear (heredados de sesiones previas, no tocados en esta)

```
modified:   agents/stock_agent.py
modified:   core/campaign_rules.py
modified:   core/executor.py
modified:   core/ml_client.py
modified:   main.py
modified:   memory/ml_tokens.json   (rota en cada uso, esperable que cambie)
modified:   test_escritura.py

untracked:  analisis_manual_output.json
untracked:  analisis_reporte_manual.py
untracked:  reportes_manuales/
```
No se commiteó nada en esta sesión — no se preguntó al usuario si quería hacerlo. `ml_tokens.json` va a seguir apareciendo modificado cada vez que se use la API (el refresh_token rota).

---

## 3. Próximos pasos sugeridos (en orden de lo que quedó abierto)

1. **Retomar con el usuario el punto de arquitectura (§1.5)** — es lo último que se estaba por definir cuando se pidió este handoff.
2. Decidir qué hacer con el Jogger Básico de testeo_medio (pausar vs. esperar) — §1.3.
3. Aplicar a mano en el panel de ML el ajuste de testeo_bajo (roas_target 2.8→3.0) si el usuario lo confirma — §1.3.
4. Preguntar qué es la campaña "prueba pantalon" (id 358374832) — §1.2.
5. Resolver el canal de soporte de ML para el ticket del 401 (§1.1) — el usuario no lo encontró, quedó sin enviar.
6. Fotos del Buzo Canguro: esperar definición del diseñador o decidir probar igual — §1.4.
7. Eventualmente commitear los cambios de código pendientes (§2), confirmando primero con el usuario.
