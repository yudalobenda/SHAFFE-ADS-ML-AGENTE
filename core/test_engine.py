"""Sample Engine / cierre del loop de product_tests.

El problema real (confirmado en vivo 2026-08-28): 268 tests quedaron
'activo' con review_at ya vencido sin ninguna decisión (263
publicacion_nueva + 5 cambio_ads) -- un cementerio, no un loop. Este modulo
NO decide en lugar del usuario (product_tests.decidir sigue siendo 100%
humano, PUT /api/product-tests/:id/decidir) -- calcula una SUGERENCIA con
evidencia real y la dellas visible (ver test_engine_runner que la escribe en
`description` via el PUT existente), para que decidir deje de ser "adivinar"
y pase a ser "revisar una propuesta con numeros".

El umbral $5.000 Ads + 100 visitas es la HIPOTESIS INICIAL ya usada en
campaign_rules.GASTO_MIN_EVALUAR/IMPRESIONES_MIN_EVALUAR -- explicitamente
NO calibrada contra historico real todavia (backtestear por precio/CPC/
conversion/margen/categoria queda pendiente, ver core/decision_engine.py)."""
from __future__ import annotations

from dataclasses import dataclass

GASTO_MIN_MUESTRA = 5_000
VISITAS_MIN_MUESTRA = 100
ROAS_WINNER = 4.0          # heredado de ROAS_TESTEO_A_PLATA: ya sostiene Ads
ROAS_STOP = 2.0            # muy por debajo de cualquier tier -- no vale la pena

SAMPLE_INSUFFICIENT = "INSUFFICIENT_SAMPLE"
SAMPLE_WINNER = "WINNER"
SAMPLE_CORRECT = "CORRECT"
SAMPLE_STOP_ADS = "STOP_ADS"
SAMPLE_BLOCKED = "BLOCKED"

DECISION_ESCALAR = "escalar"
DECISION_MANTENER = "mantener"
DECISION_REPETIR = "repetir"
DECISION_REVERTIR = "revertir"


@dataclass(frozen=True)
class TestSuggestion:
    sample_status: str
    suggested_decision: str | None  # None cuando INSUFFICIENT_SAMPLE: no hay decisión posible todavía
    reason: str
    evidence: dict


def classify_test(*, spend: float | None, visits: int | None, roas: float | None,
                   units_sold: int | None, clicks: int | None) -> TestSuggestion:
    """Clasifica un test ya vencido con las métricas reales disponibles
    (visits: visitas ML si existen; spend/roas: agregados de Ads si el
    external_item_id estuvo en Ads; units_sold: ventas reales ERP/ML orders,
    con o sin Ads). Nunca trata None como 0."""
    evidence = {"spend": spend, "visits": visits, "roas": roas, "units_sold": units_sold, "clicks": clicks}

    tiene_muestra = (spend or 0) >= GASTO_MIN_MUESTRA or (visits or 0) >= VISITAS_MIN_MUESTRA
    if not tiene_muestra:
        # Sin gasto en Ads ni visitas suficientes, pero con ventas reales
        # igual (organico funcionando) -- no es "sin muestra", es una señal
        # positiva aunque no haya pasado por Ads.
        if (units_sold or 0) >= 3 and not spend:
            return TestSuggestion(
                SAMPLE_CORRECT, DECISION_MANTENER,
                f"{units_sold} ventas orgánicas reales sin haber pasado por Ads — sigue así, no necesita Ads todavía.",
                evidence,
            )
        return TestSuggestion(
            SAMPLE_INSUFFICIENT, None,
            f"Muestra insuficiente (gasto ${spend or 0:.0f} < ${GASTO_MIN_MUESTRA}, visitas {visits or 0} < {VISITAS_MIN_MUESTRA}) — todavía no hay evidencia para decidir.",
            evidence,
        )

    if roas is not None and roas >= ROAS_WINNER:
        return TestSuggestion(
            SAMPLE_WINNER, DECISION_ESCALAR,
            f"ROAS {roas:.1f}x con muestra real (gasto ${spend or 0:.0f}, visitas {visits or 0}) — ganador, escalar.",
            evidence,
        )
    if roas is not None and roas < ROAS_STOP:
        return TestSuggestion(
            SAMPLE_STOP_ADS, DECISION_REVERTIR,
            f"ROAS {roas:.1f}x con muestra real ya cumplida — no sostiene el gasto, revertir/sacar de Ads.",
            evidence,
        )
    if roas is not None:
        return TestSuggestion(
            SAMPLE_CORRECT, DECISION_REPETIR,
            f"ROAS {roas:.1f}x intermedio con muestra real — no es un ganador claro ni un fracaso: repetir con un ajuste (foto/precio/ficha) antes de decidir del todo.",
            evidence,
        )
    if (units_sold or 0) > 0:
        return TestSuggestion(
            SAMPLE_CORRECT, DECISION_MANTENER,
            f"{units_sold} ventas reales con visitas suficientes pero sin dato de Ads — vendiendo orgánico, mantener así.",
            evidence,
        )
    return TestSuggestion(
        SAMPLE_STOP_ADS, DECISION_REVERTIR,
        f"Visitas suficientes ({visits or 0}) sin ninguna venta real — no convierte, revertir/revisar ficha.",
        evidence,
    )
