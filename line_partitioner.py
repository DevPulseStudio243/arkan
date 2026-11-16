"""
line_partitioner.py
====================
PROBLÈME RÉSOLU ICI : sur un vrai P&ID, la tuyauterie physique est souvent
connectée en un seul réseau continu (piquages, tés, changements de diamètre)
qui ne correspond PAS à une seule "ligne" au sens process. Le numéro de ligne
change à chaque té, changement de spec ou de diamètre — sans qu'il y ait de
rupture physique dans le dessin. Un simple union-find sur la connectivité
géométrique (ce que fait TopologyBuilder) fusionne alors tout le réseau
connecté en un seul "cheminement", ce qui n'a aucun sens process (une ligne
avec 47 vannes n'existe pas dans la réalité industrielle).

La solution : partitionner les segments par le numéro de ligne le plus proche
"le long du tuyau" (pas à vol d'oiseau) via un Dijkstra multi-sources, où
chaque label de ligne valide (motif GCB, ex: '20"-LP-1ACX1PN-201-N') sert de
source. Chaque segment est ensuite attribué à la ligne dont le label est
géométriquement le plus proche EN SUIVANT LE RÉSEAU DE TUYAUTERIE, exactement
comme le ferait un ingénieur qui suit le tracé du tuyau des yeux jusqu'au
prochain numéro de ligne affiché.
"""

from __future__ import annotations

import heapq
import math
from typing import Any, Dict, List, Tuple

Segment = Tuple[Tuple[float, float], Tuple[float, float], Dict[str, Any]]


def _quantize(pt: Tuple[float, float], grid: float) -> Tuple[float, float]:
    return (round(pt[0] / grid) * grid, round(pt[1] / grid) * grid)


def _seg_length(s: Segment) -> float:
    return math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1])


def _dist_point_to_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def partition_segments_by_line_label(
    segments: List[Segment],
    line_labels: List[Dict[str, Any]],
    connection_tolerance: float = 30.0,
    max_seed_distance: float = 350.0,
) -> Dict[str, List[Segment]]:
    """
    line_labels : labels déjà filtrés pour ne contenir QUE des tags de ligne
                  plausibles (motif GCB avec tirets), pas toutes les étiquettes.
    Retourne : { line_tag: [segments assignés à cette ligne] }
    """
    if not segments:
        return {}

    n = len(segments)
    grid = max(connection_tolerance, 1e-6)

    # Graphe d'adjacence : deux segments sont voisins s'ils partagent une
    # extrémité (à la tolérance de connexion près).
    node_of: Dict[Tuple[float, float], List[int]] = {}
    for i, s in enumerate(segments):
        for endpoint in (s[0], s[1]):
            node_of.setdefault(_quantize(endpoint, grid), []).append(i)

    adjacency: Dict[int, List[Tuple[int, float]]] = {i: [] for i in range(n)}
    for idx_list in node_of.values():
        for a in idx_list:
            for b in idx_list:
                if a != b:
                    adjacency[a].append((b, (_seg_length(segments[a]) + _seg_length(segments[b])) / 2.0))

    # Sources : pour chaque label de ligne valide, le segment géométriquement
    # le plus proche (s'il est à portée raisonnable du label).
    seeds: Dict[int, str] = {}
    for lbl in line_labels:
        tag = lbl.get("text", "").strip()
        if not tag:
            continue
        lx, ly = lbl["x"], lbl["y"]
        best_idx, best_dist = None, float("inf")
        for i, s in enumerate(segments):
            d = _dist_point_to_segment(lx, ly, s[0][0], s[0][1], s[1][0], s[1][1])
            if d < best_dist:
                best_dist, best_idx = d, i
        if best_idx is not None and best_dist <= max_seed_distance:
            # Si deux labels revendiquent le même segment le plus proche, on garde
            # celui déjà géométriquement le plus proche (évite d'écraser un meilleur match).
            if best_idx not in seeds or best_dist < seeds.get(f"__dist_{best_idx}", float("inf")):
                seeds[best_idx] = tag
                seeds[f"__dist_{best_idx}"] = best_dist  # stocké temporairement, nettoyé plus bas

    seeds = {k: v for k, v in seeds.items() if isinstance(k, int)}

    if not seeds:
        # Aucun label exploitable : on ne partitionne pas, tout reste dans un
        # groupe unique "UNPARTITIONED" (comportement identique à avant).
        return {"UNPARTITIONED": segments}

    # Dijkstra multi-sources : chaque segment est atteint par la ligne dont le
    # label est le plus proche EN DISTANCE CUMULÉE LE LONG DU RÉSEAU, pas à vol d'oiseau.
    dist: Dict[int, float] = {i: float("inf") for i in range(n)}
    owner: Dict[int, str] = {}
    pq: List[Tuple[float, int]] = []
    for idx, tag in seeds.items():
        dist[idx] = 0.0
        owner[idx] = tag
        heapq.heappush(pq, (0.0, idx))

    visited = set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        for v, w in adjacency[u]:
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                owner[v] = owner[u]
                heapq.heappush(pq, (nd, v))

    partitions: Dict[str, List[Segment]] = {}
    unassigned = []
    for i, s in enumerate(segments):
        tag = owner.get(i)
        if tag is None:
            unassigned.append(s)
        else:
            partitions.setdefault(tag, []).append(s)

    if unassigned:
        partitions["UNPARTITIONED"] = unassigned

    return partitions


