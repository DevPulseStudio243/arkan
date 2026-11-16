"""
tests/test_line_list_normalizer.py
==================================
Tests unitaires et d'intégration pour line_list_normalizer.py.
Vérifie :
  - Conversion normalisée ASME B36.10M / ISO 6708 (NPS -> DN)
  - Décomposition des métadonnées de tag
  - Filtrage strict à 100% des runs sans tag (élimination du bruit fantôme)
  - Dédoublonnement et consolidation par tag unique
  - Résolution des connecteurs hors-page (Off-Page Connectors)
  - Exhaustivité des clés requises par l'UI
"""

import pytest
from line_list_normalizer import (
    NPS_TO_DN,
    convert_nps_to_dn,
    parse_line_tag_metadata,
    clean_mtext_formatting,
    extract_off_page_connectors,
    normalize_pid_line_list,
)


def test_asme_b36_10m_nps_to_dn():
    """Vérifie la conformité exacte des correspondances NPS -> DN selon ASME B36.10M."""
    assert convert_nps_to_dn("1/2") == "DN15"
    assert convert_nps_to_dn("0.5") == "DN15"
    assert convert_nps_to_dn("3/4") == "DN20"
    assert convert_nps_to_dn("1") == "DN25"
    assert convert_nps_to_dn("1.5") == "DN40"
    assert convert_nps_to_dn("2") == "DN50"
    assert convert_nps_to_dn("3") == "DN80"
    assert convert_nps_to_dn("4") == "DN100"
    assert convert_nps_to_dn("6") == "DN150"
    assert convert_nps_to_dn("8") == "DN200"
    assert convert_nps_to_dn("10") == "DN250"
    assert convert_nps_to_dn("12") == "DN300"
    assert convert_nps_to_dn("14") == "DN350"
    assert convert_nps_to_dn("16") == "DN400"
    assert convert_nps_to_dn("20") == "DN500"
    assert convert_nps_to_dn("24") == "DN600"
    assert convert_nps_to_dn("28") == "DN700"
    assert convert_nps_to_dn("30") == "DN750"
    assert convert_nps_to_dn("34") == "DN850"
    assert convert_nps_to_dn("40") == "DN1000"


def test_clean_mtext_formatting():
    """Vérifie l'élimination des balises MTEXT AutoCAD."""
    raw = r"{\H1.2x;\S1#2;34\"-LP-1ACX1PN-101-N\P}"
    cleaned = clean_mtext_formatting(raw)
    assert cleaned == '1/2 34"-LP-1ACX1PN-101-N'

    raw_simple = r"{\fArial|b0|i0|c0|p34;VERS PLAN C3421-ROK1-300-PRC-DM-300005}"
    assert clean_mtext_formatting(raw_simple) == "VERS PLAN C3421-ROK1-300-PRC-DM-300005"


def test_parse_line_tag_metadata():
    """Vérifie la décomposition des tags standards EPC."""
    # Standard EPC
    m1 = parse_line_tag_metadata('34"-LP-1ACX1PN-101-N')
    assert m1["nps"] == "34"
    assert m1["fluid"] == "LP"
    assert m1["spec"] == "1ACX1PN"
    assert m1["seq"] == "101"
    assert m1["insul"] == "N"

    # Avec fraction
    m2 = parse_line_tag_metadata('1/2"-IA-1ACX1PN-501-N')
    assert m2["nps"] == "1/2"
    assert m2["fluid"] == "IA"
    assert m2["seq"] == "501"

    # Format alternatif
    m3 = parse_line_tag_metadata('6"-P-101-CS')
    assert m3["nps"] == "6"
    assert m3["fluid"] == "P"
    assert m3["seq"] == "101"


def test_filtrage_strict_eliminate_ghost_runs():
    """Vérifie que 100% des runs sans tag (bruit fantôme) sont ignorés."""
    raw_lines = [
        {"id": f"L-{i}", "tag_raw": None, "segments": [[[0, 0], [10, 0]]]}
        for i in range(100)
    ]
    # Ajouter 2 vraies lignes étiquetées
    raw_lines.append({
        "id": "L-REAL-1",
        "tag_raw": '34"-LP-1ACX1PN-101-N',
        "nps": "34",
        "fluid": "LP",
        "spec": "1ACX1PN",
        "segments": [[[100, 200], [300, 200]]]
    })
    raw_lines.append({
        "id": "L-REAL-2",
        "tag_raw": '24"-LP-1ACX1PN-102-N',
        "nps": "24",
        "fluid": "LP",
        "spec": "1ACX1PN",
        "segments": [[[300, 200], [500, 200]]]
    })

    result = normalize_pid_line_list(raw_lines, drawing_stem="TEST-STEM")
    assert len(result) == 2
    assert result[0]["line_number"] in ('24"-LP-1ACX1PN-102-N', '34"-LP-1ACX1PN-101-N')
    assert result[1]["line_number"] in ('24"-LP-1ACX1PN-102-N', '34"-LP-1ACX1PN-101-N')


