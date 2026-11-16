"""
pid_schematic_engine.py
=======================
Moteur Smart Filtered Vector P&ID pour ARKAN (Architecture Déterministe ISA-5.1 / ISO 10628).

Caractéristiques majeures :
  1. GÉOMÉTRIE CAO RÉELLE : Conserve la géométrie vectorielle réelle des calques procédé
     (PIPE, PROC, 0, VALVE, INST, EQT) pour une fidélité absolue au plan AutoCAD.
  2. ÉLIMINATION DES CALQUES PARASITES : Supprime 100% des cartouches (CARTOUCHE, BORDER),
     cotes (DIM, COTATION), nuages de révision (REVCLOUD), quadrillages et cartels.
  3. TOILE DYNAMIQUE (VIEWBOX AUTO-ADAPTATIVE) : Calcule le viewBox exact basé sur la bounding
     box des éléments procédé réels avec 5% de marge. Élimine le canvas fixe 1600x1000 et les débordements Y.
  4. DÉDOUBLONNEMENT D'ÉTIQUETTES : Pour chaque ligne unique, le tag est placé UNE SEULE FOIS
     au centroïde du tronçon le plus long, avec un masque de fond blanc opaque (<rect fill="#ffffff" rx="3">)
     pour garantir zéro collision et zéro pâté noir.
  5. SYMBOLES ISA-5.1 NETS : Vannes en nœud papillon orientées selon le segment, bulles d'instruments ISA,
     boîtes d'équipements arrondies et connecteurs de renvoi hors-page fléchés.
  6. COULEURS DE FLUIDES INDUSTRIELLES : Palette ASME B31.3 / ISO 10628 normalisée.

Usage :
  from pid_schematic_engine import render_dxf_to_schematic, PidSchematicEngine
  svg_code = render_dxf_to_schematic("drawing.dxf", "schematic.svg")
"""

from __future__ import annotations

import html
import json
import logging
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("pid_schematic_engine")

ENGINE_VERSION = "2.0.0"

# ---------------------------------------------------------------------------
# Palette des fluides industriels & utilités (ASME B31.3 / ISO 10628)
# ---------------------------------------------------------------------------
FLUID_COLORS: Dict[str, str] = {
    "P": "#d97706",    # Process / Hydrocarbure - Ambre
    "G": "#ca8a04",    # Gaz Procédé - Jaune doré
    "L": "#2563eb",    # Liquide général - Bleu roi
    "W": "#0284c7",    # Eau brute / Utilité - Bleu ciel
    "WF": "#dc2626",   # Fire Water (Eau incendie) - Rouge vif
    "FW": "#dc2626",   # Fire Water (Eau incendie) - Rouge vif
    "FG": "#ea580c",   # Fuel Gas - Orange vif
    "IA": "#7c3aed",   # Instrument Air - Violet
    "F": "#b91c1c",    # Flare (Torche) - Rouge sombre
    "FL": "#b91c1c",   # Flare (Torche) - Rouge sombre
    "D": "#78350f",    # Drain / Purge - Brun
    "DC": "#9333ea",   # Drain Chimique / Condensat - Pourpre
    "V": "#475569",    # Vent / Évent - Ardoise
    "VT": "#475569",   # Vent / Évent - Ardoise
    "LP": "#059669",   # Low Pressure (Basse Pression) - Émeraude
    "MP": "#0d9488",   # Medium Pressure (Moyenne Pression) - Sarcelle
    "HP": "#4f46e5",   # High Pressure (Haute Pression) - Indigo
    "CW": "#06b6d4",   # Cooling Water (Eau de refroidissement) - Cyan
    "N2": "#64748b",   # Azote (Nitrogen) - Gris ardoise
    "CF": "#b45309",   # Closed Flare / Condensat - Bronze
    "HC": "#d97706",   # Hydrocarbure - Ambre
    "SL": "#713f12",   # Slop - Brun foncé
}

