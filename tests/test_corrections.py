"""
Tests de non-regression des erreurs corrigees (voir CORRECTIONS.md).
Aucun fichier externe requis : les DXF sont generes par ezdxf.
"""
import copy
import json
import sys
from pathlib import Path

import ezdxf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dwg_converter
import dxf_pid_parser
from arh_pid_topology_engine import ARHPidTopologyEngine


# ----------------------------------------------------------------------------
# Fabrique d'un petit P&ID realiste (memes conventions que le plan reel C3421-ROK1-200)
# ----------------------------------------------------------------------------
def make_pid(path: Path) -> Path:
    doc = ezdxf.new("R2018", setup=True)
    doc.units = 4
    for n in ("PIPE1", "vannes", "INST1", "EQP1", "TEXT"):
        doc.layers.add(n)
    msp = doc.modelspace()

    # instrument : le tag est coupe en deux attributs INST_TYPE / INST_NO
    b = doc.blocks.new("INSTG2002")
    b.add_circle((0, 0), 10)
    b.add_attdef("INST_TYPE", (0, 5))
    b.add_attdef("INST_NO", (0, -5))
    # bloc imbrique : un bloc "vanne" contenu dans un bloc "groupe" (recursion de blocs)
    inner = doc.blocks.new("VANNE_IN")
    inner.add_circle((0, 0), 6)
    inner.add_text("201-HV-009", dxfattribs={"insert": (0, -12), "height": 4})
    outer = doc.blocks.new("GROUPE")
    outer.add_blockref("VANNE_IN", (20, 0))

    # tuyauterie : une ligne coupee par une vanne (trou de 20 unites), puis une branche en T
    msp.add_line((0, 0), (1000, 0), dxfattribs={"layer": "PIPE1"})
    msp.add_line((1020, 0), (1500, 0), dxfattribs={"layer": "PIPE1"})
    msp.add_line((1500, 0), (2000, 0), dxfattribs={"layer": "PIPE1"})      # jonction en T au noeud (1500, 0)
    msp.add_line((1500, 0), (1500, 400), dxfattribs={"layer": "PIPE1"})
    msp.add_blockref("GROUPE", (1010, 0), dxfattribs={"layer": "vannes"})
    # numeros de ligne : fraction empilee MTEXT (3/4") et ligne normale
    msp.add_mtext('\\S3#4;"-LP-1ACX1PN-209-N', dxfattribs={"insert": (500, 30), "layer": "TEXT", "char_height": 5})
    # meme numero repete sur le meme run (etiquette en double) : ne doit PAS produire d'avertissement
    msp.add_mtext('\\S3#4;"-LP-1ACX1PN-209-N', dxfattribs={"insert": (1250, 30), "layer": "TEXT", "char_height": 5})
    msp.add_text('20"-LP-1ACX1PN-214-N', dxfattribs={"insert": (1700, 30), "height": 5, "layer": "TEXT"})
    msp.add_text('2"-LP-1ACX1PN-210-N', dxfattribs={"insert": (1530, 200), "height": 5, "layer": "TEXT"})
    # equipements en bout de ligne (blocs a attribut TAG) : pas de pompe dessinee a la main ici
    eq = doc.blocks.new("EQUIP")
    eq.add_lwpolyline([(-40, -25), (40, -25), (40, 25), (-40, 25)], close=True)
    eq.add_attdef("TAG", (0, 0))
    for tag, pos in (("201-PP-001/A", (-40, 0)), ("201-CH-001", (2040, 0))):
        r = msp.add_blockref("EQUIP", pos, dxfattribs={"layer": "EQP1"})
        r.add_auto_attribs({"TAG": tag})
    # instrument pose sur la ligne
    r = msp.add_blockref("INSTG2002", (300, 60), dxfattribs={"layer": "INST1"})
    r.add_auto_attribs({"INST_TYPE": "FIC", "INST_NO": "210"})
    doc.saveas(str(path))
    return path


@pytest.fixture(scope="module")
def parsed(tmp_path_factory):
    d = tmp_path_factory.mktemp("pid")
    dxf = make_pid(d / "plan_test.dxf")
    raw, sem = dxf_pid_parser.parse_dxf_to_raw_and_semantic(dxf, d / "out")
    return raw, sem, d


# ----------------------------------------------------------------------------
# dxf_pid_parser
# ----------------------------------------------------------------------------
def test_load_config_ne_mute_pas_la_config_par_defaut(tmp_path):
    ref = copy.deepcopy(dxf_pid_parser.DEFAULT_CONFIG)
    custom = tmp_path / "cfg.json"
    custom.write_text(json.dumps({"layers": {"piping": ["MONCALQUE"]}}), encoding="utf-8")
    cfg = dxf_pid_parser.load_config(custom)
    assert "MONCALQUE" in cfg["layers"]["piping"]
    assert dxf_pid_parser.DEFAULT_CONFIG == ref, "DEFAULT_CONFIG a ete modifie (copie superficielle)"


