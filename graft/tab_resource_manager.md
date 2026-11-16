# tab_resource_manager.py

- TabResourceManager · class · L105-L243 — class TabResourceManager
- __init__ · method · L108-L109 — def __init__(self)
- get_memory_metrics · method · L111-L128 — def get_memory_metrics(self) -> Dict[str, Any]
- get_running_ollama_models · method · L130-L141 — def get_running_ollama_models(self) -> List[str]
- unload_unneeded_ollama_models · method · L143-L165 — def unload_unneeded_ollama_models(self, allowed_models: List[str]) -> List[str]
- kill_nuextract_process_if_present · method · L167-L185 — def kill_nuextract_process_if_present(self) -> bool
- perform_garbage_collection · method · L187-L196 — def perform_garbage_collection(self)
- activate_tab · method · L198-L243 — def activate_tab(self, tab_name: str) -> Dict[str, Any]