def assign_blocks_to_partitions(
    segments: List[Segment], partitions: Dict[str, List[Segment]], blocks: List[Dict[str, Any]],
    max_assign_distance: float = 500.0,
) -> Dict[int, str]:
    """
    RÉSOUT LE PROBLÈME DES VANNES DUPLIQUÉES ENTRE LIGNES PARALLÈLES.

    Avant : chaque ligne cherchait ses composants "par rayon" parmi TOUS les
    blocs du plan. Si deux tuyaux parallèles sont plus proches l'un de l'autre
    que ce rayon, une même vanne était attribuée aux deux lignes à la fois.

    Maintenant : chaque bloc est rattaché au SEGMENT DE TUYAUTERIE le plus
    proche (peu importe la distance, on prend le plus proche, point), puis
    hérite de la partition (donc de la ligne) à laquelle ce segment
    appartient. Un segment n'appartenant qu'à une seule ligne par
    construction (partition_segments_by_line_label), une vanne ne peut plus
    être partagée entre deux lignes parallèles : elle suit son tuyau, pas un
    rayon arbitraire.

    Retourne : { index_du_bloc_dans_la_liste_blocks : tag_de_ligne }
    (les blocs sans segment raisonnablement proche, ex: cartouche, ne sont
    pas dans le dict retourné).
    """
    seg_to_tag: Dict[Tuple, str] = {}
    for tag, segs in partitions.items():
        for s in segs:
            seg_to_tag[(s[0], s[1])] = tag

    assignment: Dict[int, str] = {}
    for i, b in enumerate(blocks):
        bx, by = b["x"], b["y"]
        best_seg, best_dist = None, float("inf")
        for s in segments:
            d = _dist_point_to_segment(bx, by, s[0][0], s[0][1], s[1][0], s[1][1])
            if d < best_dist:
                best_dist, best_seg = d, s
        if best_seg is not None and best_dist <= max_assign_distance:
            tag = seg_to_tag.get((best_seg[0], best_seg[1]))
            if tag and tag != "UNPARTITIONED":
                assignment[i] = tag

    return assignment


# Compatibility alias for code expecting assign_blocks_to_line_partitions
def assign_blocks_to_line_partitions(
    blocks: List[Dict[str, Any]],
    partitions: Dict[str, List[Segment]],
    max_search_radius: float = 500.0
) -> Dict[int, str]:
    segments = []
    for segs in partitions.values():
        segments.extend(segs)
    idx_map = assign_blocks_to_partitions(segments, partitions, blocks, max_assign_distance=max_search_radius)
    res = {}
    for idx, tag in idx_map.items():
        res[id(blocks[idx])] = tag
        res[idx] = tag
    return res
