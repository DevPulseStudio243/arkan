# pid_equipment_blocks.py

- _touch · function · L52-L54 — def _touch(a: List[float], b: List[float], g: float) -> bool
- _bbdist · function · L57-L59 — def _bbdist(p: List[float], bb: List[float]) -> float
- cluster · function · L62-L82 — def cluster(ents: List[Dict[str, Any]], gap: float) -> List[List[Dict[str, Any]]]
- find · function · L68-L72 — def find(x: int) -> int
- bbox_of · function · L85-L92 — def bbox_of(mem: List[Dict[str, Any]]) -> List[float]
- signature · function · L95-L111 — def signature(mem: List[Dict[str, Any]], bb: List[float]) -> str
- block_name · function · L114-L120 — def block_name(tags: List[str], idx: int) -> str
- analyse · function · L123-L352 — def analyse(folder: str | Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, List[int]], int, Dict[str, Any]]
- _panel · function · L356-L426 — def _panel(c: Dict[str, Any], geo_all: List[Dict[str, Any]], texts: List[Dict[str, Any]], ox: int, oy: int) -> str
- render_sheet · function · L429-L459 — def render_sheet(cands: List[Dict[str, Any]], geo_all: List[Dict[str, Any]], texts: List[Dict[str, Any]], path: Path | str, cols: int = 4) -> None
- _shape · function · L562-L569 — def _shape(g)
- render_review_html · function · L576-L602 — def render_review_html(cands, geo_all, texts, path, md5)
- run_equipment_blocks · function · L605-L635 — def run_equipment_blocks(folder: str | Path, out_dir: Optional[str | Path] = None) -> Dict[str, Any]
