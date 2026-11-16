# pid_schematic.py

- _pt_seg_dist_sq · function · L73-L83 — def _pt_seg_dist_sq(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float
- _find_nearest_segment_angle · function · L86-L99 — def _find_nearest_segment_angle( px: float, py: float, segments: List[Tuple[float, float, float, float]] ) -> float
- _neutral_fallback_svg · function · L102-L121 — def _neutral_fallback_svg(message: str = "Aucun élément P&ID à afficher") -> str
- _resolve_equipment_info · function · L124-L299 — def _resolve_equipment_info( eq_tag: str, eq_bbox: List[float], lines: List[Dict[str, Any]], elements: List[Dict[str, Any]], loops: Any ) -> Tuple[List[str], List[str], str, List[str], List[str]]
- render_schematic · function · L305-L901 — def render_schematic(sem: Any, out_svg_path: Optional[str | Path] = None) -> str
- to_svg · function · L414-L417 — def to_svg(x: float, y: float) -> Tuple[float, float]
