"""
tests/test_smart_schematic_engine.py
====================================
Tests unitaires et de validation du moteur Smart Filtered Vector P&ID (pid_schematic_engine.py).
Vérifie :
  - Élimination à 100% des calques parasites (cartouche, cotes, revcloud, quadrillage)
  - Toile dynamique (viewBox auto-adaptative avec 5% de marge, zéro canvas fixe)
  - Dédoublonnement strict des étiquettes (une étiquette unique avec masque blanc opaque par ligne)
  - Palette des couleurs industrielles ASME/ISO
  - Rendu des symboles ISA-5.1 (vannes en nœud papillon, bulles d'instruments)
"""

import re
import pytest
from pid_schematic_engine import (
    PidSchematicEngine,
    is_parasite_layer,
    FLUID_COLORS,
    DEFAULT_FLUID_COLOR,
)


def test_parasite_layers_filtering():
    """Vérifie l'exclusion rigoureuse des calques parasites et la conservation des calques procédé."""
    # Doivent être éliminés
    assert is_parasite_layer("CARTOUCHE") is True
    assert is_parasite_layer("BORDER_A1") is True
    assert is_parasite_layer("CADRE_TITRE") is True
    assert is_parasite_layer("DIM_COTATION") is True
    assert is_parasite_layer("REVCLOUD") is True
    assert is_parasite_layer("GRID_COORDS") is True
    assert is_parasite_layer("DEFPOINTS") is True
    assert is_parasite_layer("VIEWPORT") is True

    # Doivent être conservés
    assert is_parasite_layer("PIPE") is False
    assert is_parasite_layer("PROC") is False
    assert is_parasite_layer("PROCESS_LINE") is False
    assert is_parasite_layer("0") is False
    assert is_parasite_layer("VALVE") is False
    assert is_parasite_layer("INST") is False
    assert is_parasite_layer("EQT") is False
    assert is_parasite_layer("EQUIPMENT") is False


def test_dynamic_viewbox_and_canvas():
    """Vérifie que le viewBox est calculé dynamiquement selon la bbox procédé avec 5% de marge."""
    sem_data = {
        "lines": [
            {
                "line_number": '34"-LP-1ACX1PN-101-N',
                "fluid": "LP",
                "segments": [
                    [[100.0, 200.0], [500.0, 200.0]],
                    [[500.0, 200.0], [500.0, 600.0]]
                ]
            }
        ],
        "elements": [
            {
                "tag": "TK-101",
                "kind": "equipment",
                "position": [100.0, 200.0],
                "bbox": [80.0, 160.0, 120.0, 240.0]
            }
        ],
        "titleblock": {"drawing_number": "PLAN-TEST-001"}
    }

    engine = PidSchematicEngine()
    svg = engine.render_semantic(sem_data)

    # Récupérer le viewBox
    m = re.search(r'viewBox="([^"]+)"', svg)
    assert m is not None, "viewBox manquant dans le SVG"
    parts = [float(x) for x in m.group(1).split()]
    assert len(parts) == 4
    min_x, min_y, vb_w, vb_h = parts

    # Vérifier que le canvas N'EST PAS le canvas fixe artificiel 1600x1000
    assert (vb_w, vb_h) != (1600.0, 1000.0)
    # L'emprise X va de ~80 à 500 (span ~420), avec marge 5% (~25) -> vb_w ~470
    assert 400.0 <= vb_w <= 600.0
    # L'emprise Y va de ~160 à 600 (span ~440), avec marge 5% et panneau légende -> vb_h ~500-600
    assert 450.0 <= vb_h <= 650.0


def test_label_deduplication_single_tag_with_white_mask():
    """Vérifie qu'une ligne composée de multiples segments ne génère QU'UNE SEULE étiquette masquée."""
    sem_data = {
        "lines": [
            {
                "line_number": '34"-LP-1ACX1PN-101-N',
                "fluid": "LP",
                "segments": [
                    [[100.0, 100.0], [200.0, 100.0]],
                    [[200.0, 100.0], [200.0, 300.0]],
                    [[200.0, 300.0], [500.0, 300.0]],
                    [[500.0, 300.0], [500.0, 400.0]],
                    [[500.0, 400.0], [600.0, 400.0]]
                ]
            }
        ],
        "elements": [],
        "titleblock": {"drawing_number": "DEDUP-TEST"}
    }

    engine = PidSchematicEngine()
    svg = engine.render_semantic(sem_data)

    # Compter les occurrences de l'étiquette de ligne
    occurrences = len(re.findall(r'<g class="pid-schematic-element pid-line-tag-element"[^>]*>', svg))
    assert occurrences == 1, f"Attendu: 1 seule étiquette dédoublonnée, Obtenu: {occurrences}"

    # Vérifier la présence du masque de fond blanc opaque pour garantir zéro collision et zéro pâté noir
    assert 'fill="#ffffff"' in svg
    assert 'rx="3"' in svg
    assert 'stroke="#059669"' in svg  # Couleur verte ASME pour LP (Low Pressure)


def test_asme_fluid_colors_application():
    """Vérifie l'application fidèle des couleurs de fluides selon ASME/ISO."""
    sem_data = {
        "lines": [
            {
                "line_number": '24"-P-101-CS',
                "fluid": "P",
                "segments": [[[0.0, 0.0], [100.0, 0.0]]]
            },
            {
                "line_number": '8"-FW-201-CS',
                "fluid": "FW",
                "segments": [[[0.0, 50.0], [100.0, 50.0]]]
            },
            {
                "line_number": '2"-IA-301-SS',
                "fluid": "IA",
                "segments": [[[0.0, 100.0], [100.0, 100.0]]]
            }
        ],
        "elements": [],
        "titleblock": {"drawing_number": "COLORS-TEST"}
    }

    engine = PidSchematicEngine()
    svg = engine.render_semantic(sem_data)

    # Fluide P -> Ambre #d97706
    assert FLUID_COLORS["P"] in svg
    # Fluide FW -> Rouge #dc2626
    assert FLUID_COLORS["FW"] in svg
    # Fluide IA -> Violet #7c3aed
    assert FLUID_COLORS["IA"] in svg


def test_symbols_isa_5_1_rendering():
    """Vérifie le rendu des vannes nœud papillon et bulles d'instruments ISA-5.1."""
    sem_data = {
        "lines": [
            {
                "line_number": '10"-P-101-CS',
                "fluid": "P",
                "segments": [[[0.0, 0.0], [200.0, 0.0]]]
            }
        ],
        "elements": [
            {
                "tag": "HV-101",
                "kind": "valve",
                "position": [100.0, 0.0]
            },
            {
                "tag": "PT-101",
                "kind": "instrument",
                "position": [150.0, 30.0],
                "parts": {"pre": "PT", "loop": "101"}
            }
        ],
        "titleblock": {"drawing_number": "SYMBOLS-TEST"}
    }

    engine = PidSchematicEngine()
    svg = engine.render_semantic(sem_data)

    # Nœud papillon (polygon points)
    assert 'polygon points="-8,-5 0,0 -8,5"' in svg
    assert 'polygon points="8,-5 0,0 8,5"' in svg
    assert 'HV-101' in svg

    # Bulle instrument
    assert 'circle cx="0" cy="0"' in svg
    assert re.search(r'circle cx="0" cy="0" r="[\d\.]+"', svg) is not None
    assert 'PT' in svg
    assert '101' in svg
