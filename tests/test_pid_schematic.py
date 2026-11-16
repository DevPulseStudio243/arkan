"""
test_pid_schematic.py
=====================
Tests unitaires pour pid_schematic.py (Reconstructeur Simplifié de Plan P&ID).
"""

import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pid_schematic
from pid_schematic import render_schematic, FLUID_COLORS, FLUID_LABELS


def test_fluid_dictionary_coverage():
    """Vérifie la présence et validité des 16 fluides obligatoires du dictionnaire étendu."""
    required_fluids = ["P", "G", "L", "W", "FG", "FW", "IA", "F", "D", "V", "LP", "HP", "MP", "DC", "CW", "N2"]
    for fl in required_fluids:
        assert fl in FLUID_COLORS, f"Le fluide '{fl}' est absent de FLUID_COLORS"
        color = FLUID_COLORS[fl]
        assert color.startswith("#") and len(color) == 7, f"Couleur invalide pour '{fl}': {color}"
        assert fl in FLUID_LABELS, f"Le libellé du fluide '{fl}' est absent de FLUID_LABELS"


def test_render_schematic_synthetic(tmp_path):
    """Vérifie le rendu vectoriel SVG complet sur données synthétiques P&ID."""
    synthetic_data = {
        "titleblock": {
            "title": "SYNTHETIC WATER & PROCESS UNIT",
            "drawing_number": "DWG-TEST-001",
            "revision": "B",
        },
        "lines": [
            {
                "id": "L-001",
                "tag_raw": '4"-P-101-CS',
                "fluid": "P",
                "segments": [[[100.0, 200.0], [500.0, 200.0]]],
            },
            {
                "id": "L-002",
                "tag_raw": '2"-LP-202-SS',
                "fluid": "LP",
                "segments": [[[500.0, 200.0], [500.0, 400.0]]],
            },
            {
                "id": "L-003",
                "tag_raw": '1"-IA-303-CS',
                "fluid": "IA",
                "segments": [[[200.0, 200.0], [200.0, 100.0]]],
            },
        ],
        "elements": [
            {
                "id": "E-001",
                "kind": "equipment",
                "tag": "201-PP-001",
                "position": [100.0, 200.0],
                "bbox": [80.0, 180.0, 120.0, 220.0],
            },
            {
                "id": "V-001",
                "kind": "valve",
                "tag": "201-HV-001",
                "position": [300.0, 200.0],
                "bbox": [290.0, 195.0, 310.0, 205.0],
                "on_line": "L-001",
            },
            {
                "id": "I-001",
                "kind": "instrument",
                "tag": "PIT-217",
                "position": [200.0, 100.0],
                "bbox": [190.0, 90.0, 210.0, 110.0],
                "parts": {"pre": "PIT", "loop": "217"},
            },
        ],
        "equipment_candidates": [
            {
                "id": "EQC-01",
                "tags": ["201-TK-001"],
                "proposed_block": "STORAGE_TANK",
                "bbox": [480.0, 380.0, 520.0, 420.0],
            }
        ],
    }

    out_file = tmp_path / "test_schematic.svg"
    svg = render_schematic(synthetic_data, out_file)

    # 1. Structure du SVG
    assert svg.startswith("<svg")
    assert 'width="100%"' in svg
    assert 'height="100%"' in svg
    assert "viewBox=" in svg
    assert out_file.exists()
    assert out_file.stat().st_size > 500

    # 2. Présence obligatoire des classes et attributs interactifs
    assert 'class="pid-schematic-element' in svg
    assert 'pid-equipment-group' in svg
    assert 'class="eq-info-bubble"' in svg
    assert 'data-lines=' in svg
    assert 'data-loops=' in svg
    assert 'data-fluid=' in svg
    assert 'data-bbox=' in svg
    assert 'data-confidence=' in svg
    assert 'style="cursor:pointer;"' in svg
    assert 'data-tag="201-PP-001"' in svg
    assert 'data-kind="equipment"' in svg
    assert 'data-tag="201-HV-001"' in svg
    assert 'data-kind="valve"' in svg
    assert 'data-tag="PIT-217"' in svg
    assert 'data-kind="instrument"' in svg
    assert 'data-tag="201-TK-001"' in svg
    assert 'data-cx=' in svg
    assert 'data-cy=' in svg

    # 3. Tracé des éléments spécifiques
    # Vannes en nœud papillon
    assert "<polygon" in svg
    # Bulles d'instruments ISA-5.1
    assert "<circle" in svg
    assert "PIT" in svg
    assert "217" in svg
    # Boîtes d'équipements arrondies
    assert 'rx="8"' in svg

    # 4. Panneau d'annotations en bas
    assert '<g id="annotations-panel">' in svg
    assert "SYNTHETIC WATER &amp; PROCESS UNIT" in svg
    assert "DWG-TEST-001" in svg


def test_render_schematic_empty_and_corrupt_data(tmp_path):
    """Vérifie la robustesse en cas de données vides, None ou corrompues (aucun crash)."""
    # Test None
    svg_none = render_schematic(None)
    assert "<svg" in svg_none
    assert '<g id="annotations-panel">' in svg_none
    assert 'width="100%"' in svg_none

    # Test dictionnaire vide
    svg_empty = render_schematic({})
    assert "<svg" in svg_empty
    assert '<g id="annotations-panel">' in svg_empty

    # Test avec out_svg_path
    out_file = tmp_path / "empty.svg"
    svg_written = render_schematic({}, out_file)
    assert out_file.exists()
    assert out_file.stat().st_size > 100
