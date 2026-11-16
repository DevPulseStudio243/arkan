# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from cable_parser import parse_cable
from ie_mto_validator import calculate_iec_pe_section as pe, validate_ie_mto

CFG = {"normative_rules": {"earthing_pe": {}, "cable_trays": {"max_filling_ratio": 0.40}}}

@pytest.mark.parametrize("phase,exp", [(10, 10), (16, 16), (25, 16), (35, 16), (70, 35), (95, 50), (120, 70),
                                       (150, 95), (185, 95), (240, 120), (400, 240)])
def test_pe_three_tiers(phase, exp):
    assert pe(phase) == exp

def test_pe_beyond_table_is_none():
    assert pe(1000) is None

@pytest.mark.parametrize("spec,n,s,pe_core,red,role", [
    ("5X6", 5, 6, False, None, None), ("3X120+70", 3, 120, False, 70, "UNSPECIFIED"),
    ("4G25", 4, 25, True, None, None), ("3G1.5", 3, 1.5, True, None, None),
    ("3X120+PE70", 3, 120, False, 70, "PE"), ("3x50+N25 mm²", 3, 50, False, 25, "N"),
    ("3X25+16", 3, 25, False, 16, "UNSPECIFIED"), ("5G2,5", 5, 2.5, True, None, None)])
def test_parse_power(spec, n, s, pe_core, red, role):
    p = parse_cable(spec)
    assert (p["n_conductors"], p["section_mm2"], p["has_pe_core"], p["reduced_section_mm2"], p["reduced_role"]) == (n, s, pe_core, red, role)

def test_parse_parallel_and_pairs_and_garbage():
    assert parse_cable("2X(3X240)")["parallel_runs"] == 2
    assert parse_cable("12P0.75")["n_pairs"] == 12
    assert parse_cable("5X6")["section_mm2"] == 6          # ancien code : 5
    assert parse_cable("CANALISATION") is None and parse_cable("") is None

def feeder(spec, **kw):
    return dict({"category": "CABLE", "tag": "T1", "cable_section": spec, "quantity": 10}, **kw)

def rules(items, cfg=CFG):
    return [(a["rule"], a["severity"]) for a in validate_ie_mto(items, config=cfg)]

def test_explicit_pe_too_small_is_critical():
    assert ("MALT_01_PE_SECTION", "CRITICAL") in rules([feeder("3X120+PE35")])

def test_unspecified_reduced_conductor_is_warning_not_critical():
    r = rules([feeder("3X120+35")])
    assert ("MALT_01_PE_SECTION", "WARNING") in r and ("MALT_01_PE_SECTION", "CRITICAL") not in r

def test_ok_cases_raise_nothing():
    for spec in ("3X120+70", "4G25", "5G6", "3X120+N70", "3X25+16"):
        assert [x for x in rules([feeder(spec)]) if x[0].startswith("MALT")] == [], spec

def test_unparseable_is_reported_not_guessed():
    assert ("CABLE_00_UNPARSED", "WARNING") in rules([feeder("???")])

def test_severities_are_in_schema():
    items = [feeder("3X120+PE35"), feeder("3X120+35"), feeder("???"), {"category": "CABLE_TRAY", "tag": "C", "size": "300x50"}]
    assert {s for _, s in rules(items)} <= {"CRITICAL", "WARNING", "INFO"}

def test_iz_not_evaluated_without_table_no_invented_overcurrent():
    r = rules([feeder("5X6", calibre_a=63)])
    assert ("PUISSANCE_01_NOT_EVALUATED", "INFO") in r and not any(x[0] == "PUISSANCE_01_OVERCURRENT" for x in r)

def test_iz_with_table_flags_overcurrent_and_undersized():
    cfg = {"normative_rules": {"current_capacity": {"iz_by_method": {"E": {6: 36, 25: 101}}}}}
    a = validate_ie_mto([feeder("5X6", calibre_a=63, installation_method="E", derating_factor=0.82, ib_a=10)], config=cfg)
    assert any(x["rule"] == "PUISSANCE_01_OVERCURRENT" and x["severity"] == "CRITICAL" for x in a)
    b = validate_ie_mto([feeder("4G25", calibre_a=40, installation_method="E", ib_a=60)], config=cfg)
    assert any(x["rule"] == "PUISSANCE_01_UNDERSIZED" for x in b)
    assert not any(x["rule"] == "PUISSANCE_01_OVERCURRENT" for x in b)

def test_fill_not_evaluated_without_routing_data():
    r = rules([{"category": "CABLE_TRAY", "tag": "CDC", "size": "300x50 mm"}, feeder("5X6")])
    assert ("CHEMIN_01_FILLING_NOT_EVALUATED", "INFO") in r

def test_fill_ratio_uses_pi_over_4_d2():
    tray = {"category": "CABLE_TRAY", "tag": "CDC", "size": "300x50 mm", "route_id": "R1"}
    ok = [dict(feeder("5X6"), route_id="R1", outer_diameter_mm=20, count=10)]       # 3142 / 15000 = 21 %
    bad = [dict(feeder("5X6"), route_id="R1", outer_diameter_mm=20, count=30)]      # 9425 / 15000 = 63 %
    assert not any(x[0] == "CHEMIN_01_OCCUPATION" for x in rules([tray] + ok))
    assert ("CHEMIN_01_OCCUPATION", "CRITICAL") in rules([tray] + bad)

def test_old_length_ratio_rule_is_gone():
    # ancien code : (Σ longueurs câbles / Σ longueurs chemins) > 12 -> « remplissage > 40 % » (sans sens physique)
    items = [feeder("5X6", quantity=1000), {"category": "CABLE_TRAY", "tag": "C", "size": "100x50", "quantity": 10}]
    assert not any(x[0].startswith("CHEMIN_01_OCC") for x in rules(items))
