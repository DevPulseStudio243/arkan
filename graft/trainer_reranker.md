# trainer_reranker.py

- ReplayBuffer · class · L35-L71 — class ReplayBuffer
- __init__ · method · L41-L43 — def __init__(self, max_size: int = 1000)
- add · method · L45-L55 — def add(self, item: dict)
- sample · method · L57-L64 — def sample(self, sample_size: int = None) -> list
- get_stats · method · L66-L71 — def get_stats(self) -> dict
- RerankerTrainer · class · L74-L452 — class RerankerTrainer
- __init__ · method · L78-L84 — def __init__(self, data_dir: Path, models_dir: Path, checkpoints_dir: Path, console: Console)
- _load_training_data · method · L86-L102 — def _load_training_data(self) -> tuple
- _check_distillation_data · method · L104-L119 — def _check_distillation_data(self) -> list
- _augment_with_feedback · method · L121-L169 — def _augment_with_feedback(self, train_data: list, feedback_records: list, distill_records: list = None) -> list
- run · method · L171-L366 — def run(self)
- _patch_reranker_py · method · L368-L452 — def _patch_reranker_py(self)
