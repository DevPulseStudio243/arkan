# neural_reranker.py

- NeuralReranker · class · L14-L117 — class NeuralReranker
- __init__ · method · L15-L20 — def __init__(self, model_name: str = RERANK_MODEL)
- _ensure_initialized · method · L22-L36 — def _ensure_initialized(self)
- warmup · method · L38-L47 — def warmup(self)
- _get_cache_key · method · L49-L51 — def _get_cache_key(self, query: str, content: str) -> str
- rerank · method · L53-L117 — def rerank(self, query: str, results: List[Any], top_k: int = 5) -> List[Any]
- get_reranker · function · L122-L126 — def get_reranker() -> NeuralReranker