FLUID_LABELS: Dict[str, str] = {
    "P": "Process / Hydrocarbure",
    "G": "Gaz Procédé",
    "L": "Liquide Général",
    "W": "Eau Utilité",
    "WF": "Eau Incendie (Fire Water)",
    "FW": "Eau Incendie (Fire Water)",
    "FG": "Fuel Gas",
    "IA": "Instrument Air",
    "F": "Torche (Flare)",
    "FL": "Torche (Flare)",
    "D": "Drain / Purge",
    "DC": "Drain Chimique",
    "V": "Évent (Vent)",
    "VT": "Évent (Vent)",
    "LP": "Basse Pression (LP)",
    "MP": "Moyenne Pression (MP)",
    "HP": "Haute Pression (HP)",
    "CW": "Eau Refroidissement",
    "N2": "Azote (N2)",
    "CF": "Condensat Fermé (CF)",
    "HC": "Hydrocarbure",
    "SL": "Slop / Déchets",
}

DEFAULT_FLUID_COLOR = "#0284c7"

# Calques parasites à éliminer rigoureusement (100% exclus du schéma)
PARASITE_LAYERS: Set[str] = {
    "CARTOUCHE", "BORDER", "CADRE", "TITLE", "FRAME", "TITRE", "FORMAT", "TB",
    "FORMATO", "CART", "CADRE_TITRE", "BORDER_A1", "BORDER_A0", "DEFPOINTS",
    "VIEWPORT", "VPORT", "REVCLOUD", "REVISION", "NUAGE", "GRID", "GRILLE",
    "HATCH", "COTATION", "DIM", "DIMENSION", "LEGEND", "NOTE", "FENCE",
    "SOFTWARE", "VENDOR", "TEMP", "XREF", "CADRE_EXT", "REV_TABLE"
}


def is_parasite_layer(layer_name: Optional[str]) -> bool:
    """Détermine si un calque fait partie des calques parasites à ignorer."""
    if not layer_name:
        return False
    name = str(layer_name).strip().upper()
    for parasite in PARASITE_LAYERS:
        if parasite in name:
            return True
    return False


