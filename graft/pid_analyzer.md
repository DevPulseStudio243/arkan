# pid_analyzer.py

- calculate_civil_quantities · function · L23-L195 — def calculate_civil_quantities(prefix, dimensions_text)
- _is_valid_pid_tag · function · L361-L408 — def _is_valid_pid_tag(tag_str, prefix)
- _extract_metadata · function · L646-L733 — def _extract_metadata(text_blocks, filename)
- _extract_notes_and_holds · function · L735-L809 — def _extract_notes_and_holds(text_blocks)
- _extract_pipelines · function · L811-L878 — def _extract_pipelines(text_blocks)
- _categorize_and_enrich_elements · function · L880-L1057 — def _categorize_and_enrich_elements(unique_elements, text_blocks, pipelines)
- parse_pid_pdf · function · L1060-L1694 — def parse_pid_pdf(pdf_path, output_image_dir="generated_visuals", discipline="pid")
- add_tag · function · L1129-L1145 — def add_tag(tag_str, prefix, elem_type, x, y, box, extra=None)
- _extract_strings_from_dxf · function · L1703-L1761 — def _extract_strings_from_dxf(dxf_path)
- _extract_strings_from_dwg · function · L1770-L1798 — def _extract_strings_from_dwg(dwg_path, min_length=3)
- _filter_engineering_strings · function · L1801-L1881 — def _filter_engineering_strings(raw_strings)
- _render_dwg_to_image · function · L1884-L1948 — def _render_dwg_to_image(dwg_path, output_image_dir="generated_visuals")
- parse_dwg_file · function · L1951-L2458 — def parse_dwg_file(dwg_path, output_image_dir="generated_visuals", discipline="pid")
- add_tag · function · L2210-L2226 — def add_tag(tag_str, prefix, elem_type, x, y, extra=None)
- _render_dwg_to_pdf · function · L2460-L2508 — def _render_dwg_to_pdf(dwg_path, output_pdf_dir="generated_visuals")
- _render_dwg_to_svg · function · L2511-L2608 — def _render_dwg_to_svg(dwg_path, output_svg_dir="generated_visuals")
- map_extracted_to_dtim · function · L2610-L2743 — def map_extracted_to_dtim(extracted_data: dict, project_name: str = "Arkan-Project") -> Any
