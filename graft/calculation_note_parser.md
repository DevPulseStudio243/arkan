# calculation_note_parser.py

- _clean_str · function · L62-L65 — def _clean_str(val: Any) -> str
- _normalize_header · function · L68-L77 — def _normalize_header(header: str) -> str
- _find_column_mapping · function · L80-L106 — def _find_column_mapping(headers: List[str]) -> Dict[str, int]
- _parse_float · function · L109-L121 — def _parse_float(val: Any) -> Optional[float]
- CalculationNoteParser · class · L124-L271 — class CalculationNoteParser
- parse_file · method · L128-L139 — def parse_file(cls, file_path: Union[str, Path]) -> List[Dict[str, Any]]
- _parse_excel · method · L142-L177 — def _parse_excel(cls, path: Path) -> List[Dict[str, Any]]
- _parse_csv · method · L180-L225 — def _parse_csv(cls, path: Path) -> List[Dict[str, Any]]: # Détection de l'encodage et délimiteur
- _extract_item_from_row · method · L228-L271 — def _extract_item_from_row(row: Union[tuple, list], mapping: Dict[str, int]) -> Optional[Dict[str, Any]]
- get_val · function · L229-L234 — def get_val(field: str) -> Optional[str]
