"""
pid_schematic.py
================
Générateur et reconstructeur simplifié de schémas P&ID vectoriels interactifs (SVG).
Conforme aux standards ISA-5.1, ASME et ISO 10628.

Fournit :
  - render_schematic(sem: dict, out_svg_path: Optional[str | Path] = None) -> str
  - Palette étendue de fluides de procédés et utilités
  - Tracé orienté des vannes (nœud papillon)
  - Bulles d'instruments ISA-5.1
  - Boîtes d'équipements arrondies
  - Annotations interactives pour surbrillance bidirectionnelle
"""

import html
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------------------------------------------------------
# Dictionnaire étendu de fluides industriels & utilités (ASME / ISO 10628)
# -----------------------------------------------------------------------------
FLUID_COLORS: Dict[str, str] = {
    "P": "#d97706",    # Process (Hydrocarbure / Principal) - Ambre
    "G": "#ca8a04",    # Gaz Procédé - Jaune doré
    "L": "#2563eb",    # Liquide général - Bleu roi
    "W": "#0284c7",    # Eau brute / Utilité - Bleu ciel
    "FG": "#ea580c",   # Fuel Gas - Orange vif
    "FW": "#dc2626",   # Fire Water (Eau incendie) - Rouge vif
    "IA": "#7c3aed",   # Instrument Air (Air instrument) - Violet
    "F": "#b91c1c",    # Flare (Torche) - Rouge sombre
    "D": "#78350f",    # Drain / Purge - Brun
    "V": "#475569",    # Vent / Évent - Ardoise
    "LP": "#059669",   # Low Pressure (Basse Pression) - Émeraude
    "MP": "#0d9488",   # Medium Pressure (Moyenne Pression) - Sarcelle
    "HP": "#4f46e5",   # High Pressure (Haute Pression) - Indigo
    "DC": "#9333ea",   # Drain Chimique / Condensat - Pourpre
    "CW": "#06b6d4",   # Cooling Water (Eau de refroidissement) - Cyan
    "N2": "#64748b",   # Azote (Nitrogen) - Gris ardoise
}

FLUID_LABELS: Dict[str, str] = {
    "P": "Process",
    "G": "Gaz Procédé",
    "L": "Liquide",
    "W": "Eau",
    "FG": "Fuel Gas",
    "FW": "Fire Water",
    "IA": "Instrument Air",
    "F": "Torche (Flare)",
    "D": "Drain / Purge",
    "V": "Évent (Vent)",
    "LP": "Basse Pression (LP)",
    "MP": "Moyenne Pression (MP)",
    "HP": "Haute Pression (HP)",
    "DC": "Drain Chimique (DC)",
    "CW": "Eau Refroid. (CW)",
    "N2": "Azote (N2)",
}

DEFAULT_FLUID_COLOR = "#3b82f6"


# -----------------------------------------------------------------------------
# Utilitaires géométriques
# -----------------------------------------------------------------------------
def _pt_seg_dist_sq(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """Distance au carré entre un point (px, py) et un segment [p1, p2]."""
    dx = x2 - x1
    dy = y2 - y1
    l2 = dx * dx + dy * dy
    if l2 == 0.0:
        return (px - x1) ** 2 + (py - y1) ** 2
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return (px - proj_x) ** 2 + (py - proj_y) ** 2


def _find_nearest_segment_angle(
    px: float, py: float, segments: List[Tuple[float, float, float, float]]
) -> float:
    """Trouve l'angle (en degrés) du segment le plus proche du point (px, py)."""
    if not segments:
        return 0.0
    best_dist = float("inf")
    best_angle = 0.0
    for x1, y1, x2, y2 in segments:
        d = _pt_seg_dist_sq(px, py, x1, y1, x2, y2)
        if d < best_dist:
            best_dist = d
            best_angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
    return best_angle


def _neutral_fallback_svg(message: str = "Aucun élément P&ID à afficher") -> str:
    """Génère un SVG neutre et propre en cas de données manquantes ou invalides."""
    esc_msg = html.escape(message)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 600" width="100%" height="100%" '
        'font-family="Segoe UI, -apple-system, sans-serif">\n'
        '  <rect width="1000" height="600" fill="#f8fafc"/>\n'
        '  <g id="grid" stroke="#e2e8f0" stroke-width="1" opacity="0.6">\n'
        '    <path d="M 0 150 L 1000 150 M 0 300 L 1000 300 M 0 450 L 1000 450 '
        'M 250 0 L 250 600 M 500 0 L 500 600 M 750 0 L 750 600"/>\n'
        '  </g>\n'
        f'  <text x="500" y="280" text-anchor="middle" font-size="16" font-weight="600" fill="#64748b">{esc_msg}</text>\n'
        '  <text x="500" y="310" text-anchor="middle" font-size="12" fill="#94a3b8">Le schéma apparaîtra dès la détection vectorielle.</text>\n'
        '  <g id="annotations-panel">\n'
        '    <rect y="520" width="1000" height="80" fill="#0f172a"/>\n'
        '    <text x="30" y="565" font-size="13" font-weight="bold" fill="#f8fafc">AR-KAN P&amp;ID ANALYZER</text>\n'
        '    <text x="30" y="585" font-size="11" fill="#94a3b8">Schéma Simplifié (Stand-by)</text>\n'
        '  </g>\n'
        '</svg>'
    )


