"""Agente de research mensual: tendencias ML Argentina + oportunidades de catálogo.

Consulta:
1. /trends/MLA — keywords en tendencia en todo ML Argentina
2. /sites/MLA/search en categoría Ropa (MLA1430) — más vendidos del momento
3. Cruza con el catálogo actual de SHAFFE para identificar gaps

Modo: python main.py research
Frecuencia: mensual (primer lunes del mes, ver weekly_run.yml).
Resultado: hoja "Tendencias Research" en el Excel del mes + mensaje Telegram."""
from __future__ import annotations

from core.ml_client import MLClient

# Categorías de ropa/indumentaria en ML Argentina relevantes para SHAFFE
CATEGORIAS_SHAFFE = {
    "MLA1430": "Ropa y Accesorios",
    "MLA3636": "Ropa Hombre",
    "MLA3750": "Ropa Mujer",
    "MLA1244": "Ropa Deportiva",
    "MLA31447": "Niños y Bebés - Ropa",
}

# Keywords de categorías que SHAFFE ya vende (para detectar gaps)
PALABRAS_CATALOGO_SHAFFE = [
    "remera", "buzo", "campera", "pantalon", "jogging", "chaleco", "sweater",
    "gorro", "medias", "calza", "camisaco", "jogger", "hoodie", "rompeviento",
    "polera", "morley", "babucha", "oversize",
]

# Palabras que indican categorías probablemente fuera del catálogo de SHAFFE
PALABRAS_FUERA_CATALOGO = [
    "vestido", "falda", "bota", "zapatilla", "short", "bermuda", "traje",
    "corbata", "bufanda", "guante", "piloto", "jean", "chomba", "polo",
    "camiseta", "musculosa", "bikini", "malla", "ojotas", "sandalia",
]


class ResearchAgent:
    def __init__(self, ml: MLClient, site_id: str = "MLA"):
        self.ml = ml
        self.site_id = site_id

    def investigar(self) -> list:
        """Devuelve lista de oportunidades detectadas.
        Cada entrada: {categoria, keyword, top_producto, precio_prom, ventas_estimadas,
                       competencia, fit_shaffe, recomendacion}"""
        oportunidades = []

        # 1. Tendencias generales de ML Argentina
        trends = self._get_trends()
        for trend in trends[:30]:  # top 30 tendencias
            keyword = trend.get("keyword", "")
            url = trend.get("url", "")
            fit, categoria_fit = self._evaluar_fit_shaffe(keyword)
            if fit == "ninguno":
                continue
            oportunidades.append({
                "categoria": "Tendencias ML",
                "keyword": keyword,
                "top_producto": "",
                "precio_prom": "",
                "ventas_estimadas": "",
                "competencia": "Ver en ML",
                "fit_shaffe": fit,
                "recomendacion": self._recomendacion(keyword, fit, categoria_fit),
                "url_tendencia": url,
            })

        # 2. Más vendidos por categoría de ropa
        for cat_id, cat_nombre in CATEGORIAS_SHAFFE.items():
            resultados = self._buscar_mas_vendidos(cat_id, limit=5)
            for item in resultados:
                titulo = item.get("title", "")
                precio = item.get("price", 0)
                sold = item.get("sold_quantity", 0)
                fit, categoria_fit = self._evaluar_fit_shaffe(titulo)
                if fit == "tiene" and sold < 100:
                    continue  # ya lo tiene y no es super ventas, no interesa
                oportunidades.append({
                    "categoria": cat_nombre,
                    "keyword": titulo,
                    "top_producto": item.get("id", ""),
                    "precio_prom": f"${precio:,.0f}" if precio else "",
                    "ventas_estimadas": f"{sold}+" if sold else "N/D",
                    "competencia": "Alta" if sold > 500 else ("Media" if sold > 100 else "Baja"),
                    "fit_shaffe": fit,
                    "recomendacion": self._recomendacion(titulo, fit, categoria_fit),
                    "url_tendencia": "",
                })

        # Eliminar duplicados por keyword similar y priorizar los que SHAFFE no tiene
        vistos: set = set()
        resultado_final = []
        for o in oportunidades:
            kw = o["keyword"].lower()[:30]
            if kw not in vistos:
                vistos.add(kw)
                resultado_final.append(o)

        # Ordenar: primero los gaps (SHAFFE no tiene), después los que podría potenciar
        resultado_final.sort(key=lambda x: (0 if x["fit_shaffe"] == "gap" else 1, x["keyword"]))
        return resultado_final

    def _get_trends(self) -> list:
        try:
            data = self.ml._request("GET", f"/trends/{self.site_id}")
            if isinstance(data, list):
                return data
            return []
        except Exception:
            return []

    def _buscar_mas_vendidos(self, category_id: str, limit: int = 5) -> list:
        try:
            data = self.ml._request(
                "GET",
                f"/sites/{self.site_id}/search",
                params={
                    "category": category_id,
                    "sort": "sold_quantity_desc",
                    "limit": limit,
                    "attributes": "id,title,price,sold_quantity",
                },
            )
            return data.get("results", []) if isinstance(data, dict) else []
        except Exception:
            return []

    def _evaluar_fit_shaffe(self, texto: str) -> tuple:
        """Devuelve (fit, categoria):
        - "tiene" si SHAFFE ya vende algo similar
        - "gap" si es una oportunidad clara de catálogo
        - "potencial" si es adyacente
        - "ninguno" si no es relevante para indumentaria"""
        texto_lower = texto.lower()

        for kw in PALABRAS_CATALOGO_SHAFFE:
            if kw in texto_lower:
                return "tiene", kw

        for kw in PALABRAS_FUERA_CATALOGO:
            if kw in texto_lower:
                return "gap", kw

        # Términos adyacentes a indumentaria
        terminos_indumentaria = ["ropa", "vestimenta", "prenda", "tela", "moda", "outfit", "look"]
        for kw in terminos_indumentaria:
            if kw in texto_lower:
                return "potencial", kw

        return "ninguno", ""

    def _recomendacion(self, keyword: str, fit: str, categoria: str) -> str:
        if fit == "tiene":
            return f"Ya tenés '{categoria}' en tu catálogo. Evaluar si tus publicaciones están bien posicionadas para esta búsqueda."
        if fit == "gap":
            return f"'{categoria}' es una categoría que no tenés. Si el margen lo permite y está en tendencia, evaluar incorporar al catálogo."
        if fit == "potencial":
            return f"Categoría adyacente a tu rubro. Investigar si hay variantes o productos relacionados que SHAFFE podría sumar."
        return "Tendencia general — verificar relevancia para el catálogo SHAFFE."
