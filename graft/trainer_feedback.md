# trainer_feedback.py

- FeedbackLearner · class · L33-L478 — class FeedbackLearner
- __init__ · method · L35-L44 — def __init__(self, base_dir: Path, models_dir: Path, console: Console)
- _load_feedback · method · L46-L54 — def _load_feedback(self) -> list
- compute_source_weights · method · L58-L98 — def compute_source_weights(self, records: list) -> dict
- analyze_failure_patterns · method · L102-L140 — def analyze_failure_patterns(self, records: list) -> dict
- update_vocabulary · method · L144-L184 — def update_vocabulary(self, records: list) -> int
- generate_training_data · method · L188-L268 — def generate_training_data(self, records: list) -> dict
- update_knowledge_graph · method · L272-L314 — def update_knowledge_graph(self, records: list) -> int
- run · method · L318-L467 — def run(self)
- _patch_retriever_for_weights · method · L469-L478 — def _patch_retriever_for_weights(self)
