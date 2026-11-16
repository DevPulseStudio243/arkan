# dxf_to_pid_json.py

- _clean_str · function · L179-L188 — def _clean_str(txt: Any) -> str
- _bb_dist · function · L191-L195 — def _bb_dist(p: Sequence[float], bb: Sequence[float]) -> float
- _seg_point_projection · function · L198-L210 — def _seg_point_projection(p: Sequence[float], a: Sequence[float], b: Sequence[float]) -> Tuple[float, List[float], float]
- _intersect_seg_box · function · L213-L243 — def _intersect_seg_box(p1: Sequence[float], p2: Sequence[float], box: Sequence[float]) -> Optional[Tuple[float, float]]
- DxfToPidJsonConverter · class · L251-L1209 — class DxfToPidJsonConverter
- __init__ · method · L257-L262 — def __init__( self, config: Optional[Dict[str, Any]] = None, config_path: Optional[str | Path] = None, )
- convert · method · L264-L360 — def convert( self, dxf_path: str | Path, out_path: Optional[str | Path] = None, review: Optional[str | Path] = None, pretty: bool = True, ) -> Dict[str, Any]
- _isolate_symbol_entities · method · L366-L416 — def _isolate_symbol_entities( self, raw_data: Dict[str, Any], semantic_data: Dict[str, Any] ) -> Tuple[Set[str], Set[str]]
- _build_equipments · method · L422-L517 — def _build_equipments( self, raw_data: Dict[str, Any], semantic_data: Dict[str, Any], symbol_entity_ids: Set[str], ) -> Dict[str, Dict[str, Any]]
- _build_piping_circuits · method · L523-L856 — def _build_piping_circuits( self, raw_data: Dict[str, Any], semantic_data: Dict[str, Any], equipments: Dict[str, Dict[str, Any]], symbol_entity_ids: Set[str], ) -> List[Dict[str, Any]]
- _detect_and_attach_nozzles · method · L862-L954 — def _detect_and_attach_nozzles( self, equipments: Dict[str, Dict[str, Any]], circuits: List[Dict[str, Any]], ) -> None
- _build_valves · method · L960-L1039 — def _build_valves( self, raw_data: Dict[str, Any], semantic_data: Dict[str, Any], circuits: List[Dict[str, Any]], ) -> List[Dict[str, Any]]
- _build_instruments_and_loops · method · L1045-L1141 — def _build_instruments_and_loops( self, raw_data: Dict[str, Any], semantic_data: Dict[str, Any], circuits: List[Dict[str, Any]], valves: List[Dict[str, Any]], ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]
- _build_topology_summary · method · L1147-L1188 — def _build_topology_summary( self, equipments: List[Dict[str, Any]], circuits: List[Dict[str, Any]], valves: List[Dict[str, Any]], instruments: List[Dict[str, Any]], loops: List[Dict[str, Any]], ) -> Dict[str, Any]
- _clean_and_serialize · method · L1194-L1209 — def _clean_and_serialize(self, obj: Any) -> Any
- convert_dxf_to_json · function · L1217-L1245 — def convert_dxf_to_json( dxf_path: str | Path, output_json_path: Optional[str | Path] = None, config: Optional[Dict[str, Any]] = None, config_path: Optional[str | Path] = None, review: Optional[str | Path] = None, pretty: bool = True, ) -> Dict[str, Any]
- main · function · L1265-L1297 — def main() -> None
