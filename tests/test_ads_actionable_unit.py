import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from core.ads_actionable_unit import (  # noqa: E402
    ACTION_SCOPE_GROUP,
    ACTION_SCOPE_SINGLE,
    ActionableUnitError,
    assert_target_is_actionable,
    build_actionable_unit,
)


class ActionableUnitRealCasesTests(unittest.TestCase):
    """Regresion sobre payloads REALES (no sinteticos) capturados en vivo
    2026-08-28 contra la cuenta real de SHAFFE. Ver
    tests/fixtures/actionable_unit_real_cases.json para el origen de cada
    valor -- esto es la prueba de que ADS_ACTIONABLE_UNIT = ad_group, no
    item_id ni variante."""

    @classmethod
    def setUpClass(cls):
        fixture = BASE / "tests" / "fixtures" / "actionable_unit_real_cases.json"
        cls.data = json.loads(fixture.read_text(encoding="utf-8"))

    # --- Caso A: variante != actionable unit (regla 16.A del proyecto) ---

    def test_family_ad_group_groups_all_real_variants_together(self):
        """Camisa Hombre Elastizada: 6 MLA reales distintos, TODOS bajo el
        mismo ad_group_id real (2723481184). La unidad accionable es UNA
        sola, no 6."""
        unit = build_actionable_unit(
            self.data["ad_group_camisa_family"],
            family_items=self.data["camisa_family_items"],
        )
        self.assertEqual(unit.ad_group_type, "FAMILY")
        self.assertEqual(unit.action_scope, ACTION_SCOPE_GROUP)
        self.assertEqual(set(unit.affected_mlas), set(self.data["camisa_ad_by_item"].keys()))
        self.assertEqual(len(unit.affected_mlas), 6)
        self.assertTrue(unit.integrity_ok)
        self.assertEqual(unit.actionable_unit_id, "ad_group:2723481184")

    def test_single_variant_cannot_be_treated_as_its_own_actionable_unit(self):
        """Ninguno de los 6 item_id de la Camisa puede recibir una accion
        MOVE/PAUSE/ACTIVATE por separado -- todos resuelven a la MISMA
        ActionableUnit, y assert_target_is_actionable no levanta error para
        ninguno de ellos porque el scope real es GROUP (mover implica mover
        a las 6 juntas, no es un bug: es la regla real de Ads)."""
        unit = build_actionable_unit(
            self.data["ad_group_pantalon_family"],
            family_items=self.data["pantalon_family_items"],
        )
        for item_id in self.data["pantalon_ad_by_item"]:
            assert_target_is_actionable(unit, item_id)  # no debe lanzar
        # Pero un item_id ajeno a esta familia SI debe rechazarse:
        with self.assertRaises(ActionableUnitError):
            assert_target_is_actionable(unit, "MLA1420436886")

    def test_actionable_unit_without_family_catalog_is_low_confidence_not_invented(self):
        """Si no se provee el catalogo de la familia, la unidad NO inventa
        una lista de affected_mlas vacia como si fuera un hecho confirmado
        -- baja confidence y marca integrity_issue explicito."""
        unit = build_actionable_unit(self.data["ad_group_camisa_family"])
        self.assertEqual(unit.confidence, "low")
        self.assertEqual(unit.integrity_issue, "FAMILY_ITEMS_NOT_PROVIDED")
        self.assertFalse(unit.integrity_ok)
        with self.assertRaises(ActionableUnitError):
            assert_target_is_actionable(unit, "MLA3822378936")

    # --- Caso: 1N019 (dos publicaciones reales, misma familia comercial,
    # NO deben mezclarse como si fueran una sola unidad) ---

    def test_1n019_hombre_y_mujer_son_dos_actionable_units_independientes(self):
        unit_hombre = build_actionable_unit(self.data["ad_group_1n019_hombre_item"])
        unit_mujer = build_actionable_unit(self.data["ad_group_1n019_mujer_item"])

        self.assertEqual(unit_hombre.ad_group_type, "ITEM")
        self.assertEqual(unit_mujer.ad_group_type, "ITEM")
        self.assertEqual(unit_hombre.action_scope, ACTION_SCOPE_SINGLE)
        self.assertEqual(unit_mujer.action_scope, ACTION_SCOPE_SINGLE)

        self.assertNotEqual(unit_hombre.ad_group_id, unit_mujer.ad_group_id)
        self.assertNotEqual(unit_hombre.campaign_id, unit_mujer.campaign_id)
        self.assertEqual(unit_hombre.affected_mlas, ("MLA1420436886",))
        self.assertEqual(unit_mujer.affected_mlas, ("MLA1403338277",))

        # Una recomendacion sobre la unidad hombre jamas puede aplicarse al item mujer.
        with self.assertRaises(ActionableUnitError):
            assert_target_is_actionable(unit_hombre, "MLA1403338277")
        with self.assertRaises(ActionableUnitError):
            assert_target_is_actionable(unit_mujer, "MLA1420436886")

    def test_item_ad_group_campaign_id_is_real_not_zero(self):
        """Confirma en datos reales que get_ad_group puede traer
        campaign_id=0 para FAMILY (sin campana asignada), mientras que para
        ITEM (publicaciones mas viejas, ya asignadas) el campaign_id real
        SI viene poblado -- documentado en el docstring del modulo."""
        family_unit = build_actionable_unit(self.data["ad_group_camisa_family"])
        self.assertIsNone(family_unit.campaign_id)  # campaign_id=0 -> None, nunca "0" fantasma

        item_unit = build_actionable_unit(self.data["ad_group_1n019_hombre_item"])
        self.assertEqual(item_unit.campaign_id, "357702416")

    def test_mismatched_family_id_marks_integrity_issue(self):
        """Si un item del catalogo tiene un family_id que NO coincide con el
        family_id real del ad_group (dato corrupto/desincronizado), la
        unidad se marca de baja confianza en vez de agruparlo silenciosamente."""
        items = list(self.data["camisa_family_items"]) + [
            {"id": "MLA9999999999", "family_id": "OTRA_FAMILIA_DISTINTA"}
        ]
        unit = build_actionable_unit(self.data["ad_group_camisa_family"], family_items=items)
        self.assertFalse(unit.integrity_ok)
        self.assertIn("MLA9999999999", unit.integrity_issue)
        with self.assertRaises(ActionableUnitError):
            assert_target_is_actionable(unit, "MLA3822378936")

    def test_total_ad_groups_is_not_hardcoded_snapshot(self):
        """El numero real de ad_groups de la cuenta cambia con el catalogo
        (451 el 2026-08-28, no los 442 documentados el 05-06/08) -- este
        test solo deja constancia del snapshot verificado, ningun codigo de
        produccion debe hardcodear este numero."""
        self.assertEqual(self.data["total_ad_groups_cuenta_20260828"], 451)


if __name__ == "__main__":
    unittest.main()
