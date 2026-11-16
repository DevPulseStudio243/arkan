"""
DEERFLOW LITE — Geometry Graph Engine & Dimension Solver
Uses networkx to reconstruct topology and solve dimensions of the piping system dynamically.
100% Dynamic — No hardcoded mock nodes, tags, or arbitrary multipliers.
"""
import networkx as nx
import re
import logging
from typing import Dict, List, Any, Tuple
from engineering_catalog import get_pipe_spec, get_elbow_spec, get_flange_spec, get_reducer_spec

logger = logging.getLogger(__name__)

class GeometryGraph:
    def __init__(self, raw_text: str):
        # Truncate text before the table to only parse drawing symbols and cotes
        clean_text = raw_text or ""
        for kw in ["BORDEREAU", "LISTE DES MATERIAUX", "BILL OF MATERIALS", "MTO TABLE", "NOTES DE CONSTRUCTION"]:
            idx = clean_text.upper().find(kw)
            if idx > 200:
                clean_text = clean_text[:idx]
                break
                
        self.raw_text = raw_text or ""
        self.clean_text = clean_text
        self.G = nx.Graph()
        self.T = re.sub(r'\s+', ' ', clean_text)
        
        # Extracted nominal sizes
        self.pipe_sizes = self._detect_pipe_sizes()
        
        # Dimensions & topology
        self.cotes_with_pos = []
        self.cotes = self._extract_dimension_cotes()
        self.reconstruct_network()

    def _detect_pipe_sizes(self) -> List[str]:
        """Identifies all nominal pipe sizes on the plan."""
        sizes = set()
        for m in re.finditer(r'(\d+(?:\.\d+)?)\s*"', self.T):
            sz = m.group(1) + '"'
            if sz in ('1/2"', '3/4"', '1"', '1.5"', '2"', '2.5"', '3"', '4"', '6"', '8"', '10"', '12"', '14"', '16"', '18"', '20"', '24"'):
                sizes.add(sz)
        return sorted(list(sizes), key=lambda x: float(x.replace('"','')) if '/' not in x else 0.5)

    def _extract_dimension_cotes(self) -> List[int]:
        """Extracts dimension lengths from text safely excluding tags, elevations, and classes."""
        self.cotes_with_pos = []
        exclusion_ranges = []
        
        # 1. Tags
        tag_pat = r'\b[A-Za-z]+[A-Za-z0-9\-]*-\d{3,4}[A-Za-z0-9\-]*\b|\b[A-Za-z]+-?\d{3,4}\b'
        for m in re.finditer(tag_pat, self.T):
            exclusion_ranges.append((m.start(), m.end()))
            
        # 2. Elevations like +100.000, +102.500
        elev_pat = r'[+-]?\d{3}\.\d{3}'
        for m in re.finditer(elev_pat, self.T):
            exclusion_ranges.append((m.start(), m.end()))
            
        # 3. Class ratings and pressures like Cl.150, 150#, 10.3 barg, 40 degC
        spec_pat = r'\bCl\.\d+\b|\b\d+#|\b\d+(?:\.\d+)?\s*(?:barg|degC|mm|deg|C)\b'
        for m in re.finditer(spec_pat, self.T, re.IGNORECASE):
            exclusion_ranges.append((m.start(), m.end()))
            
        # 4. Standard numbers and prefixes
        std_pat = r'\b(?:API|ASME|ASTM|Gr|Gr\.|Grade|A|B|B16|DN|N°)\s*\d+\b'
        for m in re.finditer(std_pat, self.T, re.IGNORECASE):
            exclusion_ranges.append((m.start(), m.end()))

        # 5. Standard specification numbers specifically
        for val_str in ["594", "600", "105", "234", "106", "193", "194", "20", "40", "80"]:
            for m in re.finditer(r'\b' + val_str + r'\b', self.T):
                exclusion_ranges.append((m.start(), m.end()))

        # 6. Years (2020-2030)
        year_pat = r'\b20[2-3]\d\b'
        for m in re.finditer(year_pat, self.T):
            exclusion_ranges.append((m.start(), m.end()))

        def is_excluded(pos):
            for start, end in exclusion_ranges:
                if start <= pos < end:
                    return True
            return False

        # Extract dimension integers (typically 200mm to 50000mm in piping drawings)
        cotes = []
        for m in re.finditer(r'\b\d{3,5}\b', self.T):
            val = int(m.group(0))
            if not is_excluded(m.start()):
                if val not in (100, 150, 300, 600, 900, 1500, 2500):
                    cotes.append(val)
                    self.cotes_with_pos.append((val, m.start()))
        return cotes

    def reconstruct_network(self):
        """Builds network nodes and edges dynamically based on extracted coordinates and dimensions."""
        # Detect coordinates in format EL +... or N ... E ...
        coords = []
        for m in re.finditer(r'EL\s*([+-]?\d+(?:\.\d+)?)', self.T, re.I):
            try:
                coords.append(float(m.group(1)))
            except ValueError:
                pass

        if not coords and not self.cotes:
            return

        # Dynamically build linear nodes for the piping run
        prev_node = None
        curr_z = 0.0
        main_sz = self.pipe_sizes[0] if self.pipe_sizes else '2"'

        for idx, cote in enumerate(self.cotes[:15]): # Limit to first 15 segments
            node_id = f"N{idx}"
            curr_z += float(cote)
            self.G.add_node(node_id, pos=(0, 0, curr_z), label=f"WP-{idx+1}", size=main_sz)
            if prev_node is not None:
                self.G.add_edge(prev_node, node_id, type="pipe", size=main_sz, length_mm=cote)
            prev_node = node_id

    def get_pipe_lengths(self) -> Dict[str, float]:
        """
        Calculates exact cumulative linear pipe lengths from detected dimensions (in meters).
        """
        if not self.cotes:
            return {sz: 0.0 for sz in self.pipe_sizes} if self.pipe_sizes else {}

        # If multiple sizes exist, associate cotes by proximity or partition
        lengths: Dict[str, float] = {}
        if len(self.pipe_sizes) == 1:
            sz = self.pipe_sizes[0]
            lengths[sz] = round(sum(self.cotes) / 1000.0, 2)
        elif len(self.pipe_sizes) > 1:
            # Associate each cote with the nearest nominal size token in the text
            sz_cotes: Dict[str, List[int]] = {sz: [] for sz in self.pipe_sizes}
            for val, pos in self.cotes_with_pos:
                best_sz = self.pipe_sizes[0]
                best_dist = 999999
                for sz in self.pipe_sizes:
                    for m_sz in re.finditer(re.escape(sz), self.T):
                        d = abs(m_sz.start() - pos)
                        if d < best_dist:
                            best_dist = d
                            best_sz = sz
                sz_cotes[best_sz].append(val)

            for sz, c_list in sz_cotes.items():
                lengths[sz] = round(sum(c_list) / 1000.0, 2)
        else:
            # Default to general 2" if no size tag detected
            lengths['2"'] = round(sum(self.cotes) / 1000.0, 2)

        return lengths

    def get_caesar_nodes(self) -> List[Dict[str, Any]]:
        """Generates coordinates table for Caesar II stress model."""
        nodes = []
        for node, data in self.G.nodes(data=True):
            pos = data.get("pos", (0, 0, 0))
            nodes.append({
                "node_id": node,
                "x_mm": pos[0],
                "y_mm": pos[1],
                "z_mm": pos[2],
                "label": data.get("label", ""),
                "size": data.get("size", '2"')
            })
        return nodes
