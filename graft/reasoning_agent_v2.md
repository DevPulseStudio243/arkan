# reasoning_agent_v2.py

- convert_to_ollama_tools · function · L31-L56 — def convert_to_ollama_tools(tool_names: list[str]) -> list[dict]
- BaseQwenAgent · class · L104-L183 — class BaseQwenAgent
- __init__ · method · L107-L111 — def __init__(self, system_prompt: str, allowed_tool_names: list[str] = None)
- _execute_tool · method · L113-L123 — def _execute_tool(self, tool_name: str, arguments: dict) -> str
- call_llm · method · L125-L183 — def call_llm(self, user_query: str, response_format=None) -> str
- MasterOrchestrator · class · L188-L246 — class MasterOrchestrator
- __init__ · method · L191-L198 — def __init__(self)
- run · method · L200-L246 — def run(self, query: str) -> dict
- ReasoningAgent · class · L249-L273 — class ReasoningAgent
- __init__ · method · L250-L251 — def __init__(self, model: str = None, max_iterations: int = 6)
- run · method · L253-L273 — def run(self, query: str, discipline: str = ""): # Compatibility with old interface # Returns an object that has `.answer` at least. # En production, on devrait retourner un vrai AgentResult
- AgentResult · class · L259-L264 — class AgentResult
