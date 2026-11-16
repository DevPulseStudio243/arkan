# arh_doc_ingestion.py

- ARHDocPage · class · L66-L89 — class ARHDocPage
- __init__ · method · L67-L71 — def __init__(self, page_num: int, text: str, source_file: str = "Dossier ARH")
- _classify_sections · method · L73-L80 — def _classify_sections(self) -> List[str]
- to_dict · method · L82-L89 — def to_dict(self) -> Dict[str, Any]
- ARHDocumentIngestion · class · L92-L168 — class ARHDocumentIngestion
- parse_text_with_page_markers · method · L94-L143 — def parse_text_with_page_markers(cls, raw_text: str, filename: str = "Dossier Technique") -> List[ARHDocPage]
- get_section_text · method · L146-L153 — def get_section_text(cls, pages: List[ARHDocPage], section_name: str) -> Tuple[str, List[int]]
- compile_evidence_locator · method · L156-L168 — def compile_evidence_locator(cls, pages: List[ARHDocPage], search_term: str) -> Optional[Dict[str, Any]]
