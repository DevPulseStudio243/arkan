# plan_item_grounder.py

- PlanItemSemanticGrounder · class · L24-L353 — class PlanItemSemanticGrounder
- __init__ · method · L35-L37 — def __init__(self)
- _load_model · method · L39-L46 — def _load_model(self)
- ground_item · method · L48-L122 — def ground_item(self, tag: str, discipline_hint: Optional[str] = None, context_text: str = "") -> Dict[str, Any]
- _lookup_db · method · L124-L171 — def _lookup_db(self, tag: str, discipline: str, subcategory: str = "") -> Dict[str, Any]
- _deduce_engineering_specs · method · L173-L250 — def _deduce_engineering_specs(self, tag: str, subcategory: str, discipline: str) -> Dict[str, Any]
- _get_specialist_advice · method · L252-L353 — def _get_specialist_advice(self, specialist: str, tag: str, subcat: str) -> Dict[str, Any]
