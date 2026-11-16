# multi_agent_orchestrator.py

- SwarmBlackboard · class · L42-L58 — class SwarmBlackboard
- __init__ · method · L44-L46 — def __init__(self)
- store · method · L48-L50 — def store(self, key: str, value: Any, agent: str)
- get_summary · method · L52-L58 — def get_summary(self) -> str
- OrchestratorStep · class · L62-L68 — class OrchestratorStep
- OrchestratorResult · class · L72-L83 — class OrchestratorResult
- convert_to_ollama_tools · function · L89-L114 — def convert_to_ollama_tools(tool_names: list) -> list
- BaseQwenAgent · class · L251-L350 — class BaseQwenAgent
- __init__ · method · L254-L259 — def __init__(self, system_prompt: str, allowed_tool_names: list = None)
- _execute_tool · method · L261-L283 — def _execute_tool(self, tool_name: str, arguments: Any) -> str
- call_llm · method · L286-L350 — def call_llm(self, user_query: str, response_format=None) -> str
- MasterOrchestrator · class · L355-L563 — class MasterOrchestrator
- __init__ · method · L358-L372 — def __init__(self)
- run · method · L374-L563 — def run(self, query: str, discipline: str = "") -> OrchestratorResult
- MultiAgentReasoningAgent · class · L568-L605 — class MultiAgentReasoningAgent
- __init__ · method · L575-L579 — def __init__(self, model: str = None, max_iterations: int = 6)
- run · method · L581-L605 — def run(self, query: str, discipline: str = "")
- get_reasoning_agent · function · L611-L618 — def get_reasoning_agent() -> MultiAgentReasoningAgent
