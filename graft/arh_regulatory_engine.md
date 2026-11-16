# arh_regulatory_engine.py

- ARHRegulatoryEngine · class · L947-L1659 — class ARHRegulatoryEngine
- _detect_via_llm · method · L957-L996 — def _detect_via_llm(text_sample: str) -> str
- identify_equipment_type · method · L999-L1163 — def identify_equipment_type(text_content: str, metadata: Dict[str, Any] = None) -> str
- get_applicable_decrees · method · L1166-L1185 — def get_applicable_decrees(equipment_type: str) -> List[Dict[str, str]]
- has_electrical_scope · method · L1188-L1230 — def has_electrical_scope(equipment_type: str, text: str = "") -> bool
- detect_dossier_stage · method · L1233-L1308 — def detect_dossier_stage(text_content: str, filenames: List[str] = None) -> str
- _norm_s · function · L1248-L1249 — def _norm_s(s: str) -> str
- generate_mandatory_checklist · method · L1311-L1408 — def generate_mandatory_checklist(equipment_type: str, dossier_stage: str = "FINAL_RECEPTION") -> List[Dict[str, Any]]
- verify_ndt_extent · method · L1411-L1427 — def verify_ndt_extent(zone: str, actual_percent: float, fluid_type: str = "LIQUID") -> Tuple[bool, float, str]
- verify_hydrotest_pressure · method · L1430-L1464 — def verify_hydrotest_pressure( pma_bar: float, pms_bar: float, actual_test_bar: float, equipment_type: str, zone: str = "ZONE A", max_test_bar: Optional[float] = None ) -> Tuple[bool, float, str]
- calculate_min_pipe_thickness · method · L1467-L1481 — def calculate_min_pipe_thickness( p_bar: float, d_mm: float, r_t05_bar: float, f_factor: float, z_coef: float = 1.0 ) -> float
- calculate_asme_required_wall_thickness · method · L1484-L1542 — def calculate_asme_required_wall_thickness( p_bar: float, d_mm: float, grade_astm: str = "A105", corrosion_allowance_mm: float = 3.0, joint_efficiency: float = 1.0, y_coefficient: float = 0.4 ) -> Dict[str, Any]
- verify_norm_applicability · method · L1618-L1650 — def verify_norm_applicability(equipment_type: str, text_content: str) -> List[Dict[str, Any]]
- match_historical_arh_reserves · method · L1653-L1659 — def match_historical_arh_reserves(equipment_type: str, text_content: str) -> List[Dict[str, Any]]
