# arh_material_certificate_analyzer.py

- ARHMaterialCertificateAnalyzer · class · L133-L545 — class ARHMaterialCertificateAnalyzer
- __init__ · method · L138-L139 — def __init__(self)
- analyze_certificate_text · method · L141-L207 — def analyze_certificate_text( self, text: str, filename: str = "", page_num: int = 1, expected_grade: str = None ) -> Dict[str, Any]
- _detect_grade · method · L209-L216 — def _detect_grade(self, text: str, fallback: str = None) -> str
- _extract_heat_number · method · L218-L231 — def _extract_heat_number(self, text: str) -> Optional[str]: # Regex sécurisée sans faux positifs
- _extract_chemical_elements · method · L233-L342 — def _extract_chemical_elements(self, text: str) -> Dict[str, float]
- _extract_declared_cev · method · L345-L359 — def _extract_declared_cev(self, text: str) -> Optional[float]
- _extract_mechanical_properties · method · L361-L423 — def _extract_mechanical_properties(self, text: str) -> Dict[str, Any]
- _extract_heat_treatment · method · L427-L437 — def _extract_heat_treatment(self, text: str) -> Optional[str]
- _audit_material_compliance · method · L439-L545 — def _audit_material_compliance(self, res: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]
