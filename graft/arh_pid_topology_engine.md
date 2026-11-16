# arh_pid_topology_engine.py

- ARHPidTopologyEngine · class · L24-L336 — class ARHPidTopologyEngine
- __init__ · method · L27-L31 — def __init__(self)
- reset · method · L33-L38 — def reset(self)
- add_equipment · method · L40-L44 — def add_equipment(self, tag: str, eq_type: str = "VESSEL", metadata: Optional[Dict[str, Any]] = None)
- add_valve · method · L46-L57 — def add_valve(self, tag: str, valve_type: str, lock_status: str = "NONE", metadata: Optional[Dict[str, Any]] = None)
- add_piping_connection · method · L59-L63 — def add_piping_connection(self, from_node: str, to_node: str, line_tag: str = "", fluid: str = "", rating: str = "")
- parse_pid_text · method · L65-L103 — def parse_pid_text(self, text: str, source_doc: str = "P&ID", page: str = "") -> None
- audit_process_safety_rules · method · L105-L299 — def audit_process_safety_rules(self, source_doc: str = "P&ID", page: str = "") -> List[Dict[str, Any]]
- _classify · method · L302-L309 — def _classify(tag: str) -> Optional[str]
- _is_bleed · method · L311-L315 — def _is_bleed(self, node: str) -> bool
- load_from_line_entries · method · L317-L331 — def load_from_line_entries(self, entries: List[Dict[str, Any]]) -> None
- fresh · method · L334-L336 — def fresh(cls) -> "ARHPidTopologyEngine"
