# pid_viewer.py

- _bez · function · L40-L47 — def _bez(p1, c1, c2, p2, n=6)
- extract_page · function · L50-L144 — def extract_page(page: "fitz.Page", sym_max: float = 30.0, equip_min: float = 30.0)
- find · function · L87-L91 — def find(a)
- best_page · function · L147-L148 — def best_page(doc: "fitz.Document") -> int
- analyse_pdf · function · L151-L157 — def analyse_pdf(path: str, page_no: int | None = None, snap_tol: float = 1.0) -> Tuple["fitz.Page", CircuitGraph]
- build_viewer · function · L192-L200 — def build_viewer(pdf: str, out_html: str, page_no: int | None = None, snap_tol: float = 1.0, zoom: float = 1.5) -> CircuitGraph
