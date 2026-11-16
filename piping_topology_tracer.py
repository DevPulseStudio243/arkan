"""
piping_topology_tracer.py
==========================
Moteur de reconstruction topologique du chemin de flux P&ID / DEXPI pour ARKAN.

Réplique la méthode Model Broker en 4 étapes :
  1. Construction du graphe dual de connectivité (spatial hashing + union-find via cKDTree)
  2. Inférence du sens du flux (moteur à 5 niveaux de priorité : Flèches, Clapets, Rôles Procédé, Tubulures DEXPI, BFS)
  3. Projection le long de l'abscisse curviligne s ∈ [0, L] pour ordonner chronologiquement la robinetterie
  4. Raccordement multi-folios (OPC stitching)

Dépendances : networkx, scipy, numpy
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, List, Dict, Tuple, Any

import networkx as nx
import numpy as np
from scipy.spatial import cKDTree


# ═══════════════════════════════════════════════════════════════════════
# ÉTAPE 0 — MODÈLE DE DONNÉES & CARTES DES CODES GCB / SONATRACH
# ═══════════════════════════════════════════════════════════════════════

class ComponentType(Enum):
    NOZZLE = auto()          # Piquage / tubulure d'équipement
    VALVE_PORT = auto()      # Orifice de vanne
    TEE = auto()              # Té de dérivation
    REDUCER = auto()
    OPC = auto()              # Off-Page Connector (renvoi de folio)
    INSTRUMENT = auto()
    PUMP = auto()
    COMPRESSOR = auto()
    KOD = auto()               # Knock-Out Drum
    FLARE = auto()
    TANK = auto()
    LAUNCHER = auto()          # Gare de lancement racleur
    RECEIVER = auto()          # Gare de réception racleur
    VESSEL = auto()
    GENERIC = auto()


class EquipmentRole(Enum):
    SOURCE = auto()    # Amont / From
    SINK = auto()       # Aval / To
    NEUTRAL = auto()


ROLE_MAP = {
    ComponentType.PUMP: EquipmentRole.SOURCE,
    ComponentType.COMPRESSOR: EquipmentRole.SOURCE,
    ComponentType.LAUNCHER: EquipmentRole.SOURCE,
    ComponentType.KOD: EquipmentRole.SINK,
    ComponentType.FLARE: EquipmentRole.SINK,
    ComponentType.TANK: EquipmentRole.SINK,
    ComponentType.RECEIVER: EquipmentRole.SINK,
}

COMPANY_FLUID_MAP = {
    "AA": "Air", "AB": "Air de Soufflage", "AC": "Air de Combustion", "AI": "Air Instrument",
    "AS": "Air de Service", "CI": "Injection Chimique / Acidifiant", "CP": "Poudre Chimique",
    "CF": "Mousse Chimique", "DC": "Drain Fermé", "DD": "Drain pour Déluge",
    "DF": "Carburant Diesel", "DG": "Drain Général", "DO": "Drain Ouvert",
    "FR": "Fluide Réfrigérant", "GC": "Condensat", "NG": "Azote", "GP": "Gaz Pilote",
    "GG": "Gaz Général / Procédé / Injection", "GI": "Gaz Inerte", "GR": "Gaz de Purge",
    "LP": "Liquide Procédé (Basse Pression)", "HP": "Haute Pression", "OH": "Huile Hydraulique",
    "OL": "Huile de Lubrification", "OR": "Huile de Réchauffement", "VA": "Évent Atmosphérique / Torche",
    "VR": "Évent Dépressurisation / Torche", "WC": "Eau de Refroidissement", "WF": "Eau Incendie",
    "WH": "Eau Produite / Eau Huileuse", "WI": "Eau d'Injection", "WP": "Eau Potable",
    "WS": "Eau Salée / Eau de Mer", "WU": "Eau Utilité / Lavage", "WW": "Eau Usée",
    "P": "Process", "FG": "Fuel Gas", "BFW": "Eau d'Alimentation Chaudière",
    "ST": "Vapeur", "CD": "Condensat", "N2": "Azote", "H": "Hydrocarbure",
    "D": "Drain", "V": "Évent", "FL": "Torche", "FW": "Eau Douce",
    "EG": "Éthylène Glycol", "PR": "Process", "HC": "Hydrocarbure", "OIL": "Huile",
    "GAS": "Gaz", "LPG": "GPL", "CH": "Chimique", "ROK1": "Ligne Principale ROK1",
    "OB1": "Ligne Interconnexion OB1", "NK1": "Ligne Expédition NK1",
    "OZ2": "Ligne Oléoduc OZ2", "OZ1": "Ligne Oléoduc OZ1", "ROB1": "Ligne Raccordement ROB1"
}


COMPANY_INSULATION_MAP = {
    "H": "Hot Insulation",
    "IH": "Hot Insulation",
    "IT": "Tracing Insulation",
    "HT": "Heat Tracing",
    "N": "No Insulation",
    "C": "Cold Insulation",
    "CS": "Cold Service",
    "SS": "Personnel Protection"
}

FLUID_SERVICE_MAP = {
    "P": "Process",
    "HC": "Hydrocarbons",
    "FG": "Fuel Gas",
    "IA": "Instrument Air",
    "PA": "Plant Air",
    "CW": "Cooling Water",
    "CWD": "Cooling Water Drain",
    "CWS": "Cooling Water Supply",
    "CWR": "Cooling Water Return",
    "WW": "Waste Water",
    "N2": "Nitrogen",
    "O2": "Oxygen",
    "H2": "Hydrogen",
    "HP": "High Pressure Gas",
    "LP": "Low Pressure Gas",
    "MP": "Medium Pressure Gas",
    "PR": "Process",
    "CD": "Condensate",
    "SL": "Slop",
    "ST": "Steam",
    "VG": "Vent Gas"
}

DN_CONVERSION_MAP = {
    "0.5": "DN15", "0.75": "DN20", "1": "DN25", "1.5": "DN40", "2": "DN50",
    "3": "DN80", "4": "DN100", "6": "DN150", "8": "DN200", "10": "DN250",
    "12": "DN300", "14": "DN350", "16": "DN400", "18": "DN450", "20": "DN500",
    "24": "DN600", "26": "DN650", "28": "DN700", "30": "DN750", "32": "DN800",
    "34": "DN850", "36": "DN900", "42": "DN1050", "48": "DN1200"
}


def decode_gcb_pipe_spec(spec_code: str) -> Dict[str, str]:
    """Décode une classe de tuyauterie selon la structure supposée
    <rating><position><matière>[<norme>][<corrosion>] (ex. "3RX1" n'est qu'un exemple de forme).

    CORRECTIF : l'ancienne version renvoyait des valeurs PAR DÉFAUT (300#, rack, acier carbone,
    B31.3, 1.6 mm) pour tout code non reconnu, et décodait "CS150" en « Immergé / 0 mm ».
    Ici, un code qui ne respecte pas la structure n'est PAS décodé (decoded=False, champs vides).
    À valider : la structure ci-dessous est celle de ton code d'origine, pas une norme vérifiée.
    """
    undecoded = {"rating": "", "position": "", "material": "", "norm": "",
                 "corrosion_allowance": "", "decoded": False}
    if not spec_code:
        return undecoded
    code = spec_code.strip().upper()
    m = re.match(r"^(15|[1369Y])([ARSU])([ACGPSHR])([ACDEFJXNR])?([01369])?$", code)
    if not m:
        return undecoded
    rating_map = {"1": "150#", "3": "300#", "6": "600#", "9": "900#", "15": "1500#", "Y": "2500#"}
    pos_map = {"A": "Aérienne au Sol", "R": "Aérienne sur Rack", "S": "Immergé", "U": "Enterré"}
    mat_map = {"A": "Acier Allié", "C": "Acier Carbone", "G": "Acier Carbone Galvanisé", "P": "PVC",
               "S": "Acier Inoxydable / Duplex", "H": "HDPE", "R": "GRP"}
    norm_map = {"A": "Aucune", "C": "Cryogénique", "D": "ASME B31.1", "E": "ASME B31.8", "F": "ASME B31.4",
                "J": "Revêtu", "X": "ASME B31.3", "N": "NACE", "R": "Réfractaire"}
    corr_map = {"0": "0 mm", "1": "1.6 mm", "3": "3 mm", "6": "6 mm", "9": "Spéciale"}
    r, p, mt, nm, co = m.groups()
    return {"rating": rating_map[r], "position": pos_map[p], "material": mat_map[mt],
            "norm": norm_map.get(nm, "") if nm else "",
            "corrosion_allowance": corr_map.get(co, "") if co else "", "decoded": True}



LINE_TAG_PATTERN = re.compile(r"(\d+(?:\.\d+)?(?:/\d+)?)\s*(?:\"|'|in|inch|mm)?\s*[-_\s]+\s*([A-Z0-9]{2,4})\s*[-_\s]+\s*(\d{3,6})\s*[-_\s]*([A-Z0-9]{2,6})?", re.I)


_NON_LINE_PREFIXES = {
    "HV", "XV", "PV", "LV", "TV", "FV", "SV", "CV", "JI", "PIT", "FIT", "LIT", "TIT", "PDT", "PT", "FT", "LT", "TT",
    "PI", "FI", "LI", "TI", "GARE", "RACLEUR", "EQ", "TK", "BATIMENT", "CHAMBRE", "ROK", "ROB", "OB", "NK", "OZ",
    "NOTE", "NOTES", "TP", "TIE", "BARG", "BAR", "MM", "INCH", "DN", "FB", "LO", "LC", "NO", "NC",
    "CSO", "CSC", "EXISTANT", "EXISTING", "LAHH", "LALL", "LAH", "LAL", "PA", "M", "REF", "REV"
}  # "CH" retiré : c'est aussi un code fluide (Chimique) valide

_STRICT_LINE_TAG = re.compile(
    r"^(?:(?P<unit>\d{2,5})[-_ ]+)?(?P<size>\d+(?:\.\d+)?(?:/\d+)?)\s*(?:\"|'|in|inch)?[-_ ]+"
    r"(?P<fluid>[A-Z][A-Z0-9]{0,3})[-_ ]+(?P<seq>\d{3,6})(?:[-_ ]+(?P<spec>[A-Z0-9]{2,8}))?"
    r"(?:[-_ ]+(?P<iso>IH|IT|HT|H|N|C|IS|X))?$", re.I)

_SONATRACH_LINE_TAG = re.compile(
    r"^(?:(?P<unit>\d{2,5})[-_ ]+)?(?P<size>\d+(?:\.\d+)?(?:/\d+)?)\s*(?:\"|'|in|inch)?[-_ ]+"
    r"(?P<fluid>[A-Z][A-Z0-9]{0,3})[-_ ]+"
    r"(?P<spec>[A-Z0-9]{2,10})[-_ ]+"
    r"(?P<seq>\d{2,6})"
    r"(?:[-_ ]+(?P<iso>IH|IT|HT|H|N|C|IS|X))?$", re.I
)

_EXISTING_LINE_TAG = re.compile(
    r"^(?:(?:VERS|DE|LIGNE\s+EXISTANTE)\s+)?(?P<name>[A-Z0-9]{2,6})\s+(?P<size>\d+(?:\.\d+)?(?:/\d+)?)\s*(?:\"|'|in|inch)?\s+(?:EXISTANT|EXISTING)(?:\s+(?P<extra>\d+[\"']?))?$",
    re.I
)

_ISO_CODES = {"IH", "IT", "HT", "H", "N", "C", "IS", "X"}


def _parse_strict_line_tag(tag_clean: str) -> Optional[Dict[str, str]]:
    # 1. Existing pipeline (e.g. ROK1 34" EXISTANT)
    m_exist = _EXISTING_LINE_TAG.match(tag_clean)
    if m_exist:
        return {
            "size": m_exist.group("size"),
            "fluid": "P",
            "seq": m_exist.group("name").upper(),
            "spec": "EXISTANT",
            "isolation": ""
        }

    # 2. Sonatrach / European EPC format: SIZE - FLUID - SPEC - SEQ - [ISO]
    m_son = _SONATRACH_LINE_TAG.match(tag_clean)
    if m_son and not m_son.group("spec").isdigit():
        try:
            if float(m_son.group("size").split("/")[0]) > 60.0:
                return None
        except ValueError:
            return None
        fluid = m_son.group("fluid").upper()
        if fluid in _NON_LINE_PREFIXES:
            return None
        spec = (m_son.group("spec") or "").upper()
        iso = (m_son.group("iso") or "").upper()
        res = {"size": m_son.group("size"), "fluid": fluid, "seq": m_son.group("seq"), "spec": spec, "isolation": iso}
        if m_son.group("unit"):
            res["unit"] = m_son.group("unit")
        return res

    # 3. ASME format: SIZE - FLUID - SEQ - SPEC - [ISO]
    m = _STRICT_LINE_TAG.match(tag_clean)
    if not m:
        return None
    try:
        if float(m.group("size").split("/")[0]) > 60.0:
            return None
    except ValueError:
        return None
    fluid = m.group("fluid").upper()
    if fluid in _NON_LINE_PREFIXES:
        return None
    spec, iso = (m.group("spec") or "").upper(), (m.group("iso") or "").upper()
    if spec in _ISO_CODES and not iso:
        spec, iso = "", spec
    res = {"size": m.group("size"), "fluid": fluid, "seq": m.group("seq"), "spec": spec, "isolation": iso}
    if m.group("unit"):
        res["unit"] = m.group("unit")
    return res


def parse_line_tag(tag_str: str) -> Optional[Dict[str, str]]:
    if not tag_str or not isinstance(tag_str, str):
        return None
        
    tag_clean = tag_str.replace("\n", " ").replace("\r", " ").strip()
    tag_clean = re.sub(r'\s+', ' ', tag_clean)
    
    # Reject document/drawing references
    if re.search(r'-(?:PRC|DM|DW|GCL|PID|DWG|SH|SD)-', tag_clean, re.I) or re.match(r'^C\d{4}-', tag_clean, re.I):
        return None

    if any(k in tag_clean.upper() for k in (
        'SONATRACH', 'PETROFAC', 'CONTRAT', 'CARTOUCHE', 'DRAWING', 'P&ID', 'INTERCONNEXION',
        'REMPLACEMENT', 'GARE DE LANCEMENT', 'GARE DE RECEPTION', 'DESCRIPTION :',
        'NOTES GENERALES', 'SUPPRIMEE', 'DIRECTION', 'DIVISION', 'ECHELLE', 'FORMAT',
        'APPROBATION', 'REVISION', 'EMIS POUR'
    )):
        return None

    # Reject dimension multiplications like 34" x 34", 34"X28"
    if re.search(r'\d+\s*["\']?\s*[xX×]\s*\d+', tag_clean):
        return None

    strict = _parse_strict_line_tag(tag_clean)
    if strict:
        return strict

    EXCLUDED_VALVE_INSTRUMENT_PREFIXES = set(_NON_LINE_PREFIXES)

    all_tokens_upper = [t.strip().upper() for t in re.split(r'[-_\s]+', tag_clean) if t.strip()]
    if any(t in EXCLUDED_VALVE_INSTRUMENT_PREFIXES for t in all_tokens_upper):
        return None

    unit_prefix = ""
    unit_m = re.match(r'^(?:UNIT\s*)?(\d{2,5})[-_\s]+(.+)$', tag_clean, re.I)
    working_tag = tag_clean
    if unit_m:
        second_part = unit_m.group(2)
        second_tokens = [t.strip().upper() for t in re.split(r'[-_\s]+', second_part) if t.strip()]
        if second_tokens and not any(t in EXCLUDED_VALVE_INSTRUMENT_PREFIXES for t in second_tokens) and re.match(r'^\d+(?:\.\d+)?(?:/\d+)?(?:"|\'|in|inch|mm)?$', second_tokens[0], re.I):
            unit_prefix = unit_m.group(1)
            working_tag = second_part

    tokens = [t.strip() for t in re.split(r'[-_\s]+', working_tag) if t.strip()]
    if len(tokens) < 2:
        return None

    size = ""
    fluid = ""
    seq = ""
    spec = ""
    isolation = ""

    for t in tokens:
        if not size:
            sm = re.match(r"^(\d+(?:\.\d+)?(?:/\d+)?)\s*(?:\"|'|in|inch|mm)?$", t, re.I)
            if sm:
                try:
                    val = float(sm.group(1).split('/')[0])
                    if val <= 60.0:
                        size = sm.group(1)
                        continue
                except ValueError:
                    pass

        if not fluid and re.match(r'^[A-Z][A-Z0-9]{0,4}$', t, re.I) and t.upper() not in EXCLUDED_VALVE_INSTRUMENT_PREFIXES:
            if (len(t) >= 2 or t.upper() == 'P') and not re.match(r'^\d+$', t):
                fluid = t.upper()
                continue

        if not seq and re.match(r'^\d{2,6}$', t):
            seq = t
            continue

        if not spec and re.match(r'^[A-Z0-9]{2,10}$', t, re.I) and t.upper() != fluid and t != seq:
            if len(t) >= 2:
                spec = t.upper()
                continue

        if not isolation and t.upper() in ('H', 'N', 'IH', 'IT', 'HT', 'C', 'IN', 'IS', 'X'):
            isolation = t.upper()
            continue

    # A line tag MUST have a real fluid AND (size or seq)
    if fluid and (size or seq):
        res = {
            "size": size or "-",
            "fluid": fluid,
            "seq": seq or "-",
            "spec": spec or "",
            "isolation": isolation or ""
        }
        if unit_prefix:
            res["unit"] = unit_prefix
        return res

    return None


@dataclass
class Point2D:
    x: float
    y: float

    def as_tuple(self):
        return (self.x, self.y)


@dataclass
class Node:
    id: str
    point: Point2D
    comp_type: ComponentType
    tag: Optional[str] = None
    sheet_id: Optional[str] = None
    opc_target: Optional[str] = None
    raw_ref: Optional[object] = None


@dataclass
class Edge:
    id: str
    n1: str
    n2: str
    polyline: list
    layer: Optional[str] = None
    flow_arrow_angle: Optional[float] = None


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


class TopologyBuilder:
    def __init__(self, gap_tolerance_mm: float = 30.0):
        self.gap_tolerance = gap_tolerance_mm
        self.raw_endpoints: list[tuple[float, float, str, object]] = []

    def register_endpoint(self, x: float, y: float, endpoint_id: str, source_entity=None):
        self.raw_endpoints.append((x, y, endpoint_id, source_entity))

    def merge_disjoint_endpoints(self) -> dict[str, str]:
        if not self.raw_endpoints:
            return {}

        coords = np.array([[e[0], e[1]] for e in self.raw_endpoints])
        ids = [e[2] for e in self.raw_endpoints]

        uf = UnionFind()
        tree = cKDTree(coords)
        pairs = tree.query_pairs(r=self.gap_tolerance)

        for i, j in pairs:
            uf.union(ids[i], ids[j])

        cluster_map: dict[str, list[str]] = {}
        for eid in ids:
            root = uf.find(eid)
            cluster_map.setdefault(root, []).append(eid)

        endpoint_to_node = {}
        for root, members in cluster_map.items():
            merged_id = f"NODE-{root}"
            for m in members:
                endpoint_to_node[m] = merged_id
        return endpoint_to_node

    def build_graph(self, nodes: list[Node], edges_raw: list[Edge]) -> nx.MultiGraph:
        endpoint_map = self.merge_disjoint_endpoints()
        G = nx.MultiGraph()
        for n in nodes:
            resolved_id = endpoint_map.get(n.id, n.id)
            G.add_node(resolved_id, data=n)
        for e in edges_raw:
            n1 = endpoint_map.get(e.n1, e.n1)
            n2 = endpoint_map.get(e.n2, e.n2)
            G.add_edge(n1, n2, key=e.id, data=e)
        return G


class FlowDirectionEngine:
    def __init__(self, graph: nx.MultiGraph):
        self.graph = graph

    @staticmethod
    def _direction_from_arrow(edge_data: Edge):
        if edge_data is None or edge_data.flow_arrow_angle is None:
            return None
        theta = edge_data.flow_arrow_angle
        return (math.cos(theta), math.sin(theta))

    @staticmethod
    def _direction_from_check_valve(node: Node):
        if node.comp_type == ComponentType.VALVE_PORT and node.raw_ref and \
           getattr(node.raw_ref, "valve_kind", None) == "CHECK":
            return getattr(node.raw_ref, "check_valve_axis", None)
        return None

    @staticmethod
    def _role(node: Node) -> EquipmentRole:
        return ROLE_MAP.get(node.comp_type, EquipmentRole.NEUTRAL)

    @staticmethod
    def _nozzle_role(node: Node):
        if node.comp_type != ComponentType.NOZZLE or not node.raw_ref:
            return None
        kind = getattr(node.raw_ref, "nozzle_kind", None)
        if kind == "INLET":
            return EquipmentRole.SINK
        if kind == "OUTLET":
            return EquipmentRole.SOURCE
        return None

    def resolve_source_and_sink(self, line_subgraph: nx.MultiGraph):
        source_candidates, sink_candidates = [], []

        for nid, ndata in line_subgraph.nodes(data="data"):
            if ndata:
                role = self._role(ndata)
                if role == EquipmentRole.SOURCE:
                    source_candidates.append(nid)
                elif role == EquipmentRole.SINK:
                    sink_candidates.append(nid)

                nrole = self._nozzle_role(ndata)
                if nrole == EquipmentRole.SOURCE:
                    source_candidates.append(nid)
                elif nrole == EquipmentRole.SINK:
                    sink_candidates.append(nid)

        for u, v, edata in line_subgraph.edges(data="data"):
            if self._direction_from_arrow(edata) is not None:
                source_candidates.insert(0, u)
                sink_candidates.insert(0, v)

        source = source_candidates[0] if source_candidates else None
        sink = sink_candidates[0] if sink_candidates else None

        if source is None or sink is None:
            leaves = [n for n, d in line_subgraph.degree() if d == 1]
            if len(leaves) >= 2:
                source = source or leaves[0]
                sink = sink or leaves[1]

        return source, sink

    @staticmethod
    def bfs_path(source, sink, line_subgraph):
        try:
            return nx.shortest_path(line_subgraph, source, sink)
        except nx.NetworkXNoPath:
            return None


def _polyline_length(points: list[Point2D]) -> float:
    return sum(
        math.dist(points[i].as_tuple(), points[i + 1].as_tuple())
        for i in range(len(points) - 1)
    )


def _project_point_on_polyline(point: Point2D, polyline: list[Point2D]) -> float:
    best_s, best_dist, cumulative = 0.0, float("inf"), 0.0
    for i in range(len(polyline) - 1):
        a, b = polyline[i], polyline[i + 1]
        seg_len = math.dist(a.as_tuple(), b.as_tuple())
        if seg_len == 0:
            continue
        ax, ay, bx, by, px, py = a.x, a.y, b.x, b.y, point.x, point.y
        t = max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / seg_len ** 2))
        proj_x, proj_y = ax + t * (bx - ax), ay + t * (by - ay)
        dist = math.dist((proj_x, proj_y), (px, py))
        if dist < best_dist:
            best_dist = dist
            best_s = cumulative + t * seg_len
        cumulative += seg_len
    return best_s


class CurvilinearProjector:
    def __init__(self, path_nodes: list[Node], path_polyline: list[Point2D]):
        self.path_nodes = path_nodes
        self.polyline = path_polyline
        self.L = _polyline_length(path_polyline)

    def ordered_sequence(self) -> list[tuple[float, Node]]:
        scored = [
            (_project_point_on_polyline(n.point, self.polyline), n)
            for n in self.path_nodes
        ]
        return sorted(scored, key=lambda t: t[0])


class OPCStitcher:
    def __init__(self, opc_alias_map: dict[str, str] | None = None):
        self.alias_map = opc_alias_map or {}

    def _normalize(self, label: str) -> str:
        label = label.strip().upper()
        return self.alias_map.get(label, label)

    def stitch(self, graphs_by_sheet: dict[str, nx.MultiGraph]) -> nx.MultiGraph:
        merged = nx.MultiGraph()
        opc_index: dict[str, list[tuple[str, str]]] = {}

        for sheet_id, g in graphs_by_sheet.items():
            merged = nx.compose(merged, g)
            for nid, ndata in g.nodes(data="data"):
                if ndata and ndata.comp_type == ComponentType.OPC and ndata.opc_target:
                    key = self._normalize(ndata.opc_target)
                    opc_index.setdefault(key, []).append((sheet_id, nid))

        seen = set()
        for key, occurrences in opc_index.items():
            if len(occurrences) >= 2:
                for i in range(len(occurrences) - 1):
                    (_, n1), (_, n2) = occurrences[i], occurrences[i + 1]
                    edge_key = tuple(sorted([n1, n2]))
                    if edge_key not in seen:
                        merged.add_edge(n1, n2, key=f"OPC-LINK-{n1}-{n2}", data=None)
                        seen.add(edge_key)
        return merged


class PipingTopologyTracer:
    """Point d'entrée unique pour la traçabilité des tuyauteries ARKAN."""
    def __init__(self, tolerance: float = 30.0, box_tolerance: float = 50.0, opc_alias_map: dict | None = None,
                 inline_component_radius: float = 120.0, label_proximity_radius: float = 300.0,
                 fallback_search_radius: float = 150.0):
        self.tolerance = tolerance
        self.box_tolerance = box_tolerance
        self.builder = TopologyBuilder(tolerance)
        self.stitcher = OPCStitcher(opc_alias_map)
        self.inline_component_radius = inline_component_radius
        self.label_proximity_radius = label_proximity_radius
        self.fallback_search_radius = fallback_search_radius

    def _point_dist(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

    def _dist_to_segment(self, px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0:
            return math.sqrt((px - x1)**2 + (py - y1)**2)
        t = ((px - x1) * dx + (py - y1) * dy) / (dx*dx + dy*dy)
        t = max(0.0, min(1.0, t))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return math.sqrt((px - proj_x)**2 + (py - proj_y)**2)

    def _get_obj_coords(self, obj: Dict[str, Any]) -> Tuple[float, float]:
        if not isinstance(obj, dict):
            return (0.0, 0.0)
        if "x" in obj and "y" in obj and obj["x"] is not None and obj["y"] is not None:
            return (float(obj["x"]), float(obj["y"]))
        if "bbox" in obj and isinstance(obj["bbox"], (list, tuple)) and len(obj["bbox"]) >= 4:
            return ((float(obj["bbox"][0]) + float(obj["bbox"][2])) / 2.0, (float(obj["bbox"][1]) + float(obj["bbox"][3])) / 2.0)
        if "ports" in obj and isinstance(obj["ports"], (list, tuple)) and len(obj["ports"]) > 0:
            p0 = obj["ports"][0]
            if isinstance(p0, dict) and "x" in p0 and "y" in p0:
                return (float(p0["x"]), float(p0["y"]))
        if "position" in obj and isinstance(obj["position"], (list, tuple)) and len(obj["position"]) >= 2:
            return (float(obj["position"][0]), float(obj["position"][1]))
        return (0.0, 0.0)

    def trace_drawing(
        self,
        segments: List[Tuple[Tuple[float, float], Tuple[float, float], Dict[str, Any]]],
        labels: List[Dict[str, Any]],
        blocks: List[Dict[str, Any]],
        opcs: List[Dict[str, Any]],
        filename: str = "drawing.dxf"
    ) -> List[Dict[str, Any]]:
        line_entries = []
        uf = UnionFind()
        points_map = {}

        def get_point_id(p: Tuple[float, float]) -> int:
            rx, ry = round(p[0], 2), round(p[1], 2)
            k = (rx, ry)
            if k not in points_map:
                points_map[k] = len(points_map)
            return points_map[k]

        for s in segments:
            get_point_id(s[0])
            get_point_id(s[1])

        if points_map:
            all_pts = list(points_map.keys())
            coords = np.array(all_pts)
            tree = cKDTree(coords)
            pairs = tree.query_pairs(r=self.tolerance)
            for i, j in pairs:
                id1 = points_map[all_pts[i]]
                id2 = points_map[all_pts[j]]
                uf.union(id1, id2)

        if blocks and points_map:
            inline_blocks = [b for b in blocks if any(kw in b.get("type", "").lower() for kw in ("valve", "vanne", "handvalve", "ballvalve", "gatevalve", "checkvalve")) and not any(kw in b.get("type", "").lower() for kw in ("equipment", "vessel", "pump", "flowarrow"))]
            if inline_blocks:
                all_pts = list(points_map.keys())
                block_coords = np.array([self._get_obj_coords(b) for b in inline_blocks])
                pts_coords = np.array(all_pts)
                b_tree = cKDTree(pts_coords)
                for bx, by in block_coords:
                    close_idx = b_tree.query_ball_point([bx, by], r=35.0)
                    if len(close_idx) >= 2:
                        for k in range(len(close_idx) - 1):
                            id1 = points_map[all_pts[close_idx[k]]]
                            id2 = points_map[all_pts[close_idx[k+1]]]
                            uf.union(id1, id2)

        endpoint_to_segs = {}
        for idx, s in enumerate(segments):
            p0_id = uf.find(points_map[(round(s[0][0], 2), round(s[0][1], 2))])
            p1_id = uf.find(points_map[(round(s[1][0], 2), round(s[1][1], 2))])
            for r_id in (p0_id, p1_id):
                endpoint_to_segs.setdefault(r_id, []).append(idx)

        adj = {idx: [] for idx in range(len(segments))}
        for r_id, seg_indices in endpoint_to_segs.items():
            for idx1 in seg_indices:
                for idx2 in seg_indices:
                    if idx1 != idx2:
                        adj[idx1].append(idx2)

        visited_segments = set()
        merged_paths = []
        for idx in range(len(segments)):
            if idx in visited_segments: continue
            queue = [idx]
            path = []
            visited_segments.add(idx)
            while queue:
                curr = queue.pop(0)
                path.append(curr)
                for neighbor in adj.get(curr, []):
                    if neighbor not in visited_segments:
                        visited_segments.add(neighbor)
                        queue.append(neighbor)
            merged_paths.append(path)

        for path_idx, segment_indices in enumerate(merged_paths):
            path_segs = [segments[idx] for idx in segment_indices]
            path_points = []
            for s in path_segs:
                path_points.append(s[0])
                path_points.append(s[1])

            pt_degrees = {}
            for p in path_points:
                k = (round(p[0], 2), round(p[1], 2))
                root = uf.find(points_map[k])
                pt_degrees[root] = pt_degrees.get(root, 0) + 1

            has_branch = any(deg >= 3 for deg in pt_degrees.values())
            junctions = []
            for root, deg in pt_degrees.items():
                if deg >= 3:
                    j_coord = None
                    for p in path_points:
                        k = (round(p[0], 2), round(p[1], 2))
                        if uf.find(points_map[k]) == root:
                            j_coord = (round(p[0], 1), round(p[1], 1))
                            break
                    if j_coord:
                        junctions.append({"position": j_coord, "type": "TEE" if deg == 3 else "CROSS"})

            endpoints_roots = [root for root, deg in pt_degrees.items() if deg == 1]
            if not endpoints_roots:
                endpoints_roots = list(pt_degrees.keys())[:2]

            endpoints_coords = []
            for root in endpoints_roots:
                for p in path_points:
                    k = (round(p[0], 2), round(p[1], 2))
                    if uf.find(points_map[k]) == root:
                        endpoints_coords.append(p)
                        break

            closest_label = None
            min_label_dist = float('inf')
            for label in labels:
                lx, ly = self._get_obj_coords(label)
                parsed = parse_line_tag(label.get("text", ""))
                if not parsed: continue
                for s in path_segs:
                    dist = self._dist_to_segment(lx, ly, s[0][0], s[0][1], s[1][0], s[1][1])
                    if dist < min_label_dist:
                        min_label_dist = dist
                        closest_label = label

            tag = "UNKNOWN-LINE"
            parsed_data = {"size": "", "fluid": "", "seq": "", "spec": "", "isolation": ""}
            if closest_label and min_label_dist <= self.label_proximity_radius:
                tag = closest_label.get("text", "UNKNOWN-LINE")
                parsed_data = parse_line_tag(tag) or parsed_data

            endpoint_connections = []
            for ep in endpoints_coords:
                connected_item = None
                for b in blocks:
                    btype = b.get("type", "").lower()
                    if any(kw in btype for kw in ("valve", "vanne", "instrument", "component", "flowarrow")):
                        continue
                    for port in b.get("ports", []):
                        p_coord = self._get_obj_coords(port)
                        if self._point_dist(ep, p_coord) <= self.tolerance:
                            connected_item = {"tag": b.get("tag", "EQ"), "port": port.get("name", "N"), "type": b.get("type", "Equipment")}
                            break
                    if connected_item: break

                if not connected_item:
                    best_dist = float('inf')
                    for b in blocks:
                        btype = b.get("type", "").lower()
                        if any(kw in btype for kw in ("valve", "vanne", "instrument", "component", "flowarrow")):
                            continue
                        bx, by = self._get_obj_coords(b)
                        bw, bh = b.get("width", 20.0), b.get("height", 20.0)
                        dx, dy = abs(ep[0] - bx), abs(ep[1] - by)
                        if dx <= (bw/2 + self.box_tolerance) and dy <= (bh/2 + self.box_tolerance):
                            dist = math.sqrt(dx**2 + dy**2)
                            if dist < best_dist:
                                best_dist = dist
                                connected_item = {"tag": b.get("tag", "EQ"), "port": "Nozzle-Fallback", "type": b.get("type", "Equipment")}

                if not connected_item:
                    for opc in opcs:
                        opc_coord = self._get_obj_coords(opc)
                        if self._point_dist(ep, opc_coord) <= self.tolerance:
                            connected_item = {"tag": f"OPC:{opc.get('ref_code', opc.get('tag', 'OPC'))}", "port": "", "type": "OPC"}
                            break

                endpoint_connections.append(connected_item)

            from_node = "OPEN"
            to_node = "OPEN"
            from_port = ""
            to_port = ""

            if len(endpoint_connections) >= 1 and endpoint_connections[0]:
                from_node = endpoint_connections[0]["tag"]
                from_port = endpoint_connections[0]["port"]
            if len(endpoint_connections) >= 2 and endpoint_connections[1]:
                to_node = endpoint_connections[1]["tag"]
                to_port = endpoint_connections[1]["port"]

            arrow_dir = None
            for s in path_segs:
                for b in blocks:
                    btype = b.get("type", "").lower()
                    if btype in ("flowarrow", "pipeflowarrow"):
                        ax, ay = self._get_obj_coords(b)
                        if self._dist_to_segment(ax, ay, s[0][0], s[0][1], s[1][0], s[1][1]) <= 15.0:
                            arrow_dir = (b.get("ux", 1.0), b.get("uy", 0.0))
                            break
                if arrow_dir: break

            if arrow_dir and len(endpoints_coords) >= 2:
                ep0, ep1 = endpoints_coords[0], endpoints_coords[1]
                p0_proj = ep0[0] * arrow_dir[0] + ep0[1] * arrow_dir[1]
                p1_proj = ep1[0] * arrow_dir[0] + ep1[1] * arrow_dir[1]
                if p0_proj > p1_proj:
                    from_node, to_node = to_node, from_node
                    from_port, to_port = to_port, from_port

            ordered_valves = []
            ordered_line_components = []
            if blocks and path_segs:
                start_pt = (0.0, 0.0)
                if len(endpoints_coords) >= 1:
                    start_pt = endpoints_coords[0]
                elif len(path_segs) >= 1 and len(path_segs[0]) >= 1:
                    start_pt = (path_segs[0][0][0], path_segs[0][0][1])
                inline_candidates = []
                for b in blocks:
                    btype = b.get("type", "").lower()
                    btag = b.get("tag", "")
                    if not btag or btype in ("flowarrow", "pipeflowarrow"):
                        continue
                    bx, by = self._get_obj_coords(b)
                    min_dist_to_path = float('inf')
                    for s in path_segs:
                        dist = self._dist_to_segment(bx, by, s[0][0], s[0][1], s[1][0], s[1][1])
                        if dist < min_dist_to_path:
                            min_dist_to_path = dist
                    
                    if min_dist_to_path <= self.inline_component_radius:
                        flow_dist = math.sqrt((bx - start_pt[0])**2 + (by - start_pt[1])**2)
                        inline_candidates.append((flow_dist, btag, b.get("type", "Component"), bx, by))
                
                inline_candidates.sort(key=lambda x: x[0])
                for c in inline_candidates:
                    btag_str = c[1].strip()
                    if not btag_str: continue
                    if re.match(r'^(\d+(?:\.\d+)?(?:\/\d+)?)\s*(?:\"|\'|in|inch||mm|dn)?$', btag_str, re.I): continue
                    if btag_str.upper() in ("FB", "STD", "N.C.", "N.O.", "N/C", "N/O", "EXISTING", "EXISTANT", "DESCRIPTION :"): continue
                    if btag_str == from_node or btag_str == to_node: continue  # déjà représenté comme extrémité [equipment]
                    
                    c_entry = {"tag": btag_str, "type": c[2], "x": c[3], "y": c[4], "dist": round(c[0], 1)}
                    if c_entry not in ordered_line_components:
                        ordered_line_components.append(c_entry)
                        if any(kw in c[2].lower() for kw in ("valve", "vanne", "clapet")) or any(p in btag_str.upper() for p in ("HV", "XV", "SDV", "BDV", "CV", "MOV")):
                            if btag_str not in ordered_valves:
                                ordered_valves.append(btag_str)

            spec_decoded = decode_gcb_pipe_spec(parsed_data["spec"])
            confidence = 1.0
            reasons = []

            if tag == "UNKNOWN-LINE":
                confidence -= 0.35
                reasons.append("Missing matching line label tag")
            if from_node == "OPEN":
                confidence -= 0.15
                reasons.append("Open upstream endpoint (From)")
            if to_node == "OPEN":
                confidence -= 0.15
                reasons.append("Open downstream endpoint (To)")
            if "Fallback" in from_port or "Fallback" in to_port:
                confidence -= 0.08
                reasons.append("Connected via fallback bounding box rather than explicit ports")

            confidence = max(0.10, min(1.00, round(confidence, 2)))
            is_dead_leg = (from_node == "OPEN" and to_node != "OPEN") or (to_node == "OPEN" and from_node != "OPEN")

            # Format explicit flow path string with all sequential line components
            flow_parts = [f"[{from_node}]"]
            for comp in ordered_line_components:
                flow_parts.append(f"({comp['tag']})")
            flow_parts.append(f"[{to_node}]")
            flow_path_str = " ➔ ".join(flow_parts)

            # Format interconnections string
            inter_parts = []
            if junctions:
                inter_parts.append(f"{len(junctions)} Té(s)")
            if from_node.startswith("OPC:") or to_node.startswith("OPC:"):
                inter_parts.append("Raccord Multi-Plan (OPC)")
            if has_branch:
                inter_parts.append("Dérivation")
            interconnections_str = " | ".join(inter_parts) if inter_parts else "Directe"

            line_entries.append({
                "line_number": tag,
                "size": parsed_data["size"],
                "fluid": parsed_data["fluid"],
                "sequence": parsed_data["seq"],
                "spec": parsed_data["spec"],
                "spec_details": spec_decoded,
                "isolation": parsed_data["isolation"],
                "isolation_description": COMPANY_INSULATION_MAP.get(parsed_data["isolation"], parsed_data["isolation"]),
                "from_equipment": from_node,
                "from_port": from_port,
                "to_equipment": to_node,
                "to_port": to_port,
                "valves": ordered_valves,
                "line_components": ordered_line_components,
                "flow_path_str": flow_path_str,
                "interconnections_str": interconnections_str,
                "confidence_score": confidence,
                "reasons": reasons,
                "drawing": filename,
                "segment_count": len(segment_indices),
                "size_dn": DN_CONVERSION_MAP.get(parsed_data["size"], f"DN{parsed_data['size']}") if parsed_data["size"] else "",
                "fluid_description": FLUID_SERVICE_MAP.get(parsed_data["fluid"], parsed_data["fluid"]),
                "is_dead_leg": is_dead_leg,
                "has_branch": has_branch,
                "junctions": junctions,
                "path_coords": [(round(s[0][0], 1), round(s[0][1], 1), round(s[1][0], 1), round(s[1][1], 1)) for s in path_segs]
            })

        assigned_tags = {l["line_number"] for l in line_entries if l.get("line_number") != "UNKNOWN-LINE"}
        for lbl in labels:
            raw_text = lbl.get("text", "").strip()
            parsed = parse_line_tag(raw_text)
            # Une cotation isolée (ex: '20"', '1"') n'est PAS un numéro de ligne : les tags
            # de ligne réels de la nomenclature GCB contiennent toujours des tirets
            # (taille-fluide-séquence-spec). Sans ce garde-fou, chaque simple cote de
            # diamètre sur le plan serait traitée comme une ligne à part entière.
            if parsed and raw_text not in assigned_tags and "-" in raw_text:
                assigned_tags.add(raw_text)
                size = parsed.get("size", "")
                fluid = parsed.get("fluid", "PROCESS")
                size_dn = DN_CONVERSION_MAP.get(size, f"DN{size}") if size else ""
                fluid_desc = FLUID_SERVICE_MAP.get(fluid, fluid)
                spec_decoded = decode_gcb_pipe_spec(parsed.get("spec", ""))

                # Cherche les segments de tuyauterie réellement proches de cette étiquette
                # (label non apparié au clustering principal, ex: label isolé sur un piquage).
                lx, ly = self._get_obj_coords(lbl)
                close_segs = []
                for s in segments:
                    dist = self._dist_to_segment(lx, ly, s[0][0], s[0][1], s[1][0], s[1][1])
                    if dist <= self.fallback_search_radius:
                        close_segs.append(s)

                if not close_segs:
                    # Aucune géométrie trouvée : on ne fabrique RIEN. On expose le label
                    # tel quel avec un statut explicite "non résolu", plutôt que d'inventer
                    # un équipement ou une vanne qui n'existe peut-être pas sur ce plan.
                    line_entries.append({
                        "line_number": raw_text,
                        "tag": raw_text,
                        "size": size,
                        "size_dn": size_dn,
                        "fluid": fluid,
                        "fluid_description": fluid_desc,
                        "sequence": parsed.get("seq", "001"),
                        "spec": parsed.get("spec", ""),
                        "spec_details": spec_decoded,
                        "isolation": parsed.get("isolation", ""),
                        "isolation_description": COMPANY_INSULATION_MAP.get(parsed.get("isolation", ""), ""),
                        "from_equipment": "UNRESOLVED",
                        "from_port": "",
                        "to_equipment": "UNRESOLVED",
                        "to_port": "",
                        "valves": [],
                        "line_components": [],
                        "flow_path_str": f"[UNRESOLVED] — étiquette '{raw_text}' détectée sans tracé de tuyauterie identifiable à proximité",
                        "interconnections_str": "Non déterminé",
                        "confidence_score": 0.20,
                        "reasons": ["Label détecté mais aucun segment de tuyauterie trouvé à proximité (< 350 unités) : vérification manuelle requise"],
                        "drawing": filename,
                        "segment_count": 0,
                        "is_dead_leg": False,
                        "has_branch": False,
                        "junctions": [],
                        "path_coords": []
                    })
                    continue

                # Des segments réels ont été trouvés : on applique la même logique de
                # rattachement (équipements aux extrémités, robinetterie en ligne) que
                # pour les lignes principales, sur la base de la géométrie effective —
                # jamais de nom d'équipement ou de tag de vanne codé en dur.
                seg_points = []
                for s in close_segs:
                    seg_points.append(s[0])
                    seg_points.append(s[1])

                endpoints_coords = []
                if seg_points:
                    max_d = -1.0
                    best_pair = (seg_points[0], seg_points[0])
                    for i in range(len(seg_points)):
                        for j in range(i + 1, len(seg_points)):
                            d = self._point_dist(seg_points[i], seg_points[j])
                            if d > max_d:
                                max_d = d
                                best_pair = (seg_points[i], seg_points[j])
                    endpoints_coords = [best_pair[0], best_pair[1]]

                endpoint_connections = []
                for ep in endpoints_coords:
                    connected_item = None
                    for b in blocks:
                        btype = b.get("type", "").lower()
                        if any(kw in btype for kw in ("valve", "vanne", "instrument", "component", "flowarrow")):
                            continue
                        for port in b.get("ports", []):
                            p_coord = self._get_obj_coords(port)
                            if self._point_dist(ep, p_coord) <= self.tolerance:
                                connected_item = {"tag": b.get("tag", "EQ"), "port": port.get("name", "N")}
                                break
                        if connected_item:
                            break
                    endpoint_connections.append(connected_item)

                from_eq = endpoint_connections[0]["tag"] if len(endpoint_connections) >= 1 and endpoint_connections[0] else "OPEN"
                to_eq = endpoint_connections[1]["tag"] if len(endpoint_connections) >= 2 and endpoint_connections[1] else "OPEN"

                valves_list = []
                ordered_components = []
                start_pt = endpoints_coords[0] if endpoints_coords else (lx, ly)
                inline_candidates = []
                for b in blocks:
                    btype = b.get("type", "").lower()
                    btag = b.get("tag", "")
                    if not btag or btype in ("flowarrow", "pipeflowarrow"):
                        continue
                    bx, by = self._get_obj_coords(b)
                    min_dist_to_path = min(
                        (self._dist_to_segment(bx, by, s[0][0], s[0][1], s[1][0], s[1][1]) for s in close_segs),
                        default=float("inf"),
                    )
                    if min_dist_to_path <= self.inline_component_radius:
                        flow_dist = self._point_dist((bx, by), start_pt)
                        inline_candidates.append((flow_dist, btag, b.get("type", "Component")))

                inline_candidates.sort(key=lambda x: x[0])
                for dist, btag_str, btype_str in inline_candidates:
                    btag_str = btag_str.strip()
                    if not btag_str or btag_str in (from_eq, to_eq):
                        continue
                    ordered_components.append({"tag": btag_str, "type": btype_str, "dist": round(dist, 1)})
                    if btype_str.lower() == "valve" and btag_str not in valves_list:
                        valves_list.append(btag_str)

                flow_parts = [f"[{from_eq}]"]
                for comp in ordered_components:
                    flow_parts.append(f"({comp['tag']})")
                flow_parts.append(f"[{to_eq}]")
                flow_path_str = " ➔ ".join(flow_parts)

                confidence = 0.55  # rattaché par proximité de label, pas par clustering topologique direct
                reasons = ["Ligne reconstituée par proximité géométrique entre le label et les segments (label isolé du clustering principal)"]
                if from_eq == "OPEN":
                    confidence -= 0.10
                    reasons.append("Extrémité amont non connectée à un équipement identifié")
                if to_eq == "OPEN":
                    confidence -= 0.10
                    reasons.append("Extrémité aval non connectée à un équipement identifié")
                confidence = max(0.10, round(confidence, 2))

                matched_coords = [(round(s[0][0], 1), round(s[0][1], 1), round(s[1][0], 1), round(s[1][1], 1)) for s in close_segs]

                line_entries.append({
                    "line_number": raw_text,
                    "tag": raw_text,
                    "size": size,
                    "size_dn": size_dn,
                    "fluid": fluid,
                    "fluid_description": fluid_desc,
                    "sequence": parsed.get("seq", "001"),
                    "spec": parsed.get("spec", ""),
                    "spec_details": spec_decoded,
                    "isolation": parsed.get("isolation", ""),
                    "isolation_description": COMPANY_INSULATION_MAP.get(parsed.get("isolation", ""), ""),
                    "from_equipment": from_eq,
                    "from_port": "",
                    "to_equipment": to_eq,
                    "to_port": "",
                    "valves": valves_list,
                    "line_components": ordered_components,
                    "flow_path_str": flow_path_str,
                    "interconnections_str": "Directe" if not ordered_components else f"{len(ordered_components)} composant(s) en ligne",
                    "confidence_score": confidence,
                    "reasons": reasons,
                    "drawing": filename,
                    "segment_count": len(matched_coords),
                    "is_dead_leg": (from_eq == "OPEN") != (to_eq == "OPEN"),
                    "has_branch": False,
                    "junctions": [],
                    "path_coords": matched_coords
                })

        valid_entries = [l for l in line_entries if l.get("line_number") != "UNKNOWN-LINE"]
        if valid_entries:
            line_entries = valid_entries

        return line_entries


def stitch_project_line_lists(drawings_lines: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    lines_by_tag: Dict[str, Dict[str, Any]] = {}
    other_lines: List[Dict[str, Any]] = []

    for drawing in drawings_lines:
        for entry in drawing:
            tag = entry.get('line_number') or entry.get('tag')
            if tag and tag != 'UNKNOWN-LINE':
                if tag not in lines_by_tag:
                    lines_by_tag[tag] = dict(entry)
                else:
                    existing = lines_by_tag[tag]
                    if str(existing.get('to_equipment', '')).startswith('OPC:') and not str(entry.get('to_equipment', '')).startswith('OPC:'):
                        existing['to_equipment'] = entry.get('to_equipment', 'OPEN')
                        if entry.get('to_port'):
                            existing['to_port'] = entry.get('to_port')
                    if str(existing.get('from_equipment', '')).startswith('OPC:') and not str(entry.get('from_equipment', '')).startswith('OPC:'):
                        existing['from_equipment'] = entry.get('from_equipment', 'OPEN')
                        if entry.get('from_port'):
                            existing['from_port'] = entry.get('from_port')
                    if entry.get('drawing') and entry.get('drawing') not in str(existing.get('drawing', '')):
                        existing['drawing'] = f"{existing.get('drawing', '')}, {entry.get('drawing', '')}" 
            else:
                other_lines.append(entry)

    return list(lines_by_tag.values()) + other_lines


def validate_line_nomenclature(line_entry: Any, project_pattern: str = None) -> List[str]:
    warnings = []
    if isinstance(line_entry, str):
        parsed = parse_line_tag(line_entry)
        size = parsed.get("size") if parsed else None
        fluid = parsed.get("fluid") if parsed else None
        seq = parsed.get("seq") if parsed else None
        if not size:
            warnings.append("Diamètre manquant")
        if not fluid:
            warnings.append("Code fluide manquant")
        if not seq:
            warnings.append("Numéro de séquence manquant")
        if fluid and fluid not in FLUID_SERVICE_MAP:
            warnings.append(f"Code fluide inconnu : {fluid}")
        return warnings

    if not isinstance(line_entry, dict):
        return ["Format de ligne invalide"]

    if not line_entry.get("size"):
        warnings.append("Diamètre manquant")
    if not line_entry.get("fluid"):
        warnings.append("Code fluide manquant")
    if not line_entry.get("sequence"):
        warnings.append("Numéro de séquence manquant")
    if line_entry.get("fluid") and line_entry["fluid"] not in FLUID_SERVICE_MAP:
        warnings.append(f"Code fluide inconnu : {line_entry['fluid']}")
    if line_entry.get("is_dead_leg"):
        warnings.append("Dead-leg détecté (un bout ouvert)")
    if line_entry.get("from_equipment") == "OPEN" and line_entry.get("to_equipment") == "OPEN":
        warnings.append("Ligne isolée (aucune connexion identifiée)")
    return warnings
