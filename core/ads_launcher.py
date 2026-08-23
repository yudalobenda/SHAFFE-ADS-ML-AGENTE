"""Intenta activar en Ads una publicación 100% nueva que el ERP ya publicó en
ML (ver backend/routes/productLaunch.js). Corre desde main.py:modo_listen(),
separado del publish (que vive en el ERP) — un fallo acá nunca puede dejar la
publicación de ML en un estado raro, porque publish y Ads no comparten
transacción ni proceso. Ver plan en E:\\AGENTES CLAUDE\\AGENTE CIOMA.

Nota técnica (por qué NO se usa el mecanismo de ad_group_id de
project_ml_ads_adgroups en memoria): ese mecanismo (PUT
.../product_ads/ad_groups/{ad_group_id}) sirve para MOVER un ad_group que ya
existe entre campañas (lo usa el flujo de mover_tier). Un item recién
publicado, que nunca estuvo en Ads, todavía no tiene ad_group_id — necesita
que se lo agregue por primera vez a una campaña. Por eso acá se usa
`add_item_to_campaign` (existe en core/ml_client.py desde antes, sin
verificar contra la API real). Los dos caminos están bloqueados hoy por el
mismo 401 real confirmado en vivo el 06/08 (ver memoria
project_ml_ads_adgroups) — cuando ML habilite el permiso de escritura,
conviene reverificar cuál endpoint es el efectivamente vigente para dar de
alta un item nuevo, no asumir que éste sigue siendo el correcto.
"""
from __future__ import annotations

import core.campaign_rules as reglas
from core.ml_client import MLClient, MLClientError


def activar_item_en_testeo(
    ml: MLClient, advertiser_id: str, campaign_ids: dict, item_id: str, precio: float | None
) -> dict:
    """Intenta agregar un item nuevo a la campaña de testeo que le corresponda
    por ticket (mismo criterio que el resto del sistema, ver campaign_rules).
    Nunca levanta excepción — devuelve {"ok": True} o {"ok": False, "motivo",
    "detalle"} para que el caller siga con el resto de la cola aunque uno falle."""
    ticket = reglas.clasificar_ticket(precio) if precio else "medio"
    nombre_campania = reglas.nombre_campania("testeo", ticket)
    campaign_id = campaign_ids.get("campañas", {}).get(nombre_campania)
    if not campaign_id:
        return {"ok": False, "motivo": "sin_campania", "detalle": f"No hay campaign_id para '{nombre_campania}' en campaign_ids.json"}
    try:
        ml.add_item_to_campaign(advertiser_id, campaign_id, item_id)
        return {"ok": True, "campania": nombre_campania}
    except MLClientError as e:
        motivo = "401" if "401" in str(e) else "error"
        return {"ok": False, "motivo": motivo, "detalle": str(e)}
