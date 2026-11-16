# routes/planning_router.py

- verify_api_key · function · L16-L26 — async def verify_api_key()
- get_project_dir_path · function · L28-L35 — def get_project_dir_path(project_id: str) -> Path
- AIReportRequest · class · L43-L48 — class AIReportRequest(BaseModel)
- IndexPlanningRequest · class · L51-L56 — class IndexPlanningRequest(BaseModel)
- ComparePlanningRequest · class · L59-L61 — class ComparePlanningRequest(BaseModel)
- planning_list_stored · function · L69-L128 — async def planning_list_stored(api_key: str = Depends(verify_api_key))
- planning_load_stored · function · L132-L171 — async def planning_load_stored(path: str, api_key: str = Depends(verify_api_key))
- planning_delete_file · function · L175-L206 — async def planning_delete_file(path: str, api_key: str = Depends(verify_api_key))
- planning_analyze · function · L210-L251 — async def planning_analyze(file: UploadFile = File(...), api_key: str = Depends(verify_api_key))
- planning_ai_report · function · L255-L288 — async def planning_ai_report(req: AIReportRequest, lang: str = "fr", api_key: str = Depends(verify_api_key))
- planning_index · function · L292-L306 — async def planning_index(req: IndexPlanningRequest, api_key: str = Depends(verify_api_key))
- planning_index_list_all · function · L310-L318 — async def planning_index_list_all(api_key: str = Depends(verify_api_key))
- planning_index_list · function · L322-L330 — async def planning_index_list(project_id: str, api_key: str = Depends(verify_api_key))
- planning_compare · function · L334-L342 — async def planning_compare(req: ComparePlanningRequest, api_key: str = Depends(verify_api_key))
