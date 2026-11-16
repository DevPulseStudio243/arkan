# dxf_extractor.py

- _dist_point_to_segment · function · L32-L37 — def _dist_point_to_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float
- estimate_geometry_tolerances · function · L40-L78 — def estimate_geometry_tolerances(segments: List[Tuple], blocks: List[Dict[str, Any]]) -> Dict[str, float]
- ExtractionConfig · class · L86-L128 — class ExtractionConfig: # Layers considérés comme tuyauterie (matching insensible à la casse, substring)
- _entity_layer · function · L131-L135 — def _entity_layer(e) -> str
- _layer_matches · function · L138-L139 — def _layer_matches(layer: str, keywords: List[str]) -> bool
- _name_matches · function · L142-L155 — def _name_matches(name: str, keywords: List[str]) -> bool
- extract_segments · function · L162-L221 — def extract_segments(msp, cfg: ExtractionConfig) -> List[Tuple[Tuple[float, float], Tuple[float, float], Dict[str, Any]]]
- layer_ok · function · L166-L174 — def layer_ok(e) -> bool
- extract_labels · function · L228-L249 — def extract_labels(msp, cfg: ExtractionConfig) -> List[Dict[str, Any]]
- _get_block_attribs · function · L256-L261 — def _get_block_attribs(insert_entity) -> Dict[str, str]
- _resolve_tag · function · L264-L282 — def _resolve_tag(attribs: Dict[str, str], block_name: str, cfg: ExtractionConfig) -> Tuple[str, str]
- _classify_block · function · L285-L296 — def _classify_block(block_name: str, cfg: ExtractionConfig) -> str
- extract_blocks_and_opcs · function · L299-L359 — def extract_blocks_and_opcs( msp, doc, cfg: ExtractionConfig ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]
- attach_tags_from_nearby_text · function · L369-L399 — def attach_tags_from_nearby_text( blocks: List[Dict[str, Any]], labels: List[Dict[str, Any]], search_radius: float = 25.0 ) -> List[Dict[str, Any]]
- extract_drawing · function · L402-L427 — def extract_drawing(dxf_path: str, cfg: ExtractionConfig | None = None) -> Dict[str, Any]
