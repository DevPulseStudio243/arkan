"""
pid_orthogonal_router.py
========================
Routeur Topologique Orthogonal pour Schémas P&ID (Architecture Option A - Module 2).

Transforme le Jumeau Numérique topologique brut (issu de dxf_to_pid_json.py)
en un graphe géométrique orthogonal normalisé pour le rendu SVG :
  1. Disposition relative des équipements (normalisation des centroïdes CAO,
     préservation des relations spatiales Nord/Sud/Est/Ouest, encombrements normés).
  2. Positionnement précis des piquages/nozzles sur le contour des équipements.
  3. Routage Manhattan des tuyauteries en segments orthogonaux à angles droits
     (H-V, V-H ou H-V-H).
  4. Placement et orientation automatique ('H' / 'V') des composants en ligne (vannes, réducteurs).
  5. Détection des croisements et calcul des ponts d'enjambement (Hops ⌒).
  6. Positionnement des bulles d'instrumentation ISA-5.1 et lignes de raccordement.

Usage :
  from pid_orthogonal_router import route_pid_topology, PidOrthogonalRouter
  routed = route_pid_topology(topology_data)
"""

from __future__ import annotations

import copy
import logging
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger("pid_orthogonal_router")

ROUTER_VERSION = "1.0.0"

# Encombrements standards des équipements modulaires (largeur, hauteur) en pixels SVG
EQUIPMENT_SIZES: Dict[str, Tuple[float, float]] = {
    "VESSEL": (120.0, 80.0),
    "PUMP": (70.0, 70.0),
    "TANK": (120.0, 90.0),
    "COLUMN": (80.0, 180.0),
    "HEAT_EXCHANGER": (130.0, 70.0),
    "AIR_COOLER": (120.0, 70.0),
    "COMPRESSOR": (80.0, 80.0),
    "FILTER_STRAINER": (50.0, 50.0),
    "DRUM": (100.0, 70.0),
    "SEPARATOR": (120.0, 80.0),
    "PACKAGE": (110.0, 80.0),
    "DEFAULT": (90.0, 70.0),
}


