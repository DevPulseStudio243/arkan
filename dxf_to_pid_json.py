"""
dxf_to_pid_json.py
==================
Convertisseur DXF vers JSON Sémantique Topologique pour P&ID (Architecture Option A - Module 1).

Extrait du DXF un Jumeau Numérique structuré complet :
  - equipments       : équipements avec détection géométrique des piquages/nozzles (<28u).
  - piping_circuits  : fusion des micro-segments en circuits continus orientés
                       (from_node -> to_node, in_line_components ordonnés par ratio curviligne).
  - valves           : liste normalisée des vannes rattachées au circuit le plus proche.
  - instruments      : bulles d'instrumentation conformes ISA-5.1.
  - loops            : boucles de régulation groupées (transmetteur, régulateur, organe final).
  - topology_summary : métadonnées et statistiques de connectivité.

Usage CLI :
  python dxf_to_pid_json.py <fichier.dxf> [sortie.json] [--pretty]
"""

from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import logging
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import dxf_pid_parser
from dxf_pid_parser import (
    DEFAULT_CONFIG,
    Snap,
    UF,
    classify,
    layer_role,
    load_config,
    normalize_valve_tag,
    parse_dxf_to_raw_and_semantic,
    seg_dist,
    split_t_junctions,
)

logger = logging.getLogger("dxf_to_pid_json")

CONVERTER_VERSION = "1.0.0"
SCHEMA_VERSION = "2.0.0"

# ---------------------------------------------------------------------------
# Bases de connaissances normatives : Équipements, Vannes, ISA-5.1
# ---------------------------------------------------------------------------

EQUIPMENT_TYPES: Dict[str, Tuple[str, str]] = {
    "PP": ("PUMP", "Centrifugal / Process Pump"),
    "P": ("PUMP", "Process Pump"),
    "TK": ("TANK", "Storage / Atmospheric Tank"),
    "T": ("TANK", "Storage Tank"),
    "V": ("VESSEL", "Pressure Vessel / Separator"),
    "VS": ("VESSEL", "Vertical / Horizontal Separator"),
    "COL": ("COLUMN", "Fractionation / Distillation Column"),
    "C": ("COLUMN", "Process Column"),
    "EX": ("HEAT_EXCHANGER", "Heat Exchanger"),
    "HE": ("HEAT_EXCHANGER", "Shell & Tube Heat Exchanger"),
    "E": ("HEAT_EXCHANGER", "Heat Exchanger / Reboiler"),
    "AC": ("AIR_COOLER", "Air Cooled Heat Exchanger / Fin-Fan"),
    "K": ("COMPRESSOR", "Gas Compressor"),
    "CP": ("COMPRESSOR", "Process Compressor"),
    "ST": ("FILTER_STRAINER", "Suction Strainer / In-line Filter"),
    "STR": ("FILTER_STRAINER", "Basket / Y-Strainer"),
    "FIL": ("FILTER_STRAINER", "Cartridge / Coalescer Filter"),
    "F": ("FILTER_STRAINER", "Process Filter"),
    "DR": ("DRUM", "Knock-out / Flash Drum"),
    "FL": ("FLARE", "Flare Stack / K.O. Drum"),
    "FLA": ("FLARE", "Flare System"),
    "SK": ("PACKAGE", "Skid Mounted Unit"),
    "PKG": ("PACKAGE", "Modular Process Package"),
    "TUR": ("TURBINE", "Steam / Gas Turbine"),
    "GEN": ("GENERATOR", "Power Generator"),
    "MOT": ("MOTOR", "Electric Motor Driver"),
    "M": ("MOTOR", "Electric Motor"),
    "SEP": ("SEPARATOR", "Two-Phase / Three-Phase Separator"),
}

SOURCE_PREFIXES = ("PP", "P", "K", "CP", "PL", "TUR", "GEN")
SINK_PREFIXES = ("TK", "T", "FL", "FLA", "PR")

VALVE_TYPES: Dict[str, Tuple[str, str]] = {
    "PSV": ("PSV", "Safety Relief Valve"),
    "PRV": ("PSV", "Pressure Relief Valve"),
    "PSE": ("PSV", "Rupture Disk / Safety Element"),
    "ESDV": ("ESDV", "Emergency Shutdown Valve"),
    "SDV": ("ESDV", "Shutdown Valve"),
    "BDV": ("BDV", "Blowdown Valve"),
    "MOV": ("MOTOR_OPERATED_VALVE", "Motor Operated Valve"),
    "XV": ("ACTUATED_VALVE", "Actuated On/Off Valve"),
    "HV": ("MANUAL_VALVE", "Manual Isolation Valve"),
    "FV": ("CONTROL_VALVE", "Flow Control Valve"),
    "PV": ("CONTROL_VALVE", "Pressure Control Valve"),
    "LV": ("CONTROL_VALVE", "Level Control Valve"),
    "TV": ("CONTROL_VALVE", "Temperature Control Valve"),
    "CV": ("CONTROL_VALVE", "Control Valve"),
    "PCV": ("SELF_REGULATING_VALVE", "Pressure Regulating Valve"),
    "TCV": ("SELF_REGULATING_VALVE", "Temperature Regulating Valve"),
    "CH": ("CHECK_VALVE", "Non-Return / Check Valve"),
    "CHECK_VALVE": ("CHECK_VALVE", "Non-Return / Check Valve"),
    "GATE_VALVE": ("GATE_VALVE", "Gate Valve"),
    "BALL_VALVE": ("BALL_VALVE", "Ball Valve"),
    "GLOBE_VALVE": ("GLOBE_VALVE", "Globe Valve"),
    "BUTTERFLY_VALVE": ("BUTTERFLY_VALVE", "Butterfly Valve"),
    "NEEDLE_VALVE": ("NEEDLE_VALVE", "Needle Valve"),
    "PLUG_VALVE": ("PLUG_VALVE", "Plug Valve"),
    "DRAIN": ("DRAIN_VALVE", "Drain Valve"),
    "VENT": ("VENT_VALVE", "Vent Valve"),
}

ISA_VARIABLES: Dict[str, str] = {
    "A": "Analysis",
    "B": "Burner / Combustion",
    "C": "Conductivity",
    "D": "Density",
    "E": "Voltage",
    "F": "Flow",
    "G": "Gauging / Dimension",
    "H": "Hand / Manual",
    "I": "Current",
    "J": "Power",
    "K": "Time / Schedule",
    "L": "Level",
    "M": "Moisture / Humidity",
    "P": "Pressure / Vacuum",
    "Q": "Quantity / Totalizer",
    "R": "Radiation",
    "S": "Speed / Frequency",
    "T": "Temperature",
    "U": "Multivariable",
    "V": "Vibration / Mechanical",
    "W": "Weight / Force",
    "X": "Unclassified",
    "Y": "Event / State",
    "Z": "Position / Dimension",
}

