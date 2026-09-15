from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from core.target_price import find_target_price  # noqa: E402


def comision_constante_13pct(precio: float) -> float:
    return precio * 0.13


class TargetPriceTests(unittest.TestCase):
    def test_price_already_meets_target_margin_returns_current_price(self):
        r = find_target_price(
            precio_actual=10000, unidades=10, costo_total=50000, envio_fijo=3000, ads_fijo=5000,
            iibb_rate_efectiva=0.02, comision_por_precio=comision_constante_13pct,
            margen_neto_actual=9645, margen_neto_objetivo_pct=0.0,
        )
        self.assertTrue(r.found)
        self.assertEqual(r.precio_objetivo, 10000)
        self.assertEqual(r.iteraciones, 1)

    def test_underpriced_sku_needs_a_higher_target_price(self):
        """Costo real alto relativo al precio -> el precio actual da margen
        neto negativo; debe encontrar un precio más alto real que sí cierra
        la cuenta completa (IVA+IIBB+comisión real+costo+envío+Ads), no solo
        margen bruto."""
        r = find_target_price(
            precio_actual=10000, unidades=10, costo_total=85000, envio_fijo=3000, ads_fijo=5000,
            iibb_rate_efectiva=0.02, comision_por_precio=comision_constante_13pct,
            margen_neto_actual=-25355, margen_neto_objetivo_pct=0.0,
        )
        self.assertTrue(r.found)
        self.assertGreater(r.precio_objetivo, 10000)
        self.assertGreaterEqual(r.margen_neto_pct_a_ese_precio, 0.0)
        self.assertGreater(r.incremento_pct_vs_actual, 0)

    def test_positive_target_margin_requires_higher_price_than_breakeven(self):
        """Pedir margen neto objetivo del 10% (no solo empatar en 0) debe
        exigir un precio más alto que pedir apenas breakeven."""
        kwargs = dict(
            precio_actual=10000, unidades=10, costo_total=85000, envio_fijo=3000, ads_fijo=5000,
            iibb_rate_efectiva=0.02, comision_por_precio=comision_constante_13pct, margen_neto_actual=-25355,
        )
        breakeven = find_target_price(**kwargs, margen_neto_objetivo_pct=0.0)
        con_margen = find_target_price(**kwargs, margen_neto_objetivo_pct=0.10)
        self.assertTrue(breakeven.found and con_margen.found)
        self.assertGreater(con_margen.precio_objetivo, breakeven.precio_objetivo)

    def test_structurally_unviable_sku_is_never_forced_to_a_fake_price(self):
        """Si ni subiendo el precio dentro del límite razonable alcanza,
        found=False con motivo explícito -- nunca inventa un número."""
        r = find_target_price(
            precio_actual=10000, unidades=10, costo_total=300000, envio_fijo=3000, ads_fijo=5000,
            iibb_rate_efectiva=0.02, comision_por_precio=comision_constante_13pct,
            margen_neto_actual=-300000, margen_neto_objetivo_pct=0.0, max_incremento_pct=0.10, paso_pct=0.05,
        )
        self.assertFalse(r.found)
        self.assertIsNone(r.precio_objetivo)
        self.assertIn("no alcanza", r.motivo)

    def test_missing_commission_data_is_not_silently_ignored(self):
        r = find_target_price(
            precio_actual=10000, unidades=10, costo_total=50000, envio_fijo=3000, ads_fijo=5000,
            iibb_rate_efectiva=0.02, comision_por_precio=lambda p: None,
            margen_neto_actual=9645, margen_neto_objetivo_pct=0.0,
        )
        self.assertFalse(r.found)
        self.assertIn("simulador", r.motivo)

    def test_no_units_sold_cannot_project_a_target_price(self):
        r = find_target_price(
            precio_actual=10000, unidades=0, costo_total=50000, envio_fijo=3000, ads_fijo=5000,
            iibb_rate_efectiva=0.02, comision_por_precio=comision_constante_13pct, margen_neto_actual=0,
        )
        self.assertFalse(r.found)


if __name__ == "__main__":
    unittest.main()
