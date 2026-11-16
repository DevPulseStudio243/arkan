# cable_routing_engine.py

- TrayGraph · class · L44-L154 — class TrayGraph
- __init__ · method · L47-L54 — def __init__(self, node_merge_tol: float = 0.05)
- _grid_key · method · L56-L57 — def _grid_key(self, x: float, y: float) -> Tuple[int, int]
- add_node · method · L59-L86 — def add_node(self, x: float, y: float) -> int
- add_edge · method · L88-L104 — def add_edge(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> None
- find_nearest_node · method · L106-L117 — def find_nearest_node(self, x: float, y: float) -> Tuple[Optional[int], float]
- shortest_path · method · L119-L154 — def shortest_path(self, start_idx: int, end_idx: int) -> Tuple[Optional[List[int]], float]
- CableRoutingEngine · class · L157-L412 — class CableRoutingEngine
- __init__ · method · L160-L171 — def __init__(self, config: Optional[Dict[str, Any]] = None)
- get_elevation_for_type · method · L173-L181 — def get_elevation_for_type(self, eq_type: str) -> float
- load_from_ezdxf_doc · method · L183-L208 — def load_from_ezdxf_doc(self, doc: Any, scale_to_m: float = 0.001) -> None
- _extract_equipment · method · L210-L266 — def _extract_equipment(self, msp: Any, scale_to_m: float) -> None
- register_equipment · method · L268-L282 — def register_equipment(self, tag: str, x: float, y: float, eq_type: str = "EQUIPMENT") -> None
- find_equipment · method · L284-L305 — def find_equipment(self, tag: str) -> Optional[Dict[str, Any]]
- route_cable · method · L307-L412 — def route_cable( self, origin_tag: str, dest_tag: str, origin_type: Optional[str] = None, dest_type: Optional[str] = None ) -> Dict[str, Any]
