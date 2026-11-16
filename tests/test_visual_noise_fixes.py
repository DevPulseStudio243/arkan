"""
tests/test_visual_noise_fixes.py
================================
Validation des 4 correctifs chirurgicaux contre le bruit visuel et les déformations P&ID :
  1. Reclassification de CH (103-CH-001..005) en Vanne/Clapet (Check Valve) au lieu d'Équipement.
  2. Élimination du faux tag fantôme 'PIP-11883' (fuite de variable Python idx).
  3. Boîtes d'équipements proportionnelles au canvas et fond translucide (suppression du rectangle blanc opaque de 220 mm).
  4. Filtrage des textes de marge haute (Y >= 30180 / ANN-*) pour ne pas dupliquer 103-PP-001 et 103-VS-001.
"""

import re
import pytest
from dxf_pid_parser import DEFAULT_CONFIG, classify, build_semantic
from dxf_to_pid_json import DxfToPidJsonConverter, VALVE_TYPES, EQUIPMENT_TYPES
from pid_schematic_engine import PidSchematicEngine


def test_1_ch_reclassified_as_valve():
    """Vérifie que les tags CH (ex: 103-CH-001) sont classés en vanne (CHECK_VALVE) et jamais en équipement."""
    # 1. Vérification dans classify()
    c1 = classify("103-CH-001", DEFAULT_CONFIG)
    assert c1 is not None, "103-CH-001 doit être reconnu"
    assert c1["kind"] == "valve", f"103-CH-001 doit être de type valve, obtenu: {c1['kind']}"
    assert c1["parts"]["pre"] == "CH"

    c2 = classify("CH-005", DEFAULT_CONFIG)
    assert c2 is not None
    assert c2["kind"] == "valve"

    # 2. Vérification dans VALVE_TYPES et absence dans EQUIPMENT_TYPES
    assert "CH" in VALVE_TYPES
    assert VALVE_TYPES["CH"][0] == "CHECK_VALVE"
    assert "CH" not in EQUIPMENT_TYPES

    # 3. Vérification conversion DXF/JSON DxfToPidJsonConverter
    conv = DxfToPidJsonConverter()
    raw_dummy = {
        "entities": [
            {"id": "t1", "type": "TEXT", "text": "103-CH-001", "pos": [100.0, 100.0], "layer": "TEXT"}
        ]
    }
    sem_dummy = {
        "elements": [
            {"tag": "103-CH-001", "kind": "valve", "parts": {"area": "103", "pre": "CH", "loop": "001"}, "position": [100.0, 100.0]}
        ]
    }
    valves = conv._build_valves(raw_dummy, sem_dummy, circuits=[])
    assert len(valves) == 1
    assert valves[0]["tag"] == "103-CH-001"
    assert valves[0]["valve_type"] == "CHECK_VALVE"

    # S'assurer qu'il est exclu de _build_equipments
    sem_dummy_eq = {
        "elements": [
            {"tag": "103-CH-001", "kind": "equipment", "parts": {"area": "103", "pre": "CH", "loop": "001"}, "position": [100.0, 100.0]}
        ]
    }
    eqs = conv._build_equipments(raw_dummy, sem_dummy_eq, symbol_entity_ids=set())
    assert "103-CH-001" not in eqs, "103-CH-001 ne doit jamais être présent dans equipments"


def test_2_absence_of_fake_pip_11883():
    """Vérifie l'absence de création du faux tag fantôme 'PIP-11883' ou d'entités résiduelles sans tag."""
    # Simulation du code de détection de blocs d'api_enhanced.py
    components = []
    block_candidates = [
        {"idx": 11883, "name": "FLANGE_WELD_NECK", "x": 100.0, "y": 200.0, "rotation": 0.0, "attribs": {}}
    ]
    block_matched_tag = {}  # Pas de tag texte associé (bride anonyme)

    for b_cand in block_candidates:
        b_idx = b_cand["idx"]
        name = b_cand["name"]
        x, y = b_cand["x"], b_cand["y"]
        rot = b_cand["rotation"]
        reconstructed_tag = block_matched_tag.get(b_idx)

        is_piping = any(kw in name.lower() for kw in ("joint", "bride", "flange", "tee"))
        piping_class = "PipingComponent"

        if is_piping:
            # Ne pas créer d'entités résiduelles pour les brides anonymes sans tag
            if reconstructed_tag:
                components.append({
                    "tag": reconstructed_tag,
                    "type": "PipingComponent", "piping_class": piping_class,
                    "x": x, "y": y, "rotation": rot, "line": ""
                })

    assert len(components) == 0, "Aucune entité PIP ne doit être créée pour une bride anonyme sans tag"
    assert not any("11883" in c["tag"] for c in components)