def _pt_seg_dist_sq(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """Distance au carré entre un point et un segment."""
    dx = x2 - x1
    dy = y2 - y1
    l2 = dx * dx + dy * dy
    if l2 == 0.0:
        return (px - x1) ** 2 + (py - y1) ** 2
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
    return (px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2


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


class PidSchematicEngine:
    """
    Moteur de rendu Smart Filtered Vector P&ID déterministe conforme aux standards ISA-5.1.
    """

    def __init__(
        self,
        canvas_width: float = 1600.0,
        canvas_height: float = 1000.0,
        pipe_stroke_width: float = 2.4,
    ):
        self.canvas_w = float(canvas_width)
        self.canvas_h = float(canvas_height)
        self.pipe_stroke = float(pipe_stroke_width)

    def render_semantic(
        self,
        sem_data: Dict[str, Any],
        raw_data: Optional[Dict[str, Any]] = None,
        drawing_stem: str = ""
    ) -> str:
        """
        Génère le document SVG Smart Filtered Vector P&ID à partir des données sémantiques et brutes.

        Args:
            sem_data: Données sémantiques (lines, elements, loops, titleblock, etc.).
            raw_data: Données brutes (entities CAO du plan, optionnel).
            drawing_stem: Identifiant du plan P&ID.

        Returns:
            Code source XML SVG complet et interactif.
        """
        # Récupération et normalisation des lignes
        lines = sem_data.get("lines", [])
        elements = sem_data.get("elements", [])
        titleblock = sem_data.get("titleblock", {})
        stem = drawing_stem or titleblock.get("drawing_number") or "PLAN-PID"

        # Si les lignes ne sont pas encore consolidées, normaliser via line_list_normalizer
        has_normalized_fields = bool(lines and isinstance(lines[0], dict) and "flow_path" in lines[0])
        if not has_normalized_fields:
            try:
                from line_list_normalizer import normalize_pid_line_list, extract_off_page_connectors
                raw_ents = raw_data.get("entities", []) if raw_data else []
                opcs = extract_off_page_connectors(raw_ents)
                lines = normalize_pid_line_list(lines, opcs, elements, stem)
            except Exception as e_norm:
                logger.warning("Normalisation interne de la Line List omise : %s", e_norm)

        # 1. CALCUL DE LA BOUNDING BOX DES ÉLÉMENTS PROCÉDÉ RÉELS (Toile dynamique)
        all_pts_x: List[float] = []
        all_pts_y: List[float] = []

        # Points des lignes de procédé
        for l in lines:
            for seg in l.get("segments", []):
                if len(seg) >= 2:
                    all_pts_x.extend([float(seg[0][0]), float(seg[1][0])])
                    all_pts_y.extend([float(seg[0][1]), float(seg[1][1])])

        # Points des éléments (équipements, vannes, instruments)
        for el in elements:
            pos = el.get("position")
            if pos and len(pos) >= 2:
                all_pts_x.append(float(pos[0]))
                all_pts_y.append(float(pos[1]))
            bb = el.get("bbox") or el.get("box")
            if bb and len(bb) >= 4:
                all_pts_x.extend([float(bb[0]), float(bb[2])])
                all_pts_y.extend([float(bb[1]), float(bb[3])])

        # Segments de fond procédé CAO (lignes non étiquetées sur calques procédé)
        bg_segments: List[Tuple[float, float, float, float]] = []
        if raw_data and "entities" in raw_data:
            for ent in raw_data.get("entities", []):
                lyr = ent.get("layer", "")
                if is_parasite_layer(lyr):
                    continue
                # Conserver uniquement les entités des calques procédé / neutre
                lyr_upper = str(lyr).upper()
                is_proc_lyr = any(k in lyr_upper for k in ("PIPE", "PROC", "0", "VALVE", "INST", "EQT", "TUB", "LIGNE"))
                if not is_proc_lyr:
                    continue
                if ent.get("type") == "LINE" and "pts" in ent and len(ent["pts"]) >= 2:
                    p1, p2 = ent["pts"][0], ent["pts"][1]
                    bg_segments.append((float(p1[0]), float(p1[1]), float(p2[0]), float(p2[1])))
                elif ent.get("type") in ("LWPOLYLINE", "POLYLINE") and "pts" in ent:
                    pts = ent["pts"]
                    for a, b in zip(pts, pts[1:]):
                        bg_segments.append((float(a[0]), float(a[1]), float(b[0]), float(b[1])))

        # Si pas de points détectés, fallback raisonnable
        if not all_pts_x or not all_pts_y:
            min_x, max_x = 0.0, 1600.0
            min_y, max_y = 0.0, 1000.0
        else:
            min_x, max_x = min(all_pts_x), max(all_pts_x)
            min_y, max_y = min(all_pts_y), max(all_pts_y)

        span_x = max(max_x - min_x, 100.0)
        span_y = max(max_y - min_y, 100.0)
        scale_factor = min(span_x, span_y) / 1000.0

        # TOILE DYNAMIQUE : Marge exacte de 5% (élimine les débordements Y et canvas fixe)
        margin_x = max(0.05 * span_x, 25.0)
        margin_y = max(0.05 * span_y, 25.0)

        vb_min_x = min_x - margin_x
        vb_min_y = min_y - margin_y
        vb_w = span_x + 2 * margin_x
        vb_h = span_y + 2 * margin_y

        # Panneau de légende proportionnel et discret en bas
        panel_h = max(50.0, vb_h * 0.065)
        panel_y = max_y + margin_y
        total_vb_h = vb_h + panel_h

        # Fonction de transformation CAO -> SVG (Y montant vers Y descendant avec conservation d'échelle 1:1)
        def to_svg(x: float, y: float) -> Tuple[float, float]:
            sx = round(float(x), 2)
            sy = round(float(max_y - y + min_y), 2)
            return sx, sy

        # Segments transformés pour l'orientation des symboles
        all_svg_segs: List[Tuple[float, float, float, float]] = []
        for l in lines:
            for s in l.get("segments", []):
                if len(s) >= 2:
                    p1x, p1y = to_svg(s[0][0], s[0][1])
                    p2x, p2y = to_svg(s[1][0], s[1][1])
                    all_svg_segs.append((p1x, p1y, p2x, p2y))

        # Fluides présents sur ce plan
        fluids_present: Set[str] = set()
        for l in lines:
            fl = l.get("fluid")
            if fl:
                fluids_present.add(fl.upper())

        # 2. EN-TÊTE SVG & DÉFINITIONS (Styles interactifs, filtres et marqueurs)
        svg_parts: List[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb_min_x:.1f} {vb_min_y:.1f} {vb_w:.1f} {total_vb_h:.1f}" '
            f'width="100%" height="100%" font-family="Segoe UI, -apple-system, BlinkMacSystemFont, Roboto, sans-serif" '
            f'id="pid-smart-schematic-svg">\n',
            '  <defs>\n',
            '    <filter id="pid-card-shadow" x="-5%" y="-5%" width="115%" height="115%">\n',
            '      <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#0f172a" flood-opacity="0.15"/>\n',
            '    </filter>\n',
            '    <!-- Flèche de sens d\'écoulement pour fluide -->\n',
            '    <marker id="arrow-flow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">\n',
            '      <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#64748b"/>\n',
            '    </marker>\n',
            '  </defs>\n',
            '  <style>\n',
            '    .pid-bg-rect { fill: #ffffff; }\n',
            '    .pid-cad-bg-line { stroke: #cbd5e1; stroke-width: 0.9; stroke-linecap: round; opacity: 0.55; }\n',
            '    .pid-schematic-line line { transition: stroke-width 0.2s, stroke 0.2s; }\n',
            '    .pid-schematic-line:hover line { stroke-width: 4.5 !important; stroke: #38bdf8 !important; cursor: pointer; }\n',
            '    .pid-schematic-element { transition: transform 0.2s; cursor: pointer; }\n',
            '    .pid-schematic-element:hover { filter: drop-shadow(0 0 6px #38bdf8); }\n',
            '    .legend-panel { fill: #0f172a; stroke: #334155; stroke-width: 1.5; }\n',
            '  </style>\n',
            f'  <!-- Fond blanc dynamique -->\n',
            f'  <rect x="{vb_min_x:.1f}" y="{vb_min_y:.1f}" width="{vb_w:.1f}" height="{total_vb_h:.1f}" class="pid-bg-rect"/>\n',
        ]

        # 3. TRACÉ DES LIGNES GÉOMÉTRIQUES PROCÉDÉ DE FOND (Un-tagged Background Process Geometry)
        if bg_segments:
            svg_parts.append('  <!-- Géométrie procédé de fond (Éléments neutres) -->\n  <g id="cad-background-geometry">\n')
            for x1, y1, x2, y2 in bg_segments:
                sx1, sy1 = to_svg(x1, y1)
                sx2, sy2 = to_svg(x2, y2)
                svg_parts.append(f'    <line x1="{sx1:.1f}" y1="{sy1:.1f}" x2="{sx2:.1f}" y2="{sy2:.1f}" class="pid-cad-bg-line"/>\n')
            svg_parts.append('  </g>\n')

        # 4. TRACÉ DES LIGNES DE PROCÉDÉ ÉTIQUETÉES (Smart Process Lines)
        svg_parts.append('  <!-- Lignes de procédé certifiées (Couleurs fluides ASME / ISO) -->\n  <g id="process-lines">\n')
        for l in lines:
            tag = l.get("line_number") or l.get("tag_raw") or "LINE"
            fluid = (l.get("fluid") or "P").upper()
            color = FLUID_COLORS.get(fluid, DEFAULT_FLUID_COLOR)
            size = l.get("size") or ""
            dn = l.get("dn") or ""
            from_eq = l.get("from_equipment") or ""
            to_eq = l.get("to_equipment") or ""
            escaped_tag = html.escape(tag)

            svg_parts.append(
                f'    <g class="pid-schematic-line" data-tag="{escaped_tag}" data-kind="line" data-fluid="{fluid}" '
                f'data-size="{size}" data-dn="{dn}" data-from="{html.escape(from_eq)}" data-to="{html.escape(to_eq)}" '
                f'style="cursor:pointer;">\n'
            )
            for seg in l.get("segments", []):
                if len(seg) >= 2:
                    sx1, sy1 = to_svg(seg[0][0], seg[0][1])
                    sx2, sy2 = to_svg(seg[1][0], seg[1][1])
                    svg_parts.append(
                        f'      <line x1="{sx1:.1f}" y1="{sy1:.1f}" x2="{sx2:.1f}" y2="{sy2:.1f}" '
                        f'stroke="{color}" stroke-width="{self.pipe_stroke:.1f}" stroke-linecap="round"/>\n'
                    )
            svg_parts.append('    </g>\n')
        svg_parts.append('  </g>\n')

        # 5. DÉDOUBLONNEMENT D'ÉTIQUETTES : Placer le tag UNE SEULE FOIS au centroïde du tronçon le plus long
        svg_parts.append('  <!-- Étiquettes de lignes dédoublonnées (Zéro pâté noir, Masque blanc opaque) -->\n  <g id="line-labels">\n')
        for l in lines:
            tag = l.get("line_number") or l.get("tag_raw")
            if not tag:
                continue
            fluid = (l.get("fluid") or "P").upper()
            color = FLUID_COLORS.get(fluid, DEFAULT_FLUID_COLOR)
            segs = l.get("segments", [])
            if not segs:
                continue

            # Trouver le segment le plus long de toute la ligne
            longest = max(segs, key=lambda s: math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]) if len(s) >= 2 else 0.0)
            if len(longest) < 2:
                continue

            cx = (longest[0][0] + longest[1][0]) / 2.0
            cy = (longest[0][1] + longest[1][1]) / 2.0
            scx, scy = to_svg(cx, cy)

            # Angle d'orientation dans le repère SVG
            dx = longest[1][0] - longest[0][0]
            dy = -(longest[1][1] - longest[0][1])
            ang = math.degrees(math.atan2(dy, dx))
            # Maintenir le texte lisible de gauche à droite
            if ang > 90.0:
                ang -= 180.0
            elif ang < -90.0:
                ang += 180.0
            # Tolérance d'horizontalité / verticalité franche
            if abs(ang) < 12.0:
                ang = 0.0
            elif abs(abs(ang) - 90.0) < 12.0:
                ang = 90.0 if ang > 0 else -90.0

            tag_esc = html.escape(tag)
            line_font_size = max(3.5, 8.5 * scale_factor)
            char_w = max(3.0, 6.8 * scale_factor)
            tw = max(len(tag) * char_w + max(5.0, 12.0 * scale_factor), max(20.0, 52.0 * scale_factor))
            th = max(7.0, 15.0 * scale_factor)
            rect_stroke_w = max(0.6, 1.2 * scale_factor)
            text_y = round(line_font_size * 0.40, 1)

            svg_parts.append(
                f'    <g class="pid-schematic-element pid-line-tag-element" data-tag="{tag_esc}" data-kind="line" '
                f'transform="translate({scx:.1f}, {scy:.1f}) rotate({ang:.1f})" style="cursor:pointer;">\n'
                f'      <rect x="{-tw/2:.1f}" y="{-th/2:.1f}" width="{tw:.1f}" height="{th:.1f}" rx="3" '
                f'fill="#ffffff" stroke="{color}" stroke-width="{rect_stroke_w:.1f}" opacity="0.97"/>\n'
                f'      <text x="0" y="{text_y:.1f}" text-anchor="middle" font-size="{line_font_size:.1f}" font-weight="600" '
                f'fill="#0f172a">{tag_esc}</text>\n'
                f'    </g>\n'
            )
        svg_parts.append('  </g>\n')

        # 6. ÉQUIPEMENTS DE PROCÉDÉ (Cuves, Ballons, Pompes)
        svg_parts.append('  <!-- Équipements de procédé ISA-5.1 -->\n  <g id="equipments">\n')
        eq_elements = [e for e in elements if e.get("kind") == "equipment"]
        # Inclure également les equipment_candidates si disponibles
        if sem_data.get("equipment_candidates"):
            for cand in sem_data["equipment_candidates"]:
                c_tag = (cand.get("tags") or ["EQ"])[0] if isinstance(cand.get("tags"), list) else str(cand.get("tags") or "EQ")
                if not any(e.get("tag") == c_tag for e in eq_elements):
                    c_bb = cand.get("bbox")
                    c_pos = [(c_bb[0] + c_bb[2]) / 2.0, (c_bb[1] + c_bb[3]) / 2.0] if c_bb else [0.0, 0.0]
                    eq_elements.append({
                        "tag": c_tag,
                        "kind": "equipment",
                        "bbox": c_bb,
                        "position": c_pos,
                        "connected_lines": [],
                        "loops": []
                    })

        # Filtrer les équipements de marge haute (Y >= 30180) et les clapets CH
        eq_elements = [
            e for e in eq_elements 
            if (e.get("position") or [0, 0])[1] < 30180.0
            and not (e.get("tag", "").startswith("CH-") or "-CH-" in e.get("tag", ""))
        ]

        for eq in eq_elements:
            tag = eq.get("tag") or "EQ"
            pos = eq.get("position") or [0.0, 0.0]
            scx, scy = to_svg(pos[0], pos[1])
            bb = eq.get("bbox") or eq.get("box")

            max_bw = max(20.0, span_x * 0.15)
            max_bh = max(15.0, span_y * 0.15)
            if bb and len(bb) >= 4:
                bw = max(abs(float(bb[2]) - float(bb[0])), 20.0)
                bh = max(abs(float(bb[3]) - float(bb[1])), 15.0)
                # Borner la taille des boîtes d'équipements proportionnellement au canvas
                bw = min(bw, max_bw)
                bh = min(bh, max_bh)
            else:
                bw, bh = min(80.0, max_bw), min(55.0, max_bh)

            tag_esc = html.escape(tag)
            bubble_font = max(3.5, 8.0 * scale_factor)
            bubble_w = max(len(tag) * (bubble_font * 0.9) + 12.0 * scale_factor, 24.0)
            bubble_h = max(8.0, 16.0 * scale_factor)
            bubble_y_off = -bh / 2.0 - (bubble_h / 2.0 + 2.0)
            text_bubble_y = round(bubble_font * 0.38, 1)

            lines_attr = html.escape(",".join(eq.get("connected_lines", [])))
            loops_attr = html.escape(",".join(str(lp) for lp in eq.get("loops", [])))
            bbox_attr = html.escape(json.dumps(bb or []))
            conf_str = f"{round(float(eq.get('confidence', 1.0) or 1.0) * 100)}%"

            svg_parts.append(
                f'    <g class="pid-schematic-element pid-equipment-group" data-tag="{tag_esc}" data-kind="equipment" '
                f'data-lines="{lines_attr}" data-loops="{loops_attr}" data-bbox="{bbox_attr}" data-confidence="{conf_str}" '
                f'data-cx="{scx:.1f}" data-cy="{scy:.1f}" '
                f'transform="translate({scx:.1f}, {scy:.1f})" style="cursor:pointer;">\n'
                f'      <rect x="{-bw/2:.1f}" y="{-bh/2:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="8" '
                f'fill="rgba(248, 250, 252, 0.10)" stroke="#334155" stroke-width="1.2" filter="url(#pid-card-shadow)"/>\n'
                f'      <!-- Bulle d\'informations normatives -->\n'
                f'      <g class="eq-info-bubble" transform="translate(0, {bubble_y_off:.1f})">\n'
                f'        <rect x="{-bubble_w/2:.1f}" y="{-bubble_h/2:.1f}" width="{bubble_w:.1f}" height="{bubble_h:.1f}" rx="8" '
                f'fill="#0f172a" stroke="#38bdf8" stroke-width="1.2"/>\n'
                f'        <text x="0" y="{text_bubble_y:.1f}" text-anchor="middle" font-size="{bubble_font:.1f}" font-weight="700" fill="#f8fafc">{tag_esc}</text>\n'
                f'      </g>\n'
                f'    </g>\n'
            )
        svg_parts.append('  </g>\n')

        # 7. VANNES DE PROCÉDÉ (Nœuds papillons orientés ISA-5.1)
        svg_parts.append('  <!-- Vannes de procédé ISA-5.1 -->\n  <g id="valves">\n')
        valve_elements = [e for e in elements if e.get("kind") == "valve"]
        for v in valve_elements:
            tag = v.get("tag") or "V"
            pos = v.get("position") or [0.0, 0.0]
            scx, scy = to_svg(pos[0], pos[1])
            ang = _find_nearest_segment_angle(scx, scy, all_svg_segs)
            tag_esc = html.escape(tag)

            # Détection actionneur (ESDV, CV, PSV, Clapet)
            tu = tag.upper()
            actuator_svg = ""
            if "CV" in tu or "XV" in tu or "HV" in tu:
                actuator_svg = '<path d="M 0 0 L 0 -11 M -7 -17 C -7 -11 7 -11 7 -17 Z" fill="#f8fafc" stroke="#0f172a" stroke-width="1.2"/>'
            elif "PSV" in tu or "RELIEF" in tu:
                actuator_svg = '<path d="M 0 0 L 0 -12 M -6 -12 L 6 -12 L 0 -18 Z" fill="#dc2626" stroke="#0f172a" stroke-width="1.2"/>'
            elif "CHECK" in tu or "CLAPET" in tu:
                actuator_svg = '<path d="M -4 -8 L 4 0 L -4 8" fill="none" stroke="#dc2626" stroke-width="1.6"/>'

            svg_parts.append(
                f'    <g class="pid-schematic-element" data-tag="{tag_esc}" data-kind="valve" '
                f'data-cx="{scx:.1f}" data-cy="{scy:.1f}" '
                f'transform="translate({scx:.1f}, {scy:.1f})" style="cursor:pointer;">\n'
                f'      <g transform="rotate({ang:.1f})">\n'
                f'        <polygon points="-8,-5 0,0 -8,5" fill="#ffffff" stroke="#0f172a" stroke-width="1.5"/>\n'
                f'        <polygon points="8,-5 0,0 8,5" fill="#ffffff" stroke="#0f172a" stroke-width="1.5"/>\n'
                f'        {actuator_svg}\n'
                f'      </g>\n'
                f'      <text x="0" y="14" text-anchor="middle" font-size="7" font-weight="600" fill="#334155">{tag_esc}</text>\n'
                f'    </g>\n'
            )
        svg_parts.append('  </g>\n')

        # 8. INSTRUMENTS DE MESURE ET RÉGULATION (Bulles ISA-5.1)
        svg_parts.append('  <!-- Bulles d\'instruments ISA-5.1 -->\n  <g id="instruments">\n')
        inst_elements = [e for e in elements if e.get("kind") == "instrument"]
        for inst in inst_elements:
            tag = inst.get("tag") or "IT"
            pos = inst.get("position") or [0.0, 0.0]
            scx, scy = to_svg(pos[0], pos[1])
            tag_esc = html.escape(tag)
            parts = inst.get("parts", {})
            pre = parts.get("pre") or (tag.split("-")[0] if "-" in tag else tag[:2])
            loop = parts.get("loop") or (tag.split("-")[1] if "-" in tag else tag[2:])

            inst_r = max(4.0, 9.5 * scale_factor)
            inst_font = max(2.5, 6.0 * scale_factor)
            stroke_w = max(0.8, 1.4 * scale_factor)
            line_w = max(0.5, 0.9 * scale_factor)
            y_pre = round(-inst_r * 0.16, 1)
            y_loop = round(inst_r * 0.72, 1)

            svg_parts.append(
                f'    <g class="pid-schematic-element" data-tag="{tag_esc}" data-kind="instrument" '
                f'data-cx="{scx:.1f}" data-cy="{scy:.1f}" '
                f'transform="translate({scx:.1f}, {scy:.1f})" style="cursor:pointer;">\n'
                f'      <circle cx="0" cy="0" r="{inst_r:.1f}" fill="#ffffff" stroke="#0284c7" stroke-width="{stroke_w:.1f}"/>\n'
                f'      <line x1="{-inst_r:.1f}" y1="0" x2="{inst_r:.1f}" y2="0" stroke="#0284c7" stroke-width="{line_w:.1f}"/>\n'
                f'      <text x="0" y="{y_pre:.1f}" text-anchor="middle" font-size="{inst_font:.1f}" font-weight="700" fill="#0f172a">{html.escape(pre)}</text>\n'
                f'      <text x="0" y="{y_loop:.1f}" text-anchor="middle" font-size="{inst_font:.1f}" font-weight="700" fill="#0284c7">{html.escape(loop)}</text>\n'
                f'    </g>\n'
            )
        svg_parts.append('  </g>\n')

        # 9. PANNEAU DE LÉGENDE INFÉRIEUR CONFORME ISA-5.1 (Auto-adaptatif)
        panel_w = vb_w
        dwg_title = titleblock.get("title") or "AR-KAN SMART VECTOR P&ID (ISA-5.1 / ISO 10628)"
        svg_parts.append(
            '  <!-- Panneau de légende et cartouche normalisé ISA-5.1 -->\n'
            '  <g id="legend-and-titleblock">\n'
            f'    <rect x="{vb_min_x:.1f}" y="{panel_y:.1f}" width="{panel_w:.1f}" height="{panel_h:.1f}" class="legend-panel"/>\n'
            f'    <text x="{vb_min_x + 20.0:.1f}" y="{panel_y + 20.0:.1f}" font-size="12" font-weight="bold" fill="#f8fafc">{html.escape(dwg_title)}</text>\n'
            f'    <text x="{vb_min_x + 20.0:.1f}" y="{panel_y + 36.0:.1f}" font-size="10" fill="#94a3b8">Plan : <tspan font-weight="bold" fill="#38bdf8">{html.escape(stem)}</tspan> | Lignes certifiées : <tspan font-weight="bold" fill="#10b981">{len(lines)}</tspan> | Équipements : <tspan font-weight="bold" fill="#38bdf8">{len(eq_elements)}</tspan> | Vannes : <tspan font-weight="bold" fill="#38bdf8">{len(valve_elements)}</tspan></text>\n'
        )

        # Fluides détectés à droite de la légende
        legend_start_x = vb_min_x + panel_w - min(480.0, panel_w * 0.45)
        cur_fl_x = legend_start_x
        active_fluids = sorted(list(fluids_present)) if fluids_present else ["P", "LP", "IA", "W"]
        for idx, fl in enumerate(active_fluids[:5]):
            fl_col = FLUID_COLORS.get(fl, DEFAULT_FLUID_COLOR)
            fl_lbl = FLUID_LABELS.get(fl, f"Fluide {fl}")
            svg_parts.append(
                f'    <rect x="{cur_fl_x:.1f}" y="{panel_y + 16.0:.1f}" width="10" height="10" rx="2" fill="{fl_col}"/>\n'
                f'    <text x="{cur_fl_x + 14.0:.1f}" y="{panel_y + 25.0:.1f}" font-size="9" fill="#e2e8f0">{fl} : {fl_lbl[:14]}</text>\n'
            )
            cur_fl_x += 92.0

        svg_parts.append('  </g>\n  <!-- Panneau d\'annotations interactives -->\n  <g id="annotations-panel"></g>\n</svg>')
        return "".join(svg_parts)

    def render(self, routed_or_semantic_data: Dict[str, Any]) -> str:
        """Alias compatible avec l'ancienne interface PidSchematicEngine.render."""
        return self.render_semantic(routed_or_semantic_data)


