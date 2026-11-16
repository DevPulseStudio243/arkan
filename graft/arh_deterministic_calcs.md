# arh_deterministic_calcs.py

- ug27_cylindrical_shell · function · L19-L43 — def ug27_cylindrical_shell(p_mpa: float, inside_radius_mm: float, s_allowable_mpa: float, joint_efficiency: float = 1.0, corrosion_allowance_mm: float = 0.0) -> Dict[str, Any]
- ug99_hydrotest_minimum · function · L46-L52 — def ug99_hydrotest_minimum(mawp_bar: float, s_test_mpa: float, s_design_mpa: float) -> Dict[str, Any]
- decree_hydrotest_minimum · function · L55-L64 — def decree_hydrotest_minimum(pma_bar: float, kind: str = "ESP", zone: str = "A") -> Dict[str, Any]
- governing_hydrotest_minimum · function · L67-L74 — def governing_hydrotest_minimum(pma_bar: float, s_test_mpa: float, s_design_mpa: float, kind: str = "ESP", zone: str = "A") -> Dict[str, Any]
- barlow_pipe_thickness · function · L77-L86 — def barlow_pipe_thickness(p_mpa: float, outside_diameter_mm: float, rt05_mpa: float, design_factor_f: float, z_coef: float = 1.0) -> Dict[str, Any]
- carbon_equivalent · function · L89-L95 — def carbon_equivalent(c: float, mn: float, cr: float = 0.0, mo: float = 0.0, v: float = 0.0, ni: float = 0.0, cu: float = 0.0, si: Optional[float] = None, b: float = 0.0) -> Dict[str, float]
