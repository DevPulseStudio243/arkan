# pid_schematic_engine.py

- is_parasite_layer · function · L105-L113 — def is_parasite_layer(layer_name: Optional[str]) -> bool
- _pt_seg_dist_sq · function · L116-L124 — def _pt_seg_dist_sq(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float
- _find_nearest_segment_angle · function · L127-L140 — def _find_nearest_segment_angle( px: float, py: float, segments: List[Tuple[float, float, float, float]] ) -> float
- PidSchematicEngine · class · L143-L567 — class PidSchematicEngine
- __init__ · method · L148-L156 — def __init__( self, canvas_width: float = 1600.0, canvas_height: float = 1000.0, pipe_stroke_width: float = 2.4, )
- render_semantic · method · L158-L563 — def render_semantic( self, sem_data: Dict[str, Any], raw_data: Optional[Dict[str, Any]] = None, drawing_stem: str = "" ) -> str
- to_svg · function · L261-L264 — def to_svg(x: float, y: float) -> Tuple[float, float]
- render · method · L565-L567 — def render(self, routed_or_semantic_data: Dict[str, Any]) -> str
- render_dxf_to_schematic · function · L570-L623 — def render_dxf_to_schematic( dxf_path: str | Path, out_svg_path: Optional[str | Path] = None, out_json_path: Optional[str | Path] = None, canvas_w: float = 1600.0, canvas_h: float = 1000.0, ) -> str
