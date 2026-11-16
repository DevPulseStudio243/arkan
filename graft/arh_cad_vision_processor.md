# arh_cad_vision_processor.py

- ARHCadVisionProcessor · class · L19-L195 — class ARHCadVisionProcessor
- __init__ · method · L22-L23 — def __init__(self)
- _get_ocr_engine · method · L25-L34 — def _get_ocr_engine(self)
- is_large_format_or_drawing · method · L36-L55 — def is_large_format_or_drawing(self, width_pt: float, height_pt: float, text_content: str = "") -> bool
- process_cad_page · method · L57-L165 — def process_cad_page( self, pdf_path: str, page_idx: int, slice_size: int = 1024, overlap_ratio: float = 0.2 ) -> Dict[str, Any]
- _parse_title_block_text · method · L167-L195 — def _parse_title_block_text(self, text: str) -> Dict[str, str]
