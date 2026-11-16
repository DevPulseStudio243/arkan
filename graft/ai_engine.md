# ai_engine.py

- AIEngine · class · L18-L171 — class AIEngine
- __init__ · method · L19-L36 — def __init__(self)
- close · method · L38-L40 — def close(self)
- ask_question · method · L42-L72 — def ask_question(self, question: str, project: DTIMProject) -> Dict[str, Any]
- _translate_to_cypher · method · L74-L107 — def _translate_to_cypher(self, question: str, project_name: str) -> tuple
- _format_cypher_result_to_answer · method · L109-L125 — def _format_cypher_result_to_answer(self, question: str, records: List[Dict[str, Any]]) -> str
- _ask_local_dtim · method · L127-L171 — def _ask_local_dtim(self, question: str, project: DTIMProject) -> Dict[str, Any]
