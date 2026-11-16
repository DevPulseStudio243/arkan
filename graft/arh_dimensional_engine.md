# arh_dimensional_engine.py

- ARHDimensionalEngine · class · L83-L214 — class ARHDimensionalEngine
- clean_unit_str · method · L87-L93 — def clean_unit_str(unit_str: str) -> str
- parse_value_with_unit · method · L96-L122 — def parse_value_with_unit(cls, text_fragment: str) -> Optional[Tuple[float, str]]
- convert_to_standard · method · L125-L156 — def convert_to_standard(cls, val: float, unit_str: str, dimension_type: str = "pressure") -> Optional[Tuple[float, str]]
- pressure_reference · method · L159-L166 — def pressure_reference(unit_str: str) -> Optional[str]
- physically_concordant · method · L169-L214 — def physically_concordant( cls, val1: float, unit1: str, val2: float, unit2: str, dimension_type: str = "pressure", tol_pct: float = 2.0 ) -> Tuple[bool, str]
