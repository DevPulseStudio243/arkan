"""
circuit_graph.py
================
Graphe de circuits de tuyauterie construit à partir de segments vectoriels.

Remplace la partie "composantes connexes" de PipingTopologyTracer.trace_drawing, où UNE composante
connexe devenait UNE ligne (un té fusionnait donc deux lignes en une seule entrée).

Ici :
  * les segments sont coupés aux jonctions en T (extrémité posée sur le milieu d'un autre segment) ;
  * une LIGNE (chain) = tronçon entre deux nœuds "terminaux" (équipement, extrémité libre, té) ;
  * les vannes ponts (symbole qui interrompt le tracé) ou posées sur le tracé sont rangées dans l'ordre
    de l'abscisse curviligne le long de la ligne ;
  * un CIRCUIT = ensemble de lignes reliées par des tés/vannes, arrêté aux équipements ;
  * trace(x, y) renvoie la ligne ou le circuit sous un point (pour le surlignage dans l'interface).

Les unités sont celles des coordonnées d'entrée (points PDF, mm DXF...) : règle snap_tol en conséquence.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import networkx as nx
import numpy as np
from scipy.spatial import cKDTree

from piping_topology_tracer import decode_gcb_pipe_spec, parse_line_tag

Pt = Tuple[float, float]

_SOURCE_RE = re.compile(r"^(PP|P|K|PL)[-\s]?\d")   # pompes, compresseurs, gares de lancement
_SINK_RE = re.compile(r"^(FL|TK|PR)[-\s]?\d")      # torches, bacs, gares de réception
_AREA_RE = re.compile(r"^\d{2,4}[-_\s]")             # préfixe de zone : 201-PP-001/A -> PP-001/A


def _role_tag(tag: str) -> str:
    """Tag d'équipement sans préfixe de zone, en majuscules, pour reconnaître son rôle (source / puits).
    Sans cela, 201-PP-001/A ne correspondait jamais à _SOURCE_RE et le sens d'écoulement restait indéterminé."""
    return _AREA_RE.sub("", (tag or "").strip().upper())


@dataclass
class Symbol:
    kind: str            # "valve" | "equipment" | "instrument" | "arrow"
    x: float
    y: float
    w: float = 0.0
    h: float = 0.0
    tag: str = ""
    ux: float = 0.0      # direction (flèches)
    uy: float = 0.0


class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, a: int) -> int:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def split_at_junctions(segments: Sequence[Tuple[Pt, Pt]], tol: float, max_rounds: int = 4) -> List[Tuple[Pt, Pt]]:
    """Coupe tout segment dont l'intérieur est touché (à tol près) par l'extrémité d'un autre segment.
    Deux segments qui se croisent sans extrémité sur l'autre ne sont PAS connectés."""
    segs = [(tuple(a), tuple(b)) for a, b in segments if math.dist(a, b) > 1e-9]
    for _ in range(max_rounds):
        if not segs:
            break
        A = np.array([s[0] for s in segs], float)
        B = np.array([s[1] for s in segs], float)
        D = B - A
        L2 = np.maximum((D ** 2).sum(1), 1e-12)
        cuts: Dict[int, List[Pt]] = {}
        for i in range(len(segs)):
            for P in (A[i], B[i]):
                t = np.clip(((P - A) * D).sum(1) / L2, 0.0, 1.0)
                proj = A + t[:, None] * D
                d = np.hypot(*(proj - P).T)
                for j in np.where(d <= tol)[0]:
                    if j == i:
                        continue
                    if math.dist(P, A[j]) > tol and math.dist(P, B[j]) > tol:
                        cuts.setdefault(int(j), []).append((float(proj[j][0]), float(proj[j][1])))
        if not cuts:
            break
        out: List[Tuple[Pt, Pt]] = []
        for j, s in enumerate(segs):
            if j not in cuts:
                out.append(s)
                continue
            a = np.array(s[0])
            d = np.array(s[1]) - a
            pts = sorted({round(float(((np.array(p) - a) @ d) / (d @ d)), 4): p for p in cuts[j]}.items())
            chain = [s[0]] + [p for _, p in pts] + [s[1]]
            out.extend((chain[k], chain[k + 1]) for k in range(len(chain) - 1) if math.dist(chain[k], chain[k + 1]) > 1e-9)
        segs = out
    return segs


