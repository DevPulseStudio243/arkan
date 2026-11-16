# cable_schedule_parser.py

- _clean_str · function · L53-L56 — def _clean_str(val: Any) -> str
- _normalize_header · function · L59-L67 — def _normalize_header(header: str) -> str
- _find_cs_column_mapping · function · L70-L106 — def _find_cs_column_mapping(headers: List[str]) -> Dict[str, int]
- _detect_headers_and_start · function · L109-L141 — def _detect_headers_and_start(rows: List[Any]) -> Tuple[List[str], int]
- _parse_float · function · L144-L154 — def _parse_float(val: Any) -> Optional[float]
- CableScheduleParser · class · L157-L282 — class CableScheduleParser
- parse_file · method · L161-L172 — def parse_file(cls, file_path: Union[str, Path]) -> List[Dict[str, Any]]
- _parse_excel · method · L175-L207 — def _parse_excel(cls, path: Path) -> List[Dict[str, Any]]
- _parse_csv · method · L210-L249 — def _parse_csv(cls, path: Path) -> List[Dict[str, Any]]
- _extract_item_from_row · method · L252-L282 — def _extract_item_from_row(row: Union[tuple, list], mapping: Dict[str, int]) -> Optional[Dict[str, Any]]
- get_val · function · L253-L258 — def get_val(field: str) -> Optional[str]
