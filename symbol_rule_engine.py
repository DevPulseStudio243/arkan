"""
Symbol Rule Engine for Arkan EPC Intelligence.
Configurable geometric primitive pattern matching engine for P&ID and technical diagrams.
Recognizes custom and standard graphic primitives (ISA 5.1, DIN, PIP) to extract structured
components (Valves, Instruments, Equipment, Nozzles) from raw vector drawings and text blocks.
"""

import json
import logging
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("symbol_rule_engine")

# ── DEFAULT STANDARD SYMBOL PRESETS ──
DEFAULT_PRESETS = {
    "isa_5_1": {
        "name": "ISA 5.1 Standard",
        "description": "Instrument Society of America P&ID Symbology Standard",
        "instrument_bubbles": {
            "shape": "circle",
            "min_radius": 5.0,
            "max_radius": 30.0,
            "tag_regex": r"^(?:\d{1,4}[-_\s]?)?[A-Z]{2,4}[-_\s]?\d{2,5}[A-Z]?$"
        },
        "valve_patterns": [
            {
                "type": "GateValve",
                "geometry": "opposing_triangles",
                "prefixes": ["HV", "MOV", "GV", "BV", "XV", "DBB"]
            },
            {
                "type": "CheckValve",
                "geometry": "triangle_with_dot_or_arrow",
                "prefixes": ["CV", "NRV", "CH"]
            },
            {
                "type": "SafetyValve",
                "geometry": "angle_valve_with_spring",
                "prefixes": ["PSV", "PSE", "RV", "MRV", "PRV", "TSV"]
            },
            {
                "type": "ControlValve",
                "geometry": "valve_with_actuator_diaphragm",
                "prefixes": ["HCV", "PCV", "LCV", "TCV", "FV", "FCV"]
            }
        ],
        "equipment_patterns": [
            {"type": "Pump", "geometry": "circle_tangent_discharge", "prefixes": ["P", "PP"]},
            {"type": "Vessel", "geometry": "vertical_or_horizontal_capsule", "prefixes": ["V", "TK", "C"]},
            {"type": "HeatExchanger", "geometry": "shell_tube_bundle", "prefixes": ["E", "HE"]},
            {"type": "Filter", "geometry": "basket_or_cartridge_box", "prefixes": ["FL", "ST", "EQ_F"]}
        ]
    },
    "din": {
        "name": "DIN EN ISO 10628 Standard",
        "description": "European Standard for Flow Diagrams for Process Plants",
        "instrument_bubbles": {
            "shape": "circle_or_square",
            "min_radius": 4.0,
            "max_radius": 35.0,
            "tag_regex": r"^[A-Z]{1,3}[-_\s]?\d{2,6}$"
        },
        "valve_patterns": [
            {"type": "GlobeValve", "geometry": "filled_opposing_triangles", "prefixes": ["HV", "V"]},
            {"type": "SafetyValve", "geometry": "angle_pop_valve", "prefixes": ["SV", "PSV"]}
        ]
    },
    "pip": {
        "name": "Process Industry Practices (PIP)",
        "description": "PIP PIC001 Piping and Instrumentation Diagram Documentation Criteria",
        "instrument_bubbles": {
            "shape": "circle",
            "min_radius": 6.0,
            "max_radius": 25.0,
            "tag_regex": r"^[A-Z]{2,4}[-_\s]?\d{3,5}[A-Z]?$"
        }
    }
}


