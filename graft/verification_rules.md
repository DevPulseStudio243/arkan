# verification_rules.py

- normalize_value · function · L18-L43 — def normalize_value(val_str: str, unit: str) -> tuple[float, str]
- is_value_different · function · L46-L66 — def is_value_different(val_a: str, unit_a: str, val_b: str, unit_b: str, tolerance: float = 0.05) -> bool
- check_exception_suppression · function · L69-L97 — def check_exception_suppression(tag: str, rule_id: str, value_a: str, value_b: str, exceptions: list[dict]) -> bool
- get_project_dir_path · function · L100-L113 — def get_project_dir_path(project_id: str) -> Path
- load_project_specs · function · L116-L148 — def load_project_specs(project_id: str) -> dict
- load_project_documents_text · function · L151-L186 — def load_project_documents_text(project_dir: Path) -> dict[str, str]
- run_semantic_llm_verification · function · L189-L304 — def run_semantic_llm_verification(project_id: str, exceptions: list[dict]) -> list[dict]
- run_wiring_verification · function · L305-L515 — def run_wiring_verification(project_id: str, exceptions: list[dict]) -> list[dict]
- add_link · function · L332-L334 — def add_link(node_a, node_b, cable_tag, wire_label)
- find_paths_dfs · function · L344-L356 — def find_paths_dfs(start, end_prefix, visited, current_path)
- get_color_family · function · L425-L430 — def get_color_family(w)
- check_pressure_propagation · function · L518-L611 — def check_pressure_propagation(project_id: str, tag_attrs: dict, connections: list, exceptions: list) -> list
- run_verification_pipeline · function · L614-L1516 — def run_verification_pipeline(project_id: str) -> list[dict]
- has_path · function · L1308-L1318 — def has_path(graph, start, end, visited=None)
- run_handbook_rag_verification · function · L1519-L1584 — def run_handbook_rag_verification(project_id: str, exceptions: list[dict]) -> list[dict]
- run_planning_delays_verification · function · L1587-L1718 — def run_planning_delays_verification(project_id: str, exceptions: list[dict]) -> list[dict]
