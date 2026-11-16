# line_partitioner.py

- _quantize · function · L31-L32 — def _quantize(pt: Tuple[float, float], grid: float) -> Tuple[float, float]
- _seg_length · function · L35-L36 — def _seg_length(s: Segment) -> float
- _dist_point_to_segment · function · L39-L44 — def _dist_point_to_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float
- partition_segments_by_line_label · function · L47-L140 — def partition_segments_by_line_label( segments: List[Segment], line_labels: List[Dict[str, Any]], connection_tolerance: float = 30.0, max_seed_distance: float = 350.0, ) -> Dict[str, List[Segment]]
- assign_blocks_to_partitions · function · L143-L184 — def assign_blocks_to_partitions( segments: List[Segment], partitions: Dict[str, List[Segment]], blocks: List[Dict[str, Any]], max_assign_distance: float = 500.0, ) -> Dict[int, str]
- assign_blocks_to_line_partitions · function · L188-L201 — def assign_blocks_to_line_partitions( blocks: List[Dict[str, Any]], partitions: Dict[str, List[Segment]], max_search_radius: float = 500.0 ) -> Dict[int, str]