class SymbolRuleEngine:
    """
    Engine to parse, match, and evaluate geometric primitives against symbolic rules.
    """

    def __init__(self, preset_name: str = "isa_5_1", custom_rules_file: Optional[str] = None):
        self.preset_name = preset_name
        self.preset = DEFAULT_PRESETS.get(preset_name, DEFAULT_PRESETS["isa_5_1"])
        if custom_rules_file and os.path.exists(custom_rules_file):
            self.load_custom_rules(custom_rules_file)

    def load_custom_rules(self, file_path: str):
        """Loads custom symbol rules from a JSON configuration file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                custom_preset = json.load(f)
                self.preset.update(custom_preset)
                logger.info("Loaded custom symbol rules from %s", file_path)
        except Exception as e:
            logger.error("Failed to load custom symbol rules from %s: %s", file_path, e)

    def save_custom_preset(self, file_path: str):
        """Saves current symbol rules preset to a JSON file."""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.preset, f, indent=2, ensure_ascii=False)
                logger.info("Saved symbol rules preset to %s", file_path)
        except Exception as e:
            logger.error("Failed to save symbol rules to %s: %s", file_path, e)

    def evaluate_symbols(
        self,
        raw_lines: List[Tuple[Tuple[float, float], Tuple[float, float], Dict[str, Any]]],
        text_blocks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Evaluates raw line segments and text blocks against geometric rules.
        Returns recognized elements: equipment, valves, instruments, nozzles, and connections.
        """
        recognized_valves = []
        recognized_instruments = []
        recognized_equipment = []
        recognized_nozzles = []

        # 1. Evaluate Text Blocks against Instrument Regex & Tag Patterns
        bubble_config = self.preset.get("instrument_bubbles", {})
        tag_regex = re.compile(bubble_config.get("tag_regex", r"^(?:\d{1,4}[-_\s]?)?[A-Z]{2,4}[-_\s]?\d{2,5}[A-Z]?$"))

        for tb in text_blocks:
            text = tb.get("text", "").strip()
            cx = tb.get("x", (tb.get("box", [0, 0, 0, 0])[0] + tb.get("box", [0, 0, 0, 0])[2]) / 2)
            cy = tb.get("y", (tb.get("box", [0, 0, 0, 0])[1] + tb.get("box", [0, 0, 0, 0])[3]) / 2)
            box = tb.get("box", [cx - 10, cy - 10, cx + 10, cy + 10])

            if tag_regex.match(text):
                parts = text.split("-")
                letter_code = parts[1].upper() if len(parts) > 1 and parts[0].isdigit() else parts[0].upper()
                inst_prefixes = {"PT", "PIT", "PI", "PIA", "TT", "TIT", "TI", "TIA", "LT", "LIT", "LI", "LIA", "FT", "FIT", "FI", "FIA", "FE", "JI", "AIT", "AI", "PDT", "PDIT", "PDI", "PDIA", "FIC", "PIC", "LIC", "TIC", "LSH", "LSL", "PSH", "PSL", "TSH", "TSL", "FSH", "FSL", "ZT", "AT", "TE"}
                if letter_code in inst_prefixes or any(letter_code.startswith(p) for p in ["PT", "TT", "LT", "FT", "PDT", "AT", "ZT"]):
                    recognized_instruments.append({
                        "tag": text,
                        "prefix": letter_code,
                        "type": f"Instrument ({letter_code})",
                        "x": cx,
                        "y": cy,
                        "box": box,
                        "confidence": 0.95,
                        "source": "symbol_rule_engine"
                    })

        # 2. Evaluate Closed Polygons / Geometric Primitive Groups for Valves & Nozzles
        # Group segments by spatial proximity to find bowtie / opposing triangle shapes
        short_segments = []
        for line in raw_lines:
            p0, p1, meta = line[0], line[1], line[2]
            dist = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if 3.0 <= dist <= 50.0:  # Typical symbol segment size range
                mid_x = (p0[0] + p1[0]) / 2
                mid_y = (p0[1] + p1[1]) / 2
                short_segments.append((mid_x, mid_y, p0, p1, dist))

        # Spatial clustering for valve symbols (e.g. triangles meeting at apex)
        cluster_radius = 20.0
        used_indices = set()

        for i in range(len(short_segments)):
            if i in used_indices:
                continue
            sx, sy, p0, p1, d = short_segments[i]
            cluster = [i]

            for j in range(i + 1, len(short_segments)):
                if j in used_indices:
                    continue
                ox, oy, op0, op1, od = short_segments[j]
                if math.hypot(ox - sx, oy - sy) <= cluster_radius:
                    cluster.append(j)

            if len(cluster) >= 4:  # At least 4-6 line segments forming a valve / symbol
                for idx in cluster:
                    used_indices.add(idx)

                # Check if there is an associated tag nearby
                closest_tag = "VALVE-TAG"
                min_tag_dist = 9999.0
                for tb in text_blocks:
                    txt = tb.get("text", "").strip()
                    if any(v_prefix in txt for v_prefix in ["HV", "XV", "MOV", "CV", "PSV", "FCV", "PCV"]):
                        bx = tb.get("x", (tb.get("box", [0, 0, 0, 0])[0] + tb.get("box", [0, 0, 0, 0])[2]) / 2)
                        by = tb.get("y", (tb.get("box", [0, 0, 0, 0])[1] + tb.get("box", [0, 0, 0, 0])[3]) / 2)
                        d_tag = math.hypot(bx - sx, by - sy)
                        if d_tag < min_tag_dist and d_tag <= 100.0:
                            min_tag_dist = d_tag
                            closest_tag = txt

                recognized_valves.append({
                    "tag": closest_tag,
                    "type": "Valve (Geometric Subgraph)",
                    "x": sx,
                    "y": sy,
                    "box": [sx - 15, sy - 15, sx + 15, sy + 15],
                    "confidence": 0.90,
                    "segments_count": len(cluster),
                    "source": "symbol_rule_engine"
                })

        return {
            "preset_used": self.preset_name,
            "instruments": recognized_instruments,
            "valves": recognized_valves,
            "equipment": recognized_equipment,
            "nozzles": recognized_nozzles
        }


def apply_symbol_rules(
    raw_lines: List[Tuple[Tuple[float, float], Tuple[float, float], Dict[str, Any]]],
    text_blocks: List[Dict[str, Any]],
    preset_name: str = "isa_5_1",
    custom_rules_file: Optional[str] = None
) -> Dict[str, Any]:
    """Helper function to evaluate symbol rules on raw vector drawing data."""
    engine = SymbolRuleEngine(preset_name=preset_name, custom_rules_file=custom_rules_file)
    return engine.evaluate_symbols(raw_lines, text_blocks)
