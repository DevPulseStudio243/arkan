# arh_benchmark_evaluator.py

- ARHBenchmarkEvaluator · class · L25-L418 — class ARHBenchmarkEvaluator
- __init__ · method · L26-L27 — def __init__(self, desktop_arh_path: Optional[str] = None)
- extract_human_expert_comments · method · L29-L151 — def extract_human_expert_comments(self, pdf_path: str, incoming_pdf_path: Optional[str] = None) -> List[Dict[str, Any]]
- is_reviewer_stamp · function · L76-L87 — def is_reviewer_stamp(text: str) -> bool
- find_all_equipment_folders · method · L153-L178 — def find_all_equipment_folders(self) -> List[Dict[str, Any]]
- evaluate_dossier · method · L180-L418 — def evaluate_dossier(self, incoming_pdf: str, outgoing_pdf: str) -> Dict[str, Any]
