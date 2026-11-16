# tool_maker.py

- _ensure_dynamic_tools_file · function · L25-L34 — def _ensure_dynamic_tools_file()
- SecurityNodeVisitor · class · L37-L63 — class SecurityNodeVisitor(ast.NodeVisitor)
- __init__ · method · L40-L43 — def __init__(self)
- visit_Import · method · L45-L50 — def visit_Import(self, node)
- visit_ImportFrom · method · L52-L57 — def visit_ImportFrom(self, node)
- visit_Call · method · L59-L63 — def visit_Call(self, node)
- is_code_safe · function · L66-L86 — def is_code_safe(code: str) -> Tuple[bool, str]
- tool_create_tool · function · L89-L128 — def tool_create_tool(tool_name: str, description: str, python_code: str, params: list[str]) -> str
- get_dynamic_tools · function · L131-L166 — def get_dynamic_tools() -> Dict[str, Dict[str, Any]]
