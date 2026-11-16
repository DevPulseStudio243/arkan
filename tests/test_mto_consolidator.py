# -*- coding: utf-8 -*-
import math, os, sys, textwrap
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import openpyxl, pytest
import config_loader as cl
import mto_consolidator as mc

YAML = """
project_metadata: {project_name: "Projet test", client: "Client test"}
procurement_margins:
  cables_power: 0.08
  cable_trays: 0.05
  conduits_pvc: 0.07
  bare_copper_earthing: 0.10
  lighting_luminaires: 0.02
  accessories_hardware: 0.15
"""

@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "cfg.yaml"; p.write_text(textwrap.dedent(YAML), encoding="utf-8")
    monkeypatch.setenv(cl.ENV_PATH, str(p)); cl._CACHE.clear()

# ---------- classification : cas audités
@pytest.mark.parametrize("desc,cat,unit,expected", [
    ("SWAGED NIPPLE", "", "EA", "FITTING"),                    # était CARNET_DE_CABLES (« SWA »)
    ("STEEL SUPPORT BRACKET", "", "EA", "SUPPORTS"),           # était FITTING (« TEE »)
    ("Capteur de niveau", "", "EA", "INSTRUMENTS"),            # était FITTING (« CAP »)
    ("Presse-étoupe Ex e pour câble 1P1.5", "", "EA", "ACCESSOIRES_ELEC"),
    ("Câble d'énergie 3x120+70", "", "m", "CARNET_DE_CABLES"),
    ("CHEMINS DE CÂBLES perforés 100x50", "", "m", "CHEMINS_ET_CANALISATIONS"),
    ("Chambre de tirage 600x600x700", "PULL_BOX", "EA", "CHEMINS_ET_CANALISATIONS"),
    ("Boîte de jonction Ex e", "JUNCTION_BOX", "EA", "INSTRUMENTS"),
    ("1P1.5 mm2", "", "m", "OTHERS"),                          # était PIPE (unité m)
    ("SMLS PIPE 34\" API 5L X65", "PIPE", "M", "PIPE"),
    ("Canalisation préfabriquée", "BUSBAR_TRUNKING", "m", "DISTRIBUTION_MT_BT"),
])
def test_classification(desc, cat, unit, expected):
    assert mc.classify_item_discipline({"description": desc, "category": cat, "unit": unit}) == expected

# ---------- nombres
@pytest.mark.parametrize("raw,exp", [("12", 12.0), ("12,5", 12.5), ("1 234,5", 1234.5), ("1,234.5", 1234.5),
                                      ("35 m", 35.0), ("1,234", 1.234), (7, 7.0)])
def test_parse_number_ok(raw, exp):
    assert mc._parse_number(raw) == pytest.approx(exp)

@pytest.mark.parametrize("raw", ["3x120", "abc", "", None, "5X6"])
def test_parse_number_rejects_non_numbers(raw):
    assert mc._parse_number(raw) is None and mc._safe_float(raw, -1) == -1

def test_confidence_zero_is_not_one():
    assert mc._parse_confidence(0.0) == 0.0
    assert mc._parse_confidence(None) is None and mc._parse_confidence("n/a") is None
    assert mc._parse_confidence(85) == pytest.approx(0.85)

# ---------- éclatement des départs
FEEDER = {"category": "SWITCHGEAR_FEEDER", "tag": "300-P-101A", "designation": "Départ TGBT", "calibre_a": 63,
          "poles": "4P4D", "cable_type": "Cu/XLPE/PVC", "cable_section": "5X6", "quantity": 35.0, "unit": "m",
          "weight_unit": 0.56, "weight_total": 19.6, "source_page": 3}

def test_expand_feeders_splits_and_flags_length():
    out = mc.expand_feeders([FEEDER])
    dev, cab = out
    assert dev["unit"] == "EA" and dev["quantity"] == 1.0 and "63 A" in dev["description"]
    assert cab["category"] == "CABLE" and cab["unit"] == "m" and cab["quantity"] == 35.0
    assert any("non mesurée" in r for r in cab["extractor_reasons"])
    assert mc.expand_feeders(out) == out                       # idempotent

def test_measured_length_not_flagged():
    cab = mc.expand_feeders([dict(FEEDER, length_source="CARNET")])[1]
    assert cab["extractor_reasons"] == []

def test_busbar_not_a_cable():
    cab = mc.expand_feeders([dict(FEEDER, cable_section="CANALISATION")])[1]
    assert cab["category"] == "BUSBAR_TRUNKING"
    assert mc.classify_item_discipline(cab) == "DISTRIBUTION_MT_BT"

