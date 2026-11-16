# lightrag_integration.py

- run_async · function · L23-L39 — def run_async(coro)
- DeerFlowLightRAG · class · L42-L165 — class DeerFlowLightRAG
- __init__ · method · L45-L48 — def __init__(self)
- _ensure_initialized · method · L50-L119 — def _ensure_initialized(self)
- disponible · method · L121-L130 — def disponible(self) -> bool
- ainsert_document · method · L132-L141 — async def ainsert_document(self, text: str) -> bool
- insert_document · method · L143-L147 — def insert_document(self, text: str) -> bool
- aquery · method · L149-L159 — async def aquery(self, question: str, mode: str = "hybrid") -> str
- query · method · L161-L165 — def query(self, question: str, mode: str = "hybrid") -> str
- get_lightrag · function · L168-L175 — def get_lightrag() -> DeerFlowLightRAG
