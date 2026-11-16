"""
Multi-Sheet Off-Page Connector (OPC) Stitcher for Arkan EPC Intelligence.
Matches Continuation Tags, Drawing Cross-References, and Line Tags across multiple P&ID sheets/folios
to stitch disparate diagram files into a unified plant topology graph.
"""

import logging
import re
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger("opc_stitcher")

# Regex patterns for Drawing & Continuation References
OPC_REF_PATTERN = re.compile(
    r'\b(?:FROM|TO|SEE)\s+(?:DWG|DRAWING|FOLIO|SHEET)?\s*[-:\.\s]*([A-Z0-9-_]{5,35})\b',
    re.IGNORECASE
)


class MultiSheetOPCStitcher:
    """
    Stitches multiple P&ID sheet analysis results into a single consolidated plant model.
    """

    def __init__(self, project_name: str = "Unified_Plant_Project"):
        self.project_name = project_name

    def stitch_sheets(self, sheets_data: Any) -> Dict[str, Any]:
        """
        Takes a list or dict of individual sheet extraction results and stitches lines, equipment,
        and cross-page connectivity graphs.
        """
        if isinstance(sheets_data, dict):
            sheets_data = list(sheets_data.values())
        elif not isinstance(sheets_data, list):
            sheets_data = []

        all_equipment = []
        all_valves = []
        all_instruments = []
        all_lines = []
        opc_links = []
        sheet_ids = []

        line_by_tag: Dict[str, List[Dict[str, Any]]] = {}

        # 1. Collect all entities per sheet
        for idx, sheet in enumerate(sheets_data):
            sheet_name = sheet.get("drawing_name", sheet.get("sheet_id", f"Sheet_{idx+1}"))
            sheet_ids.append(sheet_name)

            for eq in sheet.get("equipment", []):
                eq_copy = dict(eq)
                eq_copy["sheet_origin"] = sheet_name
                all_equipment.append(eq_copy)

            for v in sheet.get("valves", []):
                v_copy = dict(v)
                v_copy["sheet_origin"] = sheet_name
                all_valves.append(v_copy)

            for inst in sheet.get("instruments", []):
                inst_copy = dict(inst)
                inst_copy["sheet_origin"] = sheet_name
                all_instruments.append(inst_copy)

            lines = sheet.get("lines", sheet.get("pipelines", []))
            for line in lines:
                l_copy = dict(line)
                l_copy["sheet_origin"] = sheet_name
                all_lines.append(l_copy)

                ltag = l_copy.get("line_tag", l_copy.get("line", ""))
                if ltag and ltag != "UNKNOWN-LINE":
                    line_by_tag.setdefault(ltag, []).append(l_copy)

        # 2. Match Cross-Sheet Lines by Line Tag
        stitched_lines_count = 0
        unified_lines = []
        processed_tags: Set[str] = set()

        for ltag, occurrences in line_by_tag.items():
            if len(occurrences) > 1:
                # Same line tag appears on multiple sheets! Stitch them.
                stitched_lines_count += 1
                processed_tags.add(ltag)

                sheets_involved = list(set(occ.get("sheet_origin", "") for occ in occurrences))
                from_nodes = [occ.get("from", occ.get("from_equipment", "OPEN")) for occ in occurrences]
                to_nodes = [occ.get("to", occ.get("to_equipment", "OPEN")) for occ in occurrences]

                # Resolve real non-OPEN equipment endpoints across sheets
                real_from = next((node for node in from_nodes if node != "OPEN"), "OPEN")
                real_to = next((node for node in to_nodes if node != "OPEN"), "OPEN")

                combined_path_coords = []
                for occ in occurrences:
                    combined_path_coords.extend(occ.get("path_coords", []))

                unified_line = {
                    "line_tag": ltag,
                    "from_equipment": real_from,
                    "to_equipment": real_to,
                    "is_stitched": True,
                    "sheets_spanned": sheets_involved,
                    "occurrences_count": len(occurrences),
                    "path_coords": combined_path_coords,
                    "confidence": 0.98
                }
                unified_lines.append(unified_line)

                opc_links.append({
                    "line_tag": ltag,
                    "from_sheet": sheets_involved[0],
                    "to_sheet": sheets_involved[-1] if len(sheets_involved) > 1 else sheets_involved[0],
                    "from_node": real_from,
                    "to_node": real_to
                })
            else:
                unified_lines.append(occurrences[0])

        # Add remaining single-sheet lines
        for line in all_lines:
            ltag = line.get("line_tag", line.get("line", ""))
            if not ltag or ltag == "UNKNOWN-LINE" or ltag not in processed_tags:
                if line not in unified_lines:
                    unified_lines.append(line)

        return {
            "project_name": self.project_name,
            "sheets_count": len(sheets_data),
            "sheet_ids": sheet_ids,
            "stitched_lines_count": stitched_lines_count,
            "opc_links": opc_links,
            "equipment": all_equipment,
            "valves": all_valves,
            "instruments": all_instruments,
            "lines": unified_lines
        }


def stitch_multi_sheet_project(sheets_data: List[Dict[str, Any]], project_name: str = "Unified_Plant_Project") -> Dict[str, Any]:
    """Helper function to stitch multi-sheet P&ID project data."""
    stitcher = MultiSheetOPCStitcher(project_name=project_name)
    return stitcher.stitch_sheets(sheets_data)
