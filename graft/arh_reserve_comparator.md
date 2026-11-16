# arh_reserve_comparator.py

- ARHReserveSemanticAnalyzer · class · L251-L363 — class ARHReserveSemanticAnalyzer
- analyze_reserve_in_text · method · L258-L336 — def analyze_reserve_in_text( self, reserve_type: str, text: str, reserve_description: str, ) -> Tuple[str, str, float]
- _generic_analysis · method · L338-L363 — def _generic_analysis( self, reserve_description: str, text: str ) -> Tuple[str, str, float]
- ARHReserveComparator · class · L370-L663 — class ARHReserveComparator
- __init__ · method · L376-L379 — def __init__(self)
- compare_revisions · method · L383-L496 — def compare_revisions( self, reserves_list: List[Dict[str, Any]], new_docs: List[Dict[str, Any]], dossier_id: str, equipment_tag: str, ) -> Dict[str, Any]
- load_reserves_from_db · method · L500-L540 — def load_reserves_from_db(self, dossier_id: str) -> List[Dict[str, Any]]
- load_reserves_from_arh_letter_text · method · L542-L579 — def load_reserves_from_arh_letter_text(self, arh_letter_text: str, arh_ref: str = "") -> List[Dict[str, Any]]
- _infer_reserve_type · method · L583-L610 — def _infer_reserve_type(self, finding: Dict[str, Any]) -> str
- _build_reserve_finding · method · L614-L663 — def _build_reserve_finding( self, reserve: Dict[str, Any], status_code: str, evidence: str, confidence: float, ) -> Dict[str, Any]
