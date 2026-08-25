"""Reglas de negocio: tiers, umbrales de ROAS/ACOS, clasificación de ticket, alertas."""
from __future__ import annotations

TIERS = ("testeo", "plata", "oro")
TIERS_ORDEN = {"testeo": 0, "plata": 1, "oro": 2}

# Límites de precio por ticket (inclusive)
# Reestructuración del 05/08/2026: Oro y Plata quedaron con 2 subniveles
# (alto/bajo, el "medio" se fusionó a "alto"); Testeo se unificó en una sola
# campaña sin subnivel de ticket. Ver project_shaffe_ads_agent.md.
TICKET_BAJO_MAX = 17_999   # < $18.000
# Ticket Alto: >= $18.000

# ROAS mínimo de evaluación por campaña (tier + ticket).
# Nota: este valor NO es el roas_target que se envía a la API de ML —
# ese es una palanca algorítmica que se maneja por separado y conservadoramente.
ROAS_TARGET = {
    "oro_alto":    7.5,
    "oro_bajo":    8.0,
    "plata_alto":  4.0,
    "plata_bajo":  4.0,
    "testeo":      3.0,
}

# ACOS máximo tolerado por campaña (testeo no tiene límite estricto).
ACOS_MAX = {
    "oro_alto":    0.15,
    "oro_bajo":    0.15,
    "plata_alto":  0.25,
    "plata_bajo":  0.25,
}

# Umbrales de movimiento entre tiers
ROAS_TESTEO_A_PLATA  = 3.5   # ROAS mínimo sostenido para subir de testeo a plata
ROAS_PLATA_A_ORO     = 6.5   # ROAS mínimo sostenido para subir a oro (todos los tickets)
ROAS_DEGRADAR_ORO    = 5.5   # en oro: si ROAS < 5.5 sostenido → bajar a plata
ROAS_DEGRADAR_PLATA  = 4.0   # en plata: si ROAS < 4.0 sostenido → sacar de ads

DIAS_SOSTENIDO_SUBIR = 1     # collects consecutivos con ROAS bueno para confirmar subida
DIAS_CAIDA_BAJAR     = 1     # collects consecutivos con ROAS malo para confirmar bajada
DIAS_SIN_TOCAR_ORO   = 15    # días mínimos sin ajustes tras confirmar producto en Oro
HORAS_GRACIA_NUEVA_PUB = 48  # horas de indexación orgánica antes de entrar a Ads

# Tiempo mínimo en el tier actual antes de poder subir
# (asegura que el producto consolide orgánico + envíos antes del ascenso)
DIAS_MIN_EN_TIER_SUBIR        = 7   # días calendario para subida normal
DIAS_MIN_EN_TIER_SUBIR_RAPIDO = 5   # días si el ROAS es ≥ 2× el objetivo del tier
ROAS_FACTOR_SUBIDA_RAPIDA     = 2.0 # multiplicador sobre roas_target para habilitar subida rápida

# Presupuesto mínimo recibido para que el ROAS sea una señal válida (ventana de 30 días).
# En ML Ads el presupuesto es de la campaña completa: si otras publicaciones lo consumen,
# esta queda sin presupuesto real aunque la campaña tenga plata. El gasto por publicación
# es la única señal confiable de que ML realmente le asignó recursos.
# Dato real SHAFFE: el único producto sin ventas tuvo $516 ARS de gasto;
# el mínimo de los que sí vendieron fue $2.755 ARS → umbral en $2.000.
GASTO_MIN_EVALUAR       = 2_000  # ARS; si gastó menos que esto, ML no le dio presupuesto real
IMPRESIONES_MIN_EVALUAR = 500    # respaldo simbólico; en la práctica siempre correlaciona con gasto

# Alerta de caída urgente (fuera del ciclo semanal)
DIAS_CAIDA_URGENTE = 3  # N días consecutivos cayendo en producto que venía bien

# Alertas CTR / CVR
CTR_ALERTA_MIN = 0.02
CVR_ALERTA_MIN = 0.01

# Stock
STOCK_BAJO_UNIDADES        = 5
STOCK_ESCALAR_MIN_UNIDADES = 10
STOCK_BAJO_VARIANTES       = 2

# Candidatas sin Ads
VENTAS_ORGANICAS_MIN_30D = 20
STOCK_CANDIDATA_MIN      = 10


def clasificar_ticket(precio: float) -> str:
    if precio <= TICKET_BAJO_MAX:
        return "bajo"
    return "alto"


def nombre_campania(tier: str, ticket: str | None) -> str:
    """Testeo no lleva ticket en el nombre (campaña única desde el 05/08)."""
    if tier == "testeo":
        return "testeo"
    return f"{tier}_{ticket}"


def tier_y_ticket(nombre: str) -> tuple:
    """"testeo" (sin sufijo) no tiene ticket en el nombre — devuelve ticket=None,
    quien llame tiene que resolverlo por precio real si lo necesita (ver
    evaluar_movimiento_tier, que ya recibe el ticket real aparte)."""
    if nombre == "testeo":
        return "testeo", None
    tier, sep, ticket = nombre.partition("_")
    return tier, (ticket if sep else None)