def test_layer_role_pas_de_faux_positif_de_sous_chaine():
    assert dxf_pid_parser.layer_role("TB1") == "titleblock"
    assert dxf_pid_parser.layer_role("OUTBOUND") == "other"      # contenait 'TB'
    assert dxf_pid_parser.layer_role("vannes") == "valve"
    assert dxf_pid_parser.layer_role("PIPE2") == "piping"


def test_instrument_recompose_depuis_les_attributs(parsed):
    _, sem, _ = parsed
    tags = {e["tag"]: e for e in sem["elements"] if e["kind"] == "instrument"}
    assert "FIC-210" in tags, "INST_TYPE + INST_NO doivent etre recombines en FIC-210"
    assert tags["FIC-210"]["parts"]["pre"] == "FIC"


def test_fraction_empilee_mtext_normalisee(parsed):
    _, sem, _ = parsed
    nps = {l["tag_raw"]: l["nps"] for l in sem["lines"] if l["tag_raw"]}
    assert nps['3/4"-LP-1ACX1PN-209-N'] == "3/4", f"fraction perdue : {nps}"


def test_blocs_imbriques_lus_recursivement(parsed):
    _, sem, _ = parsed
    assert "201-HV-009" in {e["tag"] for e in sem["elements"] if e["kind"] == "valve"}


def test_lignes_issues_de_la_geometrie_avec_pontage_vanne(parsed):
    _, sem, _ = parsed
    tagged = {l["tag_raw"] for l in sem["lines"] if l["tag_raw"]}
    assert tagged == {'3/4"-LP-1ACX1PN-209-N', '20"-LP-1ACX1PN-214-N', '2"-LP-1ACX1PN-210-N'}
    # la ligne 209 est coupee par la vanne (trou de 20) : UN seul run, deux troncons, un seul numero
    run_209 = [l for l in sem["lines"] if l["tag_raw"] == '3/4"-LP-1ACX1PN-209-N']
    assert len(run_209) == 1 and len(run_209[0]["segments"]) == 2
    # la jonction en T coupe : 3 runs (209, 214, 210)
    assert len([l for l in sem["lines"] if l["tag_raw"]]) == 3
    # etiquette en double : aucun avertissement parasite
    codes = {w["code"] for w in sem["warnings"]}
    assert "TEXT_UNATTACHED" not in codes and "LINE_TAG_CONFLICT" not in codes


def test_line_entries_et_boucles_produits(parsed):
    _, sem, _ = parsed
    assert sem["line_entries"], "line_entries vide : le moteur topologique n'a rien a consommer"
    assert isinstance(sem["loops"], list)
    assert all("line_number" in e and "line_components" in e for e in sem["line_entries"])


def test_pas_de_valeur_inventee_dans_le_cartouche(parsed):
    _, sem, _ = parsed
    assert sem["titleblock"]["drawing_number"] == "plan_test"
    assert sem["titleblock"]["drawing_number_source"] == "filename"


def test_revue_humaine_appliquee(tmp_path):
    dxf = make_pid(tmp_path / "plan_test.dxf")
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"equipment": [
        {"candidate_id": "EQC-01", "decision": "confirm", "tag": "201-CH-001", "equipment_type": "strainer / filtre",
         "bbox": [2000.0, -25.0, 2080.0, 25.0], "entity_ids": []}]}), encoding="utf-8")
    _, sem = dxf_pid_parser.parse_dxf_to_raw_and_semantic(dxf, review=review)
    ch = next(e for e in sem["elements"] if e["tag"] == "201-CH-001")
    assert ch["review_status"] == "human_confirmed" and ch["equipment_type"] == "strainer / filtre"
    assert ch["confidence"] == 1.0


# ----------------------------------------------------------------------------
# arh_pid_topology_engine
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("tag,expected", [
    ("201-HV-003", "MANUAL_VALVE"),   # prefixe de zone : etait classe comme equipement
    ("HV-003", "MANUAL_VALVE"),
    ("201-FV-216", "VALVE"),
    ("201-PSV-101", "PSV"),
    ("201-PP-001/A", None),
])
def test_classification_tags_avec_prefixe_de_zone(tag, expected):
    assert ARHPidTopologyEngine._classify(tag) == expected


def test_vanne_avec_zone_n_est_plus_un_equipement_isole():
    eng = ARHPidTopologyEngine.fresh()
    eng.load_from_line_entries([{"line_number": 'L1', "fluid": "LP", "from_equipment": "201-PP-001/A",
                                 "to_equipment": "201-CH-001", "line_components": [{"tag": "201-HV-003"}]}])
    assert "201-HV-003" in eng.valves


# ----------------------------------------------------------------------------
# dwg_converter
# ----------------------------------------------------------------------------
def test_validate_dxf_rejette_un_dxf_tronque(tmp_path):
    good = make_pid(tmp_path / "ok.dxf")
    assert dwg_converter.validate_dxf(good)
    bad = tmp_path / "tronque.dxf"
    bad.write_bytes(good.read_bytes()[:3000])
    assert not dwg_converter.validate_dxf(bad), "un DXF tronque (> 100 octets) ne doit plus passer pour valide"


