# arh_assertion_guards.py

- _squash · function · L31-L33 — def _squash(text: str) -> str
- ARHAssertionGuard · class · L36-L239 — class ARHAssertionGuard
- _is_completeness_finding · method · L71-L77 — def _is_completeness_finding(cls, text: str) -> bool
- assert_provenance · method · L80-L92 — def assert_provenance(cls, finding: Dict[str, Any]) -> Tuple[bool, str]
- _to_float · method · L96-L97 — def _to_float(tok: str) -> float
- _violations · method · L100-L138 — def _violations(cls, text: str) -> List[Tuple[str, str]]
- assert_physical_bounds · method · L141-L156 — def assert_physical_bounds(cls, finding: Dict[str, Any], full_context_text: str = "") -> Tuple[bool, str]
- assert_equipment_exclusivity · method · L160-L196 — def assert_equipment_exclusivity(cls, finding: Dict[str, Any], equipment_type: str, full_context_text: str = "") -> Tuple[bool, str]
- assert_revision_status · method · L200-L208 — def assert_revision_status(cls, finding: Dict[str, Any], is_resolved_revision: bool) -> Tuple[bool, str]
- validate_and_sanitize_findings · method · L212-L239 — def validate_and_sanitize_findings( cls, findings: List[Dict[str, Any]], equipment_type: str = "", full_context_text: str = "", is_resolved_revision: bool = False, rejected_out: Optional[List[Dict[str, Any]]] = None, ) -> List[Dict[str, Any]]
