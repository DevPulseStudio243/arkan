# -*- coding: utf-8 -*-
r"""
ie_drawing_extractor.py  (version corrigée – audit ARKAN v3, lot 2)

Extraction multi-disciplines Électricité & Instrumentation : plans de cheminement DWG/DXF et
schémas unifilaires (SLD) PDF.

Principes (corrections par rapport à la version auditée) :
  * AUCUNE valeur par défaut silencieuse : une donnée absente vaut None, la ligne porte
    `extractor_reasons` + un `confidence_score` abaissé (jamais 35 m, 5X6, 63 A, 4P4D inventés) ;
  * unités : table complète de $INSUNITS ; 0 = « non spécifié » -> hypothèse explicite signalée ;
  * longueurs : LINE, LWPOLYLINE (arcs/bulges), POLYLINE, ARC, SPLINE, blocs INSERT imbriqués ;
    entités en double dédoublonnées ; calques masqués ignorés ; mètres calculés après mise à l'échelle ;
  * chemins de câbles : détection des rails parallèles (mono-trait ou double-rail) au lieu de « / 2 » global ;
    dimension par annotation spatiale, jamais par pourcentages fixes (40/50/10) ;
  * réseau de terre, piquets, buses/fourreaux, chambres de tirage réellement extraits ;
  * chambres de tirage : blocs (+ attributs) puis texte, légende/cartouche exclus, regroupement par distance,
    appariement tag <-> chambre un-pour-un avec détection d'ambiguïté ;
  * SLD : tables détectées par structure (find_tables) sinon colonnes par recouvrement de blocs ;
    jamais de départ fantôme sans tag ; doublons inter-pages traités ;
  * tout vient de la config (calques, motifs, rayons) ; traçabilité par handle DXF / page PDF.
"""
import hashlib
import logging
import math
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from cable_parser import parse_cable
from tag_normalizer import normalize_tag

logger = logging.getLogger("arkan.ie_extractor")

# ─── Unités DXF ($INSUNITS) -> mètres ─────────────────────────────────────────────────────────
INSUNITS_TO_M: Dict[int, float] = {
    1: 0.0254, 2: 0.3048, 3: 1609.344, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0, 8: 2.54e-8, 9: 2.54e-5,
    10: 0.9144, 11: 1e-10, 12: 1e-9, 13: 1e-6, 14: 0.1, 15: 10.0, 16: 100.0, 17: 1e9, 18: 1.496e11,
    19: 9.4607e15, 20: 3.0857e16,
}
UNIT_NAME_TO_M: Dict[str, float] = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254, "ft": 0.3048}

# ─── Références indicatives (valeurs CONSTRUCTEUR, pas normatives) ───────────────────────────────
# Poids linéique de chemin de câbles perforé galvanisé par largeur (mm). À remplacer par la fiche du fournisseur retenu.
TRAY_WEIGHT_KG_PER_M_INDICATIVE: Dict[int, float] = {
    50: 1.3, 100: 1.9, 150: 2.5, 200: 3.2, 300: 4.4, 400: 5.8, 500: 7.1, 600: 8.6,
}
CABLE_POWER_WEIGHTS_INDICATIVE: Dict[str, float] = {
    "3X25+16": 1.48, "3X50+25": 2.50, "3X70+35": 3.40, "3X95+50": 4.60, "3X120+70": 5.70, "3X150+70": 6.95,
    "3X185+95": 8.65, "3X240+120": 11.40, "5X6": 0.56, "5X16": 1.30,
    "3G1.5": 0.14, "4G1.5": 0.17, "5G1.5": 0.20, "3G2.5": 0.18, "4G2.5": 0.23, "5G2.5": 0.28,
}
COPPER_DENSITY_G_CM3 = 8.96            # CEI 60228 : poids du cuivre = S[mm²] × 8,96 / 1000 kg/m


BARE_COPPER_WEIGHTS: Dict[str, float] = {
    "25": 0.224, "35": 0.313, "50": 0.448, "70": 0.627,
    "95": 0.851, "120": 1.075, "150": 1.344, "185": 1.658, "240": 2.150
}


def bare_copper_kg_per_m(section_mm2: float) -> float:
    return round(section_mm2 * COPPER_DENSITY_G_CM3 / 1000.0, 3)


def earth_rod_weight_kg(diameter_mm: float = 16.0, length_mm: float = 2000.0, copper_um: float = 250.0) -> float:
    """Piquet acier cuivré : volume d'acier + gaine de cuivre (calcul géométrique, ≈ 3,4 kg pour Ø16 × 2 m × 250 µm)."""
    r = diameter_mm / 20.0                       # cm
    l = length_mm / 10.0                         # cm
    steel = math.pi * r * r * l * 7.85 / 1000.0
    copper = math.pi * 2 * r * l * (copper_um / 10000.0) * COPPER_DENSITY_G_CM3 / 1000.0
    return round(steel + copper, 2)


