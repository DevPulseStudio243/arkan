# arh_dataset_trainer.py

- ARHDatasetTrainer · class · L24-L182 — class ARHDatasetTrainer
- __init__ · method · L25-L28 — def __init__(self, dataset_root: Path = DATASET_ROOT)
- discover_dataset_pairs · method · L30-L85 — def discover_dataset_pairs(self) -> List[Dict[str, Any]]
- extract_ground_truth_remarks · method · L87-L141 — def extract_ground_truth_remarks(self, outgoing_files: List[str], followup_excels: List[str]) -> List[str]
- benchmark_pair · method · L143-L182 — def benchmark_pair(self, pair: Dict[str, Any]) -> Dict[str, Any]
