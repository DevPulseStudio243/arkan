# ie_mto_validator.py

- _cfg · function · L30-L38 — def _cfg(config: Optional[Dict[str, Any]]) -> Dict[str, Any]
- get_next_standard_section · function · L41-L45 — def get_next_standard_section(sec: float, sections: Optional[List[float]] = None) -> Optional[float]
- calculate_iec_pe_section · function · L48-L57 — def calculate_iec_pe_section(phase_section: float, rules: Optional[Dict[str, Any]] = None) -> Optional[float]
- _anomaly · function · L60-L64 — def _anomaly(rule, severity, tag, title, message, norm, reco, status="PROPOSED", **extra)
- _fmt · function · L67-L68 — def _fmt(x: float) -> str
- check_tray_filling · function · L71-L109 — def check_tray_filling(items: List[Dict[str, Any]], rules: Dict[str, Any]) -> List[Dict[str, Any]]
- validate_ie_mto · function · L112-L202 — def validate_ie_mto(items: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None, config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]
