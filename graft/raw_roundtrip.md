# raw_roundtrip.py

- _attribs · function · L40-L47 — def _attribs(r: dict) -> dict
- rebuild_dxf · function · L50-L171 — def rebuild_dxf(raw: dict, out_path: str | Path, include_attribs: bool = True) -> Path
- _explode · function · L177-L195 — def _explode(entities, depth=0)
- _wcs_text_pos · function · L198-L203 — def _wcs_text_pos(e)
- _flat_length · function · L206-L208 — def _flat_length(e) -> float
- metrics · function · L211-L245 — def metrics(doc, spaces=None) -> dict
- _render · function · L248-L268 — def _render(doc, extents, png_path: Path, size_px=2400, ignore_text=False)
- raster_iou · function · L271-L300 — def raster_iou(orig_doc, rebuilt_doc, extents, out_png: Path, ignore_text=False) -> dict
- verify · function · L303-L360 — def verify(raw_path: str | Path, original_dxf: str | Path, out_dir: str | Path, raster: bool = True, tol_rel=1e-6, tol_ext=1e-3) -> dict
