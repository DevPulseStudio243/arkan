# -*- coding: utf-8 -*-
import math, textwrap
import ezdxf, pytest
import config_loader as cl
import ie_drawing_extractor as ex


def new_doc(units=4):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = units
    for name in ("CABLETRAY", "MALT", "FOURREAU", "LEGENDE", "CHAMBRES", "AUTRE"):
        doc.layers.add(name)
    return doc


def extract(doc, name="plan.dxf", **opts):
    return ex.extract_ie_from_dxf_doc(doc, name, opts or None)


def by_cat(res, cat):
    return [i for i in res["items"] if i["category"] == cat]


def set_cfg(tmp_path, monkeypatch, text):
    p = tmp_path / "c2.yaml"; p.write_text(textwrap.dedent(text), encoding="utf-8")
    monkeypatch.setenv(cl.ENV_PATH, str(p)); cl._CACHE.clear()


# ---------------------------------------------------------------- unités
@pytest.mark.parametrize("code,coord,expected_m", [(4, 10000, 10.0), (5, 1000, 10.0), (6, 10, 10.0), (1, 393.7008, 10.0), (2, 32.8084, 10.0)])
def test_insunits_table(code, coord, expected_m):
    doc = new_doc(code); msp = doc.modelspace()
    msp.add_line((0, 0), (coord, 0), dxfattribs={"layer": "MALT"})
    msp.add_line((0, 0), (coord, 0), dxfattribs={"layer": "FOURREAU"})
    res = extract(doc)
    assert sum(i["quantity"] for i in by_cat(res, "EARTHING")) == pytest.approx(expected_m, rel=1e-3)
    assert res["metadata"]["units_assumed"] is False


def test_unspecified_units_flagged_not_silent():
    doc = new_doc(0); doc.modelspace().add_line((0, 0), (10000, 0), dxfattribs={"layer": "MALT"})
    res = extract(doc)
    assert res["metadata"]["units_assumed"] is True and any("CONFIRMER" in w for w in res["metadata"]["warnings"])
    it = by_cat(res, "EARTHING")[0]
    assert any("unités" in r for r in it["extractor_reasons"]) and it["confidence_score"] <= 0.6


def test_unit_override_option():
    doc = new_doc(0); doc.modelspace().add_line((0, 0), (10, 0), dxfattribs={"layer": "MALT"})
    res = extract(doc, units="m")
    assert by_cat(res, "EARTHING")[0]["quantity"] == pytest.approx(10.0)
    assert res["metadata"]["units_assumed"] is False


def test_assumed_units_from_config(tmp_path, monkeypatch):
    set_cfg(tmp_path, monkeypatch, "ie_extraction: {assumed_units: cm}\n")
    doc = new_doc(0); doc.modelspace().add_line((0, 0), (1000, 0), dxfattribs={"layer": "MALT"})
    assert by_cat(extract(doc), "EARTHING")[0]["quantity"] == pytest.approx(10.0)


def test_implausible_extent_warns():
    doc = new_doc(6); doc.modelspace().add_line((0, 0), (1.0, 0), dxfattribs={"layer": "MALT"})
    assert any("probablement erronées" in w for w in extract(doc)["metadata"]["warnings"])


# ---------------------------------------------------------------- géométries
def test_bulge_polyline_arc_and_spline_are_measured():
    doc = new_doc(6); msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0, 1), (2, 0, 0)], format="xyb", dxfattribs={"layer": "MALT"})     # demi-cercle R=1 : π
    msp.add_arc((20, 0), radius=5, start_angle=0, end_angle=180, dxfattribs={"layer": "MALT"})  # 5π
    msp.add_line((40, 0), (50, 0), dxfattribs={"layer": "MALT"})                                # 10
    res = extract(doc)
    assert sum(i["quantity"] for i in by_cat(res, "EARTHING")) == pytest.approx(math.pi + 5 * math.pi + 10, rel=1e-2)


def test_polyline_3d_and_spline():
    doc = new_doc(6); msp = doc.modelspace()
    msp.add_polyline3d([(0, 0, 0), (10, 0, 0), (10, 10, 0)], dxfattribs={"layer": "MALT"})
    msp.add_spline(fit_points=[(30, 0), (35, 3), (40, 0)], dxfattribs={"layer": "MALT"})
    q = sum(i["quantity"] for i in by_cat(extract(doc), "EARTHING"))
    assert 25 < q < 40