ISA_FUNCTIONS: Dict[str, str] = {
    "A": "Alarm",
    "C": "Controller",
    "D": "Differential",
    "E": "Sensor / Primary Element",
    "F": "Ratio / Fraction",
    "G": "Glass / Viewing Device",
    "H": "High",
    "I": "Indicator",
    "K": "Control Station",
    "L": "Low",
    "O": "Orifice / Restriction",
    "P": "Test Point",
    "R": "Recorder",
    "S": "Switch",
    "T": "Transmitter",
    "V": "Valve / Final Element",
    "W": "Well / Probe",
    "X": "Unclassified Accessory",
    "Y": "Relay / Compute / Converter",
    "Z": "Driver / Actuator",
}

_LOCK_OPEN_RE = re.compile(
    r"(?<![A-Z0-9])(?:CSO|L\.O\.|LO|CAR[\s-]*SEAL[\s-]*OPEN|LOCKED[\s-]*OPEN)(?![A-Z0-9])",
    re.IGNORECASE,
)
_LOCK_CLOSED_RE = re.compile(
    r"(?<![A-Z0-9])(?:CSC|L\.C\.|LC|CAR[\s-]*SEAL[\s-]*CLOSED|LOCKED[\s-]*CLOSED)(?![A-Z0-9])",
    re.IGNORECASE,
)


def _clean_str(txt: Any) -> str:
    """Nettoie une chaîne de caractères, supprime les surrogates CP1252 et normalise l'espacement."""
    if txt is None:
        return ""
    s = str(txt)
    s = s.encode("utf-8", errors="replace").decode("utf-8")
    s = s.replace("\udcb0", "°").replace("\ufffd", "°")
    s = s.replace("\u201d", '"').replace("\\P", " ")
    s = re.sub(r"(?<=\d)#(?=\d)", "/", s)
    return re.sub(r"\s+", " ", s).strip()


def _bb_dist(p: Sequence[float], bb: Sequence[float]) -> float:
    """Distance euclidienne minimale d'un point 2D à une bounding box [xmin, ymin, xmax, ymax]."""
    dx = max(bb[0] - p[0], 0.0, p[0] - bb[2])
    dy = max(bb[1] - p[1], 0.0, p[1] - bb[3])
    return math.hypot(dx, dy)


