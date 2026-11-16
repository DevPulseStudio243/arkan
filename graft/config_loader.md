# config_loader.py

- ConfigError · class · L39-L40 — class ConfigError(Exception)
- get_config_path · function · L122-L128 — def get_config_path(path: Optional[str] = None) -> Path
- _deep_merge · function · L134-L141 — def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]
- _is_num · function · L144-L145 — def _is_num(x: Any) -> bool
- validate_config · function · L148-L203 — def validate_config(cfg: Dict[str, Any]) -> List[str]
- _info · function · L206-L212 — def _info(source: str, raw_bytes: bytes, cfg: Dict[str, Any], warning: str = "") -> Dict[str, Any]
- _load · function · L215-L238 — def _load(path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]
- load_project_config · function · L241-L252 — def load_project_config(force_reload: bool = False, path: Optional[str] = None) -> Dict[str, Any]
- get_config_info · function · L255-L258 — def get_config_info(path: Optional[str] = None) -> Dict[str, Any]
- get_threshold · function · L261-L263 — def get_threshold(name: str, default: Optional[float] = None) -> Optional[float]
- effective_margins · function · L267-L279 — def effective_margins(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, float]
- resolve_margin · function · L282-L309 — def resolve_margin(category: Optional[str], discipline: Optional[str] = None, cable_kind: Optional[str] = None) -> Tuple[float, bool]
- get_margin_for_category · function · L312-L314 — def get_margin_for_category(category: str) -> float
- apply_margin · function · L317-L333 — def apply_margin(q_net: float, margin: float, unit: Optional[str]) -> float
- get_section · function · L336-L338 — def get_section(name: str) -> Dict[str, Any]
