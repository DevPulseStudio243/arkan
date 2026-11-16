# entities.py

- _get_equipment_description · function · L49-L56 — def _get_equipment_description(tag: str) -> str
- _is_from_excluded_source · function · L81-L88 — def _is_from_excluded_source(filename: str) -> bool
- extract_entities · function · L144-L164 — def extract_entities(text: str) -> dict
- extract_equipment_tags · function · L167-L175 — def extract_equipment_tags(text: str) -> list
- load_kb · function · L180-L193 — def load_kb() -> list
- save_to_kb · function · L196-L257 — def save_to_kb(entities: dict, source_file: str, context_snippet: str = "")
- _detect_query_intent · function · L335-L349 — def _detect_query_intent(query: str) -> list
- build_kb_context · function · L352-L475 — def build_kb_context(query: str) -> str
