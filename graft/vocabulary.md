# vocabulary.py

- _load_vocabulary · function · L88-L106 — def _load_vocabulary() -> dict
- _load_learned_vocabulary · function · L109-L125 — def _load_learned_vocabulary() -> dict
- expand_query · function · L128-L204 — def expand_query(query: str) -> str
- build_vocabulary · function · L207-L258 — def build_vocabulary(documents: list[str], min_df: int = 2) -> dict
- get_term_frequency · function · L261-L287 — def get_term_frequency(term: str = "", top_n: int = 0) -> float | list
- invalidate_cache · function · L290-L295 — def invalidate_cache()
- _tokenize_for_vocab · function · L298-L307 — def _tokenize_for_vocab(text: str) -> list[str]
- _is_domain_term · function · L310-L318 — def _is_domain_term(term: str) -> bool
- learn_synonyms_from_corpus · function · L321-L370 — def learn_synonyms_from_corpus(documents: list[str], min_cooccurrence: int = 3) -> dict
- _compute_idf · function · L373-L377 — def _compute_idf(num_docs: int, doc_freq: int) -> float
