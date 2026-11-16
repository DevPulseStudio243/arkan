# line_list_normalizer.py

- clean_mtext_formatting · function · L100-L124 — def clean_mtext_formatting(text: str) -> str
- convert_nps_to_dn · function · L127-L158 — def convert_nps_to_dn(nps_raw: Any) -> str
- parse_line_tag_metadata · function · L161-L233 — def parse_line_tag_metadata(tag_raw: str) -> Dict[str, Optional[str]]
- extract_off_page_connectors · function · L236-L281 — def extract_off_page_connectors(raw_entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]
- _format_off_page_label · function · L284-L302 — def _format_off_page_label(text: str, is_destination: bool = True) -> str
- _find_nearest_off_page · function · L305-L327 — def _find_nearest_off_page( pt: List[float], opcs: List[Dict[str, Any]], max_radius: float = 85.0 ) -> Optional[Tuple[str, float]]
- normalize_pid_line_list · function · L330-L575 — def normalize_pid_line_list( raw_lines: List[Dict[str, Any]], off_page_connectors: Optional[List[Dict[str, Any]]] = None, equipments: Optional[List[Dict[str, Any]]] = None, drawing_stem: str = "" ) -> List[Dict[str, Any]]
