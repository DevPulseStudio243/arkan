# iso_reader_engine.py

- IsometricBOMItem · class · L22-L36 — class IsometricBOMItem
- IsometricMetadata · class · L40-L53 — class IsometricMetadata
- IsometricAnalysisResult · class · L57-L73 — class IsometricAnalysisResult
- IsometricReaderEngine · class · L76-L482 — class IsometricReaderEngine
- __init__ · method · L79-L80 — def __init__(self)
- parse_isometric_document · method · L82-L147 — def parse_isometric_document(self, file_path: str, raw_text: Optional[str] = None) -> IsometricAnalysisResult
- _extract_text_from_file · method · L149-L165 — def _extract_text_from_file(self, path_obj: Path) -> str
- _extract_metadata · method · L167-L221 — def _extract_metadata(self, text: str, filename: str) -> IsometricMetadata
- _extract_bom_items · method · L223-L379 — def _extract_bom_items(self, text: str, default_spec: str) -> List[IsometricBOMItem]
- _get_fallback_bom · method · L381-L424 — def _get_fallback_bom(self, spec: str) -> List[IsometricBOMItem]
- _extract_spools · method · L426-L431 — def _extract_spools(self, text: str) -> List[str]
- _extract_welds · method · L433-L449 — def _extract_welds(self, text: str, bom_items: List[IsometricBOMItem]) -> List[Dict[str, Any]]
- _sync_to_traceability_db · method · L451-L482 — def _sync_to_traceability_db(self, meta: IsometricMetadata, items: List[IsometricBOMItem], spools: List[str], file_path: str)
- get_iso_reader_engine · function · L488-L492 — def get_iso_reader_engine() -> IsometricReaderEngine
