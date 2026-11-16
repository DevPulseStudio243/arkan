# trainer_synthetic.py

- SyntheticDataGenerator · class · L352-L670 — class SyntheticDataGenerator
- __init__ · method · L354-L357 — def __init__(self, data_dir: Path, console: Console)
- _rand_tag · method · L359-L366 — def _rand_tag(self, discipline=None)
- _rand_param · method · L368-L370 — def _rand_param(self, param_type)
- _fill_template · method · L372-L404 — def _fill_template(self, template: str, discipline: str = None) -> str
- generate_reranker_pairs · method · L408-L449 — def generate_reranker_pairs(self, n: int = 800) -> list
- generate_embedding_pairs · method · L453-L499 — def generate_embedding_pairs(self, n: int = 600) -> list
- generate_classifier_samples · method · L503-L520 — def generate_classifier_samples(self, n_per_class: int = 150) -> list
- generate_qa_pairs · method · L524-L574 — def generate_qa_pairs(self, n: int = 300) -> list
- save_jsonl · method · L578-L583 — def save_jsonl(self, data: list, filename: str)
- save_json · method · L585-L589 — def save_json(self, data, filename: str)
- run · method · L593-L670 — def run(self)
