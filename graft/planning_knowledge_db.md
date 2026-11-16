# planning_knowledge_db.py

- PlanningKnowledgeDB · class · L1594-L1819 — class PlanningKnowledgeDB
- __init__ · method · L1597-L1599 — def __init__(self, db_path: str = DB_PATH)
- _get_connection · method · L1601-L1606 — def _get_connection(self) -> sqlite3.Connection
- _init_db · method · L1608-L1623 — def _init_db(self)
- seed_initial_knowledge · method · L1625-L1676 — def seed_initial_knowledge(self) -> int
- get_task_count · method · L1678-L1683 — def get_task_count(self) -> int
- get_coverage_report · method · L1685-L1706 — def get_coverage_report(self) -> Dict[str, Any]
- search_tasks_by_discipline · method · L1708-L1741 — def search_tasks_by_discipline(self, discipline: str) -> List[Dict[str, Any]]
- get_all_tasks_for_rag · method · L1743-L1772 — def get_all_tasks_for_rag(self) -> List[Dict[str, Any]]
- record_learning_feedback · method · L1774-L1786 — def record_learning_feedback(self, tache_id: Optional[int], nom_tache: str, rendement_estime: float, rendement_reel: float, projet_id: str = "", commentaire: str = "") -> bool
- recalibrate_yields_batch · method · L1788-L1819 — def recalibrate_yields_batch(self) -> int
