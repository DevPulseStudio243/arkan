# dwg_converter.py

- DWGConversionError · class · L37-L38 — class DWGConversionError(RuntimeError)
- _find_libredwg · function · L44-L57 — def _find_libredwg() -> str
- _find_acme_converter · function · L60-L65 — def _find_acme_converter() -> str
- _find_accoreconsole · function · L68-L73 — def _find_accoreconsole() -> str
- _find_oda_converter · function · L76-L81 — def _find_oda_converter() -> str
- cache_dir · function · L87-L91 — def cache_dir() -> Path
- _md5 · function · L94-L99 — def _md5(path: Path) -> str
- _timeout_for · function · L102-L107 — def _timeout_for(dwg: Path) -> int
- validate_dxf · function · L110-L129 — def validate_dxf(path: Path | str, min_entities: int = 1) -> bool
- _version_digits · function · L132-L134 — def _version_digits(out_version: str) -> str
- _engine_libredwg · function · L140-L150 — def _engine_libredwg(dwg: Path, out: Path, out_version: str, timeout: int) -> None
- _engine_acme · function · L153-L158 — def _engine_acme(dwg: Path, out: Path, out_version: str, timeout: int) -> None
- _engine_accore · function · L161-L169 — def _engine_accore(dwg: Path, out: Path, out_version: str, timeout: int) -> None
- _engine_oda · function · L172-L182 — def _engine_oda(dwg: Path, out: Path, out_version: str, timeout: int) -> None
- _engine_com · function · L185-L187 — def _engine_com(dwg: Path, out: Path, out_version: str, timeout: int) -> None
- convert_dwg_to_dxf · function · L200-L244 — def convert_dwg_to_dxf(dwg_path: str, output_dxf_path: Optional[str] = None, out_version: str = "ACAD2018") -> str
- _deliver · function · L247-L253 — def _deliver(cached: Path, target: Path) -> str
- ensure_dxf · function · L256-L263 — def ensure_dxf(path: str) -> str