def test_conversion_sans_moteur_ne_renvoie_pas_un_ancien_dxf(tmp_path, monkeypatch):
    monkeypatch.setenv("ARKAN_CAD_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(dwg_converter, "_ENGINES", [])
    dwg = tmp_path / "plan.dwg"
    dwg.write_bytes(b"AC1032" + b"\0" * 500)
    stale = tmp_path / "plan.dxf"
    stale.write_text("ancien contenu perime " * 20)
    with pytest.raises(dwg_converter.DWGConversionError):
        dwg_converter.convert_dwg_to_dxf(str(dwg), str(stale))
    assert stale.read_text().startswith("ancien"), "le fichier cible ne doit pas etre ecrase par un echec"


def test_cache_par_contenu_et_moteur_invalide(tmp_path, monkeypatch):
    monkeypatch.setenv("ARKAN_CAD_CACHE", str(tmp_path / "cache"))
    good = make_pid(tmp_path / "src.dxf")
    calls = {"n": 0}

    def fake_engine(dwg, out, version, timeout):
        calls["n"] += 1
        out.write_bytes(good.read_bytes())

    def broken_engine(dwg, out, version, timeout):
        out.write_bytes(good.read_bytes()[:4000])         # DXF tronque : doit etre rejete

    dwg = tmp_path / "plan.dwg"
    dwg.write_bytes(b"AC1032" + b"\1" * 500)
    monkeypatch.setattr(dwg_converter, "_ENGINES", [("casse", broken_engine), ("ok", fake_engine)])
    out1 = dwg_converter.convert_dwg_to_dxf(str(dwg))
    assert dwg_converter.validate_dxf(out1) and calls["n"] == 1
    dwg_converter.convert_dwg_to_dxf(str(dwg))
    assert calls["n"] == 1, "le 2e appel doit venir du cache"
    dwg.write_bytes(b"AC1032" + b"\2" * 500)               # DWG revise sous le meme nom
    dwg_converter.convert_dwg_to_dxf(str(dwg))
    assert calls["n"] == 2, "un DWG modifie doit etre reconverti"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only test incompatible avec Windows pathlib")
def test_exe_windows_ignore_hors_windows(monkeypatch):
    monkeypatch.setattr(dwg_converter.os, "name", "posix")
    found = dwg_converter._find_libredwg()
    assert not found.lower().endswith(".exe")


def test_cartouche_du_paperspace_et_prefixe_de_tags(tmp_path):
    """Le cartouche est dans le paper space (attributs NUMDESSIN / NUMREV...) et une note annonce le prefixe des tags."""
    doc = ezdxf.new("R2018", setup=True)
    cart = doc.blocks.new("CARTOUCHE_A1")
    for tag in ("NUMDESSIN", "NUMREV", "DISCIPLINE", "1.REV.DATE.", "1.EMIS.BUTE.", "1.REV.DESS.PAR."):
        cart.add_attdef(tag, (0, 0))
    lay = doc.layouts.new("FEUILLE-1")
    lay.add_blockref("CARTOUCHE_A1", (0, 0)).add_auto_attribs({
        "NUMDESSIN": "X1-200-PRC-0042", "NUMREV": "3", "DISCIPLINE": "PROCESS",
        "1.REV.DATE.": "01/02/2026", "1.EMIS.BUTE.": "EMIS POUR COMMENTAIRES", "1.REV.DESS.PAR.": "A.B"})
    lay.add_text("REV N", dxfattribs={"insert": (5, 5), "height": 2})            # texte parasite
    msp = doc.modelspace()
    msp.add_mtext("NOTES: TOUS LES TAGS DES VANNES ET INSTRUMENTS SONT PREFIXES DE 201.",
                  dxfattribs={"insert": (0, 100), "char_height": 3})
    b = doc.blocks.new("INSTG")
    b.add_attdef("INST_TYPE", (0, 0))
    b.add_attdef("INST_NO", (0, -3))
    msp.add_blockref("INSTG", (10, 10)).add_auto_attribs({"INST_TYPE": "FIC", "INST_NO": "210"})
    dxf = tmp_path / "x.dxf"
    doc.saveas(str(dxf))
    _, sem = dxf_pid_parser.parse_dxf_to_raw_and_semantic(dxf)
    tb = sem["titleblock"]
    assert tb["drawing_number"] == "X1-200-PRC-0042" and tb["drawing_number_source"] == "titleblock_attribute:NUMDESSIN"
    assert tb["revision"] == "3" and tb["discipline"] == "PROCESS"
    assert tb["revisions"][0]["purpose"] == "EMIS POUR COMMENTAIRES" and tb["revisions"][0]["date"] == "01/02/2026"
    assert sem["tag_prefix"]["value"] == "201"
    inst = next(e for e in sem["elements"] if e["tag"] == "FIC-210")
    assert inst["full_tag"] == "201-FIC-210"
    assert all(e["bbox"] for e in sem["elements"]), "les elements de la semantique ne viennent que du model space"

