# query_planner.py

- QueryType · class · L14-L24 — class QueryType(Enum)
- SubQuery · class · L28-L34 — class SubQuery
- RetrievalPlan · class · L38-L47 — class RetrievalPlan
- classify_query · function · L113-L136 — def classify_query(query: str) -> QueryType
- detect_disciplines · function · L139-L150 — def detect_disciplines(query: str) -> list[str]
- extract_equipment_tags · function · L153-L178 — def extract_equipment_tags(query: str) -> list[str]
- decompose_query · function · L181-L229 — def decompose_query(query: str) -> list[SubQuery]
- plan_retrieval · function · L232-L284 — def plan_retrieval(query: str) -> RetrievalPlan
