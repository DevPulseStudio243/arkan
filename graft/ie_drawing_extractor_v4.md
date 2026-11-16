# ie_drawing_extractor_v4.py

- _safe_float · function · L64-L72 — def _safe_float(val: Any, default: Optional[float] = 0.0) -> Optional[float]
- parse_cable_section_string · function · L75-L89 — def parse_cable_section_string(raw_sec: str) -> Tuple[Optional[str], Optional[str], Optional[float]]
- extract_sld_from_pdf_matrix · function · L92-L348 — def extract_sld_from_pdf_matrix( pdf_path: str, original_filename: Optional[str] = None, options: Optional[Dict[str, Any]] = None ) -> Dict[str, Any]
- extract_ie_drawing · function · L351-L366 — def extract_ie_drawing( file_path: str, original_filename: Optional[str] = None, options: Optional[Dict[str, Any]] = None ) -> Dict[str, Any]
- extract_ie_from_dwg_native · function · L369-L493 — def extract_ie_from_dwg_native( dwg_path: str, original_filename: Optional[str] = None, options: Optional[Dict[str, Any]] = None ) -> Dict[str, Any]
