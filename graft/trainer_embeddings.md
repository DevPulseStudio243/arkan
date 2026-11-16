# trainer_embeddings.py

- EmbeddingTrainer · class · L26-L293 — class EmbeddingTrainer: # Modèle plus léger et compatible CPU/GPU entry-level
- __init__ · method · L32-L38 — def __init__(self, data_dir: Path, models_dir: Path, checkpoints_dir: Path, console: Console)
- _load_data · method · L40-L53 — def _load_data(self) -> tuple
- _augment_with_feedback · method · L55-L96 — def _augment_with_feedback(self, train_data: list) -> list
- run · method · L98-L246 — def run(self)
- _propose_config_patch · method · L248-L293 — def _propose_config_patch(self)