def _seg_point_projection(p: Sequence[float], a: Sequence[float], b: Sequence[float]) -> Tuple[float, List[float], float]:
    """
    Projette un point P sur un segment [A, B].
    Retourne (t, projection_point, distance) où t est dans [0.0, 1.0].
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 <= 1e-12:
        return 0.0, [float(a[0]), float(a[1])], math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    proj = [a[0] + t * dx, a[1] + t * dy]
    dist = math.hypot(p[0] - proj[0], p[1] - proj[1])
    return t, proj, dist


def _intersect_seg_box(p1: Sequence[float], p2: Sequence[float], box: Sequence[float]) -> Optional[Tuple[float, float]]:
    """
    Algorithme de Liang-Barsky : calcule les paramètres t0, t1 d'intersection
    d'un segment [P1, P2] avec une boîte AABB [xmin, ymin, xmax, ymax].
    Retourne (t0, t1) dans [0.0, 1.0] ou None si aucun chevauchement.
    """
    xmin, ymin, xmax, ymax = box
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    t0, t1 = 0.0, 1.0

    checks = [
        (-dx, p1[0] - xmin),
        (dx, xmax - p1[0]),
        (-dy, p1[1] - ymin),
        (dy, ymax - p1[1]),
    ]
    for p, q in checks:
        if abs(p) < 1e-12:
            if q < 0.0:
                return None
        else:
            r = q / p
            if p < 0.0:
                if r > t0:
                    t0 = r
            else:
                if r < t1:
                    t1 = r
            if t0 > t1:
                return None
    return t0, t1


# ---------------------------------------------------------------------------
# Classe Principale : DxfToPidJsonConverter
# ---------------------------------------------------------------------------


class DxfToPidJsonConverter:
    """
    Convertisseur principal transformant un fichier CAO P&ID (DXF/DWG)
    en un Jumeau Numérique sémantique et topologique JSON.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        config_path: Optional[str | Path] = None,
    ):
        self.cfg = copy.deepcopy(config) if config else load_config(config_path)

    def convert(
        self,
        dxf_path: str | Path,
        out_path: Optional[str | Path] = None,
        review: Optional[str | Path] = None,
        pretty: bool = True,
    ) -> Dict[str, Any]:
        """
        Exécute la conversion complète du DXF vers le JSON sémantique topologique.

        Args:
            dxf_path: Chemin du fichier DXF ou DWG source.
            out_path: Chemin optionnel pour sauvegarder le fichier JSON généré.
            review: Chemin optionnel vers equipment_review.json pour validation humaine.
            pretty: Formate le JSON avec indentation de 2 espaces si True.

        Returns:
            Dict contenant le Jumeau Numérique topologique complet.
        """
        src = Path(dxf_path)
        if not src.exists():
            raise FileNotFoundError(f"Fichier P&ID introuvable : {src}")

        # 1. Parsing DXF robuste via dxf_pid_parser
        raw_data, semantic_data = parse_dxf_to_raw_and_semantic(
            src, out_folder=None, cfg=self.cfg, review=review
        )

        # 2. Identification des entités de symboles vs entités de tuyauterie procédé
        symbol_entity_ids, valve_entity_ids = self._isolate_symbol_entities(
            raw_data, semantic_data
        )

        # 3. Extraction & géométrie affinée des équipements (gestion inline strainer/filter)
        equipments_dict = self._build_equipments(
            raw_data, semantic_data, symbol_entity_ids
        )

        # 4. Fusion des micro-segments en circuits logiques continus et orientation
        circuits = self._build_piping_circuits(
            raw_data, semantic_data, equipments_dict, symbol_entity_ids
        )

        # 5. Détection et rattachement des piquages/nozzles sur les équipements (<28u)
        self._detect_and_attach_nozzles(equipments_dict, circuits)

        # 6. Normalisation et rattachement des vannes aux circuits
        valves = self._build_valves(raw_data, semantic_data, circuits)

        # 7. Extraction des instruments et boucles de régulation ISA-5.1
        instruments, loops = self._build_instruments_and_loops(
            raw_data, semantic_data, circuits, valves
        )

        # 8. Résumé topologique et métriques de connectivité
        equipments_list = list(equipments_dict.values())
        summary = self._build_topology_summary(equipments_list, circuits, valves, instruments, loops)

        # 9. Métadonnées globales
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "converter_version": CONVERTER_VERSION,
            "source_file": src.name,
            "drawing_number": semantic_data.get("titleblock", {}).get("drawing_number", src.stem),
            "drawing_title": semantic_data.get("titleblock", {}).get("title", ""),
            "units": raw_data.get("units", "unitless"),
            "dxf_md5": raw_data.get("source", {}).get("dxf_md5", ""),
            "generated_at": datetime.datetime.now().isoformat(),
        }

        # 10. Assemblage du Jumeau Numérique final
        digital_twin = {
            "metadata": metadata,
            "equipments": equipments_list,
            "piping_circuits": circuits,
            "valves": valves,
            "instruments": instruments,
            "loops": loops,
            "instrument_loops": loops,
            "topology_summary": summary,
        }

        # Sérialisation et nettoyage des surrogates / types non JSON
        sanitized = self._clean_and_serialize(digital_twin)

        if out_path:
            out_file = Path(out_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            indent = 2 if pretty else None
            out_file.write_text(
                json.dumps(sanitized, ensure_ascii=False, indent=indent),
                encoding="utf-8",
                errors="replace",
            )
            logger.info("Jumeau Numérique P&ID enregistré avec succès dans %s", out_file)

        return sanitized

    # -----------------------------------------------------------------------
    # 2. Isolation des entités de symboles
    # -----------------------------------------------------------------------

    def _isolate_symbol_entities(
        self, raw_data: Dict[str, Any], semantic_data: Dict[str, Any]
    ) -> Tuple[Set[str], Set[str]]:
        """
        Distingue les entités graphiques qui constituent des symboles de vannes
        ou d'équipements en ligne (crépines, filtres) des vraies lignes de procédé.
        """
        cfg = self.cfg
        raw_entities = raw_data.get("entities", [])
        role_map = {r["id"]: layer_role(r.get("layer", ""), cfg) for r in raw_entities}
        texts = [r for r in raw_entities if r.get("type") in ("TEXT", "MTEXT", "ATTRIB") and r.get("text")]

        sem_elements = semantic_data.get("elements", [])
        valves = [e for e in sem_elements if e.get("kind") == "valve"]
        equipments = [e for e in sem_elements if e.get("kind") == "equipment"]

        valve_entity_ids: Set[str] = set()
        for v in valves:
            vpos = v.get("position", [0.0, 0.0])
            for r in raw_entities:
                if r.get("type") in ("LINE", "LWPOLYLINE", "POLYLINE") and r.get("bbox"):
                    w = r["bbox"][2] - r["bbox"][0]
                    h = r["bbox"][3] - r["bbox"][1]
                    mid = [(r["bbox"][0] + r["bbox"][2]) / 2.0, (r["bbox"][1] + r["bbox"][3]) / 2.0]
                    # Un symbole de vanne a une taille modeste (<=25u) et est centré sur le tag de vanne
                    if max(w, h) <= 25.0 and math.hypot(mid[0] - vpos[0], mid[1] - vpos[1]) <= 25.0:
                        valve_entity_ids.add(r["id"])

        equipment_entity_ids: Set[str] = set()
        for r in raw_entities:
            if role_map[r["id"]] == "equipment":
                equipment_entity_ids.add(r["id"])

        # Capture des symboles d'équipements en ligne (crépines ST, filtres FIL)
        # Ces équipements ont leurs symboles dessinés sur PIPE ou d'autres calques
        for eq in equipments:
            tag = eq.get("tag", "")
            pre = eq.get("parts", {}).get("pre", "")
            if pre in ("ST", "STR", "FIL", "F") or any(k in tag for k in ("ST", "FIL", "STR")):
                t = next((x for x in texts if x["text"].strip().upper() == tag.strip().upper()), None)
                tpos = t["pos"] if t and "pos" in t else eq.get("position", [0.0, 0.0])
                for r in raw_entities:
                    if r["id"] not in valve_entity_ids and r.get("type") in ("LINE", "LWPOLYLINE", "POLYLINE") and r.get("bbox"):
                        w = r["bbox"][2] - r["bbox"][0]
                        h = r["bbox"][3] - r["bbox"][1]
                        mid = [(r["bbox"][0] + r["bbox"][2]) / 2.0, (r["bbox"][1] + r["bbox"][3]) / 2.0]
                        if max(w, h) <= 40.0 and math.hypot(mid[0] - tpos[0], mid[1] - tpos[1]) <= 25.0:
                            equipment_entity_ids.add(r["id"])

        all_symbol_ids = equipment_entity_ids | valve_entity_ids
        return all_symbol_ids, valve_entity_ids

    # -----------------------------------------------------------------------
    # 3. Construction des équipements
    # -----------------------------------------------------------------------

    def _build_equipments(
        self,
        raw_data: Dict[str, Any],
        semantic_data: Dict[str, Any],
        symbol_entity_ids: Set[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Construit les objets équipements avec tag, type normé, bbox et ancre CAO."""
        raw_entities = raw_data.get("entities", [])
        cfg = self.cfg
        equip_attach_tol = float(cfg.get("equip_attach_tol", 28.0))
        role_map = {r["id"]: layer_role(r.get("layer", ""), cfg) for r in raw_entities}
        texts = [r for r in raw_entities if r.get("type") in ("TEXT", "MTEXT", "ATTRIB") and r.get("text")]

        sem_elements = semantic_data.get("elements", [])
        eq_elements = [e for e in sem_elements if e.get("kind") == "equipment"]

        raw_by_id = {r["id"]: r for r in raw_entities}
        equipments: Dict[str, Dict[str, Any]] = {}

        for idx, el in enumerate(eq_elements, 1):
            tag = _clean_str(el.get("tag", ""))
            parts = el.get("parts", {})
            pre = (parts.get("pre") or "").upper()
            seq = parts.get("seq") or ""

            # Reclassification stricte : CH est un clapet / check valve, jamais un équipement
            if pre == "CH" or "-CH-" in tag or tag.startswith("CH-"):
                continue

            # Filtrer les textes de marge haute / cartouche (ex: Y >= 30180 ou calques ANN-*)
            pos = el.get("position") or [0.0, 0.0]
            el_layer = (el.get("layer") or "").upper()
            if el_layer.startswith("ANN-") or (len(pos) > 1 and pos[1] >= 30180.0):
                continue

            eq_type, eq_desc = EQUIPMENT_TYPES.get(pre, ("EQUIPMENT", "Process Equipment"))
            if el.get("equipment_type"):
                eq_type = str(el["equipment_type"]).upper()

            # Recherche du texte source
            t = next((x for x in texts if x["text"].strip().upper() == tag.strip().upper()), None)
            tpos = t["pos"] if t and "pos" in t else el.get("position", [0.0, 0.0])

            # 1. Si l'équipement est un équipement en ligne (crépine, filtre), chercher son symbole local hors calque equipment
            inline_ents = [
                r for r in raw_entities
                if r["id"] in symbol_entity_ids and r.get("bbox")
                and role_map[r["id"]] != "equipment"
                and _bb_dist(tpos, r["bbox"]) <= equip_attach_tol
                and max(r["bbox"][2] - r["bbox"][0], r["bbox"][3] - r["bbox"][1]) <= 40.0
            ]
            # 2. Si l'équipement est sur le calque equipment (pompes, bacs, colonnes)
            eq_layer_ents = [
                r for r in raw_entities
                if role_map[r["id"]] == "equipment" and r.get("bbox")
                and _bb_dist(tpos, r["bbox"]) <= equip_attach_tol
            ]

            if pre in ("ST", "STR", "FIL", "F") and inline_ents:
                xs = [c for g in inline_ents for c in (g["bbox"][0], g["bbox"][2])]
                ys = [c for g in inline_ents for c in (g["bbox"][1], g["bbox"][3])]
                bbox = [min(xs), min(ys), max(xs), max(ys)]
                anchor = [round((bbox[0] + bbox[2]) / 2.0, 3), round((bbox[1] + bbox[3]) / 2.0, 3)]
            elif eq_layer_ents:
                # Regrouper les entités les plus proches du texte (éviter de fusionner deux équipements)
                min_d = min(_bb_dist(tpos, g["bbox"]) for g in eq_layer_ents)
                closest_ents = [g for g in eq_layer_ents if _bb_dist(tpos, g["bbox"]) <= min_d + 15.0]
                xs = [c for g in closest_ents for c in (g["bbox"][0], g["bbox"][2])]
                ys = [c for g in closest_ents for c in (g["bbox"][1], g["bbox"][3])]
                bbox = [min(xs), min(ys), max(xs), max(ys)]
                anchor = [round((bbox[0] + bbox[2]) / 2.0, 3), round((bbox[1] + bbox[3]) / 2.0, 3)]
            elif inline_ents:
                xs = [c for g in inline_ents for c in (g["bbox"][0], g["bbox"][2])]
                ys = [c for g in inline_ents for c in (g["bbox"][1], g["bbox"][3])]
                bbox = [min(xs), min(ys), max(xs), max(ys)]
                anchor = [round((bbox[0] + bbox[2]) / 2.0, 3), round((bbox[1] + bbox[3]) / 2.0, 3)]
            else:
                bbox = list(el.get("bbox") or [tpos[0] - 10.0, tpos[1] - 10.0, tpos[0] + 10.0, tpos[1] + 10.0])
                anchor = list(el.get("position") or tpos)

            eq_id = f"EQ-{idx:03d}"
            equipments[tag] = {
                "id": eq_id,
                "tag": tag,
                "type": eq_type,
                "description": eq_desc,
                "prefix": pre,
                "sequence": seq,
                "bbox": [round(float(v), 3) for v in bbox],
                "cad_anchor": [round(float(v), 3) for v in anchor],
                "nozzles": [],
                "connected_circuits": [],
                "confidence": round(float(el.get("confidence", 0.9)), 2),
            }

        return equipments

    # -----------------------------------------------------------------------
    # 4. Fusion des micro-segments en circuits continus
    # -----------------------------------------------------------------------

    def _build_piping_circuits(
        self,
        raw_data: Dict[str, Any],
        semantic_data: Dict[str, Any],
        equipments: Dict[str, Dict[str, Any]],
        symbol_entity_ids: Set[str],
    ) -> List[Dict[str, Any]]:
        """
        Fusionne les micro-segments de tuyauterie en circuits continus orientés.
        Rattache les étiquettes de ligne et ordonne les composants en ligne.
        """
        cfg = self.cfg
        snap_tol = float(cfg.get("snap_tol", 8.0))
        bridge_tol = float(cfg.get("bridge_tol", 35.0))
        equip_attach_tol = float(cfg.get("equip_attach_tol", 28.0))
        on_line_tol = float(cfg.get("on_line_tol", 25.0))
        text_attach_max = float(cfg.get("text_attach_max", 150.0))

        raw_entities = raw_data.get("entities", [])
        role_map = {r["id"]: layer_role(r.get("layer", ""), cfg) for r in raw_entities}

        # 1. Collecte des vrais segments de tuyauterie (en excluant les traits de symboles)
        initial_pipe_segs: List[Tuple[List[float], List[float]]] = []
        for r in raw_entities:
            if r["id"] in symbol_entity_ids:
                continue
            if role_map[r["id"]] == "piping" and r["type"] in ("LINE", "LWPOLYLINE", "POLYLINE"):
                pts = r.get("pts", [])
                if r.get("closed") and pts:
                    pts = pts + [pts[0]]
                for a, b in zip(pts, pts[1:]):
                    if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-3:
                        initial_pipe_segs.append(([float(a[0]), float(a[1])], [float(b[0]), float(b[1])]))

        # 2. Découpage des lignes traversant le corps des équipements (Liang-Barsky)
        # Process piping exists outside equipment boundaries; inside is internal volume.
        clipped_segs: List[Dict[str, Any]] = []
        for a, b in initial_pipe_segs:
            cuts: List[float] = [0.0, 1.0]
            for eq in equipments.values():
                inter = _intersect_seg_box(a, b, eq["bbox"])
                if inter:
                    t0, t1 = inter
                    if 0.0 < t0 < 1.0:
                        cuts.append(t0)
                    if 0.0 < t1 < 1.0:
                        cuts.append(t1)

            cuts = sorted(set(cuts))
            dx, dy = b[0] - a[0], b[1] - a[1]

            for t_start, t_end in zip(cuts, cuts[1:]):
                if t_end - t_start < 1e-4:
                    continue
                p_start = [a[0] + t_start * dx, a[1] + t_start * dy]
                p_end = [a[0] + t_end * dx, a[1] + t_end * dy]
                p_mid = [(p_start[0] + p_end[0]) / 2.0, (p_start[1] + p_end[1]) / 2.0]

                # Si le milieu du sous-segment est strictement à l'intérieur d'un équipement, on l'écarte
                inside_any = False
                for eq in equipments.values():
                    bx = eq["bbox"]
                    if bx[0] < p_mid[0] < bx[2] and bx[1] < p_mid[1] < bx[3]:
                        inside_any = True
                        break

                if not inside_any:
                    clipped_segs.append({"a": p_start, "b": p_end, "handle": ""})

        # 3. Coupure aux jonctions en T
        if cfg.get("split_t_junctions", True) and clipped_segs:
            clipped_segs = split_t_junctions(clipped_segs, snap_tol)

        # 4. Graphe de connectivité par Snap & Union-Find
        snap = Snap(snap_tol)
        uf = UF()
        seg_nodes: List[Tuple[int, int]] = []
        for sg in clipped_segs:
            na = snap.node(sg["a"])
            nb = snap.node(sg["b"])
            uf.u(na, nb)
            seg_nodes.append((na, nb))

        # Pontage des vannes en ligne
        valves_sem = [e for e in semantic_data.get("elements", []) if e.get("kind") == "valve"]
        for v in valves_sem:
            vpos = v.get("position", [0.0, 0.0])
            near_nodes = [
                n for n, pt in enumerate(snap.pts)
                if math.hypot(pt[0] - vpos[0], pt[1] - vpos[1]) <= bridge_tol
            ]
            if len(near_nodes) >= 2:
                for n2 in near_nodes[1:]:
                    uf.u(near_nodes[0], n2)

        # 5. Détection des nœuds rattachés aux équipements (au plus proche)
        node_equipment: Dict[int, str] = {}
        for n, pt in enumerate(snap.pts):
            best_tag = None
            best_d = equip_attach_tol + 1.0
            for tag, eq in equipments.items():
                d = _bb_dist(pt, eq["bbox"])
                if d < best_d:
                    best_d = d
                    best_tag = tag
            if best_tag and best_d <= equip_attach_tol:
                node_equipment[n] = best_tag

        node_deg: Dict[int, List[int]] = defaultdict(list)
        for i, (na, nb) in enumerate(seg_nodes):
            node_deg[na].append(i)
            node_deg[nb].append(i)

        terminal_nodes: Set[int] = set()
        for n, seg_ids in node_deg.items():
            if n in node_equipment or len(seg_ids) != 2:
                terminal_nodes.add(n)

        # 6. Parcours des chaînes entre nœuds terminaux
        adj: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
        for i, (na, nb) in enumerate(seg_nodes):
            adj[na].append((nb, i))
            adj[nb].append((na, i))

        visited_edges: Set[int] = set()
        chains: List[Dict[str, Any]] = []

        for start_node in list(terminal_nodes):
            for nxt_node, edge_idx in adj[start_node]:
                if edge_idx in visited_edges:
                    continue

                chain_nodes = [start_node, nxt_node]
                chain_edges = [edge_idx]
                visited_edges.add(edge_idx)

                curr = nxt_node
                while curr not in terminal_nodes and len(node_deg[curr]) == 2:
                    neighbors = [item for item in adj[curr] if item[1] != chain_edges[-1]]
                    if not neighbors:
                        break
                    nxt, e_idx = neighbors[0]
                    if e_idx in visited_edges:
                        break
                    chain_nodes.append(nxt)
                    chain_edges.append(e_idx)
                    visited_edges.add(e_idx)
                    curr = nxt

                chains.append({
                    "nodes": chain_nodes,
                    "edges": chain_edges,
                    "start_node": start_node,
                    "end_node": chain_nodes[-1],
                })

        # Boucles résiduelles fermées
        for i, (na, nb) in enumerate(seg_nodes):
            if i not in visited_edges:
                visited_edges.add(i)
                chain_nodes = [na, nb]
                chain_edges = [i]
                curr = nb
                while True:
                    neighbors = [item for item in adj[curr] if item[1] not in visited_edges]
                    if not neighbors:
                        break
                    nxt, e_idx = neighbors[0]
                    chain_nodes.append(nxt)
                    chain_edges.append(e_idx)
                    visited_edges.add(e_idx)
                    curr = nxt
                chains.append({
                    "nodes": chain_nodes,
                    "edges": chain_edges,
                    "start_node": chain_nodes[0],
                    "end_node": chain_nodes[-1],
                })

        # 7. Collecte des étiquettes de ligne
        line_tags = []
        for r in raw_entities:
            if r.get("type") in ("TEXT", "MTEXT", "ATTRIB") and r.get("text"):
                c = classify(r["text"], cfg)
                if c and c.get("kind") == "line":
                    line_tags.append({
                        "tag": c["tag"],
                        "parts": c["parts"],
                        "pos": r.get("pos", [0.0, 0.0]),
                    })

        # 8. Composants en ligne candidats
        inline_candidates = []
        for vel in semantic_data.get("elements", []):
            if vel.get("kind") in ("valve", "instrument"):
                inline_candidates.append({
                    "type": vel["kind"].upper(),
                    "tag": vel["tag"],
                    "sub_type": vel.get("parts", {}).get("pre", "VALVE"),
                    "pos": vel.get("position", [0.0, 0.0]),
                })

        # 9. Assemblage et orientation des circuits
        circuits: List[Dict[str, Any]] = []

        for cid_idx, ch in enumerate(chains, 1):
            nodes = ch["nodes"]
            poly = [snap.pts[n] for n in nodes]
            total_len = sum(math.hypot(poly[i + 1][0] - poly[i][0], poly[i + 1][1] - poly[i][1]) for i in range(len(poly) - 1))
            if total_len < float(cfg.get("min_line_length", 5.0)):
                continue

            # Rattachement étiquette de ligne la plus proche
            best_tag = None
            min_tag_dist = text_attach_max
            for lt in line_tags:
                d = min(
                    seg_dist(lt["pos"], poly[i], poly[i + 1])
                    for i in range(len(poly) - 1)
                )
                if d <= min_tag_dist:
                    min_tag_dist = d
                    best_tag = lt

            line_tag_val = best_tag["tag"] if best_tag else None
            parts = best_tag["parts"] if best_tag else {}
            fluid_val = parts.get("fluid")
            size_val = parts.get("nps")
            spec_val = parts.get("spec")

            s_node, e_node = ch["start_node"], ch["end_node"]
            s_eq = node_equipment.get(s_node)
            e_eq = node_equipment.get(e_node)

            # Orientation Source -> Puits ou convention gauche -> droite
            direction = 1
            if s_eq and e_eq:
                s_pre = equipments[s_eq]["prefix"]
                e_pre = equipments[e_eq]["prefix"]
                # Aspiration : Crépine / Filtre -> Pompe / Compresseur
                if s_pre in ("ST", "STR", "FIL", "F") and e_pre in ("PP", "P", "K", "CP"):
                    direction = 1
                elif e_pre in ("ST", "STR", "FIL", "F") and s_pre in ("PP", "P", "K", "CP"):
                    direction = -1
                elif s_pre in SOURCE_PREFIXES or e_pre in SINK_PREFIXES:
                    direction = 1
                elif e_pre in SOURCE_PREFIXES or s_pre in SINK_PREFIXES:
                    direction = -1
            elif e_eq and not s_eq:
                e_pre = equipments[e_eq]["prefix"]
                if e_pre in SOURCE_PREFIXES:
                    direction = -1
                elif e_pre in SINK_PREFIXES:
                    direction = 1
            elif s_eq and not e_eq:
                s_pre = equipments[s_eq]["prefix"]
                if s_pre in SOURCE_PREFIXES:
                    direction = 1
                elif s_pre in SINK_PREFIXES:
                    direction = -1
            else:
                if poly[0][0] > poly[-1][0]:
                    direction = -1

            if direction == -1:
                poly = poly[::-1]
                s_node, e_node = e_node, s_node
                s_eq, e_eq = e_eq, s_eq

            # Ordonnancement des composants en ligne
            in_line_components = []
            cum_dist = [0.0]
            for i in range(len(poly) - 1):
                cum_dist.append(cum_dist[-1] + math.hypot(poly[i + 1][0] - poly[i][0], poly[i + 1][1] - poly[i][1]))

            for comp in inline_candidates:
                cpos = comp["pos"]
                if comp["tag"] in (s_eq, e_eq):
                    continue

                best_c_dist = on_line_tol + 1.0
                best_s = 0.0
                for i in range(len(poly) - 1):
                    t, proj, d = _seg_point_projection(cpos, poly[i], poly[i + 1])
                    if d < best_c_dist:
                        best_c_dist = d
                        best_s = cum_dist[i] + t * (cum_dist[i + 1] - cum_dist[i])

                if best_c_dist <= on_line_tol and total_len > 0:
                    ratio = max(0.0, min(1.0, best_s / total_len))
                    in_line_components.append({
                        "type": comp["type"],
                        "tag": comp["tag"],
                        "sub_type": comp["sub_type"],
                        "cad_coords": [round(cpos[0], 3), round(cpos[1], 3)],
                        "position_ratio": round(ratio, 4),
                    })

            in_line_components.sort(key=lambda c: c["position_ratio"])

            circ_id = f"CIRC-{cid_idx:03d}"

            from_node = {
                "equipment_tag": s_eq,
                "nozzle": None,
                "node_type": "EQUIPMENT" if s_eq else ("TEE_JUNCTION" if len(node_deg[s_node]) >= 3 else "OPEN_HEADER"),
            }
            to_node = {
                "equipment_tag": e_eq,
                "nozzle": None,
                "node_type": "EQUIPMENT" if e_eq else ("TEE_JUNCTION" if len(node_deg[e_node]) >= 3 else "OPEN_HEADER"),
            }

            circuit_obj = {
                "line_id": circ_id,
                "line_tag": line_tag_val,
                "fluid": fluid_val,
                "nominal_size": size_val,
                "spec": spec_val,
                "from_node": from_node,
                "to_node": to_node,
                "in_line_components": in_line_components,
                "polyline": [[round(p[0], 3), round(p[1], 3)] for p in poly],
                "length": round(total_len, 3),
                "confidence": round(1.0 - (min_tag_dist / text_attach_max) * 0.3, 2) if best_tag else 0.6,
            }
            circuits.append(circuit_obj)

            if s_eq:
                equipments[s_eq]["connected_circuits"].append(circ_id)
            if e_eq:
                equipments[e_eq]["connected_circuits"].append(circ_id)

        return circuits

    # -----------------------------------------------------------------------
    # 5. Détection et rattachement des piquages / nozzles
    # -----------------------------------------------------------------------

    def _detect_and_attach_nozzles(
        self,
        equipments: Dict[str, Dict[str, Any]],
        circuits: List[Dict[str, Any]],
    ) -> None:
        """
        Détecte géométriquement les piquages/nozzles sur la frontière des équipements (<28u).
        Affecte les directions (INLET / OUTLET / BIDIRECTIONAL).
        """
        snap_tol = float(self.cfg.get("snap_tol", 8.0))

        for eq_tag, eq in equipments.items():
            bb = eq["bbox"]
            contact_points: List[Dict[str, Any]] = []

            for c in circuits:
                circ_id = c["line_id"]
                poly = c["polyline"]
                if not poly:
                    continue

                p_start = poly[0]
                if c["from_node"].get("equipment_tag") == eq_tag:
                    contact_points.append({
                        "coords": p_start,
                        "direction": "OUTLET",
                        "circuit_id": circ_id,
                        "is_start": True,
                    })

                p_end = poly[-1]
                if c["to_node"].get("equipment_tag") == eq_tag:
                    contact_points.append({
                        "coords": p_end,
                        "direction": "INLET",
                        "circuit_id": circ_id,
                        "is_start": False,
                    })

            # Dédoublonnage des points de contact voisins
            unique_nozzles = []
            for cp in contact_points:
                merged = False
                for un in unique_nozzles:
                    if math.hypot(un["coords"][0] - cp["coords"][0], un["coords"][1] - cp["coords"][1]) <= snap_tol:
                        if un["direction"] != cp["direction"]:
                            un["direction"] = "BIDIRECTIONAL"
                        un["circuits"].append(cp["circuit_id"])
                        merged = True
                        break
                if not merged:
                    unique_nozzles.append({
                        "coords": cp["coords"],
                        "direction": cp["direction"],
                        "circuits": [cp["circuit_id"]],
                    })

            for n_idx, un in enumerate(unique_nozzles, 1):
                n_tag = f"N{n_idx}"
                n_id = f"NOZ-{eq_tag}-{n_tag}"
                nx, ny = un["coords"][0], un["coords"][1]
                # Calcul de l'orientation (N / S / E / W) par rapport à la bounding box
                d_w = abs(nx - bb[0])
                d_e = abs(nx - bb[2])
                d_s = abs(ny - bb[1])
                d_n = abs(ny - bb[3])
                min_edge = min(d_w, d_e, d_s, d_n)
                if min_edge == d_w:
                    orientation = "W"
                elif min_edge == d_e:
                    orientation = "E"
                elif min_edge == d_n:
                    orientation = "N"
                else:
                    orientation = "S"

                nozzle_obj = {
                    "id": n_id,
                    "tag": n_tag,
                    "coords": [round(un["coords"][0], 3), round(un["coords"][1], 3)],
                    "direction": un["direction"],
                    "orientation": orientation,
                    "connected_circuits": un["circuits"],
                }
                eq["nozzles"].append(nozzle_obj)

                for circ_id in un["circuits"]:
                    for c in circuits:
                        if c["line_id"] == circ_id:
                            if c["from_node"].get("equipment_tag") == eq_tag and not c["from_node"].get("nozzle"):
                                c["from_node"]["nozzle"] = n_tag
                            if c["to_node"].get("equipment_tag") == eq_tag and not c["to_node"].get("nozzle"):
                                c["to_node"]["nozzle"] = n_tag

    # -----------------------------------------------------------------------
    # 6. Normalisation et rattachement des vannes
    # -----------------------------------------------------------------------

    def _build_valves(
        self,
        raw_data: Dict[str, Any],
        semantic_data: Dict[str, Any],
        circuits: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Construit la liste des vannes normalisées rattachées au circuit le plus proche."""
        on_line_tol = float(self.cfg.get("on_line_tol", 25.0))
        valves: List[Dict[str, Any]] = []

        sem_valves = [e for e in semantic_data.get("elements", []) if e.get("kind") == "valve"]

        raw_texts = " ".join(
            r.get("text", "") for r in raw_data.get("entities", [])
            if r.get("type") in ("TEXT", "MTEXT", "ATTRIB")
        )

        for idx, vel in enumerate(sem_valves, 1):
            tag = _clean_str(vel.get("tag", f"VALVE-{idx:03d}"))
            parts = vel.get("parts", {})
            pre = (parts.get("pre") or "").upper()
            coords = vel.get("position", [0.0, 0.0])

            v_type, _ = VALVE_TYPES.get(pre, ("MANUAL_VALVE", "Manual Valve"))
            if "PSV" in tag or "PRV" in tag:
                v_type = "PSV"
            elif "ESDV" in tag or "SDV" in tag:
                v_type = "ESDV"
            elif "BDV" in tag:
                v_type = "BDV"
            elif any(k in tag for k in ("FV", "PV", "LV", "TV", "CV")):
                v_type = "CONTROL_VALVE"
            elif "CHECK" in tag or pre == "CH" or "-CH-" in tag:
                v_type = "CHECK_VALVE"

            lock_status = "NONE"
            if re.search(rf"{re.escape(tag)}[^\n]{{0,60}}{_LOCK_OPEN_RE.pattern}", raw_texts, re.I):
                lock_status = "CSO"
            elif re.search(rf"{re.escape(tag)}[^\n]{{0,60}}{_LOCK_CLOSED_RE.pattern}", raw_texts, re.I):
                lock_status = "CSC"

            best_circuit_id = None
            best_line_tag = None
            best_ratio = None
            min_dist = on_line_tol + 10.0

            for c in circuits:
                poly = c["polyline"]
                if len(poly) < 2:
                    continue
                cum_len = 0.0
                total_len = c["length"]
                for i in range(len(poly) - 1):
                    seg_len = math.hypot(poly[i + 1][0] - poly[i][0], poly[i + 1][1] - poly[i][1])
                    t, _, d = _seg_point_projection(coords, poly[i], poly[i + 1])
                    if d < min_dist:
                        min_dist = d
                        best_circuit_id = c["line_id"]
                        best_line_tag = c["line_tag"]
                        s = cum_len + t * seg_len
                        best_ratio = round(max(0.0, min(1.0, s / total_len)), 4) if total_len > 0 else 0.0
                    cum_len += seg_len

            v_id = f"VALV-{idx:03d}"
            valve_obj = {
                "id": v_id,
                "tag": tag,
                "valve_type": v_type,
                "sub_type": pre or "VALVE",
                "circuit_id": best_circuit_id,
                "line_tag": best_line_tag,
                "cad_coords": [round(float(coords[0]), 3), round(float(coords[1]), 3)],
                "position_ratio": best_ratio,
                "lock_status": lock_status,
                "has_tag": vel.get("has_text_tag", True),
                "confidence": round(float(vel.get("confidence", 0.85)), 2),
            }
            valves.append(valve_obj)

        return valves

    # -----------------------------------------------------------------------
    # 7. Instruments et boucles de régulation ISA-5.1
    # -----------------------------------------------------------------------

    def _build_instruments_and_loops(
        self,
        raw_data: Dict[str, Any],
        semantic_data: Dict[str, Any],
        circuits: List[Dict[str, Any]],
        valves: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Extrait les instruments ISA-5.1 et reconstitue les boucles de régulation."""
        sem_instr = [e for e in semantic_data.get("elements", []) if e.get("kind") == "instrument"]
        instruments: List[Dict[str, Any]] = []

        for idx, el in enumerate(sem_instr, 1):
            tag = _clean_str(el.get("tag", ""))
            parts = el.get("parts", {})
            var = parts.get("var", "")
            fn = parts.get("fn", "")
            loop_seq = parts.get("loop", "")
            coords = el.get("position", [0.0, 0.0])

            var_desc = ISA_VARIABLES.get(var, "Process Variable")
            fn_desc = " ".join(ISA_FUNCTIONS.get(char, char) for char in fn) or "Instrument"

            best_circuit_id = None
            min_dist = float(self.cfg.get("on_line_tol", 25.0))
            for c in circuits:
                poly = c["polyline"]
                for i in range(len(poly) - 1):
                    _, _, d = _seg_point_projection(coords, poly[i], poly[i + 1])
                    if d < min_dist:
                        min_dist = d
                        best_circuit_id = c["line_id"]

            inst_obj = {
                "id": f"INST-{idx:03d}",
                "tag": tag,
                "variable": var,
                "function": fn,
                "variable_desc": var_desc,
                "function_desc": fn_desc,
                "loop_tag": f"{var}-{loop_seq}" if loop_seq else tag,
                "cad_coords": [round(float(coords[0]), 3), round(float(coords[1]), 3)],
                "circuit_id": best_circuit_id,
                "confidence": round(float(el.get("confidence", 0.9)), 2),
            }
            instruments.append(inst_obj)

        loops_map: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "transmitter": None,
                "controller": None,
                "final_element": None,
                "associated_valves": [],
                "instruments": [],
                "variable": "",
            }
        )

        for inst in instruments:
            ltag = inst["loop_tag"]
            lp = loops_map[ltag]
            lp["instruments"].append(inst["tag"])
            lp["variable"] = inst["variable"]

            fn = inst["function"]
            if "T" in fn and "C" not in fn:
                lp["transmitter"] = inst["tag"]
            elif "C" in fn:
                lp["controller"] = inst["tag"]

        for v in valves:
            vtag = v["tag"]
            for ltag, lp in loops_map.items():
                num_part = re.search(r"\d+", ltag)
                if num_part and num_part.group() in vtag and (v["valve_type"] == "CONTROL_VALVE" or "V" in v["sub_type"]):
                    lp["associated_valves"].append(vtag)
                    if not lp["final_element"]:
                        lp["final_element"] = vtag

        loops: List[Dict[str, Any]] = []
        for idx, (ltag, lp) in enumerate(sorted(loops_map.items()), 1):
            var_name = ISA_VARIABLES.get(lp["variable"], "Process").upper()
            is_comp = bool(lp["transmitter"] and (lp["controller"] or lp["final_element"]))
            loop_obj = {
                "loop_id": f"LOOP-{idx:03d}",
                "loop_tag": ltag,
                "variable": var_name,
                "variable_desc": f"{ISA_VARIABLES.get(lp['variable'], 'Process')} Control Loop",
                "transmitter": lp["transmitter"],
                "controller": lp["controller"],
                "final_element": lp["final_element"],
                "associated_valves": sorted(set(lp["associated_valves"])),
                "instruments": sorted(set(lp["instruments"])),
                "is_complete": is_comp,
            }
            loops.append(loop_obj)

        return instruments, loops

    # -----------------------------------------------------------------------
    # 8. Synthèse de la topologie
    # -----------------------------------------------------------------------

    def _build_topology_summary(
        self,
        equipments: List[Dict[str, Any]],
        circuits: List[Dict[str, Any]],
        valves: List[Dict[str, Any]],
        instruments: List[Dict[str, Any]],
        loops: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Calcule les statistiques et la santé de la topologie du P&ID."""
        total_eq = len(equipments)
        connected_eq = sum(1 for eq in equipments if len(eq["connected_circuits"]) > 0)
        isolated_eq = total_eq - connected_eq

        total_circ = len(circuits)
        complete_circ = sum(
            1 for c in circuits
            if c["from_node"].get("equipment_tag") and c["to_node"].get("equipment_tag")
        )
        open_circ = total_circ - complete_circ

        valves_tagged = sum(1 for v in valves if v.get("has_tag"))
        valves_untagged = len(valves) - valves_tagged

        complete_loops = sum(1 for lp in loops if lp.get("is_complete"))

        connectivity_ratio = round(connected_eq / total_eq, 2) if total_eq > 0 else 0.0

        return {
            "total_equipments": total_eq,
            "connected_equipments": connected_eq,
            "isolated_equipments": isolated_eq,
            "total_circuits": total_circ,
            "complete_circuits": complete_circ,
            "open_circuits": open_circ,
            "total_valves": len(valves),
            "valves_with_tag": valves_tagged,
            "valves_without_tag": valves_untagged,
            "total_instruments": len(instruments),
            "total_loops": len(loops),
            "complete_loops": complete_loops,
            "connectivity_ratio": connectivity_ratio,
        }

    # -----------------------------------------------------------------------
    # 9. Nettoyage et sérialisation
    # -----------------------------------------------------------------------

    def _clean_and_serialize(self, obj: Any) -> Any:
        """Convertit récursivement les structures de données en types JSON purs."""
        if isinstance(obj, dict):
            return {str(k): self._clean_and_serialize(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple, set)):
            return [self._clean_and_serialize(v) for v in obj]
        elif isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return round(obj, 3)
        elif isinstance(obj, (int, str, bool)) or obj is None:
            return obj
        elif hasattr(obj, "item"):
            return self._clean_and_serialize(obj.item())
        else:
            return str(obj)


# ---------------------------------------------------------------------------
# Fonction utilitaire de haut niveau
# ---------------------------------------------------------------------------


def convert_dxf_to_json(
    dxf_path: str | Path,
    output_json_path: Optional[str | Path] = None,
    config: Optional[Dict[str, Any]] = None,
    config_path: Optional[str | Path] = None,
    review: Optional[str | Path] = None,
    pretty: bool = True,
) -> Dict[str, Any]:
    """
    Fonction utilitaire principale pour convertir un fichier DXF/DWG en JSON sémantique topologique.

    Args:
        dxf_path: Chemin vers le fichier DXF ou DWG source.
        output_json_path: Chemin optionnel où sauvegarder le JSON généré.
        config: Dictionnaire de configuration optionnel.
        config_path: Chemin optionnel vers un fichier YAML/JSON de configuration.
        review: Chemin optionnel vers un fichier de revue humaine.
        pretty: Si True, formate le JSON avec indentation de 2 espaces.

    Returns:
        Dict contenant le Jumeau Numérique topologique complet.
    """
    converter = DxfToPidJsonConverter(config=config, config_path=config_path)
    return converter.convert(
        dxf_path=dxf_path,
        out_path=output_json_path,
        review=review,
        pretty=pretty,
    )


__all__ = [
    "CONVERTER_VERSION",
    "SCHEMA_VERSION",
    "EQUIPMENT_TYPES",
    "VALVE_TYPES",
    "ISA_VARIABLES",
    "ISA_FUNCTIONS",
    "DxfToPidJsonConverter",
    "convert_dxf_to_json",
]


# ---------------------------------------------------------------------------
# Point d'entrée CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convertisseur DXF vers JSON Sémantique Topologique pour P&ID (ARKAN Module 1)"
    )
    parser.add_argument("dxf_path", help="Chemin vers le fichier DXF ou DWG à convertir")
    parser.add_argument("out_path", nargs="?", default=None, help="Chemin du fichier JSON en sortie")
    parser.add_argument("--review", help="Chemin vers equipment_review.json pour validation humaine")
    parser.add_argument("--pretty", action="store_true", default=True, help="Activer l'indentation JSON (défaut: True)")
    args = parser.parse_args()

    input_path = Path(args.dxf_path)
    output_path = Path(args.out_path) if args.out_path else input_path.with_name(f"{input_path.stem}_topology.json")

    converter = DxfToPidJsonConverter()
    result = converter.convert(
        dxf_path=input_path,
        out_path=output_path,
        review=args.review,
        pretty=args.pretty,
    )

    summary = result.get("topology_summary", {})
    print(f"\n=======================================================")
    print(f" JUMEAU NUMÉRIQUE P&ID GÉNÉRÉ AVEC SUCCÈS")
    print(f"=======================================================")
    print(f" Source      : {input_path.name}")
    print(f" Sortie      : {output_path}")
    print(f" Équipements : {summary.get('total_equipments')} ({summary.get('connected_equipments')} connectés)")
    print(f" Circuits    : {summary.get('total_circuits')} ({summary.get('complete_circuits')} complets)")
    print(f" Vannes      : {summary.get('total_valves')} ({summary.get('valves_with_tag')} avec tag)")
    print(f" Instruments : {summary.get('total_instruments')}, Boucles : {summary.get('total_loops')}")
    print(f" Connectivité: {summary.get('connectivity_ratio', 0) * 100:.1f} %")
    print(f"=======================================================\n")


if __name__ == "__main__":
    main()
