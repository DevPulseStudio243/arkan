# engineering_tools.py

- tool_convert_units · function · L64-L88 — def tool_convert_units(value: str, from_unit: str, to_unit: str) -> str
- tool_calculate_pressure_drop · function · L95-L155 — def tool_calculate_pressure_drop( flow_rate_m3h: str, pipe_diameter_mm: str, pipe_length_m: str, fluid_density_kg_m3: str, fluid_viscosity_cp: str, pipe_roughness_mm: str = "0.046" ) -> str
- tool_calculate_pump_power · function · L162-L212 — def tool_calculate_pump_power( flow_rate_m3h: str, total_head_m: str, fluid_density_kg_m3: str, pump_efficiency_pct: str, motor_efficiency_pct: str = "95" ) -> str
- tool_extract_data_sheet · function · L219-L313 — def tool_extract_data_sheet(file_path: str, equipment_tag: str = "") -> str
- tool_calculate_pipe_sizing · function · L320-L389 — def tool_calculate_pipe_sizing( flow_rate_m3h: str, fluid_density_kg_m3: str, fluid_viscosity_cp: str, max_velocity_ms: str = "3.0", fluid_type: str = "liquid" ) -> str
- tool_find_piping_class · function · L415-L466 — def tool_find_piping_class( design_pressure_bar: str, design_temp_c: str, fluid_service: str = "HC" ) -> str
- tool_check_norm_compliance · function · L527-L563 — def tool_check_norm_compliance(norm_code: str, context: str = "") -> str
- tool_extract_instrument_list · function · L570-L663 — def tool_extract_instrument_list(file_path: str) -> str
- tool_calculate_relief_valve · function · L718-L782 — def tool_calculate_relief_valve( set_pressure_bar: str, back_pressure_bar: str, fluid_type: str, flow_rate_kg_h: str, molecular_weight: str = "44", temperature_c: str = "100", cp_cv_ratio: str = "1.3" ) -> str
- tool_analyze_control_loop · function · L797-L853 — def tool_analyze_control_loop(loop_tag: str, file_path: str = "", context: str = "") -> str
- tool_check_hazop_deviation · function · L881-L918 — def tool_check_hazop_deviation(parameter: str, guide_word: str, node_description: str = "") -> str
- tool_update_knowledge_graph · function · L944-L958 — def tool_update_knowledge_graph(tag_a: str, tag_b: str, relation: str, source: str) -> str
- tool_cross_check_documents · function · L960-L987 — def tool_cross_check_documents(tag: str) -> str
- tool_generate_equipment_report · function · L1006-L1012 — def tool_generate_equipment_report(tag: str, format: str = "text") -> str
- tool_import_equipment_list · function · L1015-L1104 — def tool_import_equipment_list(file_path: str) -> str
- tool_get_scada_live_data · function · L1107-L1120 — def tool_get_scada_live_data(tag: str) -> str
- tool_analyze_scada_trend · function · L1123-L1147 — def tool_analyze_scada_trend(tag: str, metric: str, last_n: str = "20") -> str
