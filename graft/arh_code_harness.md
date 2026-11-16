# arh_code_harness.py

- lookup_material_properties · function · L78-L128 — def lookup_material_properties(raw_material_str: str) -> Optional[Dict[str, Any]]
- _validate_sandbox_ast · function · L142-L157 — def _validate_sandbox_ast(code: str) -> Optional[str]
- _sandbox_worker · function · L160-L173 — def _sandbox_worker(code: str, input_data: Dict[str, Any], queue) -> None
- ARHCodeExecutionHarness · class · L177-L398 — class ARHCodeExecutionHarness
- verify_decret_21_261_art08 · method · L184-L239 — def verify_decret_21_261_art08( cls, declared_s_mpa: float, material_name: str, rm_mpa: Optional[float] = None, re_mpa: Optional[float] = None ) -> Dict[str, Any]
- verify_hydrotest_pressure · method · L242-L290 — def verify_hydrotest_pressure( cls, pma_bar: float, p_hydro_declared_bar: float, temperature_ambient_c: float = 20.0, stress_ratio_test_over_design: float = 1.0 ) -> Dict[str, Any]
- calculate_minimum_wall_thickness_asme · method · L293-L354 — def calculate_minimum_wall_thickness_asme( cls, p_design_bar: float, inside_diameter_mm: float, s_allowable_mpa: float, weld_efficiency_e: float = 1.0, corrosion_allowance_mm: float = 3.0 ) -> Dict[str, Any]
- execute_sandboxed_code · method · L357-L398 — def execute_sandboxed_code( cls, python_code: str, input_data: Optional[Dict[str, Any]] = None, timeout_sec: float = 1.0 ) -> Dict[str, Any]
- _elapsed · function · L374-L375 — def _elapsed() -> float
