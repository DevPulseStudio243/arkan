# routes/vault_router.py

- AgentMemoryCreate · class · L14-L18 — class AgentMemoryCreate(BaseModel)
- get_vault_status · function · L22-L35 — async def get_vault_status()
- trigger_vault_sync · function · L39-L46 — async def trigger_vault_sync()
- get_vault_graph · function · L50-L56 — async def get_vault_graph()
- get_vault_note · function · L60-L70 — async def get_vault_note(path: str = Query(..., description="Chemin relatif ou identifiant de la note"))
- create_agent_memory_note · function · L74-L86 — async def create_agent_memory_note(payload: AgentMemoryCreate)
- open_vault_in_os · function · L90-L92 — async def open_vault_in_os()
