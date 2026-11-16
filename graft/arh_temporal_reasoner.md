# arh_temporal_reasoner.py

- ARHDateExtractor · class · L158-L238 — class ARHDateExtractor
- extract_dates_from_text · method · L161-L178 — def extract_dates_from_text(self, text: str) -> List[date]
- _parse_match · method · L180-L210 — def _parse_match(self, m: re.Match, fmt: str) -> Optional[date]
- _is_plausible_date · method · L212-L218 — def _is_plausible_date(self, d: date) -> bool
- extract_most_recent_date_near_keyword · method · L220-L238 — def extract_most_recent_date_near_keyword( self, text: str, keywords: List[str], window_chars: int = 200 ) -> Optional[date]
- ARHTemporalReasoningAgent · class · L245-L653 — class ARHTemporalReasoningAgent
- __init__ · method · L251-L255 — def __init__(self)
- audit_temporal_validity · method · L257-L296 — def audit_temporal_validity( self, docs: List[Dict[str, Any]], equipment_type: str, dossier_stage: str ) -> List[Dict[str, Any]]
- _check_welder_qualifications · method · L302-L418 — def _check_welder_qualifications(self, text: str, fname: str) -> List[Dict[str, Any]]
- _check_atex_certificates · method · L424-L485 — def _check_atex_certificates(self, text: str, fname: str) -> List[Dict[str, Any]]
- _check_consular_visa · method · L491-L538 — def _check_consular_visa(self, text: str, fname: str) -> List[Dict[str, Any]]
- _check_calibration_certs · method · L544-L609 — def _check_calibration_certs(self, text: str, fname: str) -> List[Dict[str, Any]]
- _build_finding · method · L615-L653 — def _build_finding( self, rule_key: str, fname: str, priority: str, title: str, observation: str, action_required: str, days_elapsed: Optional[int], expiry_date: Optional[date], ) -> Dict[str, Any]
- check_date_validity · function · L660-L705 — def check_date_validity( date_str: str, rule_key: str, today: Optional[date] = None ) -> Dict[str, Any]