def test_nested_block_with_scale_and_layer_zero_inheritance():
    doc = new_doc(6)
    inner = doc.blocks.new("INNER"); inner.add_line((0, 0), (1, 0), dxfattribs={"layer": "0"})
    outer = doc.blocks.new("OUTER"); outer.add_blockref("INNER", (0, 0), dxfattribs={"layer": "0"})
    ins = doc.modelspace().add_blockref("OUTER", (0, 0), dxfattribs={"layer": "MALT", "xscale": 5, "yscale": 5})
    res = extract(doc)
    assert sum(i["quantity"] for i in by_cat(res, "EARTHING")) == pytest.approx(5.0)


def test_duplicate_entities_removed_and_hidden_layers_skipped():
    doc = new_doc(6); msp = doc.modelspace()
    for _ in range(3):
        msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "MALT"})
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "FOURREAU"})
    doc.layers.get("FOURREAU").off()
    res = extract(doc)
    assert sum(i["quantity"] for i in by_cat(res, "EARTHING")) == pytest.approx(10.0)
    assert res["metadata"]["duplicates_removed"] == 2 and not by_cat(res, "CONDUIT")


def test_entity_cap(tmp_path, monkeypatch):
    set_cfg(tmp_path, monkeypatch, "thresholds: {dwg_max_entities_memory_cap: 5}\n")
    doc = new_doc(6); msp = doc.modelspace()
    for k in range(20):
        msp.add_line((0, k), (10, k), dxfattribs={"layer": "MALT"})
    res = extract(doc)
    assert any("tronqué" in w for w in res["metadata"]["warnings"])


# ---------------------------------------------------------------- chemins de câbles
def tray_rails(msp, y0, length, gap, layer="CABLETRAY"):
    msp.add_line((0, y0), (length, y0), dxfattribs={"layer": layer})
    msp.add_line((0, y0 + gap), (length, y0 + gap), dxfattribs={"layer": layer})


def test_double_rail_tray_is_halved_by_detection_and_sized_by_annotation():
    doc = new_doc(4); msp = doc.modelspace()
    tray_rails(msp, 0, 20000, 200)                                   # 20 m, rails à 200 mm
    msp.add_text("200x50", dxfattribs={"insert": (5000, 400), "layer": "AUTRE"})
    res = extract(doc)
    t = by_cat(res, "CABLE_TRAY")
    assert len(t) == 1 and t[0]["size"] == "200x50 mm" and t[0]["quantity"] == pytest.approx(20.0, rel=1e-3)
    assert res["metadata"]["tray_convention"]["mode"] == "double_rail"
    assert t[0]["weight_unit"] == 3.2 and t[0]["weight_source"] == "TABLE_INDICATIVE"
    assert t[0]["source_handles"]                                    # traçabilité DXF


def test_single_line_tray_is_not_halved():
    doc = new_doc(6); msp = doc.modelspace()
    msp.add_line((0, 0), (15, 0), dxfattribs={"layer": "CABLETRAY"})
    msp.add_line((15, 0), (15, 12), dxfattribs={"layer": "CABLETRAY"})
    msp.add_text("100x50", dxfattribs={"insert": (7, 1), "layer": "AUTRE"})
    res = extract(doc)
    trays = by_cat(res, "CABLE_TRAY")
    assert sum(t["quantity"] for t in trays) == pytest.approx(27.0, rel=1e-3)          # l'ancien « / 2 » donnait 13,5
    sized = {t["size"]: t["quantity"] for t in trays}
    assert sized["100x50 mm"] == pytest.approx(15.0) and sized[""] == pytest.approx(12.0)   # le tronçon à > 5 m de l'annotation reste « non annoté »
    assert res["metadata"]["tray_convention"]["mode"] == "single_line"


def test_convention_forced_by_option():
    doc = new_doc(6); msp = doc.modelspace(); msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "CABLETRAY"})
    assert by_cat(extract(doc, tray_convention="double_rail"), "CABLE_TRAY")[0]["quantity"] == pytest.approx(5.0)


def test_unannotated_tray_has_no_invented_split():
    doc = new_doc(4); tray_rails(doc.modelspace(), 0, 10000, 200)
    t = by_cat(extract(doc), "CABLE_TRAY")
    assert len(t) == 1 and t[0]["size"] == "" and t[0]["tag"] == "CDC-NON-ANNOTE"     # plus de 40 / 50 / 10 %
    assert t[0]["confidence_score"] <= 0.5 and t[0]["extractor_reasons"]


