# tests/test_ei_triangulation.py

- client · function · L22-L23 — def client()
- tmp_excel_calc_note · function · L27-L38 — def tmp_excel_calc_note(tmp_path)
- tmp_csv_calc_note · function · L42-L49 — def tmp_csv_calc_note(tmp_path)
- tmp_excel_cable_schedule · function · L53-L67 — def tmp_excel_cable_schedule(tmp_path)
- test_calculation_note_parser_excel · function · L70-L80 — def test_calculation_note_parser_excel(tmp_excel_calc_note)
- test_calculation_note_parser_csv · function · L83-L91 — def test_calculation_note_parser_csv(tmp_csv_calc_note)
- test_cable_schedule_parser · function · L94-L100 — def test_cable_schedule_parser(tmp_excel_cable_schedule)
- test_triangulation_axis_1_omission · function · L103-L123 — def test_triangulation_axis_1_omission()
- test_triangulation_axis_2_length_mismatch · function · L126-L146 — def test_triangulation_axis_2_length_mismatch()
- test_triangulation_axis_3_voltage_drop_recalculation · function · L149-L173 — def test_triangulation_axis_3_voltage_drop_recalculation()
- test_triangulation_axis_4_section_and_spec_mismatch · function · L176-L192 — def test_triangulation_axis_4_section_and_spec_mismatch()
- test_api_triangulation_and_action_flow · function · L195-L253 — def test_api_triangulation_and_action_flow(client, tmp_excel_calc_note, tmp_excel_cable_schedule)
