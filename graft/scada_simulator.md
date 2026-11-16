# scada_simulator.py

- ScadaSimulator · class · L13-L118 — class ScadaSimulator
- __init__ · method · L16-L24 — def __init__(self)
- get_live_data · method · L26-L66 — def get_live_data(self, tag: str) -> dict
- get_trend · method · L68-L113 — def get_trend(self, tag: str, metric: str, last_n: int = 20) -> Dict
- get_all_live · method · L115-L118 — def get_all_live(self, tags: List[str] = None) -> List[Dict]
- get_live_tag_data · function · L124-L126 — def get_live_tag_data(tag: str) -> dict
- get_trend_data · function · L128-L130 — def get_trend_data(tag: str, metric: str, last_n: int = 20) -> dict
- get_dashboard_data · function · L132-L134 — def get_dashboard_data(tags: List[str] = None) -> List[Dict]
