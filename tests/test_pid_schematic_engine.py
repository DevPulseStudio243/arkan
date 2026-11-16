"""
tests/test_pid_schematic_engine.py
==================================
Tests unitaires et de validation du Moteur de Rendu SVG ISA-5.1 (Module 3).
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from dxf_to_pid_json import convert_dxf_to_json
from pid_orthogonal_router import route_pid_topology
from pid_schematic_engine import (
    ENGINE_VERSION,
    FLUID_COLORS,
    PidSchematicEngine,
    render_dxf_to_schematic,
)

SAMPLE_DXF = Path(__file__).resolve().parent.parent / "samples" / "synthetic_pid.dxf"


@pytest.fixture
def synthetic_dxf_path() -> Path:
    assert SAMPLE_DXF.exists(), f"Fichier test introuvable: {SAMPLE_DXF}"
    return SAMPLE_DXF


@pytest.fixture
def routed_synthetic_data(synthetic_dxf_path) -> Dict[str, Any]:
    raw_topo = convert_dxf_to_json(synthetic_dxf_path)
    return route_pid_topology(raw_topo)


class TestPidSchematicEngine:
    """Suite de tests pour le moteur SVG PidSchematicEngine."""

    def test_instantiation_default_and_custom(self):
        """Vérifie l'instanciation du moteur avec paramètres par défaut et personnalisés."""
        engine = PidSchematicEngine()
        assert engine.canvas_w == 1600.0
        assert engine.canvas_h == 1000.0
        assert engine.pipe_stroke == 2.5

        custom = PidSchematicEngine(canvas_width=1920.0, canvas_height=1080.0, pipe_stroke_width=3.0)
        assert custom.canvas_w == 1920.0
        assert custom.canvas_h == 1080.0
        assert custom.pipe_stroke == 3.0

    def test_render_dxf_to_schematic_end_to_end(self, synthetic_dxf_path, tmp_path):
        """Test de bout en bout : conversion DXF -> Routage -> Rendu SVG et export fichiers."""
        out_svg = tmp_path / "test_schematic.svg"
        out_json = tmp_path / "test_schematic.json"

        svg_content = render_dxf_to_schematic(
            synthetic_dxf_path, out_svg_path=out_svg, out_json_path=out_json
        )

        assert out_svg.exists()
        assert out_json.exists()
        assert len(svg_content) > 1000

        # Vérification de la validité stricte du XML SVG
        root = ET.fromstring(svg_content)
        assert root.tag.endswith("svg")
        assert root.attrib.get("viewBox") == "0 0 1600.0 1000.0"

        # Présence des calques essentiels
        group_ids = [g.attrib.get("id") for g in root.iter() if g.attrib.get("id")]
        assert "grid" in group_ids
        assert "layer-piping-circuits" in group_ids
        assert "layer-valves" in group_ids
        assert "layer-equipments" in group_ids
        assert "layer-instruments" in group_ids
        assert "legend-and-titleblock" in group_ids

    def test_svg_elements_and_markup(self, routed_synthetic_data):
        """Vérifie la présence de toutes les balises vectorielles standardisées."""
        engine = PidSchematicEngine()
        svg = engine.render(routed_synthetic_data)

        # Vérification textuelle des balises maîtresses
        assert "<svg" in svg and "</svg>" in svg
        assert "<defs>" in svg and "</defs>" in svg
        assert "<style>" in svg and "</style>" in svg
        assert "<rect" in svg
        assert "<circle" in svg
        assert "<path" in svg
        assert "<polygon" in svg
        assert "<text" in svg
        assert "<line" in svg

    def test_interactive_data_attributes(self, routed_synthetic_data):
        """Vérifie l'injection des attributs interactifs data-*."""
        engine = PidSchematicEngine()
        svg = engine.render(routed_synthetic_data)
        root = ET.fromstring(svg)

        interactive_elems = [e for e in root.iter() if any(k.startswith("data-") for k in e.attrib)]
        assert len(interactive_elems) >= 8  # svg, 4 circuits, 1 valve, 3 equipments

        # Vérification attributs des équipements
        pump_a = next(e for e in interactive_elems if e.attrib.get("data-tag") == "201-PP-001/A")
        assert pump_a.attrib.get("data-type") == "PUMP"
        assert "data-cad-x" in pump_a.attrib
        assert "data-cad-y" in pump_a.attrib

        # Vérification attributs des tuyauteries
        circ_001 = next(e for e in interactive_elems if e.attrib.get("data-circuit-id") == "CIRC-001")
        assert circ_001.attrib.get("data-fluid") == "P"
        assert circ_001.attrib.get("data-type") == "PIPING"

        # Vérification attributs des vannes
        valve_hv = next(e for e in interactive_elems if e.attrib.get("data-tag") == "201-HV-001")
        assert valve_hv.attrib.get("data-type") == "MANUAL_VALVE"

    def test_equipment_glyphs_isa_5_1(self):
        """Vérifie le rendu des différents glyphes vectoriels d'équipements ISA-5.1."""
        synthetic_data = {
            "canvas": {"width": 1600.0, "height": 1000.0},
            "equipments": [
                {
                    "tag": "V-101",
                    "type": "VESSEL",
                    "svg_center": [200.0, 300.0],
                    "svg_width": 120.0,
                    "svg_height": 80.0,
                    "svg_bbox": [140.0, 260.0, 260.0, 340.0],
                    "cad_anchor": [10.0, 20.0],
                    "nozzles": [],
                },
                {
                    "tag": "E-101",
                    "type": "HEAT_EXCHANGER",
                    "svg_center": [500.0, 300.0],
                    "svg_width": 130.0,
                    "svg_height": 70.0,
                    "svg_bbox": [435.0, 265.0, 565.0, 335.0],
                    "cad_anchor": [30.0, 20.0],
                    "nozzles": [],
                },
                {
                    "tag": "C-101",
                    "type": "COLUMN",
                    "svg_center": [800.0, 300.0],
                    "svg_width": 80.0,
                    "svg_height": 180.0,
                    "svg_bbox": [760.0, 210.0, 840.0, 390.0],
                    "cad_anchor": [50.0, 20.0],
                    "nozzles": [],
                },
                {
                    "tag": "TK-101",
                    "type": "TANK",
                    "svg_center": [1100.0, 300.0],
                    "svg_width": 120.0,
                    "svg_height": 90.0,
                    "svg_bbox": [1040.0, 255.0, 1160.0, 345.0],
                    "cad_anchor": [70.0, 20.0],
                    "nozzles": [],
                },
            ],
            "piping_circuits": [],
            "valves": [],
            "instruments": [],
            "metadata": {},
            "topology_summary": {},
        }

        engine = PidSchematicEngine()
        svg = engine.render(synthetic_data)
        root = ET.fromstring(svg)

        # Vérification que chaque équipement a été rendu dans son groupe
        vessel_g = next(g for g in root.iter() if g.attrib.get("id") == "V-101")
        assert vessel_g.attrib.get("data-type") == "VESSEL"

        exchanger_g = next(g for g in root.iter() if g.attrib.get("id") == "E-101")
        assert exchanger_g.attrib.get("data-type") == "HEAT_EXCHANGER"

        column_g = next(g for g in root.iter() if g.attrib.get("id") == "C-101")
        assert column_g.attrib.get("data-type") == "COLUMN"

        tank_g = next(g for g in root.iter() if g.attrib.get("id") == "TK-101")
        assert tank_g.attrib.get("data-type") == "TANK"

    def test_valves_bowtie_rendering(self):
        """Vérifie le rendu des vannes en nœud papillon et leurs actionneurs."""
        synthetic_data = {
            "canvas": {"width": 1600.0, "height": 1000.0},
            "equipments": [],
            "piping_circuits": [],
            "valves": [
                {
                    "tag": "HV-001",
                    "valve_type": "MANUAL_VALVE",
                    "svg_coords": [300.0, 400.0],
                    "cad_coords": [10.0, 10.0],
                    "orientation": "H",
                },
                {
                    "tag": "FV-002",
                    "valve_type": "CONTROL_VALVE",
                    "svg_coords": [500.0, 400.0],
                    "cad_coords": [20.0, 10.0],
                    "orientation": "V",
                },
                {
                    "tag": "ESDV-003",
                    "valve_type": "ESDV",
                    "svg_coords": [700.0, 400.0],
                    "cad_coords": [30.0, 10.0],
                    "orientation": "H",
                },
            ],
            "instruments": [],
            "metadata": {},
            "topology_summary": {},
        }

        engine = PidSchematicEngine()
        svg = engine.render(synthetic_data)
        root = ET.fromstring(svg)

        # Vérification HV-001 (manuel)
        hv_g = next(g for g in root.iter() if g.attrib.get("id") == "HV-001")
        polygons_hv = list(hv_g.iter("{http://www.w3.org/2000/svg}polygon"))
        assert len(polygons_hv) == 2  # Deux triangles formant le nœud papillon

        # Vérification FV-002 (vanne de contrôle avec dôme actionneur)
        fv_g = next(g for g in root.iter() if g.attrib.get("id") == "FV-002")
        paths_fv = list(fv_g.iter("{http://www.w3.org/2000/svg}path"))
        assert len(paths_fv) >= 1  # Dôme de la membrane d'actionneur

        # Vérification ESDV-003 (vanne d'arrêt d'urgence avec boîte)
        esdv_g = next(g for g in root.iter() if g.attrib.get("id") == "ESDV-003")
        rects_esdv = list(esdv_g.iter("{http://www.w3.org/2000/svg}rect"))
        assert len(rects_esdv) >= 1  # Boîtier de commande ESDV

    def test_hops_arc_rendering(self):
        """Vérifie que les arcs de franchissement (Hops) sont bien inscrits dans le SVG avec commande 'A'."""
        routed_circuit_with_hop = {
            "line_id": "CIRC-HOP",
            "line_tag": "3\"-P-001",
            "fluid": "P",
            "segments": [
                {
                    "p1": [400.0, 100.0],
                    "p2": [400.0, 500.0],
                    "dir": "V",
                    "length": 400.0,
                    "hops": [
                        {
                            "crossing_point": [400.0, 300.0],
                            "crossed_circuit_id": "OTHER-H",
                            "radius": 8.0,
                            "axis": "V",
                        }
                    ],
                }
            ],
        }

        data = {
            "canvas": {"width": 1000.0, "height": 800.0},
            "equipments": [],
            "piping_circuits": [routed_circuit_with_hop],
            "valves": [],
            "instruments": [],
            "metadata": {},
            "topology_summary": {"total_hops": 1},
        }

        engine = PidSchematicEngine()
        svg = engine.render(data)

        # Vérification de la présence de la commande d'arc elliptique 'A' dans le path
        assert "A 8.0 8.0 0 0" in svg

    def test_instruments_bubble_rendering(self):
        """Vérifie le rendu des bulles d'instruments ISA-5.1 et leur trait de liaison."""
        data = {
            "canvas": {"width": 1000.0, "height": 800.0},
            "equipments": [],
            "piping_circuits": [],
            "valves": [],
            "instruments": [
                {
                    "id": "INST-001",
                    "tag": "PT-201",
                    "variable": "P",
                    "function": "T",
                    "loop_tag": "P-201",
                    "svg_coords": [450.0, 250.0],
                    "cad_coords": [10.0, 10.0],
                    "leader_line": [[450.0, 300.0], [450.0, 264.0]],
                }
            ],
            "metadata": {},
            "topology_summary": {},
        }

        engine = PidSchematicEngine()
        svg = engine.render(data)
        root = ET.fromstring(svg)

        inst_g = next(g for g in root.iter() if g.attrib.get("id") == "PT-201")
        # Cercle de bulle
        circles = list(inst_g.iter("{http://www.w3.org/2000/svg}circle"))
        assert len(circles) == 1
        assert circles[0].attrib.get("r") == "14.0"

        # Trait de liaison en tirets
        lines = list(inst_g.iter("{http://www.w3.org/2000/svg}line"))
        assert len(lines) >= 2  # Leader line + ligne médiane

    def test_legend_panel_and_fluid_colors(self, routed_synthetic_data):
        """Vérifie la présence du panneau de légende inférieur et des fluides ASME."""
        engine = PidSchematicEngine()
        svg = engine.render(routed_synthetic_data)
        root = ET.fromstring(svg)

        legend_g = next(g for g in root.iter() if g.attrib.get("id") == "legend-and-titleblock")
        legend_text = "".join(legend_g.itertext())

        assert "AR-KAN P&ID SCHEMATIC" in legend_text
        assert "Équipements" in legend_text
        assert "Circuits" in legend_text
        assert "Vannes" in legend_text
        assert "LÉGENDE DES FLUIDES" in legend_text
        assert "Process" in legend_text or "P :" in legend_text
