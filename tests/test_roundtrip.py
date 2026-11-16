"""raw.json v2 : capture sans perte et reconstruction (raw_roundtrip.py). DXF genere par ezdxf, aucun fichier externe."""
import json
import math
import sys
from pathlib import Path

import ezdxf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("scipy")

import dxf_pid_parser
import raw_roundtrip


def make_dxf(path: Path) -> Path:
    doc = ezdxf.new("R2018", setup=True)
    doc.units = 4
    doc.layers.add("PIPE1")
    doc.layers.add("TEXT")
    # bloc asymetrique : polyligne avec arc (bulge), cercle, arc, ellipse complete, spline, hachure, solid, textes
    b = doc.blocks.new("SYM")
    b.add_lwpolyline([(0, 0, 0.5), (10, 0, 0), (10, 6, -0.3)], format="xyb")
    b.add_circle((10, 0), 2)
    b.add_arc((4, 4), 3, 20, 140)
    b.add_ellipse((6, 2), (2, 1, 0), 0.5, 0.3, 2 * math.pi + 0.3)
    b.add_spline([(0, 0), (3, 4), (6, -2), (9, 3)])
    h = b.add_hatch()
    h.set_solid_fill()
    h.paths.add_polyline_path([(0, 0), (2, 0), (2, 2), (0, 2)], is_closed=True)
    b.add_solid([(0, 0), (3, 0), (0, 3), (3, 3)])
    b.add_text("ABC", dxfattribs={"insert": (5, 5), "height": 2, "rotation": 30})
    b.add_attdef("INST_TYPE", (0, 0))
    msp = doc.modelspace()
    msp.add_blockref("SYM", (100, 50), dxfattribs={"xscale": -1, "yscale": 1}).add_auto_attribs({"INST_TYPE": "FIC"})
    msp.add_blockref("SYM", (200, 50), dxfattribs={"rotation": 90})                # bloc pivote
    msp.add_blockref("SYM", (300, 50), dxfattribs={"xscale": 2, "yscale": 2})      # bloc agrandi
    msp.add_line((0, 0), (50, 0), dxfattribs={"layer": "PIPE1"})
    msp.add_mtext("NOTE", dxfattribs={"insert": (10, 20), "char_height": 3, "layer": "TEXT"})
    doc.saveas(str(path))
    return path


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("rt")
    dxf = make_dxf(d / "sym.dxf")
    raw, _ = dxf_pid_parser.parse_dxf_to_raw_and_semantic(dxf, d / "out")
    return raw, dxf, d


def test_coverage_sans_perte(built):
    raw, _, _ = built
    cov = raw["coverage"]
    assert cov["lossless"] and not cov["unparsed_types"]
    assert cov["types"].get("ATTDEF", {"mode": "ignored_by_design"})["mode"] == "ignored_by_design"
    for t in ("LWPOLYLINE", "ARC", "ELLIPSE", "SPLINE", "HATCH", "SOLID"):
        assert cov["types"][t]["mode"] == "parametric", t


def test_bloc_en_miroir_positions_monde(built):
    raw, _, _ = built
    circles = sorted((r["pos"] for r in raw["entities"] if r["type"] == "CIRCLE"), key=lambda p: p[0])
    # cercle du bloc en (10, 0) : miroir en x autour de (100, 50) -> (90, 50) ; non mirore en (200+0, 50+10) etc.
    assert any(abs(p[0] - 90) < 1e-9 and abs(p[1] - 50) < 1e-9 for p in circles), circles
    txt = [r for r in raw["entities"] if r["type"] == "TEXT" and r["text"] == "ABC"]
    assert any(abs(t["pos"][0] - 95) < 1e-9 and abs(t["pos"][1] - 55) < 1e-9 for t in txt), [t["pos"] for t in txt]


def test_bulge_arcs_et_angles_conserves(built):
    raw, _, _ = built
    poly = [r for r in raw["entities"] if r["type"] == "LWPOLYLINE" and r["block_path"] == ["SYM"]]
    assert poly and any(abs(v[2]) > 1e-9 for p in poly for v in p["verts"]), "le bulge (arc) doit etre conserve"
    arcs = [r for r in raw["entities"] if r["type"] == "ARC"]
    assert arcs and all("start_angle" in a and "end_angle" in a for a in arcs)
    ell = [r for r in raw["entities"] if r["type"] == "ELLIPSE"][0]
    assert {"major_axis", "ratio", "start_param", "end_param"} <= set(ell)


def test_parent_et_matrice_des_inserts(built):
    raw, _, _ = built
    ins = [r for r in raw["entities"] if r["type"] == "INSERT" and r["name"] == "SYM"]
    assert len(ins) == 3 and {tuple(i["scale"][:2]) for i in ins} == {(-1.0, 1.0), (1.0, 1.0), (2.0, 2.0)}
    ids = {r["id"] for r in raw["entities"]}
    assert all(r["parent"] in ids for r in raw["entities"] if r.get("parent"))


def test_aller_retour_exact(built):
    raw, dxf, d = built
    rep = raw_roundtrip.verify(d / "out" / "raw.json", dxf, d / "rt", raster=False)
    assert rep["exact"], rep["problemes"]
    assert rep["espaces"]["model"]["counts_equal"]


def test_aller_retour_detecte_une_perte(built, tmp_path):
    """Le verificateur doit echouer si le JSON perd une information (ici : bulge supprime)."""
    raw, dxf, d = built
    broken = json.loads((d / "out" / "raw.json").read_text(encoding="utf-8"))
    for r in broken["entities"]:
        if r["type"] == "LWPOLYLINE":
            r["verts"] = [[v[0], v[1], 0.0] for v in r["verts"]]
    (tmp_path / "raw_broken.json").write_text(json.dumps(broken), encoding="utf-8")
    rep = raw_roundtrip.verify(tmp_path / "raw_broken.json", dxf, tmp_path / "rt", raster=False)
    assert not rep["exact"] and any("LWPOLYLINE" in p for p in rep["problemes"])
