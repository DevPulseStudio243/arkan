"""
dxf_pid_parser.py
=================
Pipeline vectoriel P&ID pour ARKAN : DXF (ou DWG converti) -> raw.json -> semantic.json -> digest.json

API conservee :
  - load_config(config_path=None) -> dict
  - layer_role(layer_name, cfg=None) -> str
  - parse_dxf_to_raw_and_semantic(dxf_or_dwg_path, out_folder=None, cfg=None, review=None) -> (raw, semantic)
  - parse_file(dxf_or_dwg_path, out_folder=None) -> {"raw", "semantic"}

Ce que produit semantic.json :
  - elements   : equipements / vannes / instruments (tags decomposes, position, lien au symbole, confiance)
  - lines      : "runs" de tuyauterie issus de la GEOMETRIE (extremites raccordees par snapping, coupes aux jonctions),
                 un numero de ligne n'est rattache qu'a un seul run
  - line_entries : format attendu par arh_pid_topology_engine.load_from_line_entries
  - loops      : boucles de regulation (transmetteur / regulateur / organe final)
  - warnings   : proxy Plant 3D, tags non rattaches, lignes sans tag, equipements non connectes ou a confirmer...
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ezdxf
from ezdxf import bbox as ez_bbox
from ezdxf import recover
from ezdxf import units as ez_units
from ezdxf import upright as _upright

# Conversion DWG -> DXF avec fallback multi-moteurs
try:
    from dwg_converter import ensure_dxf
except ImportError:  # pragma: no cover
    def ensure_dxf(path: str) -> str:
        if str(path).lower().endswith(".dxf"):
            return str(path)
        raise RuntimeError(f"dwg_converter introuvable pour convertir {path}")

logger = logging.getLogger("dxf_pid_parser")

PARSER_VERSION = "2.1.0"
SCHEMA_VERSION = "1.0"
SCHEMA_VERSION_RAW = "2.0"
_FLIPPED_Z = (0.0, 0.0, -1.0)

DEFAULT_CONFIG: Dict[str, Any] = {
    "layers": {
        "titleblock": ["CARTOUCHE", "BORDER", "CADRE", "TITLE", "FRAME", "TITRE", "FORMAT", "TB",
                       "FORMATO", "CART", "CADRE_TITRE", "BORDER_A1", "BORDER_A0"],
        "ignore": ["DEFPOINTS", "VIEWPORT", "VPORT", "REVCLOUD", "REVISION", "NUAGE", "GRID",
                   "GRILLE", "HATCH", "COTATION", "DIM", "DIMENSION", "LEGEND", "NOTE", "FENCE",
                   "SOFTWARE", "VENDOR", "TEMP", "XREF"],
        "valve": ["VANNE", "VANNES", "VALVE", "VALVES", "VALV"],
        "equipment": ["EQT", "EQP", "EQP1", "EQUIP", "EQUIPMENT", "MATERIEL", "MECAN", "APPARATE",
                      "VESSEL", "PUMP", "TANK", "MECH", "02. EQUIPEMENT", "02. EQUIPMENT"],
        "instrumentation": ["INST", "INSTR", "INSTRUMENT", "INSTRUMENTATION", "BOUCLE", "LOOP", "ELECT",
                            "SIGNAL", "DCS", "PLC", "05. INSTRUMENT", "05. INSTRUMENTATION"],
        "piping": ["PIPE", "PIPE1", "PIPE2", "PIPING", "PROCESS", "TUYAU", "LIGNE", "P-LINE",
                   "PROC", "TUBING", "UTILITY", "PROCES", "01. TUYAUTERIE", "01. PIPING"],
        "text": ["TEXT", "TXT", "TEXTE", "ANNOT", "LABEL", "TAG", "TXT30", "06. TEXT",
                 "TEXT BOX", "ATTRIB", "ANNOTATION"],
    },
    "tolerances": {
        "cluster_gap": 10.0, "min_entities": 8, "min_size": 30.0, "tag_max": 25.0,
        "inline_equipment_radius": 25.0, "line_tag_proximity": 40.0, "valve_proximity": 15.0,
    },
    # --- geometrie (unites du dessin) : a regler selon l'echelle du plan
    "snap_tol": 8.0,              # tolerance de raccord des extremites (8.0 pour raccord franc jonctions en T)
    "text_attach_max": 150.0,     # distance max texte -> ligne / symbole
    "on_line_tol": 25.0,          # distance max vanne -> troncon
    "equip_attach_tol": 28.0,     # distance max extremite de ligne -> bbox equipement (28.0 pour buse-bride)
    "equip_cluster_gap": 5.0,     # traits d'equipement a moins de ce gap = meme equipement
    "min_line_length": 8.0,       # ignore les petits traits (8.0 pour bypass, drains, events et piquages courts)
    "bridge_tol": 60.0,           # un symbole en ligne relie deux troncons distants de <= bridge_tol
    "max_block_depth": 6,
    "split_t_junctions": True,    # couper une ligne la ou une branche s'y raccorde en son milieu
    # LibreDWG marque souvent tous les attributs comme invisibles (flags=1) : on ignore ce drapeau
    "hidden_attribs": ["INVIS_DATA", "SYSTEM"],
    "use_invisible_flag": False,
    # attributs de bloc a recombiner en un tag : [attribut type, attribut numero]
    "attrib_compose": [["INST_TYPE", "INST_NO"]],
    # --- tags (fullmatch, majuscules). Ordre d'essai : ligne, equipement, vanne, instrument
    "line_re": [
        # 20"-LP-1ACX1PN-209-N  (taille-fluide-classe-sequence-isolation)
        r'^(?P<nps>\d+(?:\.\d+)?(?:/\d+)?)\s*["\u201d]?\s*-\s*(?P<fluid>[A-Z]{1,3})\s*-\s*(?P<spec>[A-Z0-9]*[A-Z][A-Z0-9]*)\s*-\s*(?P<seq>\d{2,5})(?:\s*-\s*(?P<insul>[A-Z]))?$',
        # 6"-P-101-CS  (taille-fluide-sequence-classe[-isolation])
        r'^(?P<nps>\d+(?:\.\d+)?(?:-\d+/\d+)?)\s*["\u201d]?\s*-\s*(?P<fluid>[A-Z]{1,3})\s*-\s*(?P<seq>\d{2,5})\s*-\s*(?P<spec>[A-Z0-9]+)(?:\s*-\s*(?P<insul>[A-Z0-9]{1,3}))?$',
    ],
    "equip_re": r"^(?:(?P<area>\d{2,4})[_-])?(?P<pre>PP|CP|TK|HE|AC|FLA|FL|ST|SK|PKG|GL|GR|PL|PR|TUR|GEN|MOT|VS|COL|EX|SEP|FIL|STR|DR|[PKVDERCTHF])[_-]?(?P<seq>\d{2,5}[A-Z]{0,2}(?:/[A-Z])*)$",
    "valve_re": r"^(?:(?P<area>\d{2,4})[_-])?(?P<pre>[A-Z]{1,3}V|CH|NRV)[_-]?(?P<loop>\d{2,5}[A-Z]{0,2})$",
    "instr_re": r"^(?:(?P<area>\d{2,4})[_-])?(?P<var>[A-Z])(?P<fn>[A-Z]{1,3})[_-]?(?P<loop>\d{2,5}[A-Z]?)$",
    "instr_blacklist": ["PN", "DN", "NO", "NB", "NPS", "SCH", "DWG", "REV", "ANSI", "API", "ISO", "ASME", "NOTE"],
    "fluids": {"P": "Process", "G": "Gaz", "L": "Liquide", "W": "Eau", "FG": "Fuel gas",
               "FW": "Eau incendie", "IA": "Air instrument", "SW": "Eau de mer",
               "F": "Torche", "D": "Drain", "V": "Vent", "CW": "Eau de refroidissement"},
}


def load_config(config_path: Optional[str | Path] = None) -> Dict[str, Any]:
    """Charge la configuration (JSON) ou retourne une COPIE de la configuration par defaut.
    Correction : l'ancienne version mutait DEFAULT_CONFIG (copie superficielle)."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if not config_path:
        return cfg
    p = Path(config_path)
    if not p.exists():
        logger.warning("Fichier de configuration %s introuvable, utilisation du defaut", config_path)
        return cfg
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Erreur chargement config %s: %s, fallback defaut", config_path, e)
        return cfg
    for key, val in data.items():
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(val)
        else:
            cfg[key] = val
    return cfg


def _kw_match(kw: str, name: str) -> bool:
    """Mot-cle de calque. Mots courts (<=3 lettres) : jeton exact ou suivi de chiffres (TB, DIM, DCS...),
    pour eviter les faux positifs de sous-chaine ('DIM' dans un nom quelconque)."""
    kw = kw.upper()
    if len(kw) >= 4:
        return kw in name
    return any(tok == kw or (tok.startswith(kw) and tok[len(kw):].isdigit())
               for tok in re.split(r"[^A-Z0-9]+", name) if tok)


