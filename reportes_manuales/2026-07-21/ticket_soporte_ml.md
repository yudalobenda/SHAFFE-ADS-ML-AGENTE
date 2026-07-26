# Ticket de soporte — Mercado Libre Developers

**Asunto:** Permiso de escritura habilitado en la app pero la API de Product Ads sigue rechazando escritura (401)

## Datos de la cuenta / app
- Vendedor: SHAFFECO. (user_id `262443439`)
- Aplicación: "openclaw" / "clawleon" (client_id `2900560376757443`)
- Advertiser_id de Ads: `21757`, site_id: `MLA`

## Qué pasó
1. El permiso funcional **"Publicidad de un producto"** de la aplicación estaba en **"Sin acceso"**. Lo cambié a **"Lectura y escritura"** en el panel de Developers.
2. Volví a autorizar la aplicación (flujo OAuth completo, `grant_type=authorization_code`) para obtener un token nuevo.
3. El token nuevo confirma el scope correcto: `urn:ml:mktp:ads:/read-write` aparece en la respuesta del intercambio de token.
4. La **lectura funciona perfecto** con este token: `GET` a `/marketplace/advertising/MLA/product_ads/campaigns/{campaign_id}` devuelve `200` con los datos reales de la campaña (budget, roas_target, acos_target, status).
5. Pero cualquier intento de **escritura sigue rechazado**, más de 24hs después del cambio de permiso y la reautorización.

## Error exacto que recibo
`PUT` a `https://api.mercadolibre.com/marketplace/advertising/MLA/product_ads/campaigns/357700013` con body `{"budget": 50000.0, "roas_target": 2.8}` (mismos valores que ya tiene la campaña, no es un cambio real):

```
Status: 401
{
  "message": "User does not have permission to write.",
  "error": "mclics.campaigns.exceptions.UnauthorizedException",
  "status": 401,
  "cause": "java.lang.Throwable: User does not have permission to write."
}
```

Probé variantes de headers (`Api-Version: 1`, `Api-Version: 2`, `x-format-new: true`) sin cambios en el resultado.

También probé `PUT` a `https://api.mercadolibre.com/marketplace/advertising/MLA/product_ads/ads/{item_id}` (para pausar/activar una publicación puntual dentro de una campaña) y ahí el resultado es distinto: **503 Service Unavailable**, de forma consistente en varios intentos a lo largo del día.

## Lo que necesito saber
- ¿El permiso "Publicidad de un producto: Lectura y escritura" en el panel de Developers es suficiente para escribir en Product Ads, o hace falta habilitar algo adicional (aprobación específica, certificación, o un toggle separado dentro del panel de Mercado Ads/vendedores, distinto del panel de Developers)?
- Si hace falta una aprobación adicional de parte de Mercado Libre para escritura en Product Ads vía API, ¿cómo se solicita?
- ¿El error 503 en `/product_ads/ads/{item_id}` (PUT) es un problema conocido de ese endpoint, o estoy usando una ruta incorrecta?

Gracias.