def test_two_annotations_split_by_proximity():
    doc = new_doc(4); msp = doc.modelspace()
    tray_rails(msp, 0, 20000, 200)
    msp.add_text("100x50", dxfattribs={"insert": (1000, 300), "layer": "AUTRE"})
    msp.add_text("300x50", dxfattribs={"insert": (19000, 300), "layer": "AUTRE"})
    sizes = {i["size"]: i["quantity"] for i in by_cat(extract(doc), "CABLE_TRAY")}
    assert set(sizes) == {"100x50 mm", "300x50 mm"} and sum(sizes.values()) == pytest.approx(20.0, rel=1e-2)
    assert sizes["100x50 mm"] == pytest.approx(10.0, abs=1.5)


def test_pull_box_dimensions_not_taken_as_tray_size():
    doc = new_doc(4); msp = doc.modelspace(); tray_rails(msp, 0, 10000, 200)
    msp.add_text("Chambre 600x600x700", dxfattribs={"insert": (5000, 400), "layer": "AUTRE"})
    assert by_cat(extract(doc), "CABLE_TRAY")[0]["size"] == ""


# ---------------------------------------------------------------- terre, piquets, buses
def test_earthing_by_annotation_and_weight_formula():
    doc = new_doc(6); msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "MALT"})
    msp.add_line((0, 50), (30, 50), dxfattribs={"layer": "MALT"})
    msp.add_text("Cu nu 50 mm2", dxfattribs={"insert": (50, 2), "layer": "AUTRE"})
    msp.add_text("Cu nu 70 mm2", dxfattribs={"insert": (15, 52), "layer": "AUTRE"})
    sec = {i["size"]: i for i in by_cat(extract(doc), "EARTHING")}
    assert sec["50 mm²"]["quantity"] == pytest.approx(100.0) and sec["70 mm²"]["quantity"] == pytest.approx(30.0)
    assert sec["50 mm²"]["weight_unit"] == 0.448 and sec["70 mm²"]["weight_unit"] == 0.627        # CEI 60228 : S × 8,96


def test_earthing_without_annotation_is_flagged_or_uses_config(tmp_path, monkeypatch):
    doc = new_doc(6); doc.modelspace().add_line((0, 0), (40, 0), dxfattribs={"layer": "MALT"})
    it = by_cat(extract(doc), "EARTHING")[0]
    assert it["size"] == "" and it["weight_total"] is None and it["confidence_score"] <= 0.5
    set_cfg(tmp_path, monkeypatch, "ie_extraction: {earthing_default_section_mm2: 50}\n")
    it = by_cat(extract(doc), "EARTHING")[0]
    assert it["size"] == "50 mm²" and any("supposée" in r for r in it["extractor_reasons"])


def test_earth_rods_counted_with_geometric_weight():
    doc = new_doc(6)
    blk = doc.blocks.new("PIQUET_TERRE"); blk.add_circle((0, 0), 0.1)
    for k in range(7):
        doc.modelspace().add_blockref("PIQUET_TERRE", (k * 5, 0), dxfattribs={"layer": "MALT"})
    it = by_cat(extract(doc), "EARTH_ROD")[0]
    assert it["quantity"] == 7 and it["unit"] == "EA" and 3.0 < it["weight_unit"] < 3.8     # ≈ 3,4 kg (l'ancien code : 4,5)


def test_ducts_nb_tubes_and_diameter():
    doc = new_doc(6); msp = doc.modelspace()
    msp.add_line((0, 0), (30, 0), dxfattribs={"layer": "FOURREAU"})
    msp.add_text("2x%%c110 PVC PN10", dxfattribs={"insert": (15, 1), "layer": "AUTRE"})
    it = by_cat(extract(doc), "CONDUIT")[0]
    assert it["size"] == "2xØ110" and it["trench_length_m"] == pytest.approx(30.0) and it["quantity"] == pytest.approx(60.0)


# ---------------------------------------------------------------- chambres de tirage
def add_box_block(doc):
    blk = doc.blocks.new("CHAMBRE_TIRAGE"); blk.add_attdef("TAG", (0, 0)); blk.add_lwpolyline([(0, 0), (0.6, 0), (0.6, 0.6), (0, 0.6)], close=True)


def test_pull_box_block_with_attribute_tag():
    doc = new_doc(6); add_box_block(doc)
    ins = doc.modelspace().add_blockref("CHAMBRE_TIRAGE", (10, 10)); ins.add_auto_attribs({"TAG": "300-EL-312"})
    boxes = by_cat(extract(doc), "PULL_BOX")
    assert len(boxes) == 1 and boxes[0]["tag"] == "300-EL-312" and boxes[0]["confidence_score"] >= 0.9