# ---------- export Excel de bout en bout
ITEMS = [
    {"category": "PULL_BOX", "tag": "CH-1", "description": "Chambre de tirage", "quantity": 3, "unit": "EA", "weight_total": 255.0, "confidence_score": 0.95},
    {"category": "CABLE_TRAY", "tag": "CDC-100", "description": "Chemin de câbles 100x50", "quantity": 100, "unit": "m", "weight_total": 190.0, "confidence_score": 0.95},
    {"category": "EARTH_ROD", "tag": "PQ", "description": "Piquet de terre", "quantity": 10, "unit": "EA", "weight_total": 45.0},
    FEEDER,
]

def run(items, tmp_path, anomalies=None):
    out = tmp_path / "o.xlsx"
    mc.generate_master_multidiscipline_excel(items, {"filename": "t.pdf"}, anomalies or [], str(out))
    return openpyxl.load_workbook(out)

def kpi(wb, label_start):
    ws = wb["SYNTHESE_GLOBALE"]
    for r in range(5, 20):
        v = ws.cell(row=r, column=1).value
        if v and str(v).startswith(label_start):
            return ws.cell(row=r, column=4).value
    raise AssertionError(label_start)

def test_units_are_not_mixed(tmp_path):
    wb = run([dict(i) for i in ITEMS], tmp_path)
    assert kpi(wb, "Linéaire de chemins") == pytest.approx(100.0)          # avant : 103 (chambres comptées en m)
    assert kpi(wb, "Chambres, buses") == pytest.approx(3.0)
    assert kpi(wb, "Piquets") == pytest.approx(10.0)
    assert kpi(wb, "Linéaire de câbles") == pytest.approx(35.0)            # câble du départ SLD enfin compté
    assert isinstance(kpi(wb, "Poids total acier"), (int, float))                  # numérique, plus du texte

def test_feeder_appears_in_both_tabs(tmp_path):
    wb = run([dict(i) for i in ITEMS], tmp_path)
    dist = [r[2] for r in wb["DISTRIBUTION_MT_BT"].iter_rows(min_row=2, values_only=True) if r[2]]
    assert any("Départ protégé 300-P-101A" in str(d) and "63 A" in str(d) for d in dist)
    cab = [r[2] for r in wb["CARNET_DE_CABLES"].iter_rows(min_row=2, values_only=True) if r[2]]
    assert any("5X6" in str(d) for d in cab)

def test_totals_per_unit_formulas(tmp_path):
    ws = run([dict(i) for i in ITEMS], tmp_path)["CHEMINS_ET_CANALISATIONS"]
    labels = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
    assert any(str(l).startswith("TOTAL PAR UNITÉ [EA]") for l in labels if l)
    assert any(str(l).startswith("TOTAL PAR UNITÉ [M]") for l in labels if l)

def test_margins_by_category_and_rounding(tmp_path):
    items = [dict(i) for i in ITEMS]
    run(items, tmp_path)
    by_tag = {i["tag"]: i for i in items}
    assert by_tag["CDC-100"]["quantity_ordered"] == pytest.approx(105.0)    # 5 %
    assert by_tag["CH-1"]["quantity_ordered"] == 3.0                        # équipement : 0 %, plus de 3,3
    assert by_tag["CH-1"]["procurement_margin_percent"] == "0%"

def test_a_valider_is_populated_honestly(tmp_path):
    items = [dict(i) for i in ITEMS] + [{"category": "CABLE_TRAY", "tag": "X", "description": "zéro confiance", "quantity": 5, "unit": "m", "confidence_score": 0.0}]
    wb = run(items, tmp_path)
    tags = [r[1] for r in wb["A_VALIDER"].iter_rows(min_row=2, values_only=True) if r[1]]
    assert "X" in tags                                         # 0,0 n'est plus transformé en 1,0
    assert "C-300-P-101A-PWR" in tags                           # longueur 35 m non mesurée
    assert kpi(wb, "Lignes sans score") >= 1                    # lignes non évaluées signalées

def test_none_confidence_does_not_crash(tmp_path):
    run([{"category": "CABLE_TRAY", "tag": "T", "description": "x", "quantity": 1, "unit": "m", "confidence_score": None}], tmp_path)

def test_undefined_margin_flagged_for_electrical(tmp_path):
    items = [{"category": "CABLE_INSTRUMENT", "tag": "I1", "description": "Câble instrumentation 1P1.5", "quantity": 100, "unit": "m", "confidence_score": 0.9}]
    wb = run(items, tmp_path)                                   # CABLE_INSTRUMENT -> pas de marge dans ce YAML
    ws = wb["A_VALIDER"]
    obs = [r[16] for r in ws.iter_rows(min_row=2, values_only=True) if r[1] == "I1"]
    assert obs and "marge" in obs[0]