def roas_target_campania(nombre: str) -> float:
    """ROAS de evaluación para una campaña dada. Fallback conservador si el nombre no existe."""
    return ROAS_TARGET.get(nombre, 4.0)


def acos_max_campania(nombre: str) -> float | None:
    return ACOS_MAX.get(nombre)


def es_subida_tier(tier_origen: str, tier_destino: str) -> bool:
    return TIERS_ORDEN.get(tier_destino, 0) > TIERS_ORDEN.get(tier_origen, 0)


def roas_target_to_acos_target(roas_target: float) -> float:
    return (1 / roas_target) * 100


def evaluar_movimiento_tier(
    nombre_campania_actual: str,
    historial_roas: list,
    dias_en_oro: int = 0,
    dias_en_tier_actual: int = 999,
    ticket_actual: str | None = None,
) -> str | None:
    """Evalúa si un producto debe moverse de campaña.

    Devuelve:
    - nombre de campaña destino (ej. "oro_alto") si corresponde subir o bajar
    - "pausar" si debe salir de ads completamente (plata con ROAS sostenido < 4)
    - None si no hay movimiento

    historial_roas: ROAS diarios, más reciente al final.
    dias_en_oro: días que lleva el producto en una campaña Oro (para regla de 15 días).
    dias_en_tier_actual: días en el tier actual; bloquea subidas si no supera el mínimo.
                         Default 999 = producto rastreado antes de esta regla → no bloquear.
    ticket_actual: ticket real (clasificar_ticket sobre el precio), OBLIGATORIO
                   para resolver el destino cuando el tier actual es "testeo"
                   (esa campaña no lleva ticket en el nombre). Para plata/oro
                   se ignora: el ticket real ya viene del nombre de la campaña.
    """
    if not historial_roas:
        return None

    tier_actual, ticket_del_nombre = tier_y_ticket(nombre_campania_actual)
    ticket = ticket_del_nombre if ticket_del_nombre is not None else (ticket_actual or "alto")

    # Oro recién confirmado: no tocar hasta cumplir el mínimo de estabilidad
    if tier_actual == "oro" and dias_en_oro < DIAS_SIN_TOCAR_ORO:
        return None

    ultimos_subir = historial_roas[-DIAS_SOSTENIDO_SUBIR:]
    ultimos_bajar = historial_roas[-DIAS_CAIDA_BAJAR:]

    # Días mínimos en el tier actual para permitir subida
    # Si el ROAS supera 2× el objetivo del tier, se acepta el mínimo reducido
    roas_actual = historial_roas[-1]
    roas_obj = roas_target_campania(nombre_campania_actual)
    dias_min_subir = (
        DIAS_MIN_EN_TIER_SUBIR_RAPIDO
        if roas_actual >= roas_obj * ROAS_FACTOR_SUBIDA_RAPIDA
        else DIAS_MIN_EN_TIER_SUBIR
    )

    if tier_actual == "testeo":
        if dias_en_tier_actual < dias_min_subir:
            return None  # aún no consolidó suficiente tiempo en testeo
        if len(ultimos_subir) >= DIAS_SOSTENIDO_SUBIR and all(r >= ROAS_PLATA_A_ORO for r in ultimos_subir):
            return f"oro_{ticket}"
        if len(ultimos_subir) >= DIAS_SOSTENIDO_SUBIR and all(r > ROAS_TESTEO_A_PLATA for r in ultimos_subir):
            return f"plata_{ticket}"
        return None

    if tier_actual == "plata":
        # Bajada: rápida, no espera tiempo mínimo
        if len(ultimos_bajar) >= DIAS_CAIDA_BAJAR and all(r < ROAS_DEGRADAR_PLATA for r in ultimos_bajar):
            return "pausar"
        # Subida: requiere tiempo mínimo en plata
        if dias_en_tier_actual < dias_min_subir:
            return None
        if len(ultimos_subir) >= DIAS_SOSTENIDO_SUBIR and all(r >= ROAS_PLATA_A_ORO for r in ultimos_subir):
            return f"oro_{ticket}"
        return None

    if tier_actual == "oro":
        if len(ultimos_bajar) >= DIAS_CAIDA_BAJAR and all(r < ROAS_DEGRADAR_ORO for r in ultimos_bajar):
            return f"plata_{ticket}"
        return None

    return None


def es_caida_urgente(historial_roas: list, roas_target: float) -> bool:
    """True si el producto venía bien y lleva DIAS_CAIDA_URGENTE días consecutivos
    por debajo del target. Señal para alerta inmediata fuera del ciclo semanal."""
    if len(historial_roas) < DIAS_CAIDA_URGENTE + 1:
        return False
    tenia_buen_roas = any(r >= roas_target for r in historial_roas[:-DIAS_CAIDA_URGENTE])
    caida_reciente = all(r < roas_target for r in historial_roas[-DIAS_CAIDA_URGENTE:])
    return tenia_buen_roas and caida_reciente