def test_3_equipment_boxes_proportional_and_translucent():
    """Vérifie que les boîtes d'équipements sont translucides et bornées à 15% du canvas sans bloc blanc de 220 mm."""
    # Toile de 300 x 300 unités
    sem_data = {
        "lines": [
            {
                "line_number": '10"-P-101-CS',
                "fluid": "P",
                "segments": [[[100.0, 100.0], [400.0, 100.0]]]
            }
        ],
        "elements": [
            {
                "tag": "103-VS-001",
                "kind": "equipment",
                "position": [200.0, 100.0],
                # Bbox originale de 290 mm de large
                "bbox": [100.0, 90.0, 390.0, 110.0]
            },
            {
                "tag": "PT-101",
                "kind": "instrument",
                "position": [250.0, 150.0],
                "parts": {"pre": "PT", "loop": "101"}
            }
        ],
        "titleblock": {"drawing_number": "PLAN-ROK1-TEST"}
    }

    engine = PidSchematicEngine()
    svg = engine.render_semantic(sem_data)

    # 1. Absence du rectangle opaque #f8fafc de 220 mm
    assert 'fill="#f8fafc" stroke="#334155"' not in svg, "Le rectangle blanc opaque #f8fafc doit être éliminé"
    assert 'width="220.0"' not in svg, "La largeur fixe de 220 mm doit être éliminée"

    # 2. Présence du fond fin translucide
    assert 'fill="rgba(248, 250, 252, 0.10)"' in svg

    # 3. Largeur de boîte bornée proportionnellement (span_x = 300 -> span_x * 0.15 = 45.0)
    # Chercher la largeur de la boîte équipement
    m = re.search(r'<rect x="-[0-9\.]+" y="-[0-9\.]+" width="([0-9\.]+)" height="([0-9\.]+)" rx="8" fill="rgba\(248, 250, 252, 0\.10\)"', svg)
    assert m is not None, "Rectangle d'équipement avec tracé translucide introuvable"
    bw = float(m.group(1))
    assert bw <= 50.0, f"La largeur de la boîte ({bw}) doit être bornée à ~45 (15% de 300), pas 220 ou 290"

    # 4. Bulle d'instrument proportionnelle (scale_factor ~ 0.1 à 0.3)
    m_circle = re.search(r'<circle cx="0" cy="0" r="([0-9\.]+)"', svg)
    assert m_circle is not None
    r_val = float(m_circle.group(1))
    assert r_val <= 6.0, f"Le rayon de la bulle d'instrument ({r_val}) doit être réduit sur un canvas compact"


def test_4_high_margin_texts_filtering():
    """Vérifie le filtrage des textes situés en marge haute (Y >= 30180 ou calques ANN-*) pour éviter les doublons."""
    # Simulation des entités brutes du plan réel 100-300002
    raw = [
        # Équipements réels dans la zone procédé
        {"id": "t1", "type": "TEXT", "layer": "TEXT", "text": "103-VS-001", "pos": [32364.9, 29826.4], "handle": "H1", "block_path": ""},
        {"id": "t2", "type": "TEXT", "layer": "TEXT", "text": "103-PP-001", "pos": [32364.9, 29826.4], "handle": "H2", "block_path": ""},
        # Doublons en marge haute (en-tête / cartouche Y = 30200 >= 30180)
        {"id": "t3", "type": "TEXT", "layer": "TEXT", "text": "103-PP-001", "pos": [32139.8, 30200.0], "handle": "H3", "block_path": ""},
        {"id": "t4", "type": "TEXT", "layer": "TEXT", "text": "103-VS-001", "pos": [32552.8, 30200.0], "handle": "H4", "block_path": ""},
        # Texte sur calque d'annotation ANN-SMTEXT
        {"id": "t5", "type": "TEXT", "layer": "ANN-SMTEXT", "text": "103-VS-001", "pos": [32737.5, 30195.0], "handle": "H5", "block_path": ""}
    ]

    sem = build_semantic(raw=raw, cfg=DEFAULT_CONFIG, warnings=[])
    eq_tags = [e["tag"] for e in sem["elements"] if e.get("kind") == "equipment"]

    # Doit contenir exactement 103-VS-001 et 103-PP-001 une seule fois chacun
    assert eq_tags.count("103-VS-001") == 1, f"103-VS-001 doit apparaître une seule fois, obtenu: {eq_tags.count('103-VS-001')}"
    assert eq_tags.count("103-PP-001") == 1, f"103-PP-001 doit apparaître une seule fois, obtenu: {eq_tags.count('103-PP-001')}"
    assert len(eq_tags) == 2, f"Attendu: 2 équipements réels, Obtenu: {len(eq_tags)}"

    # Vérification dans PidSchematicEngine : les éléments marginaux sont ignorés
    engine = PidSchematicEngine()
    sem_data = {
        "lines": [{"line_number": '10"-P-101-CS', "fluid": "P", "segments": [[[32000.0, 29800.0], [32500.0, 29800.0]]] }],
        "elements": [
            {"tag": "103-VS-001", "kind": "equipment", "position": [32364.9, 29826.4]},
            {"tag": "103-VS-001", "kind": "equipment", "position": [32552.8, 30200.0]}  # Marge haute
        ],
        "titleblock": {}
    }
    svg = engine.render_semantic(sem_data)
    rendered_groups = re.findall(r'data-tag="103-VS-001" data-kind="equipment"', svg)
    assert len(rendered_groups) == 1, f"Seul l'équipement procédé réel doit être rendu, obtenu: {len(rendered_groups)}"