def layer_role(layer_name: str, cfg: Optional[Dict[str, Any]] = None) -> str:
    """Role d'un calque : titleblock | ignore | valve | equipment | instrumentation | piping | text | other."""
    if not layer_name:
        return "other"
    name = str(layer_name).strip().upper()
    layers_cfg = (cfg or DEFAULT_CONFIG).get("layers", DEFAULT_CONFIG["layers"])
    for role in ("titleblock", "ignore", "valve", "equipment", "instrumentation", "piping", "text"):
        if any(_kw_match(kw, name) for kw in layers_cfg.get(role, [])):
            return role
    return "other"


def _role(layer: str, cfg: dict) -> Optional[str]:
    """Role interne utilise par la construction semantique."""
    r = layer_role(layer, cfg)
    return {"piping": "process_line", "instrumentation": "instrument"}.get(
        r, r if r in ("valve", "equipment", "titleblock", "ignore") else None)


def normalize_review(review: dict) -> dict:
    """equipment_review.json (export de equipment_review.html) -> decisions exploitables.
    confirm : equipement valide (tag, bbox, type) ; merge : fusionne dans un autre candidat ;
    not_equipment : le tag n'est pas un equipement."""
    items = {x["candidate_id"]: x for x in review.get("equipment", [])}
    manual, rejected = {}, []
    for x in items.values():
        if x["decision"] == "confirm" and x.get("bbox"):
            manual[x["candidate_id"]] = {"tag": (x.get("tag") or "").strip().upper(), "bbox": x["bbox"],
                                         "type": x.get("equipment_type") or None,
                                         "note": x.get("note") or "", "aliases": []}
        elif x["decision"] == "not_equipment" and x.get("tag"):
            rejected.append(x["tag"].strip().upper())
    for x in items.values():
        if x["decision"] == "merge" and x.get("bbox") and x.get("merge_with") in manual:
            tgt = manual[x["merge_with"]]
            a, b = tgt["bbox"], x["bbox"]
            tgt["bbox"] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
            if x.get("tag") and x["tag"].strip().upper() != tgt["tag"]:
                tgt["aliases"].append(x["tag"].strip().upper())
    return {"manual": {m["tag"]: m for m in manual.values() if m["tag"]}, "rejected": sorted(set(rejected))}


# ----------------------------------------------------------------------------
# Etape 1 : raw.json v2 (capture SANS PERTE de la geometrie, en coordonnees monde)
# ----------------------------------------------------------------------------
# Chaque entite est decrite par ses parametres natifs (angles d'arc, bulge, parametres d'ellipse, points de
# controle de spline, contours de hachure...) : le dessin peut etre reconstruit a partir du JSON seul
# (voir raw_roundtrip.py). Les blocs en miroir (extrusion 0,0,-1) sont redresses en coordonnees monde.
SCHEMA_VERSION_RAW = "2.0"
_FLIPPED_Z = (0.0, 0.0, -1.0)


def _r(v) -> float:
    """Coordonnee en pleine precision (float64 exact, ecrit sans arrondi) : l'exactitude de la reconstitution
    ne doit pas dependre d'un arrondi (a 6 decimales, un arc ou une ellipse change de longueur)."""
    return float(v) + 0.0                      # +0.0 : normalise -0.0


def _rp(v) -> float:
    """Angles, parametres d'ellipse, bulge, rapport, poids : pleine precision egalement (voir _r)."""
    return float(v) + 0.0


def _xy(p) -> list[float]:
    return [_r(p[0]), _r(p[1])]


def _xyz_if_needed(p) -> list[float]:
    return [_r(p[0]), _r(p[1])] + ([_r(p[2])] if len(p) > 2 and abs(p[2]) > 1e-9 else [])


def _clean(txt: str) -> str:
    if not txt:
        return ""
    # Neutraliser les surrogates CP1252 (ex: \udcb0 pour le symbole degré)
    txt = txt.encode("utf-8", errors="replace").decode("utf-8")
    txt = txt.replace("\udcb0", "°").replace("\ufffd", "°")
    txt = txt.replace("\u201d", '"').replace("\u201c", '"').replace("\\P", " ").replace(r"\P", " ")
    # Fractions empilees MTEXT : \S1#2; -> 1/2 ou \S1^2; -> 1/2 (avec espace si colle a un mot/chiffre)
    txt = re.sub(r"\\S([^;#^]+)[#^/]([^;]+);(?=[A-Za-z0-9])", r"\1/\2 ", txt)
    txt = re.sub(r"\\S([^;#^]+)[#^/]([^;]+);", r"\1/\2", txt)
    # Fractions empilees MTEXT simples : 3#4 -> 3/4
    txt = re.sub(r"(?<=\d)#(?=\d)", "/", txt)
    # Nettoyage chirurgical des balises et codes de controle MTEXT (\H...;, \f...;, \C...;, \A...;, etc.)
    txt = re.sub(r"\\[A-Za-z][^;]*;", "", txt)
    txt = re.sub(r"[{}]", "", txt)
    txt = txt.replace(r'\"', '"').replace(r"\'", "'")
    return re.sub(r"\s+", " ", txt).strip()


def _is_flipped(e) -> bool:
    try:
        ex = e.dxf.get("extrusion", (0, 0, 1))
        return abs(ex[0]) < 1e-9 and abs(ex[1]) < 1e-9 and ex[2] < 0
    except Exception:
        return False


def _style(e) -> dict:
    """Style graphique ecrit seulement s'il differe de BYLAYER (le JSON reste compact)."""
    d, st = e.dxf, {}
    if d.get("color", 256) != 256:
        st["color"] = d.color
    if d.hasattr("true_color"):
        st["true_color"] = d.true_color
    if str(d.get("linetype", "BYLAYER")).upper() != "BYLAYER":
        st["linetype"] = d.linetype
    if d.get("lineweight", -1) != -1:
        st["lineweight"] = d.lineweight
    return st


def _path_bbox(e):
    """Boite englobante exacte (arcs, bulges, courbes) via les chemins ezdxf, a 0,02 pres."""
    try:
        from ezdxf import path as ez_path
        pts = list(ez_path.make_path(e).flattening(0.02))
        if pts:
            xs, ys = [p.x for p in pts], [p.y for p in pts]
            return [_r(min(xs)), _r(min(ys)), _r(max(xs)), _r(max(ys))]
    except Exception:
        pass
    try:
        ext = ez_bbox.extents([e])
        if ext.has_data:
            return [*_xy(ext.extmin), *_xy(ext.extmax)]
    except Exception:
        pass
    return None


def _hatch_paths(h) -> list[dict]:
    out = []
    for p in h.paths:
        kind = p.type.name if hasattr(p.type, "name") else str(p.type)
        item = {"flags": int(p.path_type_flags)}
        if not hasattr(p, "edges"):
            item.update(type="polyline", closed=bool(p.is_closed),
                        verts=[[_r(v[0]), _r(v[1]), _rp(v[2]) if len(v) > 2 else 0.0] for v in p.vertices])
        else:
            edges = []
            for ed in p.edges:
                n = ed.type.name if hasattr(ed.type, "name") else str(ed.type)
                if n == "LINE":
                    edges.append({"e": "line", "s": _xy(ed.start), "t": _xy(ed.end)})
                elif n == "ARC":
                    edges.append({"e": "arc", "c": _xy(ed.center), "r": _r(ed.radius), "sa": _rp(ed.start_angle),
                                  "ea": _rp(ed.end_angle), "ccw": bool(ed.ccw)})
                elif n == "ELLIPSE":
                    edges.append({"e": "ellipse", "c": _xy(ed.center), "major": [_rp(ed.major_axis[0]), _rp(ed.major_axis[1])],
                                  "ratio": _rp(ed.ratio), "sa": _rp(ed.start_angle), "ea": _rp(ed.end_angle),
                                  "ccw": bool(ed.ccw)})
                elif n == "SPLINE":
                    edges.append({"e": "spline", "deg": int(ed.degree), "periodic": bool(ed.periodic),
                                  "ctrl": [_xy(v) for v in ed.control_points], "knots": [_rp(k) for k in ed.knot_values],
                                  "weights": [_rp(w) for w in ed.weights], "fit": [_xy(v) for v in ed.fit_points]})
            item.update(type="edges", edges=edges)
        out.append(item)
    return out


# types dont la geometrie est decrite par ses parametres natifs
PARAMETRIC_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "HATCH", "SOLID", "TRACE",
                    "TEXT", "MTEXT", "INSERT", "ATTRIB", "VIEWPORT", "IMAGE"}
IGNORED_BY_DESIGN = {"ATTDEF"}      # gabarit d'attribut : la valeur reelle est portee par l'ATTRIB de l'INSERT


