# pipeline.py

- PipelineResponse · class · L30-L47 — class PipelineResponse
- OilGasPipeline · class · L54-L606 — class OilGasPipeline
- __init__ · method · L75-L81 — def __init__(self)
- _ensure_initialized · method · L83-L120 — def _ensure_initialized(self)
- process_query · method · L122-L363 — async def process_query(self, query: str, user_discipline: str = "", use_agent: bool = True) -> PipelineResponse
- _get_neo4j_context · method · L365-L408 — def _get_neo4j_context(self, query: str, equipment_tags: list, disciplines: list) -> str
- _process_with_agent · method · L410-L449 — async def _process_with_agent(self, query: str, discipline: str, response: PipelineResponse, start_time: float) -> PipelineResponse
- _call_llm · method · L451-L508 — async def _call_llm(self, system_prompt: str, user_prompt: str) -> str
- _get_kb_context · method · L510-L548 — def _get_kb_context(self, equipment_tags: list, disciplines: list) -> str
- _record_feedback · method · L550-L573 — def _record_feedback(self, query: str, response: PipelineResponse)
- submit_user_feedback · method · L575-L591 — def submit_user_feedback(self, query: str, answer: str, rating: str, correction: str = "", sources: list = None)
- get_system_status · method · L593-L606 — def get_system_status(self) -> dict
- get_pipeline · function · L613-L619 — def get_pipeline() -> OilGasPipeline
- ask · function · L621-L623 — async def ask(query: str, discipline: str = "") -> PipelineResponse
