# arh_ai_engine.py

- ARHSpecialistRouter · class · L276-L301 — class ARHSpecialistRouter
- identify_specialist · method · L278-L301 — def identify_specialist(text: str, forced_type: Optional[str] = None) -> Dict[str, Any]
- ARHAIEngine · class · L304-L540 — class ARHAIEngine
- __new__ · method · L308-L311 — def __new__(cls)
- audit_dossier_with_specialist · method · L313-L530 — def audit_dossier_with_specialist( self, docs_text: str, equipment_type: Optional[str] = None, equipment_tag: Optional[str] = None, file_names: Optional[List[str]] = None, group_docs: Optional[List[Dict[str, Any]]] = None, dossier_stage: str = "PRELIMINARY", skip_universal_qaqc: bool = False, ) -> List[Dict[str, Any]]
- analyze · method · L532-L540 — def analyze(self, input_text: str) -> dict
