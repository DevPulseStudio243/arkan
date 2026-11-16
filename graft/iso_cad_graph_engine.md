# iso_cad_graph_engine.py

- IsometricCADGraphEngine · class · L31-L203 — class IsometricCADGraphEngine
- __init__ · method · L34-L38 — def __init__(self, dxf_path: str)
- _load_document · method · L40-L53 — def _load_document(self)
- is_valid · method · L55-L56 — def is_valid(self) -> bool
- extract_cad_topology · method · L58-L162 — def extract_cad_topology(self) -> Dict[str, Any]
- _calculate_bends_from_segments · method · L164-L203 — def _calculate_bends_from_segments(self, segments: List[Dict[str, Any]], tolerance_dist: float = 25.0) -> int
- analyze_isometric_cad_file · function · L206-L223 — def analyze_isometric_cad_file(dxf_or_dwg_path: str) -> Dict[str, Any]
- analyze_pdf_vector_topology · function · L226-L738 — def analyze_pdf_vector_topology(pdf_path: str, bom_items: Optional[List[Dict[str, Any]]] = None, page_idx: Optional[int] = None) -> Dict[str, Any]
- is_in_callout_box · function · L277-L281 — def is_in_callout_box(w)
- get_iso_axis · function · L568-L573 — def get_iso_axis(ang: float) -> Optional[int]: # Tolérance 22° pour supporter les pentes de tuyauterie (FALL, drainage, skews)
