"""
tests/test_deblocages_pid.py
============================
Tests de non-régression et de validation des 5 déblocages géométriques et sémantiques :
1. Tolérances physiques (min_line_length=8.0, equip_attach_tol=28.0, snap_tol=8.0)
2. Élargissement multi-calques (lignes sur calques 0, TEXT, etc.)
3. Extraction des vannes blocs sans tag texte
4. Séparation des runs aux réductions de diamètre
5. Préfixes d'équipements étendus (VS, COL, EX, SEP, FIL, STR, DR)
6. Rendu schématique épuré (pas de L-xxxx opaque, pas de EQ_FORME_x, symboles vannes orientés, amont/aval)
"""

import math
import sys
from pathlib import Path
import ezdxf
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import dxf_pid_parser
import pid_equipment_blocks
import pid_schematic


def test_physical_tolerances_config():
    """Vérifie la mise à jour des tolérances physiques standardisées."""
    cfg = dxf_pid_parser.load_config(None)
    assert cfg["snap_tol"] == 8.0, f"snap_tol doit être 8.0, trouvé: {cfg['snap_tol']}"
    assert cfg["equip_attach_tol"] == 28.0, f"equip_attach_tol doit être 28.0, trouvé: {cfg['equip_attach_tol']}"
    assert cfg["min_line_length"] == 8.0, f"min_line_length doit être 8.0, trouvé: {cfg['min_line_length']}"

    assert pid_equipment_blocks.TAG_MAX == 28.0, f"TAG_MAX doit être 28.0, trouvé: {pid_equipment_blocks.TAG_MAX}"
    assert pid_equipment_blocks.GAP == 12.0, f"GAP doit être 12.0, trouvé: {pid_equipment_blocks.GAP}"


def test_extended_equipment_prefixes():
    """Vérifie que les préfixes étendus sont bien classés en tant qu'équipements et non instruments."""
    cfg = dxf_pid_parser.load_config(None)
    test_tags = [
        "303-VS-001",
        "VS-001",
        "COL-101",
        "201-COL-002",
        "EX-201",
        "SEP-301",
        "FIL-401",
        "STR-501",
        "DR-601",
    ]
    for tag in test_tags:
        res = dxf_pid_parser.classify(tag, cfg)
        assert res is not None, f"Tag {tag} non reconnu"
        assert res["kind"] == "equipment", f"Tag {tag} classé en '{res['kind']}' au lieu de 'equipment'"


def test_multi_layer_line_expansion(tmp_path):
    """Vérifie que les segments de tuyauterie sur calque TEXT ou 0 proches d'une étiquette sont extraits."""
    dxf_path = tmp_path / "multi_layer.dxf"
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()

    # Segments dessinés sur calque TEXT (comme dans 100-004)
    msp.add_line((100, 100), (300, 100), dxfattribs={"layer": "TEXT"})
    msp.add_line((300, 100), (300, 250), dxfattribs={"layer": "0"})
    msp.add_text('4"-P-101-CS', dxfattribs={"insert": (150, 115), "layer": "TEXT", "height": 3.0})

    doc.saveas(str(dxf_path))

    _, sem = dxf_pid_parser.parse_dxf_to_raw_and_semantic(dxf_path)
    assert len(sem["lines"]) >= 1, "Les segments sur calque TEXT/0 n'ont pas été extraits"
    tagged = [l for l in sem["lines"] if l.get("tag_raw") == '4"-P-101-CS']
    assert len(tagged) == 1, "La ligne 4\"-P-101-CS doit être étiquetée"


def test_untagged_valve_blocks_extraction(tmp_path):
    """Vérifie l'extraction des blocs de vannes sans étiquette texte."""
    dxf_path = tmp_path / "untagged_valves.dxf"
    doc = ezdxf.new("R2018", setup=True)

    # Définition de blocs de vannes sans attribut texte
    b_ball = doc.blocks.new("ball valve")
    b_ball.add_line((-5, -5), (5, 5))
    b_ball.add_line((-5, 5), (5, -5))

    b_check = doc.blocks.new("clapet de non retour")
    b_check.add_circle((0, 0), 4)

    msp = doc.modelspace()
    # Ligne de tuyauterie
    msp.add_line((0, 50), (400, 50), dxfattribs={"layer": "PIPE"})
    msp.add_text('6"-P-101-CS', dxfattribs={"insert": (200, 60), "layer": "TEXT", "height": 3.0})

    # Blocs de vannes posés sur la ligne
    msp.add_blockref("ball valve", (100, 50), dxfattribs={"layer": "vannes"})
    msp.add_blockref("clapet de non retour", (250, 50), dxfattribs={"layer": "vannes"})

    doc.saveas(str(dxf_path))

    _, sem = dxf_pid_parser.parse_dxf_to_raw_and_semantic(dxf_path)
    valves = [e for e in sem["elements"] if e["kind"] == "valve"]
    assert len(valves) == 2, f"Attendu 2 vannes blocs extraites, trouvé: {len(valves)}"
    valve_tags = {v["tag"] for v in valves}
    assert "BALL_VALVE" in valve_tags
    assert "CHECK_VALVE" in valve_tags
    for v in valves:
        assert v.get("on_line") is not None, f"La vanne {v['tag']} doit être associée à sa ligne"


