# Revisión de fotos — productos con peor CTR (2026-07-21)

Contexto: mismo día se corrigieron descripciones (ver `resumen_cambios.md`) de los 11 productos
con peor CTR real (`ctr_potencial.json`, ya filtrado por status activo). El usuario intentó hoy
cambiar fotos manualmente en el panel de ML pero no tiene las fotos nuevas listas — esta nota es
el criterio para decidir qué hacer con cada uno, priorizado por impresiones × CTR (plata en juego).

Fotos actuales y alternativas ya subidas: carpeta `fotos_revision/`.

## 1. Buzo Canguro Hombre Friza Hoodie (testeo_medio, 908k impr, CTR 0,12%)
**Acción inmediata, sin sesión de fotos nueva.** La foto #2 que YA está subida en la galería
(`buzo_canguro_alternativa_galeria.jpg`) es de frente, mirando a cámara, buen encuadre — mejor
candidata a portada que la actual (`buzo_canguro_actual.jpg`, mirando al costado, poco contacto visual).
⚠️ Tiene texto superpuesto ("MÁXIMA COMODIDAD...") — ML puede rechazar overlays de texto en la
foto de portada según categoría. Probar subirla como principal; si la rechaza, pedir esa misma
pose sin el texto.

## 2. Pantalón Gabardina Chupin Azul (oro_alto, 287k impr, CTR 0,18%)
## 3. Pantalón De Vestir Gabardina Corte Chino (oro_alto, 390k impr, CTR 0,11%)
**Necesitan sesión nueva.** Ninguna foto ya subida sirve de portada: todas son sin cabeza o con
overlay promocional. Ambas comparten el mismo problema de composición: plano completo caminando
lejos de cámara, pantalón oscuro sobre piso/fondo gris — bajísimo contraste y el producto ocupa
una fracción chica del cuadro cuando ML lo recorta a cuadrado para el buscador.
**Brief para la foto nueva:** encuadre de la cintura para abajo (no cuerpo entero de lejos),
modelo de frente o girando hacia cámara, fondo con contraste real contra el color del pantalón
(evitar gris sobre gris/asfalto), el pantalón debe ocupar más de la mitad del cuadro.

## 4. Campera Guata Gris (plata_medio, 2,4M impr — la mayor exposición de la cuenta, CTR 0,25%)
La foto actual ya es de frente, bien iluminada, sin problema evidente de composición.
[POSIBLE, no CONFIRMADO] El CTR bajo con tanta impresión sugiere que el problema no es la foto sino
la categoría (camperas inflables básicas, muy competida) o precio. No priorizar sesión de fotos
nueva acá todavía — antes revisar precio vs. competencia directa.

## 5. Pack X3 Remeras Básicas (oro_alto, 57k impr, CTR 0,07% — el peor de toda la cuenta)
Foto de estudio prolija, buena luz, muestra los 3 colores. Igual que el caso anterior:
[POSIBLE] el problema no es la foto. Con esta imagen y el peor CTR de la cuenta, antes de invertir
en fotos nuevas conviene revisar precio y también si el recorte cuadrado del buscador está
cortando a los modelos de los costados (composición muy ancha, 3 personas en fila).

## Resumen — qué hacer ahora
| Producto | Acción | Costo |
|---|---|---|
| Buzo Canguro Hoodie | Reordenar galería (probar foto #2 como portada) | $0, hoy mismo |
| Pantalón Gabardina Chupin | Sesión nueva con el brief de arriba | Requiere foto nueva |
| Pantalón De Vestir Gabardina | Sesión nueva con el mismo brief (comparten problema) | Requiere foto nueva |
| Campera Guata | No tocar foto todavía — revisar precio primero | — |
| Pack X3 Remeras | No tocar foto todavía — revisar precio/recorte primero | — |
