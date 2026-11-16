# geometry_engine.py

- GeometryGraph · class · L14-L170 — class GeometryGraph
- __init__ · method · L15-L35 — def __init__(self, raw_text: str): # Truncate text before the table to only parse drawing symbols and cotes
- _detect_pipe_sizes · method · L37-L44 — def _detect_pipe_sizes(self) -> List[str]
- _extract_dimension_cotes · method · L46-L95 — def _extract_dimension_cotes(self) -> List[int]
- is_excluded · function · L81-L85 — def is_excluded(pos)
- reconstruct_network · method · L97-L121 — def reconstruct_network(self)
- get_pipe_lengths · method · L123-L155 — def get_pipe_lengths(self) -> Dict[str, float]
- get_caesar_nodes · method · L157-L170 — def get_caesar_nodes(self) -> List[Dict[str, Any]]
