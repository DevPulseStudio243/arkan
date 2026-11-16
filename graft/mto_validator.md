# mto_validator.py

- _safe_float · function · L58-L67 — def _safe_float(val: Any, default: float = 0.0) -> float
- normalize_nps · function · L70-L84 — def normalize_nps(nps_str: str) -> str
- normalize_rating · function · L87-L95 — def normalize_rating(rating_str: str) -> str
- validate_isometric_plan · function · L98-L1019 — def validate_isometric_plan( bom_items: List[Dict[str, Any]], metadata: Dict[str, Any], file_path: Optional[str] = None, raw_text: Optional[str] = None, ocr_lines: Optional[List[str]] = None, spools: Optional[List[Dict[str, Any]]] = None ) -> Dict[str, Any]
- extract_fluid_code · function · L282-L288 — def extract_fluid_code(tag: str) -> Optional[str]
