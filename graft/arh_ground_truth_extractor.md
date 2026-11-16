# arh_ground_truth_extractor.py

- extract_text_from_pdf · function · L64-L76 — def extract_text_from_pdf(pdf_path: Path, max_pages: int = 50) -> str
- extract_reserves_from_pdf · function · L79-L130 — def extract_reserves_from_pdf(pdf_path: Path) -> List[str]
- extract_reserves_from_excel · function · L133-L154 — def extract_reserves_from_excel(xlsx_path: Path) -> List[str]
- _is_commented_file · function · L161-L164 — def _is_commented_file(name: str) -> bool
- discover_pairs · function · L167-L227 — def discover_pairs() -> List[Dict[str, Any]]
- _classify_part_from_path · function · L234-L253 — def _classify_part_from_path(path: str) -> str
- reserves_to_anomalies · function · L256-L310 — def reserves_to_anomalies(reserves: List[str]) -> List[Dict[str, Any]]
- format_as_training_example · function · L313-L360 — def format_as_training_example(pair: Dict[str, Any], incoming_text: str, reserves: List[str]) -> Optional[Dict[str, Any]]
- extract_ground_truth · function · L367-L453 — def extract_ground_truth() -> Dict[str, Any]