def _capture(e, t: str, r: dict, warns: list) -> bool:
    """Ajoute a r la geometrie de e. Retourne False si le type n'est pas decrit parametriquement."""
    d = e.dxf
    st = _style(e)
    if st:
        r["style"] = st
    if t == "LINE":
        s, en = d.start, d.end
        r["pts"] = [_xy(s), _xy(en)]
        if abs(s[2]) > 1e-9 or abs(en[2]) > 1e-9:
            r["pts3d"] = [_xyz_if_needed(s), _xyz_if_needed(en)]
    elif t == "LWPOLYLINE":
        pts = list(e.get_points("xyseb"))
        r["verts"] = [[_r(p[0]), _r(p[1]), _rp(p[4])] for p in pts]
        r["pts"] = [[v[0], v[1]] for v in r["verts"]]
        r["closed"] = bool(e.closed)
        if any(abs(p[2]) > 1e-9 or abs(p[3]) > 1e-9 for p in pts):
            r["widths"] = [[_r(p[2]), _r(p[3])] for p in pts]
        if abs(d.get("const_width", 0)) > 1e-9:
            r["const_width"] = _r(d.const_width)
        if abs(d.get("elevation", 0)) > 1e-9:
            r["elevation"] = _r(d.elevation)
        r["bbox"] = _path_bbox(e)
    elif t == "POLYLINE":
        if e.is_poly_face_mesh or e.is_polygon_mesh or e.is_3d_polyline:
            warns.append({"code": "POLYLINE_3D_OR_MESH_NOT_PARAMETRIC", "handle": r["handle"]})
            return False
        verts = [(v.dxf.location, v.dxf.get("bulge", 0.0)) for v in e.vertices]
        r["verts"] = [[_r(p[0]), _r(p[1]), _rp(b)] for p, b in verts]
        r["pts"] = [[v[0], v[1]] for v in r["verts"]]
        r["closed"] = bool(e.is_closed)
        r["bbox"] = _path_bbox(e)
    elif t == "ARC":
        r.update(pos=_xy(d.center), radius=_r(d.radius), start_angle=_rp(d.start_angle), end_angle=_rp(d.end_angle))
        r["bbox"] = _path_bbox(e)
    elif t == "CIRCLE":
        r.update(pos=_xy(d.center), radius=_r(d.radius))
        r["bbox"] = [_r(d.center[0] - d.radius), _r(d.center[1] - d.radius),
                     _r(d.center[0] + d.radius), _r(d.center[1] + d.radius)]
    elif t == "ELLIPSE":
        r.update(pos=_xy(d.center), major_axis=[_rp(c) for c in d.major_axis][:2] + ([_rp(d.major_axis[2])] if abs(d.major_axis[2]) > 1e-9 else []),
                 ratio=_rp(d.ratio), start_param=_rp(d.start_param), end_param=_rp(d.end_param))
        r["bbox"] = _path_bbox(e)
    elif t == "SPLINE":
        r.update(degree=int(d.degree), closed=bool(e.closed),
                 control_points=[_xyz_if_needed(p) for p in e.control_points],
                 knots=[_rp(k) for k in e.knots], weights=[_rp(w) for w in e.weights],
                 fit_points=[_xyz_if_needed(p) for p in e.fit_points])
        r["bbox"] = _path_bbox(e)
    elif t == "HATCH":
        r.update(pattern=d.get("pattern_name", "SOLID"), solid_fill=bool(d.get("solid_fill", 1)),
                 elevation=_r(d.get("elevation", (0, 0, 0))[2]), paths=_hatch_paths(e))
        if not r["solid_fill"]:
            r.update(pattern_scale=_rp(d.get("pattern_scale", 1.0)), pattern_angle=_rp(d.get("pattern_angle", 0.0)),
                     pattern_double=int(d.get("pattern_double", 0)))
            try:
                r["pattern_lines"] = [{"angle": _rp(l.angle), "base": _xy(l.base_point), "offset": _xy(l.offset),
                                       "dashes": [_rp(x) for x in l.dash_length_items]} for l in e.pattern.lines]
            except Exception:
                pass
        try:
            ext = ez_bbox.extents([e])
            r["bbox"] = [*_xy(ext.extmin), *_xy(ext.extmax)] if ext.has_data else None
        except Exception:
            r["bbox"] = None
    elif t in ("SOLID", "TRACE"):
        r["corners"] = [_xy(d.get(k, d.vtx0)) for k in ("vtx0", "vtx1", "vtx2", "vtx3")]
        xs, ys = [c[0] for c in r["corners"]], [c[1] for c in r["corners"]]
        r["bbox"] = [min(xs), min(ys), max(xs), max(ys)]
    elif t == "IMAGE":
        iw, ih = d.image_size[0], d.image_size[1]
        u, v = d.u_pixel, d.v_pixel     # taille d'un pixel selon u et v (vecteurs en unites dessin)
        p0 = d.insert
        corners = [p0, p0 + u * iw, p0 + u * iw + v * ih, p0 + v * ih]
        xs, ys = [c[0] for c in corners], [c[1] for c in corners]
        fn = None
        try:
            fn = e.image_def.dxf.filename if e.image_def is not None else None
        except Exception:
            fn = None
        r.update(pos=_xy(p0), u_vector=_xy(u), v_vector=_xy(v), image_size=[int(iw), int(ih)], file=fn,
                 flags=int(d.get("flags", 0)), bbox=[_r(min(xs)), _r(min(ys)), _r(max(xs)), _r(max(ys))])
    elif t == "VIEWPORT":
        r.update(pos=_xy(d.center), width=_r(d.width), height=_r(d.height), view_center=_xy(d.view_center_point),
                 view_height=_r(d.view_height), status=int(d.get("status", 0)))
        r["bbox"] = [_r(d.center[0] - d.width / 2), _r(d.center[1] - d.height / 2),
                     _r(d.center[0] + d.width / 2), _r(d.center[1] + d.height / 2)]
    else:
        return False
    return True


def _text_common(e, r: dict) -> None:
    """TEXT / ATTRIB : l'insertion est en OCS ; un bloc en miroir donne extrusion (0,0,-1) -> x change de signe."""
    d = e.dxf
    flip = _is_flipped(e)
    ins = d.insert
    r["pos"] = [_r(-ins[0] if flip else ins[0]), _r(ins[1])]
    rot = float(d.get("rotation", 0.0))
    r["rotation"] = _rp((180.0 - rot) % 360.0 if flip else rot)
    if flip:
        r["ocs_mirrored"] = True
    r.update(height=_rp(d.get("height", 0.0)), width_factor=_rp(d.get("width", 1.0)),
             oblique=_rp(d.get("oblique", 0.0)), style_name=d.get("style", "Standard"),
             halign=int(d.get("halign", 0)), valign=int(d.get("valign", 0)))
    if d.get("text_generation_flag", 0):
        r["text_generation_flag"] = int(d.text_generation_flag)       # 2 = miroir X, 4 = miroir Y
    if d.hasattr("align_point"):
        ap = d.align_point
        r["align_point"] = [_r(-ap[0] if flip else ap[0]), _r(ap[1])]


