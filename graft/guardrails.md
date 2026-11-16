# guardrails.py

- AnswerGuardrails · class · L20-L310 — class AnswerGuardrails
- __init__ · method · L37-L39 — def __init__(self): # Seuil : 0.5 → on n'affiche l'avertissement que si < 50% des claims sont groundés
- verify_answer · method · L41-L89 — def verify_answer(self, answer: str, context: str, query: str = "") -> dict
- _extract_claims · method · L91-L145 — def _extract_claims(self, answer: str) -> list[dict]
- _is_claim_grounded · method · L147-L252 — def _is_claim_grounded(self, claim: dict, context_lower: str) -> bool
- _sanitize_answer · method · L254-L270 — def _sanitize_answer(self, answer: str, ungrounded: list[dict], context: str) -> str
- check_safety · method · L272-L310 — def check_safety(self, answer: str) -> dict
- get_guardrails · function · L317-L323 — def get_guardrails() -> AnswerGuardrails
- verify_answer · function · L325-L326 — def verify_answer(answer: str, context: str, query: str = "") -> dict
- check_safety · function · L328-L329 — def check_safety(answer: str) -> dict
- extract_claims · function · L332-L334 — def extract_claims(answer: str) -> list[dict]
- verify_grounding · function · L336-L356 — def verify_grounding(claims: list[dict], context: str) -> dict