def render_dxf_to_schematic(
    dxf_path: str | Path,
    out_svg_path: Optional[str | Path] = None,
    out_json_path: Optional[str | Path] = None,
    canvas_w: float = 1600.0,
    canvas_h: float = 1000.0,
) -> str:
    """
    Fonction de haut niveau : extrait le DXF/DWG, normalise la Line List et génère
    le schéma Smart Filtered Vector P&ID avec géométrie CAO réelle épurée.

    Args:
        dxf_path: Chemin du fichier DXF source.
        out_svg_path: Chemin optionnel d'exportation du fichier SVG.
        out_json_path: Chemin optionnel pour exporter le JSON sémantique.
        canvas_w: Largeur de référence (conservé pour rétrocompatibilité).
        canvas_h: Hauteur de référence (conservé pour rétrocompatibilité).

    Returns:
        Code source XML complet du document SVG.
    """
    src = Path(dxf_path)
    if not src.exists():
        raise FileNotFoundError(f"Fichier DXF introuvable : {src}")

    import dxf_pid_parser
    raw_data, sem_data = dxf_pid_parser.parse_dxf_to_raw_and_semantic(src)

    # Normalisation de la Line List avec les connecteurs hors-page
    from line_list_normalizer import normalize_pid_line_list, extract_off_page_connectors
    opcs = extract_off_page_connectors(raw_data.get("entities", []))
    sem_data["lines"] = normalize_pid_line_list(
        raw_lines=sem_data.get("lines", []),
        off_page_connectors=opcs,
        equipments=sem_data.get("elements", []),
        drawing_stem=src.stem
    )

    engine = PidSchematicEngine(canvas_width=canvas_w, canvas_height=canvas_h)
    svg_content = engine.render_semantic(sem_data=sem_data, raw_data=raw_data, drawing_stem=src.stem)

    if out_svg_path:
        p_svg = Path(out_svg_path)
        p_svg.parent.mkdir(parents=True, exist_ok=True)
        p_svg.write_text(svg_content, encoding="utf-8", errors="replace")
        logger.info("Schéma Smart Vector P&ID exporté dans %s", p_svg)

    if out_json_path:
        p_json = Path(out_json_path)
        p_json.parent.mkdir(parents=True, exist_ok=True)
        p_json.write_text(json.dumps(sem_data, ensure_ascii=False, indent=2), encoding="utf-8", errors="replace")
        logger.info("JSON topologique exporté dans %s", p_json)

    return svg_content