def test_formula_injection_neutralized_and_no_apostrophe(tmp_path):
    items = [{"category": "CABLE_TRAY", "tag": "-", "description": "=HYPERLINK(\"http://x\",\"c\")", "quantity": 1, "unit": "m", "confidence_score": 0.9}]
    wb = run(items, tmp_path)
    ws = wb["CHEMINS_ET_CANALISATIONS"]
    c = ws["C2"]
    assert c.data_type == "s" and str(c.value).startswith("=HYPERLINK")
    assert ws["B2"].value == "-"                                # plus de « '- »
    ws2 = run([dict(i) for i in ITEMS], tmp_path)["CHEMINS_ET_CANALISATIONS"]
    sums = [c.value for row in ws2.iter_rows() for c in row if c.data_type == "f"]
    assert sums and all(str(s).startswith(("=SUMIF(", "=SUM(")) for s in sums)

def test_matrix_handles_warning_info_and_injection(tmp_path):
    an = [{"rule": "R1", "severity": "WARNING", "tag": "=1+1", "title": "t", "message": "m"},
          {"rule": "R2", "severity": "INFO", "tag": "T", "title": "t"}]
    ws = run([dict(ITEMS[1])], tmp_path, an)["MATRICE_RESERVES_GLOBALE"]
    assert ws["C2"].value == "WARNING" and ws["C3"].value == "INFO"
    assert ws["D2"].data_type == "s"

def test_config_source_printed(tmp_path):
    ws = run([dict(ITEMS[1])], tmp_path)["SYNTHESE_GLOBALE"]
    assert "Configuration :" in ws["A3"].value and "Projet test" in ws["A2"].value and "Client test" in ws["A2"].value

def test_missing_config_is_visible(tmp_path, monkeypatch):
    monkeypatch.setenv(cl.ENV_PATH, str(tmp_path / "nope.yaml")); cl._CACHE.clear()
    ws = run([dict(ITEMS[1])], tmp_path)["SYNTHESE_GLOBALE"]
    assert "DEFAULTS" in ws["A3"].value

# ---------- tuyauterie : surfaces
def test_paint_surface_uses_pipe_diameter():
    plans = [{"filename": "iso1", "metadata": {}, "mto": [{"category": "PIPE", "description": "SMLS PIPE", "size": '34"', "unit": "M", "quantity": 100}]}]
    st = mc.consolidate_mto_items(plans)["global_stats"]
    assert st["total_paint_m2"] == pytest.approx(math.pi * 0.8636 * 100, rel=1e-3)     # ≈ 271 m² (avant : 35)
    assert st["paint_unresolved_pipe_m"] == 0

def test_od_parsing():
    assert mc._pipe_od_m('2"') == pytest.approx(0.0603)
    assert mc._pipe_od_m("1-1/2\"") == pytest.approx(0.0483)
    assert mc._pipe_od_m("DN300") == pytest.approx(0.3239)
    assert mc._pipe_od_m("34") == pytest.approx(0.8636)
    assert mc._pipe_od_m("n/a") is None


def test_consolidation_keeps_distinct_ei_tags_apart_and_counts_units_separately():
    plans = [{"filename": "a", "metadata": {}, "mto": [
        {"category": "SWITCHGEAR_FEEDER", "tag": "300-P-101A", "description": "Départ protégé", "unit": "EA", "quantity": 1},
        {"category": "SWITCHGEAR_FEEDER", "tag": "300-P-102A", "description": "Départ protégé", "unit": "EA", "quantity": 1},
        {"category": "PIPE", "description": "SMLS PIPE", "size": '2"', "unit": "M", "quantity": 100},
        {"category": "VALVE", "description": "Ball valve", "size": '2"', "unit": "EA", "quantity": 4},
        {"category": "VALVE", "description": "Ball valve", "size": '2"', "unit": "EA", "quantity": 2}]}]
    r = mc.consolidate_mto_items(plans)
    feeders = [i for i in r["consolidated_items"] if "Départ" in i.get("description", "") or i.get("tag", "").startswith("DIS")]
    assert r["global_stats"]["total_lines"] == 4                      # 2 départs distincts + 1 tube + 1 vanne fusionnée (4+2)
    assert r["global_stats"]["total_items"] == 2 + 6                  # pièces seulement : les 100 m ne comptent plus
    assert r["global_stats"]["quantity_by_unit"] == {"EA": 8.0, "M": 100.0}
