# bpu_planner_engine.py

- normalize_unit · function · L59-L64 — def normalize_unit(unit_raw: str) -> str
- BPUExtractor · class · L71-L421 — class BPUExtractor
- extract_from_excel · method · L75-L99 — def extract_from_excel(file_bytes: bytes, filename: str = "bpu.xlsx") -> List[Dict[str, Any]]
- extract_from_pdf · method · L102-L133 — def extract_from_pdf(file_bytes: bytes, filename: str = "bpu.pdf") -> List[Dict[str, Any]]
- extract_from_csv · method · L136-L148 — def extract_from_csv(csv_text: str) -> List[Dict[str, Any]]
- extract_from_text · method · L151-L257 — def extract_from_text(pasted_text: str) -> List[Dict[str, Any]]
- _parse_dataframe · method · L260-L331 — def _parse_dataframe(df: pd.DataFrame, source: str = "") -> List[Dict[str, Any]]
- _parse_raw_unstructured_dataframe · method · L334-L341 — def _parse_raw_unstructured_dataframe(df: pd.DataFrame, source: str = "") -> List[Dict[str, Any]]
- _parse_float · method · L344-L356 — def _parse_float(val: Any) -> Optional[float]
- enrich_item_with_knowledge · method · L359-L413 — def enrich_item_with_knowledge(item: Dict[str, Any]) -> Dict[str, Any]
- enrich_items_with_knowledge · method · L416-L421 — def enrich_items_with_knowledge(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]
- BPUPlanningConverter · class · L428-L687 — class BPUPlanningConverter
- convert_bpu_to_planning · method · L454-L604 — def convert_bpu_to_planning( cls, bpu_items: List[Dict[str, Any]], project_name: str = "PROJET_BPU_EXTRAIT", include_pcc: bool = True ) -> PlanningResponse
- _infer_discipline_from_text · method · L607-L636 — def _infer_discipline_from_text(desig: str) -> str
- _infer_yield_from_discipline_and_unit · method · L639-L666 — def _infer_yield_from_discipline_and_unit(discipline: str, unit: str) -> Tuple[float, str]
- _get_phase_from_discipline · method · L669-L687 — def _get_phase_from_discipline(discipline: str) -> str
