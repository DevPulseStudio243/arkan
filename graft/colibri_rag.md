# colibri_rag.py

- ColibriFastRAG · class · L19-L169 — class ColibriFastRAG
- __init__ · method · L20-L26 — def __init__(self, data_dir: str = "d:/DATA BASE IA/data")
- _tokenize · method · L28-L31 — def _tokenize(self, text: str) -> List[str]
- build_index · method · L33-L99 — def build_index(self)
- _chunk_text · method · L101-L120 — def _chunk_text(self, text: str, source: str, chunk_size: int = 600) -> List[str]
- search · method · L122-L169 — def search(self, query: str, top_k: int = 5) -> Dict[str, Any]
- get_colibri_engine · function · L175-L179 — def get_colibri_engine()
