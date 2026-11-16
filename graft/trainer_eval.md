# trainer_eval.py

- SystemEvaluator · class · L35-L581 — class SystemEvaluator
- __init__ · method · L37-L42 — def __init__(self, base_dir: Path, models_dir: Path, data_dir: Path, console: Console)
- _reciprocal_rank · method · L46-L50 — def _reciprocal_rank(self, relevant_ids: set, ranked_ids: list) -> float
- _average_precision · method · L52-L68 — def _average_precision(self, relevant_ids: set, ranked_ids: list, k: int = 10) -> float
- _precision_at_k · method · L70-L71 — def _precision_at_k(self, relevant_ids: set, ranked_ids: list, k: int) -> float
- eval_retrieval · method · L75-L163 — def eval_retrieval(self) -> dict
- eval_grounding · method · L167-L196 — def eval_grounding(self) -> dict
- eval_classifier · method · L200-L260 — def eval_classifier(self) -> dict
- eval_latency · method · L264-L316 — def eval_latency(self) -> dict
- eval_reranker · method · L320-L399 — def eval_reranker(self) -> dict
- _make_candidate · function · L346-L356 — def _make_candidate(doc_id: str, text: str) -> SimpleNamespace
- run · method · L405-L581 — def run(self)
