# agent_memory.py

- AgentMemory · class · L25-L182 — class AgentMemory
- __init__ · method · L28-L65 — def __init__(self, persist_dir: str = CHROMA_PERSIST_DIR)
- _hash_query · method · L67-L68 — def _hash_query(self, query: str) -> str
- save_experience · method · L70-L109 — def save_experience(self, query: str, final_answer: str, steps: list, model_used: str)
- save_human_correction · method · L111-L132 — def save_human_correction(self, query: str, correct_answer: str, context: str = "")
- recall_experience · method · L134-L175 — def recall_experience(self, query: str) -> Optional[Dict[str, Any]]
- get_stats · method · L177-L182 — def get_stats(self) -> Dict[str, Any]
- get_agent_memory · function · L188-L192 — def get_agent_memory() -> AgentMemory