def _resolve_equipment_info(
    eq_tag: str,
    eq_bbox: List[float],
    lines: List[Dict[str, Any]],
    elements: List[Dict[str, Any]],
    loops: Any
) -> Tuple[List[str], List[str], str, List[str], List[str]]:
    """
    Résout pour un équipement donné :
      1. Les tuyauteries connectées réelles (amont / aval calculées avec la tolérance buse 28 u).
      2. Les boucles ISA associées (loops, instruments reliés).
      3. Le fluide principal du procédé.
    """
    bx1, by1, bx2, by2 = eq_bbox if (eq_bbox and len(eq_bbox) >= 4) else (0.0, 0.0, 0.0, 0.0)
    has_bbox = (bx2 > bx1 or by2 > by1)
    margin = max(abs(bx2 - bx1), abs(by2 - by1)) * 0.4 + 30.0
    nozzle_tol = 28.0

    eq_lines: List[str] = []
    amont_lines: List[str] = []
    aval_lines: List[str] = []
    eq_fluids: List[str] = []

    el_by_id = {e.get("id"): e.get("tag") for e in elements if e.get("id")}
    matching_el = next((e for e in elements if e.get("tag") == eq_tag or e.get("id") == eq_tag), None)
    el_connected_line_ids = set(matching_el.get("connected_lines", [])) if matching_el else set()

    # 1. Résolution des lignes de tuyauteries connectées (amont / aval)
    for l in lines:
        l_tag = l.get("tag_raw") or l.get("line_number") or l.get("tag") or l.get("id") or ""
        if not l_tag:
            continue

        l_id = l.get("id") or ""
        from_eq = str(l.get("from_equipment") or "")
        to_eq = str(l.get("to_equipment") or "")
        connects = l.get("connects") or []
        if isinstance(connects, str):
            connects = [connects]

        connects_tags = {el_by_id.get(cid, cid) for cid in connects}

        is_connected = False
        direction = None

        if eq_tag and (eq_tag == to_eq or eq_tag in to_eq):
            is_connected = True
            direction = "amont"
        elif eq_tag and (eq_tag == from_eq or eq_tag in from_eq):
            is_connected = True
            direction = "aval"
        elif l_id in el_connected_line_ids or (eq_tag and eq_tag in connects_tags):
            is_connected = True

        # Tolérance buse géométrique (28 u)
        if has_bbox:
            segs = l.get("segments") or []
            if segs:
                p_start = segs[0][0]
                p_end = segs[-1][1]
                d_start = math.hypot(max(bx1 - p_start[0], 0, p_start[0] - bx2),
                                     max(by1 - p_start[1], 0, p_start[1] - by2))
                d_end = math.hypot(max(bx1 - p_end[0], 0, p_end[0] - bx2),
                                   max(by1 - p_end[1], 0, p_end[1] - by2))

                if d_start <= nozzle_tol or d_end <= nozzle_tol:
                    is_connected = True
                    if direction is None:
                        if d_end <= nozzle_tol and d_end < d_start:
                            direction = "amont"
                        elif d_start <= nozzle_tol and d_start < d_end:
                            direction = "aval"
                        else:
                            direction = "amont" if d_end <= nozzle_tol else "aval"

        if is_connected:
            if l_tag not in eq_lines:
                eq_lines.append(l_tag)
            if direction == "amont" and l_tag not in amont_lines:
                amont_lines.append(l_tag)
            elif direction == "aval" and l_tag not in aval_lines:
                aval_lines.append(l_tag)

            fl = (l.get("fluid") or "").strip().upper()
            if fl:
                eq_fluids.append(fl)

    for lt in eq_lines:
        if lt not in amont_lines and lt not in aval_lines:
            if len(amont_lines) <= len(aval_lines):
                amont_lines.append(lt)
            else:
                aval_lines.append(lt)

    # 2. Résolution des boucles ISA associées
    eq_loops: List[str] = []

    # Depuis le conteneur 'loops'
    if isinstance(loops, dict):
        for l_key, l_val in loops.items():
            s_val = str(l_val)
            if (eq_tag and eq_tag in s_val) or any(ln in s_val for ln in eq_lines):
                eq_loops.append(str(l_key))
    elif isinstance(loops, list):
        for lp in loops:
            if isinstance(lp, dict):
                s_lp = str(lp)
                if (eq_tag and eq_tag in s_lp) or any(ln in s_lp for ln in eq_lines):
                    lid = lp.get("loop") or lp.get("id") or lp.get("tag")
                    if lid:
                        eq_loops.append(str(lid))
            elif isinstance(lp, str):
                if (eq_tag and lp in eq_tag) or any(lp in ln for ln in eq_lines):
                    eq_loops.append(lp)

    # Depuis les instruments associés
    for el in elements:
        if el.get("kind") != "instrument":
            continue
        itag = el.get("tag") or ""
        parts = el.get("parts") or {}
        loop_candidate = parts.get("loop") or el.get("loop") or ""
        if not loop_candidate and "-" in itag:
            chunks = itag.split("-")
            for c in reversed(chunks):
                if any(ch.isdigit() for ch in c):
                    loop_candidate = c
                    break

        is_assoc = False
        inst_line = el.get("line") or el.get("on_line") or ""
        if inst_line and any(inst_line == ln or inst_line in ln or ln in inst_line for ln in eq_lines):
            is_assoc = True

        pos = el.get("position")
        if not is_assoc and pos and len(pos) >= 2 and eq_bbox:
            px, py = float(pos[0]), float(pos[1])
            if bx1 - margin * 2.5 <= px <= bx2 + margin * 2.5 and by1 - margin * 2.5 <= py <= by2 + margin * 2.5:
                is_assoc = True

        if loop_candidate and (loop_candidate in eq_tag or any(loop_candidate in ln for ln in eq_lines)):
            is_assoc = True

        if is_assoc and loop_candidate and str(loop_candidate) not in eq_loops:
            eq_loops.append(str(loop_candidate))

    # Séquence de repli si aucune boucle explicite trouvée
    if not eq_loops:
        for ln in eq_lines:
            digits = re.findall(r'\b\d{2,4}\b', ln)
            if digits:
                eq_loops.append(digits[0])
                break
        if not eq_loops and eq_tag:
            digits = re.findall(r'\b\d{2,4}\b', eq_tag)
            if digits:
                eq_loops.append(digits[0])

    # 3. Résolution du fluide principal
    main_fluid = "P"
    if eq_fluids:
        main_fluid = Counter(eq_fluids).most_common(1)[0][0]
    else:
        found_f = False
        for f_key in FLUID_COLORS.keys():
            if any(f"-{f_key}-" in ln.upper() or ln.upper().startswith(f"{f_key}-") for ln in eq_lines):
                main_fluid = f_key
                found_f = True
                break
        if not found_f:
            for f_key in FLUID_COLORS.keys():
                if f"-{f_key}-" in eq_tag.upper() or eq_tag.upper().startswith(f"{f_key}-"):
                    main_fluid = f_key
                    break

    return eq_lines, eq_loops, main_fluid, amont_lines, aval_lines


