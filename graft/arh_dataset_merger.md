# arh_dataset_merger.py

- load_jsonl · function · L45-L60 — def load_jsonl(path: Path) -> List[Dict[str, Any]]
- load_quality_comments · function · L63-L144 — def load_quality_comments(path: Path) -> List[Dict[str, Any]]
- validate_example · function · L151-L177 — def validate_example(ex: Dict[str, Any]) -> bool
- sanitize_example · function · L180-L197 — def sanitize_example(ex: Dict[str, Any]) -> Dict[str, Any]
- balance_dataset · function · L204-L230 — def balance_dataset(examples: List[Dict[str, Any]], max_per_part: int = 3000) -> List[Dict[str, Any]]
- merge_all · function · L237-L333 — def merge_all() -> Dict[str, Any]
