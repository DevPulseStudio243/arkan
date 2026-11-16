# prompts.py

- QueryType · class · L15-L25 — class QueryType(Enum)
- build_prompt · function · L130-L192 — def build_prompt( query: str, context: str, query_type: Optional[QueryType] = None, kb_context: str = "", agent_warnings: str = "", discipline: str = "", history_context: str = "", ) -> dict[str, str]
- build_insufficient_response · function · L195-L220 — def build_insufficient_response(query: str, partial_context: str = "") -> str
