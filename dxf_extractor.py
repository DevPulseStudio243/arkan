"""
dxf_extractor.py
=================
Couche d'ingestion CAD pour ARKAN Piping Topology Tracer.

Rôle : lire un fichier DXF (converti depuis DWG si nécessaire) avec ezdxf,
et produire les 4 structures attendues par PipingTopologyTracer.trace_drawing() :

    segments : List[( (x,y), (x,y), meta )]   -> géométrie des tuyauteries
    labels   : List[{"text","x","y"}]          -> textes / tags de ligne
    blocks   : List[{"tag","type","x","y","width","height","ports":[...]}]  -> équipements/vannes/instruments
    opcs     : List[{"x","y","ref_code"}]      -> renvois de folio (Off-Page Connectors)

Le DXF n'ayant pas de sémantique universelle, l'extraction se pilote via
un objet ExtractionConfig (mots-clés de layers, de noms de blocs, d'attributs)
à adapter au standard de dessin du projet (ici calé sur GCB / SONATRACH).

Dépendances : ezdxf
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

import ezdxf
from ezdxf.math import Vec2


def _dist_point_to_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def estimate_geometry_tolerances(segments: List[Tuple], blocks: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Les seuils de proximité géométrique (gap de connexion, rayon de rattachement
    d'une vanne à sa ligne, rayon d'un label à son tracé...) ne peuvent PAS être
    des constantes universelles : un DXF Plant 3D en millimètres et un P&ID
    schématique en pouces n'ont pas du tout la même échelle numérique. On déduit
    donc ces seuils de la géométrie réelle du plan : la distance médiane entre
    une vanne et le segment de tuyauterie le plus proche donne l'échelle native
    du dessin, et tout le reste est dérivé proportionnellement.
    """
    valve_like = [b for b in blocks if b.get("type") in ("Valve", "Instrument", "Component")]
    nearest_dists = []
    if segments and valve_like:
        for b in valve_like:
            bx, by = b["x"], b["y"]
            d = min(_dist_point_to_segment(bx, by, s[0][0], s[0][1], s[1][0], s[1][1]) for s in segments)
            nearest_dists.append(d)

    seg_lengths = [math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]) for s in segments if s]
    seg_lengths = [l for l in seg_lengths if l > 0]

    if nearest_dists:
        nearest_dists.sort()
        unit = nearest_dists[int(len(nearest_dists) * 0.9)]  # p90 : couvre la quasi-totalité des cas réels
        unit = max(unit, 1e-6)
    elif seg_lengths:
        seg_lengths.sort()
        unit = seg_lengths[len(seg_lengths) // 10] * 0.3  # à défaut de blocs, fraction d'un petit segment
    else:
        unit = 30.0  # dernier recours : ancienne constante par défaut (hypothèse mm)

    return {
        "connection_gap_tolerance": round(max(unit * 1.5, 1e-3), 4),
        "inline_component_radius": round(max(unit * 3.0, 1e-3), 4),
        "label_proximity_radius": round(max(unit * 8.0, 1e-3), 4),
        "fallback_search_radius": round(max(unit * 5.0, 1e-3), 4),
        "estimated_unit": round(unit, 4),
        "sample_size": len(nearest_dists),
    }


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION D'EXTRACTION (à adapter par standard de dessin projet)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ExtractionConfig:
    # Layers considérés comme tuyauterie (matching insensible à la casse, substring)
    piping_layer_keywords: List[str] = field(default_factory=lambda: [
        "PIPE", "PROCESS", "TUYAU", "LIGNE", "PIPING", "P-LINE"
    ])
    # Si aucun layer ne matche, on prend TOUTES les LINE/LWPOLYLINE (mode dégradé)
    fallback_to_all_layers: bool = True

    # Mots-clés de noms de blocs -> type de composant
    valve_block_keywords: List[str] = field(default_factory=lambda: [
        "VALVE", "VANNE", "HV", "XV", "SDV", "BDV", "MOV", "CHECKVALVE", "GATEVALVE", "BALLVALVE",
        "ROBINET", "CLAPET", "BOISSEAU", "PASSAGE DIRECT", "SOUPAPE", "P_V", "P$V", "P_VBLR", "P$VGL", "VGA", "VGL"
    ])
    instrument_block_keywords: List[str] = field(default_factory=lambda: [
        "INSTRUMENT", "PT", "FT", "LT", "TT", "PI", "FI", "LI", "TI", "PIT", "FIT", "LIT", "TIT", "INST", "J_INST", "J_DCS"
    ])
    opc_block_keywords: List[str] = field(default_factory=lambda: [
        "OPC", "OFFPAGE", "CONNECTOR", "RENVOI", "CONTINUATION"
    ])
    equipment_block_keywords: List[str] = field(default_factory=lambda: [
        "PUMP", "POMPE", "COMPRESSOR", "COMPRESSEUR", "KOD", "VESSEL", "BALLON",
        "TANK", "BAC", "FLARE", "TORCHE", "LAUNCHER", "RECEIVER", "GARE"
    ])
    flow_arrow_block_keywords: List[str] = field(default_factory=lambda: [
        "FLOWARROW", "ARROW", "FLECHE"
    ])

    # Nom de l'attribut DXF (ATTRIB/ATTDEF) portant le tag de l'équipement/vanne
    tag_attribute_candidates: List[str] = field(default_factory=lambda: [
        "TAG", "TAGNO", "TAG_NO", "EQUIPMENT_TAG", "NUMTAG", "REF", "INSTR_NO", "SP_NO", "VGA", "VGL", "VALVE_SIZE"
    ])
    # Nom de l'attribut portant la référence de renvoi pour les OPC (ex: folio cible)
    opc_ref_attribute_candidates: List[str] = field(default_factory=lambda: [
        "REF", "SHEET", "FOLIO", "TARGET", "CONT_TO", "DWG_REF"
    ])

    piping_layer_exclude_keywords: List[str] = field(default_factory=lambda: [
        "REVCLOUD", "CARTOUCHE", "BORDER", "CADRE", "TITLE", "TEXT", "COTATION", "DIM", "HATCH"
    ])

    text_layer_exclude_keywords: List[str] = field(default_factory=lambda: [
        "TITLE", "CARTOUCHE", "BORDER", "CADRE"
    ])


def _entity_layer(e) -> str:
    try:
        return (e.dxf.layer or "").upper()
    except Exception:
        return ""


def _layer_matches(layer: str, keywords: List[str]) -> bool:
    return any(kw.upper() in layer for kw in keywords)


def _name_matches(name: str, keywords: List[str]) -> bool:
    name_u = (name or "").upper()
    for kw in keywords:
        kw_u = kw.upper()
        if len(kw_u) <= 3:
            # Mots-clés courts (codes instrument type PI/FI/TI...) : on exige une
            # frontière de mot pour éviter les faux positifs dans des mots français
            # (ex: "TI" ne doit pas matcher à l'intérieur de "ETIQUETTE" ou "INSTALLE").
            if re.search(rf'(?<![A-Z]){re.escape(kw_u)}(?![A-Z])', name_u):
                return True
        else:
            if kw_u in name_u:
                return True
    return False


# ═══════════════════════════════════════════════════════════════════════
# EXTRACTION DES SEGMENTS DE TUYAUTERIE
# ═══════════════════════════════════════════════════════════════════════

def extract_segments(msp, cfg: ExtractionConfig) -> List[Tuple[Tuple[float, float], Tuple[float, float], Dict[str, Any]]]:
    segments = []
    candidate_layers_used = False

    def layer_ok(e) -> bool:
        nonlocal candidate_layers_used
        layer = _entity_layer(e)
        if _layer_matches(layer, cfg.piping_layer_exclude_keywords):
            return False
        if _layer_matches(layer, cfg.piping_layer_keywords):
            candidate_layers_used = True
            return True
        return False

    # Première passe : LINE
    for e in msp.query("LINE"):
        layer = _entity_layer(e)
        if _layer_matches(layer, cfg.piping_layer_exclude_keywords):
            continue
        if not layer_ok(e) and not cfg.fallback_to_all_layers:
            continue
        p0 = (e.dxf.start.x, e.dxf.start.y)
        p1 = (e.dxf.end.x, e.dxf.end.y)
        segments.append((p0, p1, {"layer": layer, "handle": e.dxf.handle}))

    # LWPOLYLINE -> décomposée en segments successifs
    for e in msp.query("LWPOLYLINE"):
        layer = _entity_layer(e)
        if _layer_matches(layer, cfg.piping_layer_exclude_keywords):
            continue
        if not layer_ok(e) and not cfg.fallback_to_all_layers:
            continue
        pts = [Vec2(p[0], p[1]) for p in e.get_points("xy")]
        if e.closed and len(pts) > 1:
            pts.append(pts[0])
        for i in range(len(pts) - 1):
            p0 = (pts[i].x, pts[i].y)
            p1 = (pts[i + 1].x, pts[i + 1].y)
            segments.append((p0, p1, {"layer": layer, "handle": e.dxf.handle}))

    # POLYLINE (ancien format 3D/2D)
    for e in msp.query("POLYLINE"):
        layer = _entity_layer(e)
        if _layer_matches(layer, cfg.piping_layer_exclude_keywords):
            continue
        if not layer_ok(e) and not cfg.fallback_to_all_layers:
            continue
        pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
        if e.is_closed and len(pts) > 1:
            pts.append(pts[0])
        for i in range(len(pts) - 1):
            segments.append((pts[i], pts[i + 1], {"layer": layer, "handle": e.dxf.handle}))

    if not candidate_layers_used and not cfg.fallback_to_all_layers:
        raise ValueError(
            "Aucun layer de tuyauterie détecté avec les mots-clés configurés. "
            "Ajustez ExtractionConfig.piping_layer_keywords ou activez fallback_to_all_layers."
        )

    return segments


# ═══════════════════════════════════════════════════════════════════════
# EXTRACTION DES TEXTES (TAGS DE LIGNE)
# ═══════════════════════════════════════════════════════════════════════

def extract_labels(msp, cfg: ExtractionConfig) -> List[Dict[str, Any]]:
    labels = []
    for e in msp.query("TEXT"):
        layer = _entity_layer(e)
        if _layer_matches(layer, cfg.text_layer_exclude_keywords):
            continue
        insert = e.dxf.insert
        text = re.sub(r'\s+', ' ', e.dxf.text).strip()
        if text:
            labels.append({"text": text, "x": insert.x, "y": insert.y, "layer": layer})

    for e in msp.query("MTEXT"):
        layer = _entity_layer(e)
        if _layer_matches(layer, cfg.text_layer_exclude_keywords):
            continue
        insert = e.dxf.insert
        plain = e.plain_text() if hasattr(e, "plain_text") else e.text
        text = re.sub(r'\s+', ' ', plain).strip()
        if text:
            labels.append({"text": text, "x": insert.x, "y": insert.y, "layer": layer})

    return labels


# ═══════════════════════════════════════════════════════════════════════
# EXTRACTION DES BLOCS (ÉQUIPEMENTS, VANNES, INSTRUMENTS, FLÈCHES)
# ═══════════════════════════════════════════════════════════════════════

def _get_block_attribs(insert_entity) -> Dict[str, str]:
    attribs = {}
    if insert_entity.attribs:
        for a in insert_entity.attribs:
            attribs[a.dxf.tag.upper()] = a.dxf.text
    return attribs


def _resolve_tag(attribs: Dict[str, str], block_name: str, cfg: ExtractionConfig) -> Tuple[str, str]:
    """Retourne (tag, source) où source vaut 'attribute' ou 'block_name' (fallback générique)."""
    # 1. Composite instrument attributes: ex: SYSTEM_NO=18, INST_TYPE=PIT, INSTR_NO=01201 -> 18-PIT-01201
    if "INST_TYPE" in attribs and "INSTR_NO" in attribs:
        sys_no = attribs.get("SYSTEM_NO", "").strip()
        itype = attribs.get("INST_TYPE", "").strip()
        ino = attribs.get("INSTR_NO", "").strip()
        tag_str = f"{sys_no}-{itype}-{ino}".strip("-")
        if tag_str:
            return tag_str, "attribute"

    # 2. Tag candidates from attribute list
    for cand in cfg.tag_attribute_candidates:
        if cand in attribs and attribs[cand].strip():
            return attribs[cand].strip(), "attribute"

    if len(attribs) == 1:
        return list(attribs.values())[0].strip(), "attribute"
    return block_name, "block_name"


def _classify_block(block_name: str, cfg: ExtractionConfig) -> str:
    if _name_matches(block_name, cfg.opc_block_keywords):
        return "OPC"
    if _name_matches(block_name, cfg.valve_block_keywords):
        return "Valve"
    if _name_matches(block_name, cfg.instrument_block_keywords):
        return "Instrument"
    if _name_matches(block_name, cfg.flow_arrow_block_keywords):
        return "FlowArrow"
    if _name_matches(block_name, cfg.equipment_block_keywords):
        return "Equipment"
    return "Component"


def extract_blocks_and_opcs(
    msp, doc, cfg: ExtractionConfig
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    blocks = []
    opcs = []

    for e in msp.query("INSERT"):
        block_name = e.dxf.name
        attribs = _get_block_attribs(e)
        comp_type = _classify_block(block_name, cfg)
        x, y = e.dxf.insert.x, e.dxf.insert.y

        # Bounding box approximative via l'étendue de la définition de bloc (échelle appliquée)
        try:
            block_def = doc.blocks.get(block_name)
            xs, ys = [], []
            for be in block_def:
                if hasattr(be.dxf, "insert"):
                    xs.append(be.dxf.insert.x)
                    ys.append(be.dxf.insert.y)
            width = (max(xs) - min(xs)) * abs(e.dxf.xscale) if len(xs) >= 2 else 40.0
            height = (max(ys) - min(ys)) * abs(e.dxf.yscale) if len(ys) >= 2 else 40.0
            width = width or 40.0
            height = height or 40.0
        except Exception:
            width, height = 40.0, 40.0

        # Ports = points d'attributs additionnels marqués "PORT" ou, à défaut, l'insertion
        ports = [{"x": x, "y": y, "name": "Nozzle-Fallback"}]
        for tag_name, val in attribs.items():
            if tag_name.startswith("PORT"):
                ports.append({"x": x, "y": y, "name": val})

        if comp_type == "OPC":
            ref_code = None
            for cand in cfg.opc_ref_attribute_candidates:
                if cand in attribs and attribs[cand].strip():
                    ref_code = attribs[cand].strip()
                    break
            ref_code = ref_code or block_name
            opcs.append({"x": x, "y": y, "ref_code": ref_code})
            # Un OPC reste aussi visible comme "block" pour permettre son rattachement
            blocks.append({
                "tag": f"OPC:{ref_code}", "type": "OPC", "x": x, "y": y,
                "width": width, "height": height, "ports": ports
            })
            continue

        tag, tag_source = _resolve_tag(attribs, block_name, cfg)
        block_dir_x, block_dir_y = 1.0, 0.0
        if comp_type == "FlowArrow":
            angle = math.radians(getattr(e.dxf, "rotation", 0.0))
            block_dir_x, block_dir_y = math.cos(angle), math.sin(angle)

        blocks.append({
            "tag": tag, "type": comp_type, "x": x, "y": y,
            "width": width, "height": height, "ports": ports,
            "ux": block_dir_x, "uy": block_dir_y, "tag_source": tag_source,
        })

    return blocks, opcs


# ═══════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE UNIQUE
# ═══════════════════════════════════════════════════════════════════════

_TAG_LIKE_RE = re.compile(r'^\d{2,4}-[A-Za-z]{1,5}-\d{2,4}[A-Za-z]{0,2}$')


def attach_tags_from_nearby_text(
    blocks: List[Dict[str, Any]], labels: List[Dict[str, Any]], search_radius: float = 25.0
) -> List[Dict[str, Any]]:
    """
    Certains DXF (notamment convertis depuis des DWG anciens, ou dessinés sans
    attributs de bloc) ne portent AUCUN tag dans le bloc lui-même : le nom du
    bloc CAD n'est qu'un nom de symbole générique ("ball valve", "clapet de
    non retour"...), et l'identifiant réel (ex: "214-HV-003") n'existe que
    comme texte libre posé à côté sur le plan. Pour ces blocs (tag_source ==
    'block_name'), on cherche le texte le plus proche qui ressemble à un tag
    d'équipement/vanne réel (motif NNN-LL-NNN) et on l'utilise à la place du
    nom de symbole générique, avec traçabilité de la substitution.
    """
    candidate_labels = [l for l in labels if _TAG_LIKE_RE.match(l.get("text", "").strip())]

    for b in blocks:
        if b.get("tag_source") != "block_name" or not candidate_labels:
            continue
        bx, by = b["x"], b["y"]
        best_label, best_dist = None, float("inf")
        for l in candidate_labels:
            d = math.hypot(l["x"] - bx, l["y"] - by)
            if d < best_dist:
                best_dist, best_label = d, l
        if best_label is not None and best_dist <= search_radius:
            b["symbol_type"] = b["tag"]  # conserve le nom de symbole générique pour info
            b["tag"] = best_label["text"].strip()
            b["tag_source"] = "nearby_text"
            b["tag_match_distance"] = round(best_dist, 2)

    return blocks


def extract_drawing(dxf_path: str, cfg: ExtractionConfig | None = None) -> Dict[str, Any]:
    """Lit un fichier DXF et retourne les 4 structures attendues par PipingTopologyTracer."""
    cfg = cfg or ExtractionConfig()
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    segments = extract_segments(msp, cfg)
    labels = extract_labels(msp, cfg)
    blocks, opcs = extract_blocks_and_opcs(msp, doc, cfg)

    tol = estimate_geometry_tolerances(segments, blocks)
    blocks = attach_tags_from_nearby_text(blocks, labels, search_radius=tol["label_proximity_radius"])

    return {
        "segments": segments,
        "labels": labels,
        "blocks": blocks,
        "opcs": opcs,
        "geometry_tolerances": tol,
        "entity_counts": {
            "segments": len(segments),
            "labels": len(labels),
            "blocks": len(blocks),
            "opcs": len(opcs),
        },
    }
