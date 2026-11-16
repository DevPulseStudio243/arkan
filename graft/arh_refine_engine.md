# arh_refine_engine.py

- _init_refine_tables · function · L29-L60 — def _init_refine_tables()
- _normalize_text · function · L71-L77 — def _normalize_text(text: str) -> str
- ARHRefineEngine · class · L80-L279 — class ARHRefineEngine
- record_feedback · method · L85-L153 — def record_feedback( self, dossier_id: str, finding_id: str, verdict: str, inspector_notes: str, finding_data: Optional[Dict[str, Any]] = None, vendor_name: Optional[str] = None, equipment_type: Optional[str] = None ) -> Dict[str, Any]
- _derive_rule_from_feedback · method · L155-L202 — def _derive_rule_from_feedback( self, category: str, title: str, notes: str, vendor_name: Optional[str], equipment_type: Optional[str], verdict: str ) -> Optional[Dict[str, Any]]
- get_active_rules · method · L204-L230 — def get_active_rules( self, vendor_name: Optional[str] = None, equipment_type: Optional[str] = None ) -> List[Dict[str, Any]]
- apply_refine_rules · method · L232-L279 — def apply_refine_rules( self, findings: List[Dict[str, Any]], vendor_name: Optional[str] = None, equipment_type: Optional[str] = None ) -> List[Dict[str, Any]]