def flatten(doc, cfg: dict):
    """Parcourt model space ET paper spaces, resout recursivement les blocs (coordonnees monde).
    Retourne (entites, stats par type, avertissements). `space` = "model" ou "paper:<layout>"."""
    out: list[dict] = []
    stats: dict[str, int] = defaultdict(int)
    warnings: list[dict] = []
    per_root: dict[str, int] = defaultdict(int)
    missing: dict[tuple, int] = {}

    def new_id(root: str) -> str:
        per_root[root] += 1
        return f"{root}#{per_root[root]}"

    def walk(entities, path, root, depth, space, parent):
        for e in entities:
            t = e.dxftype()
            h = root or e.dxf.get("handle") or "V"
            stats[f"{t}@{space.split(':')[0]}"] += 1
            if t == "ATTDEF":
                continue
            try:
                _upright.upright(e)                 # redresse les entites en miroir (extrusion 0,0,-1)
            except Exception:
                pass
            r = {"id": new_id(h), "handle": h, "type": t, "layer": e.dxf.get("layer", "0"),
                 "block_path": list(path), "space": space}
            if parent:
                r["parent"] = parent
            if t in ("TEXT", "MTEXT", "ATTRIB"):
                st = _style(e)
                if st:
                    r["style"] = st
                if t == "MTEXT":
                    d = e.dxf
                    r["text"] = _clean(e.plain_text())
                    r["text_raw"] = e.text
                    r.update(pos=_xy(d.insert), char_height=_rp(d.get("char_height", 0.0)),
                             rotation=_rp(d.get("rotation", 0.0)), width=_rp(d.get("width", 0.0)),
                             attachment_point=int(d.get("attachment_point", 1)), style_name=d.get("style", "Standard"))
                    for k in ("line_spacing_factor", "defined_height", "flow_direction", "line_spacing_style"):
                        if d.hasattr(k):
                            r[k] = _rp(d.get(k)) if isinstance(d.get(k), float) else d.get(k)
                    if d.hasattr("text_direction"):
                        r["text_direction"] = [_rp(c) for c in d.text_direction][:2]
                else:
                    r["text"] = _clean(e.dxf.text)
                    r["text_raw"] = e.dxf.text
                    _text_common(e, r)
                    if t == "ATTRIB":
                        r["tag"] = e.dxf.tag
                        r["attrib_flags"] = int(e.dxf.get("flags", 0))
                out.append(r)
                continue
            if t == "INSERT":
                d = e.dxf
                r.update(name=d.name, block=d.name, pos=_xy(d.insert),
                         scale=[_r(d.get("xscale", 1.0)), _r(d.get("yscale", 1.0)), _r(d.get("zscale", 1.0))],
                         rotation=_r(d.get("rotation", 0.0)))
                if d.get("column_count", 1) > 1 or d.get("row_count", 1) > 1:
                    r["array"] = {"cols": int(d.column_count), "rows": int(d.row_count),
                                  "col_spacing": _r(d.column_spacing), "row_spacing": _r(d.row_spacing)}
                st = _style(e)
                if st:
                    r["style"] = st
                out.append(r)
                for a in e.attribs:
                    if a.dxf.tag in cfg["hidden_attribs"]:
                        continue
                    if cfg["use_invisible_flag"] and a.dxf.get("flags", 0) & 1:
                        continue
                    txt = _clean(a.dxf.text)
                    if not txt:
                        continue
                    ar = {"id": new_id(h), "handle": h, "type": "ATTRIB", "layer": a.dxf.get("layer", r["layer"]),
                          "block_path": list(path) + [d.name], "space": space, "parent": r["id"],
                          "insert_id": r["id"], "parent_insert": h, "tag": a.dxf.tag, "text": txt,
                          "text_raw": a.dxf.text, "attrib_flags": int(a.dxf.get("flags", 0))}
                    _text_common(a, ar)
                    st2 = _style(a)
                    if st2:
                        ar["style"] = st2
                    out.append(ar)
                if depth >= cfg["max_block_depth"]:
                    warnings.append({"code": "BLOCK_DEPTH_LIMIT", "handle": h, "name": d.name})
                    continue
                try:
                    walk(e.virtual_entities(), path + [d.name], h, depth + 1, space, r["id"])
                except Exception as exc:        # bloc corrompu / xref non resolue / definition absente
                    key = (d.name, space, str(exc)[:80])
                    missing[key] = missing.get(key, 0) + 1
                continue
            try:
                ok = _capture(e, t, r, warnings)
            except Exception as exc:
                warnings.append({"code": "ENTITY_CAPTURE_FAILED", "type": t, "handle": h, "error": str(exc)[:80]})
                ok = False
            if ok and not r.get("bbox") and r.get("pts"):       # LINE (et repli des polylignes) : boite des sommets
                xs, ys = [q[0] for q in r["pts"]], [q[1] for q in r["pts"]]
                r["bbox"] = [min(xs), min(ys), max(xs), max(ys)]
            if not ok:
                r["unparsed"] = True
                try:
                    ext = ez_bbox.extents([e])
                    r["bbox"] = [*_xy(ext.extmin), *_xy(ext.extmax)] if ext.has_data else None
                except Exception:
                    r["bbox"] = None
            out.append(r)

    walk(doc.modelspace(), [], None, 0, "model", None)
    for lay in doc.layouts:
        if lay.name != "Model":
            walk(lay, [], None, 0, f"paper:{lay.name}", None)

    for (name, space, err), n in sorted(missing.items()):
        warnings.append({"code": "BLOCK_DEFINITION_MISSING", "name": name, "space": space, "count": n, "error": err,
                         "hint": "INSERT dont la definition de bloc est absente du DXF : son contenu n'est pas recuperable"})
    proxies = sum(n for k, n in stats.items() if k.startswith("ACAD_PROXY_ENTITY@"))
    if proxies:
        warnings.append({"code": "PROXY_OBJECTS", "count": proxies,
                         "hint": "objets proxy (ex. Plant 3D) non lus par ezdxf -> repli vision"})
    return out, dict(stats), warnings


def document_meta(doc) -> dict:
    """Tables du document : calques, blocs, styles de texte, en-tete (unites, etendue), mises en page."""
    h = doc.header

    def hv(k, default=None):
        try:
            v = h.get(k, default)
            return [_r(c) for c in v] if isinstance(v, (tuple, list)) else v
        except Exception:
            return default

    layers = [{"name": l.dxf.name, "color": l.dxf.get("color", 7), "linetype": l.dxf.get("linetype", "Continuous"),
               "lineweight": l.dxf.get("lineweight", -3), "on": bool(l.is_on()), "frozen": bool(l.is_frozen()),
               "locked": bool(l.is_locked()), "plot": bool(l.dxf.get("plot", 1))} for l in doc.layers]
    blocks = []
    for b in doc.blocks:
        if b.name.startswith("*"):
            continue
        blocks.append({"name": b.name, "base_point": _xy(b.block.dxf.base_point), "entities": len(b),
                       "has_attdef": any(e.dxftype() == "ATTDEF" for e in b)})
    return {
        "dxf_version": doc.dxfversion,
        "header": {"insunits": hv("$INSUNITS"), "measurement": hv("$MEASUREMENT"), "ltscale": hv("$LTSCALE"),
                   "extmin": hv("$EXTMIN"), "extmax": hv("$EXTMAX")},
        "layers": layers, "blocks": blocks,
        "text_styles": [{"name": s.dxf.name, "font": s.dxf.get("font", ""), "bigfont": s.dxf.get("bigfont", ""),
                         "height": s.dxf.get("height", 0.0), "width": s.dxf.get("width", 1.0),
                         "oblique": s.dxf.get("oblique", 0.0), "flags": s.dxf.get("flags", 0),
                         "generation_flags": s.dxf.get("generation_flags", 0)} for s in doc.styles],
        "layouts": [{"name": l.name, "entities": len(l)} for l in doc.layouts],
    }


def coverage_report(stats: dict, raw: list[dict]) -> dict:
    """Pour chaque type : combien d'entites dans le DXF, combien reprises, et sous quelle forme.
    `lossless` est vrai seulement si aucune entite n'est perdue ni laissee sans parametres."""
    in_dxf: dict[str, int] = defaultdict(int)
    for k, n in stats.items():
        in_dxf[k.split("@")[0]] += n
    captured: dict[str, int] = defaultdict(int)
    unparsed: dict[str, int] = defaultdict(int)
    for r in raw:
        captured[r["type"]] += 1
        if r.get("unparsed"):
            unparsed[r["type"]] += 1
    rows, lossless = {}, True
    for t in sorted(in_dxf):
        if t in IGNORED_BY_DESIGN:
            mode = "ignored_by_design"
        elif t in PARAMETRIC_TYPES and not unparsed.get(t):
            mode = "parametric"
        else:
            mode = "unparsed"
        rows[t] = {"in_dxf": in_dxf[t], "captured": captured.get(t, 0), "mode": mode}
        if mode == "unparsed" or (mode == "parametric" and t != "ATTRIB" and captured.get(t, 0) != in_dxf[t]):
            lossless = False
    return {"types": rows, "lossless": lossless,
            "unparsed_types": sorted(t for t, v in rows.items() if v["mode"] == "unparsed")}


# ----------------------------------------------------------------------------
# Etape 2 : classification des tags
# ----------------------------------------------------------------------------
def classify(text: str, cfg: dict) -> dict | None:
    t = _clean(text).upper()
    if not t or len(t) > 40:
        return None
    for kind, key in (("line", "line_re"), ("equipment", "equip_re"),
                      ("valve", "valve_re"), ("instrument", "instr_re")):
        pats = cfg[key] if isinstance(cfg[key], list) else [cfg[key]]
        for pat in pats:
            m = re.match(pat, t)
            if m:
                parts = {k: v for k, v in m.groupdict().items() if v}
                if kind == "instrument":
                    parts["pre"] = parts.get("var", "") + parts.get("fn", "")
                    if parts["pre"] in cfg.get("instr_blacklist", []):
                        continue
                return {"kind": kind, "tag": t, "parts": parts}
    return None


