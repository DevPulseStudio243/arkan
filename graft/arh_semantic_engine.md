# arh_semantic_engine.py

- OllamaSemanticExtractor · class · L34-L300 — class OllamaSemanticExtractor
- is_available · method · L38-L44 — def is_available(cls) -> bool
- build_system_prompt · method · L47-L74 — def build_system_prompt(cls) -> str
- _normalize_dict · method · L77-L263 — def _normalize_dict(cls, raw: Dict, doc_text: str = "") -> Dict[str, Any]
- _safe_float · function · L81-L88 — def _safe_float(val: Any, key_name: str = "") -> Optional[float]
- extract · method · L266-L300 — def extract(cls, doc_text: str) -> Optional[Dict[str, Any]]
- ARHNormativeValidator · class · L307-L556 — class ARHNormativeValidator
- validate_hydrotest · method · L311-L366 — def validate_hydrotest(pma: float, p_ep: Optional[float], ratio: float, codes: List[str], spec_name: str, slug: str, doc: str, page_num: int = 1, proof_text: str = "") -> Optional[Dict]
- validate_metallurgy_cev · method · L369-L413 — def validate_metallurgy_cev(c: Optional[float], mn: Optional[float], cr: Optional[float], mo: Optional[float], v: Optional[float], ni: Optional[float], cu: Optional[float], nace_required: bool, spec_name: str, slug: str, doc: str, page_num: int = 1, proof_text: str = "") -> Optional[Dict]
- validate_charpy_impact · method · L416-L448 — def validate_charpy_impact(energy_j: Optional[float], temp_c: Optional[float], spec_name: str, slug: str, doc: str, page_num: int = 1, proof_text: str = "") -> Optional[Dict]
- validate_thickness_asme · method · L451-L500 — def validate_thickness_asme(ep: Optional[float], diam: Optional[float], pma: Optional[float], joint_e: Optional[float], c_corr: float, codes: List[str], spec_name: str, slug: str, doc: str, page_num: int = 1, proof_text: str = "") -> Optional[Dict]
- validate_cert31 · method · L503-L530 — def validate_cert31(cert_present: Optional[bool], spec_name: str, slug: str, eq_type: str, doc: str, page_num: int = 1, proof_text: str = "") -> Optional[Dict]
- validate_itp · method · L533-L556 — def validate_itp(itp_present: Optional[bool], hold_points: Optional[bool], spec_name: str, slug: str, doc: str, page_num: int = 1, proof_text: str = "") -> Optional[Dict]
- semantic_audit · function · L563-L712 — def semantic_audit( docs_text: str, equipment_type: str, equipment_tag: str, spec_name: str, spec_slug: str, codes: List[str], hydro_ratio: float, file_names: Optional[List[str]] = None ) -> Tuple[List[Dict], Dict, str]
