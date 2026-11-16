# arh_auto_trainer_daemon.py

- _init_benchmark_db · function · L30-L60 — def _init_benchmark_db()
- _get_expert_annotations_for_file · function · L62-L78 — def _get_expert_annotations_for_file(filename: str, project: str) -> List[Dict[str, Any]]
- _match_comment_with_expert · function · L80-L108 — def _match_comment_with_expert(detected_comment: Dict[str, Any], expert_annot: Dict[str, Any]) -> bool
- evaluate_and_learn_project · function · L110-L170 — def evaluate_and_learn_project(project_name: str, processor: ARHDocumentProcessor) -> Dict[str, Any]
- run_continuous_training · function · L172-L196 — def run_continuous_training()
