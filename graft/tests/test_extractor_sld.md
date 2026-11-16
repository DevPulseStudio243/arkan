# tests/test_extractor_sld.py

- make_table_pdf · function · L11-L24 — def make_table_pdf(path, rows, header=("TAG", "DESIGNATION", "P (kW)", "CALIBRE (A)", "CABLE", "LONGUEUR (m)"), title="SCHEMA UNIFILAIRE TGBT BT", pages=1)
- make_column_pdf · function · L27-L35 — def make_column_pdf(path, columns, title="SCHEMA UNIFILAIRE TGBT", page_blocks=1)
- run · function · L38-L39 — def run(path, **opts)
- test_table_layout_reads_fields_and_never_invents_values · function · L49-L62 — def test_table_layout_reads_fields_and_never_invents_values(tmp_path)
- test_column_layout_without_ruling_lines · function · L65-L71 — def test_column_layout_without_ruling_lines(tmp_path)
- test_no_phantom_feeder_without_tag · function · L74-L78 — def test_no_phantom_feeder_without_tag(tmp_path)
- test_missing_calibre_and_section_are_none_with_reasons · function · L81-L86 — def test_missing_calibre_and_section_are_none_with_reasons(tmp_path)
- test_duplicates_between_pages_and_conflicts · function · L89-L99 — def test_duplicates_between_pages_and_conflicts(tmp_path)
- test_unknown_pdf_is_rejected_not_forced_into_sld · function · L102-L107 — def test_unknown_pdf_is_rejected_not_forced_into_sld(tmp_path)
- test_busbar_trunking_section_kept · function · L110-L113 — def test_busbar_trunking_section_kept(tmp_path)
- test_extract_ie_drawing_dispatch · function · L116-L118 — def test_extract_ie_drawing_dispatch(tmp_path)
- test_end_to_end_with_consolidator · function · L121-L132 — def test_end_to_end_with_consolidator(tmp_path)
