# pid_orthogonal_router.py

- PidOrthogonalRouter · class · L51-L721 — class PidOrthogonalRouter
- __init__ · method · L57-L71 — def __init__( self, canvas_width: float = 1600.0, canvas_height: float = 1000.0, margin_x: float = 120.0, margin_y_top: float = 90.0, margin_y_bottom: float = 140.0, hop_radius: float = 8.0, )
- layout_and_route · method · L73-L152 — def layout_and_route( self, topology_data: Dict[str, Any], canvas_w: Optional[float] = None, canvas_h: Optional[float] = None, ) -> Dict[str, Any]
- _compute_cad_bounds · method · L158-L189 — def _compute_cad_bounds( self, equipments: List[Dict[str, Any]], circuits: List[Dict[str, Any]], ) -> Tuple[float, float, float, float]
- _map_cad_to_svg · method · L191-L213 — def _map_cad_to_svg( self, cad_x: float, cad_y: float, cad_bounds: Tuple[float, float, float, float], ) -> Tuple[float, float]
- _layout_equipments · method · L219-L275 — def _layout_equipments( self, equipments: List[Dict[str, Any]], cad_bounds: Tuple[float, float, float, float], ) -> Dict[str, Dict[str, Any]]
- _place_nozzles · method · L281-L343 — def _place_nozzles( self, equipments: List[Dict[str, Any]] ) -> Tuple[Dict[Tuple[str, str], List[float]], Dict[Tuple[str, str], str]]
- _route_circuits · method · L349-L421 — def _route_circuits( self, circuits: List[Dict[str, Any]], eq_map: Dict[str, Dict[str, Any]], nozzle_coords_map: Dict[Tuple[str, str], List[float]], nozzle_orient_map: Dict[Tuple[str, str], str], cad_bounds: Tuple[float, float, float, float], ) -> List[Dict[str, Any]]
- _resolve_endpoint · method · L423-L476 — def _resolve_endpoint( self, node: Dict[str, Any], is_start: bool, cad_poly: List[List[float]], eq_map: Dict[str, Dict[str, Any]], nozzle_coords: Dict[Tuple[str, str], List[float]], nozzle_orients: Dict[Tuple[str, str], str], cad_bounds: Tuple[float, float, float, float], ) -> Tuple[List[float], str]
- _compute_manhattan_path · method · L478-L531 — def _compute_manhattan_path( self, p_start: List[float], dir_from: str, p_end: List[float], dir_to: str, ) -> List[List[float]]
- _place_and_orient_components · method · L537-L609 — def _place_and_orient_components( self, circuits: List[Dict[str, Any]], valves: List[Dict[str, Any]], ) -> List[Dict[str, Any]]
- _detect_and_build_hops · method · L615-L670 — def _detect_and_build_hops(self, circuits: List[Dict[str, Any]]) -> int
- _place_instruments · method · L676-L721 — def _place_instruments( self, instruments: List[Dict[str, Any]], circuits: List[Dict[str, Any]], eq_map: Dict[str, Dict[str, Any]], cad_bounds: Tuple[float, float, float, float], ) -> List[Dict[str, Any]]
- route_pid_topology · function · L724-L741 — def route_pid_topology( topology_data: Dict[str, Any], canvas_w: float = 1600.0, canvas_h: float = 1000.0, ) -> Dict[str, Any]
