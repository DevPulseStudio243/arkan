# arh_official_deliverables_engine.py

- ARHOfficialDeliverablesEngine · class · L131-L478 — class ARHOfficialDeliverablesEngine
- __init__ · method · L134-L135 — def __init__(self, db_path: str = r"d:\DATA BASE IA\arh_dossiers.db")
- _get_dossier_data · method · L137-L159 — def _get_dossier_data(self, dossier_id: str) -> Dict[str, Any]
- generate_official_bordereau_pdf · method · L164-L259 — def generate_official_bordereau_pdf(self, dossier_id: str) -> str
- generate_fiche_descriptive_pdf · method · L264-L352 — def generate_fiche_descriptive_pdf(self, dossier_id: str) -> str
- draw_section_hdr · function · L293-L296 — def draw_section_hdr(label: str, cur_y: float) -> float
- generate_matrice_levee_reserves_pdf · method · L357-L478 — def generate_matrice_levee_reserves_pdf(self, dossier_id: str) -> str
