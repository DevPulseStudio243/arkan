# boq_planner.py

- get_best_planning_model · function · L19-L51 — async def get_best_planning_model() -> str
- add_days_with_calendar · function · L60-L87 — def add_days_with_calendar(start_date: datetime, duration_days: float, calendar_type: str) -> datetime
- calculate_logic_dates · function · L89-L183 — def calculate_logic_dates( project_start_str: str, tasks: List[Dict[str, Any]], predecessors: List[Dict[str, Any]], calendar_type: str, safety_coef: float = 1.10 ) -> List[Dict[str, Any]]
- generate_xer_string · function · L185-L295 — def generate_xer_string( project_id: str, project_name: str, wbs: List[Dict[str, Any]], tasks: List[Dict[str, Any]], predecessors: List[Dict[str, Any]], calendar_type: str ) -> str
- generate_xer_from_boq · function · L297-L451 — async def generate_xer_from_boq( project_id: str, project_name: str, start_date: str, calendar_type: str, safety_coef: float, bpu_content: str, rag_context: str = "" ) -> Dict[str, Any]
