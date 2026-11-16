# verification_extractors.py

- resolve_project_for_file · function · L23-L54 — def resolve_project_for_file(file_path: Path) -> dict
- extract_attributes_from_docx · function · L57-L153 — def extract_attributes_from_docx(file_path: Path) -> list[dict]
- _parse_sub_attributes · function · L156-L431 — def _parse_sub_attributes(text: str, tag: str, document: str, project_id: str, attributes: list)
- extract_attributes_from_xlsx · function · L434-L473 — def extract_attributes_from_xlsx(file_path: Path) -> list[dict]
- is_in_legend_or_cartouche · function · L476-L484 — def is_in_legend_or_cartouche(index: int, content: str) -> bool
- extract_attributes_from_pfd_html · function · L487-L537 — def extract_attributes_from_pfd_html(file_path: Path) -> list[dict]
- preprocess_fragmented_text · function · L540-L563 — def preprocess_fragmented_text(text: str) -> str
- determine_main_tag · function · L566-L596 — def determine_main_tag(text: str) -> str
- extract_attributes_from_pdf · function · L599-L678 — def extract_attributes_from_pdf(file_path: Path) -> list[dict]
- compute_file_hash · function · L681-L692 — def compute_file_hash(file_path: Path) -> str
- scan_and_extract_project_documents · function · L695-L800 — def scan_and_extract_project_documents(project_dir_path: Path) -> int
