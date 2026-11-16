# dwg_iso_extractor.py

- find_accoreconsole · function · L49-L54 — def find_accoreconsole() -> Optional[str]
- convert_dwg_to_dxf_headless · function · L57-L124 — def convert_dwg_to_dxf_headless(dwg_path: str, output_dxf_path: str, timeout_sec: int = 60) -> bool
- clean_mtext · function · L127-L141 — def clean_mtext(text: str) -> str
- parse_title_block_metadata · function · L144-L184 — def parse_title_block_metadata(doc) -> Dict[str, Any]
- parse_acad_table_from_doc · function · L187-L355 — def parse_acad_table_from_doc(doc) -> List[Dict[str, Any]]
- extract_entities_from_dxf · function · L358-L394 — def extract_entities_from_dxf(dxf_path: str) -> List[Tuple[float, float, str]]
- parse_bom_from_entities · function · L397-L723 — def parse_bom_from_entities(entities: List[Tuple[float, float, str]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]
- reconstruct_sheet_items · function · L726-L1280 — def reconstruct_sheet_items(doc, page_idx: int, cad_topology: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]
- reconstruct_bom_from_pdf_graphics · function · L1283-L1331 — def reconstruct_bom_from_pdf_graphics(pdf_path: str, global_metadata: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]
- extract_iso_from_pdf · function · L1335-L1676 — def extract_iso_from_pdf(pdf_path: str) -> Dict[str, Any]
- _w_center_x · function · L1486-L1487 — def _w_center_x(w_tuple)
- format_iso_text_summary · function · L1679-L1704 — def format_iso_text_summary(bom_items: List[Dict[str, Any]], spools: List[Dict[str, Any]], metadata: Dict[str, Any], filename: str) -> str
- process_dwg_isometric · function · L1707-L1808 — def process_dwg_isometric(file_path: str) -> Dict[str, Any]
