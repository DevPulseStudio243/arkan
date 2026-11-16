# verification_db.py

- get_db_connection · function · L14-L19 — def get_db_connection()
- init_verification_db · function · L22-L104 — def init_verification_db()
- save_attributes · function · L107-L140 — def save_attributes(attributes: list[dict])
- save_verification_results · function · L143-L197 — def save_verification_results(project_id: str, results: list[dict])
- resolve_anomaly · function · L200-L216 — def resolve_anomaly(result_id: str, status: str, comment: str) -> bool
- get_project_anomalies · function · L219-L234 — def get_project_anomalies(project_id: str) -> list[dict]
- get_project_attributes · function · L237-L248 — def get_project_attributes(project_id: str) -> list[dict]
- add_exception · function · L251-L274 — def add_exception(project_id: str, tag: str, rule_id: str, justification: str, condition_scope: dict = None, approved_by: str = "Expert") -> str
- get_exceptions · function · L277-L290 — def get_exceptions(project_id: str) -> list[dict]
- get_processed_documents_metadata · function · L293-L320 — def get_processed_documents_metadata(project_id: str) -> dict
- save_processed_document · function · L323-L339 — def save_processed_document(project_id: str, filename: str, file_path: str, file_size: int, last_modified: str, file_hash: str)
- delete_processed_document · function · L342-L356 — def delete_processed_document(project_id: str, file_path: str)
- clear_document_attributes · function · L359-L373 — def clear_document_attributes(project_id: str, document: str)
