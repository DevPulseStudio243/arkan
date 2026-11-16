# causal_memory.py

- Incident · class · L100-L118 — class Incident
- to_text · method · L111-L118 — def to_text(self) -> str
- CausalMemory · class · L121-L217 — class CausalMemory
- __init__ · method · L127-L130 — def __init__(self, db_path: Path = DB_PATH)
- _init_db · method · L132-L146 — def _init_db(self)
- _tokenize · method · L148-L153 — def _tokenize(self, text: str) -> set
- _jaccard · method · L155-L158 — def _jaccard(self, a: set, b: set) -> float
- find_similar_incidents · method · L160-L180 — def find_similar_incidents(self, query: str, top_k: int = 3) -> list[Incident]
- build_causal_context · method · L182-L194 — def build_causal_context(self, query: str, top_k: int = 3) -> str
- store_incident · method · L196-L206 — def store_incident(self, situation: str, symptomes: str, causes: str, resolution: str, severite: str = "MOYEN", duree_h: float = 0.0, equipement: str = "") -> int
- get_all_incidents · method · L208-L214 — def get_all_incidents(self) -> list[Incident]
- close · method · L216-L217 — def close(self)
- get_causal_memory · function · L222-L226 — def get_causal_memory() -> CausalMemory
