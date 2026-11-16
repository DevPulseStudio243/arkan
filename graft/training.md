# training.py

- ContinuousTrainer · class · L18-L246 — class ContinuousTrainer
- __init__ · method · L27-L28 — def __init__(self)
- _load_state · method · L30-L45 — def _load_state(self) -> dict
- _save_state · method · L47-L51 — def _save_state(self)
- incremental_update · method · L53-L112 — def incremental_update(self, query: str = None, answer: str = None, sources: list[str] = None, rating: str = "auto", confidence: float = 0.5, new_feedback: list = None, new_documents: list = None)
- _process_single_feedback · method · L114-L133 — def _process_single_feedback(self, engine, query: str, answer: str, sources: list[str], rating: str, confidence: float): # Convert "auto" rating to concrete rating based on confidence
- run_full_cycle · method · L135-L197 — def run_full_cycle(self, rebuild_bm25: bool = True, rebuild_vocab: bool = True, prune_graph: bool = True)
- _rebuild_vocabulary · method · L199-L231 — def _rebuild_vocabulary(self)
- get_status · method · L233-L246 — def get_status(self) -> dict
- get_trainer · function · L253-L259 — def get_trainer() -> ContinuousTrainer
