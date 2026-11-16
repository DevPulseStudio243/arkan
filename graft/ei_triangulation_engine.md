# ei_triangulation_engine.py

- _get_next_standard_section · function · L30-L35 — def _get_next_standard_section(current_sec_mm2: float) -> float
- _extract_primary_cross_section · function · L38-L43 — def _extract_primary_cross_section(sec_str: Optional[str]) -> Optional[float]
- _format_upsized_cable · function · L46-L61 — def _format_upsized_cable(sec_str: Optional[str], next_s: float) -> str
- EITriangulationEngine · class · L64-L443 — class EITriangulationEngine
- __init__ · method · L67-L75 — def __init__( self, length_tolerance_pct: float = 10.0, max_voltage_drop_power_pct: float = 5.0, max_voltage_drop_control_pct: float = 3.0, ) -> None
- triangulate · method · L77-L143 — def triangulate( self, cad_feeders: List[Dict[str, Any]], cable_schedule_items: List[Dict[str, Any]], calc_note_items: List[Dict[str, Any]], cad_metadata: Optional[Dict[str, Any]] = None, ) -> Dict[str, Any]
- _analyze_tag_triangulation · method · L145-L357 — def _analyze_tag_triangulation( self, tag: str, cad_f: Optional[Dict[str, Any]], cs_f: Optional[Dict[str, Any]], cn_f: Optional[Dict[str, Any]], ) -> Optional[Dict[str, Any]]
- _build_card · method · L359-L443 — def _build_card( self, tag: str, category: str, severity: str, title: str, cad_f: Optional[Dict[str, Any]], cs_f: Optional[Dict[str, Any]], cn_f: Optional[Dict[str, Any]], comment: str, proposed_section: str, proposed_length: float, proposed_action: str, ) -> Dict[str, Any]