def test_deduplication_and_length_cumulation():
    """Vérifie que plusieurs tronçons avec le même tag sont fusionnés avec calcul de longueur cumulée."""
    raw_lines = [
        {
            "id": "L-1",
            "tag_raw": '34"-LP-1ACX1PN-101-N',
            "nps": "34",
            "fluid": "LP",
            "spec": "1ACX1PN",
            "segments": [[[0.0, 0.0], [100.0, 0.0]]],  # longueur 100
            "valves": ["V-101"]
        },
        {
            "id": "L-2",
            "tag_raw": '34"-LP-1ACX1PN-101-N',
            "nps": "34",
            "fluid": "LP",
            "spec": "1ACX1PN",
            "segments": [[[100.0, 0.0], [100.0, 50.0]]],  # longueur 50
            "valves": ["V-102"]
        },
        {
            "id": "L-3",
            "tag_raw": '34"-LP-1ACX1PN-101-N',
            "nps": "34",
            "fluid": "LP",
            "spec": "1ACX1PN",
            "segments": [[[100.0, 50.0], [200.0, 50.0]]],  # longueur 100
            "valves": ["V-101"]  # doublon de vanne
        }
    ]

    result = normalize_pid_line_list(raw_lines, drawing_stem="DWG-001")
    assert len(result) == 1
    res = result[0]
    assert res["line_number"] == '34"-LP-1ACX1PN-101-N'
    assert res["total_length"] == 250.0
    assert res["runs_merged"] == 3
    assert res["segments_count"] == 3
    assert sorted(res["valves"]) == ["V-101", "V-102"]
    assert res["size"] == '34"'
    assert res["dn"] == "DN850"
    assert res["pid_number"] == "DWG-001"


def test_off_page_connectors_resolution():
    """Vérifie la résolution des renvois hors-page situés à proximité des extrémités libres."""
    raw_lines = [
        {
            "id": "L-1",
            "tag_raw": '34"-LP-6UCF1RN-304-X',
            "nps": "34",
            "fluid": "LP",
            "spec": "6UCF1RN",
            "segments": [
                [[100.0, 200.0], [500.0, 200.0]],
                [[500.0, 200.0], [600.0, 200.0]]
            ],
            "from_equipment": None,
            "to_equipment": None
        }
    ]

    opcs = [
        {"text": "C3421-ROK1-300-PRC-DM-300005", "pos": [80.0, 205.0]},   # proche du début (d ~ 20u)
        {"text": "VERS ARZEW", "pos": [615.0, 200.0]}                      # proche de la fin (d ~ 15u)
    ]

    result = normalize_pid_line_list(raw_lines, off_page_connectors=opcs, drawing_stem="081")
    assert len(result) == 1
    res = result[0]
    assert "C3421-ROK1-300-PRC-DM-300005" in res["from_equipment"]
    assert res["to_equipment"] == "VERS ARZEW"
    assert res["flow_path"] == f"{res['from_equipment']} ➔ [{res['line_number']}] ➔ VERS ARZEW"


def test_connected_equipment_priority_over_opc():
    """Vérifie qu'un équipement raccordé (cuve, pompe) reste prioritaire sur un renvoi lointain."""
    equipments = [
        {"id": "E-TK101", "kind": "equipment", "tag": "TK-101", "position": [100.0, 200.0]}
    ]

    raw_lines = [
        {
            "id": "L-1",
            "tag_raw": '10"-P-101-CS',
            "nps": "10",
            "fluid": "P",
            "spec": "CS",
            "connects": ["E-TK101"],
            "segments": [[[100.0, 200.0], [400.0, 200.0]]],
            "from_equipment": "TK-101",
            "to_equipment": None
        }
    ]

    opcs = [
        {"text": "VERS BEJAIA", "pos": [415.0, 200.0]}
    ]

    result = normalize_pid_line_list(raw_lines, off_page_connectors=opcs, equipments=equipments, drawing_stem="DWG-TK")
    assert len(result) == 1
    res = result[0]
    assert res["from_equipment"] == "TK-101"
    assert res["to_equipment"] == "VERS BEJAIA"
    assert res["dn"] == "DN250"