# ----------------------------------------------------------------------------
# Etape 3 : geometrie (snapping + composantes connexes)
# ----------------------------------------------------------------------------
def seg_dist(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


class Snap:
    def __init__(self, tol):
        self.tol, self.cells, self.pts = tol, defaultdict(list), []

    def node(self, p) -> int:
        cx, cy = int(p[0] // self.tol), int(p[1] // self.tol)
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for n in self.cells.get((cx + i, cy + j), ()):
                    if math.hypot(self.pts[n][0] - p[0], self.pts[n][1] - p[1]) <= self.tol:
                        return n
        self.pts.append(p)
        self.cells[(cx, cy)].append(len(self.pts) - 1)
        return len(self.pts) - 1


class UF:
    def __init__(self):
        self.p: dict[int, int] = {}

    def f(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def u(self, a, b):
        self.p[self.f(a)] = self.f(b)


def split_t_junctions(segs: list, tol: float) -> list:
    """Coupe un troncon la ou l'extremite d'un autre troncon vient s'y poser en son milieu (jonction en T
    dessinee sans noeud). Sans cela, la branche et la ligne principale restent deux traits non raccordes."""
    splits: dict[int, list] = defaultdict(list)
    for i, si in enumerate(segs):
        for p in (si["a"], si["b"]):
            for j, sj in enumerate(segs):
                if i == j:
                    continue
                a, b = sj["a"], sj["b"]
                if (p[0] < min(a[0], b[0]) - tol or p[0] > max(a[0], b[0]) + tol
                        or p[1] < min(a[1], b[1]) - tol or p[1] > max(a[1], b[1]) + tol):
                    continue
                if math.dist(p, a) <= tol or math.dist(p, b) <= tol:
                    continue                      # deja une extremite : le snapping s'en charge
                if seg_dist(p, a, b) <= tol:
                    splits[j].append(tuple(p))
    out = []
    for j, sg in enumerate(segs):
        if j not in splits:
            out.append(sg)
            continue
        a, b = sg["a"], sg["b"]
        L2 = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 or 1.0
        ps = sorted(set(splits[j]), key=lambda q: ((q[0] - a[0]) * (b[0] - a[0]) + (q[1] - a[1]) * (b[1] - a[1])) / L2)
        chain = [a] + [list(q) for q in ps] + [b]
        for u, v in zip(chain, chain[1:]):
            out.append({**sg, "a": u, "b": v})
    return out


def _length(pl) -> float:
    return sum(math.dist(pl[i], pl[i + 1]) for i in range(len(pl) - 1))


VALVE_KEYWORDS = (
    "VALVE", "VANNE", "CLAPET", "CHECK", "GATE", "GLOBE", "BALL",
    "SOUPAPE", "PSV", "ROBINET", "DRAIN", "VENT", "NEEDLE", "BUTTERFLY",
    "PAPILLON", "MEMBRANE", "DIAPHRAGM", "SAFETY", "RELIEF"
)

REDUCER_KEYWORDS = ("REDUC", "RED_CONC", "RED_ECC", "REDUCTION", "REDUCTEUR")


def normalize_valve_tag(name: str) -> str:
    """Normalise le nom de bloc ou symbole d'une vanne en étiquette standardisée."""
    n = (name or "").strip()
    nl = n.lower()
    if any(k in nl for k in ("clapet", "check")):
        return "CHECK_VALVE"
    if any(k in nl for k in ("passage direct", "gate")):
        return "GATE_VALVE"
    if any(k in nl for k in ("boisseau", "ball")):
        return "BALL_VALVE"
    if any(k in nl for k in ("soupape", "globe")):
        return "GLOBE_VALVE"
    if any(k in nl for k in ("relief", "psv", "safety", "securite")):
        return "PSV"
    if "vent" in nl:
        return "VENT"
    if "drain" in nl:
        return "DRAIN"
    if "needle" in nl:
        return "NEEDLE_VALVE"
    if any(k in nl for k in ("papillon", "butterfly")):
        return "BUTTERFLY_VALVE"
    clean = re.sub(r"[^A-Za-z0-9]+", "_", n).strip("_").upper()
    return clean or "VALVE"


def split_runs_at_reductions(comps: dict[int, list[dict]], ltags: list[dict],
                             inserts: list[dict], cfg: dict) -> dict[int, list[dict]]:
    """Sépare les runs de tuyauterie lorsqu'un symbole de réduction est présent
    ou lorsque deux tags de diamètre différent sont détectés sur le même run."""
    reducers = [ins for ins in inserts if any(kw in (ins.get("name") or ins.get("block") or "").upper() for kw in REDUCER_KEYWORDS)]
    next_k = max(comps.keys(), default=0) + 1
    new_comps = {}

    for k, ss in comps.items():
        if not ss:
            continue
        near_reds = [r for r in reducers if min(seg_dist(r["pos"], sg["a"], sg["b"]) for sg in ss) <= cfg["on_line_tol"]]
        near_tags = [t for t in ltags if min(seg_dist(t["pos"], sg["a"], sg["b"]) for sg in ss) <= cfg["text_attach_max"]]
        distinct_tags = {t["tag"] for t in near_tags}
        distinct_nps = {t["parts"].get("nps") for t in near_tags if t.get("parts") and t["parts"].get("nps")}

        needs_split = (len(near_reds) > 0) or (len(distinct_nps) >= 2) or (len(distinct_tags) >= 2 and len(near_tags) >= 2)
        if not needs_split:
            new_comps[k] = ss
            continue

        if len(ss) == 1:
            sg = ss[0]
            a, b = sg["a"], sg["b"]
            if near_reds:
                split_pt = near_reds[0]["pos"]
            elif len(near_tags) >= 2:
                t1, t2 = near_tags[0], near_tags[1]
                mid_x = (t1["pos"][0] + t2["pos"][0]) / 2.0
                mid_y = (t1["pos"][1] + t2["pos"][1]) / 2.0
                split_pt = [mid_x, mid_y]
            else:
                split_pt = [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0]

            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy or 1.0
            t_proj = max(0.05, min(0.95, ((split_pt[0] - a[0]) * dx + (split_pt[1] - a[1]) * dy) / L2))
            proj = [round(a[0] + t_proj * dx, 3), round(a[1] + t_proj * dy, 3)]
            new_comps[k] = [{**sg, "a": a, "b": proj}]
            new_comps[next_k] = [{**sg, "a": proj, "b": b}]
            next_k += 1
        else:
            if near_reds:
                r_pos = near_reds[0]["pos"]
                best_i = min(range(len(ss)), key=lambda i: seg_dist(r_pos, ss[i]["a"], ss[i]["b"]))
                split_idx = max(1, min(len(ss) - 1, best_i + 1))
                part1 = ss[:split_idx]
                part2 = ss[split_idx:]
            elif len(near_tags) >= 2:
                t1, t2 = near_tags[0], near_tags[1]
                part1 = [sg for sg in ss if seg_dist(t1["pos"], sg["a"], sg["b"]) <= seg_dist(t2["pos"], sg["a"], sg["b"])]
                part2 = [sg for sg in ss if sg not in part1]
                if not part1 or not part2:
                    mid = len(ss) // 2
                    part1, part2 = ss[:mid], ss[mid:]
            else:
                mid = len(ss) // 2
                part1, part2 = ss[:mid], ss[mid:]

            new_comps[k] = part1
            new_comps[next_k] = part2
            next_k += 1

    return new_comps


# ----------------------------------------------------------------------------
# Etape 4 : semantic.json
# ----------------------------------------------------------------------------
def build_semantic(raw: list[dict], cfg: dict, warnings: list[dict]) -> dict:
    warnings = list(warnings)
    role = {r["id"]: _role(r["layer"], cfg) for r in raw}
    by_id = {r["id"]: r for r in raw}
    inserts = [r for r in raw if r["type"] == "INSERT" and role[r["id"]] not in ("ignore", "titleblock")]

    # --- attributs recombines (ex. INST_TYPE + INST_NO -> "FIC-210")
    composed = []
    for ta, na in cfg.get("attrib_compose", []):
        grp = defaultdict(list)
        for r in raw:
            if r["type"] == "ATTRIB" and r.get("tag") in (ta, na):
                grp[r["insert_id"]].append(r)
        for iid, rs in grp.items():
            typ = next((x["text"] for x in rs if x["tag"] == ta), None)
            num = next((x["text"] for x in rs if x["tag"] == na
                        and re.fullmatch(r"\d{2,5}[A-Z]?", x["text"])), None)
            if typ and num and re.fullmatch(r"[A-Z]{2,4}", typ):
                ins = by_id[iid]
                composed.append({"id": f"{iid}:c", "handle": ins["handle"], "type": "ATTRIB",
                                 "layer": ins["layer"], "block_path": ins["block_path"],
                                 "text": f"{typ}-{num}", "pos": ins["pos"], "insert_id": iid})
                role[f"{iid}:c"] = role[iid]

    # --- tags classes (TEXT / MTEXT / ATTRIB), dedoublonnes
    tags, seen = [], set()
    for r in raw + composed:
        if r["type"] not in ("TEXT", "MTEXT", "ATTRIB") or role[r["id"]] in ("ignore", "titleblock"):
            continue
        # Filtrer les textes de marge haute (cartouche/en-tête, ex: Y >= 30180) ou calques de renvoi / annotation
        pos_y = r.get("pos", [0.0, 0.0])[1] if r.get("pos") else 0.0
        r_layer = (r.get("layer") or "").upper()
        if r_layer.startswith("ANN-") or pos_y >= 30180.0:
            continue
        c = classify(r.get("text", ""), cfg)
        if not c:
            continue
        key = (c["tag"], round(r["pos"][0]), round(r["pos"][1]))
        if key in seen:
            continue
        seen.add(key)
        tags.append({**c, "src": r["id"], "handle": r["handle"], "layer": r["layer"],
                     "pos": r["pos"], "insert_id": r.get("insert_id"),
                     "block_path": r["block_path"]})

    # --- segments de process (avec élargissement multi-calques)
    ltags = [x for x in tags if x["kind"] == "line"]

    cand_segs = []
    for r in raw:
        if r["type"] in ("LINE", "LWPOLYLINE", "POLYLINE"):
            r_role = role[r["id"]]
            if r_role in ("titleblock", "ignore", "equipment"):
                continue
            is_proc = (r_role == "process_line")
            pts = r["pts"] + ([r["pts"][0]] if r.get("closed") else [])
            for a, b in zip(pts, pts[1:]):
                cand_segs.append({
                    "a": a, "b": b, "handle": r["handle"], "layer": r["layer"],
                    "is_process": is_proc, "id": r["id"]
                })

    snap_pre = Snap(cfg["snap_tol"])
    uf_pre = UF()
    for s in cand_segs:
        s["na"] = snap_pre.node(s["a"])
        s["nb"] = snap_pre.node(s["b"])
        uf_pre.u(s["na"], s["nb"])

    # Pontage initial à travers les blocs de vannes pour connecter les réseaux de tuyauterie
    for ins in inserts:
        bname = (ins.get("name") or ins.get("block") or "").upper()
        if role[ins["id"]] in ("valve", "instrument", None) or any(kw in bname for kw in VALVE_KEYWORDS):
            near_nodes = [s["na"] for s in cand_segs if math.dist(s["a"], ins["pos"]) <= cfg["bridge_tol"]] + \
                         [s["nb"] for s in cand_segs if math.dist(s["b"], ins["pos"]) <= cfg["bridge_tol"]]
            if len(near_nodes) >= 2:
                for n1 in near_nodes[1:]:
                    uf_pre.u(near_nodes[0], n1)

    tagged_roots = set()
    for s in cand_segs:
        if s["is_process"]:
            tagged_roots.add(uf_pre.f(s["na"]))
        elif ltags:
            d = min(seg_dist(t["pos"], s["a"], s["b"]) for t in ltags)
            if d <= 120.0:
                tagged_roots.add(uf_pre.f(s["na"]))

    rawsegs = [
        {"a": s["a"], "b": s["b"], "handle": s["handle"], "layer": s["layer"]}
        for s in cand_segs if uf_pre.f(s["na"]) in tagged_roots
    ]

    snap, uf, segs = Snap(cfg["snap_tol"]), UF(), []
    if cfg.get("split_t_junctions", True):
        rawsegs = split_t_junctions(rawsegs, cfg["snap_tol"])
    for sg in rawsegs:
        na, nb = snap.node(sg["a"]), snap.node(sg["b"])
        uf.u(na, nb)
        segs.append({**sg, "na": na, "nb": nb})
    # un "run" = chaine de troncons joints uniquement par des noeuds de degre 2
    # (une jonction en T, un changement de numero de ligne coupe le run)
    deg: dict[int, list[int]] = defaultdict(list)
    for i, sg in enumerate(segs):
        deg[sg["na"]].append(i)
        deg[sg["nb"]].append(i)
    uf = UF()
    for i in range(len(segs)):
        uf.f(i)
    for n, ids in deg.items():
        if len(ids) == 2:
            uf.u(ids[0], ids[1])
    # pontage des symboles en ligne : exactement 2 extremites libres a proximite du symbole
    for ins in inserts:
        bname = (ins.get("name") or ins.get("block") or "").upper()
        if role[ins["id"]] not in ("valve", "instrument", None) and not any(kw in bname for kw in VALVE_KEYWORDS):
            continue
        near = [n for n, ids in deg.items() if len(ids) == 1
                and math.dist(snap.pts[n], ins["pos"]) <= cfg["bridge_tol"]]
        if len(near) == 2 and uf.f(deg[near[0]][0]) != uf.f(deg[near[1]][0]):
            uf.u(deg[near[0]][0], deg[near[1]][0])
    comps: dict[int, list[dict]] = defaultdict(list)
    for i, sg in enumerate(segs):
        comps[uf.f(i)].append(sg)
    comps = {k: v for k, v in comps.items()
             if sum(math.dist(s["a"], s["b"]) for s in v) >= cfg["min_line_length"]}
    # Découpage des runs aux réductions de diamètre ou symboles de réduction
    comps = split_runs_at_reductions(comps, ltags, inserts, cfg)

    def nearest_comp(p, tol):
        best = (None, tol + 1)
        for k, ss in comps.items():
            d = min(seg_dist(p, s["a"], s["b"]) for s in ss)
            if d < best[1]:
                best = (k, d)
        return best if best[1] <= tol else (None, None)

    # ids deterministes ET uniques : une meme polyligne peut former plusieurs runs (coupee a une jonction),
    # donc "L-<plus petit handle>" seul provoquait des collisions et l'ecrasement de lignes
    line_id, taken = {}, defaultdict(int)
    for k in sorted(comps, key=lambda k: (min(sg["handle"] for sg in comps[k]),
                                          min(min(sg["a"], sg["b"]) for sg in comps[k]))):
        base = f"L-{min(sg['handle'] for sg in comps[k])}"
        taken[base] += 1
        line_id[k] = base if taken[base] == 1 else f"{base}-{taken[base]}"

    # --- lignes
    lines = {}
    for k, ss in comps.items():
        xs = [c for s in ss for c in (s["a"][0], s["b"][0])]
        ys = [c for s in ss for c in (s["a"][1], s["b"][1])]
        lines[line_id[k]] = {
            "id": line_id[k], "tag_raw": None, "nps": None, "fluid": None, "seq": None,
            "spec": None, "segments": [[s["a"], s["b"]] for s in ss],
            "bbox": [min(xs), min(ys), max(xs), max(ys)],
            "handles": sorted({s["handle"] for s in ss}), "layer": ss[0]["layer"],
            "connects": [], "confidence": 0.0}

    # --- tags de ligne -> runs : appariement glouton un-a-un (plus petite distance d'abord)
    ltags = [x for x in tags if x["kind"] == "line"]
    cand = []
    for ti, t in enumerate(ltags):
        for k, ss in comps.items():
            d = min(seg_dist(t["pos"], sg["a"], sg["b"]) for sg in ss)
            if d <= cfg["text_attach_max"]:
                cand.append((d, ti, k))
    cand.sort()
    done_t, unattached = set(), []
    for d, ti, k in cand:
        t, L = ltags[ti], lines[line_id[k]]
        if ti in done_t or L["tag_raw"]:
            continue
        done_t.add(ti)
        L.update(tag_raw=t["tag"], source_handle=t["handle"],
                 confidence=round(1 - d / cfg["text_attach_max"], 2),
                 **{p: t["parts"].get(p) for p in ("nps", "fluid", "seq", "spec")})
    # Tags restants : un numero de ligne repete sur un run deja numerote avec le MEME texte est un simple doublon
    # d'etiquette (frequent sur les P&ID) ; seul un texte DIFFERENT a cote d'un run deja numerote est un conflit.
    unattached = []
    for ti, t in enumerate(ltags):
        if ti in done_t:
            continue
        near = [(d, k) for d, tj, k in cand if tj == ti]
        if near:
            d, k = min(near)
            L = lines[line_id[k]]
            if L["tag_raw"] == t["tag"]:
                continue
            warnings.append({"code": "LINE_TAG_CONFLICT", "handle": t["handle"], "text": t["tag"],
                             "nearest_line": L["id"], "line_tag": L["tag_raw"]})
            continue
        unattached.append(t)
    for t in unattached:
        warnings.append({"code": "TEXT_UNATTACHED", "handle": t["handle"], "text": t["tag"]})
    for L in lines.values():
        if not L["tag_raw"]:
            warnings.append({"code": "LINE_NO_TAG", "line_id": L["id"]})

    # --- equipements dessines en geometrie libre (calques equipment) : clusters de bbox
    geo = [r["bbox"] for r in raw if role[r["id"]] == "equipment" and r.get("bbox")
           and r["type"] not in ("TEXT", "MTEXT", "ATTRIB")]
    gap, cl = cfg["equip_cluster_gap"], []          # cl : [[bbox, ...], ...] fusionnes
    for bb in geo:
        cur = list(bb)
        rest = []
        for c in cl:
            if not (cur[2] + gap < c[0] or c[2] + gap < cur[0] or cur[3] + gap < c[1] or c[3] + gap < cur[1]):
                cur = [min(cur[0], c[0]), min(cur[1], c[1]), max(cur[2], c[2]), max(cur[3], c[3])]
            else:
                rest.append(c)
        cl = rest + [cur]
    # une seconde passe fusionne les clusters devenus voisins
    changed = True
    while changed:
        changed = False
        for i in range(len(cl)):
            for j in range(i + 1, len(cl)):
                a_, b_ = cl[i], cl[j]
                if not (a_[2] + gap < b_[0] or b_[2] + gap < a_[0] or a_[3] + gap < b_[1] or b_[3] + gap < a_[1]):
                    cl[i] = [min(a_[0], b_[0]), min(a_[1], b_[1]), max(a_[2], b_[2]), max(a_[3], b_[3])]
                    del cl[j]
                    changed = True
                    break
            if changed:
                break
    cl = [c for c in cl if max(c[2] - c[0], c[3] - c[1]) >= cfg["min_line_length"]]

    def bb_dist(p, bb):
        dx = max(bb[0] - p[0], 0, p[0] - bb[2])
        dy = max(bb[1] - p[1], 0, p[1] - bb[3])
        return math.hypot(dx, dy)

    # --- elements (equipements / vannes / instruments)
    elements, used, manual_used = [], defaultdict(int), set()
    used_insert_ids = set()
    for t in (x for x in tags if x["kind"] != "line"):
        ins = by_id.get(t["insert_id"]) if t["insert_id"] else None
        conf, source = 1.0, "attrib"
        if ins is None and inserts:
            cand = min(inserts, key=lambda i: math.dist(i["pos"], t["pos"]))
            if math.dist(cand["pos"], t["pos"]) <= cfg["text_attach_max"]:
                ins, conf, source = cand, 0.7, "proximity"
        if ins is not None:
            used_insert_ids.add(ins["id"])
        if ins is None:
            conf, source = 0.4, "text_only"
        pos = ins["pos"] if ins else t["pos"]
        ebbox = None
        if t["kind"] == "equipment" and cl:
            bi = min(range(len(cl)), key=lambda i: bb_dist(t["pos"], cl[i]))
            if bb_dist(t["pos"], cl[bi]) <= cfg["text_attach_max"]:
                ebbox = cl[bi]
                pos = [round((ebbox[0] + ebbox[2]) / 2, 3), round((ebbox[1] + ebbox[3]) / 2, 3)]
                conf, source = 0.9, "equipment_geometry"
        eq_type, review_status = None, "ok"
        rv = cfg.get("_review") or {"manual": {}, "rejected": []}
        if t["kind"] == "equipment":
            if t["tag"] in rv["rejected"]:
                continue
            man = rv["manual"].get(t["tag"])
            if man:
                ebbox, eq_type, review_status = man["bbox"], man["type"], "human_confirmed"
                pos = [round((ebbox[0] + ebbox[2]) / 2, 3), round((ebbox[1] + ebbox[3]) / 2, 3)]
                conf, source = 1.0, "human_confirmed"
                manual_used.add(t["tag"])
            elif source != "attrib":      # dessine a la main / sans bloc : a faire confirmer
                review_status = "to_confirm"
        used[t["handle"]] += 1
        el = {"id": f"E-{t['handle']}" + (f"-{used[t['handle']]}" if used[t["handle"]] > 1 else ""),
              "handle": t["handle"], "kind": t["kind"], "tag": t["tag"], "layer": t["layer"],
              "block_path": t["block_path"], "block": ins["name"] if ins else None,
              "position": pos, "bbox": ebbox, "parts": t["parts"], "on_line": None, "connected_lines": [],
              "confidence": conf, "link_source": source,
              "equipment_type": eq_type, "review_status": review_status,
              "has_text_tag": True}
        if t["kind"] == "equipment":
            for k in comps:
                if ebbox:   # distance des extremites libres du run a la bbox de l'equipement
                    ends = [pt for sg in comps[k] for pt in (sg["a"], sg["b"])]
                    d = min(bb_dist(pt, ebbox) for pt in ends)
                else:
                    d = min(seg_dist(pos, s["a"], s["b"]) for s in comps[k])
                if d <= cfg["equip_attach_tol"]:
                    el["connected_lines"].append(line_id[k])
            if not el["connected_lines"]:
                warnings.append({"code": "EQUIPMENT_NOT_CONNECTED", "tag": t["tag"]})
        else:
            k, d = nearest_comp(pos, cfg["on_line_tol"])
            if k is not None:
                el["on_line"] = line_id[k]
                el["connected_lines"] = [line_id[k]]
        for lid in el["connected_lines"]:
            lines[lid]["connects"].append(el["id"])
        if el["bbox"] is None:
            el["bbox"] = [round(pos[0] - 6, 3), round(pos[1] - 6, 3), round(pos[0] + 6, 3), round(pos[1] + 6, 3)]
        elements.append(el)

    # --- Vannes blocs sans tag texte (détection et extraction)
    for ins in inserts:
        if ins["id"] in used_insert_ids:
            continue
        bname = (ins.get("name") or ins.get("block") or "").upper()
        is_valve = (role[ins["id"]] == "valve") or any(kw in bname for kw in VALVE_KEYWORDS)
        if not is_valve:
            continue
        used_insert_ids.add(ins["id"])
        vtag = normalize_valve_tag(ins.get("name") or ins.get("block") or "VALVE")
        used[ins["handle"]] += 1
        pos = ins["pos"]
        vel = {
            "id": f"V-{ins['handle']}" + (f"-{used[ins['handle']]}" if used[ins['handle']] > 1 else ""),
            "handle": ins["handle"], "kind": "valve", "tag": vtag, "layer": ins["layer"],
            "block_path": ins["block_path"], "block": ins.get("name"),
            "position": pos,
            "bbox": ins.get("bbox") or [round(pos[0] - 6, 3), round(pos[1] - 6, 3),
                                         round(pos[0] + 6, 3), round(pos[1] + 6, 3)],
            "parts": {"pre": "V", "loop": None},
            "on_line": None, "connected_lines": [],
            "confidence": 0.85, "link_source": "block_symbol",
            "equipment_type": None, "review_status": "ok",
            "has_text_tag": False
        }
        k, d = nearest_comp(pos, cfg["on_line_tol"])
        if k is not None:
            vel["on_line"] = line_id[k]
            vel["connected_lines"] = [line_id[k]]
            lines[line_id[k]]["connects"].append(vel["id"])
        elements.append(vel)
    # equipements saisis par l'humain dont le tag n'est pas (ou plus) un texte du plan
    for tag, man in (cfg.get("_review") or {"manual": {}})["manual"].items():
        if tag in manual_used:
            continue
        bb = man["bbox"]
        pos = [round((bb[0] + bb[2]) / 2, 3), round((bb[1] + bb[3]) / 2, 3)]
        el = {"id": f"E-MAN-{tag}", "handle": None, "kind": "equipment", "tag": tag, "layer": None,
              "block_path": [], "block": None, "position": pos, "bbox": bb, "parts": {},
              "on_line": None, "connected_lines": [], "confidence": 1.0,
              "link_source": "human_confirmed", "equipment_type": man["type"],
              "review_status": "human_confirmed"}
        for k in comps:
            ends = [pt for sg in comps[k] for pt in (sg["a"], sg["b"])]
            if min(bb_dist(pt, bb) for pt in ends) <= cfg["equip_attach_tol"]:
                el["connected_lines"].append(line_id[k])
                lines[line_id[k]]["connects"].append(el["id"])
        if not el["connected_lines"]:
            warnings.append({"code": "EQUIPMENT_NOT_CONNECTED", "tag": tag})
        elements.append(el)
    pending = sorted(e["tag"] for e in elements if e["review_status"] == "to_confirm")
    if pending:
        warnings.append({"code": "EQUIPMENT_TO_CONFIRM", "count": len(pending), "tags": pending,
                         "hint": "equipements non issus d'un bloc : valider avec equipment_review.html"})
    el_by_id = {e["id"]: e for e in elements}

    # --- line_entries (format arh_pid_topology_engine.load_from_line_entries)
    line_entries = []
    for L in lines.values():
        if not L["tag_raw"]:
            continue
        mem = [el_by_id[i] for i in dict.fromkeys(L["connects"])]     # sans doublon, ordre conserve
        eq = [e for e in mem if e["kind"] == "equipment"]
        mid = [e for e in mem if e["kind"] in ("valve", "instrument") and e["on_line"] == L["id"]]
        frm = to = None
        if len(eq) >= 2:
            a, b = max(((x, y) for x in eq for y in eq if x is not y),
                       key=lambda xy: math.dist(xy[0]["position"], xy[1]["position"]))
            frm, to = a, b
            vx, vy = b["position"][0] - a["position"][0], b["position"][1] - a["position"][1]
            mid.sort(key=lambda e: (e["position"][0] - a["position"][0]) * vx
                                   + (e["position"][1] - a["position"][1]) * vy)
        else:
            mid.sort(key=lambda e: e["position"][0])
            warnings.append({"code": "LINE_EQUIPMENT_INCOMPLETE", "line_id": L["id"],
                             "tag": L["tag_raw"], "found": [e["tag"] for e in eq]})
            frm = eq[0] if eq else None
        L["path"] = [e["tag"] for e in ([frm] if frm else []) + mid + ([to] if to else [])]
        line_entries.append({
            "line_number": L["tag_raw"], "fluid": L["fluid"],
            "from_equipment": frm["tag"] if frm else None,
            "to_equipment": to["tag"] if to else None,
            "line_components": [{"tag": e["tag"]} for e in mid if e["kind"] == "valve"],
            "lock_status": {},  # a renseigner si l'etat LO/LC/CSO est lisible dans les attributs
            "line_id": L["id"], "confidence": L["confidence"]})

    # --- boucles de regulation
    loops: dict[tuple, dict] = defaultdict(lambda: {"transmitter": None, "controller": None, "final": None})
    for e in elements:
        p = e["parts"]
        if e["kind"] == "instrument":
            key, fn = (p["var"], p["loop"]), p["fn"]
            if "T" in fn and "C" not in fn:
                loops[key]["transmitter"] = e["tag"]
            elif "C" in fn:
                loops[key]["controller"] = e["tag"]
        elif e["kind"] == "valve" and p.get("loop"):
            loops[(p["pre"][0], p["loop"])]["final"] = e["tag"]
    loop_list = []
    for (var, num), v in sorted(loops.items()):
        if v["transmitter"] or v["controller"]:
            loop_list.append({"loop": f"{var}-{num}", **v,
                              "complete": all(v.values())})
            if v["controller"] and not (v["transmitter"] and v["final"]):
                warnings.append({"code": "LOOP_INCOMPLETE", "loop": f"{var}-{num}",
                                 "missing": [k for k, x in v.items() if not x]})

    # --- sortie (retire les segments bruts du bloc lines si trop gros ? non : utiles au rendu)
    return {"elements": elements, "lines": list(lines.values()), "loops": loop_list,
            "line_entries": line_entries, "warnings": warnings}


# ----------------------------------------------------------------------------
# Etape 5 : digest compact pour ARKAN / LLM
# ----------------------------------------------------------------------------
def build_digest(sem: dict, sheet: str) -> dict:
    return {
        "sheet": sheet,
        "lines": [{"id": L["id"], "tag": L["tag_raw"], "path": L.get("path", [])}
                  for L in sem["lines"] if L["tag_raw"]],
        "loops": sem["loops"],
        "warnings": [" ".join(f"{k}={v}" for k, v in w.items()) for w in sem["warnings"]],
    }



# ----------------------------------------------------------------------------
# Cartouche et notes (paper space)
# ----------------------------------------------------------------------------
TITLEBLOCK_FIELDS = {
    "drawing_number": ["NUMDESSIN", "DRAWING_NO", "DWG_NO", "DRAWING NUMBER", "NUMERO_PLAN", "N_PLAN", "DOC_NO"],
    "revision": ["NUMREV", "REV", "REVISION", "REV_NO"],
    "contract": ["NUMCONTRAT", "CONTRACT", "PROJECT_NO", "NUM_PROJET"],
    "discipline": ["DISCIPLINE"],
    "title": ["TITRE", "TITLE", "DESIGNATION", "DWG_TITLE"],
}
_REV_RE = re.compile(r"^(\d+)\.(REV\.DATE|EMIS\.BUTE|REV\.DESS\.PAR|REV\.VERIF\.PAR|REV\.APP\.PAR)\.?$", re.I)
_REV_LABEL_RE = re.compile(r"^(\d+)(?:ERE|EME|E|ER)\.REV$", re.I)
_REV_KEYS = {"REV.DATE": "date", "EMIS.BUTE": "purpose", "REV.DESS.PAR": "drawn_by",
             "REV.VERIF.PAR": "checked_by", "REV.APP.PAR": "approved_by"}


def extract_titleblock(raw: list, cfg: dict, stem: str) -> dict:
    """Cartouche lu dans les attributs du bloc de cartouche (paper space), jamais invente.
    A defaut de champ lisible, le numero de plan est le nom du fichier (source indiquee)."""
    groups: dict[str, list] = defaultdict(list)
    for r in raw:
        if r["type"] == "ATTRIB" and str(r.get("space", "")).startswith("paper:") and r.get("text"):
            groups[r.get("insert_id") or r["id"]].append(r)
    tb: dict = {}
    if groups:
        best = max(groups.values(), key=len)
        attrs = {r["tag"]: r["text"].strip() for r in best}
        tb["block"] = best[0]["block_path"][-1] if best[0]["block_path"] else None
        tb["attributes_count"] = len(attrs)
        up = {k.upper(): v for k, v in attrs.items()}
        tags = dict(cfg.get("titleblock_fields") or TITLEBLOCK_FIELDS)
        for field, names in tags.items():
            for n in names:
                if up.get(n.upper()):
                    tb[field] = up[n.upper()]
                    tb[f"{field}_source"] = f"titleblock_attribute:{n}"
                    break
        if "title" not in tb:                       # attribut dont le nom est le texte lui-meme (cartouches Sonatrach)
            cand = [v for k, v in attrs.items() if k.strip() == v.strip() and len(v) > 5 and "/" not in v[:3]]
            if cand:
                tb["title"], tb["title_source"] = cand[0], "titleblock_attribute:self_named"
        revs: dict[int, dict] = defaultdict(dict)
        for k, v in attrs.items():
            m = _REV_RE.match(k.strip())
            if m:
                revs[int(m.group(1))][_REV_KEYS[m.group(2).upper()]] = v
                continue
            m = _REV_LABEL_RE.match(k.strip())
            if m:
                revs[int(m.group(1))]["revision"] = v
        if revs:
            tb["revisions"] = [{"index": i, **revs[i]} for i in sorted(revs)]
    if not tb.get("drawing_number"):
        tb["drawing_number"], tb["drawing_number_source"] = stem, "filename"
    return tb


_PREFIX_RE = re.compile(r"PR[EÉ]FIX[EÉ]S?\s+(?:DE|PAR|AVEC|:)\s*(\d{2,4})|PREFIXED\s+(?:WITH|BY)\s+(\d{2,4})", re.I)


def find_tag_prefix(raw: list) -> Optional[dict]:
    """Note generale du type 'TOUS LES TAGS DES VANNES ET INSTRUMENTS SONT PREFIXES DE 201'."""
    for r in raw:
        if r["type"] in ("TEXT", "MTEXT") and r.get("text"):
            m = _PREFIX_RE.search(r["text"])
            if m:
                return {"value": m.group(1) or m.group(2), "source_handle": r["handle"], "text": r["text"][:160]}
    return None


detect_tag_prefix = find_tag_prefix

# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def parse_dxf_to_raw_and_semantic(
    dxf_or_dwg_path: str | Path,
    out_folder: Optional[str | Path] = None,
    cfg: Optional[Dict[str, Any]] = None,
    review: Optional[str | Path] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Parse un DXF (ou un DWG converti) et retourne (raw_data, semantic_data).
    review : equipment_review.json exporte par equipment_review.html (confirmations humaines)."""
    cfg = copy.deepcopy(cfg) if cfg else load_config(None)
    if review:
        cfg["_review"] = normalize_review(json.loads(Path(review).read_text(encoding="utf-8")))
    src_path = Path(dxf_or_dwg_path)
    if not src_path.exists():
        raise FileNotFoundError(f"Fichier P&ID introuvable : {src_path}")

    dxf_file = Path(ensure_dxf(str(src_path)))
    md5 = hashlib.md5(dxf_file.read_bytes()).hexdigest()
    try:
        doc = ezdxf.readfile(str(dxf_file))
    except Exception:
        doc, _auditor = recover.readfile(str(dxf_file))

    raw, stats, warns = flatten(doc, cfg)
    model = [r for r in raw if r.get("space", "model") == "model"]      # la semantique ne lit que le model space
    paper_n = len(raw) - len(model)
    if paper_n:
        warns.append({"code": "PAPERSPACE_READ_FOR_TITLEBLOCK_ONLY", "entities": paper_n,
                      "hint": "paper space capture dans raw.json, utilise pour le cartouche et les notes"})
    if len(model) < 5:
        warns.append({"code": "DXF_NEARLY_EMPTY", "entities": len(model)})
    units = ez_units.decode(doc.units) if doc.units else "unitless"
    cfg_hash = hashlib.md5(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:6]
    source = {"dxf_md5": md5, "ezdxf": ezdxf.__version__, "parser_version": PARSER_VERSION,
              "config_hash": cfg_hash, "file": src_path.name}
    by_type: dict[str, int] = defaultdict(int)
    for k, n in stats.items():
        by_type[k.split("@")[0]] += n
    cov = coverage_report(stats, raw)
    if not cov["lossless"]:
        warns.append({"code": "RAW_NOT_LOSSLESS", "unparsed_types": cov["unparsed_types"]})
    raw_data = {"schema_version": SCHEMA_VERSION_RAW, "source": source, "units": units,
                "document": document_meta(doc), "coverage": cov,
                "entity_stats": dict(by_type), "entity_stats_by_space": stats, "entities": raw}

    sem = build_semantic(model, cfg, warns)
    titleblock = extract_titleblock(raw, cfg, src_path.stem)
    tag_prefix = find_tag_prefix(raw)
    if tag_prefix:
        for el in sem["elements"]:
            has_area = bool(el.get("parts", {}).get("area")) or re.match(r"^\d{2,4}[-_]", el["tag"])
            el["full_tag"] = el["tag"] if (has_area or el["kind"] not in ("valve", "instrument")) \
                else f"{tag_prefix['value']}-{el['tag']}"
    semantic_data = {"schema_version": SCHEMA_VERSION, "source": source, "units": units,
                     "titleblock": titleblock, "tag_prefix": tag_prefix, **sem}

    if out_folder:
        out_p = Path(out_folder)
        out_p.mkdir(parents=True, exist_ok=True)
        digest = build_digest(sem, src_path.stem)
        for name, obj in (("raw", raw_data), ("semantic", semantic_data), ("digest", digest)):
            (out_p / f"{name}.json").write_text(
                json.dumps(obj, ensure_ascii=False, indent=1),
                encoding="utf-8",
                errors="replace",
            )
        logger.info("raw.json, semantic.json et digest.json ecrits dans %s", out_p)
    return raw_data, semantic_data


def parse_file(dxf_or_dwg_path: str | Path, out_folder: Optional[str | Path] = None) -> Dict[str, Any]:
    """Alias retournant {'raw': ..., 'semantic': ...}."""
    raw, sem = parse_dxf_to_raw_and_semantic(dxf_or_dwg_path, out_folder=out_folder)
    return {"raw": raw, "semantic": sem}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="DXF/DWG -> raw.json, semantic.json, digest.json")
    ap.add_argument("input")
    ap.add_argument("out_dir", nargs="?")
    ap.add_argument("--equipment-review", help="equipment_review.json (confirmations humaines)")
    a = ap.parse_args()
    out = a.out_dir or str(Path(a.input).parent / "pid_parsed")
    raw_res, sem_res = parse_dxf_to_raw_and_semantic(a.input, out, review=a.equipment_review)
    print(f"Extraction terminee pour {a.input}:")
    print(f"  - Entites brutes (raw.json) : {len(raw_res['entities'])}")
    print(f"  - Elements semantiques : {len(sem_res['elements'])}")
    print(f"  - Lignes de tuyauterie : {len(sem_res['lines'])}, boucles : {len(sem_res['loops'])}, "
          f"avertissements : {len(sem_res['warnings'])}")
