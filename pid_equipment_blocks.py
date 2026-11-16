"""
pid_equipment_blocks.py : candidats "bloc" pour les équipements dessinés en géométrie libre
========================================================================================

Après dxf_pid_parser.py, ce script :
  1. regroupe la géométrie des calques d'équipement en équipements candidats (un cluster = un équipement dessiné)
  2. associe les tags d'équipement à ces clusters (un tag -> un cluster, un-à-un)
  3. applique un fallback multi-calques pour les équipements en ligne (ex: ST-001 crépines, CH-001 chillers, FL-001 filtres)
  4. détecte les clusters de même forme (même signature géométrique MD5) -> une seule définition de bloc, N insertions
  5. écrit equipment_candidates.json (statut, handles des entités, bloc proposé, champ de décision à remplir)
  6. produit equipment_preview.svg : rendu vectoriel natif haute fidélité (zéro dépendance Cairo)
  7. produit semantic_with_equipment.json enrichi du jumeau numérique

Usage :
    python pid_equipment_blocks.py <dossier_parseur> <sortie_dir>
    (dossier_parseur contient raw.json et semantic.json)
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sys
from collections import Counter, defaultdict
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Correction 1 : Import direct depuis dxf_pid_parser
from dxf_pid_parser import layer_role, load_config

logger = logging.getLogger("pid_equipment_blocks")

GEO = {"LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "ELLIPSE", "SPLINE"}
GAP = 12.0            # gap de fusion des traits d'un même équipement
MIN_ENTITIES = 8      # un cluster plus petit est un fragment / un symbole isolé
MIN_SIZE = 30.0       # ... sauf s'il est grand
TAG_MAX = 28.0        # distance max tag -> bbox du cluster (aligné buse 28.0)
# la tuyauterie n'est PAS exclue par calque (un strainer peut etre dessine sur PIPE) : le filtre de taille
# et le nombre d'entites ecartent le reseau de lignes
INLINE_EXCLUDED_ROLES = ("instrumentation", "valve", "text", "ignore", "titleblock")
INLINE_MAX_SIZE = 80.0        # un symbole en ligne plus grand que ceci n'est pas un symbole
INLINE_MAX_ENTITIES = 40
INLINE_MIN_ENTITIES = 3
INLINE_MIN_SIZE = 8.0
PANEL = 340


def _touch(a: List[float], b: List[float], g: float) -> bool:
    """Détermine si deux bboxes [xmin, ymin, xmax, ymax] se touchent avec une marge g."""
    return not (a[2] + g < b[0] or b[2] + g < a[0] or a[3] + g < b[1] or b[3] + g < a[1])


def _bbdist(p: List[float], bb: List[float]) -> float:
    """Distance euclidienne minimale entre un point et une bounding box."""
    return math.hypot(max(bb[0] - p[0], 0, p[0] - bb[2]), max(bb[1] - p[1], 0, p[1] - bb[3]))


def cluster(ents: List[Dict[str, Any]], gap: float) -> List[List[Dict[str, Any]]]:
    """Clustering Union-Find basé sur l'adjacence spatiale des bounding boxes."""
    if not ents:
        return []
    parent = list(range(len(ents)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(ents)):
        for j in range(i + 1, len(ents)):
            if _touch(ents[i]["bbox"], ents[j]["bbox"], gap):
                parent[find(i)] = find(j)

    out = defaultdict(list)
    for i, e in enumerate(ents):
        out[find(i)].append(e)
    return list(out.values())


def bbox_of(mem: List[Dict[str, Any]]) -> List[float]:
    """Calcule la bounding box englobante d'un groupe d'entités."""
    return [
        min(m["bbox"][0] for m in mem),
        min(m["bbox"][1] for m in mem),
        max(m["bbox"][2] for m in mem),
        max(m["bbox"][3] for m in mem)
    ]


def signature(mem: List[Dict[str, Any]], bb: List[float]) -> str:
    """
    Forme normalisée : mêmes entités aux mêmes positions relatives -> même hash MD5.
    Permet de regrouper les équipements de géométrie strictement identique.
    """
    ox, oy = bb[0], bb[1]
    items = sorted(
        (
            m["type"],
            round((m["bbox"][0] - ox) * 2) / 2,
            round((m["bbox"][1] - oy) * 2) / 2,
            round((m["bbox"][2] - ox) * 2) / 2,
            round((m["bbox"][3] - oy) * 2) / 2
        )
        for m in mem
    )
    return hashlib.md5(json.dumps(items).encode()).hexdigest()[:8]


def block_name(tags: List[str], idx: int) -> str:
    """Génère un nom de bloc standardisé pour l'export AutoCAD / Plant 3D."""
    if tags:
        base = re.sub(r"^\d{3}-", "", tags[0])
        base = re.sub(r"[/]?[A-Z]$", "", base)
        return "EQ_" + re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")
    return f"EQ_FORME_{idx}"


def analyse(folder: str | Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, List[int]], int, Dict[str, Any]]:
    """
    Analyse les fichiers raw.json et semantic.json du dossier spécifié.
    Applique le clustering d'équipements, le matching de tags et le fallback multi-calques.
    """
    p_folder = Path(folder)
    raw_path = p_folder / "raw.json"
    sem_path = p_folder / "semantic.json"

    if not raw_path.exists() or not sem_path.exists():
        raise FileNotFoundError(f"Dossier {folder} incomplet (raw.json et semantic.json requis)")

    # raw.json v2 contient aussi le paper space (cartouche, notes) : seuls les equipements du model space comptent
    raw = [r for r in json.loads(raw_path.read_text("utf-8"))["entities"] if r.get("space", "model") == "model"]
    sem = json.loads(sem_path.read_text("utf-8"))
    cfg = load_config(None)

    role = {r["id"]: layer_role(r["layer"], cfg) for r in raw}

    geo_all = [
        r for r in raw
        if r["type"] in GEO and r.get("bbox") and role[r["id"]] not in ("ignore", "titleblock")
    ]
    prim = [r for r in geo_all if role[r["id"]] == "equipment"]
    texts = [r for r in raw if r["type"] in ("TEXT", "MTEXT", "ATTRIB") and r.get("text")]

    # --- 1. Clusters sur le calque d'équipement
    cands: List[Dict[str, Any]] = []
    for mem in cluster(prim, GAP):
        bb = bbox_of(mem)
        size = max(bb[2] - bb[0], bb[3] - bb[1])
        if len(mem) >= MIN_ENTITIES or size >= MIN_SIZE:
            cands.append({"members": mem, "bbox": bb, "size": size})
    cands.sort(key=lambda c: (round(c["bbox"][1] / 50), c["bbox"][0]))
    fragments = len(prim) - sum(len(c["members"]) for c in cands)

    # --- 2. Tags d'équipement -> Cluster (un-à-un, le plus proche d'abord)
    eqs = [e for e in sem.get("elements", []) if e.get("kind") == "equipment"]
    tagpos: Dict[str, List[float]] = {}
    for e in eqs:
        t = next((x for x in texts if x["handle"] == e["handle"] and x["text"].upper() == e["tag"].upper()), None)
        tagpos[e["id"]] = t["pos"] if t and t.get("pos") else e.get("position", [0.0, 0.0])

    pairs = sorted(
        (_bbdist(tagpos[e["id"]], c["bbox"]), e["id"], i)
        for e in eqs for i, c in enumerate(cands)
        if c["size"] >= MIN_SIZE and _bbdist(tagpos[e["id"]], c["bbox"]) <= TAG_MAX
    )
    tag_of: Dict[str, int] = {}
    cand_tags: Dict[int, List[str]] = defaultdict(list)
    for d, eid, ci in pairs:
        if eid in tag_of or ci in cand_tags:
            continue
        tag_of[eid] = ci
        cand_tags[ci].append(next(x["tag"] for x in eqs if x["id"] == eid))

    # --- 3. Signatures MD5 -> Groupes de formes identiques
    for c in cands:
        c["sig"] = signature(c["members"], c["bbox"])
    groups: Dict[str, List[int]] = defaultdict(list)
    for i, c in enumerate(cands):
        groups[c["sig"]].append(i)

    out: List[Dict[str, Any]] = []
    used_entity_ids: Set[str] = set()

    for i, c in enumerate(cands):
        g = groups[c["sig"]]
        tags = sorted(cand_tags.get(i, []))
        n = len(g)
        ent_ids = [m["id"] for m in c["members"]]
        used_entity_ids.update(ent_ids)
        out.append({
            "id": f"EQC-{i + 1:02d}",
            "kind": "drawn_cluster" if c["size"] >= MIN_SIZE else "small_symbol",
            "tags": tags,
            "bbox": [round(v, 1) for v in c["bbox"]],
            "size": [round(c["bbox"][2] - c["bbox"][0], 1), round(c["bbox"][3] - c["bbox"][1], 1)],
            "layers": sorted({m["layer"] for m in c["members"]}),
            "composition": dict(Counter(m["type"] for m in c["members"])),
            "entity_ids": ent_ids,
            "handles": sorted({m["handle"] for m in c["members"]}),
            "shape_group": f"G-{c['sig']}",
            "same_shape_count": n,
            "same_shape_as": [f"EQC-{j + 1:02d}" for j in g if j != i],
            "proposed_block": block_name(tags or sum(([t for t in cand_tags.get(j, [])] for j in g), []), i + 1),
            "proposal": (
                f"même forme que {n - 1} autre(s) : 1 définition de bloc, {n} insertions"
                if n > 1 else "forme unique : 1 bloc, 1 insertion"
            ),
            "status": (
                ("tag_matched" if tags else "no_tag_nearby")
                if c["size"] >= MIN_SIZE else "small_symbol_not_an_equipment_candidate"
            ),
            "user_decision": None,
        })

    # --- 4. Correction 3 : Fallback multi-calques pour les équipements en ligne
    # Si un tag équipement (ex: 201-ST-001 strainer, CH-001 chiller/chemical, FL-001 filtre)
    # n'a pas de géométrie sur EQT/equipment, inspecter les calques process/piping/autres
    # dans un rayon de tolérance (15-25mm) pour lui associer le symbole en ligne correspondant
    base = len(out)
    k = 0
    for e in eqs:
        if e["id"] in tag_of:
            continue
        k += 1
        p = tagpos[e["id"]]

        # Géométrie proche non encore assignée sur les calques du plan (process, piping, autres)
        # Correction : on exclut la tuyauterie, les vannes, les instruments et les gros traits (reseau de
        # lignes), sinon le "symbole" absorbait tout le voisinage (30 a 100 entites, 6 calques, jusqu'a
        # 388 unites de haut) et rattachait l'equipement a des lignes qui ne sont pas les siennes.
        near_geo = [
            g for g in geo_all
            if g["id"] not in used_entity_ids and _bbdist(p, g["bbox"]) <= TAG_MAX
            and role[g["id"]] not in INLINE_EXCLUDED_ROLES
            and max(g["bbox"][2] - g["bbox"][0], g["bbox"][3] - g["bbox"][1]) <= INLINE_MAX_SIZE
        ]
        best_cl = None
        if near_geo:
            best_cl = min(cluster(near_geo, GAP), key=lambda cl: _bbdist(p, bbox_of(cl)))
            bbc = bbox_of(best_cl)
            if len(best_cl) > INLINE_MAX_ENTITIES or max(bbc[2] - bbc[0], bbc[3] - bbc[1]) > INLINE_MAX_SIZE:
                best_cl = None            # amas trop grand pour etre un symbole : tag orphelin, a confirmer a la main
            elif len(best_cl) < INLINE_MIN_ENTITIES and max(bbc[2] - bbc[0], bbc[3] - bbc[1]) < INLINE_MIN_SIZE:
                best_cl = None            # un trait isole de quelques unites n'est pas un symbole d'equipement

        if best_cl:
            bb = bbox_of(best_cl)
            sig = signature(best_cl, bb)
            inline_ent_ids = [m["id"] for m in best_cl]
            used_entity_ids.update(inline_ent_ids)

            c_id = f"EQC-{base + k:02d}"
            p_blk = block_name([e["tag"]], base + k)
            out.append({
                "id": c_id,
                "kind": "inline_equipment",
                "tags": [e["tag"]],
                "bbox": [round(v, 1) for v in bb],
                "size": [round(bb[2] - bb[0], 1), round(bb[3] - bb[1], 1)],
                "layers": sorted({m["layer"] for m in best_cl}),
                "composition": dict(Counter(m["type"] for m in best_cl)),
                "entity_ids": inline_ent_ids,
                "handles": sorted({m["handle"] for m in best_cl}),
                "shape_group": f"G-{sig}",
                "same_shape_count": 1,
                "same_shape_as": [],
                "proposed_block": p_blk,
                "proposal": (
                    f"Équipement en ligne ({e['tag']}) rattaché à {len(best_cl)} entité(s) "
                    f"sur calque(s) {', '.join(sorted({m['layer'] for m in best_cl}))}"
                ),
                "status": "inline_symbol_to_confirm",
                "user_decision": None,        # jamais auto-confirme : a valider via equipment_review.html
            })
            # Mettre à jour l'élément dans semantic
            e["bbox"] = [round(v, 1) for v in bb]
            e["candidate_id"] = c_id
            e["shape_group"] = f"G-{sig}"
            e["proposed_block"] = p_blk
            e["inline"] = True
            e["link_source"] = "inline_equipment_geometry"
            e["confidence"] = 0.5
            e["review_status"] = "to_confirm"

        else:
            # Aucun symbole géométrique à proximité : tag orphelin à confirmer
            near = [g for g in geo_all if _bbdist(p, g["bbox"]) <= TAG_MAX]
            c_id = f"EQC-{base + k:02d}"
            p_blk = block_name([e["tag"]], base + k)
            cand_bbox = [round(p[0] - TAG_MAX, 1), round(p[1] - TAG_MAX, 1), round(p[0] + TAG_MAX, 1), round(p[1] + TAG_MAX, 1)]
            out.append({
                "id": c_id,
                "kind": "tag_without_equipment_layer_geometry",
                "tags": [e["tag"]],
                "tag_position": p,
                "bbox": cand_bbox,
                "proposed_block": p_blk,
                "nearby_layers": dict(Counter(g["layer"] for g in near)),
                "entity_ids": [g["id"] for g in near],
                "status": "symbol_to_confirm",
                "proposal": (
                    f"aucun équipement dessiné à moins de {TAG_MAX:.0f} unités : "
                    "le symbole est peut-être sur un autre calque ou absent"
                ),
                "user_decision": None,
            })

    # --- 5. Tag multi-unités (ex. 201-PP-001A/B/C/D) cohérent avec le groupe ?
    for c in out:
        for t in c["tags"]:
            if re.search(r"\d[A-Z](?:/[A-Z])+$", t):
                units = len(re.findall(r"[A-Z]", t.split("-")[-1]))
                c["multi_unit_tag"] = {"tag": t, "units": units}
    for e in eqs:
        m = re.search(r"-(\d{2,4})([A-Z](?:/[A-Z])+)$", e["tag"])
        if m:
            prefix = e["tag"][: e["tag"].rfind(m.group(1))] + m.group(1)
            sibs = [c for c in out if any(t.startswith(prefix + "/") for t in c["tags"])]
            units = m.group(2).count("/") + 1
            for c in out:
                if e["tag"] in c["tags"]:
                    c["multi_unit_check"] = (
                        f"{e['tag']} annonce {units} unités ; {len(sibs)} équipement(s) "
                        f"{prefix}/x dessiné(s)" + (" -> cohérent" if len(sibs) == units else " -> À VÉRIFIER")
                    )
    for c in out:
        c.pop("multi_unit_tag", None)

    # Enrichissement de semantic.json avec les données d'équipements validés
    for e in eqs:
        match_c = next((c for c in out if e["tag"] in c["tags"]), None)
        if match_c:
            e["bbox"] = match_c["bbox"]
            e["candidate_id"] = match_c["id"]
            if "shape_group" in match_c:
                e["shape_group"] = match_c["shape_group"]
            if "proposed_block" in match_c:
                e["proposed_block"] = match_c["proposed_block"]
            else:
                p_blk = block_name([e["tag"]], int(match_c["id"].split("-")[-1]) if "-" in match_c["id"] else 1)
                e["proposed_block"] = p_blk
                match_c["proposed_block"] = p_blk
            if match_c["kind"] == "drawn_cluster":
                e["link_source"] = "equipment_geometry"
                e["confidence"] = 0.98

    return raw, geo_all, texts, out, groups, fragments, sem