def test_legend_text_is_not_a_pull_box_but_plan_text_is_with_lower_confidence():
    doc = new_doc(6); msp = doc.modelspace()
    msp.add_text("CHAMBRE DE TIRAGE 600x600x700", dxfattribs={"insert": (0, 0), "layer": "LEGENDE"})
    assert by_cat(extract(doc), "PULL_BOX") == []
    msp.add_text("CHAMBRE DE TIRAGE 600x600x700", dxfattribs={"insert": (50, 50), "layer": "CHAMBRES"})
    b = by_cat(extract(doc), "PULL_BOX")
    assert len(b) == 1 and b[0]["confidence_score"] <= 0.6 and b[0]["size"] == "600x600x700 mm"
    assert any("texte seul" in r for r in b[0]["extractor_reasons"])


def test_close_detections_cluster_but_distant_boxes_do_not():
    doc = new_doc(6); msp = doc.modelspace(); add_box_block(doc)
    msp.add_blockref("CHAMBRE_TIRAGE", (10, 10))
    msp.add_text("Chambre de tirage", dxfattribs={"insert": (10.5, 10.5), "layer": "CHAMBRES"})     # même chambre
    msp.add_blockref("CHAMBRE_TIRAGE", (40, 10))
    assert len(by_cat(extract(doc), "PULL_BOX")) == 2


def test_tag_to_box_one_to_one_and_ambiguity():
    doc = new_doc(6); msp = doc.modelspace(); add_box_block(doc)
    msp.add_blockref("CHAMBRE_TIRAGE", (10, 10)); msp.add_blockref("CHAMBRE_TIRAGE", (20, 10))
    msp.add_text("300-EL-001", dxfattribs={"insert": (11, 11), "layer": "AUTRE"})
    msp.add_text("300-EL-002", dxfattribs={"insert": (21, 11), "layer": "AUTRE"})
    tags = sorted(b["tag"] for b in by_cat(extract(doc), "PULL_BOX"))
    assert tags == ["300-EL-001", "300-EL-002"]
    doc2 = new_doc(6); m2 = doc2.modelspace(); add_box_block(doc2)
    m2.add_blockref("CHAMBRE_TIRAGE", (10, 10))
    m2.add_text("300-EL-001", dxfattribs={"insert": (11, 10), "layer": "AUTRE"})
    m2.add_text("300-EL-002", dxfattribs={"insert": (9, 10), "layer": "AUTRE"})
    b = by_cat(extract(doc2), "PULL_BOX")[0]
    assert any("ambigu" in r for r in b["extractor_reasons"]) and b["confidence_score"] <= 0.5


def test_box_without_tag_flagged_and_weight_not_invented():
    doc = new_doc(6); add_box_block(doc); doc.modelspace().add_blockref("CHAMBRE_TIRAGE", (10, 10))
    b = by_cat(extract(doc), "PULL_BOX")[0]
    assert b["tag"].startswith("CHAMBRE-") and b["weight_unit"] is None            # l'ancien code : 85 kg en dur
    assert any("aucun tag" in r for r in b["extractor_reasons"])


def test_reference_weight_from_config(tmp_path, monkeypatch):
    set_cfg(tmp_path, monkeypatch, "ie_extraction: {reference_weights: {pull_box_kg: 320}}\n")
    doc = new_doc(6); add_box_block(doc); doc.modelspace().add_blockref("CHAMBRE_TIRAGE", (10, 10))
    assert by_cat(extract(doc), "PULL_BOX")[0]["weight_total"] == 320


# ---------------------------------------------------------------- DWG : cache par hash du contenu
def test_dwg_cache_is_content_hash_not_name_and_size(tmp_path, monkeypatch):
    import sys, types
    calls = []
    def fake_convert(src, dst, timeout_sec=60):
        calls.append(src)
        d = new_doc(6); d.modelspace().add_line((0, 0), (10, 0), dxfattribs={"layer": "MALT"}); d.saveas(dst)
    mod = types.ModuleType("dwg_iso_extractor"); mod.convert_dwg_to_dxf_headless = fake_convert
    monkeypatch.setitem(sys.modules, "dwg_iso_extractor", mod)
    monkeypatch.chdir(tmp_path)
    a = tmp_path / "plan.dwg"; b = tmp_path / "autre.dwg"
    a.write_bytes(b"A" * 1000); b.write_bytes(b"B" * 1000)          # même taille, contenu différent
    ex.extract_ie_from_dwg_native(str(a), "plan.dwg"); ex.extract_ie_from_dwg_native(str(b), "plan.dwg")
    ex.extract_ie_from_dwg_native(str(a), "plan.dwg")                # 3e appel : cache
    assert len(calls) == 2                                           # l'ancienne clé (nom + taille) aurait confondu a et b


def test_unsupported_format():
    with pytest.raises(ValueError):
        ex.extract_ie_drawing("x.txt", "x.txt")
