# -*- coding: utf-8 -*-
import pytest
import ie_drawing_extractor as ex

try:
    import pymupdf as fitz
except ImportError:
    import fitz


def make_table_pdf(path, rows, header=("TAG", "DESIGNATION", "P (kW)", "CALIBRE (A)", "CABLE", "LONGUEUR (m)"),
                   title="SCHEMA UNIFILAIRE TGBT BT", pages=1):
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=842, height=595)
        page.insert_text((40, 30), title, fontsize=14)
        x0, y0, cw, rh = 40, 60, 120, 28
        data = [header] + list(rows)
        for r, row in enumerate(data):
            for c, val in enumerate(row):
                rect = fitz.Rect(x0 + c * cw, y0 + r * rh, x0 + (c + 1) * cw, y0 + (r + 1) * rh)
                page.draw_rect(rect, color=(0, 0, 0), width=0.8)
                page.insert_textbox(rect + (3, 4, -3, -2), str(val), fontsize=8)
    doc.save(path); doc.close()


def make_column_pdf(path, columns, title="SCHEMA UNIFILAIRE TGBT", page_blocks=1):
    doc = fitz.open()
    for _ in range(page_blocks):
        page = doc.new_page(width=842, height=595)
        page.insert_text((40, 30), title, fontsize=14)
        for k, text in enumerate(columns):
            rect = fitz.Rect(40 + k * 90, 80, 40 + k * 90 + 70, 300)
            page.insert_textbox(rect, text, fontsize=7)
    doc.save(path); doc.close()


def run(path, **opts):
    return ex.extract_sld_from_pdf_matrix(str(path), "sld.pdf", opts or None)


ROWS = [
    ("300-P-101A", "Pompe huile", "315 kW", "630 A", "3x240+120", "42 m"),
    ("300-P-102A", "Pompe refrigerant", "45 kW", "100 A", "3x50+25", ""),
    ("300-MCC-01", "MCC principal", "", "400 A", "", ""),
]


def test_table_layout_reads_fields_and_never_invents_values(tmp_path):
    pdf = tmp_path / "t.pdf"; make_table_pdf(pdf, ROWS)
    res = run(pdf)
    f = {i["tag"]: i for i in res["items"]}
    assert set(f) == {"300-P-101A", "300-P-102A", "300-MCC-01"}
    a = f["300-P-101A"]
    assert (a["calibre_a"], a["cable_section"], a["power_kw"], a["quantity"]) == (630, "3X240+120", 315.0, 42.0)
    assert a["length_source"] == "SLD_TABLE" and a["extraction_mode"] == "TABLE" and a["source_page"] == 1
    b = f["300-P-102A"]
    assert b["quantity"] is None and b["length_source"] == "UNKNOWN" and b["weight_total"] is None   # plus de 35 m
    c = f["300-MCC-01"]
    assert c["cable_section"] is None and c["calibre_a"] == 400                                        # plus de 5X6 par défaut
    assert any("section" in r for r in c["extractor_reasons"]) and c["confidence_score"] < a["confidence_score"]
    assert res["metadata"]["total_cable_m"] == 42.0 and res["metadata"]["feeders_without_length"] == 2


def test_column_layout_without_ruling_lines(tmp_path):
    pdf = tmp_path / "c.pdf"
    make_column_pdf(pdf, ["300-P-101A\nPompe d'injection\n63 A\n4P3D\n3x25+16", "300-P-102A\nPompe\n100 A\n3P3D\n3x50+25"])
    res = run(pdf)
    f = {i["tag"]: i for i in res["items"]}
    assert f["300-P-101A"]["poles"] == "4P3D" and f["300-P-101A"]["calibre_a"] == 63      # 4P3D n'était pas reconnu
    assert f["300-P-102A"]["cable_section"] == "3X50+25" and f["300-P-102A"]["extraction_mode"] == "COLUMN"


def test_no_phantom_feeder_without_tag(tmp_path):
    pdf = tmp_path / "p.pdf"
    make_column_pdf(pdf, ["Pompe d'injection\n63 A\n3x25+16", "300-P-102A\n100 A\n3x50+25", "TRANSFO 630 kVA", "300-P-103A\n40 A\n3x16+16"])
    tags = [i["tag"] for i in run(pdf)["items"]]
    assert tags == ["300-P-102A", "300-P-103A"]                       # l'ancien code créait DEP-P1-xxx pour « POMPE » / « TRANSFO »


