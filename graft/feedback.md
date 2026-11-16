# feedback.py

- _load_db · function · L24-L36 — def _load_db()
- _save_db · function · L39-L45 — def _save_db(records)
- _tokenize · function · L50-L54 — def _tokenize(text)
- _token_overlap · function · L57-L65 — def _token_overlap(text_a, text_b)
- save_feedback · function · L70-L107 — def save_feedback(question, answer, sources=None, rating="pending", metadata=None)
- get_similar_questions · function · L110-L126 — def get_similar_questions(question, threshold=0.5, max_results=5)
- get_best_answer · function · L129-L161 — def get_best_answer(question, threshold=0.85, max_age_days=30)
- get_retrieval_stats · function · L165-L211 — def get_retrieval_stats()
- learn_from_feedback · function · L214-L270 — def learn_from_feedback()
