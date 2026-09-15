"""Decision Engine de CIOMA Ads: unica autoridad logica que convierte
metricas reales de una ADS_ACTIONABLE_UNIT en UNA recomendacion accionable.

Reemplaza (para las unidades ya migradas a la estructura nueva) la logica
vieja de campaign_rules.evaluar_movimiento_tier, que sigue viva y sin tocar
para las campanas historicas (ORO/PLATA/TESTEO) todavia no migradas -- ver
el docstring de campaign_rules.py. Este motor apunta a los 6 estados nuevos:
MOTORES-ESCALA, POTENCIALES-TEST, RENTABLES-EFICIENCIA, RECUPERAR CAPITAL,
CORREGIR, FUERA ADS.

IMPORTANTE: los umbrales de abajo (ROAS_MOTORES, ROAS_RENTABLE, etc.) son
una HIPOTESIS INICIAL heredada de los umbrales ya validados en
campaign_rules.py (ROAS_PLATA_A_ORO=6.5, ROAS_TESTEO_A_PLATA=3.5,
GASTO_MIN_EVALUAR=2000), NO una calibracion nueva contra historico real --
eso queda pendiente (backtestear por precio/CPC/conversion/margen/categoria,
como pide el proyecto). Por eso formula_version se etiqueta explicitamente
"-hipotesis": cualquier decision automatica que dependa de este numero debe
poder rastrear que todavia no fue validada estadisticamente.

Toda Recommendation apunta a un actionable_unit_id (ver
core/ads_actionable_unit.py) -- nunca a un item_id suelto. Este modulo no
pega a la red: recibe metricas ya calculadas (ver
core/decision_context.py para como se arman con datos reales)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from core.ads_actionable_unit import ACTION_SCOPE_GROUP, ActionableUnit

FORMULA_VERSION = "decision-engine-v1-hipotesis"

# --- Estados/campañas nuevas (nombres tal cual existen HOY en la cuenta real,
# confirmados en vivo 2026-08-28: MOTORES – ESCALA id 359121717 active,
# POTENCIALES – TEST id 359130777 active, CORREGIR id 359121756 paused,
# RENTABLES – EFICIENCIA id 359147661 paused, RECUPERAR CAPITAL id 359147625
# paused. "FUERA ADS" es un estado, no una campaña de Ads.) ---
CAMPAIGN_MOTORES = "MOTORES – ESCALA"
CAMPAIGN_POTENCIALES = "POTENCIALES – TEST"
CAMPAIGN_RENTABLES = "RENTABLES – EFICIENCIA"
CAMPAIGN_RECUPERAR = "RECUPERAR CAPITAL"
CAMPAIGN_CORREGIR = "CORREGIR"
ESTADO_FUERA_ADS = "FUERA ADS"

ACTIONS = (
    "KEEP_TESTING", "MOVE_TO_MOTORES", "MOVE_TO_RENTABLES", "MOVE_TO_CORREGIR",
    "MOVE_TO_RECUPERAR", "REMOVE_FROM_ADS", "NO_ACTION", "BLOCKED", "REPLENISH_BEFORE_SCALE",
)

# --- Umbrales (hipotesis inicial, heredados de core/campaign_rules.py) ---
GASTO_MIN_EVALUAR = 2_000          # ARS 30d — por debajo, ML no dio presupuesto real
IMPRESIONES_MIN_EVALUAR = 500
ROAS_MOTORES = 6.5                 # heredado de ROAS_PLATA_A_ORO -- FALLBACK cuando no hay margen real (ver abajo)
ROAS_RENTABLE = 4.0                # heredado de ROAS_TESTEO_A_PLATA -- FALLBACK cuando no hay margen real
# Un ROAS que apenas empata el break-even (roas_break_even, ver
# core/decision_context.compute_margin_break_even) no deja ganancia real
# después de Ads -- exigimos superarlo con margen de sobra. RENTABLE pide
# 15% arriba del empate; MOTORES (escalar de verdad) pide bastante más,
# porque escalar significa apostar más plata a ese margen.
MARGEN_SEGURIDAD_SOBRE_BREAKEVEN = 1.15
MARGEN_SEGURIDAD_MOTORES = 1.75
UNITS_MIN_VOLUMEN_ESCALA = 3       # ventas Ads 30d minimas para hablar de "volumen", no solo ROAS puntual
STOCK_CRITICO_UNIDADES = 5         # heredado de STOCK_BAJO_UNIDADES
STOCK_SOBRANTE_COBERTURA_DIAS = 120  # cobertura muy larga sin rotación -> capital inmovilizado
CLICKS_MIN_DIAGNOSTICO = 30
CTR_ALERTA_MIN = 0.02
CVR_ALERTA_MIN = 0.01


@dataclass(frozen=True)
class Recommendation:
    actionable_unit_id: str
    affected_mlas: tuple[str, ...]
    affected_variants: tuple
    current_campaign: str | None
    recommended_action: str
    recommended_campaign: str | None
    reason: str
    evidence: dict
    economic_confidence: str
    sample_confidence: str
    stock_confidence: str
    expected_impact: str
    risk: str
    stop_loss: str | None
    review_at: str
    formula_version: str
    created_at: str

    def to_legacy_accion(self) -> dict | None:
        """Traduce a la forma `accion` que ya consume
        core/erp_client.py:push_ads_queue -- reutiliza la cola existente en
        vez de crear un sistema paralelo. Devuelve None para acciones que no
        deben generar una fila en ads_queue (KEEP_TESTING/NO_ACTION/BLOCKED/
        REPLENISH_BEFORE_SCALE -- esa ultima es una sugerencia de compra, no
        una accion de Ads, y se conecta aparte a purchase_suggestions)."""
        if self.recommended_action not in ("MOVE_TO_MOTORES", "MOVE_TO_RENTABLES",
                                            "MOVE_TO_CORREGIR", "MOVE_TO_RECUPERAR", "REMOVE_FROM_ADS"):
            return None
        base = {
            "item_ids": list(self.affected_mlas),
            "family_name": self.evidence.get("family_name") or self.actionable_unit_id,
            "motivo": self.reason,
            "roas_reciente": self.evidence.get("roas"),
            "_recommendation": {
                "actionableUnitId": self.actionable_unit_id,
                "affectedVariants": [
                    {"itemId": v.item_id, "skuCode": v.sku_code} for v in self.affected_variants
                ] if self.affected_variants else [],
                "currentCampaign": self.current_campaign,
                "recommendedState": self.recommended_action,
                "evidence": self.evidence,
                "economicConfidence": self.economic_confidence,
                "sampleConfidence": self.sample_confidence,
                "stockConfidence": self.stock_confidence,
                "expectedImpact": self.expected_impact,
                "risk": self.risk,
                "stopLoss": self.stop_loss,
                "reviewAt": self.review_at,
                "formulaVersion": self.formula_version,
            },
        }
        if self.recommended_action == "REMOVE_FROM_ADS":
            return {**base, "tipo": "pausar"}
        destino = {
            "MOVE_TO_MOTORES": CAMPAIGN_MOTORES,
            "MOVE_TO_RENTABLES": CAMPAIGN_RENTABLES,
            "MOVE_TO_CORREGIR": CAMPAIGN_CORREGIR,
            "MOVE_TO_RECUPERAR": CAMPAIGN_RECUPERAR,
        }[self.recommended_action]
        return {**base, "tipo": "mover_tier", "campania_origen": self.current_campaign, "campania_destino": destino}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _review_at(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def decide(unit: ActionableUnit, context: dict) -> Recommendation:
    """context (todo opcional salvo lo marcado, faltante=None -- nunca 0):
    roas, acos, tacos (float|None)
    spend_30d, ads_revenue_30d, total_revenue_30d (float|None, ARS)
    prints_30d, clicks_30d (int|None)
    units_ads_30d, units_total_30d (int|None)
    current_campaign (str|None) -- nombre de campaña actual
    economic_confidence (str) 'high'|'medium'|'low'|'blocked' -- de sku_daily_economics
    stock_total (int|None), coverage_days (float|None)
    target_price_result (dict|None) -- salida de
        core.target_price.resolve_target_price_for_code, ya como dict
        (TargetPriceResult.__dict__); si está presente y found=True, se
        suma como palanca de corrección en el reason de CORREGIR/REMOVE.
    """
    evidence = {**context, "ad_group_id": unit.ad_group_id, "ad_group_type": unit.ad_group_type}

    if not unit.integrity_ok:
        return _blocked(unit, evidence, f"ActionableUnit sin integridad verificada: {unit.integrity_issue}")

    spend = context.get("spend_30d")
    prints = context.get("prints_30d")
    tiene_presupuesto_real = (spend or 0) >= GASTO_MIN_EVALUAR or (prints or 0) >= IMPRESIONES_MIN_EVALUAR
    sample_confidence = "high" if tiene_presupuesto_real else "insufficient"

    economic_confidence = context.get("economic_confidence") or "low"
    if economic_confidence == "blocked":
        return _blocked(unit, evidence, "Economía bloqueada: falta un componente crítico (IVA/shipping) sin reconciliar.")

    stock_total = context.get("stock_total")
    stock_confidence = "high" if stock_total is not None else "low"
    stock_critico = stock_total is not None and stock_total <= STOCK_CRITICO_UNIDADES
    coverage_days = context.get("coverage_days")
    stock_sobrante = coverage_days is not None and coverage_days >= STOCK_SOBRANTE_COBERTURA_DIAS

    if not tiene_presupuesto_real:
        return Recommendation(
            actionable_unit_id=unit.actionable_unit_id, affected_mlas=unit.affected_mlas,
            affected_variants=unit.affected_variants, current_campaign=context.get("current_campaign"),
            recommended_action="KEEP_TESTING", recommended_campaign=None,
            reason="Sin presupuesto real asignado todavía (gasto/impresiones por debajo del mínimo) — no hay evidencia suficiente para decidir.",
            evidence=evidence, economic_confidence=economic_confidence, sample_confidence=sample_confidence,
            stock_confidence=stock_confidence, expected_impact="ninguno (mantener en observación)",
            risk="bajo", stop_loss=None, review_at=_review_at(7),
            formula_version=FORMULA_VERSION, created_at=_now_iso(),
        )

    roas = context.get("roas")
    units_ads = context.get("units_ads_30d") or 0

    # Umbral real: si conocemos el margen bruto de la unidad, un ROAS "alto"
    # en términos absolutos puede seguir estando por debajo de lo que hace
    # falta para ganar plata con ESE margen puntual (ver ejemplo: ROAS 10x
    # con margen bruto 8% tiene break-even en 12,5x — un ROAS de 10x ahí es
    # pérdida neta, no importa lo bien que se vea aislado). Sin margen real
    # conocido, caemos al umbral genérico fijo como fallback conservador,
    # dejándolo explícito en el motivo para no esconder que es una
    # aproximación menos confiable.
    roas_break_even = context.get("roas_break_even")
    if roas_break_even is not None:
        umbral_rentable = max(ROAS_RENTABLE, roas_break_even * MARGEN_SEGURIDAD_SOBRE_BREAKEVEN)
        umbral_motores = max(ROAS_MOTORES, roas_break_even * MARGEN_SEGURIDAD_MOTORES)
        basis = "margen neto pre Ads conciliado" if context.get("margin_basis") == "settlement_mp_pre_ads" else "margen informado"
        fuente_umbral = f"break-even real de {basis} ({roas_break_even:.1f}x con margen {context.get('margin_pct', 0) * 100:.0f}%)"
    else:
        umbral_rentable, umbral_motores = ROAS_RENTABLE, ROAS_MOTORES
        fuente_umbral = "umbral genérico (sin margen real conocido para esta unidad)"
    evidence["umbral_rentable_usado"] = umbral_rentable
    evidence["umbral_motores_usado"] = umbral_motores
    evidence["fuente_umbral"] = fuente_umbral

    if roas is not None and roas >= umbral_motores and units_ads >= UNITS_MIN_VOLUMEN_ESCALA:
        if stock_critico:
            return Recommendation(
                actionable_unit_id=unit.actionable_unit_id, affected_mlas=unit.affected_mlas,
                affected_variants=unit.affected_variants, current_campaign=context.get("current_campaign"),
                recommended_action="REPLENISH_BEFORE_SCALE", recommended_campaign=None,
                reason=f"ROAS {roas:.1f}x con volumen real ({units_ads} unidades/30d) pero stock crítico ({stock_total} u) — reponer antes de escalar Ads.",
                evidence=evidence, economic_confidence=economic_confidence, sample_confidence=sample_confidence,
                stock_confidence=stock_confidence, expected_impact="alto si se repone; escalar ahora arriesga quiebre de stock",
                risk="medio", stop_loss="si no hay reposición en 15 días, revisar si sigue en Ads",
                review_at=_review_at(7), formula_version=FORMULA_VERSION, created_at=_now_iso(),
            )
        return Recommendation(
            actionable_unit_id=unit.actionable_unit_id, affected_mlas=unit.affected_mlas,
            affected_variants=unit.affected_variants, current_campaign=context.get("current_campaign"),
            recommended_action="MOVE_TO_MOTORES", recommended_campaign=CAMPAIGN_MOTORES,
            reason=f"ROAS {roas:.1f}x sostenido con volumen real ({units_ads} unidades/30d), supera el umbral de escala ({umbral_motores:.1f}x, {fuente_umbral}) y stock/cobertura compatibles.",
            evidence=evidence, economic_confidence=economic_confidence, sample_confidence=sample_confidence,
            stock_confidence=stock_confidence, expected_impact="escalar presupuesto sin perder eficiencia",
            risk="bajo", stop_loss=f"si ROAS cae sostenido debajo de {umbral_rentable:.1f}x, degradar a {CAMPAIGN_RENTABLES}",
            review_at=_review_at(15), formula_version=FORMULA_VERSION, created_at=_now_iso(),
        )

    if roas is not None and roas >= umbral_rentable:
        if units_ads < UNITS_MIN_VOLUMEN_ESCALA:
            motivo_sin_escala = f"volumen insuficiente ({units_ads} unidades/30d < {UNITS_MIN_VOLUMEN_ESCALA})"
        elif roas_break_even is not None:
            motivo_sin_escala = f"no llega al margen de seguridad sobre su propio break-even ({roas:.1f}x < {umbral_motores:.1f}x necesarios, {fuente_umbral})"
        else:
            motivo_sin_escala = f"ROAS no alcanza el umbral de escala ({roas:.1f}x < {umbral_motores:.1f}x)"
        return Recommendation(
            actionable_unit_id=unit.actionable_unit_id, affected_mlas=unit.affected_mlas,
            affected_variants=unit.affected_variants, current_campaign=context.get("current_campaign"),
            recommended_action="MOVE_TO_RENTABLES", recommended_campaign=CAMPAIGN_RENTABLES,
            reason=f"ROAS {roas:.1f}x rentable ({fuente_umbral}) pero {motivo_sin_escala} — mantener eficiencia.",
            evidence=evidence, economic_confidence=economic_confidence, sample_confidence=sample_confidence,
            stock_confidence=stock_confidence, expected_impact="mantener rentabilidad actual",
            risk="bajo", stop_loss=f"si ROAS cae sostenido debajo de {umbral_rentable:.1f}x, mover a {CAMPAIGN_CORREGIR}",
            review_at=_review_at(10), formula_version=FORMULA_VERSION, created_at=_now_iso(),
        )

    clicks = context.get("clicks_30d") or 0
    ctr = (clicks / prints) if prints else None
    cvr = (units_ads / clicks) if clicks else None
    hay_trafico_diagnosticable = clicks >= CLICKS_MIN_DIAGNOSTICO or (prints or 0) >= IMPRESIONES_MIN_EVALUAR
    señal_corregible = hay_trafico_diagnosticable and (
        (ctr is not None and ctr < CTR_ALERTA_MIN) or (cvr is not None and cvr < CVR_ALERTA_MIN)
    )
    if señal_corregible:
        motivo_ctr = f"CTR {ctr*100:.1f}% bajo tráfico real" if ctr is not None and ctr < CTR_ALERTA_MIN else None
        motivo_cvr = f"CVR {cvr*100:.1f}% bajo con clicks reales" if cvr is not None and cvr < CVR_ALERTA_MIN else None
        return Recommendation(
            actionable_unit_id=unit.actionable_unit_id, affected_mlas=unit.affected_mlas,
            affected_variants=unit.affected_variants, current_campaign=context.get("current_campaign"),
            recommended_action="MOVE_TO_CORREGIR", recommended_campaign=CAMPAIGN_CORREGIR,
            reason=f"Hay tráfico real pero {' y '.join(x for x in (motivo_ctr, motivo_cvr) if x)} — señal de problema corregible (foto/título/ficha/precio), no de falta de demanda.{_nota_precio_objetivo(context)}",
            evidence={**evidence, "ctr": ctr, "cvr": cvr}, economic_confidence=economic_confidence,
            sample_confidence=sample_confidence, stock_confidence=stock_confidence,
            expected_impact="recuperar conversión sin bajar presupuesto todavía",
            risk="bajo", stop_loss="si tras el diagnóstico no mejora en 10 días, reevaluar salida de Ads",
            review_at=_review_at(10), formula_version=FORMULA_VERSION, created_at=_now_iso(),
        )

    if stock_sobrante and (roas is None or roas < umbral_rentable):
        return Recommendation(
            actionable_unit_id=unit.actionable_unit_id, affected_mlas=unit.affected_mlas,
            affected_variants=unit.affected_variants, current_campaign=context.get("current_campaign"),
            recommended_action="MOVE_TO_RECUPERAR", recommended_campaign=CAMPAIGN_RECUPERAR,
            reason=f"Cobertura de stock muy alta ({coverage_days:.0f} días) con Ads ineficiente — prioridad es liberar capital, no maximizar ROAS.",
            evidence=evidence, economic_confidence=economic_confidence, sample_confidence=sample_confidence,
            stock_confidence=stock_confidence, expected_impact="liberar capital inmovilizado",
            risk="medio", stop_loss="si tras 20 días no rota, evaluar salida definitiva de Ads",
            review_at=_review_at(20), formula_version=FORMULA_VERSION, created_at=_now_iso(),
        )

    if roas is not None and roas < umbral_rentable:
        return Recommendation(
            actionable_unit_id=unit.actionable_unit_id, affected_mlas=unit.affected_mlas,
            affected_variants=unit.affected_variants, current_campaign=context.get("current_campaign"),
            recommended_action="REMOVE_FROM_ADS", recommended_campaign=None,
            reason=f"ROAS {roas:.1f}x por debajo de {umbral_rentable:.1f}x ({fuente_umbral}) con presupuesto real ya asignado y sin señal de problema corregible ni de capital inmovilizado — no sostiene Ads hoy.{_nota_precio_objetivo(context)}",
            evidence=evidence, economic_confidence=economic_confidence, sample_confidence=sample_confidence,
            stock_confidence=stock_confidence, expected_impact="dejar de perder en Ads; sigue vendiendo orgánico si lo hacía",
            risk="bajo", stop_loss=None, review_at=_review_at(30),
            formula_version=FORMULA_VERSION, created_at=_now_iso(),
        )

    return Recommendation(
        actionable_unit_id=unit.actionable_unit_id, affected_mlas=unit.affected_mlas,
        affected_variants=unit.affected_variants, current_campaign=context.get("current_campaign"),
        recommended_action="NO_ACTION", recommended_campaign=None,
        reason="Sin señal suficiente para mover de campaña con los datos disponibles.",
        evidence=evidence, economic_confidence=economic_confidence, sample_confidence=sample_confidence,
        stock_confidence=stock_confidence, expected_impact="ninguno", risk="bajo", stop_loss=None,
        review_at=_review_at(10), formula_version=FORMULA_VERSION, created_at=_now_iso(),
    )


def _nota_precio_objetivo(context: dict) -> str:
    """Si el caller ya resolvió el precio objetivo real (ver
    core/target_price.resolve_target_price_for_code), lo suma como palanca
    concreta de corrección -- "subir precio" es tan válida como foto/título/
    ficha (ver Recovery Engine), y a veces es la única real cuando el margen
    de base ya es demasiado ajustado para que ningún CTR lo salve."""
    tp = context.get("target_price_result")
    if not tp or not tp.get("found"):
        return ""
    return (
        f" Precio objetivo real (según costo ERP + comisión real de ML): "
        f"${tp['precio_objetivo']:.0f} ({tp['incremento_pct_vs_actual']*100:+.0f}% vs el actual) "
        f"para dejar margen neto positivo."
    )


def _blocked(unit: ActionableUnit, evidence: dict, reason: str) -> Recommendation:
    return Recommendation(
        actionable_unit_id=unit.actionable_unit_id, affected_mlas=unit.affected_mlas,
        affected_variants=unit.affected_variants, current_campaign=evidence.get("current_campaign"),
        recommended_action="BLOCKED", recommended_campaign=None, reason=reason, evidence=evidence,
        economic_confidence=evidence.get("economic_confidence") or "blocked", sample_confidence="insufficient",
        stock_confidence="low", expected_impact="ninguno", risk="ninguno (bloqueado)", stop_loss=None,
        review_at=_review_at(3), formula_version=FORMULA_VERSION, created_at=_now_iso(),
    )
