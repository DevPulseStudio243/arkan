# asme_piping_catalog.py

- normalize_nps · function · L200-L219 — def normalize_nps(raw_val: Any) -> str
- normalize_schedule · function · L222-L236 — def normalize_schedule(raw_sch: Any) -> str
- normalize_rating · function · L239-L249 — def normalize_rating(raw_rating: Any) -> str
- get_pipe_unit_weight · function · L252-L280 — def get_pipe_unit_weight(nps: str, schedule: str = "SCH 40") -> float
- get_fitting_unit_weight · function · L283-L306 — def get_fitting_unit_weight(category: str, nps: str, schedule: str = "SCH 40") -> float
- get_flange_unit_weight · function · L309-L322 — def get_flange_unit_weight(nps: str, rating: str = "150#", flange_type: str = "WN") -> float
- get_valve_unit_weight · function · L325-L339 — def get_valve_unit_weight(nps: str, rating: str = "150#", valve_type: str = "BALL") -> float
- calculate_piping_takeoffs · function · L371-L422 — def calculate_piping_takeoffs(nps: str, callout_counts: Dict[str, int], rating: str = "150#") -> Tuple[float, Dict[str, float]]
