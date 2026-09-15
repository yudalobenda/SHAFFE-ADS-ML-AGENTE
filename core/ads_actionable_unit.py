"""ADS_ACTIONABLE_UNIT: la unidad minima que Mercado Ads realmente permite
mover/pausar/activar. Existe porque SKU padre, MLA, variante, user_product,
ad_group y "unidad accionable Ads" NO son lo mismo, y una recomendacion de
Ads generada sobre el nivel equivocado puede pedir una accion imposible.

Verificado EN VIVO contra la cuenta real de SHAFFE (advertiser_id=21757,
site MLA) el 2026-08-28 con core/ml_client.py (get_ad, get_ad_group,
get_ad_groups) - ver tests/fixtures/actionable_unit_real_cases.json para los
payloads reales capturados:

- Mercado Ads modela la unidad movible como `ad_group`, no como item_id.
  Cada ad_group trae `ad_group_type`: "FAMILY" o "ITEM".
- ad_group_type=FAMILY: agrupa TODAS las variantes (todos los item_id/MLA)
  del mismo `family_id` de ML bajo un unico ad_group_id. Confirmado con
  "Camisa Hombre Elastizada" (family_id 5835601663700178, ad_group_id
  2723481184: los 6 item_id de muestra devolvieron el MISMO ad_group_id) y
  "Pantalon Gabardina" (family_id 4816596800258335, ad_group_id 1248435949,
  mismo resultado). El campo `ad_group_external_id` del ad_group coincide
  exactamente con el `family_id` real del item cuando el tipo es FAMILY.
- ad_group_type=ITEM: publicaciones sin variantes (family de 1 en ML, o sea
  sin guia de talles). El ad_group es a nivel de esa unica publicacion.
  `ad_group_external_id` es entonces el item_id mismo, no un family_id.
  Confirmado con el caso real 1N019: MLA1420436886 (ad_group_id 204050174,
  campaign_id 357702416) y MLA1403338277 (ad_group_id 105126942, campaign_id
  359130777) son DOS ad_groups ITEM totalmente independientes -- ni
  comparten ad_group_id ni campaign_id -- aunque ambas remeras sean la misma
  familia comercial "1N019" para el negocio. Una recomendacion sobre una NO
  puede aplicarse a la otra.
- get_ad_group(ad_group_id) puede devolver campaign_id=0 para un ad_group
  FAMILY recien creado sin campana asignada todavia (visto en vivo: 3 de los
  451 ad_groups actuales, todos creados 2026-08-27). get_ad(item_id) SI trae
  el campaign_id real de forma consistente. Por eso el discovery real usa
  get_ad(item_id) como fuente de campaign_id, no get_ad_group().
- Cantidad total de ad_groups: 451 el 2026-08-28 (NO 442 -- ese numero era
  un snapshot puntual del 05-06/08 documentado en ml_client.py; ML sigue
  creando ad_groups automaticamente a medida que se publican productos
  nuevos). Nunca hardcodear este numero: siempre recontar via get_ad_groups.

Regla dura que este modulo existe para hacer imposible de violar:
UNA RECOMENDACION DE ADS SOLO PUEDE APUNTAR A UN ActionableUnit COMPLETO.
Si ad_group_type=FAMILY, la unidad incluye TODOS los affected_mlas -- no hay
forma de mover/pausar/activar una sola variante suelta dentro de esa familia
via el mecanismo de ad_group (mover el grupo mueve a todas las variantes
juntas). Los datos a nivel variante individual (CTR, conversion, stock)
siguen sirviendo para DIAGNOSTICAR dentro de la unidad, nunca para generar
una accion que la API no puede ejecutar a ese nivel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

ACTION_SCOPE_GROUP = "GROUP"
ACTION_SCOPE_SINGLE = "SINGLE"
ACTION_SCOPE_UNKNOWN = "UNKNOWN"

AD_GROUP_TYPE_FAMILY = "FAMILY"
AD_GROUP_TYPE_ITEM = "ITEM"


class ActionableUnitError(Exception):
    """Se levanta cuando el codigo intenta tratar algo por debajo de
    ADS_ACTIONABLE_UNIT (un item suelto dentro de un grupo FAMILY, o un
    ad_group con integridad no verificada) como si fuera accionable."""


@dataclass(frozen=True)
class VariantRef:
    item_id: str
    sku_code: str | None = None
    talle: str | None = None
    color: str | None = None
    user_product_id: str | None = None


@dataclass(frozen=True)
class ActionableUnit:
    actionable_unit_id: str
    ad_group_id: str
    ad_group_type: str                 # FAMILY | ITEM | (otro valor no documentado por ML)
    ad_group_external_id: str          # family_id si FAMILY, item_id si ITEM
    campaign_id: str | None
    action_scope: str                  # GROUP | SINGLE | UNKNOWN
    affected_mlas: tuple[str, ...]
    affected_variants: tuple[VariantRef, ...]
    affected_user_products: tuple[str, ...]
    parent_skus: tuple[str, ...]
    source: str
    confidence: str                    # high | medium | low
    verified_at: str
    integrity_ok: bool
    integrity_issue: str | None = None
    evidence: dict = field(default_factory=dict)

    def to_api(self) -> dict:
        return {
            "actionableUnitId": self.actionable_unit_id,
            "adGroupId": self.ad_group_id,
            "adGroupType": self.ad_group_type,
            "adGroupExternalId": self.ad_group_external_id,
            "campaignId": self.campaign_id,
            "actionScope": self.action_scope,
            "affectedMlas": list(self.affected_mlas),
            "affectedVariants": [
                {"itemId": v.item_id, "skuCode": v.sku_code, "talle": v.talle,
                 "color": v.color, "userProductId": v.user_product_id}
                for v in self.affected_variants
            ],
            "affectedUserProducts": list(self.affected_user_products),
            "parentSkus": list(self.parent_skus),
            "source": self.source,
            "confidence": self.confidence,
            "verifiedAt": self.verified_at,
            "integrityOk": self.integrity_ok,
            "integrityIssue": self.integrity_issue,
            "evidence": self.evidence,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_actionable_unit(
    ad_group: dict,
    *,
    family_items: Iterable[dict] | None = None,
    sku_by_item: dict[str, str] | None = None,
    user_product_by_item: dict[str, str] | None = None,
    campaign_id_override: str | None = None,
    verified_at: str | None = None,
    source: str = "ml_ad_group_api",
) -> ActionableUnit:
    """Construye la ActionableUnit a partir de payloads YA obtenidos (esta
    funcion no pega a la red -- separa calculo de I/O para poder testearla
    con fixtures reales sin credenciales). `ad_group` es el dict devuelto por
    MLClient.get_ad_group / cada resultado de get_ad_groups.

    family_items: catalogo de items (payload de la API de Items estandar)
    que comparten el mismo family_id, SOLO necesario cuando
    ad_group_type=FAMILY -- si no se provee, se cae a
    confidence="low"/integrity_issue explicito en vez de inventar la lista.
    """
    ad_group_id = str(ad_group.get("id"))
    ad_group_type = ad_group.get("ad_group_type")
    ad_group_external_id = str(ad_group.get("ad_group_external_id") or "")
    campaign_id = campaign_id_override
    if campaign_id is None:
        raw_campaign = ad_group.get("campaign_id")
        campaign_id = str(raw_campaign) if raw_campaign not in (None, 0) else None
    verified_at = verified_at or _now_iso()
    sku_by_item = sku_by_item or {}
    user_product_by_item = user_product_by_item or {}

    if ad_group_type == AD_GROUP_TYPE_FAMILY:
        items = list(family_items or [])
        item_ids = tuple(str(item.get("id")) for item in items if item.get("id"))
        mismatched = [
            str(item.get("id")) for item in items
            if str(item.get("family_id") or "") != ad_group_external_id
        ]
        integrity_ok = bool(item_ids) and not mismatched
        integrity_issue = None
        if not item_ids:
            integrity_issue = "FAMILY_ITEMS_NOT_PROVIDED"
        elif mismatched:
            integrity_issue = f"ITEMS_WITH_MISMATCHED_FAMILY_ID:{','.join(mismatched)}"
        confidence = "high" if integrity_ok else "low"
        variants = tuple(
            VariantRef(
                item_id=str(item.get("id")),
                sku_code=sku_by_item.get(str(item.get("id"))),
                talle=_attr(item, "SIZE") or _attr(item, "TALLE"),
                color=_attr(item, "COLOR"),
                user_product_id=user_product_by_item.get(str(item.get("id"))),
            )
            for item in items
        )
        parent_skus = tuple(sorted({v.sku_code for v in variants if v.sku_code}))
        return ActionableUnit(
            actionable_unit_id=f"ad_group:{ad_group_id}",
            ad_group_id=ad_group_id,
            ad_group_type=ad_group_type,
            ad_group_external_id=ad_group_external_id,
            campaign_id=campaign_id,
            action_scope=ACTION_SCOPE_GROUP if len(item_ids) > 1 else (
                ACTION_SCOPE_SINGLE if item_ids else ACTION_SCOPE_UNKNOWN
            ),
            affected_mlas=item_ids,
            affected_variants=variants,
            affected_user_products=tuple(sorted(set(user_product_by_item.values()))),
            parent_skus=parent_skus,
            source=source,
            confidence=confidence,
            verified_at=verified_at,
            integrity_ok=integrity_ok,
            integrity_issue=integrity_issue,
            evidence={"ad_group": ad_group, "family_item_count": len(item_ids)},
        )

    if ad_group_type == AD_GROUP_TYPE_ITEM:
        item_id = ad_group_external_id or None
        integrity_ok = bool(item_id)
        sku_code = sku_by_item.get(item_id) if item_id else None
        variants = (VariantRef(item_id=item_id, sku_code=sku_code),) if item_id else ()
        return ActionableUnit(
            actionable_unit_id=f"ad_group:{ad_group_id}",
            ad_group_id=ad_group_id,
            ad_group_type=ad_group_type,
            ad_group_external_id=ad_group_external_id,
            campaign_id=campaign_id,
            action_scope=ACTION_SCOPE_SINGLE if integrity_ok else ACTION_SCOPE_UNKNOWN,
            affected_mlas=(item_id,) if item_id else (),
            affected_variants=variants,
            affected_user_products=tuple(sorted(set(user_product_by_item.values()))),
            parent_skus=tuple(sorted({sku_code})) if sku_code else (),
            source=source,
            confidence="high" if integrity_ok else "low",
            verified_at=verified_at,
            integrity_ok=integrity_ok,
            integrity_issue=None if integrity_ok else "ITEM_AD_GROUP_WITHOUT_EXTERNAL_ID",
            evidence={"ad_group": ad_group},
        )

    # Tipo de ad_group no documentado por ML: nunca asumimos su alcance.
    return ActionableUnit(
        actionable_unit_id=f"ad_group:{ad_group_id}",
        ad_group_id=ad_group_id,
        ad_group_type=str(ad_group_type),
        ad_group_external_id=ad_group_external_id,
        campaign_id=campaign_id,
        action_scope=ACTION_SCOPE_UNKNOWN,
        affected_mlas=(),
        affected_variants=(),
        affected_user_products=(),
        parent_skus=(),
        source=source,
        confidence="low",
        verified_at=verified_at,
        integrity_ok=False,
        integrity_issue=f"UNKNOWN_AD_GROUP_TYPE:{ad_group_type}",
        evidence={"ad_group": ad_group},
    )


def _attr(item: dict, attr_id: str) -> str | None:
    for attr in item.get("attributes") or []:
        if str(attr.get("id") or "").upper() == attr_id:
            return attr.get("value_name")
    return None


def discover_actionable_unit_for_item(
    ml,
    site_id: str,
    item_id: str,
    *,
    family_catalog_by_family_id: dict[str, list[dict]] | None = None,
    sku_by_item: dict[str, str] | None = None,
    user_product_by_item: dict[str, str] | None = None,
) -> ActionableUnit:
    """I/O real (solo lectura): resuelve la ActionableUnit de un item_id
    pegandole a la API real de Ads. `family_catalog_by_family_id` debe venir
    pre-armado por el caller (agrupar el catalogo activo del seller por
    family_id, como ya hace backend/routes/publicaciones.js en el ERP) --
    este modulo no vuelve a traer el catalogo completo por cada item para no
    encarecer el discovery de N items a N llamadas de catalogo completo.

    campaign_id se toma de get_ad (item), no de get_ad_group: verificado en
    vivo que get_ad_group puede devolver campaign_id=0 para un ad_group
    FAMILY recien creado sin campana asignada, mientras que get_ad(item_id)
    siempre trae el campaign_id real."""
    ad = ml.get_ad(site_id, item_id)
    ad_group_id = ad.get("ad_group_id")
    if ad_group_id is None:
        raise ActionableUnitError(f"{item_id} no tiene ad_group_id -- probablemente no esta en Ads.")
    ad_group = ml.get_ad_group(site_id, str(ad_group_id))
    family_items = None
    if ad_group.get("ad_group_type") == AD_GROUP_TYPE_FAMILY:
        family_id = str(ad_group.get("ad_group_external_id") or "")
        family_items = (family_catalog_by_family_id or {}).get(family_id)
    campaign_id = str(ad.get("campaign_id")) if ad.get("campaign_id") not in (None, 0) else None
    return build_actionable_unit(
        ad_group,
        family_items=family_items,
        sku_by_item=sku_by_item,
        user_product_by_item=user_product_by_item,
        campaign_id_override=campaign_id,
        source="ml_ad_group_api+ml_ad_api",
    )


def assert_target_is_actionable(unit: ActionableUnit, requested_item_id: str) -> None:
    """Guardrail central: levanta ActionableUnitError si alguien intenta
    generar una accion (MOVE/PAUSE/ACTIVATE) apuntando a un item_id suelto
    que en realidad pertenece a un ad_group GROUP con mas miembros. La unica
    forma valida de accionar sobre esa variante es a traves de la unidad
    completa (unit.actionable_unit_id), nunca sobre requested_item_id solo."""
    if not unit.integrity_ok:
        raise ActionableUnitError(
            f"ActionableUnit {unit.actionable_unit_id} sin integridad verificada "
            f"({unit.integrity_issue}) -- no se puede generar una accion sobre ella."
        )
    if requested_item_id not in unit.affected_mlas:
        raise ActionableUnitError(
            f"{requested_item_id} no pertenece a la ActionableUnit {unit.actionable_unit_id} "
            f"(affected_mlas={unit.affected_mlas})."
        )
    if unit.action_scope == ACTION_SCOPE_GROUP and len(unit.affected_mlas) > 1:
        # No es un error: es exactamente la regla de negocio. Se deja
        # explicito para que el caller (Decision Engine) nunca reciba esto
        # como una sorpresa silenciosa -- mover implica mover a todo el grupo.
        return
