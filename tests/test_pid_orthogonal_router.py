"""
tests/test_pid_orthogonal_router.py
===================================
Tests unitaires et de validation du Routeur Topologique Orthogonal (Module 2).
"""

import math
import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from dxf_to_pid_json import convert_dxf_to_json
from pid_orthogonal_router import (
    EQUIPMENT_SIZES,
    ROUTER_VERSION,
    PidOrthogonalRouter,
    route_pid_topology,
)

SAMPLE_DXF = Path(__file__).resolve().parent.parent / "samples" / "synthetic_pid.dxf"


@pytest.fixture
def synthetic_topology() -> Dict[str, Any]:
    """Charge et convertit synthetic_pid.dxf en topologie de base."""
    return convert_dxf_to_json(SAMPLE_DXF)


class TestPidOrthogonalRouter:
    """Suite de tests pour la classe PidOrthogonalRouter et la fonction route_pid_topology."""

    def test_instantiation_default_and_custom(self):
        """Vérifie l'instanciation avec dimensions par défaut et surchargées."""
        router = PidOrthogonalRouter()
        assert router.canvas_w == 1600.0
        assert router.canvas_h == 1000.0
        assert router.hop_radius == 8.0

        custom = PidOrthogonalRouter(canvas_width=2000.0, canvas_height=1200.0, hop_radius=10.0)
        assert custom.canvas_w == 2000.0
        assert custom.canvas_h == 1200.0
        assert custom.hop_radius == 10.0

    def test_equipment_sizes_specification(self):
        """Vérifie que les encombrements modulaires correspondent à la spécification."""
        assert EQUIPMENT_SIZES["VESSEL"] == (120.0, 80.0)
        assert EQUIPMENT_SIZES["PUMP"] == (70.0, 70.0)
        assert EQUIPMENT_SIZES["FILTER_STRAINER"] == (50.0, 50.0)
        assert "TANK" in EQUIPMENT_SIZES
        assert "COLUMN" in EQUIPMENT_SIZES
        assert "HEAT_EXCHANGER" in EQUIPMENT_SIZES

    def test_layout_equipments_relative_positions(self, synthetic_topology):
        """Vérifie le positionnement spatial relatif et les dimensions SVG des équipements."""
        router = PidOrthogonalRouter(canvas_width=1600.0, canvas_height=1000.0)
        routed = router.layout_and_route(synthetic_topology)

        equipments = routed["equipments"]
        assert len(equipments) == 3

        eq_by_tag = {eq["tag"]: eq for eq in equipments}
        strainer = eq_by_tag["201-ST-001"]
        pump_a = eq_by_tag["201-PP-001/A"]
        pump_b = eq_by_tag["201-PP-001/B"]

        # 1. Vérification de la préservation de l'ordre Ouest -> Est
        assert strainer["svg_center"][0] < pump_a["svg_center"][0] < pump_b["svg_center"][0]

        # 2. Vérification des dimensions modulaires
        assert strainer["svg_width"] == 50.0
        assert strainer["svg_height"] == 50.0
        assert pump_a["svg_width"] == 70.0
        assert pump_a["svg_height"] == 70.0
        assert pump_b["svg_width"] == 70.0
        assert pump_b["svg_height"] == 70.0

        # 3. Vérification de la cohérence de svg_bbox avec svg_center
        for eq in (strainer, pump_a, pump_b):
            cx, cy = eq["svg_center"]
            w, h = eq["svg_width"], eq["svg_height"]
            bbox = eq["svg_bbox"]
            assert pytest.approx(bbox[0], abs=1e-1) == cx - w / 2.0
            assert pytest.approx(bbox[1], abs=1e-1) == cy - h / 2.0
            assert pytest.approx(bbox[2], abs=1e-1) == cx + w / 2.0
            assert pytest.approx(bbox[3], abs=1e-1) == cy + h / 2.0

        # 4. Vérification de l'absence de chevauchement horizontal
        assert strainer["svg_bbox"][2] < pump_a["svg_bbox"][0]
        assert pump_a["svg_bbox"][2] < pump_b["svg_bbox"][0]

    def test_place_nozzles_on_contour(self, synthetic_topology):
        """Vérifie que les piquages sont placés exactement sur les bords selon leur orientation."""
        routed = route_pid_topology(synthetic_topology)
        eq_by_tag = {eq["tag"]: eq for eq in routed["equipments"]}

        pump_a = eq_by_tag["201-PP-001/A"]
        nozzles = {n["tag"]: n for n in pump_a["nozzles"]}

        # N1 est orienté Ouest (W) : x = xmin
        assert "N1" in nozzles
        n1 = nozzles["N1"]
        assert n1["orientation"] == "W"
        assert pytest.approx(n1["svg_coords"][0], abs=1e-1) == pump_a["svg_bbox"][0]
        assert pytest.approx(n1["svg_coords"][1], abs=1e-1) == pump_a["svg_center"][1]

        # N2 est orienté Est (E) : x = xmax
        assert "N2" in nozzles
        n2 = nozzles["N2"]
        assert n2["orientation"] == "E"
        assert pytest.approx(n2["svg_coords"][0], abs=1e-1) == pump_a["svg_bbox"][2]
        assert pytest.approx(n2["svg_coords"][1], abs=1e-1) == pump_a["svg_center"][1]

    def test_orthogonal_circuits_and_strict_manhattan(self, synthetic_topology):
        """Vérifie que tous les segments routés sont strictement orthogonaux (horizontaux ou verticaux)."""
        routed = route_pid_topology(synthetic_topology)
        circuits = routed["piping_circuits"]
        assert len(circuits) == 4

        for c in circuits:
            poly = c["orthogonal_polyline"]
            assert len(poly) >= 2, f"Circuit {c['line_id']} a moins de 2 points"

            segments = c["segments"]
            assert len(segments) == len(poly) - 1

            for s in segments:
                p1, p2 = s["p1"], s["p2"]
                dx = abs(p2[0] - p1[0])
                dy = abs(p2[1] - p1[1])
                # Strictement horizontal (dy ~= 0) ou vertical (dx ~= 0)
                is_orthogonal = (dx < 1e-2 and dy > 0) or (dy < 1e-2 and dx > 0)
                assert is_orthogonal, f"Segment non-orthogonal dans {c['line_id']}: {p1} -> {p2}"
                assert s["dir"] in ("H", "V")
                if s["dir"] == "H":
                    assert dy < 1e-2
                else:
                    assert dx < 1e-2

    def test_in_line_components_position_and_orientation(self, synthetic_topology):
        """Vérifie le positionnement et l'orientation automatique des composants en ligne."""
        routed = route_pid_topology(synthetic_topology)

        # Vérification sur le circuit CIRC-003 qui contient la vanne 201-HV-001
        circ_003 = next(c for c in routed["piping_circuits"] if c["line_id"] == "CIRC-003")
        assert len(circ_003["in_line_components"]) == 1
        comp = circ_003["in_line_components"][0]

        assert comp["tag"] == "201-HV-001"
        assert comp["orientation"] == "H"  # Segment horizontal entre Pump A et Pump B
        assert "svg_coords" in comp
        coords = comp["svg_coords"]

        # Coordonnées cohérentes entre les deux équipements
        pump_a_x = next(e["svg_bbox"][2] for e in routed["equipments"] if e["tag"] == "201-PP-001/A")
        pump_b_x = next(e["svg_bbox"][0] for e in routed["equipments"] if e["tag"] == "201-PP-001/B")
        assert pump_a_x < coords[0] < pump_b_x

        # Synchronisation avec la liste globale des vannes
        valves = routed["valves"]
        hv001 = next(v for v in valves if v["tag"] == "201-HV-001")
        assert hv001["svg_coords"] == coords
        assert hv001["orientation"] == "H"

    def test_manhattan_path_generation_scenarios(self):
        """Teste les différents scénarios de routage Manhattan (H-V, V-H, H-V-H)."""
        router = PidOrthogonalRouter()

        # 1. Alignement direct horizontal
        p_h = router._compute_manhattan_path([100.0, 200.0], "E", [400.0, 200.0], "W")
        assert len(p_h) == 2
        assert p_h[0] == [100.0, 200.0]
        assert p_h[1] == [400.0, 200.0]

        # 2. H-V-H : sortie E, entrée W, niveaux Y différents
        p_hvh = router._compute_manhattan_path([100.0, 200.0], "E", [400.0, 350.0], "W")
        assert len(p_hvh) == 4
        assert p_hvh[0] == [100.0, 200.0]
        assert p_hvh[1] == [250.0, 200.0]  # Mid X
        assert p_hvh[2] == [250.0, 350.0]  # Vertical transition
        assert p_hvh[3] == [400.0, 350.0]

        # 3. H-V : sortie E, entrée N (virage 90°)
        p_hv = router._compute_manhattan_path([100.0, 200.0], "E", [300.0, 400.0], "N")
        assert len(p_hv) == 3
        assert p_hv[0] == [100.0, 200.0]
        assert p_hv[1] == [300.0, 200.0]
        assert p_hv[2] == [300.0, 400.0]

        # 4. V-H : sortie S, entrée E (virage 90°)
        p_vh = router._compute_manhattan_path([100.0, 100.0], "S", [300.0, 400.0], "E")
        assert len(p_vh) == 3
        assert p_vh[0] == [100.0, 100.0]
        assert p_vh[1] == [100.0, 400.0]
        assert p_vh[2] == [300.0, 400.0]

    def test_hops_detection_on_intersecting_lines(self):
        """Vérifie la détection des intersections et la génération des ponts d'arc (Hops)."""
        # Création d'une topologie synthétique avec croisement à angle droit
        topology = {
            "metadata": {"drawing_number": "TEST-HOPS"},
            "equipments": [],
            "piping_circuits": [
                {
                    "line_id": "LINE-H",
                    "line_tag": "6\"-P-001",
                    "fluid": "P",
                    "from_node": {"node_type": "OPEN_HEADER"},
                    "to_node": {"node_type": "OPEN_HEADER"},
                    "polyline": [[100.0, 300.0], [500.0, 300.0]],
                },
                {
                    "line_id": "LINE-V",
                    "line_tag": "4\"-W-002",
                    "fluid": "W",
                    "from_node": {"node_type": "OPEN_HEADER"},
                    "to_node": {"node_type": "OPEN_HEADER"},
                    "polyline": [[300.0, 100.0], [300.0, 500.0]],
                },
            ],
            "valves": [],
            "instruments": [],
            "loops": [],
        }

        router = PidOrthogonalRouter(canvas_width=1000.0, canvas_height=1000.0, hop_radius=8.0)
        routed = router.layout_and_route(topology)

        # Le segment vertical doit avoir détecté le croisement avec la ligne horizontale
        circ_v = next(c for c in routed["piping_circuits"] if c["line_id"] == "LINE-V")
        v_seg = circ_v["segments"][0]

        assert len(v_seg["hops"]) == 1
        hop = v_seg["hops"][0]
        assert hop["crossed_circuit_id"] == "LINE-H"
        assert hop["radius"] == 8.0
        assert hop["axis"] == "V"
        assert pytest.approx(hop["crossing_point"][0], abs=2.0) == 500.0
        assert pytest.approx(hop["crossing_point"][1], abs=2.0) == 475.0

        assert routed["topology_summary"]["total_hops"] == 1

    def test_instruments_placement_with_leader_line(self):
        """Vérifie le positionnement d'instruments reliés par leader line en tirets."""
        topology = {
            "metadata": {"drawing_number": "TEST-INST"},
            "equipments": [],
            "piping_circuits": [
                {
                    "line_id": "CIRC-01",
                    "line_tag": "3\"-P-100",
                    "fluid": "P",
                    "from_node": {"node_type": "OPEN_HEADER"},
                    "to_node": {"node_type": "OPEN_HEADER"},
                    "polyline": [[100.0, 400.0], [600.0, 400.0]],
                }
            ],
            "valves": [],
            "instruments": [
                {
                    "id": "INST-001",
                    "tag": "PT-101",
                    "variable": "P",
                    "function": "T",
                    "circuit_id": "CIRC-01",
                    "cad_coords": [350.0, 400.0],
                }
            ],
            "loops": [],
        }

        router = PidOrthogonalRouter()
        routed = router.layout_and_route(topology)

        insts = routed["instruments"]
        assert len(insts) == 1
        pt = insts[0]
        assert pt["tag"] == "PT-101"
        assert "svg_coords" in pt
        assert pt["leader_line"] is not None
        assert len(pt["leader_line"]) == 2
        # La bulle est au-dessus du point d'attache sur la ligne
        attach_pt, bubble_pt = pt["leader_line"]
        assert bubble_pt[1] < attach_pt[1]
