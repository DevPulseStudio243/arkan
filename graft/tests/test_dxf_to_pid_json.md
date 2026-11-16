# tests/test_dxf_to_pid_json.py

- synthetic_dxf_path · function · L29-L32 — def synthetic_dxf_path()
- converted_data · function · L36-L38 — def converted_data(synthetic_dxf_path)
- TestDxfToPidJsonConverter · class · L41-L247 — class TestDxfToPidJsonConverter
- test_instantiation_default_and_custom · method · L44-L53 — def test_instantiation_default_and_custom(self)
- test_file_not_found_raises · method · L55-L60 — def test_file_not_found_raises(self, tmp_path)
- test_root_structure_keys · method · L62-L75 — def test_root_structure_keys(self, converted_data)
- test_metadata_fields · method · L77-L84 — def test_metadata_fields(self, converted_data)
- test_equipments_and_nozzles · method · L86-L125 — def test_equipments_and_nozzles(self, converted_data)
- test_piping_circuits_and_inline_components · method · L127-L161 — def test_piping_circuits_and_inline_components(self, converted_data)
- test_valves · method · L163-L176 — def test_valves(self, converted_data)
- test_topology_summary · method · L178-L189 — def test_topology_summary(self, converted_data)
- test_json_file_export · method · L191-L200 — def test_json_file_export(self, synthetic_dxf_path, tmp_path)
- test_instrument_and_loops_isa_5_1 · method · L202-L247 — def test_instrument_and_loops_isa_5_1(self)