def test_missing_calibre_and_section_are_none_with_reasons(tmp_path):
    pdf = tmp_path / "m.pdf"; make_column_pdf(pdf, ["300-P-101A\nPompe", "300-P-102A\nPompe\n3x50+25\n100 A"])
    f = {i["tag"]: i for i in run(pdf)["items"]}
    x = f["300-P-101A"]
    assert x["calibre_a"] is None and x["cable_section"] is None and x["poles"] is None      # plus de 63 A / 5X6 / 4P4D
    assert len(x["extractor_reasons"]) >= 2 and x["confidence_score"] <= 0.5


def test_duplicates_between_pages_and_conflicts(tmp_path):
    pdf = tmp_path / "d.pdf"
    make_column_pdf(pdf, ["300-P-101A\n63 A\n3x25+16", "300-P-102A\n40 A\n3x16+16"], page_blocks=2)               # même départ répété page 2
    res = run(pdf)
    assert len(res["items"]) == 2 and any("doublon" in w for w in res["metadata"]["warnings"])
    doc = fitz.open(str(pdf)); p = doc[1]; p.add_redact_annot(fitz.Rect(0, 60, 842, 400)); p.apply_redactions()
    p.insert_textbox(fitz.Rect(40, 80, 110, 300), "300-P-101A\n100 A\n3x50+25", fontsize=7)
    p.insert_textbox(fitz.Rect(130, 80, 200, 300), "300-P-102A\n40 A\n3x16+16", fontsize=7)
    doc.save(str(tmp_path / "d2.pdf")); doc.close()
    res2 = run(tmp_path / "d2.pdf")
    assert len(res2["items"]) == 3 and any("déjà vu" in r for it in res2["items"] for r in it["extractor_reasons"])


def test_unknown_pdf_is_rejected_not_forced_into_sld(tmp_path):
    pdf = tmp_path / "u.pdf"; make_column_pdf(pdf, ["Notice de montage\nPompe P-101A"], title="NOTICE")
    res = run(pdf)
    assert res["items"] == [] and res["metadata"]["doc_type"] == "UNKNOWN" and res["metadata"]["warnings"]
    forced = run(pdf, doc_type="ELEC_SLD_BT")
    assert forced["metadata"]["doc_type"] == "ELEC_SLD_BT"


def test_busbar_trunking_section_kept(tmp_path):
    pdf = tmp_path / "b.pdf"; make_column_pdf(pdf, ["300-TRP-001\nCANALISATION\n1600 A", "300-P-001\n63 A\n3x25+16"])
    it = next(i for i in run(pdf)["items"] if i["tag"] == "300-TRP-001")
    assert it["cable_section"] == "CANALISATION" and it["cable_type"] is None


def test_extract_ie_drawing_dispatch(tmp_path):
    pdf = tmp_path / "x.pdf"; make_column_pdf(pdf, ["300-P-101A\n63 A\n3x25+16", "300-P-102A\n100 A\n3x50+25"])
    assert len(ex.extract_ie_drawing(str(pdf), "sld.pdf")["items"]) == 2


def test_end_to_end_with_consolidator(tmp_path):
    """SLD -> expand_feeders -> Excel : la longueur inconnue n'est pas inventée et la ligne est à valider."""
    import openpyxl, mto_consolidator as mc
    pdf = tmp_path / "e.pdf"; make_table_pdf(pdf, ROWS)
    items = ex.extract_ie_drawing(str(pdf), "sld.pdf")["items"]
    out = tmp_path / "o.xlsx"
    mc.generate_master_multidiscipline_excel(items, {"filename": "sld.pdf"}, [], str(out))
    wb = openpyxl.load_workbook(out)
    cab = [r for r in wb["CARNET_DE_CABLES"].iter_rows(min_row=2, values_only=True) if r[1] and str(r[1]).startswith("C-")]
    assert len(cab) == 2                                           # 3 départs, 2 avec section lisible
    valider = [r[1] for r in wb["A_VALIDER"].iter_rows(min_row=2, values_only=True) if r[1]]
    assert "C-300-P-102A-PWR" in valider and "C-300-P-101A-PWR" not in valider      # longueur lue = de confiance
