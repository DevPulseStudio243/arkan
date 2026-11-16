# arh_agent_network_manager.py

- get_all_dynamic_agent_profiles · function · L111-L142 — def get_all_dynamic_agent_profiles() -> Dict[str, Dict[str, Any]]
- ARHAgentNetworkManager · class · L148-L301 — class ARHAgentNetworkManager
- __init__ · method · L154-L157 — def __init__(self, db_path: Path = DB_PATH, dossiers_db_path: Path = Path("arh_dossiers.db"))
- _init_network_tables · method · L159-L184 — def _init_network_tables(self)
- get_topology · method · L186-L211 — def get_topology(self) -> Dict[str, Any]
- sync_on_dossier_added · method · L213-L241 — def sync_on_dossier_added(self, dossier_data: Dict[str, Any])
- sync_on_dossier_deleted · method · L243-L252 — def sync_on_dossier_deleted(self, dossier_id: str) -> Dict[str, Any]
- sync_on_reserve_resolved · method · L254-L264 — def sync_on_reserve_resolved(self, dossier_id: str, reserve_id: str, justification: str = "") -> Dict[str, Any]
- sync_on_reserve_reopened · method · L266-L276 — def sync_on_reserve_reopened(self, dossier_id: str, reserve_id: str) -> Dict[str, Any]
- sync_all_from_dossiers_db · method · L278-L292 — def sync_all_from_dossiers_db(self) -> Dict[str, Any]
- get_project_live_vision · method · L294-L301 — def get_project_live_vision(self, project_name: str) -> Dict[str, Any]
- get_agent_network_manager · function · L307-L311 — def get_agent_network_manager() -> ARHAgentNetworkManager
