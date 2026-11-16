# arh_dataset_generator_v2.py

- _new_id · function · L170-L171 — def _new_id(prefix: str = "REM") -> str
- _rand_pma · function · L174-L175 — def _rand_pma() -> float
- _rand_temp · function · L178-L179 — def _rand_temp(min_t: int = -46, max_t: int = 350) -> float
- _rand_diameter · function · L182-L185 — def _rand_diameter(unit: str = "in") -> str
- _rand_cev · function · L188-L200 — def _rand_cev() -> tuple
- _make_anomaly · function · L203-L212 — def _make_anomaly(priority: str, category: str, title: str, article: str, action: str, lang: str = "FR") -> Dict[str, Any]
- _make_output · function · L215-L222 — def _make_output(decision: str, score: float, anomalies: List[Dict]) -> str
- gen_part4_annexe_e · function · L227-L349 — def gen_part4_annexe_e(lang: str = "FR") -> Dict[str, Any]
- gen_part5_calcs · function · L354-L440 — def gen_part5_calcs(lang: str = "FR") -> Dict[str, Any]
- gen_part2_consular · function · L445-L547 — def gen_part2_consular(lang: str = "FR") -> Dict[str, Any]
- gen_part8_welding · function · L552-L630 — def gen_part8_welding(lang: str = "FR") -> Dict[str, Any]
- gen_part10_itp · function · L635-L716 — def gen_part10_itp(lang: str = "FR") -> Dict[str, Any]
- gen_cert_material · function · L721-L825 — def gen_cert_material(lang: str = "FR") -> Dict[str, Any]
- gen_part11_atex · function · L830-L908 — def gen_part11_atex(lang: str = "FR") -> Dict[str, Any]
- gen_levee_reserves · function · L913-L972 — def gen_levee_reserves(lang: str = "FR") -> Dict[str, Any]
- generate_all · function · L992-L1013 — def generate_all(output_path: Path = OUTPUT_DIR / "dataset_arh_new_22000.jsonl") -> int
