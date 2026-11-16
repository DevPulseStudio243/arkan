# arh_dataset_builder.py

- ARHDatasetBuilder · class · L18-L80 — class ARHDatasetBuilder
- __init__ · method · L19-L22 — def __init__(self, output_dir: Optional[Path] = None)
- generate_instruction_sample · method · L24-L44 — def generate_instruction_sample(self, piece_code: str, raw_text: str, expected_contract: Dict[str, Any], decree_ref: str) -> Dict[str, Any]
- build_dataset_from_dossier · method · L46-L80 — def build_dataset_from_dossier(self, dossier_id: str, output_filename: str = "arh_finetune_dataset.jsonl") -> str
