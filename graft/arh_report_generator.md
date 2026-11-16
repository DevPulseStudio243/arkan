# arh_report_generator.py

- ARHReportGenerator · class · L25-L191 — class ARHReportGenerator
- __init__ · method · L26-L28 — def __init__(self, output_dir: str = "generated_visuals")
- generate_pdf_report · method · L30-L41 — def generate_pdf_report(self, audit_result: Dict[str, Any]) -> str
- _build_reportlab_pdf · method · L43-L165 — def _build_reportlab_pdf(self, res: Dict[str, Any], pdf_path: str) -> str
- _build_fallback_text_report · method · L167-L191 — def _build_fallback_text_report(self, res: Dict[str, Any], pdf_path: str) -> str
