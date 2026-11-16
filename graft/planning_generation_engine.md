# planning_generation_engine.py

- RendementDetail · class · L25-L27 — class RendementDetail(BaseModel)
- EquipeRole · class · L29-L31 — class EquipeRole(BaseModel)
- TachePlanning · class · L33-L58 — class TachePlanning(BaseModel)
- PlanningResponse · class · L60-L67 — class PlanningResponse(BaseModel)
- PlanningGenerationRequest · class · L69-L76 — class PlanningGenerationRequest(BaseModel)
- PlanningValidationRequest · class · L78-L85 — class PlanningValidationRequest(BaseModel)
- PlanningHybridRAG · class · L92-L145 — class PlanningHybridRAG
- __init__ · method · L95-L101 — def __init__(self, db: PlanningKnowledgeDB = planning_db)
- refresh_index · method · L103-L114 — def refresh_index(self)
- _tokenize · method · L116-L117 — def _tokenize(self, text: str) -> List[str]
- search_similar_tasks · method · L119-L145 — def search_similar_tasks(self, query: str, top_k: int = 3, discipline: Optional[str] = None, unite: Optional[str] = None) -> List[Dict[str, Any]]
- PlanningCPMEngine · class · L152-L312 — class PlanningCPMEngine
- calculate_cpm · method · L156-L312 — def calculate_cpm(taches: List[TachePlanning]) -> Tuple[List[TachePlanning], List[str], float, List[str]]
- PlanningGuardrails · class · L333-L399 — class PlanningGuardrails
- audit_and_clamp_yield · method · L337-L365 — def audit_and_clamp_yield(tache_nom: str, quantite: float, rendement_propose: float, unite: str, rag_match: Optional[Dict[str, Any]] = None) -> Tuple[float, float, str, List[str]]
- enforce_universal_precedence · method · L368-L399 — def enforce_universal_precedence(taches: List[TachePlanning]) -> Tuple[List[TachePlanning], List[str]]
