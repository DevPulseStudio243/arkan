"""Tests de non-régression des correctifs ARH (pytest)."""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest

from arh_dimensional_engine import dimensional_engine as de
from arh_assertion_guards import assertion_guard as ag
from arh_deterministic_calcs import (ug27_cylindrical_shell, ug99_hydrotest_minimum, decree_hydrotest_minimum,
                                     governing_hydrotest_minimum, barlow_pipe_thickness, carbon_equivalent)


# ---------- Moteur dimensionnel ----------
def test_barg_vs_bara_concordant():
    ok, _ = de.physically_concordant(0.5, "barg", 1.51325, "bara", "pressure", 0.5)
    assert ok

def test_bar_vs_psi():
    assert de.physically_concordant(10, "bar", 145.038, "psi", "pressure", 0.5)[0]

def test_real_discordance_detected():
    assert not de.physically_concordant(10, "bar", 12, "bar", "pressure", 2.0)[0]

def test_parser_prefers_known_unit():
    assert de.parse_value_with_unit("A516 Gr 70 12 mm") == (12.0, "millimeter")
    assert de.parse_value_with_unit("19.6 barg") == (19.6, "bar")

def test_temperature_and_length():
    assert de.physically_concordant(100, "C", 212, "F", "temperature", 1.0)[0]
    assert de.physically_concordant(25.4, "mm", 1, "in", "length", 0.5)[0]


# ---------- Garde-fous ----------
def F(**k):
    base = {"title": "t", "observation": "o", "document_concerned": "NOTE_CALCUL.pdf", "page": "3"}
    base.update(k); return base

def test_provenance_requires_source():
    ok, _ = ag.assert_provenance({"title": "x", "observation": "Anomalie sans source"})
    assert not ok

def test_provenance_no_longer_bypassed_by_word_absence():
    ok, _ = ag.assert_provenance({"title": "x", "observation": "Absence de rigueur dans le raisonnement"})
    assert not ok

def test_provenance_completeness_with_named_document():
    ok, _ = ag.assert_provenance({"title": "Certificat 3.1 manquant", "observation": "Certificat matière non fourni"})
    assert ok

def test_aberrant_value_hallucinated_is_rejected():
    ok, _ = ag.assert_physical_bounds(F(observation="Contrainte de 20000000 MPa"), "contrainte 138 MPa")
    assert not ok

def test_aberrant_value_present_in_document_is_kept_and_flagged():
    f = F(observation="Le document indique S = 20000000 MPa (faute de frappe)")
    ok, _ = ag.assert_physical_bounds(f, "Contrainte admissible S = 20 000 000 MPa")
    assert ok and "VALEUR_ABERRANTE_DANS_LE_DOCUMENT" in f["guard_flags"]

def test_tensile_strength_not_treated_as_allowable_stress():
    ok, _ = ag.assert_physical_bounds(F(observation="Rm = 1200 MPa pour la boulonnerie B7"), "")
    assert ok

def test_seamless_word_does_not_hide_weld_reserve_in_welded_dossier():
    ctx = "Tubes SEAMLESS A106. Virole soudée selon WPS-01 et PQR-01, soudage SAW."
    f = F(title="WPS non qualifiée", observation="La WPS-01 ne couvre pas l'épaisseur")
    assert ag.assert_equipment_exclusivity(f, "PRESSURE_VESSEL", ctx)[0]

def test_seamless_only_dossier_rejects_weld_reserve():
    ctx = "Bouteille en acier SANS SOUDURE. Fabrication par extrusion."
    f = F(title="WPS manquante", observation="PQR à fournir")
    f2 = F(title="Qualification PQR", observation="PQR absente du dossier")
    assert not ag.assert_equipment_exclusivity(f2, "CYLINDER", ctx)[0]

def test_extinguisher_atex_rejected_but_word_boundary_safe():
    assert not ag.assert_equipment_exclusivity(F(observation="Certificat ATEX requis"), "FIRE_EXTINGUISHER")[0]
    assert ag.assert_equipment_exclusivity(F(observation="Le BRÉSIL est le pays d'origine"), "FIRE_EXTINGUISHER")[0]

def test_pipeline_end_to_end_with_audit_trail():
    rejected = []
    out = ag.validate_and_sanitize_findings(
        [F(), {"title": "sans source", "observation": "x"}], equipment_type="PRESSURE_VESSEL", rejected_out=rejected)
    assert len(out) == 1 and len(rejected) == 1


# ---------- Calculs déterministes ----------
def test_ug27_known_value():
    r = ug27_cylindrical_shell(p_mpa=1.0, inside_radius_mm=500, s_allowable_mpa=138, joint_efficiency=1.0)
    assert r["t_circumferential_mm"] == pytest.approx(1.0 * 500 / (138 - 0.6), abs=1e-3)
    assert r["t_governing_mm"] == r["t_circumferential_mm"] and r["valid"]

def test_ug27_out_of_domain_warns():
    r = ug27_cylindrical_shell(p_mpa=60, inside_radius_mm=100, s_allowable_mpa=138)
    assert not r["valid"]

def test_ug27_rejects_bad_inputs():
    with pytest.raises(ValueError): ug27_cylindrical_shell(10, 100, 5)

def test_hydrotest_governing_reference():
    g = governing_hydrotest_minimum(10, s_test_mpa=138, s_design_mpa=100)   # ASME 1.3*10*1.38=17.94 vs décret 15
    assert g["governing"] == "ASME UG-99" and g["p_test_min_bar"] == pytest.approx(17.94)
    assert decree_hydrotest_minimum(10, "PIPELINE", "C")["p_test_min_bar"] == 12.5

def test_barlow_and_cev():
    assert barlow_pipe_thickness(10, 508, 450, 0.72)["e_mm"] == pytest.approx(10*508/(2*450*0.72), abs=1e-3)
    assert carbon_equivalent(0.2, 1.2, cr=0.1, mo=0.05, ni=0.1)["cev_iiw"] == pytest.approx(0.2+1.2/6+0.15/5+0.1/15, abs=1e-4)


# ---------- Harness : épreuve hydro, UG-27, sandbox ----------
def test_harness_hydro_no_longer_tolerates_underpressure():
    from arh_code_harness import arh_code_harness as h
    assert not h.verify_hydrotest_pressure(10, 14.6)["is_compliant_decret"]   # 1.5x = 15 ; avant : accepté (tolérance 0.5)
    assert h.verify_hydrotest_pressure(10, 15.0)["is_compliant_decret"]

def test_harness_ug27_has_longitudinal_and_validity():
    from arh_code_harness import arh_code_harness as h
    r = h.calculate_minimum_wall_thickness_asme(10, 1000, 138, 1.0, 3.0)
    assert r["t_governing_mm"] >= r["t_longitudinal_mm"] and r["validity_ok"]

def test_sandbox_timeout_and_forbidden():
    from arh_code_harness import arh_code_harness as h
    assert h.execute_sandboxed_code("x = 2*3")["result"]["x"] == 6
    assert h.execute_sandboxed_code("while True:\n    pass", timeout_sec=0.5)["status"] == "TIMEOUT"
    assert h.execute_sandboxed_code("import os")["status"] == "FORBIDDEN_OPERATION"
    assert h.execute_sandboxed_code("x = ().__class__")["status"] == "FORBIDDEN_OPERATION"
