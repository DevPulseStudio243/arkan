# -*- coding: utf-8 -*-
"""
tests/test_cable_routing_engine.py
Tests unitaires pour le moteur de routage Dijkstra des câbles (cable_routing_engine.py).
"""
import pytest
from cable_routing_engine import CableRoutingEngine, TrayGraph


def test_tray_graph_basic():
    g = TrayGraph(node_merge_tol=0.05)
    # Ajouter des arêtes : (0, 0) -> (10, 0) -> (10, 20)
    g.add_edge((0.0, 0.0), (10.0, 0.0))
    g.add_edge((10.0, 0.0), (10.0, 20.0))

    assert len(g.nodes) == 3
    # Nœud proche de (0.01, 0.01) doit fusionner avec (0, 0)
    idx_snap = g.add_node(0.01, 0.01)
    assert idx_snap == 0

    # Dijkstra
    u, _ = g.find_nearest_node(0, 0)
    v, _ = g.find_nearest_node(10, 20)
    path, dist = g.shortest_path(u, v)
    assert path is not None
    assert pytest.approx(dist, 0.01) == 30.0


def test_dijkstra_shortest_path_branching():
    g = TrayGraph()
    # Graphe triangulaire :
    # A (0,0) -> B (10,0) -> C (20,0) : dist = 20
    # A (0,0) -> D (10, 50) -> C (20,0) : dist = long
    g.add_edge((0, 0), (10, 0))
    g.add_edge((10, 0), (20, 0))
    g.add_edge((0, 0), (10, 50))
    g.add_edge((10, 50), (20, 0))

    u, _ = g.find_nearest_node(0, 0)
    v, _ = g.find_nearest_node(20, 0)
    path, dist = g.shortest_path(u, v)
    assert path is not None
    assert pytest.approx(dist, 0.01) == 20.0


def test_dijkstra_unreachable():
    g = TrayGraph()
    # Deux réseaux déconnectés
    g.add_edge((0, 0), (10, 0))
    g.add_edge((100, 100), (110, 100))

    u, _ = g.find_nearest_node(0, 0)
    v, _ = g.find_nearest_node(100, 100)
    path, dist = g.shortest_path(u, v)
    assert path is None


def test_cable_routing_engine_full_flow():
    engine = CableRoutingEngine()
    # Réseau de chemins :
    # (0, 10) -> (50, 10) -> (50, 80)
    engine.graph.add_edge((0.0, 10.0), (50.0, 10.0))
    engine.graph.add_edge((50.0, 10.0), (50.0, 80.0))

    # TGBT à (0, 8) -> distance au chemin = 2.0 m
    engine.register_equipment("TGBT-01", 0.0, 8.0, eq_type="TGBT")
    # Pompe 300-P-101A à (53, 80) -> distance au chemin = 3.0 m
    engine.register_equipment("300-P-101A", 53.0, 80.0, eq_type="PUMP")

    res = engine.route_cable("TGBT-01", "300-P-101A")
    assert res["status"] == "ROUTED"
    assert res["length_source"] == "DIJKSTRA_ROUTED"

    # L_chemin = (50 - 0) + (80 - 10) = 50 + 70 = 120.0 m
    # Drops horizontaux = 2.0 + 3.0 = 5.0 m
    # Élévations : TGBT = 3.5 m, PUMP = 3.0 m -> 6.5 m
    # Boucles de service = 3.0 m
    # Total = 120 + 5 + 6.5 + 3.0 = 134.5 m
    assert pytest.approx(res["tray_length_m"], 0.1) == 120.0
    assert pytest.approx(res["horizontal_drops_m"], 0.1) == 5.0
    assert pytest.approx(res["vertical_elevation_m"], 0.1) == 6.5
    assert pytest.approx(res["service_loops_m"], 0.1) == 3.0
    assert pytest.approx(res["total_length_m"], 0.1) == 134.5


def test_cable_routing_missing_equipment():
    engine = CableRoutingEngine()
    engine.graph.add_edge((0, 0), (10, 0))
    engine.register_equipment("TGBT-01", 0, 0, eq_type="TGBT")

    res = engine.route_cable("TGBT-01", "P-UNKNOWN")
    assert res["status"] == "DEST_NOT_FOUND"
    assert res["total_length_m"] is None
    assert res["length_source"] == "UNKNOWN"
    assert "introuvable" in res["warning"]


def test_cable_routing_snap_too_far():
    engine = CableRoutingEngine()
    engine.graph.add_edge((0, 0), (10, 0))
    engine.register_equipment("TGBT-01", 0, 0)
    # Équipement à 1000m du chemin
    engine.register_equipment("P-FAR", 1000, 1000)

    res = engine.route_cable("TGBT-01", "P-FAR")
    assert res["status"] == "SNAP_TOO_FAR"
    assert res["total_length_m"] is None
    assert res["length_source"] == "UNKNOWN"


def test_cable_routing_from_ezdxf_drawing():
    import ezdxf
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # Chemin de câbles en millimètres : (0, 0) -> (20000, 0) -> (20000, 15000)
    msp.add_line((0, 0), (20000, 0), dxfattribs={"layer": "CABLETRAY"})
    msp.add_line((20000, 0), (20000, 15000), dxfattribs={"layer": "CABLETRAY"})

    # Équipements comme TEXT
    msp.add_text("TGBT-01", dxfattribs={"layer": "EQUIPMENT", "insert": (0, 1000)})
    msp.add_text("300-P-101A", dxfattribs={"layer": "EQUIPMENT", "insert": (20000, 16000)})

    engine = CableRoutingEngine()
    engine.load_from_ezdxf_doc(doc, scale_to_m=0.001)

    res = engine.route_cable("TGBT-01", "300-P-101A")
    assert res["status"] == "ROUTED"
    assert res["length_source"] == "DIJKSTRA_ROUTED"
    # L_chemin = 20m + 15m = 35m
    # Drop orig = 1m, drop dest = 1m -> 2m
    # Z: 3.5 + 3.0 = 6.5m
    # Loops: 3.0m
    # Total = 35 + 2 + 6.5 + 3.0 = 46.5 m
    assert pytest.approx(res["tray_length_m"], 0.1) == 35.0
    assert pytest.approx(res["total_length_m"], 0.1) == 46.5

