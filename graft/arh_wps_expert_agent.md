# arh_wps_expert_agent.py

- check_itp_tpi_arh_column · function · L31-L76 — def check_itp_tpi_arh_column(text: str) -> bool
- ARHWeldingProcedureExpertAgent · class · L134-L587 — class ARHWeldingProcedureExpertAgent
- __init__ · method · L140-L142 — def __init__(self)
- compute_asme_ix_thickness_range · method · L149-L170 — def compute_asme_ix_thickness_range(coupon_thickness_mm: float) -> Tuple[float, float]
- compute_iso_15614_thickness_range · method · L173-L191 — def compute_iso_15614_thickness_range(coupon_thickness_mm: float) -> Tuple[float, float]
- compute_asme_ix_diameter_range · method · L194-L204 — def compute_asme_ix_diameter_range(coupon_diameter_mm: float) -> Tuple[float, float]
- extract_wps_parameters · method · L210-L342 — def extract_wps_parameters(self, text: str, filename: str = "") -> Dict[str, Any]
- audit · method · L348-L587 — def audit( self, docs: List[Dict[str, Any]], equipment_type: str, dossier_stage: str = "PRELIMINARY", equipment_context: Optional[Dict[str, Any]] = None ) -> List[Dict[str, Any]]
