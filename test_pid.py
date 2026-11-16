import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pytest
from make_sample_pdf import make
from piping_topology_tracer import Point2D, parse_line_tag, decode_gcb_pipe_spec
from arh_pid_topology_engine import ARHPidTopologyEngine
from pid_viewer import analyse_pdf, build_viewer


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    p = str(tmp_path_factory.mktemp("pdf") / "sample.pdf")
    make(p)
    return p


@pytest.fixture(scope="module")
def graph(sample):
    return analyse_pdf(sample)[1]


# ---------------- tracer : correctifs ----------------
def test_point2d_instantiable():
    assert Point2D(1.0, 2.0).as_tuple() == (1.0, 2.0)

@pytest.mark.parametrize("tag,size,fluid", [('10"-FG-5001-CS150', "10", "FG"), ("10-FG-5001-CS150", "10", "FG"),
                                            ('6"-CH-1200-A1A', "6", "CH")])
def test_parse_line_tag(tag, size, fluid):
    r = parse_line_tag(tag)
    assert r and r["size"] == size and r["fluid"] == fluid

@pytest.mark.parametrize("tag", ["HV-1001", "10-PT-1001", "SONATRACH 10-FG-5001"])
def test_parse_line_tag_rejects_non_lines(tag):
    assert parse_line_tag(tag) is None

def test_decode_spec_never_invents_values():
    r = decode_gcb_pipe_spec("CS150")
    assert r["decoded"] is False and r["rating"] == "" and r["corrosion_allowance"] == ""
    assert decode_gcb_pipe_spec("3RC")["rating"] == "300#"


# ---------------- ARH : correctifs ----------------
def test_line_tag_is_not_an_equipment():
    e = ARHPidTopologyEngine(); e.parse_pid_text('10"-P-5001-CS150  V-200')
    assert "P-5001" not in e.equipments and "V-200" in e.equipments

def test_low_is_not_locked_open():
    e = ARHPidTopologyEngine(); e.parse_pid_text("PSV-101 LOW PRESSURE   PSV-102 CSO")
    assert e.valves["PSV-101"]["lock_status"] == "NONE" and e.valves["PSV-102"]["lock_status"] == "CSO"

def test_cso_not_stolen_from_next_tag():
    e = ARHPidTopologyEngine(); e.parse_pid_text("HV-101  PSV-102 CSO")
    assert e.valves["HV-101"]["lock_status"] == "NONE"

def test_no_edges_means_no_false_findings():
    e = ARHPidTopologyEngine(); e.parse_pid_text("V-200 K-300 PSV-101")
    assert [f["id"] for f in e.audit_process_safety_rules()] == ["PID_TOPOLOGY_UNAVAILABLE"]

def test_psv_and_dbb_rules_with_topology():
    e = ARHPidTopologyEngine.fresh()
    e.load_from_line_entries([
        {"line_number": "L1", "from_equipment": "V-200", "line_components": [{"tag": "HV-101"}, {"tag": "PSV-101"}], "to_equipment": "FL-1"},
        {"line_number": "L2", "from_equipment": "V-200", "line_components": [{"tag": "HV-201"}, {"tag": "HV-202"}], "to_equipment": "K-300"}])
    ids = {f["id"] for f in e.audit_process_safety_rules()}
    assert ids == {"PID_PSV_NOCSO_PSV-101", "PID_DBB_NOBLEED_HV-201_HV-202"}


# ---------------- circuit_graph : ce que l'ancien tracer ne savait pas faire ----------------
def test_tee_on_segment_interior_gives_three_lines(graph):
    assert len(graph.chains) == 3
    assert len({c["circuit"] for c in graph.chains}) == 1

def test_valves_ordered_and_endpoints(graph):
    by_tag = {c["tag"]: c for c in graph.chains}
    main = by_tag['10"-FG-5001-CS150']
    assert main["from"]["tag"] == "V-101" and [k["tag"] for k in main["components"]] == ["HV-101"]
    assert main["to"]["kind"] == "junction"
    assert [k["tag"] for k in by_tag['4"-FG-5002-CS150']["components"]] == ["HV-103"]
    assert by_tag['4"-FG-5002-CS150']["to"]["tag"] == "TK-201"

def test_flow_from_arrow_and_unknown_is_honest(graph):
    by_tag = {c["tag"]: c for c in graph.chains}
    assert by_tag['10"-FG-5001-CS150']["flow_basis"] == "arrow"          # flèche vers la droite
    assert by_tag['10"-FG-5003-CS150']["flow_known"] is False            # ni flèche ni rôle -> on ne devine pas

def test_click_traces_line_then_circuit(graph):
    one = graph.trace(330, 300, "line")        # sur XV-102 côté tracé principal aval
    assert len(one["chains"]) == 1
    full = graph.trace(300, 200, "circuit")    # sur la branche
    assert len(full["chains"]) == 3
    assert graph.trace(10, 10) is None

def test_line_entries_feed_the_audit(graph):
    e = ARHPidTopologyEngine.fresh()
    e.load_from_line_entries(graph.to_line_entries("sample.pdf"))
    assert e.graph.number_of_edges() >= 3 and "V-101" in e.equipments

def test_viewer_html_is_built(sample, tmp_path):
    out = tmp_path / "v.html"
    build_viewer(sample, str(out))
    html = out.read_text(encoding="utf-8")
    assert "data:image/png;base64," in html and "HV-101" in html
