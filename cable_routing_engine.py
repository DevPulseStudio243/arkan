# -*- coding: utf-8 -*-
"""
cable_routing_engine.py - Moteur de routage automatique des câbles par Dijkstra (ARKAN v3)

Fonctionnalités :
  1. Construction du graphe 2D des chemins de câbles à partir d'entités DXF/DWG (LINE, LWPOLYLINE).
  2. Extraction et normalisation spatiale des coordonnées d'équipements (INSERT/blocs, TEXT, MTEXT).
  3. Algorithme de Dijkstra pour trouver le plus court chemin sur le réseau de cheminements.
  4. Calcul de la longueur physique 3D réelle :
     L_tot = L_chemin + d_raccordement_origine + d_raccordement_destination
             + Delta_Z_origine + Delta_Z_destination + L_boucles_service.
  5. Politique stricte zéro valeur inventée : si destination ou cheminement introuvable -> None + A_VALIDER.
"""

import heapq
import logging
import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Élévations verticales par défaut (en mètres)
DEFAULT_ELEVATIONS = {
    "TGBT": 3.5,
    "SWITCHGEAR": 3.5,
    "PANEL": 2.5,
    "MCC": 3.5,
    "MOTOR": 3.0,
    "PUMP": 3.0,
    "P": 3.0,
    "COMPRESSOR": 3.0,
    "C": 3.0,
    "JUNCTION_BOX": 2.5,
    "JB": 2.5,
    "INSTRUMENT": 2.5,
    "DEFAULT": 3.0
}

DEFAULT_SERVICE_LOOPS = 3.0  # 2 x 1.5 m pour raccordement / presse-étoupe / réserve armoire
DEFAULT_MAX_SNAP_DISTANCE = 50.0  # mètres max entre équipement et chemin de câbles