def recomendacion_alerta(alerta_tipo: str, roas: float, nombre_campania_actual: str) -> str:
    """Texto corto de acción recomendada para mostrar junto a cada alerta."""
    if alerta_tipo == "ctr_bajo":
        if roas == 0:
            return "sin ventas — cambiá la foto principal antes de decidir"
        target = roas_target_campania(nombre_campania_actual)
        ratio = roas / target if target else 0
        if ratio < 0.4:
            return "ROAS muy bajo — cambiar foto + precio o pausar"
        if ratio < 0.7:
            return "mejorar foto/precio para recuperar el ROAS"
        return "mejorar foto para potenciar (ya está cerca del objetivo)"
    if alerta_tipo == "cvr_bajo":
        if roas == 0:
            return "sin ventas — revisá descripción, precio y fotos secundarias"
        return "la gente entra pero no compra — mejorar descripción/ficha"
    if alerta_tipo == "acos_alto":
        return "costo de publicidad muy alto para este tier — revisar puja o pausar"
    return ""


def alertas_metricas(impresiones: int, clics: int, conversiones: int, acos: float | None, nombre_campania_actual: str) -> list:
    alertas = []
    if impresiones == 0:
        return alertas
    ctr = clics / impresiones
    if ctr < CTR_ALERTA_MIN and impresiones >= 100:
        alertas.append("ctr_bajo")
    if clics > 0:
        cvr = conversiones / clics
        if cvr < CVR_ALERTA_MIN and clics >= 30:
            alertas.append("cvr_bajo")
    acos_max = acos_max_campania(nombre_campania_actual)
    if acos is not None and acos_max is not None and acos > acos_max:
        alertas.append("acos_alto")
    return alertas


def tiene_presupuesto_real(costo: float, impresiones: int) -> bool:
    """True si ML realmente le asignó presupuesto a esta publicación.
    El presupuesto es de la campaña: si otras publicaciones lo consumen, esta queda sin
    recursos aunque la campaña tenga plata. Con gasto < $2.000 ARS en 30 días, ML no le
    dio presupuesto real y el ROAS no es una señal válida para decidir movimientos de tier."""
    return costo >= GASTO_MIN_EVALUAR or impresiones >= IMPRESIONES_MIN_EVALUAR


def calcular_margen(ingresos: float, unidades: float, costo_producto: float | None, gasto_ads: float) -> dict | None:
    """Margen real de producto usando costo REAL del ERP (nunca Excel ni
    supuesto hardcodeado — ver CIOMA / AUDITORIA-FASE-0.md, este agente antes
    no tenía ningún ancla de costo real).

    OJO: margen_post_ads_pct NO resta comisión de Mercado Libre ni impuestos
    — este agente no tiene ese dato real por publicación (vive en el ERP a
    nivel venta, no por línea de Ads). Se etiqueta explícitamente qué NO está
    incluido en vez de inventar un promedio, siguiendo la regla de "no ocultar
    incertidumbre". Por eso un margen_post_ads_pct positivo pero bajo (ej. <15%)
    puede terminar en pérdida real una vez descontada la comisión de ML.

    Devuelve None si no hay costo real o no hay unidades vendidas (nada que evaluar)."""
    if not unidades or unidades <= 0 or costo_producto is None:
        return None
    precio_prom = ingresos / unidades
    if precio_prom <= 0:
        return None
    ads_por_unidad = gasto_ads / unidades
    margen_producto_pct = (precio_prom - costo_producto) / precio_prom * 100
    margen_post_ads_pct = (precio_prom - costo_producto - ads_por_unidad) / precio_prom * 100
    return {
        "precio_prom": precio_prom,
        "costo_producto": costo_producto,
        "ads_por_unidad": ads_por_unidad,
        "margen_producto_pct": margen_producto_pct,
        "margen_post_ads_pct": margen_post_ads_pct,
    }


def es_poco_stock(unidades_totales: int, variantes_disponibles: int, total_variantes: int | None = None) -> bool:
    """Poco stock si las unidades totales son bajas, O si de varias variantes
    posibles quedan muy pocas disponibles (señal de que se vendieron talles/
    colores y el producto se está agotando).

    OJO: la señal de "variantes disponibles bajas" solo aplica si el producto
    tuvo alguna vez más variantes que STOCK_BAJO_VARIANTES. Un producto que
    siempre fue talle único / 1 sola variante (total_variantes <= 2) no está
    "agotándose" por tener 1 de 1 disponible - simplemente tiene su única
    variante en stock. Sin total_variantes (compat con llamadas viejas), se
    mantiene el comportamiento anterior (puede dar falso positivo en talle único)."""
    if unidades_totales < STOCK_BAJO_UNIDADES:
        return True
    if total_variantes is not None and total_variantes <= STOCK_BAJO_VARIANTES:
        return False
    return variantes_disponibles <= STOCK_BAJO_VARIANTES