class PidOrthogonalRouter:
    """
    Routeur orthogonal topologique pour diagrammes P&ID.
    Calcule le layout relatif et génère les tracés Manhattan déterministes.
    """

    def __init__(
        self,
        canvas_width: float = 1600.0,
        canvas_height: float = 1000.0,
        margin_x: float = 120.0,
        margin_y_top: float = 90.0,
        margin_y_bottom: float = 140.0,
        hop_radius: float = 8.0,
    ):
        self.canvas_w = float(canvas_width)
        self.canvas_h = float(canvas_height)
        self.margin_x = float(margin_x)
        self.margin_y_top = float(margin_y_top)
        self.margin_y_bottom = float(margin_y_bottom)
        self.hop_radius = float(hop_radius)

    def layout_and_route(
        self,
        topology_data: Dict[str, Any],
        canvas_w: Optional[float] = None,
        canvas_h: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Exécute la disposition spatiale relative et le routage Manhattan complet.

        Args:
            topology_data: Dict JSON topologique issu de DxfToPidJsonConverter.
            canvas_w: Largeur de toile SVG optionnelle (surcharge l'instance).
            canvas_h: Hauteur de toile SVG optionnelle (surcharge l'instance).

        Returns:
            Dict structuré enrichi avec coordonnées SVG, polylignes orthogonales,
            composants orientés et ponts d'arcs (hops).
        """
        if canvas_w is not None:
            self.canvas_w = float(canvas_w)
        if canvas_h is not None:
            self.canvas_h = float(canvas_h)

        data = copy.deepcopy(topology_data)
        equipments_list: List[Dict[str, Any]] = data.get("equipments", [])
        circuits_list: List[Dict[str, Any]] = data.get("piping_circuits", [])
        valves_list: List[Dict[str, Any]] = data.get("valves", [])
        instruments_list: List[Dict[str, Any]] = data.get("instruments", [])

        # 1. Calcul de l'emprise CAO globale pour la normalisation
        cad_bounds = self._compute_cad_bounds(equipments_list, circuits_list)

        # 2. Disposition relative des équipements (Option A)
        eq_map = self._layout_equipments(equipments_list, cad_bounds)

        # 3. Positionnement des piquages / nozzles sur le contour
        nozzle_coords_map, nozzle_orient_map = self._place_nozzles(equipments_list)

        # 4. Routage orthogonal Manhattan des circuits de tuyauterie
        routed_circuits = self._route_circuits(
            circuits_list, eq_map, nozzle_coords_map, nozzle_orient_map, cad_bounds
        )

        # 5. Positionnement et orientation des composants en ligne (vannes, réducteurs)
        updated_valves = self._place_and_orient_components(
            routed_circuits, valves_list
        )

        # 6. Détection des croisements et calcul des ponts d'enjambement (Hops)
        total_hops = self._detect_and_build_hops(routed_circuits)

        # 7. Positionnement des bulles d'instruments ISA-5.1
        routed_instruments = self._place_instruments(
            instruments_list, routed_circuits, eq_map, cad_bounds
        )

        # 8. Assemblage des résultats
        summary = copy.deepcopy(data.get("topology_summary", {}))
        summary["total_hops"] = total_hops
        summary["total_routed_circuits"] = len(routed_circuits)

        result: Dict[str, Any] = {
            "metadata": copy.deepcopy(data.get("metadata", {})),
            "canvas": {
                "width": self.canvas_w,
                "height": self.canvas_h,
                "margin_x": self.margin_x,
                "margin_y_top": self.margin_y_top,
                "margin_y_bottom": self.margin_y_bottom,
            },
            "equipments": equipments_list,
            "piping_circuits": routed_circuits,
            "valves": updated_valves,
            "instruments": routed_instruments,
            "loops": copy.deepcopy(data.get("loops", [])),
            "instrument_loops": copy.deepcopy(data.get("instrument_loops", [])),
            "topology_summary": summary,
        }
        result["metadata"]["router_version"] = ROUTER_VERSION
        return result

    # -----------------------------------------------------------------------
    # 1. Emprise globale CAO
    # -----------------------------------------------------------------------

    def _compute_cad_bounds(
        self,
        equipments: List[Dict[str, Any]],
        circuits: List[Dict[str, Any]],
    ) -> Tuple[float, float, float, float]:
        """Calcule la boîte englobante [xmin, ymin, xmax, ymax] en coordonnées CAO."""
        xs: List[float] = []
        ys: List[float] = []

        for eq in equipments:
            anchor = eq.get("cad_anchor")
            if anchor and len(anchor) >= 2:
                xs.append(float(anchor[0]))
                ys.append(float(anchor[1]))
            bb = eq.get("bbox")
            if bb and len(bb) >= 4:
                xs.extend([float(bb[0]), float(bb[2])])
                ys.extend([float(bb[1]), float(bb[3])])

        for c in circuits:
            poly = c.get("polyline", [])
            for pt in poly:
                if len(pt) >= 2:
                    xs.append(float(pt[0]))
                    ys.append(float(pt[1]))

        if not xs:
            return (0.0, 0.0, 100.0, 100.0)

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        return (min_x, min_y, max_x, max_y)

    def _map_cad_to_svg(
        self,
        cad_x: float,
        cad_y: float,
        cad_bounds: Tuple[float, float, float, float],
    ) -> Tuple[float, float]:
        """
        Normalise un point CAO (x, y) vers l'espace SVG.
        Inverse l'axe Y (le Nord CAO vers le haut du canvas SVG).
        """
        min_x, min_y, max_x, max_y = cad_bounds
        span_x = max_x - min_x
        span_y = max_y - min_y

        norm_x = (cad_x - min_x) / span_x if span_x > 1e-4 else 0.5
        norm_y = (cad_y - min_y) / span_y if span_y > 1e-4 else 0.5

        usable_w = self.canvas_w - 2.0 * self.margin_x
        usable_h = self.canvas_h - self.margin_y_top - self.margin_y_bottom

        svg_x = self.margin_x + norm_x * usable_w
        svg_y = self.margin_y_top + (1.0 - norm_y) * usable_h
        return svg_x, svg_y

    # -----------------------------------------------------------------------
    # 2. Disposition relative des équipements
    # -----------------------------------------------------------------------

    def _layout_equipments(
        self,
        equipments: List[Dict[str, Any]],
        cad_bounds: Tuple[float, float, float, float],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Positionne les équipements sur le canvas SVG tout en respectant
        leur ordonnancement relatif Nord/Sud/Est/Ouest et résolvant les collisions.
        """
        eq_map: Dict[str, Dict[str, Any]] = {}
        if not equipments:
            return eq_map

        # Attribution des dimensions normées
        for eq in equipments:
            eq_type = eq.get("type", "DEFAULT")
            w, h = EQUIPMENT_SIZES.get(eq_type, EQUIPMENT_SIZES["DEFAULT"])
            eq["svg_width"] = w
            eq["svg_height"] = h

            cad_anchor = eq.get("cad_anchor") or [0.0, 0.0]
            svg_cx, svg_cy = self._map_cad_to_svg(cad_anchor[0], cad_anchor[1], cad_bounds)
            eq["svg_center"] = [round(svg_cx, 1), round(svg_cy, 1)]

        # Tri par coordonnée X pour séparer les équipements proches ou alignés
        sorted_eqs = sorted(equipments, key=lambda e: (e["svg_center"][0], e["svg_center"][1]))

        # Résolution de collision horizontale (garantir un espacement min entre blocs)
        min_gap_x = 40.0
        for i in range(len(sorted_eqs) - 1):
            curr_eq = sorted_eqs[i]
            next_eq = sorted_eqs[i + 1]
            curr_right = curr_eq["svg_center"][0] + curr_eq["svg_width"] / 2.0
            next_left = next_eq["svg_center"][0] - next_eq["svg_width"] / 2.0

            # Si même niveau vertical ou chevauchement vertical
            curr_y = curr_eq["svg_center"][1]
            next_y = next_eq["svg_center"][1]
            if abs(curr_y - next_y) < (curr_eq["svg_height"] + next_eq["svg_height"]) / 2.0:
                if next_left < curr_right + min_gap_x:
                    delta = (curr_right + min_gap_x) - next_left
                    next_eq["svg_center"][0] = round(next_eq["svg_center"][0] + delta, 1)

        # Recalcul des bounding boxes SVG
        for eq in equipments:
            cx, cy = eq["svg_center"]
            w, h = eq["svg_width"], eq["svg_height"]
            eq["svg_bbox"] = [
                round(cx - w / 2.0, 1),
                round(cy - h / 2.0, 1),
                round(cx + w / 2.0, 1),
                round(cy + h / 2.0, 1),
            ]
            tag = eq.get("tag", "")
            eq_map[tag] = eq

        return eq_map

    # -----------------------------------------------------------------------
    # 3. Positionnement des piquages / nozzles
    # -----------------------------------------------------------------------

    def _place_nozzles(
        self, equipments: List[Dict[str, Any]]
    ) -> Tuple[Dict[Tuple[str, str], List[float]], Dict[Tuple[str, str], str]]:
        """
        Positionne les piquages sur le contour exact de l'équipement
        selon leur orientation ('W', 'E', 'N', 'S').
        """
        nozzle_coords_map: Dict[Tuple[str, str], List[float]] = {}
        nozzle_orient_map: Dict[Tuple[str, str], str] = {}

        for eq in equipments:
            tag = eq.get("tag", "")
            bbox = eq["svg_bbox"]
            xmin, ymin, xmax, ymax = bbox
            cx, cy = eq["svg_center"]
            w, h = eq["svg_width"], eq["svg_height"]

            nozzles = eq.get("nozzles", [])
            # Regrouper les nozzles par face pour espacement régulier si multiples
            by_face: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for n in nozzles:
                orient = (n.get("orientation") or "E").upper()
                if orient not in ("W", "E", "N", "S"):
                    orient = "E"
                by_face[orient].append(n)

            # Face Ouest (West - entrée principale gauche)
            west_noz = by_face.get("W", [])
            for idx, n in enumerate(west_noz):
                y_pos = cy if len(west_noz) == 1 else ymin + (idx + 1) * h / (len(west_noz) + 1)
                pt = [xmin, round(y_pos, 1)]
                n["svg_coords"] = pt
                nozzle_coords_map[(tag, n.get("tag", ""))] = pt
                nozzle_orient_map[(tag, n.get("tag", ""))] = "W"

            # Face Est (East - sortie principale droite)
            east_noz = by_face.get("E", [])
            for idx, n in enumerate(east_noz):
                y_pos = cy if len(east_noz) == 1 else ymin + (idx + 1) * h / (len(east_noz) + 1)
                pt = [xmax, round(y_pos, 1)]
                n["svg_coords"] = pt
                nozzle_coords_map[(tag, n.get("tag", ""))] = pt
                nozzle_orient_map[(tag, n.get("tag", ""))] = "E"

            # Face Nord (North - haut)
            north_noz = by_face.get("N", [])
            for idx, n in enumerate(north_noz):
                x_pos = cx if len(north_noz) == 1 else xmin + (idx + 1) * w / (len(north_noz) + 1)
                pt = [round(x_pos, 1), ymin]
                n["svg_coords"] = pt
                nozzle_coords_map[(tag, n.get("tag", ""))] = pt
                nozzle_orient_map[(tag, n.get("tag", ""))] = "N"

            # Face Sud (South - bas)
            south_noz = by_face.get("S", [])
            for idx, n in enumerate(south_noz):
                x_pos = cx if len(south_noz) == 1 else xmin + (idx + 1) * w / (len(south_noz) + 1)
                pt = [round(x_pos, 1), ymax]
                n["svg_coords"] = pt
                nozzle_coords_map[(tag, n.get("tag", ""))] = pt
                nozzle_orient_map[(tag, n.get("tag", ""))] = "S"

        return nozzle_coords_map, nozzle_orient_map

    # -----------------------------------------------------------------------
    # 4. Routage orthogonal Manhattan des circuits
    # -----------------------------------------------------------------------

    def _route_circuits(
        self,
        circuits: List[Dict[str, Any]],
        eq_map: Dict[str, Dict[str, Any]],
        nozzle_coords_map: Dict[Tuple[str, str], List[float]],
        nozzle_orient_map: Dict[Tuple[str, str], str],
        cad_bounds: Tuple[float, float, float, float],
    ) -> List[Dict[str, Any]]:
        """
        Calcule pour chaque circuit un tracé orthogonal strict (H-V, V-H ou H-V-H)
        entre son point de départ et son point d'arrivée.
        """
        routed_circuits: List[Dict[str, Any]] = []

        for c in circuits:
            circ = copy.deepcopy(c)
            from_node = circ.get("from_node", {})
            to_node = circ.get("to_node", {})
            cad_poly = circ.get("polyline", [])

            # Détermination point de départ & orientation de sortie
            p_start, dir_from = self._resolve_endpoint(
                from_node,
                is_start=True,
                cad_poly=cad_poly,
                eq_map=eq_map,
                nozzle_coords=nozzle_coords_map,
                nozzle_orients=nozzle_orient_map,
                cad_bounds=cad_bounds,
            )

            # Détermination point d'arrivée & orientation d'entrée
            p_end, dir_to = self._resolve_endpoint(
                to_node,
                is_start=False,
                cad_poly=cad_poly,
                eq_map=eq_map,
                nozzle_coords=nozzle_coords_map,
                nozzle_orients=nozzle_orient_map,
                cad_bounds=cad_bounds,
            )

            # Calcul du tracé Manhattan
            orthogonal_poly = self._compute_manhattan_path(
                p_start, dir_from, p_end, dir_to
            )

            # Décomposition en segments avec étiquette d'orientation ('H' ou 'V')
            segments = []
            for i in range(len(orthogonal_poly) - 1):
                p1 = orthogonal_poly[i]
                p2 = orthogonal_poly[i + 1]
                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]
                seg_dir = "H" if abs(dx) >= abs(dy) else "V"
                length = math.hypot(dx, dy)
                if length > 1e-3:
                    segments.append({
                        "p1": [round(p1[0], 1), round(p1[1], 1)],
                        "p2": [round(p2[0], 1), round(p2[1], 1)],
                        "dir": seg_dir,
                        "length": round(length, 1),
                        "hops": [],
                    })

            circ["orthogonal_polyline"] = [
                [round(pt[0], 1), round(pt[1], 1)] for pt in orthogonal_poly
            ]
            circ["segments"] = segments
            circ["hops"] = []
            routed_circuits.append(circ)

        return routed_circuits

    def _resolve_endpoint(
        self,
        node: Dict[str, Any],
        is_start: bool,
        cad_poly: List[List[float]],
        eq_map: Dict[str, Dict[str, Any]],
        nozzle_coords: Dict[Tuple[str, str], List[float]],
        nozzle_orients: Dict[Tuple[str, str], str],
        cad_bounds: Tuple[float, float, float, float],
    ) -> Tuple[List[float], str]:
        """Résout le point de raccordement et la direction d'échappement."""
        eq_tag = node.get("equipment_tag")
        noz_tag = node.get("nozzle")

        if eq_tag and eq_tag in eq_map:
            eq = eq_map[eq_tag]
            # 1. Piquage identifié
            if noz_tag and (eq_tag, noz_tag) in nozzle_coords:
                pt = nozzle_coords[(eq_tag, noz_tag)]
                orient = nozzle_orients.get((eq_tag, noz_tag), "E" if is_start else "W")
                return list(pt), orient

            # 2. Piquage par défaut sur l'équipement
            if is_start:
                # Sortie par défaut face Est
                pt = [eq["svg_bbox"][2], eq["svg_center"][1]]
                return pt, "E"
            else:
                # Entrée par défaut face Ouest
                pt = [eq["svg_bbox"][0], eq["svg_center"][1]]
                return pt, "W"

        # Nœud hors équipement (OPEN_HEADER ou TEE_JUNCTION)
        if cad_poly:
            cad_pt = cad_poly[0] if is_start else cad_poly[-1]
            svg_x, svg_y = self._map_cad_to_svg(cad_pt[0], cad_pt[1], cad_bounds)
            # Déduire la direction du premier ou dernier vecteur CAO
            if len(cad_poly) >= 2:
                if is_start:
                    dx = cad_poly[1][0] - cad_poly[0][0]
                    dy = cad_poly[1][1] - cad_poly[0][1]
                else:
                    dx = cad_poly[-1][0] - cad_poly[-2][0]
                    dy = cad_poly[-1][1] - cad_poly[-2][1]
                if abs(dx) >= abs(dy):
                    orient = "E" if dx >= 0 else "W"
                else:
                    orient = "S" if dy <= 0 else "N"  # En CAO Y monte
            else:
                orient = "E" if is_start else "W"
            return [round(svg_x, 1), round(svg_y, 1)], orient

        fallback_x = self.margin_x if is_start else self.canvas_w - self.margin_x
        return [fallback_x, self.canvas_h / 2.0], "E" if is_start else "W"

    def _compute_manhattan_path(
        self,
        p_start: List[float],
        dir_from: str,
        p_end: List[float],
        dir_to: str,
    ) -> List[List[float]]:
        """
        Construit une polyligne orthogonale à angles droits entre p_start et p_end.
        Génère une ligne directe, 2 segments (H-V ou V-H) ou 3 segments (H-V-H / V-H-V).
        """
        x1, y1 = p_start[0], p_start[1]
        x2, y2 = p_end[0], p_end[1]

        # 1. Alignement direct horizontal ou vertical
        if abs(y1 - y2) <= 1.0:
            return [[x1, y1], [x2, y1]]
        if abs(x1 - x2) <= 1.0:
            return [[x1, y1], [x1, y2]]

        # 2. Cas standard écoulement gauche -> droite (H-V-H)
        if dir_from in ("E", "W") and dir_to in ("E", "W"):
            if (dir_from == "E" and x2 > x1 + 10.0) or (dir_from == "W" and x2 < x1 - 10.0):
                mid_x = (x1 + x2) / 2.0
                return [[x1, y1], [mid_x, y1], [mid_x, y2], [x2, y2]]
            else:
                # Boucle de retournement (bypass ou boucle fermée)
                stub = 35.0 if dir_from == "E" else -35.0
                detour_y = min(y1, y2) - 50.0 if min(y1, y2) > 150.0 else max(y1, y2) + 50.0
                return [
                    [x1, y1],
                    [x1 + stub, y1],
                    [x1 + stub, detour_y],
                    [x2 - stub, detour_y],
                    [x2 - stub, y2],
                    [x2, y2],
                ]

        # 3. Cas standard écoulement vertical (V-H-V)
        if dir_from in ("N", "S") and dir_to in ("N", "S"):
            mid_y = (y1 + y2) / 2.0
            return [[x1, y1], [x1, mid_y], [x2, mid_y], [x2, y2]]

        # 4. Virage à 90 degrés H-V (sortie horizontale, entrée verticale)
        if dir_from in ("E", "W") and dir_to in ("N", "S"):
            return [[x1, y1], [x2, y1], [x2, y2]]

        # 5. Virage à 90 degrés V-H (sortie verticale, entrée horizontale)
        if dir_from in ("N", "S") and dir_to in ("E", "W"):
            return [[x1, y1], [x1, y2], [x2, y2]]

        # Repli général H-V-H
        mid_x = (x1 + x2) / 2.0
        return [[x1, y1], [mid_x, y1], [mid_x, y2], [x2, y2]]

    # -----------------------------------------------------------------------
    # 5. Positionnement & orientation des composants en ligne
    # -----------------------------------------------------------------------

    def _place_and_orient_components(
        self,
        circuits: List[Dict[str, Any]],
        valves: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Positionne les vannes et réducteurs sur les segments orthogonaux
        selon leur ratio curviligne et déduit automatiquement leur orientation ('H' ou 'V').
        """
        valve_by_tag: Dict[str, Dict[str, Any]] = {v.get("tag", ""): v for v in valves if v.get("tag")}

        for circ in circuits:
            segments = circ.get("segments", [])
            total_len = sum(s["length"] for s in segments)
            if total_len <= 1e-3:
                continue

            for comp in circ.get("in_line_components", []):
                ratio = float(comp.get("position_ratio", 0.5))
                target_dist = ratio * total_len

                acc = 0.0
                chosen_seg = segments[0]
                seg_t = 0.5

                for s in segments:
                    s_len = s["length"]
                    if acc + s_len >= target_dist or s is segments[-1]:
                        chosen_seg = s
                        seg_t = max(0.0, min(1.0, (target_dist - acc) / s_len)) if s_len > 1e-3 else 0.5
                        break
                    acc += s_len

                p1, p2 = chosen_seg["p1"], chosen_seg["p2"]
                cx = p1[0] + seg_t * (p2[0] - p1[0])
                cy = p1[1] + seg_t * (p2[1] - p1[1])

                comp["svg_coords"] = [round(cx, 1), round(cy, 1)]
                comp["orientation"] = chosen_seg["dir"]  # 'H' ou 'V'

                # Mise à jour synchronisée de la liste globale des vannes
                vtag = comp.get("tag", "")
                if vtag in valve_by_tag:
                    valve_by_tag[vtag]["svg_coords"] = [round(cx, 1), round(cy, 1)]
                    valve_by_tag[vtag]["orientation"] = chosen_seg["dir"]

        # Traitement des vannes rattachées par circuit_id mais non présentes dans in_line_components
        circ_by_id = {c.get("line_id"): c for c in circuits if c.get("line_id")}
        for v in valves:
            if "svg_coords" not in v:
                cid = v.get("circuit_id")
                ratio = float(v.get("position_ratio") or 0.5)
                if cid and cid in circ_by_id:
                    c = circ_by_id[cid]
                    segs = c.get("segments", [])
                    tot = sum(s["length"] for s in segs)
                    if tot > 0:
                        target = ratio * tot
                        acc = 0.0
                        for s in segs:
                            if acc + s["length"] >= target or s is segs[-1]:
                                st = max(0.0, min(1.0, (target - acc) / s["length"])) if s["length"] > 0 else 0.5
                                p1, p2 = s["p1"], s["p2"]
                                v["svg_coords"] = [round(p1[0] + st * (p2[0] - p1[0]), 1), round(p1[1] + st * (p2[1] - p1[1]), 1)]
                                v["orientation"] = s["dir"]
                                break
                            acc += s["length"]
                if "svg_coords" not in v:
                    # Coordonnées par défaut au centre
                    v["svg_coords"] = [self.canvas_w / 2.0, self.canvas_h / 2.0]
                    v["orientation"] = "H"

        return valves

    # -----------------------------------------------------------------------
    # 6. Détection des croisements et ponts d'enjambement (Hops)
    # -----------------------------------------------------------------------

    def _detect_and_build_hops(self, circuits: List[Dict[str, Any]]) -> int:
        """
        Détecte les intersections orthogonales entre circuits distincts.
        Génère les ponts d'enjambement (arcs) sur les lignes verticales.
        """
        total_hops = 0
        eps = 6.0  # Tolérance d'écartement des extrémités pour ne pas confondre avec des tés

        # Collecter tous les segments horizontaux et verticaux
        h_segments: List[Tuple[str, Dict[str, Any]]] = []
        v_segments: List[Tuple[str, Dict[str, Any]]] = []

        for c in circuits:
            cid = c.get("line_id", "")
            for s in c.get("segments", []):
                if s["dir"] == "H":
                    h_segments.append((cid, s))
                else:
                    v_segments.append((cid, s))

        # Vérification des intersections
        for v_cid, v_seg in v_segments:
            vx = v_seg["p1"][0]
            vy_min = min(v_seg["p1"][1], v_seg["p2"][1])
            vy_max = max(v_seg["p1"][1], v_seg["p2"][1])
            v_dir_sign = 1 if v_seg["p2"][1] >= v_seg["p1"][1] else -1

            detected_hops_for_v: List[Tuple[float, Dict[str, Any]]] = []

            for h_cid, h_seg in h_segments:
                if v_cid == h_cid:
                    continue  # Même circuit

                hy = h_seg["p1"][1]
                hx_min = min(h_seg["p1"][0], h_seg["p2"][0])
                hx_max = max(h_seg["p1"][0], h_seg["p2"][0])

                # Condition d'intersection stricte
                if (hx_min + eps < vx < hx_max - eps) and (vy_min + eps < hy < vy_max - eps):
                    hop_obj = {
                        "crossing_point": [round(vx, 1), round(hy, 1)],
                        "crossed_circuit_id": h_cid,
                        "radius": self.hop_radius,
                        "y_crossing": hy,
                        "axis": "V",
                        "sweep": 1,  # Arc bombé vers la droite (+X)
                    }
                    detected_hops_for_v.append((hy, hop_obj))
                    total_hops += 1

            if detected_hops_for_v:
                # Trier les hops dans le sens de parcours du segment vertical
                detected_hops_for_v.sort(key=lambda item: item[0] * v_dir_sign)
                v_seg["hops"] = [item[1] for item in detected_hops_for_v]

        return total_hops

    # -----------------------------------------------------------------------
    # 7. Positionnement des instruments ISA-5.1
    # -----------------------------------------------------------------------

    def _place_instruments(
        self,
        instruments: List[Dict[str, Any]],
        circuits: List[Dict[str, Any]],
        eq_map: Dict[str, Dict[str, Any]],
        cad_bounds: Tuple[float, float, float, float],
    ) -> List[Dict[str, Any]]:
        """
        Positionne les bulles d'instruments ISA-5.1 avec leur ligne de raccordement en tirets.
        """
        routed_inst: List[Dict[str, Any]] = []
        circ_by_id = {c.get("line_id"): c for c in circuits if c.get("line_id")}

        for idx, inst in enumerate(instruments):
            in_obj = copy.deepcopy(inst)
            cid = in_obj.get("circuit_id")
            bubble_offset_y = -45.0  # Au-dessus de la ligne

            if cid and cid in circ_by_id:
                circ = circ_by_id[cid]
                segs = circ.get("segments", [])
                if segs:
                    # Placer l'instrument au milieu du premier segment horizontal significatif
                    target_seg = next((s for s in segs if s["dir"] == "H" and s["length"] > 30.0), segs[0])
                    p1, p2 = target_seg["p1"], target_seg["p2"]
                    attach_x = round((p1[0] + p2[0]) / 2.0, 1)
                    attach_y = round((p1[1] + p2[1]) / 2.0, 1)

                    bubble_x = attach_x
                    bubble_y = round(attach_y + bubble_offset_y, 1)

                    in_obj["svg_coords"] = [bubble_x, bubble_y]
                    in_obj["leader_line"] = [
                        [attach_x, attach_y],
                        [bubble_x, bubble_y + 14.0],  # Contact bas de la bulle r=14
                    ]
            else:
                # Repli sur coordonnées CAO normalisées
                cad_pos = in_obj.get("cad_coords") or [0.0, 0.0]
                svg_x, svg_y = self._map_cad_to_svg(cad_pos[0], cad_pos[1], cad_bounds)
                in_obj["svg_coords"] = [round(svg_x, 1), round(svg_y, 1)]
                in_obj["leader_line"] = None

            routed_inst.append(in_obj)

        return routed_inst


def route_pid_topology(
    topology_data: Dict[str, Any],
    canvas_w: float = 1600.0,
    canvas_h: float = 1000.0,
) -> Dict[str, Any]:
    """
    Fonction utilitaire autonome pour exécuter le routage topologique orthogonal.

    Args:
        topology_data: Dictionnaire topologique issu de dxf_to_pid_json.py.
        canvas_w: Largeur du canvas SVG en pixels (défaut: 1600.0).
        canvas_h: Hauteur du canvas SVG en pixels (défaut: 1000.0).

    Returns:
        Dictionnaire enrichi avec les tracés orthogonaux et métadonnées de rendu.
    """
    router = PidOrthogonalRouter(canvas_width=canvas_w, canvas_height=canvas_h)
    return router.layout_and_route(topology_data)
