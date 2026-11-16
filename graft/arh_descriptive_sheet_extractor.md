# arh_descriptive_sheet_extractor.py

- ARHDescriptiveSheetExtractor · class · L16-L231 — class ARHDescriptiveSheetExtractor
- is_descriptive_sheet · method · L24-L36 — def is_descriptive_sheet(self, text: str) -> bool
- extract_from_text · method · L38-L231 — def extract_from_text(self, text: str, filename: str = "", page_num: int = 1) -> Dict[str, Any]
- parse_pressure · function · L110-L140 — def parse_pressure(pattern: str, txt: str) -> Optional[Dict[str, Any]]: # Formule multiplicatrice ex: "1.5 × design pressure"
- parse_temp · function · L147-L151 — def parse_temp(pattern: str, txt: str) -> Optional[str]
