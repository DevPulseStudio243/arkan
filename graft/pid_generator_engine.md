# pid_generator_engine.py

- PIDEquipment · class · L20-L25 — class PIDEquipment(BaseModel)
- PIDPipeline · class · L27-L34 — class PIDPipeline(BaseModel)
- PIDValve · class · L36-L41 — class PIDValve(BaseModel)
- PIDInstrument · class · L43-L48 — class PIDInstrument(BaseModel)
- PIDDesignResult · class · L50-L61 — class PIDDesignResult(BaseModel)
- PIDGeneratorEngine · class · L64-L677 — class PIDGeneratorEngine
- __init__ · method · L67-L70 — def __init__(self)
- generate · method · L72-L125 — def generate(self, prompt: str, process_type: str = "separation", project_code: str = "ARKAN-EPC") -> PIDDesignResult
- _build_separator_topology · method · L127-L159 — def _build_separator_topology(self, prompt: str, project_code: str) -> Dict[str, Any]
- _build_pig_trap_topology · method · L161-L187 — def _build_pig_trap_topology(self, prompt: str, project_code: str) -> Dict[str, Any]
- _build_wellhead_topology · method · L189-L213 — def _build_wellhead_topology(self, prompt: str, project_code: str) -> Dict[str, Any]
- _build_pumping_topology · method · L215-L241 — def _build_pumping_topology(self, prompt: str, project_code: str) -> Dict[str, Any]
- _build_flare_topology · method · L243-L265 — def _build_flare_topology(self, prompt: str, project_code: str) -> Dict[str, Any]
- _render_orthogonal_svg · method · L267-L586 — def _render_orthogonal_svg(self, equipments: List[PIDEquipment], pipelines: List[PIDPipeline], valves: List[PIDValve], instruments: List[PIDInstrument], process_type: str = "separation", title: str = "") -> str
- _generate_dxf · method · L589-L631 — def _generate_dxf(self, title: str, equipments: List[PIDEquipment], pipelines: List[PIDPipeline], valves: List[PIDValve], instruments: List[PIDInstrument]) -> str
- _generate_dexpi_xml · method · L633-L651 — def _generate_dexpi_xml(self, title: str, equipments: List[PIDEquipment], pipelines: List[PIDPipeline], valves: List[PIDValve], instruments: List[PIDInstrument]) -> str
- _calculate_mto · method · L653-L677 — def _calculate_mto(self, pipelines: List[PIDPipeline], valves: List[PIDValve]) -> Dict[str, Any]
