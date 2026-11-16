# obsidian_vault_engine.py

- ensure_vault_directories · function · L55-L81 — def ensure_vault_directories()
- sanitize_filename · function · L84-L90 — def sanitize_filename(name: str) -> str
- sync_standards_to_vault · function · L149-L179 — def sync_standards_to_vault()
- get_procurement_data_from_sqlite · function · L186-L210 — def get_procurement_data_from_sqlite() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]
- sync_projects_and_contracts_to_vault · function · L213-L404 — def sync_projects_and_contracts_to_vault() -> Dict[str, int]
- sync_arh_dossiers_to_vault · function · L411-L476 — def sync_arh_dossiers_to_vault() -> int
- sync_agent_memory_to_vault · function · L483-L507 — def sync_agent_memory_to_vault()
- generate_master_moc · function · L514-L561 — def generate_master_moc()
- build_vault_knowledge_graph · function · L579-L682 — def build_vault_knowledge_graph() -> Dict[str, Any]
- sync_full_vault · function · L689-L713 — def sync_full_vault() -> Dict[str, Any]
- read_note_content · function · L716-L760 — def read_note_content(relative_path: str) -> Dict[str, Any]
- append_agent_memory · function · L763-L794 — def append_agent_memory(title: str, content: str, tags: Optional[List[str]] = None, links: Optional[List[str]] = None) -> Dict[str, Any]
- open_vault_locally · function · L797-L809 — def open_vault_locally() -> Dict[str, Any]