# ---------------------------------------------------------------- Aperçu SVG / Rendu
def _panel(c: Dict[str, Any], geo_all: List[Dict[str, Any]], texts: List[Dict[str, Any]], ox: int, oy: int) -> str:
    """Génère un panneau SVG interactif pour un équipement candidat."""
    bb = c["bbox"]
    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    half = max(bb[2] - bb[0], bb[3] - bb[1]) / 2 * 1.6 + 25
    half = max(half, 10.0)
    x0, y0, x1, y1 = cx - half, cy - half, cx + half, cy + half
    sc = (PANEL - 20) / (2 * half)
    X = lambda x: ox + 10 + (x - x0) * sc
    Y = lambda y: oy + 52 + (y1 - y) * sc - 10
    tag_only = c["kind"] == "tag_without_equipment_layer_geometry"
    hi = set() if tag_only else set(c["entity_ids"])

    s = [
        f'<rect x="{ox}" y="{oy}" width="{PANEL}" height="{PANEL + 40}" fill="white" stroke="#bbb"/>',
        f'<clipPath id="cl{ox}_{oy}"><rect x="{ox}" y="{oy + 42}" width="{PANEL}" height="{PANEL - 2}"/></clipPath>',
        f'<g clip-path="url(#cl{ox}_{oy})">'
    ]
    for g in geo_all:
        b = g.get("bbox")
        if not b or b[2] < x0 or b[0] > x1 or b[3] < y0 or b[1] > y1:
            continue
        col, w = ("#d1242f", 1.4) if g["id"] in hi else ("#aab", 0.8)
        if g["type"] in ("LINE", "LWPOLYLINE", "POLYLINE") and g.get("pts"):
            pts = " ".join(f"{X(a):.1f},{Y(b_):.1f}" for a, b_ in g["pts"])
            s.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="{w}"/>')
        elif g["type"] == "CIRCLE" and g.get("radius"):
            s.append(
                f'<circle cx="{X(g["pos"][0]):.1f}" cy="{Y(g["pos"][1]):.1f}" '
                f'r="{g["radius"] * sc:.1f}" fill="none" stroke="{col}" stroke-width="{w}"/>'
            )
        else:
            s.append(
                f'<ellipse cx="{X((b[0] + b[2]) / 2):.1f}" cy="{Y((b[1] + b[3]) / 2):.1f}" '
                f'rx="{max((b[2] - b[0]) * sc / 2, 0.5):.1f}" ry="{max((b[3] - b[1]) * sc / 2, 0.5):.1f}" '
                f'fill="none" stroke="{col}" stroke-width="{w}"/>'
            )
    for t in texts:
        if not t.get("pos"):
            continue
        px, py = t["pos"]
        if x0 <= px <= x1 and y0 <= py <= y1:
            mine = t["text"].upper() in [tag.upper() for tag in c["tags"]]
            s.append(
                f'<text x="{X(px):.1f}" y="{Y(py):.1f}" font-size="{10 if mine else 8}" '
                f'fill="{"#0550ae" if mine else "#777"}" font-weight="{"bold" if mine else "normal"}">'
                f'{escape(t["text"][:20])}</text>'
            )
    if tag_only:
        tp = c.get("tag_position", [cx, cy])
        s.append(
            f'<circle cx="{X(tp[0] + 18):.1f}" cy="{Y(tp[1]):.1f}" r="26" '
            f'fill="none" stroke="#d1242f" stroke-width="1.5" stroke-dasharray="4 3"/>'
        )
    s.append("</g>")

    tag = ", ".join(c["tags"]) or "(sans tag)"
    sg = c.get("shape_group", "G-forme")[2:]
    cnt = c.get("same_shape_count", 1)
    if c["kind"] == "tag_without_equipment_layer_geometry":
        sub = "symbole à confirmer"
    elif c["kind"] == "inline_equipment":
        sub = f"équipement en ligne ({sg})"
    elif c["kind"] == "small_symbol":
        sub = f"groupe {sg} x{cnt} - petit symbole"
    else:
        sub = f"groupe {sg} x{cnt}"

    s.append(f'<text x="{ox + 8}" y="{oy + 17}" font-size="12" font-weight="bold">{escape(c["id"])} {escape(tag[:34])}</text>')
    s.append(f'<text x="{ox + 8}" y="{oy + 33}" font-size="11" fill="#555">{escape(sub)}</text>')
    return "\n".join(s)


