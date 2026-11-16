# symbol_rule_engine.py

- SymbolRuleEngine · class · L84-L216 — class SymbolRuleEngine
- __init__ · method · L89-L93 — def __init__(self, preset_name: str = "isa_5_1", custom_rules_file: Optional[str] = None)
- load_custom_rules · method · L95-L103 — def load_custom_rules(self, file_path: str)
- save_custom_preset · method · L105-L112 — def save_custom_preset(self, file_path: str)
- evaluate_symbols · method · L114-L216 — def evaluate_symbols( self, raw_lines: List[Tuple[Tuple[float, float], Tuple[float, float], Dict[str, Any]]], text_blocks: List[Dict[str, Any]] ) -> Dict[str, Any]
- apply_symbol_rules · function · L219-L227 — def apply_symbol_rules( raw_lines: List[Tuple[Tuple[float, float], Tuple[float, float], Dict[str, Any]]], text_blocks: List[Dict[str, Any]], preset_name: str = "isa_5_1", custom_rules_file: Optional[str] = None ) -> Dict[str, Any]
