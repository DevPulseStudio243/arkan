# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from tag_normalizer import TagNormalizer

@pytest.fixture
def tn():
    return TagNormalizer(config={"tag_normalization": {"aliases": {"POMPE HUILE": "300-P-102A"}}})

# --- Cas audités : ces appariements étaient FAUX dans la version précédente
@pytest.mark.parametrize("a,b", [
    ("FV-0102", "FV-0103"), ("PT-0102", "PT-0103"),
    ("300-P-101A", "400-P-101A"), ("P-101A", "P-101B"),
    ("P-10100", "P-10101"), ("PT-0102", "TT-0102"),
])
def test_distinct_equipment_never_match(tn, a, b):
    ok, score, kind = tn.match_tags(a, b)
    assert ok is False, (a, b, kind)

@pytest.mark.parametrize("a,b,kind", [
    ("300-P-101A", "300-P-101A", "EXACT"),
    ("300-P-101A", "300P101A", "CANONICAL_EXACT"),
    ("P101A", "P-101A", "CANONICAL_EXACT"),
    ("P-101A", "300-P-101A", "UNIT_PREFIX_MISSING"),
    ("FV-0102", "FV-102", "NUMBER_PADDING"),
    ("P-101", "P-101A", "PARTIAL_SUFFIX_MATCH"),
])
def test_legitimate_matches(tn, a, b, kind):
    ok, score, k = tn.match_tags(a, b)
    assert ok and k == kind, (a, b, k)

def test_unit_prefix_preserved(tn):
    assert tn.canonical_tag("300-P-101A") == "300-P-101A"
    assert tn.canonical_tag("P101A") == "P-101A"
    assert tn.canonical_tag("300-MCC-01") == "300-MCC-01"
    assert tn.canonical_tag("TRP-3") == "TRP-3"

def test_compressors_not_mistaken_for_cables(tn):
    assert tn.canonical_tag("K-101") == "K-101"
    assert tn.canonical_tag("C-101A") == "C-101A"

def test_cable_tag_resolves_to_equipment(tn):
    d = tn.decompose_tag("C-300-P-101A-PWR")
    assert d["canonical"] == "300-P-101A" and d["cable_function"] == "PWR"
    ok, _, _ = tn.match_tags("C-300-P-101A-PWR", "300-P-101A")
    assert ok

def test_aliases_come_from_config_only():
    assert TagNormalizer(config={}).aliases == {}
    t = TagNormalizer(config={"tag_normalization": {"aliases": {"pompe huile": "300-p-102a"}}})
    assert t.canonical_tag("POMPE HUILE") == "300-P-102A"
    assert t.match_tags("pompe huile", "300-P-102A")[0]

def test_config_does_not_remove_instrument_types():
    t = TagNormalizer(config={"tag_normalization": {"valid_equipment_types": ["P", "C"]}})
    assert {"FV", "PT", "XV", "PSV", "K"} <= t.valid_types

def test_fuzzy_never_when_digits_differ(tn):
    assert tn.match_tags("POMPE REFRIGERANT 101", "POMPE REFRIGERANT 102")[0] is False
    assert tn.match_tags("POMPE REFRIGERANT HUILE", "POMPE REFRIGERANT HUILES")[0] is True

def test_extract_tags_from_label(tn):
    assert tn.extract_tags("POMPE REFRIGERANT P101A") == ["P-101A"]
    assert tn.extract_tags("Départ 300-P-101A / 300-P-101B") == ["300-P-101A", "300-P-101B"]

def test_empty_and_none(tn):
    assert tn.match_tags("", "P-101A") == (False, 0.0, "NO_MATCH")
    assert tn.canonical_tag(None) == ""