def render_sheet(cands: List[Dict[str, Any]], geo_all: List[Dict[str, Any]], texts: List[Dict[str, Any]], path: Path | str, cols: int = 4) -> None:
    """
    Correction 2 : Écriture native du SVG interactif equipment_preview.svg.
    Supporte un fallback doux sans crash si un fichier PNG est demandé.
    """
    path_obj = Path(path)
    rows = math.ceil(len(cands) / cols) if cands else 1
    W, H = cols * (PANEL + 10) + 10, rows * (PANEL + 50) + 10
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="Arial, sans-serif">',
        f'<rect width="{W}" height="{H}" fill="#f3f4f6"/>'
    ]
    for i, c in enumerate(cands):
        parts.append(_panel(c, geo_all, texts, 10 + (i % cols) * (PANEL + 10), 10 + (i // cols) * (PANEL + 50)))
    parts.append("</svg>")
    svg_content = "\n".join(parts)

    # 1. Écriture obligatoire du SVG natif (Chromium / Electron / Web)
    svg_target = path_obj.with_suffix(".svg")
    svg_target.write_text(svg_content, encoding="utf-8")
    logger.info("Planche vectorielle SVG sauvegardée : %s", svg_target)

    # 2. Si PNG demandé, tentative avec fallback doux
    if path_obj.suffix.lower() == ".png":
        try:
            import cairosvg
            cairosvg.svg2png(bytestring=svg_content.encode("utf-8"), write_to=str(path_obj))
            logger.info("Rendu PNG sauvegardé via CairoSVG : %s", path_obj)
        except Exception:
            # Fallback doux : pas de crash si CairoSVG / GTK est absent sous Windows
            logger.info("CairoSVG non disponible sous Windows. Planche SVG vectorielle disponible : %s", svg_target)


REVIEW_HTML = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revue des equipements - P&ID</title>
<style>
:root{--bg:#f3f4f6;--card:#fff;--tx:#1f2328;--mut:#656d76;--bd:#d0d7de;--ok:#1a7f37;--ko:#cf222e;--mg:#0969da}
@media (prefers-color-scheme: dark){:root{--bg:#0d1117;--card:#161b22;--tx:#e6edf3;--mut:#8b949e;--bd:#30363d}}
*{box-sizing:border-box}body{margin:0;font:14px/1.4 Arial,Helvetica,sans-serif;background:var(--bg);color:var(--tx)}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--bd);padding:10px 16px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
header h1{font-size:16px;margin:0 8px 0 0}.pill{background:var(--bg);border:1px solid var(--bd);border-radius:12px;padding:2px 10px}
button,select,input{font:inherit;color:inherit}
button{background:var(--card);border:1px solid var(--bd);border-radius:6px;padding:5px 10px;cursor:pointer}
button.primary{background:var(--mg);border-color:var(--mg);color:#fff}
button.on.ok{background:var(--ok);border-color:var(--ok);color:#fff}button.on.ko{background:var(--ko);border-color:var(--ko);color:#fff}button.on.mg{background:var(--mg);border-color:var(--mg);color:#fff}
.help{max-width:1500px;margin:12px auto 0;padding:0 16px;color:var(--mut)}
main{max-width:1500px;margin:0 auto;padding:12px 16px 60px;display:grid;grid-template-columns:repeat(auto-fill,minmax(520px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;overflow:hidden}
.card.d-confirm{border-color:var(--ok)}.card.d-not_equipment{border-color:var(--ko)}.card.d-merge{border-color:var(--mg)}
.ch{padding:8px 12px;display:flex;justify-content:space-between;gap:8px;border-bottom:1px solid var(--bd)}
.ch b{font-size:14px}.sub{color:var(--mut);font-size:12px}
svg.cv{display:block;width:100%;height:330px;background:#fff;touch-action:none;cursor:crosshair}
.ctl{padding:8px 12px;display:grid;gap:7px}.row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.row input[type=text]{flex:1;min-width:120px;padding:4px 6px;border:1px solid var(--bd);border-radius:6px;background:var(--card)}
select{padding:4px;border:1px solid var(--bd);border-radius:6px;background:var(--card)}
.err{color:var(--ko);font-size:12px}.info{color:var(--mut);font-size:12px}
</style></head><body>
<header><h1>Revue des equipements</h1>
<span class="pill" id="cnt"></span>
<select id="flt"><option value="all">Tous</option><option value="todo">A traiter</option><option value="done">Traites</option></select>
<span style="flex:1"></span>
<button id="copy">Copier le JSON</button><button class="primary" id="exp">Exporter equipment_review.json</button></header>
<p class="help">Pour chaque equipement dessine sans bloc : <b>selectionnez ses traits</b> (glisser un rectangle = ajouter les traits entierement dedans, clic = un trait), verifiez le tag et le type, puis <b>Confirmer</b>,
<b>Pas un equipement</b> ou <b>Fusionner</b> avec un autre candidat. Rouge = trait selectionne. Le fichier exporte est relu par
<code>dxf_pid_parser.py --equipment-review equipment_review.json</code>.</p>
<main id="main"></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const KEY='eqreview_'+D.md5;
const TYPES=["","pompe","strainer / filtre","ballon / capacite","echangeur","compresseur","reservoir","package / skid","autre"];
let S={};try{S=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
const mode={};
D.candidates.forEach(c=>{if(!S[c.id])S[c.id]={decision:null,tag:c.tags[0]||'',type:c.suggest_type||'',sel:c.sel0.slice(),merge:'',note:''};mode[c.id]='add';});
function save(){try{localStorage.setItem(KEY,JSON.stringify(S))}catch(e){}}
const esc=t=>String(t).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
function bboxOf(c){const sel=new Set(S[c.id].sel);let b=null;for(const s of c.shapes){if(!sel.has(s.i))continue;b=b?[Math.min(b[0],s.b[0]),Math.min(b[1],s.b[1]),Math.max(b[2],s.b[2]),Math.max(b[3],s.b[3])]:s.b.slice();}return b;}
function svgOf(c){const [x0,y0,x1,y1]=c.crop,w=x1-x0,h=y1-y0,fs=w/38,sel=new Set(S[c.id].sel);
let o=`<svg class="cv" data-c="${c.id}" viewBox="${x0} ${-y1} ${w} ${h}" preserveAspectRatio="xMidYMid meet">`;
for(const s of c.shapes){const on=sel.has(s.i),st=on?'#d1242f':'#8b93a1',sw=on?2:1;const a=`data-i="${s.i}" fill="none" stroke="${st}" stroke-width="${sw}" vector-effect="non-scaling-stroke"`;
if(s.t==='p'){let pts='';for(let k=0;k<s.p.length;k+=2)pts+=s.p[k]+','+(-s.p[k+1])+' ';o+=`<polyline points="${pts}" ${a}/>`;}
else if(s.t==='c')o+=`<circle cx="${s.p[0]}" cy="${-s.p[1]}" r="${s.p[2]}" ${a}/>`;
else o+=`<ellipse cx="${(s.b[0]+s.b[2])/2}" cy="${-(s.b[1]+s.b[3])/2}" rx="${Math.max((s.b[2]-s.b[0])/2,.2)}" ry="${Math.max((s.b[3]-s.b[1])/2,.2)}" ${a}/>`;}
for(const t of c.texts){const mine=c.tags.includes(t.s.toUpperCase());o+=`<text x="${t.x}" y="${-t.y}" font-size="${fs}" fill="${mine?'#0550ae':'#57606a'}" font-weight="${mine?'bold':'normal'}" pointer-events="none">${esc(t.s)}</text>`;}
o+=`<rect class="rb" x="0" y="0" width="0" height="0" fill="rgba(9,105,218,.15)" stroke="#0969da" stroke-dasharray="4 3" vector-effect="non-scaling-stroke" pointer-events="none"/></svg>`;return o;}
function render(c){const st=S[c.id],el=document.getElementById('card-'+c.id);const b=bboxOf(c);
el.className='card'+(st.decision?' d-'+st.decision:'');
const others=D.candidates.filter(o=>o.id!==c.id).map(o=>`<option value="${o.id}"${st.merge===o.id?' selected':''}>${o.id} ${esc(S[o.id].tag||o.tags.join(', '))}</option>`).join('');
el.innerHTML=`<div class="ch"><div><b>${c.id} ${esc(c.tags.join(', ')||'(sans tag)')}</b><div class="sub">${esc(c.label)}</div></div><div class="sub">${esc(c.same.length?'meme forme : '+c.same.join(', '):'')}</div></div>`+svgOf(c)+
`<div class="ctl"><div class="row"><button data-act="add" class="${mode[c.id]==='add'?'on mg':''}">+ Ajouter</button><button data-act="rem" class="${mode[c.id]==='rem'?'on ko':''}">- Retirer</button><button data-act="clr">Tout effacer</button>
<span class="info">${st.sel.length} trait(s) ${b?'| bbox '+b.map(v=>v.toFixed(0)).join(', ')+' ('+(b[2]-b[0]).toFixed(0)+' x '+(b[3]-b[1]).toFixed(0)+')':''}</span></div>
<div class="row"><input type="text" data-f="tag" placeholder="Tag (ex. 201-PP-001/A)" value="${esc(st.tag)}"><select data-f="type">${TYPES.map(t=>`<option${st.type===t?' selected':''}>${t}</option>`).join('')}</select></div>
<div class="row"><button data-d="confirm" class="${st.decision==='confirm'?'on ok':''}">Confirmer</button><button data-d="not_equipment" class="${st.decision==='not_equipment'?'on ko':''}">Pas un equipement</button><button data-d="merge" class="${st.decision==='merge'?'on mg':''}">Fusionner avec</button>
<select data-f="merge" ${st.decision==='merge'?'':'style="display:none"'}><option value="">- choisir -</option>${others}</select></div>
<div class="row"><input type="text" data-f="note" placeholder="Note (facultatif)" value="${esc(st.note)}">${c.same.length?'<button data-act="grp">Meme decision pour le groupe</button>':''}</div>
<div class="err" id="err-${c.id}"></div></div>`;bind(c);count();}
function pt(svg,e){const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(svg.getScreenCTM().inverse());}
function bind(c){const el=document.getElementById('card-'+c.id),st=S[c.id],svg=el.querySelector('svg.cv'),rb=svg.querySelector('.rb');let a=null,a0=null;
svg.addEventListener('pointerdown',e=>{svg.setPointerCapture(e.pointerId);a=pt(svg,e);a0={x:e.clientX,y:e.clientY};});
svg.addEventListener('pointermove',e=>{if(!a)return;const q=pt(svg,e);rb.setAttribute('x',Math.min(a.x,q.x));rb.setAttribute('y',Math.min(a.y,q.y));rb.setAttribute('width',Math.abs(q.x-a.x));rb.setAttribute('height',Math.abs(q.y-a.y));});
svg.addEventListener('pointerup',e=>{if(!a)return;const q=pt(svg,e),drag=Math.hypot(e.clientX-a0.x,e.clientY-a0.y)>5;let hit=[];
if(drag){const X0=Math.min(a.x,q.x),X1=Math.max(a.x,q.x),Y0=-Math.max(-a.y,-q.y),Y1=-Math.min(-a.y,-q.y);
const ymin=Math.min(-a.y,-q.y),ymax=Math.max(-a.y,-q.y);hit=c.shapes.filter(s=>s.b[0]>=X0&&s.b[2]<=X1&&s.b[1]>=ymin&&s.b[3]<=ymax).map(s=>s.i);}
else{const r=(c.crop[2]-c.crop[0])*.012,X=q.x,Y=-q.y;const m=c.shapes.filter(s=>s.b[2]>=X-r&&s.b[0]<=X+r&&s.b[3]>=Y-r&&s.b[1]<=Y+r);
m.sort((u,v)=>(u.b[2]-u.b[0])*(u.b[3]-u.b[1])-(v.b[2]-v.b[0])*(v.b[3]-v.b[1]));hit=m.slice(0,1).map(s=>s.i);}
const set=new Set(st.sel);hit.forEach(i=>mode[c.id]==='rem'?set.delete(i):set.add(i));st.sel=[...set];a=null;save();render(c);});
el.querySelectorAll('[data-act]').forEach(b=>b.onclick=()=>{const k=b.dataset.act;
if(k==='add'||k==='rem'){mode[c.id]=k;render(c);}else if(k==='clr'){st.sel=[];save();render(c);}
else if(k==='grp'){c.same.forEach(id=>{const o=S[id];o.decision=st.decision;o.type=st.type;save();render(D.candidates.find(x=>x.id===id));});render(c);}});
el.querySelectorAll('[data-d]').forEach(b=>b.onclick=()=>{st.decision=st.decision===b.dataset.d?null:b.dataset.d;save();render(c);});
el.querySelectorAll('[data-f]').forEach(i=>i.onchange=()=>{st[i.dataset.f]=i.value;save();if(i.dataset.f==='merge')render(c);});}
function count(){const n=D.candidates.filter(c=>S[c.id].decision).length;document.getElementById('cnt').textContent=n+' / '+D.candidates.length+' traites';filt();}
function filt(){const f=document.getElementById('flt').value;D.candidates.forEach(c=>{const d=!!S[c.id].decision;const e=document.getElementById('card-'+c.id);if(e)e.style.display=(f==='all'||(f==='todo'&&!d)||(f==='done'&&d))?'':'none';});}
function build(){const out=[],errs=[];for(const c of D.candidates){const st=S[c.id];if(!st.decision)continue;const b=bboxOf(c);let e='';
if(st.decision==='confirm'&&(!st.tag.trim()||!b))e='Confirmer : il faut un tag et au moins un trait selectionne.';
if(st.decision==='not_equipment'&&!(st.tag.trim()||c.tags.length))e="Pas un equipement : indiquez le tag concerne.";
if(st.decision==='merge'&&(!st.merge||!b))e='Fusionner : choisissez la cible et selectionnez des traits.';
document.getElementById('err-'+c.id).textContent=e;if(e){errs.push(c.id);continue;}
out.push({candidate_id:c.id,decision:st.decision,tag:(st.tag||c.tags[0]||'').trim(),equipment_type:st.type||null,bbox:b?b.map(v=>Math.round(v*1000)/1000):null,
entity_ids:st.sel,handles:[...new Set(st.sel.map(i=>i.split('#')[0]))],merge_with:st.decision==='merge'?st.merge:null,note:st.note||'',shape_group:c.group});}
return {out,errs};}
function json(){const {out,errs}=build();if(errs.length){alert('A corriger : '+errs.join(', '));return null;}
return JSON.stringify({schema_version:'1.0',dxf_md5:D.md5,equipment:out},null,1);}
document.getElementById('exp').onclick=()=>{const j=json();if(!j)return;const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([j],{type:'application/json'}));a.download='equipment_review.json';a.click();};
document.getElementById('copy').onclick=async()=>{const j=json();if(!j)return;try{await navigator.clipboard.writeText(j);alert('JSON copie');}catch(e){prompt('Copiez le JSON :',j);}};
document.getElementById('flt').onchange=filt;
const main=document.getElementById('main');D.candidates.forEach(c=>{const d=document.createElement('div');d.id='card-'+c.id;main.appendChild(d);render(c);});
</script></body></html>
"""


def _shape(g):
    b = [round(v, 1) for v in g["bbox"]]
    if g["type"] in ("LINE", "LWPOLYLINE", "POLYLINE") and g.get("pts"):
        flat = [round(c, 1) for pt in g["pts"] for c in pt]
        return {"i": g["id"], "t": "p", "p": flat, "b": b}
    if g["type"] == "CIRCLE":
        return {"i": g["id"], "t": "c", "p": [round(g["pos"][0], 1), round(g["pos"][1], 1), round(g["radius"], 1)], "b": b}
    return {"i": g["id"], "t": "e", "b": b}


TYPE_HINT = {"PP": "pompe", "ST": "strainer / filtre", "TK": "reservoir", "E": "echangeur",
             "V": "ballon / capacite", "K": "compresseur"}


def render_review_html(cands, geo_all, texts, path, md5):
    data = []
    for c in cands:
        if c["kind"] == "tag_without_equipment_layer_geometry":
            px, py = c["tag_position"]
            crop = [px - 70, py - 70, px + 70, py + 70]
        else:
            bb = c["bbox"]
            cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
            half = max(bb[2] - bb[0], bb[3] - bb[1]) / 2 * 1.6 + 25
            crop = [cx - half, cy - half, cx + half, cy + half]
        shapes = [_shape(g) for g in geo_all
                  if not (g["bbox"][2] < crop[0] or g["bbox"][0] > crop[2] or g["bbox"][3] < crop[1] or g["bbox"][1] > crop[3])][:900]
        tx = [{"x": round(t["pos"][0], 1), "y": round(t["pos"][1], 1), "s": t["text"][:24]} for t in texts
              if crop[0] <= t["pos"][0] <= crop[2] and crop[1] <= t["pos"][1] <= crop[3]][:80]
        m = re.search(r"-([A-Z]{1,2})-\d", (c["tags"][0] if c["tags"] else ""))
        label = {"drawn_cluster": "equipement dessine sans bloc", "small_symbol": "petit symbole (a qualifier)",
                 "tag_without_equipment_layer_geometry": "tag sans equipement sur les calques d'equipement : "
                                                         "selectionnez les traits du symbole",
                 "inline_equipment": "symbole en ligne detecte autour du tag : a verifier"}[c["kind"]]
        data.append({"id": c["id"], "kind": c["kind"], "tags": c["tags"], "label": label,
                     "group": c.get("shape_group"), "same": c.get("same_shape_as", []),
                     "crop": [round(v, 1) for v in crop], "shapes": shapes, "texts": tx,
                     "sel0": c["entity_ids"] if c["kind"] != "tag_without_equipment_layer_geometry" else [],
                     "suggest_type": TYPE_HINT.get(m.group(1), "") if m else ""})
    blob = json.dumps({"md5": md5, "candidates": data}, ensure_ascii=False).replace("</", "<\\/")
    Path(path).write_text(REVIEW_HTML.replace("__DATA__", blob), encoding="utf-8")


def run_equipment_blocks(folder: str | Path, out_dir: Optional[str | Path] = None) -> Dict[str, Any]:
    """Exécute l'analyse et génère tous les fichiers requis."""
    in_folder = Path(folder)
    target_dir = Path(out_dir) if out_dir else in_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    raw, geo_all, texts, cands, groups, frag, sem = analyse(in_folder)

    rep = {
        "schema_version": "1.0",
        "fragments_ignored": frag,
        "candidates": cands,
        "shape_groups": {f"G-{k}": [f"EQC-{i + 1:02d}" for i in v] for k, v in groups.items() if len(v) > 1}
    }
    (target_dir / "equipment_candidates.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), "utf-8")

    sem["equipment_candidates"] = cands
    (target_dir / "semantic_with_equipment.json").write_text(json.dumps(sem, ensure_ascii=False, indent=1), "utf-8")

    render_sheet(cands, geo_all, texts, target_dir / "equipment_preview.svg")
    # Outil de revue humaine : l'operateur confirme / corrige / fusionne les equipements dessines sans bloc
    render_review_html(cands, geo_all, texts, target_dir / "equipment_review.html",
                       (sem.get("source") or {}).get("dxf_md5", ""))
    # Tente aussi d'écrire le PNG avec fallback doux
    render_sheet(cands, geo_all, texts, target_dir / "equipment_preview.png")

    logger.info(
        "%d candidats, %d groupes de formes identiques, %d fragments ignorés",
        len(cands), len(rep["shape_groups"]), frag
    )
    return rep


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    folder_arg, out_dir_arg = sys.argv[1], Path(sys.argv[2])
    run_equipment_blocks(folder_arg, out_dir_arg)