def _dist_point_segments(p: Pt, A: np.ndarray, B: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    P = np.array(p, float)
    D = B - A
    t = np.clip(((P - A) * D).sum(1) / np.maximum((D ** 2).sum(1), 1e-12), 0.0, 1.0)
    proj = A + t[:, None] * D
    return np.hypot(*(proj - P).T), t


class CircuitGraph:
    def __init__(self, segments: Sequence[Tuple[Pt, Pt]], symbols: Iterable[Symbol] = (),
                 labels: Iterable[Dict[str, Any]] = (), snap_tol: float = 1.0, bridge_margin: float = 4.0,
                 label_radius: float = 60.0, arrow_tol: float = 8.0, equipment_margin: float = 2.0):
        self.snap_tol = snap_tol
        self.symbols = list(symbols)
        self.segments = split_at_junctions(segments, snap_tol)
        self.warnings: List[str] = []
        self._build(bridge_margin, equipment_margin)
        self._assign_chains(list(labels), label_radius, arrow_tol)
        self._assign_circuits()

    # ------------------------------------------------------------------ construction
    def _build(self, bridge_margin: float, eq_margin: float) -> None:
        n = len(self.segments)
        self._A = np.array([s[0] for s in self.segments], float).reshape(-1, 2)
        self._B = np.array([s[1] for s in self.segments], float).reshape(-1, 2)
        pts = np.vstack([self._A, self._B]) if n else np.zeros((0, 2))
        uf = _UF(2 * n)
        if n:
            for i, j in cKDTree(pts).query_pairs(self.snap_tol):
                uf.union(i, j)
        count: Dict[int, int] = {}
        for k in range(2 * n):
            count[uf.find(k)] = count.get(uf.find(k), 0) + 1
        dangling = [k for k in range(2 * n) if count[uf.find(k)] == 1]

        bridged: List[Tuple[Symbol, int]] = []
        self._edge_symbols: Dict[int, List[Tuple[float, Symbol]]] = {}
        for sym in (s for s in self.symbols if s.kind == "valve"):
            hw, hh = sym.w / 2 + bridge_margin, sym.h / 2 + bridge_margin
            inside = [k for k in dangling if abs(pts[k][0] - sym.x) <= hw and abs(pts[k][1] - sym.y) <= hh]
            if len(inside) >= 2:
                for k in inside[1:]:
                    uf.union(inside[0], k)
                bridged.append((sym, inside[0]))
            elif n:
                d, t = _dist_point_segments((sym.x, sym.y), self._A, self._B)
                i = int(np.argmin(d))
                if d[i] <= max(sym.h, sym.w) / 2 + bridge_margin:
                    self._edge_symbols.setdefault(i, []).append((float(t[i]), sym))
                else:
                    self.warnings.append(f"Vanne {sym.tag or (round(sym.x), round(sym.y))} non rattachée au tracé")

        root = [uf.find(k) for k in range(2 * n)]
        members: Dict[int, List[int]] = {}
        for k, r in enumerate(root):
            members.setdefault(r, []).append(k)
        G = nx.MultiGraph()
        for r, ks in members.items():
            xy = pts[ks].mean(axis=0)
            G.add_node(r, xy=(float(xy[0]), float(xy[1])), terminal=None, symbols=[])
        for sym, k in bridged:
            G.nodes[root[k]]["symbols"].append(sym)
        equipment = [s for s in self.symbols if s.kind == "equipment"]
        for r in G.nodes:
            x, y = G.nodes[r]["xy"]
            best = None
            for e in equipment:
                m = self.snap_tol + eq_margin
                if abs(x - e.x) <= e.w / 2 + m and abs(y - e.y) <= e.h / 2 + m:
                    dist = math.hypot(x - e.x, y - e.y)
                    if best is None or dist < best[0]:
                        best = (dist, e.tag or f"EQ@{round(e.x)},{round(e.y)}")
            if best:
                G.nodes[r]["terminal"] = best[1]
        self._edge_nodes: Dict[int, Tuple[int, int]] = {}
        for i in range(n):
            a, b = root[i], root[n + i]
            if a == b:
                continue
            G.add_edge(a, b, key=i, seg=i, length=float(math.dist(self.segments[i][0], self.segments[i][1])))
            self._edge_nodes[i] = (a, b)
        self.G = G

    def _is_passthrough(self, node: int) -> bool:
        return self.G.degree(node) == 2 and self.G.nodes[node]["terminal"] is None

    def _assign_chains(self, labels: List[Dict[str, Any]], label_radius: float, arrow_tol: float) -> None:
        edge_ids = sorted(self._edge_nodes)
        pos = {e: k for k, e in enumerate(edge_ids)}
        uf = _UF(len(edge_ids))
        for node in self.G.nodes:
            if self._is_passthrough(node):
                es = [k for _, _, k in self.G.edges(node, keys=True)]
                uf.union(pos[es[0]], pos[es[1]])
        groups: Dict[int, List[int]] = {}
        for e in edge_ids:
            groups.setdefault(uf.find(pos[e]), []).append(e)

        # étiquettes de ligne -> segment le plus proche
        direct: Dict[int, List[Tuple[float, str]]] = {}
        if edge_ids:
            A, B = self._A[edge_ids], self._B[edge_ids]
            for lb in labels:
                text = (lb.get("text") or "").strip()
                if "-" not in text or not parse_line_tag(text):
                    continue
                d, _ = _dist_point_segments((lb["x"], lb["y"]), A, B)
                k = int(np.argmin(d))
                if d[k] <= label_radius:
                    direct.setdefault(edge_ids[k], []).append((float(d[k]), text))

        self.chains: List[Dict[str, Any]] = []
        self._chain_of_edge: Dict[int, int] = {}
        for members in groups.values():
            cid = len(self.chains)
            chain = self._order_chain(cid, members)
            tags = sorted((d, t) for e in members for d, t in direct.get(e, []))
            warns: List[str] = []
            tag = ""
            if tags:
                tag = tags[0][1]
                if len({t for _, t in tags}) > 1:
                    warns.append("Plusieurs étiquettes de ligne différentes sur ce tronçon : " + ", ".join(sorted({t for _, t in tags})))
            parsed = parse_line_tag(tag) or {}
            chain.update(tag=tag, size=parsed.get("size", ""), fluid=parsed.get("fluid", ""),
                         seq=parsed.get("seq", ""), spec=parsed.get("spec", ""), warnings=warns)
            self._orient(chain, arrow_tol)
            self._score(chain)
            self.chains.append(chain)
            for e in members:
                self._chain_of_edge[e] = cid

    def _order_chain(self, cid: int, members: List[int]) -> Dict[str, Any]:
        H = nx.Graph()
        for e in members:
            a, b = self._edge_nodes[e]
            H.add_edge(a, b, seg=e)
        ends = [n for n in H.nodes if H.degree(n) == 1]
        if len(ends) >= 2:
            path = nx.shortest_path(H, ends[0], ends[-1])
        else:  # boucle fermée
            start = next(iter(H.nodes))
            path = list(nx.dfs_preorder_nodes(H, start))
        nodes = path
        segs_in_order = [H[nodes[i]][nodes[i + 1]]["seg"] for i in range(len(nodes) - 1)] if len(nodes) > 1 else []
        poly = [self.G.nodes[n]["xy"] for n in nodes]
        s_at, acc = [0.0], 0.0
        for i in range(len(poly) - 1):
            acc += math.dist(poly[i], poly[i + 1])
            s_at.append(acc)
        items: List[Tuple[float, Symbol]] = []
        for i, n in enumerate(nodes):
            for sym in self.G.nodes[n]["symbols"]:
                items.append((s_at[i], sym))
        for i, e in enumerate(segs_in_order):
            for t, sym in self._edge_symbols.get(e, []):
                a = np.array(self.segments[e][0])
                b = np.array(self.segments[e][1])
                # t est mesuré de segments[e][0] vers [1] ; on le ramène au sens du chemin
                forward = math.dist(self.G.nodes[nodes[i]]["xy"], tuple(a)) <= math.dist(self.G.nodes[nodes[i]]["xy"], tuple(b))
                frac = t if forward else 1 - t
                items.append((s_at[i] + frac * (s_at[i + 1] - s_at[i]), sym))
        return {"id": f"L{cid}", "nodes": nodes, "segments": segs_in_order, "polyline": poly,
                "length": acc, "_items": sorted(items, key=lambda it: it[0])}

    def _end_info(self, node: int) -> Dict[str, str]:
        d = self.G.nodes[node]
        if d["terminal"]:
            return {"kind": "equipment", "tag": d["terminal"]}
        if self.G.degree(node) >= 3:
            return {"kind": "junction", "tag": f"TEE@{round(d['xy'][0])},{round(d['xy'][1])}"}
        return {"kind": "open", "tag": "OPEN"}

    def _orient(self, chain: Dict[str, Any], arrow_tol: float) -> None:
        nodes = chain["nodes"]
        basis, direction = "none", 0
        arrows = [s for s in self.symbols if s.kind == "arrow"]
        votes = []
        for ar in arrows:
            for i, e in enumerate(chain["segments"]):
                d, _ = _dist_point_segments((ar.x, ar.y), self._A[[e]], self._B[[e]])
                if d[0] <= arrow_tol:
                    p0, p1 = self.G.nodes[nodes[i]]["xy"], self.G.nodes[nodes[i + 1]]["xy"]
                    dot = (p1[0] - p0[0]) * ar.ux + (p1[1] - p0[1]) * ar.uy
                    if abs(dot) > 1e-9:
                        votes.append(1 if dot > 0 else -1)
        if votes:
            basis = "arrow"
            direction = 1 if sum(votes) >= 0 else -1
            if len(set(votes)) > 1:
                chain["warnings"].append("Flèches de sens contradictoires sur ce tronçon")
        else:
            a, b = self._end_info(nodes[0]), self._end_info(nodes[-1])
            ta, tb = _role_tag(a["tag"]), _role_tag(b["tag"])
            if a["kind"] == "equipment" and _SOURCE_RE.match(ta) or b["kind"] == "equipment" and _SINK_RE.match(tb):
                basis, direction = "equipment_role", 1
            elif b["kind"] == "equipment" and _SOURCE_RE.match(tb) or a["kind"] == "equipment" and _SINK_RE.match(ta):
                basis, direction = "equipment_role", -1
        if direction == -1:
            L = chain["length"]
            chain["nodes"] = nodes[::-1]
            chain["segments"] = chain["segments"][::-1]
            chain["polyline"] = chain["polyline"][::-1]
            chain["_items"] = sorted(((L - s, sym) for s, sym in chain["_items"]), key=lambda it: it[0])
        chain["flow_basis"] = basis
        chain["flow_known"] = basis != "none"
        chain["from"] = self._end_info(chain["nodes"][0])
        chain["to"] = self._end_info(chain["nodes"][-1])
        chain["components"] = [{"tag": sym.tag or f"?VALVE@{round(sym.x)},{round(sym.y)}", "kind": sym.kind, "s": round(s, 1)}
                               for s, sym in chain.pop("_items")]

    @staticmethod
    def _score(chain: Dict[str, Any]) -> None:
        c, reasons = 1.0, []
        if not chain["tag"]:
            c -= 0.35
            reasons.append("Aucune étiquette de ligne rattachée")
        for side, label in (("from", "amont"), ("to", "aval")):
            if chain[side]["kind"] == "open":
                c -= 0.15
                reasons.append(f"Extrémité {label} libre")
        if not chain["flow_known"]:
            c -= 0.10
            reasons.append("Sens d'écoulement indéterminé (ni flèche ni rôle d'équipement)")
        chain["confidence"] = round(max(0.1, c), 2)
        chain["reasons"] = reasons + chain["warnings"]

    def _assign_circuits(self) -> None:
        uf = _UF(len(self.chains))
        node_chains: Dict[int, List[int]] = {}
        for c in self.chains:
            for n in (c["nodes"][0], c["nodes"][-1]):
                node_chains.setdefault(n, []).append(int(c["id"][1:]))
        for n, cs in node_chains.items():
            if self.G.nodes[n]["terminal"] is None:
                for other in cs[1:]:
                    uf.union(cs[0], other)
        for c in self.chains:
            c["circuit"] = f"C{uf.find(int(c['id'][1:]))}"

    # ------------------------------------------------------------------ requêtes
    def chain_at(self, x: float, y: float, pick_radius: float = 10.0) -> Optional[Dict[str, Any]]:
        ids = sorted(self._edge_nodes)
        if not ids:
            return None
        d, _ = _dist_point_segments((x, y), self._A[ids], self._B[ids])
        k = int(np.argmin(d))
        return self.chains[self._chain_of_edge[ids[k]]] if d[k] <= pick_radius else None

    def trace(self, x: float, y: float, mode: str = "line", pick_radius: float = 10.0) -> Optional[Dict[str, Any]]:
        """mode="line" : la ligne sous le point ; mode="circuit" : tout le circuit (arrêt aux équipements)."""
        c = self.chain_at(x, y, pick_radius)
        if c is None:
            return None
        if mode == "line":
            return {"chains": [c], "segments": list(c["segments"])}
        chains = [k for k in self.chains if k["circuit"] == c["circuit"]]
        return {"chains": chains, "segments": [s for k in chains for s in k["segments"]]}

    def to_line_entries(self, filename: str = "drawing.pdf") -> List[Dict[str, Any]]:
        """Même format que PipingTopologyTracer.trace_drawing -> utilisable par l'UI, le MTO et l'ARH."""
        out = []
        for c in self.chains:
            valves = [k["tag"] for k in c["components"] if k["kind"] == "valve"]
            parts = [f"[{c['from']['tag']}]"] + [f"({k['tag']})" for k in c["components"]] + [f"[{c['to']['tag']}]"]
            ends_open = [c["from"]["kind"] == "open", c["to"]["kind"] == "open"]
            out.append({
                "line_number": c["tag"] or "UNKNOWN-LINE", "size": c["size"], "fluid": c["fluid"],
                "sequence": c["seq"], "spec": c["spec"], "spec_details": decode_gcb_pipe_spec(c["spec"]),
                "from_equipment": c["from"]["tag"], "to_equipment": c["to"]["tag"], "from_port": "", "to_port": "",
                "valves": valves, "line_components": [{"tag": k["tag"], "type": k["kind"], "dist": k["s"]} for k in c["components"]],
                "flow_path_str": " ➔ ".join(parts), "flow_basis": c["flow_basis"],
                "confidence_score": c["confidence"], "reasons": c["reasons"], "drawing": filename,
                "segment_count": len(c["segments"]), "is_dead_leg": sum(ends_open) == 1,
                "has_branch": "junction" in (c["from"]["kind"], c["to"]["kind"]), "circuit": c["circuit"],
                "path_coords": [tuple(round(v, 1) for v in (*self.segments[s][0], *self.segments[s][1])) for s in c["segments"]],
            })
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "segments": [[*a, *b] for a, b in self.segments],
            "chain_of_segment": [self._chain_of_edge.get(i, -1) for i in range(len(self.segments))],
            "chains": [{k: v for k, v in c.items() if k not in ("nodes",)} for c in self.chains],
            "symbols": [s.__dict__ for s in self.symbols], "warnings": self.warnings,
        }
