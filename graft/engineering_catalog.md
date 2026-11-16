# engineering_catalog.py

- get_pipe_spec · function · L218-L226 — def get_pipe_spec(size: str, schedule: str = "40") -> dict
- get_flange_spec · function · L228-L234 — def get_flange_spec(size: str, rating: str = "150") -> dict
- get_elbow_spec · function · L236-L243 — def get_elbow_spec(size: str, angle: str = "90", type: str = "LR") -> dict
- get_reducer_spec · function · L245-L252 — def get_reducer_spec(size_large: str, size_small: str) -> dict
- get_tee_spec · function · L254-L260 — def get_tee_spec(size: str) -> dict
- get_valve_weight · function · L262-L268 — def get_valve_weight(valve_type: str, size: str) -> float
