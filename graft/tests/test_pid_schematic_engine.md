# tests/test_pid_schematic_engine.py

- synthetic_dxf_path · function · L31-L33 — def synthetic_dxf_path() -> Path
- routed_synthetic_data · function · L37-L39 — def routed_synthetic_data(synthetic_dxf_path) -> Dict[str, Any]
- TestPidSchematicEngine · class · L42-L338 — class TestPidSchematicEngine
- test_instantiation_default_and_custom · method · L45-L55 — def test_instantiation_default_and_custom(self)
- test_render_dxf_to_schematic_end_to_end · method · L57-L82 — def test_render_dxf_to_schematic_end_to_end(self, synthetic_dxf_path, tmp_path)
- test_svg_elements_and_markup · method · L84-L98 — def test_svg_elements_and_markup(self, routed_synthetic_data)
- test_interactive_data_attributes · method · L100-L122 — def test_interactive_data_attributes(self, routed_synthetic_data)
- test_equipment_glyphs_isa_5_1 · method · L124-L192 — def test_equipment_glyphs_isa_5_1(self)
- test_valves_bowtie_rendering · method · L194-L245 — def test_valves_bowtie_rendering(self)
- test_hops_arc_rendering · method · L247-L285 — def test_hops_arc_rendering(self)
- test_instruments_bubble_rendering · method · L287-L322 — def test_instruments_bubble_rendering(self)
- test_legend_panel_and_fluid_colors · method · L324-L338 — def test_legend_panel_and_fluid_colors(self, routed_synthetic_data)