def test_reduction_run_splitting(tmp_path):
    """Vérifie la séparation des runs lorsqu'un changement de diamètre est détecté."""
    dxf_path = tmp_path / "reduction.dxf"
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()

    # Un long tronçon continu sans nœud intermédiaire
    msp.add_line((0, 100), (600, 100), dxfattribs={"layer": "PIPE"})
    # Deux étiquettes de diamètres différents (4" et 2")
    msp.add_text('4"-P-101-CS', dxfattribs={"insert": (100, 115), "layer": "TEXT", "height": 3.0})
    msp.add_text('2"-P-102-CS', dxfattribs={"insert": (500, 115), "layer": "TEXT", "height": 3.0})

    doc.saveas(str(dxf_path))

    _, sem = dxf_pid_parser.parse_dxf_to_raw_and_semantic(dxf_path)
    tagged_lines = [l for l in sem["lines"] if l.get("tag_raw")]
    assert len(tagged_lines) == 2, f"Attendu 2 lignes séparées, trouvé: {len(tagged_lines)}"
    tags = {l["tag_raw"] for l in tagged_lines}
    assert '4"-P-101-CS' in tags
    assert '2"-P-102-CS' in tags
    # Aucun conflit de ligne
    conflicts = [w for w in sem["warnings"] if w.get("code") == "LINE_TAG_CONFLICT"]
    assert len(conflicts) == 0, f"Conflits inattendus: {conflicts}"


def test_schematic_rendering_deblocages(tmp_path):
    """Vérifie les améliorations visuelles dans le rendu vectoriel SVG."""
    sem_data = {
        "titleblock": {"title": "TEST SCHEMATIC", "drawing_number": "DWG-001"},
        "lines": [
            {
                "id": "L-001",
                "tag_raw": None,  # Ligne sans tag explicite
                "fluid": "P",
                "segments": [[[100.0, 100.0], [500.0, 100.0]]],
            },
            {
                "id": "L-002",
                "tag_raw": '4"-P-201-CS',
                "fluid": "P",
                "from_equipment": "201-PP-001",
                "segments": [[[100.0, 100.0], [300.0, 100.0]]],
            },
        ],
        "elements": [
            {
                "id": "E-001",
                "kind": "equipment",
                "tag": "201-PP-001",
                "position": [100.0, 100.0],
                "bbox": [80.0, 80.0, 120.0, 120.0],
            },
            {
                "id": "V-001",
                "kind": "valve",
                "tag": "BALL_VALVE",
                "has_text_tag": False,
                "position": [200.0, 100.0],
                "bbox": [195.0, 95.0, 205.0, 105.0],
            },
        ],
        "equipment_candidates": [
            {
                "id": "EQC-01",
                "tags": [],
                "proposed_block": "EQ_FORME_1",
                "bbox": [300.0, 80.0, 340.0, 120.0],
            }
        ],
    }

    svg = pid_schematic.render_schematic(sem_data)

    # 1. Pas de badge opaque pour l'identifiant interne L-001
    assert ">L-001<" not in svg, "L'identifiant interne 'L-001' ne doit pas avoir de badge opaque"

    # 2. Pas d'affichage 'EQ_FORME_1'
    assert ">EQ_FORME_1<" not in svg, "'EQ_FORME_1' ne doit pas être affiché sur les formes épurées"

    # 3. La vanne sans tag texte est dessinée en papillon sans boîte de texte
    assert 'data-tag="BALL_VALVE"' in svg
    assert "<polygon" in svg
    assert ">BALL_VALVE<" not in svg, "La vanne non étiquetée ne doit pas avoir de badge texte"

    # 4. Connexions amont / aval présentes dans les attributs d'équipement
    assert 'data-amont=' in svg
    assert 'data-aval=' in svg