# -----------------------------------------------------------------------------
# Fonction Principale de Rendu Schématique
# -----------------------------------------------------------------------------
def render_schematic(sem: Any, out_svg_path: Optional[str | Path] = None) -> str:
    """
    Génère un schéma P&ID simplifié vectoriel (SVG) à partir des données sémantiques.

    Paramètres :
      sem : dictionnaire sémantique P&ID contenant lines, elements, equipment_candidates, etc.
      out_svg_path : chemin de fichier optionnel pour enregistrer le SVG sur disque.

    Retourne :
      Chaîne contenant le code XML complet du SVG.
    """
    if not isinstance(sem, dict):
        svg_str = _neutral_fallback_svg("Données sémantiques invalides")
        if out_svg_path:
            Path(out_svg_path).write_text(svg_str, encoding="utf-8")
        return svg_str

    lines: List[Dict[str, Any]] = sem.get("lines") or []
    elements: List[Dict[str, Any]] = sem.get("elements") or []
    candidates: List[Dict[str, Any]] = sem.get("equipment_candidates") or []
    titleblock: Dict[str, Any] = sem.get("titleblock") or {}
    loops: Any = sem.get("loops") or []
    general_notes: List[Any] = sem.get("general_notes") or []
    warnings: List[Any] = sem.get("warnings") or []

    # Vérification du contenu
    if not lines and not elements and not candidates:
        svg_str = _neutral_fallback_svg("Aucun élément ou tuyauterie détecté dans ce plan")
        if out_svg_path:
            Path(out_svg_path).write_text(svg_str, encoding="utf-8")
        return svg_str

    # Délégation au moteur Smart Filtered Vector P&ID (Toile dynamique, étiquettes dédoublonnées)
    try:
        from pid_schematic_engine import PidSchematicEngine
        stem = titleblock.get("drawing_number") or ""
        svg_content = PidSchematicEngine().render_semantic(sem_data=sem, drawing_stem=stem)
        if out_svg_path:
            p = Path(out_svg_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(svg_content, encoding="utf-8", errors="replace")
        return svg_content
    except Exception as e_smart:
        logger.warning("Délégation Smart Schematic non aboutie, repli local : %s", e_smart)

    # 1. Calcul de l'emprise globale (Bounding Box) en coordonnées CAO
    pts: List[Tuple[float, float]] = []

    for l in lines:
        for seg in l.get("segments") or []:
            if len(seg) >= 2:
                pts.append((float(seg[0][0]), float(seg[0][1])))
                pts.append((float(seg[1][0]), float(seg[1][1])))

    for el in elements:
        pos = el.get("position")
        if pos and len(pos) >= 2:
            pts.append((float(pos[0]), float(pos[1])))
        bb = el.get("bbox") or el.get("box")
        if bb and len(bb) >= 4:
            pts.append((float(bb[0]), float(bb[1])))
            pts.append((float(bb[2]), float(bb[3])))

    for c in candidates:
        bb = c.get("bbox")
        if bb and len(bb) >= 4:
            pts.append((float(bb[0]), float(bb[1])))
            pts.append((float(bb[2]), float(bb[3])))

    if not pts:
        min_x, min_y, max_x, max_y = 0.0, 0.0, 1000.0, 600.0
    else:
        min_x = min(p[0] for p in pts)
        max_x = max(p[0] for p in pts)
        min_y = min(p[1] for p in pts)
        max_y = max(p[1] for p in pts)

    dx = max_x - min_x
    dy = max_y - min_y
    if dx <= 0.0:
        dx = 1000.0
    if dy <= 0.0:
        dy = 600.0

    # Marges modèle (6%)
    min_x -= dx * 0.06
    max_x += dx * 0.06
    min_y -= dy * 0.06
    max_y += dy * 0.06
    span_x = max_x - min_x
    span_y = max_y - min_y

    # Dimensions du Canvas SVG
    canvas_w = 1600.0
    aspect = span_x / span_y if span_y > 0 else 1.6
    main_h = max(min(canvas_w / aspect, 1200.0), 700.0)
    panel_h = 160.0
    total_h = main_h + panel_h

    # Transformation d'échelle uniforme (AutoCAD Y montant -> SVG Y descendant)
    margin_x = 40.0
    margin_y = 40.0
    usable_w = canvas_w - 2 * margin_x
    usable_h = main_h - 2 * margin_y

    scale = min(usable_w / span_x, usable_h / span_y)
    offset_x = margin_x + (usable_w - span_x * scale) / 2.0
    offset_y = margin_y + (usable_h - span_y * scale) / 2.0

    def to_svg(x: float, y: float) -> Tuple[float, float]:
        sx = offset_x + (x - min_x) * scale
        sy = offset_y + (max_y - y) * scale
        return sx, sy

    # 2. Collecte des segments pour l'orientation des vannes
    svg_segments: List[Tuple[float, float, float, float]] = []
    fluids_present: set[str] = set()

    for l in lines:
        fl = (l.get("fluid") or "").upper().strip()
        if fl:
            fluids_present.add(fl)
        for seg in l.get("segments") or []:
            if len(seg) >= 2:
                sx1, sy1 = to_svg(float(seg[0][0]), float(seg[0][1]))
                sx2, sy2 = to_svg(float(seg[1][0]), float(seg[1][1]))
                svg_segments.append((sx1, sy1, sx2, sy2))

    # Initialisation du code SVG
    svg_lines: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {canvas_w:.1f} {total_h:.1f}" '
        f'width="100%" height="100%" font-family="Segoe UI, -apple-system, BlinkMacSystemFont, Roboto, sans-serif">\n'
        f'  <!-- Fond du plan schématique -->\n'
        f'  <rect width="{canvas_w:.1f}" height="{main_h:.1f}" fill="#ffffff"/>\n'
        f'  <defs>\n'
        f'    <filter id="pid-shadow" x="-10%" y="-10%" width="125%" height="125%">\n'
        f'      <feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity="0.08"/>\n'
        f'    </filter>\n'
        f'  </defs>\n'
        f'  <g id="schematic-grid" stroke="#f1f5f9" stroke-width="1">\n'
    ]

    # Grille subtile d'arrière-plan
    step = 80.0
    gx = 0.0
    while gx < canvas_w:
        svg_lines.append(f'    <line x1="{gx:.1f}" y1="0" x2="{gx:.1f}" y2="{main_h:.1f}"/>\n')
        gx += step
    gy = 0.0
    while gy < main_h:
        svg_lines.append(f'    <line x1="0" y1="{gy:.1f}" x2="{canvas_w:.1f}" y2="{gy:.1f}"/>\n')
        gy += step
    svg_lines.append('  </g>\n\n')

    # 3. Tracé des Lignes de Tuyauterie
    svg_lines.append('  <!-- Lignes de Tuyauterie Procédé / Utilités -->\n  <g id="piping-lines">\n')

    for idx, l in enumerate(lines):
        line_id = l.get("id") or f"L-{idx+1:03d}"
        tag_raw = (l.get("tag_raw") or "").strip()
        fluid = (l.get("fluid") or "").upper().strip()

        # Si le fluide n'est pas explicite, extraction par motif usuel
        if not fluid:
            for f_key in FLUID_COLORS.keys():
                if f"-{f_key}-" in tag_raw.upper() or tag_raw.upper().startswith(f"{f_key}-"):
                    fluid = f_key
                    break

        col = FLUID_COLORS.get(fluid, DEFAULT_FLUID_COLOR)
        segs = l.get("segments") or []
        if not segs:
            continue

        longest_len = 0.0
        best_mid = (0.0, 0.0)
        best_ang = 0.0

        for seg in segs:
            if len(seg) < 2:
                continue
            sx1, sy1 = to_svg(float(seg[0][0]), float(seg[0][1]))
            sx2, sy2 = to_svg(float(seg[1][0]), float(seg[1][1]))
            svg_lines.append(
                f'    <line x1="{sx1:.1f}" y1="{sy1:.1f}" x2="{sx2:.1f}" y2="{sy2:.1f}" '
                f'stroke="{col}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>\n'
            )
            slen = math.hypot(sx2 - sx1, sy2 - sy1)
            if slen > longest_len:
                longest_len = slen
                best_mid = ((sx1 + sx2) / 2.0, (sy1 + sy2) / 2.0)
                best_ang = math.degrees(math.atan2(sy2 - sy1, sx2 - sx1))

        # Étiquette de tuyauterie sur boîte opaque : UNIQUEMENT pour les tags explicites (pas les identifiants internes L-xxxx)
        is_internal_id = (not tag_raw) or bool(re.match(r"^L-[\dA-Za-z#_-]+$", tag_raw))
        if tag_raw and not is_internal_id and longest_len > 35.0:
            ang = best_ang
            if ang > 90.0:
                ang -= 180.0
            elif ang < -90.0:
                ang += 180.0

            tw = max(len(tag_raw) * 6.8 + 14.0, 48.0)
            th = 17.0
            mx_c, my_c = best_mid
            svg_lines.append(
                f'    <g class="pid-schematic-element" data-tag="{html.escape(tag_raw)}" data-kind="line" '
                f'data-cx="{mx_c:.1f}" data-cy="{my_c:.1f}" style="cursor:pointer;" '
                f'transform="translate({mx_c:.1f}, {my_c:.1f}) rotate({ang:.1f})">\n'
                f'      <rect x="{-tw/2:.1f}" y="{-th/2:.1f}" width="{tw:.1f}" height="{th:.1f}" rx="3" '
                f'fill="#ffffff" stroke="{col}" stroke-width="1.2" opacity="0.96"/>\n'
                f'      <text x="0" y="3.5" text-anchor="middle" font-size="8.5" font-weight="600" '
                f'fill="#0f172a">{html.escape(tag_raw)}</text>\n'
                f'    </g>\n'
            )

    svg_lines.append('  </g>\n\n')

    # 4. Tracé des Équipements (Boîtes Arrondies avec Bulles Normatives)
    svg_lines.append('  <!-- Équipements Principaux (Boîtes Arrondies avec Bulles Normatives) -->\n  <g id="equipments">\n')

    rendered_eq_tags = set()

    # Rendu des candidats d'équipements détectés
    for c in candidates:
        cand_id = c.get("id") or "EQ"
        tags = c.get("tags") or []
        tag = tags[0] if tags else (c.get("proposed_block") or cand_id)
        rendered_eq_tags.add(tag)

        # Forme épurée sans affichage de "EQ_FORME_x"
        is_generic_forme = bool(re.match(r"^EQ_FORME_\d+$", tag)) or tag.startswith("EQC-") or tag == "EQ"
        display_tag = "" if is_generic_forme else tag

        bb = c.get("bbox") or [0, 0, 0, 0]
        cx_m = (bb[0] + bb[2]) / 2.0
        cy_m = (bb[1] + bb[3]) / 2.0
        scx, scy = to_svg(cx_m, cy_m)

        bw = max(abs(bb[2] - bb[0]) * scale, 95.0)
        bh = max(abs(bb[3] - bb[1]) * scale, 64.0)
        bw = min(bw, 220.0)
        bh = min(bh, 140.0)

        block_title = c.get("proposed_block") or "Équipement"
        if re.match(r"^EQ_FORME_\d+$", block_title):
            block_title = "Équipement"

        conf_val = c.get("confidence", 0.95)
        if isinstance(conf_val, float) and conf_val <= 1.0:
            conf_str = f"{int(conf_val * 100)}%"
        else:
            conf_str = f"{conf_val}%" if str(conf_val).isdigit() else str(conf_val)

        eq_lines, eq_loops, main_fluid, amont_lines, aval_lines = _resolve_equipment_info(tag, bb, lines, elements, loops)
        loop_str = f"Loop {eq_loops[0]}" if eq_loops else "Loop N/A"
        nb_conn = len(eq_lines)
        nb_in = len(amont_lines)
        nb_out = len(aval_lines)
        if nb_in > 0 or nb_out > 0:
            lines_str = f"{nb_conn} Ligne{'s' if nb_conn != 1 else ''} ({nb_in} amont / {nb_out} aval)"
        else:
            lines_str = f"{nb_conn} Ligne{'s' if nb_conn != 1 else ''}"
        bubble_text = f"{main_fluid} • {lines_str} • {loop_str}"
        bubble_w = max(len(bubble_text) * 5.8 + 18.0, 95.0)

        lines_attr = html.escape(",".join(eq_lines))
        amont_attr = html.escape(",".join(amont_lines))
        aval_attr = html.escape(",".join(aval_lines))
        loops_attr = html.escape(",".join(eq_loops))
        bbox_attr = html.escape(json.dumps([round(float(v), 2) for v in bb]))

        if display_tag:
            header_svg = (
                f'      <path d="M {-bw/2:.1f} {-bh/2 + 22:.1f} L {bw/2:.1f} {-bh/2 + 22:.1f}" stroke="#e2e8f0" stroke-width="1.2"/>\n'
                f'      <rect x="{-bw/2:.1f}" y="{-bh/2:.1f}" width="{bw:.1f}" height="22" rx="8" ry="8" fill="#e2e8f0" opacity="0.65"/>\n'
                f'      <text x="0" y="{-bh/2 + 15:.1f}" text-anchor="middle" font-size="10.5" font-weight="700" '
                f'fill="#0f172a">{html.escape(display_tag)}</text>\n'
                f'      <text x="0" y="8" text-anchor="middle" font-size="9" font-weight="500" fill="#64748b">{html.escape(block_title)}</text>\n'
            )
        else:
            header_svg = (
                f'      <text x="0" y="2" text-anchor="middle" font-size="9.5" font-weight="600" fill="#64748b">{html.escape(block_title)}</text>\n'
            )

        svg_lines.append(
            f'    <g class="pid-schematic-element pid-equipment-group" data-tag="{html.escape(tag)}" data-kind="equipment" '
            f'data-type="{html.escape(block_title)}" data-fluid="{html.escape(main_fluid)}" data-lines="{lines_attr}" '
            f'data-amont="{amont_attr}" data-aval="{aval_attr}" '
            f'data-loops="{loops_attr}" data-bbox="{bbox_attr}" data-confidence="{conf_str}" '
            f'data-cx="{scx:.1f}" data-cy="{scy:.1f}" style="cursor:pointer;" '
            f'transform="translate({scx:.1f}, {scy:.1f})">\n'
            f'      <!-- Bulle d\'informations normative compacte -->\n'
            f'      <g class="eq-info-bubble" transform="translate(0, {-bh/2 - 14:.1f})" style="cursor:pointer;">\n'
            f'        <rect x="{-bubble_w/2:.1f}" y="-9" width="{bubble_w:.1f}" height="18" rx="9" fill="#0f172a" stroke="#38bdf8" stroke-width="1.2" opacity="0.95"/>\n'
            f'        <text x="0" y="3.5" text-anchor="middle" font-size="8" font-weight="600" fill="#f8fafc">{html.escape(bubble_text)}</text>\n'
            f'      </g>\n'
            f'      <!-- Corps rectangulaire de l\'équipement -->\n'
            f'      <rect x="{-bw/2:.1f}" y="{-bh/2:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="8" ry="8" '
            f'fill="#f8fafc" stroke="#334155" stroke-width="2.2" filter="url(#pid-shadow)"/>\n'
            f'{header_svg}'
            f'    </g>\n'
        )

    # Rendu des équipements dans elements non encore couverts
    for el in elements:
        if el.get("kind") != "equipment":
            continue
        tag = el.get("tag") or el.get("id") or "EQ"
        if tag in rendered_eq_tags:
            continue
        rendered_eq_tags.add(tag)

        # Forme épurée sans affichage de "EQ_FORME_x"
        is_generic_forme = bool(re.match(r"^EQ_FORME_\d+$", tag)) or tag.startswith("E-") or tag == "EQ"
        display_tag = "" if is_generic_forme else tag

        pos = el.get("position")
        bb = el.get("bbox") or el.get("box") or [0, 0, 0, 0]
        if pos:
            scx, scy = to_svg(float(pos[0]), float(pos[1]))
        elif bb and (bb[2] > bb[0] or bb[3] > bb[1]):
            scx, scy = to_svg((bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0)
        else:
            continue

        bw, bh = 100.0, 68.0
        eq_type = el.get("type") or "Équipement"
        if re.match(r"^EQ_FORME_\d+$", eq_type):
            eq_type = "Équipement"

        conf_val = el.get("confidence", 0.90)
        if isinstance(conf_val, float) and conf_val <= 1.0:
            conf_str = f"{int(conf_val * 100)}%"
        else:
            conf_str = f"{conf_val}%" if str(conf_val).isdigit() else str(conf_val)

        eq_lines, eq_loops, main_fluid, amont_lines, aval_lines = _resolve_equipment_info(tag, bb, lines, elements, loops)
        loop_str = f"Loop {eq_loops[0]}" if eq_loops else "Loop N/A"
        nb_conn = len(eq_lines)
        nb_in = len(amont_lines)
        nb_out = len(aval_lines)
        if nb_in > 0 or nb_out > 0:
            lines_str = f"{nb_conn} Ligne{'s' if nb_conn != 1 else ''} ({nb_in} amont / {nb_out} aval)"
        else:
            lines_str = f"{nb_conn} Ligne{'s' if nb_conn != 1 else ''}"
        bubble_text = f"{main_fluid} • {lines_str} • {loop_str}"
        bubble_w = max(len(bubble_text) * 5.8 + 18.0, 95.0)

        lines_attr = html.escape(",".join(eq_lines))
        amont_attr = html.escape(",".join(amont_lines))
        aval_attr = html.escape(",".join(aval_lines))
        loops_attr = html.escape(",".join(eq_loops))
        bbox_attr = html.escape(json.dumps([round(float(v), 2) for v in bb]))

        if display_tag:
            header_svg = (
                f'      <rect x="{-bw/2:.1f}" y="{-bh/2:.1f}" width="{bw:.1f}" height="22" rx="8" ry="8" fill="#e2e8f0" opacity="0.65"/>\n'
                f'      <text x="0" y="{-bh/2 + 15:.1f}" text-anchor="middle" font-size="10.5" font-weight="700" '
                f'fill="#0f172a">{html.escape(display_tag)}</text>\n'
                f'      <text x="0" y="8" text-anchor="middle" font-size="9" fill="#64748b">{html.escape(eq_type)}</text>\n'
            )
        else:
            header_svg = (
                f'      <text x="0" y="2" text-anchor="middle" font-size="9.5" font-weight="600" fill="#64748b">{html.escape(eq_type)}</text>\n'
            )

        svg_lines.append(
            f'    <g class="pid-schematic-element pid-equipment-group" data-tag="{html.escape(tag)}" data-kind="equipment" '
            f'data-type="{html.escape(eq_type)}" data-fluid="{html.escape(main_fluid)}" data-lines="{lines_attr}" '
            f'data-amont="{amont_attr}" data-aval="{aval_attr}" '
            f'data-loops="{loops_attr}" data-bbox="{bbox_attr}" data-confidence="{conf_str}" '
            f'data-cx="{scx:.1f}" data-cy="{scy:.1f}" style="cursor:pointer;" '
            f'transform="translate({scx:.1f}, {scy:.1f})">\n'
            f'      <!-- Bulle d\'informations normative compacte -->\n'
            f'      <g class="eq-info-bubble" transform="translate(0, {-bh/2 - 14:.1f})" style="cursor:pointer;">\n'
            f'        <rect x="{-bubble_w/2:.1f}" y="-9" width="{bubble_w:.1f}" height="18" rx="9" fill="#0f172a" stroke="#38bdf8" stroke-width="1.2" opacity="0.95"/>\n'
            f'        <text x="0" y="3.5" text-anchor="middle" font-size="8" font-weight="600" fill="#f8fafc">{html.escape(bubble_text)}</text>\n'
            f'      </g>\n'
            f'      <!-- Corps rectangulaire de l\'équipement -->\n'
            f'      <rect x="{-bw/2:.1f}" y="{-bh/2:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="8" ry="8" '
            f'fill="#f8fafc" stroke="#334155" stroke-width="2.2" filter="url(#pid-shadow)"/>\n'
            f'{header_svg}'
            f'    </g>\n'
        )

    svg_lines.append('  </g>\n\n')

    # 5. Tracé des Vannes (Nœud Papillon Orienté selon l'Angle de Ligne)
    svg_lines.append('  <!-- Vannes de Sectionnement & Régulation (Nœud Papillon) -->\n  <g id="valves">\n')

    for el in elements:
        if el.get("kind") != "valve":
            continue
        tag = el.get("tag") or el.get("id") or "VALVE"
        pos = el.get("position")
        bb = el.get("bbox") or el.get("box")

        if pos and len(pos) >= 2:
            scx, scy = to_svg(float(pos[0]), float(pos[1]))
        elif bb and len(bb) >= 4:
            scx, scy = to_svg((bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0)
        else:
            continue

        ang = _find_nearest_segment_angle(scx, scy, svg_segments)

        # Symbole Nœud Papillon Standard ISA-5.1
        # Triangle gauche : (-11,-7) -> (0,0) -> (-11,7)
        # Triangle droit  : (11,-7)  -> (0,0) -> (11,7)
        is_actuated = any(kw in tag for kw in ("HV", "XV", "MOV", "CV", "FV", "LV", "PV", "TV", "SDV"))
        actuator_svg = ""
        if is_actuated:
            # Tige + Chapeau d'actionneur
            actuator_svg = (
                '<line x1="0" y1="0" x2="0" y2="-13" stroke="#0f172a" stroke-width="1.5"/>\n'
                '      <circle cx="0" cy="-17" r="5" fill="#f8fafc" stroke="#0f172a" stroke-width="1.5"/>\n'
            )

        # Si la vanne a un tag explicite (pas un bloc sans étiquette texte), afficher le badge texte
        has_text_tag = el.get("has_text_tag", True)
        is_generic_valve = (
            not has_text_tag
            or bool(re.match(r"^V-[\dA-Za-z#_-]+$", tag))
            or tag in ("VALVE", "BALL_VALVE", "GATE_VALVE", "CHECK_VALVE", "GLOBE_VALVE", "VENT", "DRAIN", "PSV")
        )

        label_svg = ""
        if not is_generic_valve:
            label_svg = (
                f'      <!-- Étiquette de la vanne (toujours horizontale pour lisibilité) -->\n'
                f'      <rect x="{-len(tag)*3.2 - 4:.1f}" y="-26" width="{len(tag)*6.4 + 8:.1f}" height="13" '
                f'rx="2" fill="#ffffff" stroke="#cbd5e1" stroke-width="0.8" opacity="0.95"/>\n'
                f'      <text x="0" y="-16.5" text-anchor="middle" font-size="8.5" font-weight="700" '
                f'fill="#0f172a">{html.escape(tag)}</text>\n'
            )

        svg_lines.append(
            f'    <g class="pid-schematic-element" data-tag="{html.escape(tag)}" data-kind="valve" '
            f'data-cx="{scx:.1f}" data-cy="{scy:.1f}" style="cursor:pointer;" '
            f'transform="translate({scx:.1f}, {scy:.1f})">\n'
            f'      <!-- Corps orienté de la vanne (Nœud Papillon) -->\n'
            f'      <g transform="rotate({ang:.1f})">\n'
            f'        <polygon points="-11,-7 0,0 -11,7" fill="#ffffff" stroke="#0f172a" stroke-width="1.8"/>\n'
            f'        <polygon points="11,-7 0,0 11,7" fill="#ffffff" stroke="#0f172a" stroke-width="1.8"/>\n'
            f'        {actuator_svg}'
            f'      </g>\n'
            f'{label_svg}'
            f'    </g>\n'
        )

    svg_lines.append('  </g>\n\n')

    # 6. Tracé des Instruments (Bulles ISA-5.1)
    svg_lines.append('  <!-- Instrumentation ISA-5.1 (Bulles avec Séparateur) -->\n  <g id="instruments">\n')

    for el in elements:
        if el.get("kind") != "instrument":
            continue
        tag = el.get("tag") or el.get("id") or "INST"
        pos = el.get("position")
        bb = el.get("bbox") or el.get("box")

        if pos and len(pos) >= 2:
            scx, scy = to_svg(float(pos[0]), float(pos[1]))
        elif bb and len(bb) >= 4:
            scx, scy = to_svg((bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0)
        else:
            continue

        parts = el.get("parts") or {}
        pre = parts.get("pre") or ""
        loop = parts.get("loop") or ""

        # Découpage si tag type "TIT-205" ou "PIT217"
        if not pre and "-" in tag:
            chunks = tag.split("-")
            if len(chunks) == 2:
                pre, loop = chunks[0], chunks[1]
            elif len(chunks) >= 3:
                pre, loop = chunks[1], chunks[2]

        r = 15.0
        svg_lines.append(
            f'    <g class="pid-schematic-element" data-tag="{html.escape(tag)}" data-kind="instrument" '
            f'data-cx="{scx:.1f}" data-cy="{scy:.1f}" style="cursor:pointer;" '
            f'transform="translate({scx:.1f}, {scy:.1f})">\n'
            f'      <circle cx="0" cy="0" r="{r:.1f}" fill="#ffffff" stroke="#0284c7" stroke-width="1.8"/>\n'
            f'      <line x1="{-r:.1f}" y1="0" x2="{r:.1f}" y2="0" stroke="#0284c7" stroke-width="1.2"/>\n'
        )

        if pre and loop:
            svg_lines.append(
                f'      <text x="0" y="-3.5" text-anchor="middle" font-size="8.5" font-weight="700" '
                f'fill="#0369a1">{html.escape(pre)}</text>\n'
                f'      <text x="0" y="9.5" text-anchor="middle" font-size="8" font-weight="600" '
                f'fill="#0369a1">{html.escape(loop)}</text>\n'
            )
        else:
            svg_lines.append(
                f'      <text x="0" y="3.5" text-anchor="middle" font-size="8" font-weight="700" '
                f'fill="#0369a1">{html.escape(tag)}</text>\n'
            )

        svg_lines.append('    </g>\n')

    svg_lines.append('  </g>\n\n')

    # 7. Panneau d'Annotations & Cartouche au Bas du Canvas
    panel_y = main_h
    svg_lines.append(
        f'  <!-- Panneau d\'Annotations & Cartouche P&ID -->\n'
        f'  <g id="annotations-panel">\n'
        f'    <rect x="0" y="{panel_y:.1f}" width="{canvas_w:.1f}" height="{panel_h:.1f}" '
        f'fill="#0f172a" stroke="#1e293b" stroke-width="1"/>\n'
        f'    <!-- Bordure supérieure lumineuse -->\n'
        f'    <line x1="0" y1="{panel_y:.1f}" x2="{canvas_w:.1f}" y2="{panel_y:.1f}" stroke="#3b82f6" stroke-width="2"/>\n'
    )

    # Colonne 1 : Métadonnées du Cartouche
    dwg_title = titleblock.get("title") or "P&ID SCHÉMA DE PROCÉDÉ RECONSTRUIT"
    dwg_num = titleblock.get("drawing_number") or titleblock.get("doc_number") or "non lu"
    dwg_rev = titleblock.get("revision") or "non lue"
    svg_lines.append(
        f'    <g transform="translate(35, {panel_y + 28:.1f})">\n'
        f'      <text x="0" y="0" font-size="14" font-weight="700" fill="#f8fafc">{html.escape(str(dwg_title))}</text>\n'
        f'      <text x="0" y="24" font-size="11" fill="#94a3b8">PLAN : <tspan font-weight="600" fill="#f1f5f9">{html.escape(str(dwg_num))}</tspan>  |  REV : <tspan font-weight="600" fill="#f1f5f9">{html.escape(str(dwg_rev))}</tspan>  |  UNITÉS : {html.escape(str(sem.get("units") or "non lues"))}</text>\n'
        f'      <text x="0" y="44" font-size="10" fill="#64748b">Reconstruction automatique, à valider  |  Généré par Arkan P&amp;ID Engine</text>\n'
        f'    </g>\n'
    )

    # Colonne 2 : Légende des Fluides Détectés
    legend_fluids = sorted(list(fluids_present)) if fluids_present else ["P", "LP", "IA", "W"]
    svg_lines.append(
        f'    <g transform="translate(680, {panel_y + 22:.1f})">\n'
        f'      <text x="0" y="0" font-size="11" font-weight="700" fill="#94a3b8" letter-spacing="0.5">LÉGENDE DES FLUIDES DÉTECTÉS</text>\n'
    )

    badge_x = 0.0
    badge_y = 14.0
    for i, fl in enumerate(legend_fluids[:8]):  # Max 8 badges
        c_badge = FLUID_COLORS.get(fl, DEFAULT_FLUID_COLOR)
        lbl = FLUID_LABELS.get(fl, fl)
        b_txt = f"{fl}: {lbl}"
        bw_b = len(b_txt) * 6.0 + 22.0

        if badge_x + bw_b > 440.0:
            badge_x = 0.0
            badge_y += 24.0

        svg_lines.append(
            f'      <rect x="{badge_x:.1f}" y="{badge_y:.1f}" width="{bw_b:.1f}" height="18" rx="4" fill="#1e293b" stroke="{c_badge}" stroke-width="1.2"/>\n'
            f'      <circle cx="{badge_x + 9:.1f}" cy="{badge_y + 9:.1f}" r="4" fill="{c_badge}"/>\n'
            f'      <text x="{badge_x + 18:.1f}" y="{badge_y + 12.5:.1f}" font-size="9.5" font-weight="600" fill="#f8fafc">{html.escape(b_txt)}</text>\n'
        )
        badge_x += bw_b + 8.0

    svg_lines.append('    </g>\n')

    # Colonne 3 : Métriques & Synthèse d'Analyse
    nb_eq = len(rendered_eq_tags)
    nb_valves = sum(1 for e in elements if e.get("kind") == "valve")
    nb_inst = sum(1 for e in elements if e.get("kind") == "instrument")
    nb_lines = len(lines)

    svg_lines.append(
        f'    <g transform="translate(1220, {panel_y + 24:.1f})">\n'
        f'      <text x="0" y="0" font-size="11" font-weight="700" fill="#94a3b8" letter-spacing="0.5">SYNTHÈSE DU MODÈLE NUMÉRIQUE</text>\n'
        f'      <g transform="translate(0, 18)">\n'
        f'        <rect x="0" y="0" width="70" height="34" rx="4" fill="#1e293b"/>\n'
        f'        <text x="35" y="15" text-anchor="middle" font-size="8.5" fill="#94a3b8">Équip.</text>\n'
        f'        <text x="35" y="28" text-anchor="middle" font-size="11" font-weight="700" fill="#38bdf8">{nb_eq}</text>\n'
        f'        <rect x="78" y="0" width="70" height="34" rx="4" fill="#1e293b"/>\n'
        f'        <text x="113" y="15" text-anchor="middle" font-size="8.5" fill="#94a3b8">Vannes</text>\n'
        f'        <text x="113" y="28" text-anchor="middle" font-size="11" font-weight="700" fill="#a78bfa">{nb_valves}</text>\n'
        f'        <rect x="156" y="0" width="70" height="34" rx="4" fill="#1e293b"/>\n'
        f'        <text x="191" y="15" text-anchor="middle" font-size="8.5" fill="#94a3b8">Instrum.</text>\n'
        f'        <text x="191" y="28" text-anchor="middle" font-size="11" font-weight="700" fill="#34d399">{nb_inst}</text>\n'
        f'        <rect x="234" y="0" width="70" height="34" rx="4" fill="#1e293b"/>\n'
        f'        <text x="269" y="15" text-anchor="middle" font-size="8.5" fill="#94a3b8">Lignes</text>\n'
        f'        <text x="269" y="28" text-anchor="middle" font-size="11" font-weight="700" fill="#fbbf24">{nb_lines}</text>\n'
        f'      </g>\n'
        f'      <text x="0" y="74" font-size="9.5" fill="#64748b">Surbrillance interactive activée pour sélection 1-clic.</text>\n'
        f'    </g>\n'
    )

    svg_lines.append('  </g>\n')
    svg_lines.append('</svg>\n')

    svg_str = "".join(svg_lines)

    if out_svg_path:
        out_p = Path(out_svg_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(svg_str, encoding="utf-8")

    return svg_str


# -----------------------------------------------------------------------------
# Interface Ligne de Commande CLI
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: python {Path(__file__).name} input.json output.svg")
        sys.exit(0)

    in_file = Path(sys.argv[1])
    out_file = Path(sys.argv[2])

    if not in_file.exists():
        print(f"Erreur : Le fichier d'entrée '{in_file}' n'existe pas.")
        sys.exit(1)

    try:
        data = json.loads(in_file.read_text(encoding="utf-8"))
        render_schematic(data, out_file)
        print(f"Schéma SVG simplifié généré avec succès dans '{out_file}'.")
    except Exception as exc:
        print(f"Erreur lors de la génération du schéma : {exc}")
        sys.exit(1)
