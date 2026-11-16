# reranker.py

- _init_cross_encoder · function · L16-L32 — def _init_cross_encoder()
- _ensure_cross_encoder · function · L37-L41 — def _ensure_cross_encoder()
- get_neural_reranker · function · L49-L59 — def get_neural_reranker()
- neural_rerank · function · L61-L76 — def neural_rerank(query: str, results: list, top_n: int = 8) -> list
- semantic_rerank · function · L79-L100 — def semantic_rerank(query: str, results: list, top_k: Optional[int] = None) -> list
- _cross_encoder_rerank · function · L103-L126 — def _cross_encoder_rerank(query: str, results: list, top_k: Optional[int] = None) -> list
- _lexical_rerank · function · L129-L161 — def _lexical_rerank(query: str, results: list, top_k: Optional[int] = None) -> list
- _entity_match_score · function · L164-L179 — def _entity_match_score(query: str, content: str) -> float
- _tokenize · function · L182-L188 — def _tokenize(text: str) -> list[str]
- cross_rerank · function · L191-L193 — def cross_rerank(query: str, results: list, top_k: Optional[int] = None) -> list
