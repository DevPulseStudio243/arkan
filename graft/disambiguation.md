# disambiguation.py

- DisambiguationEngine · class · L14-L119 — class DisambiguationEngine
- resolve · method · L23-L57 — def resolve(self, question: str, context_docs: List[Any] = None) -> Dict[str, Any]
- _find_similar_tags · method · L59-L82 — def _find_similar_tags(self, tags: List[str]) -> Dict[str, List[str]]
- _resolve_by_context · method · L84-L119 — def _resolve_by_context( self, question: str, similar_groups: Dict[str, List[str]], docs: List[Any] ) -> Tuple[List[str], str]
- get_disambiguation_engine · function · L125-L129 — def get_disambiguation_engine() -> DisambiguationEngine
