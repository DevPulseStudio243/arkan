"""
Tests de circuit_graph.py.
piping_topology_tracer (decode_gcb_pipe_spec, parse_line_tag) n'est pas livre dans le bundle : si le vrai module
est absent, un STUB MINIMAL est injecte ici pour tester uniquement la logique du graphe (coupe aux jonctions,
pontage des vannes, orientation, ordre des composants).
"""
import re
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("scipy")
pytest.importorskip("networkx")

try:
    import piping_topology_tracer  # noqa: F401
except ImportError:
    stub = types.ModuleType("piping_topology_tracer")
    _TAG = re.compile(r'^(?P<size>\d+(?:/\d+)?)"?-(?P<fluid>[A-Z]{1,3})-(?P<spec>[A-Z0-9]*[A-Z][A-Z0-9]*)-(?P<seq>\d{2,5})')
    stub.parse_line_tag = lambda t: (m.groupdict() if (m := _TAG.match(t or "")) else None)
    stub.decode_gcb_pipe_spec = lambda spec: {}
    sys.modules["piping_topology_tracer"] = stub

from circuit_graph import CircuitGraph, Symbol, split_at_junctions


def test_te_pose_au_milieu_coupe_la_ligne_principale():
    segs = [((0, 0), (100, 0)), ((50, 0), (50, 40))]           # la branche s'arrete sur le milieu du tube
    out = split_at_junctions(segs, tol=1.0)
    assert len(out) == 3, "la ligne principale doit etre coupee au te"


def test_croisement_sans_extremite_nest_pas_une_connexion():
    segs = [((0, 50), (100, 50)), ((50, 0), (50, 100))]
    assert len(split_at_junctions(segs, tol=1.0)) == 2


def test_chaines_composants_ordre_et_sens_avec_prefixe_de_zone():
    segs = [((0, 0), (100, 0)), ((100, 0), (200, 0))]
    symbols = [
        Symbol("equipment", 0, 0, 10, 10, "201-PP-001/A"),     # pompe avec prefixe de zone : source
        Symbol("equipment", 200, 0, 10, 10, "201-TK-001"),     # bac avec prefixe de zone : puits
        Symbol("valve", 150, 0, 8, 8, "201-HV-003"),
        Symbol("valve", 50, 0, 8, 8, "201-HV-001"),
    ]
    labels = [{"text": '4"-LP-1ACX1PN-209-N', "x": 100, "y": 15}]
    g = CircuitGraph(segs, symbols, labels, snap_tol=1.0)
    assert len(g.chains) == 1
    c = g.chains[0]
    assert c["tag"] == '4"-LP-1ACX1PN-209-N'
    assert [k["tag"] for k in c["components"]] == ["201-HV-001", "201-HV-003"], "ordre amont -> aval"
    assert c["from"]["tag"] == "201-PP-001/A" and c["to"]["tag"] == "201-TK-001"
    assert c["flow_basis"] == "equipment_role", "le role des equipements doit etre reconnu malgre le prefixe de zone"


def test_sens_inverse_si_les_equipements_sont_dessines_a_l_envers():
    segs = [((0, 0), (200, 0))]
    symbols = [Symbol("equipment", 200, 0, 10, 10, "201-PP-001/A"), Symbol("equipment", 0, 0, 10, 10, "201-TK-001")]
    c = CircuitGraph(segs, symbols, [], snap_tol=1.0).chains[0]
    assert c["from"]["tag"] == "201-PP-001/A" and c["to"]["tag"] == "201-TK-001"


def test_vanne_pont_relie_deux_troncons():
    segs = [((0, 0), (90, 0)), ((110, 0), (200, 0))]           # trou de 20 : symbole de vanne dans le trou
    g = CircuitGraph(segs, [Symbol("valve", 100, 0, 20, 8, "201-HV-009")], [], snap_tol=1.0)
    assert len(g.chains) == 1 and [k["tag"] for k in g.chains[0]["components"]] == ["201-HV-009"]


def test_graphe_vide_ne_plante_pas():
    g = CircuitGraph([], [], [], snap_tol=1.0)
    assert g.chains == [] and g.trace(0, 0) is None


def test_pid_viewer_reconnait_les_tags_avec_prefixe_de_zone():
    pytest.importorskip("fitz")                 # PyMuPDF
    import pid_viewer
    assert pid_viewer._VALVE_TAG.match("201-HV-003") and pid_viewer._VALVE_TAG.match("HV-003")
    assert pid_viewer._EQUIP_TAG.match("201-PP-001/A") and pid_viewer._EQUIP_TAG.match("P-101")


def test_parse_line_tag_reel_et_parseur_dxf_s_accordent_sur_les_numeros_de_ligne():
    """Recoupement de deux implementations independantes sur les numeros de ligne du plan C3421-ROK1-200."""
    import piping_topology_tracer as tracer
    if getattr(tracer, "__file__", None) is None:                       # stub minimal : pas de recoupement possible
        pytest.skip("vrai piping_topology_tracer absent")
    import dxf_pid_parser
    cfg = dxf_pid_parser.load_config(None)
    for tag in ['20"-LP-1ACX1PN-209-N', '3/4"-LP-1ACX1PN-209-N', '2"-NG-1ACX1PN-205-N', '40"-LP-1ACX1PN-201-N']:
        real = tracer.parse_line_tag(tag)
        mine = dxf_pid_parser.classify(tag, cfg)
        assert real and mine and mine["kind"] == "line", tag
        assert (real["size"], real["fluid"], real["seq"], real["spec"]) == \
               (mine["parts"]["nps"], mine["parts"]["fluid"], mine["parts"]["seq"], mine["parts"]["spec"]), tag
    assert tracer.parse_line_tag("201-HV-003") is None and dxf_pid_parser.classify("201-HV-003", cfg)["kind"] == "valve"

