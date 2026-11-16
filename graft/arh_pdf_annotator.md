# arh_pdf_annotator.py

- ARHPDFAnnotator · class · L24-L638 — class ARHPDFAnnotator
- __init__ · method · L25-L26 — def __init__(self, uploads_dir: str = os.getenv("ARH_UPLOADS_DIR", "d:/DATA BASE IA/arh_uploads"))
- resolve_pdf_path · method · L28-L97 — def resolve_pdf_path(self, dossier_id: str, filename: str) -> Optional[Path]
- get_master_pdf_path · method · L99-L125 — def get_master_pdf_path(self, dossier_id: str) -> Optional[Path]
- find_target_rects · method · L128-L433 — def find_target_rects( self, page: fitz.Page, title: str = "", snippet: str = "", highlight_terms: Optional[List[str]] = None, target_content: Optional[str] = None ) -> List[fitz.Rect]
- render_page_to_png · method · L435-L561 — def render_page_to_png( self, dossier_id: str, filename: str, page_num: int, target_snippet: Optional[str] = None, target_title: Optional[str] = None, highlight_enabled: bool = True ) -> bytes
- annotate_document · method · L563-L638 — def annotate_document( self, dossier_id: str, filename: str, comments: List[Dict[str, Any]], page_blocks: Optional[List[Dict[str, Any]]] = None ) -> str
