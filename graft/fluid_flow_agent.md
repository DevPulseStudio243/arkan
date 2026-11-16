# fluid_flow_agent.py

- parse_size_to_float · function · L34-L53 — def parse_size_to_float(val) -> float
- FluidFlowReasoningAgent · class · L56-L339 — class FluidFlowReasoningAgent
- __init__ · method · L59-L60 — def __init__(self)
- is_equipment_tag · method · L62-L79 — def is_equipment_tag(self, text: str) -> bool
- is_line_tag · method · L82-L89 — def is_line_tag(self, text: str) -> bool
- split_lines_at_reducers · method · L91-L168 — def split_lines_at_reducers( self, line_entries: List[Dict[str, Any]], labels: List[Dict[str, Any]] ) -> List[Dict[str, Any]]
- reason_flow_direction · method · L170-L206 — def reason_flow_direction(self, line_entry: Dict[str, Any]) -> Dict[str, Any]
- get_base_line_key · method · L208-L232 — def get_base_line_key(self, tag_str: str, size: str = "") -> str
- process_and_validate_lines · method · L234-L339 — def process_and_validate_lines( self, raw_lines: List[Dict[str, Any]], labels: List[Dict[str, Any]] ) -> List[Dict[str, Any]]