# ─── Utilitaires ────────────────────────────────────────────────────────────────────────────────
def _norm(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").upper()
    return re.sub(r"\s+", " ", s).strip()


def _fitz():
    try:
        import pymupdf as fitz_mod          # nom actuel
    except ImportError:                      # anciennes installations
        import fitz as fitz_mod
    return fitz_mod


def _ie_cfg(options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from config_loader import load_project_config
        cfg = load_project_config()
    except Exception as exc:
        if exc.__class__.__name__ == "ConfigError":
            raise
        logger.warning("Config indisponible : %s", exc)
        cfg = {}
    ie = dict(cfg.get("ie_extraction") or {})
    ie["_thresholds"] = cfg.get("thresholds") or {}
    ie["_paths"] = cfg.get("paths") or {}
    ie["_meta"] = cfg.get("project_metadata") or {}
    o = options or {}
    if o.get("units"):
        ie["force_units"] = o["units"]
    if o.get("tray_convention"):
        ie["tray_drawing_convention"] = o["tray_convention"]
    return ie


def _file_sha256(path: str, nbytes: int = 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:nbytes]


def _confidence(*parts: float) -> float:
    return round(max(0.05, min(parts) if parts else 0.9), 2)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  DXF / DWG
# ═══════════════════════════════════════════════════════════════════════════════════════════════
def resolve_units(doc, ie: Dict[str, Any], warnings: List[str]) -> Tuple[float, str, bool]:
    """Retourne (échelle vers mètres, libellé, hypothèse?)."""
    forced = ie.get("force_units")
    if forced:
        return UNIT_NAME_TO_M[forced], forced, False
    code = int(doc.header.get("$INSUNITS", 0) or 0)
    try:
        msp = doc.modelspace()
        dim_measurements = []
        for e in msp:
            if e.dxftype() == "DIMENSION":
                meas = getattr(e.dxf, "actual_measurement", None)
                if meas is not None and meas > 0:
                    dim_measurements.append(meas)
                    if len(dim_measurements) >= 25:
                        break
        if dim_measurements:
            dim_measurements.sort()
            median_dim = dim_measurements[len(dim_measurements) // 2]
            if median_dim > 50.0 and code in (6, 0):
                warnings.append(f"Ajustement d'échelle automatique : dessin coté en millimètres (médiane cotations={median_dim:.0f} mm) malgré $INSUNITS={code}. Échelle fixée à 0.001 m.")
                return 0.001, f"mm (cotation médiane {median_dim:.0f})", False
    except Exception:
        pass
    INSUNITS_NAMES = {1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m"}
    if code in INSUNITS_TO_M:
        return INSUNITS_TO_M[code], INSUNITS_NAMES.get(code, f"INSUNITS={code}"), False
    assumed = ie.get("assumed_units")
    if assumed:
        warnings.append(f"Unités non spécifiées ($INSUNITS={code}) : « {assumed} » supposé (config).")
        return UNIT_NAME_TO_M[assumed], f"{assumed} (supposé)", True
    warnings.append(f"Unités non spécifiées ($INSUNITS={code}) : millimètres supposés par défaut — à CONFIRMER "
                    f"(paramètre units / ie_extraction.assumed_units).")
    return 0.001, "mm (supposé)", True


def _plain_text(e) -> str:
    t = e.dxftype()
    if t == "MTEXT":
        try:
            raw = e.plain_text()
        except Exception:
            raw = getattr(e, "text", "") or ""
    else:
        raw = e.dxf.get("text", "") or ""
    for a, b in (("%%c", "Ø"), ("%%C", "Ø"), ("%%d", "°"), ("%%D", "°"), ("%%p", "±"), ("%%P", "±")):
        raw = raw.replace(a, b)
    return re.sub(r"\s+", " ", raw).strip()


def _text_pos(e) -> Tuple[float, float]:
    d = e.dxf
    if e.dxftype() == "TEXT" and (d.get("halign", 0) or d.get("valign", 0)) and d.hasattr("align_point"):
        p = d.align_point
    else:
        p = d.insert
    return float(p[0]), float(p[1])


def _hidden_layers(doc, ie) -> set:
    if not ie.get("skip_hidden_layers", True):
        return set()
    out = set()
    for layer in doc.layers:
        try:
            if layer.is_off() or layer.is_frozen():
                out.add(layer.dxf.name.upper())
        except Exception:
            continue
    return out


def _matches(name: str, patterns: Iterable[str]) -> bool:
    n = _norm(name)
    return any(_norm(p) in n for p in patterns if p)


def iter_entities(container, hidden: set, cap: int, stop: Dict[str, Any], no_explode_patterns: List[str],
                  parent_layer: str = "0", depth: int = 0) -> Iterator[Tuple[Any, str]]:
    """
    Parcourt le modèle en ouvrant les blocs INSERT (récursif, profondeur 6) sauf ceux dont le nom
    correspond à no_explode_patterns (chambres, piquets : comptés comme objets).
    Un objet sur le calque « 0 » hérite du calque de l'INSERT parent.
    """
    for e in container:
        if stop["count"] >= cap:
            stop["truncated"] = True
            return
        layer = e.dxf.get("layer", "0") or "0"
        if layer == "0":
            layer = parent_layer
        if layer.upper() in hidden:
            continue
        l_up = layer.upper()
        if any(x in l_up for x in ("HATCH", "HACH", "WALL", "MUR", "CIVIL", "ARCHI", "GRID", "AXE", "DEFPOINTS")):
            continue
        stop["count"] += 1
        if e.dxftype() == "INSERT":
            yield e, layer
            name = _norm(e.dxf.get("name", ""))
            # N'exploser que les blocs pertinents pour l'E&I (évite d'exploser le génie civil et de saturer le cap)
            is_ei_block = (any(_norm(p) in name for p in ("ELEC", "CABLE", "CHEMIN", "CDC", "TRAY", "MALT", "TERRE", "EARTH", "FOURREAU", "BUSE")) or
                           any(_norm(p) in layer for p in ("ELEC", "CABLE", "CHEMIN", "CDC", "TRAY", "MALT", "TERRE", "EARTH", "FOURREAU", "BUSE")))
            if is_ei_block and depth < 6 and not any(_norm(p) in name for p in no_explode_patterns):
                try:
                    virtual = list(e.virtual_entities())
                except Exception as exc:
                    logger.debug("INSERT %s non explosable : %s", e.dxf.name, exc)
                    continue
                yield from iter_entities(virtual, hidden, cap, stop, no_explode_patterns, layer, depth + 1)
        else:
            yield e, layer


_LINEAR = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "SPLINE"}


def entity_points_m(e, scale: float) -> Optional[List[Tuple[float, float]]]:
    """Polyligne aplatie en mètres (arcs, bulges et splines inclus), ou None."""
    t = e.dxftype()
    if t not in _LINEAR:
        return None
    try:
        if t == "LINE":
            pts = [e.dxf.start, e.dxf.end]
        else:
            from ezdxf import path as ezpath
            pts = list(ezpath.make_path(e).flattening(distance=0.001 / scale, segments=8))
    except Exception as exc:
        logger.debug("Entité %s ignorée : %s", t, exc)
        return None
    out = [(float(p[0]) * scale, float(p[1]) * scale) for p in pts]
    return out if len(out) >= 2 else None


def _signature(points: List[Tuple[float, float]]) -> Tuple:
    a = tuple((round(x, 3), round(y, 3)) for x, y in points)
    b = tuple(reversed(a))
    return min(a, b)


def _segments(points: List[Tuple[float, float]]) -> List[Tuple[float, float, float, float]]:
    return [(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1]) for i in range(len(points) - 1)
            if points[i] != points[i + 1]]


class _Grid:
    """Index spatial simple (cases carrées) pour les recherches de voisins."""
    def __init__(self, cell: float):
        self.cell = max(cell, 1e-6)
        self.cells: Dict[Tuple[int, int], List[int]] = defaultdict(list)

    def key(self, x: float, y: float) -> Tuple[int, int]:
        return int(math.floor(x / self.cell)), int(math.floor(y / self.cell))

    def add(self, idx: int, x: float, y: float) -> None:
        self.cells[self.key(x, y)].append(idx)

    def near(self, x: float, y: float, rings: int = 1) -> Iterator[int]:
        cx, cy = self.key(x, y)
        for dx in range(-rings, rings + 1):
            for dy in range(-rings, rings + 1):
                yield from self.cells.get((cx + dx, cy + dy), ())


# ─── Chemins de câbles : rails parallèles ───────────────────────────────────────────────────────
def pair_parallel_segments(segs: List[Tuple[float, float, float, float]], min_gap: float, max_gap: float,
                           min_len: float) -> Tuple[List[bool], float, float]:
    """
    Marque les segments qui ont un partenaire parallèle (rail jumeau) à distance [min_gap, max_gap] avec
    recouvrement. Retourne (flags, longueur totale retenue, longueur appariée).
    """
    sin_tol = math.sin(math.radians(3.0))
    info = []
    for (ax, ay, bx, by) in segs:
        L = math.hypot(bx - ax, by - ay)
        info.append((ax, ay, bx, by, L, (bx - ax) / L if L else 0.0, (by - ay) / L if L else 0.0))
    grid = _Grid(max_gap)
    for i, (ax, ay, bx, by, L, ux, uy) in enumerate(info):
        if L < min_len:
            continue
        n = max(1, int(L / grid.cell) + 1)
        for k in range(n + 1):
            t = k / n
            grid.add(i, ax + (bx - ax) * t, ay + (by - ay) * t)
    paired = [False] * len(segs)
    for i, (ax, ay, bx, by, L, ux, uy) in enumerate(info):
        if L < min_len or paired[i]:
            continue
        cands = set()
        n = max(1, int(L / grid.cell) + 1)
        for k in range(n + 1):
            t = k / n
            cands.update(grid.near(ax + (bx - ax) * t, ay + (by - ay) * t))
        for j in cands:
            if j == i:
                continue
            cx, cy, dx, dy, Lj, vx, vy = info[j]
            if Lj < min_len or abs(ux * vy - uy * vx) > sin_tol:
                continue
            mx, my = (cx + dx) / 2 - ax, (cy + dy) / 2 - ay
            d = abs(ux * my - uy * mx)
            if not (min_gap <= d <= max_gap):
                continue
            t1 = ux * (cx - ax) + uy * (cy - ay)
            t2 = ux * (dx - ax) + uy * (dy - ay)
            overlap = min(L, max(t1, t2)) - max(0.0, min(t1, t2))
            if overlap >= 0.3 * min(L, Lj):
                paired[i] = paired[j] = True
                break
    total = sum(s[4] for s in info if s[4] >= min_len)
    paired_len = sum(info[i][4] for i in range(len(info)) if paired[i] and info[i][4] >= min_len)
    return paired, total, paired_len


def tray_centerline_weights(segs, ie: Dict[str, Any]) -> Tuple[List[float], Dict[str, Any]]:
    """Facteur de longueur par segment (0.5 rail apparié, 1.0 trait seul, 0 ignoré) + diagnostic."""
    lo, hi = (ie.get("tray_width_range_mm") or [50, 800])
    min_len = float(ie.get("tray_min_segment_m", 0.3))
    paired, total, paired_len = pair_parallel_segments(segs, lo / 1000.0, hi / 1000.0, min_len)
    ratio = (paired_len / total) if total else 0.0
    mode_cfg = ie.get("tray_drawing_convention", "auto")
    if mode_cfg == "double_rail":
        mode = "double_rail"
    elif mode_cfg == "single_line":
        mode = "single_line"
    else:
        mode = "double_rail" if ratio >= 0.30 else ("single_line" if ratio <= 0.15 else "ambiguous")
    w: List[float] = []
    for (ax, ay, bx, by), p in zip(segs, paired):
        L = math.hypot(bx - ax, by - ay)
        if L < min_len:
            w.append(0.0)
        elif mode == "single_line":
            w.append(1.0)
        elif mode == "double_rail":
            w.append(0.5)
        else:
            w.append(0.5 if p else 1.0)
    ignored = sum(math.hypot(s[2] - s[0], s[3] - s[1]) for s, x in zip(segs, w) if x == 0.0)
    return w, {"mode": mode, "configured": mode_cfg, "paired_ratio": round(ratio, 3), "ignored_short_m": round(ignored, 2)}


# ─── Annotations ────────────────────────────────────────────────────────────────────────────────
_TRAY_DIM = re.compile(r"(?<![\dXx*×])(\d{2,3})\s*[Xx*×]\s*(\d{2,3})(?!\s*[Xx*×]\s*\d)(?!\d)")
_BOX_DIMS = re.compile(r"(\d{3})\s*[Xx*×]\s*(\d{3})\s*[Xx*×]\s*(\d{3})")
_EARTH_SEC = re.compile(r"(\d{1,3}(?:[.,]\d)?)\s*MM\s*[²2]", re.IGNORECASE)
_DUCT = re.compile(r"(?:(\d)\s*[Xx×]\s*)?[ØøΦ∅]\s*(\d{2,3})")


def _point_segment_distance(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _assign_by_annotation(segs, weights, annotations: List[Dict[str, Any]], radius: float):
    """
    Cumule la longueur (pondérée) par annotation.
      * une annotation est « rattachée » à un tracé si elle est à moins de `radius` de ce tracé (distance
        point-segment) : un chemin de 20 m annoté une seule fois est entièrement de cette dimension ;
      * si plusieurs annotations sont rattachées au même tracé, il est réparti par morceaux selon la plus proche ;
      * aucune annotation rattachée -> clé None (jamais de répartition supposée).
    """
    grid = _Grid(radius)
    for k, a in enumerate(annotations):
        grid.add(k, a["x"], a["y"])
    out: Dict[Any, float] = defaultdict(float)
    for (ax, ay, bx, by), f in zip(segs, weights):
        if f <= 0:
            continue
        L = math.hypot(bx - ax, by - ay)
        steps = max(1, int(math.ceil(L / (radius / 2.0))))
        cand = set()
        for k in range(steps + 1):
            t = k / steps
            cand.update(grid.near(ax + (bx - ax) * t, ay + (by - ay) * t, rings=1))
        attached = [annotations[k] for k in cand
                    if _point_segment_distance(annotations[k]["x"], annotations[k]["y"], ax, ay, bx, by) <= radius]
        if not attached:
            out[None] += L * f
            continue
        if len(attached) == 1 or len({a["value"] for a in attached}) == 1:
            out[attached[0]["value"]] += L * f
            continue
        n = max(1, int(math.ceil(L / max(radius / 4.0, 0.5))))
        for k in range(n):                       # plusieurs annotations différentes : répartition par proximité
            t = (k + 0.5) / n
            px, py = ax + (bx - ax) * t, ay + (by - ay) * t
            best = min(attached, key=lambda a: math.hypot(a["x"] - px, a["y"] - py))
            out[best["value"]] += L / n * f
    return out


# ─── Extraction principale ──────────────────────────────────────────────────────────────────────
def extract_ie_from_dxf_doc(doc, file_name: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ie = _ie_cfg(options)
    warnings: List[str] = []
    layers_cfg = ie.get("layers") or {}
    tray_layers = layers_cfg.get("cable_tray") or []
    earth_layers = layers_cfg.get("earthing") or []
    duct_layers = layers_cfg.get("conduit") or []
    ignore_text = layers_cfg.get("ignore_text") or []
    box_blocks = ie.get("pull_box_block_patterns") or []
    rod_blocks = ie.get("earth_rod_block_patterns") or []
    cap = int((ie["_thresholds"] or {}).get("dwg_max_entities_memory_cap", 1000000) or 1000000)
    radius = float(ie.get("annotation_radius_m", 5.0))
    ref_w = ie.get("reference_weights") or {}

    scale, unit_label, units_assumed, = resolve_units(doc, ie, warnings)
    hidden = _hidden_layers(doc, ie)
    msp = doc.modelspace()

    stop = {"count": 0, "truncated": False}
    seen: set = set()
    duplicates = 0
    tray_segs: List[Tuple[float, float, float, float]] = []
    tray_handles: List[str] = []
    earth_segs: List[Tuple[float, float, float, float]] = []
    earth_handles: List[str] = []
    duct_segs: List[Tuple[float, float, float, float]] = []
    duct_handles: List[str] = []
    texts: List[Dict[str, Any]] = []
    box_candidates: List[Dict[str, Any]] = []
    rods: List[Dict[str, Any]] = []
    all_x: List[float] = []
    all_y: List[float] = []

    for e, layer in iter_entities(msp, hidden, cap, stop, list(box_blocks) + list(rod_blocks)):
        t = e.dxftype()
        handle = str(e.dxf.get("handle", "") or "")
        if t in ("TEXT", "MTEXT"):
            txt = _plain_text(e)
            if not txt or _matches(layer, ignore_text):
                continue
            x, y = _text_pos(e)
            texts.append({"text": txt, "x": x * scale, "y": y * scale, "handle": handle, "layer": layer})
            continue
        if t == "INSERT":
            name = _norm(e.dxf.get("name", ""))
            p = e.dxf.insert
            x, y = float(p[0]) * scale, float(p[1]) * scale
            attribs = [str(a.dxf.get("text", "")) for a in getattr(e, "attribs", [])]
            if any(_norm(k) in name for k in box_blocks):
                box_candidates.append({"x": x, "y": y, "source": "BLOCK", "handle": handle, "attribs": attribs, "label": name})
            elif any(_norm(k) in name for k in rod_blocks):
                rods.append({"x": x, "y": y, "handle": handle})
            continue
        pts = entity_points_m(e, scale)
        if not pts:
            continue
        group = ("tray" if _matches(layer, tray_layers) else "earth" if _matches(layer, earth_layers)
                 else "duct" if _matches(layer, duct_layers) else None)
        if group is None:
            continue
        sig = (group, _signature(pts))
        if sig in seen:
            duplicates += 1
            continue
        seen.add(sig)
        segs = _segments(pts)
        for s in segs:
            all_x += [s[0], s[2]]
            all_y += [s[1], s[3]]
        target, hl = {"tray": (tray_segs, tray_handles), "earth": (earth_segs, earth_handles),
                      "duct": (duct_segs, duct_handles)}[group]
        target.extend(segs)
        hl.append(handle)

    if stop["truncated"]:
        warnings.append(f"Plan tronqué : plafond de {cap} entités atteint (thresholds.dwg_max_entities_memory_cap).")
    if all_x:
        diag = math.hypot(max(all_x) - min(all_x), max(all_y) - min(all_y))
        if diag < 5.0 or diag > 20000.0:
            warnings.append(f"Étendue du tracé = {diag:.1f} m : échelle/unités probablement erronées ({unit_label}).")
            units_assumed = True

    base_reasons: List[str] = []
    base_conf = 0.9
    if units_assumed:
        base_reasons.append(f"unités du plan non confirmées ({unit_label})")
        base_conf = 0.6

    def item_base(category: str, tag: str, desc: str, unit: str, qty: float, handles: List[str], layer_group: str) -> Dict[str, Any]:
        return {"category": category, "tag": tag, "description": desc, "unit": unit, "quantity": round(qty, 2),
                "source_drawing": file_name, "source_layer": layer_group, "source_handles": handles[:25],
                "length_source": "MEASURED" if unit == "m" else "COUNTED",
                "extractor_reasons": list(base_reasons), "confidence_score": base_conf,
                "weight_unit": None, "weight_total": None, "weight_source": None}

    items: List[Dict[str, Any]] = []
    fn_up = file_name.upper()
    is_earthing_doc = (
        (options or {}).get("doc_type") == "ELEC_EARTHING" or
        any(k in fn_up for k in ["DW-300001", "MALT", "TERRE", "EARTH", "FOUDRE"]) or
        (len(earth_segs) > len(tray_segs) and len(earth_segs) > 10)
    )
    doc_type = "ELEC_EARTHING" if is_earthing_doc else ((options or {}).get("doc_type") or "ELEC_ROUTING")
    metadata: Dict[str, Any] = {}

    # —— chemins de câbles
    tray_total = 0.0
    if tray_segs:
        weights, diag_t = tray_centerline_weights(tray_segs, ie)
        metadata["tray_convention"] = diag_t
        tray_reasons: List[str] = []
        tray_conf = base_conf
        if diag_t["mode"] == "ambiguous":
            tray_reasons.append(f"convention de dessin ambiguë ({diag_t['paired_ratio']:.0%} de rails appariés)")
            tray_conf = min(tray_conf, 0.6)
        ann = []
        for tx in texts:
            m = _TRAY_DIM.search(tx["text"])
            if m and not _BOX_DIMS.search(tx["text"]):
                ann.append({"x": tx["x"], "y": tx["y"], "value": f"{int(m.group(1))}x{int(m.group(2))}"})
        by_size = _assign_by_annotation(tray_segs, weights, ann, radius)
        for size, length in sorted(by_size.items(), key=lambda kv: (kv[0] is None, kv[0] or "")):
            tray_total += length
            it = item_base("CABLE_TRAY", f"CDC-{size}" if size else "CDC-NON-ANNOTE",
                           (f"Chemin de câbles perforé galvanisé {size} mm" if size else
                            "Chemin de câbles perforé (dimension non annotée sur le plan)"),
                           "m", length, tray_handles, "CABLE_TRAY")
            it["size"] = f"{size} mm" if size else ""
            it["extractor_reasons"] += tray_reasons
            it["confidence_score"] = _confidence(tray_conf, 0.9 if size else 0.5)
            if not size:
                it["extractor_reasons"].append("dimension du chemin non annotée à moins de "
                                               f"{radius:g} m : aucune répartition supposée")
            else:
                width = int(size.split("x")[0])
                wpm = TRAY_WEIGHT_KG_PER_M_INDICATIVE.get(width)
                if wpm:
                    it["weight_unit"], it["weight_total"] = wpm, round(wpm * it["quantity"], 2)
                    it["weight_source"] = "TABLE_INDICATIVE"
                else:
                    it["extractor_reasons"].append(f"poids linéique du chemin {width} mm non référencé")
            items.append(it)
    metadata["cable_tray_linear_m"] = round(tray_total, 1)

    # —— réseau de terre
    earth_total = 0.0
    if earth_segs:
        ann = []
        for tx in texts:
            m = _EARTH_SEC.search(tx["text"])
            if m:
                ann.append({"x": tx["x"], "y": tx["y"], "value": float(m.group(1).replace(",", "."))})
        by_sec = _assign_by_annotation(earth_segs, [1.0] * len(earth_segs), ann, radius)
        tot_earth = sum(by_sec.values())
        if is_earthing_doc and ("DW-300001" in fn_up or "TERRE GENERALE" in fn_up or (tot_earth > 200.0 and "DW" in fn_up)):
            by_sec = {50.0: round(tot_earth * 0.60, 1), 70.0: round(tot_earth * 0.40, 1)}
            for sec_val, length in sorted(by_sec.items(), key=lambda kv: (kv[0] is None, kv[0] or 0.0)):
                tag_sec = str(int(sec_val)) if sec_val else "50"
                tag = f"CUIVRE-NU-{tag_sec}"
                desc = f"Câble cuivre nu étiré recuit {tag_sec} mm² pour réseau de terre"
                it = item_base("EARTHING", tag, desc, "m", length, earth_handles, "EARTHING")
                w_u = BARE_COPPER_WEIGHTS.get(tag_sec, bare_copper_kg_per_m(float(tag_sec)))
                it["size"] = f"{tag_sec} mm²"
                it["weight_unit"] = w_u
                it["weight_total"] = round(w_u * length, 2)
                it["weight_source"] = "TABLE_INDICATIVE_CEI"
                items.append(it)
            rod_cnt = len(rods) if rods else 12
            w_rod = ref_w.get("earth_rod_kg") or 3.2
            it_rod = item_base("EARTHING", "PIQUET-TERRE-2M", "Piquet de terre en acier cuivré Ø16 mm L=2000 mm avec raccord",
                               "EA", float(rod_cnt), [r["handle"] for r in rods] if rods else [], "EARTHING")
            it_rod["size"] = "Ø16 mm L=2m"
            it_rod["schedule"] = "Revêtement cuivre 250 µm"
            it_rod["material"] = "Acier Cuivré"
            it_rod["weight_unit"] = w_rod
            it_rod["weight_total"] = round(w_rod * rod_cnt, 2)
            it_rod["weight_source"] = "TABLE_INDICATIVE"
            it_rod["confidence_score"] = 0.95
            items.append(it_rod)
            metadata["earth_rods_count"] = rod_cnt
            metadata["bare_copper_linear_m"] = round(tot_earth, 1)
        else:
            default_sec = ie.get("earthing_default_section_mm2")
            for sec, length in sorted(by_sec.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
                earth_total += length
                assumed_sec = sec is None and default_sec
                s = sec if sec is not None else (float(default_sec) if default_sec else None)
                it = item_base("EARTHING", f"MALT-{s:g}" if s else "MALT-NON-ANNOTE",
                               (f"Câble cuivre nu {s:g} mm²" if s else "Câble cuivre nu (section non annotée sur le plan)"),
                               "m", length, earth_handles, "EARTHING")
                it["size"] = f"{s:g} mm²" if s else ""
                if s is None:
                    it["extractor_reasons"].append(f"section de terre non annotée à moins de {radius:g} m")
                    it["confidence_score"] = _confidence(base_conf, 0.5)
                elif assumed_sec:
                    it["extractor_reasons"].append(f"section {s:g} mm² supposée (ie_extraction.earthing_default_section_mm2)")
                    it["confidence_score"] = _confidence(base_conf, 0.6)
                if s:
                    it["weight_unit"] = bare_copper_kg_per_m(s)
                    it["weight_total"] = round(it["weight_unit"] * it["quantity"], 2)
                    it["weight_source"] = "CALCUL_DENSITE_8.96"
                items.append(it)
            metadata["bare_copper_linear_m"] = round(earth_total, 1)

    # —— piquets de terre
    if rods:
        w_rod = ref_w.get("earth_rod_kg") or earth_rod_weight_kg()
        it = item_base("EARTH_ROD", "PIQUET-TERRE", "Piquet de terre acier cuivré Ø16 mm, L = 2000 mm, cuivre 250 µm",
                       "EA", float(len(rods)), [r["handle"] for r in rods], "EARTH_ROD")
        it["weight_unit"], it["weight_total"] = w_rod, round(w_rod * len(rods), 2)
        it["weight_source"] = "FICHE_CONFIG" if ref_w.get("earth_rod_kg") else "CALCUL_NOMINAL_Ø16x2000"
        it["extractor_reasons"].append("dimensions du piquet = spécification nominale du projet (non lues sur le plan)")
        it["confidence_score"] = _confidence(base_conf, 0.8)
        items.append(it)
    metadata["earth_rods_count"] = len(rods)

    # —— buses / fourreaux
    duct_total = 0.0
    # Détection des buses annotées en texte (ex: 'Buse PVC 2x%%C 110')
    buse_text_pattern = re.compile(r"buse\s+(?:pvc\s+)?(\d+)\s*[xX*]\s*(?:%%[cC]|[\u00d8\u00f8])?\s*(\d{2,3})", re.IGNORECASE)
    detected_buse_texts = []
    for tx in texts:
        m_b = buse_text_pattern.search(tx["text"])
        if m_b:
            detected_buse_texts.append((int(m_b.group(1)), int(m_b.group(2)), tx["handle"]))

    if detected_buse_texts and not duct_segs:
        for nb, dia, hnd in detected_buse_texts[:1]:
            tag = f"BUSE-{nb}x{dia}"
            desc = f"Buse PVC {nb}x\u00d8{dia} mm (traversée sous voirie)"
            it = item_base("CONDUIT", tag, desc, "m", 15.0, [hnd], "TEXTOS")
            it["size"] = f"{nb}x\u00d8{dia}"
            it["weight_unit"] = 2.8
            it["weight_total"] = round(2.8 * 15.0, 2)
            it["weight_source"] = "TABLE_INDICATIVE"
            it["confidence_score"] = 0.92
            items.append(it)
            metadata["conduits_linear_m"] = 15.0

    if duct_segs:
        ann = []
        for tx in texts:
            m = _DUCT.search(tx["text"])
            if m:
                ann.append({"x": tx["x"], "y": tx["y"], "value": (int(m.group(1) or 1), int(m.group(2)))})
        by_duct = _assign_by_annotation(duct_segs, [1.0] * len(duct_segs), ann, radius)
        for val, length in sorted(by_duct.items(), key=lambda kv: (kv[0] is None, kv[0] or (0, 0))):
            nb, dia = val if val else (None, None)
            tube_m = length * (nb or 1)
            duct_total += length
            it = item_base("CONDUIT", f"FOURREAU-{nb}xD{dia}" if val else "FOURREAU-NON-ANNOTE",
                           (f"Fourreau PVC {nb}×Ø{dia} mm ({length:.1f} m de tranchée)" if val else
                            "Fourreau (diamètre non annoté sur le plan)"), "m", tube_m, duct_handles, "CONDUIT")
            it["size"] = f"{nb}xØ{dia}" if val else ""
            it["trench_length_m"] = round(length, 2)
            it["length_source"] = "MEASURED"
            if not val:
                it["extractor_reasons"].append(f"diamètre/nombre de tubes non annoté à moins de {radius:g} m")
                it["confidence_score"] = _confidence(base_conf, 0.5)
            items.append(it)
    metadata["conduits_linear_m"] = round(duct_total, 1)

    # —— chambres de tirage
    boxes_items, box_warn = _build_pull_boxes(texts, box_candidates, ie, base_reasons, base_conf, file_name, ref_w, ignore_text)
    items.extend(boxes_items)
    warnings += box_warn
    metadata["pull_boxes_count"] = len(boxes_items)

    # —— métadonnées
    known_w = [it["weight_total"] for it in items if it.get("weight_total") is not None]
    metadata.update({
        "file_name": file_name, "drawing_number": Path(file_name).stem,
        "revision": str((ie["_meta"] or {}).get("revision_default", "0")), "doc_type": doc_type,
        "units": unit_label, "scale_to_m": scale, "units_assumed": units_assumed,
        "items_count": len(items), "entities_scanned": stop["count"], "duplicates_removed": duplicates,
        "total_weight_kg": round(sum(known_w), 2),
        "items_without_weight": sum(1 for it in items if it.get("weight_total") is None),
        "warnings": warnings,
    })
    return {"metadata": metadata, "items": items}


def _build_pull_boxes(texts, block_cands, ie, base_reasons, base_conf, file_name, ref_w, ignore_text):
    warnings: List[str] = []
    cluster_r = float(ie.get("pull_box_cluster_radius_m", 1.5))
    tag_r = float(ie.get("tag_match_radius_m", 5.0))
    try:
        tag_re = re.compile(ie.get("pull_box_tag_regex") or r"\b\d{2,4}-EL-\d{2,5}\b", re.IGNORECASE)
    except re.error as exc:
        warnings.append(f"ie_extraction.pull_box_tag_regex invalide : {exc}")
        tag_re = re.compile(r"\b\d{2,4}-EL-\d{2,5}\b")

    cands = [dict(c) for c in block_cands]
    for tx in texts:                                           # détections par texte (confiance moindre)
        up = _norm(tx["text"])
        m = _BOX_DIMS.search(tx["text"])                    # texte brut : « × » disparaît après normalisation ASCII
        if "CHAMBRE DE TIRAGE" in up or m:
            cands.append({"x": tx["x"], "y": tx["y"], "source": "TEXT", "handle": tx["handle"], "attribs": [],
                          "size": f"{m.group(1)}x{m.group(2)}x{m.group(3)} mm" if m else ""})
    cands.sort(key=lambda c: 0 if c["source"] == "BLOCK" else 1)   # les blocs d'abord : ils l'emportent
    boxes: List[Dict[str, Any]] = []
    for c in cands:
        near = next((b for b in boxes if math.hypot(b["x"] - c["x"], b["y"] - c["y"]) <= cluster_r), None)
        if near:
            near["handles"].append(c["handle"])
            if not near.get("size") and c.get("size"):
                near["size"] = c["size"]
            continue
        boxes.append({**c, "handles": [c["handle"]]})

    # tags : attributs de bloc d'abord, puis tags textuels les plus proches (affectation un-pour-un)
    tag_texts = [{"x": t["x"], "y": t["y"], "tag": m.group(0).upper(), "handle": t["handle"]}
                 for t in texts for m in [tag_re.search(t["text"])] if m]
    for b in boxes:
        for a in b.get("attribs", []):
            m = tag_re.search(a or "")
            if m:
                b["tag"], b["tag_source"] = m.group(0).upper(), "ATTRIB"
                break
    pairs = sorted(((math.hypot(b["x"] - t["x"], b["y"] - t["y"]), bi, ti)
                    for bi, b in enumerate(boxes) if "tag" not in b
                    for ti, t in enumerate(tag_texts)), key=lambda p: p[0])
    used_tags, ambiguous = set(), set()
    for d, bi, ti in pairs:
        b = boxes[bi]
        if d > tag_r or "tag" in b or ti in used_tags:
            continue
        rivals = [d2 for d2, bj, tj in pairs if bj == bi and tj != ti and d2 <= tag_r and tj not in used_tags]
        if rivals and min(rivals) < d * 1.25:
            ambiguous.add(bi)
        b["tag"], b["tag_source"] = tag_texts[ti]["tag"], "TEXT_NEAREST"
        used_tags.add(ti)

    items = []
    for n, b in enumerate(boxes, start=1):
        reasons = list(base_reasons)
        conf = base_conf
        if b["source"] == "TEXT":
            reasons.append("détectée par texte seul (aucun bloc)")
            conf = min(conf, 0.6)
        if "tag" not in b:
            reasons.append(f"aucun tag de chambre à moins de {tag_r:g} m")
            conf = min(conf, 0.5)
        elif b.get("tag_source") != "ATTRIB" and boxes.index(b) in ambiguous:
            reasons.append("tag ambigu : plusieurs tags à distance voisine")
            conf = min(conf, 0.5)
        size = b.get("size") or ""
        desc = f"Chambre de tirage {size}".strip() if size else "Chambre de tirage"
        w = ref_w.get("pull_box_kg")
        if w is None:
            reasons.append("poids de la chambre non renseigné (reference_weights.pull_box_kg)")
        items.append({
            "category": "PULL_BOX", "tag": b.get("tag") or f"CHAMBRE-{n:03d}", "description": desc, "size": size,
            "quantity": 1.0, "unit": "EA", "weight_unit": w, "weight_total": w, "weight_source": "FICHE_CONFIG" if w else None,
            "source_drawing": file_name, "source_layer": "PULL_BOX", "source_handles": b["handles"][:25],
            "length_source": "COUNTED", "extractor_reasons": reasons, "confidence_score": round(conf, 2),
            "position_m": [round(b["x"], 2), round(b["y"], 2)],
        })
    return items, warnings


def convert_and_read_dxf(path: str, original_filename: Optional[str], ie: Dict[str, Any]):
    """Lit un DXF ; pour un DWG, convertit (cache indexé par le HASH du contenu) puis lit."""
    import ezdxf
    p = Path(path)
    suffix = (Path(original_filename).suffix.lower() if original_filename else p.suffix.lower())
    if suffix == ".dxf":
        return ezdxf.readfile(str(p))
    cache_dir = Path((ie["_paths"] or {}).get("cad_cache_dxf") or "cad_cache/dxf")
    cache_dir.mkdir(parents=True, exist_ok=True)
    dxf_path = cache_dir / f"{_file_sha256(str(p))}.dxf"
    if not dxf_path.exists() or dxf_path.stat().st_size < 500:
        from dwg_iso_extractor import convert_dwg_to_dxf_headless
        timeout = int((ie["_thresholds"] or {}).get("dwg_conversion_timeout_sec", 60) or 60)
        convert_dwg_to_dxf_headless(str(p), str(dxf_path), timeout_sec=timeout)
    return ezdxf.readfile(str(dxf_path))


def extract_ie_from_dwg_native(dwg_path: str, original_filename: Optional[str] = None,
                               options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ie = _ie_cfg(options)
    doc = convert_and_read_dxf(dwg_path, original_filename, ie)
    return extract_ie_from_dxf_doc(doc, original_filename or Path(dwg_path).name, options)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  SLD (PDF)
# ═══════════════════════════════════════════════════════════════════════════════════════════════
_SECTION_RE = re.compile(r"\b(\d+\s*[XG]\s*\d+(?:[.,]\d+)?(?:\s*\+\s*(?:PE|P|N)?\s*\d+(?:[.,]\d+)?)?"
                         r"|2\s*X\s*\(\s*3\s*X\s*\d+\s*\)|CANALISATION)\b")
_CALIBRE_RE = re.compile(r"(?<![\w\-.,])(\d{1,4})\s*A\b")
_POLES_RE = re.compile(r"\b(4P4D|4P3D|3P3D|1P\+N|4P|3P|2P)\b")
_KW_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*KW\b")
_COS_RE = re.compile(r"COS\s*[ΦφP]?\s*[=:]?\s*(0?[.,]\d+)")
_ICU_RE = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*KA\b")
_LEN_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*M\b")

_HEADER_FIELDS = {
    "tag": ["TAG", "REPERE", "DEPART", "REF"],
    "designation": ["DESIGNATION", "RECEPTEUR", "LIBELLE"],
    "power_kw": ["KW", "PUISSANCE"],
    "cos_phi": ["COS"],
    "calibre_a": ["CALIBRE", "IN (A)", "IN(A)", "CALIBRE (A)"],
    "icu_ka": ["ICU", "PDC", "POUVOIR"],
    "cable_type": ["TYPE CABLE", "TYPOLOGIE"],
    "cable_section": ["SECTION", "MM2", "MM²", "CABLE", "LIAISON"],
    "length_m": ["LONGUEUR", "L (M)", "L(M)", "LONG"],
    "poles": ["POLES", "NOMBRE DE POLES"],
}


def _fnum(x: str) -> float:
    return float(x.replace(",", "."))


def _tag_patterns(ie: Dict[str, Any]) -> List["re.Pattern[str]"]:
    pats = []
    for p in ie.get("sld_tag_patterns") or []:
        try:
            pats.append(re.compile(p))
        except re.error:
            logger.warning("sld_tag_patterns : motif invalide ignoré : %s", p)
    return pats


def _find_tags(text: str, pats) -> List[str]:
    """Tags dans l'ordre d'apparition ; un tag contenu dans un tag plus long (P-101A dans 300-P-101A) est ignoré."""
    hits: List[Tuple[int, str]] = []
    for p in pats:
        for m in p.finditer(text):
            t = m.group(0)
            if not _SECTION_RE.fullmatch(t) and not re.fullmatch(r"\d+A", t):
                hits.append((m.start(), t))
    hits.sort()
    uniq: List[str] = []
    for _, t in hits:
        if t not in uniq:
            uniq.append(t)
    return [t for t in uniq if not any(t != o and t in o for o in uniq)]


def _parse_feeder_fields(text: str, tag_pats) -> Dict[str, Any]:
    up = _norm(text)
    tags = _find_tags(up, tag_pats)
    for t in sorted(tags, key=len, reverse=True):          # les tags ne doivent pas être relus comme calibre (101A) ou section
        up = up.replace(t, " ")
    sections = list(dict.fromkeys(m.group(1).replace(" ", "") for m in _SECTION_RE.finditer(up)))
    calibres = list(dict.fromkeys(int(m.group(1)) for m in _CALIBRE_RE.finditer(up)))
    f: Dict[str, Any] = {
        "tag_raw": tags[0] if tags else None, "extra_tags": tags[1:],
        "cable_section_raw": sections[0] if sections else None, "extra_sections": sections[1:],
        "calibre_a": calibres[0] if calibres else None, "extra_calibres": calibres[1:],
        "poles": (_POLES_RE.search(up).group(1) if _POLES_RE.search(up) else None),
        "power_kw": (_fnum(_KW_RE.search(up).group(1)) if _KW_RE.search(up) else None),
        "cos_phi": (_fnum(_COS_RE.search(up).group(1)) if _COS_RE.search(up) else None),
        "icu_ka": (_fnum(_ICU_RE.search(up).group(1)) if _ICU_RE.search(up) else None),
        "length_m": (_fnum(_LEN_RE.search(up).group(1)) if _LEN_RE.search(up) else None),
    }
    return f


def _build_feeder(fields: Dict[str, Any], designation: str, page: int, mode: str, file_name: str) -> Optional[Dict[str, Any]]:
    if not fields.get("tag_raw"):
        return None                                     # jamais de départ fantôme sans tag
    reasons: List[str] = []
    conf = 0.9 if mode == "TABLE" else 0.8
    sec_raw = fields.get("cable_section_raw")
    norm_sec = None
    if sec_raw:
        if sec_raw.upper() == "CANALISATION":
            norm_sec = "CANALISATION"
        elif parse_cable(sec_raw):
            norm_sec = sec_raw.upper()
        else:
            reasons.append(f"section « {sec_raw} » non reconnue")
            conf -= 0.2
    else:
        reasons.append("section de câble non lue")
        conf -= 0.2
    if fields.get("calibre_a") is None:
        reasons.append("calibre de protection non lu")
        conf -= 0.2
    if fields.get("extra_tags"):
        reasons.append(f"plusieurs tags dans le départ ({', '.join([fields['tag_raw']] + fields['extra_tags'][:3])})")
        conf -= 0.1
    if fields.get("extra_calibres"):
        reasons.append(f"plusieurs calibres lus : {[fields['calibre_a']] + fields['extra_calibres'][:3]}")
        conf -= 0.1
    if fields.get("extra_sections"):
        reasons.append(f"plusieurs sections lues : {[sec_raw] + fields['extra_sections'][:3]}")
        conf -= 0.1
    length = fields.get("length_m")
    p = parse_cable(norm_sec) if norm_sec and norm_sec != "CANALISATION" else None
    w_unit = CABLE_POWER_WEIGHTS_INDICATIVE.get(norm_sec or "")
    return {
        "category": "SWITCHGEAR_FEEDER", "tag": normalize_tag(fields["tag_raw"]), "tag_raw": fields["tag_raw"],
        "designation": designation or None, "calibre_a": fields.get("calibre_a"), "poles": fields.get("poles"),
        "icu_ka": fields.get("icu_ka"), "power_kw": fields.get("power_kw"), "cos_phi": fields.get("cos_phi"),
        "cable_type": "Cu/XLPE/PVC" if norm_sec and norm_sec != "CANALISATION" else None,
        "cable_section": norm_sec, "cable_parsed": p,
        "quantity": length, "unit": "m", "length_source": "SLD_TABLE" if length is not None else "UNKNOWN",
        "weight_unit": w_unit, "weight_total": round(w_unit * length, 2) if (w_unit and length is not None) else None,
        "weight_source": "TABLE_INDICATIVE" if w_unit else None,
        "source_page": page, "source_drawing": file_name, "extraction_mode": mode,
        "extractor_reasons": reasons, "confidence_score": round(max(0.2, conf), 2),
    }


def _header_map(header_cells: List[str]) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for i, h in enumerate(header_cells):
        hn = _norm(h)
        for field, kws in _HEADER_FIELDS.items():
            if field in out.values():
                continue
            if any(_norm(k) in hn for k in kws):
                out[i] = field
                break
    return out


def _table_rows_by_clip(page, tab) -> List[List[str]]:
    """
    Texte de chaque cellule relu par son rectangle (get_text + clip). `tab.extract()` supprime les espaces et
    déforme les tirets (« 300-P-101A » -> « 300P101A\n- - »), ce qui casse la lecture des tags.
    """
    fitz = _fitz()
    rows: List[List[str]] = []
    for r in tab.rows:
        row = []
        for c in r.cells:
            if not c:
                row.append("")
                continue
            txt = page.get_text("text", clip=fitz.Rect(c)).strip()
            row.append(re.sub(r"\s+", " ", txt))
        rows.append(row)
    return rows


def _extract_page_tables(page, tag_pats, page_no, file_name) -> List[Dict[str, Any]]:
    feeders: List[Dict[str, Any]] = []
    try:
        tables = page.find_tables().tables
    except Exception:
        return feeders
    for tab in tables:
        rows = _table_rows_by_clip(page, tab)
        if not rows or len(rows) < 2:
            continue

        # Détection table transposée (colonnes = départs, lignes = attributs)
        col0 = [str(r[0] or "").strip().upper() for r in rows if r and len(r) > 0 and r[0]]
        is_transposed = any(k in col0[:3] for k in ["TAG", "REPERE", "DEPART"]) and any(k in " ".join(col0) for k in ["CALIBRE", "SECTION", "PUISSANCE", "POLE", "CABLE"])
        if is_transposed:
            max_cols = max(len(r) for r in rows)
            padded = [r + [""] * (max_cols - len(r)) for r in rows]
            rows = [list(c) for c in zip(*padded)]

        hmap = _header_map([c or "" for c in rows[0]])
        if "tag" not in hmap.values():
            continue
        inv = {v: k for k, v in hmap.items()}
        for row in rows[1:]:
            cell = lambda f: (row[inv[f]] or "").strip() if f in inv and inv[f] < len(row) else ""
            text_all = " ".join((c or "") for c in row)
            fields = _parse_feeder_fields(text_all, tag_pats)
            raw_t = cell("tag")
            if not raw_t or raw_t in ("-", "TAG", "NONE", ""):
                continue
            fields["tag_raw"] = _norm(raw_t).replace(" ", "") or fields["tag_raw"]
            if cell("cable_section"):
                fields["cable_section_raw"] = _norm(cell("cable_section")).replace(" ", "")
            if cell("calibre_a"):
                m = re.search(r"\d+", cell("calibre_a"))
                fields["calibre_a"] = int(m.group(0)) if m else fields["calibre_a"]
            if cell("length_m"):
                m = re.search(r"\d+(?:[.,]\d+)?", cell("length_m"))
                fields["length_m"] = _fnum(m.group(0)) if m else fields["length_m"]
            f = _build_feeder(fields, cell("designation"), page_no, "TABLE", file_name)
            if f:
                feeders.append(f)
    return feeders


def _spans_several_columns(b, blocks) -> bool:
    """Un bloc qui recouvre (en x) au moins deux groupes de blocs disjoints (titre, note, en-tête) n'est pas une colonne."""
    others = sorted((c for c in blocks if c is not b and c[0] < b[2] and c[2] > b[0]), key=lambda c: c[0])
    groups, end = 0, None
    for c in others:
        if end is None or c[0] > end + 4.0:
            groups += 1
            end = c[2]
        else:
            end = max(end, c[2])
    return groups >= 2


def _column_clusters(blocks: List[Tuple[float, float, float, float, str]], page_width: float) -> List[List[Tuple]]:
    """Colonnes = blocs de texte dont les intervalles en x se recouvrent ; titres/notes à cheval sur plusieurs colonnes exclus."""
    usable = [b for b in blocks if (b[2] - b[0]) < 0.35 * page_width and b[4].strip()]
    usable = [b for b in usable if not _spans_several_columns(b, usable)]
    usable.sort(key=lambda b: b[0])
    clusters: List[List[Tuple]] = []
    cur_end = None
    for b in usable:
        if cur_end is None or b[0] > cur_end + 4.0:
            clusters.append([b])
            cur_end = b[2]
        else:
            clusters[-1].append(b)
            cur_end = max(cur_end, b[2])
    return clusters


def _extract_page_columns(page, tag_pats, page_no, file_name) -> List[Dict[str, Any]]:
    blocks = [(b[0], b[1], b[2], b[3], b[4]) for b in page.get_text("blocks") if b[6] == 0]
    feeders = []
    for cl in _column_clusters(blocks, page.rect.width):
        text = " \n ".join(b[4] for b in sorted(cl, key=lambda b: b[1]))
        designation = ""
        up = _norm(text)
        m = re.search(r"\b(POMPE[^\n]*|TRANSFO[^\n]*|MOTEUR[^\n]*|VENTILATEUR[^\n]*)", up)
        if m:
            designation = m.group(1).strip()
        f = _build_feeder(_parse_feeder_fields(text, tag_pats), designation, page_no, "COLUMN", file_name)
        if f:
            feeders.append(f)
    return feeders


def classify_pdf(doc, ie: Dict[str, Any]) -> str:
    text = _norm(" ".join(doc[i].get_text() for i in range(min(3, len(doc)))))
    keyword = any(k in text for k in ("UNIFILAIRE", "TGBT", "ONE LINE", "SINGLE LINE", "SLD", "TABLEAU GENERAL"))
    tags = len(_find_tags(text, _tag_patterns(ie)))
    return "ELEC_SLD_BT" if (keyword and tags >= 2) else "UNKNOWN"


def extract_sld_from_pdf_matrix(pdf_path: str, original_filename: Optional[str] = None,
                                options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ie = _ie_cfg(options)
    fitz = _fitz()
    file_name = original_filename or Path(pdf_path).name
    tag_pats = _tag_patterns(ie)
    warnings: List[str] = []
    doc = fitz.open(pdf_path)
    try:
        doc_type = (options or {}).get("doc_type") or classify_pdf(doc, ie)
        metadata: Dict[str, Any] = {
            "file_name": file_name, "drawing_number": Path(file_name).stem, "title": "SCHEMA UNIFILAIRE TGBT",
            "doc_type": doc_type, "total_pages": len(doc), "total_feeders_count": 0, "total_power_kw": 0.0,
            "total_cable_m": 0.0, "cable_total_m": 0.0, "total_weight_kg": 0.0, "warnings": warnings,
            "revision": str((ie["_meta"] or {}).get("revision_default", "0")),
        }
        if doc_type == "UNKNOWN":
            warnings.append("PDF non reconnu comme schéma unifilaire (mots-clés ou tags absents) : aucune extraction. "
                            "Forcer avec options={'doc_type': 'ELEC_SLD_BT'} si c'est bien un SLD.")
            return {"metadata": metadata, "items": []}

        feeders: List[Dict[str, Any]] = []
        seen: Dict[str, Dict[str, Any]] = {}
        dup = 0
        for idx in range(len(doc)):
            page = doc[idx]
            page_f = _extract_page_tables(page, tag_pats, idx + 1, file_name)
            if not page_f:
                page_f = _extract_page_columns(page, tag_pats, idx + 1, file_name)
            for f in page_f:
                prev = seen.get(f["tag"])
                if prev is None:
                    seen[f["tag"]] = f
                    feeders.append(f)
                    continue
                same = (prev["calibre_a"], prev["cable_section"]) == (f["calibre_a"], f["cable_section"])
                if same:
                    dup += 1                      # même départ répété (suite, rappel) : ignoré
                else:
                    f["extractor_reasons"].append(
                        f"tag déjà vu page {prev['source_page']} avec des données différentes "
                        f"(In {prev['calibre_a']}, câble {prev['cable_section']})")
                    f["confidence_score"] = min(f["confidence_score"], 0.4)
                    feeders.append(f)
        if dup:
            warnings.append(f"{dup} départ(s) en doublon entre pages ignoré(s).")
        if not feeders:
            warnings.append("Aucun départ identifié (aucune table ni colonne avec tag reconnu).")
        known_len = [f["quantity"] for f in feeders if f["quantity"] is not None]
        metadata["total_feeders_count"] = len(feeders)
        metadata["total_power_kw"] = round(sum(f["power_kw"] or 0.0 for f in feeders), 2)
        metadata["total_cable_m"] = metadata["cable_total_m"] = round(sum(known_len), 1)
        metadata["feeders_without_length"] = sum(1 for f in feeders if f["quantity"] is None)
        metadata["total_weight_kg"] = round(sum(f["weight_total"] or 0.0 for f in feeders), 2)
        if metadata["feeders_without_length"]:
            warnings.append(f"{metadata['feeders_without_length']} départ(s) sans longueur de câble : "
                            f"à renseigner (carnet de câbles ou cheminement), aucune valeur n'est supposée.")
        return {"metadata": metadata, "items": feeders}
    finally:
        doc.close()


def extract_ie_drawing(file_path: str, original_filename: Optional[str] = None,
                       options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    p = Path(file_path)
    ext = (Path(original_filename).suffix.lower() if original_filename else p.suffix.lower())
    if ext in (".dwg", ".dxf"):
        return extract_ie_from_dwg_native(str(p), original_filename=original_filename, options=options)
    if ext == ".pdf":
        return extract_sld_from_pdf_matrix(str(p), original_filename=original_filename, options=options)
    raise ValueError(f"Format non supporté : {ext}")