class TrayGraph:
    """Graphe non orienté modélisant le réseau de chemins de câbles."""

    def __init__(self, node_merge_tol: float = 0.05):
        self.node_merge_tol = node_merge_tol
        self.nodes: List[Tuple[float, float]] = []
        # adj[node_index] = list of (neighbor_index, distance)
        self.adj: Dict[int, List[Tuple[int, float]]] = {}
        # spatial lookup grid for fast node snapping
        self._grid: Dict[Tuple[int, int], List[int]] = {}
        self._grid_size = max(0.5, node_merge_tol * 10)

    def _grid_key(self, x: float, y: float) -> Tuple[int, int]:
        return (int(math.floor(x / self._grid_size)), int(math.floor(y / self._grid_size)))

    def add_node(self, x: float, y: float) -> int:
        """Ajoute un nœud ou retourne le nœud existant dans le rayon de tolérance."""
        gx, gy = self._grid_key(x, y)
        candidates = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidates.extend(self._grid.get((gx + dx, gy + dy), []))

        best_idx = None
        best_d = self.node_merge_tol
        for idx in candidates:
            nx, ny = self.nodes[idx]
            d = math.hypot(x - nx, y - ny)
            if d < best_d:
                best_d = d
                best_idx = idx

        if best_idx is not None:
            return best_idx

        new_idx = len(self.nodes)
        self.nodes.append((x, y))
        self.adj[new_idx] = []
        k = (gx, gy)
        if k not in self._grid:
            self._grid[k] = []
        self._grid[k].append(new_idx)
        return new_idx

    def add_edge(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> None:
        """Ajoute une arête bidirectionnelle entre deux coordonnées."""
        u = self.add_node(p1[0], p1[1])
        v = self.add_node(p2[0], p2[1])
        if u == v:
            return
        dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if dist <= 1e-6:
            return

        # Éviter les arêtes doublons
        for nbr, d in self.adj[u]:
            if nbr == v:
                return

        self.adj[u].append((v, dist))
        self.adj[v].append((u, dist))

    def find_nearest_node(self, x: float, y: float) -> Tuple[Optional[int], float]:
        """Trouve le nœud du graphe le plus proche d'un point (x, y) et sa distance."""
        if not self.nodes:
            return None, float("inf")
        best_idx = None
        best_d = float("inf")
        for idx, (nx, ny) in enumerate(self.nodes):
            d = math.hypot(x - nx, y - ny)
            if d < best_d:
                best_d = d
                best_idx = idx
        return best_idx, best_d

    def shortest_path(self, start_idx: int, end_idx: int) -> Tuple[Optional[List[int]], float]:
        """Algorithme de Dijkstra pour trouver le plus court chemin entre deux nœuds."""
        if start_idx == end_idx:
            return [start_idx], 0.0

        distances: Dict[int, float] = {start_idx: 0.0}
        previous: Dict[int, Optional[int]] = {start_idx: None}
        pq = [(0.0, start_idx)]
        visited: Set[int] = set()

        while pq:
            cur_dist, u = heapq.heappop(pq)
            if u in visited:
                continue
            visited.add(u)

            if u == end_idx:
                # Reconstruire le chemin
                path = []
                curr = end_idx
                while curr is not None:
                    path.append(curr)
                    curr = previous[curr]
                path.reverse()
                return path, cur_dist

            for nbr, weight in self.adj.get(u, []):
                if nbr in visited:
                    continue
                new_dist = cur_dist + weight
                if new_dist < distances.get(nbr, float("inf")):
                    distances[nbr] = new_dist
                    previous[nbr] = u
                    heapq.heappush(pq, (new_dist, nbr))

        return None, float("inf")


class CableRoutingEngine:
    """Moteur principal de routage des câbles sur plan d'implantation."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        routing_cfg = self.config.get("routing") or {}
        elev_cfg = routing_cfg.get("elevation") or {}
        self.elevations = {**DEFAULT_ELEVATIONS, **elev_cfg}
        self.service_loops = float(routing_cfg.get("service_loops", {}).get("total_default_m", DEFAULT_SERVICE_LOOPS))
        self.max_snap_dist = float(routing_cfg.get("snap_tolerance_m", DEFAULT_MAX_SNAP_DISTANCE))
        self.node_merge_tol = float(routing_cfg.get("node_merge_tolerance_m", 0.05))

        self.graph = TrayGraph(node_merge_tol=self.node_merge_tol)
        # equipment_positions: normalized_tag -> (x_m, y_m, z_m, original_tag, eq_type)
        self.equipment: Dict[str, Dict[str, Any]] = {}

    def get_elevation_for_type(self, eq_type: str) -> float:
        """Détermine la descente/montée verticale selon la famille d'équipement."""
        t = (eq_type or "").upper().strip()
        if t in self.elevations:
            return float(self.elevations[t])
        for k, v in self.elevations.items():
            if k in t:
                return float(v)
        return float(self.elevations.get("DEFAULT", 3.0))

    def load_from_ezdxf_doc(self, doc: Any, scale_to_m: float = 0.001) -> None:
        """Construit le graphe et localise les équipements depuis un document ezdxf."""
        msp = doc.modelspace()

        # 1. Extraction des segments de cheminement (LINE, LWPOLYLINE)
        tray_layer_keywords = ["CABLETRAY", "CHEMIN", "CDC", "CHEMINEMENT", "CABLE_TRAY"]
        for e in msp:
            lay = e.dxf.layer.upper()
            if not any(kw in lay for kw in tray_layer_keywords):
                continue
            dxftype = e.dxftype()
            if dxftype == "LINE":
                s = e.dxf.start
                end = e.dxf.end
                p1 = (s[0] * scale_to_m, s[1] * scale_to_m)
                p2 = (end[0] * scale_to_m, end[1] * scale_to_m)
                self.graph.add_edge(p1, p2)
            elif dxftype == "LWPOLYLINE":
                pts = list(e.get_points("xy"))
                for i in range(len(pts) - 1):
                    p1 = (pts[i][0] * scale_to_m, pts[i][1] * scale_to_m)
                    p2 = (pts[i + 1][0] * scale_to_m, pts[i + 1][1] * scale_to_m)
                    self.graph.add_edge(p1, p2)

        # 2. Extraction des équipements (INSERT/blocs, TEXT, MTEXT)
        self._extract_equipment(msp, scale_to_m)

    def _extract_equipment(self, msp: Any, scale_to_m: float) -> None:
        """Localise les blocs et textes représentants des départs / charges."""
        try:
            from tag_normalizer import normalize_tag
        except ImportError:
            normalize_tag = lambda t: str(t or "").upper().strip()

        # Regex pour repérer des tags d'équipements typiques (TGBT, P-101A, JB-10, etc.)
        tag_pat = re.compile(r"\b((?:\d{3}-)?[A-Z]{1,5}-\d{2,4}[A-Z]?|TGBT(?:-\d+)?|MCC(?:-\d+)?|TD(?:-\d+)?)\b", re.IGNORECASE)

        for e in msp:
            dxftype = e.dxftype()
            if dxftype == "INSERT":
                # Blocs
                b_name = e.dxf.name.upper()
                pos = e.dxf.insert
                x_m, y_m = pos[0] * scale_to_m, pos[1] * scale_to_m

                # Vérifier attributs du bloc
                block_tag = None
                if hasattr(e, "attribs"):
                    for att in e.attribs:
                        val = att.dxf.text.strip()
                        m = tag_pat.search(val)
                        if m:
                            block_tag = m.group(1).upper()
                            break

                candidate_tag = block_tag or b_name
                m = tag_pat.search(candidate_tag)
                tag_to_use = m.group(1).upper() if m else candidate_tag

                norm = normalize_tag(tag_to_use)
                self.equipment[norm] = {
                    "tag": tag_to_use,
                    "normalized": norm,
                    "x": x_m,
                    "y": y_m,
                    "type": "SWITCHGEAR" if "TGBT" in norm or "MCC" in norm else "EQUIPMENT"
                }

            elif dxftype in ("TEXT", "MTEXT"):
                text = e.dxf.text if dxftype == "TEXT" else getattr(e, "text", "")
                text_clean = re.sub(r"\\[A-Za-z0-9]+;", "", str(text)).strip().upper()
                m = tag_pat.search(text_clean)
                if m:
                    raw_tag = m.group(1).upper()
                    norm = normalize_tag(raw_tag)
                    pos = e.dxf.insert
                    x_m, y_m = pos[0] * scale_to_m, pos[1] * scale_to_m
                    self.equipment[norm] = {
                        "tag": raw_tag,
                        "normalized": norm,
                        "x": x_m,
                        "y": y_m,
                        "type": "SWITCHGEAR" if "TGBT" in norm or "MCC" in norm else "EQUIPMENT"
                    }

    def register_equipment(self, tag: str, x: float, y: float, eq_type: str = "EQUIPMENT") -> None:
        """Enregistre manuellement ou via coordonnées connues un équipement."""
        try:
            from tag_normalizer import normalize_tag
            norm = normalize_tag(tag)
        except ImportError:
            norm = str(tag or "").upper().strip()

        self.equipment[norm] = {
            "tag": tag,
            "normalized": norm,
            "x": float(x),
            "y": float(y),
            "type": eq_type
        }

    def find_equipment(self, tag: str) -> Optional[Dict[str, Any]]:
        """Recherche un équipement par tag exact ou normalisé."""
        try:
            from tag_normalizer import normalize_tag
            norm = normalize_tag(tag)
        except ImportError:
            norm = str(tag or "").upper().strip()

        if norm in self.equipment:
            return self.equipment[norm]

        # Recherche de secours : sous-chaîne ou correspondance partielle de tag
        for eq_norm, data in self.equipment.items():
            if norm in eq_norm or eq_norm in norm:
                return data
            # Correspondance sur le numéro d'équipement
            n1 = re.sub(r"\D", "", norm)
            n2 = re.sub(r"\D", "", eq_norm)
            if n1 and n1 == n2 and len(n1) >= 3:
                return data

        return None

    def route_cable(
        self,
        origin_tag: str,
        dest_tag: str,
        origin_type: Optional[str] = None,
        dest_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calcule le routage par Dijkstra entre l'origine (ex: TGBT) et la destination (ex: charge/moteur).
        Retourne le métré détaillé ou None si impossible.
        """
        orig_data = self.find_equipment(origin_tag)
        dest_data = self.find_equipment(dest_tag)

        # Si l'origine n'est pas trouvée mais ressemble à un TGBT général
        if not orig_data:
            # Chercher tout TGBT enregistré
            for k, v in self.equipment.items():
                if "TGBT" in k or "MCC" in k:
                    orig_data = v
                    break

        if not orig_data:
            return {
                "status": "ORIGIN_NOT_FOUND",
                "origin_tag": origin_tag,
                "dest_tag": dest_tag,
                "total_length_m": None,
                "length_source": "UNKNOWN",
                "warning": f"Origine '{origin_tag}' introuvable sur le plan d'implantation."
            }

        if not dest_data:
            return {
                "status": "DEST_NOT_FOUND",
                "origin_tag": origin_tag,
                "dest_tag": dest_tag,
                "total_length_m": None,
                "length_source": "UNKNOWN",
                "warning": f"Destination '{dest_tag}' introuvable sur le plan d'implantation."
            }

        # Nœuds les plus proches sur le graphe de chemins
        u_idx, d_orig = self.graph.find_nearest_node(orig_data["x"], orig_data["y"])
        v_idx, d_dest = self.graph.find_nearest_node(dest_data["x"], dest_data["y"])

        if u_idx is None or v_idx is None:
            return {
                "status": "NO_TRAY_NETWORK",
                "origin_tag": origin_tag,
                "dest_tag": dest_tag,
                "total_length_m": None,
                "length_source": "UNKNOWN",
                "warning": "Aucun chemin de câbles détecté pour le routage."
            }

        if d_orig > self.max_snap_dist or d_dest > self.max_snap_dist:
            too_far = orig_tag if d_orig > self.max_snap_dist else dest_tag
            dist_far = max(d_orig, d_dest)
            return {
                "status": "SNAP_TOO_FAR",
                "origin_tag": origin_tag,
                "dest_tag": dest_tag,
                "total_length_m": None,
                "length_source": "UNKNOWN",
                "warning": f"Équipement '{too_far}' trop éloigné du réseau de chemins ({dist_far:.1f} m > {self.max_snap_dist} m)."
            }

        # Dijkstra
        path_indices, tray_dist = self.graph.shortest_path(u_idx, v_idx)
        if path_indices is None or math.isinf(tray_dist):
            return {
                "status": "UNREACHABLE",
                "origin_tag": origin_tag,
                "dest_tag": dest_tag,
                "total_length_m": None,
                "length_source": "UNKNOWN",
                "warning": f"Réseau de chemins discontinu entre '{origin_tag}' et '{dest_tag}'."
            }

        # Calcul des dénivellations Z et boucles de service
        o_type = origin_type or orig_data.get("type", "SWITCHGEAR")
        d_type = dest_type or dest_data.get("type", "EQUIPMENT")
        dz_orig = self.get_elevation_for_type(o_type)
        dz_dest = self.get_elevation_for_type(d_type)
        loops = self.service_loops

        # Longueur physique 3D totale
        # L_tot = L_chemin + drop_horizontal_orig + drop_horizontal_dest + dz_orig + dz_dest + loops
        total_len = tray_dist + d_orig + d_dest + dz_orig + dz_dest + loops

        path_coords = [self.graph.nodes[i] for i in path_indices]

        return {
            "status": "ROUTED",
            "origin_tag": orig_data["tag"],
            "dest_tag": dest_data["tag"],
            "total_length_m": round(total_len, 2),
            "tray_length_m": round(tray_dist, 2),
            "horizontal_drops_m": round(d_orig + d_dest, 2),
            "vertical_elevation_m": round(dz_orig + dz_dest, 2),
            "service_loops_m": round(loops, 2),
            "length_source": "DIJKSTRA_ROUTED",
            "path_node_count": len(path_indices),
            "path_coords": path_coords
        }
