# report_agent.py

- generate_equipment_report · function · L18-L33 — def generate_equipment_report(tag: str, output_format: str = "text") -> str
- call_llm_sync · function · L36-L67 — def call_llm_sync(prompt: str, system_prompt: str = "") -> str
- _collect_equipment_data · function · L70-L153 — def _collect_equipment_data(tag: str) -> Dict[str, Any]
- _generate_text_report · function · L156-L221 — def _generate_text_report(tag: str, data: Dict[str, Any]) -> str
- _generate_docx_report · function · L224-L307 — def _generate_docx_report(tag: str, data: Dict[str, Any]) -> str
