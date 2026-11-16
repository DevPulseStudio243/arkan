# arh_model_router.py

- ARHPartClassifier · class · L136-L165 — class ARHPartClassifier
- classify · method · L139-L155 — def classify(self, text: str) -> str
- classify_all · method · L157-L165 — def classify_all(self, text: str) -> List[tuple]
- ARHLanguageDetector · class · L172-L193 — class ARHLanguageDetector
- detect · method · L184-L193 — def detect(self, text: str) -> str
- ARHModelDispatcher · class · L200-L313 — class ARHModelDispatcher
- __init__ · method · L203-L207 — def __init__(self, base_url: str = OLLAMA_BASE_URL, timeout: int = OLLAMA_TIMEOUT)
- _get_available_models · method · L209-L216 — def _get_available_models(self) -> set
- select_model · method · L218-L230 — def select_model(self, part: str, language: str = "FR") -> str
- call_ollama · method · L232-L247 — def call_ollama(self, model: str, prompt: str, system: str = "") -> Optional[str]
- analyze · method · L249-L313 — def analyze(self, text: str, part: str, language: str = "FR", instruction_override: str = "") -> Optional[Dict[str, Any]]
- ARHModelRouter · class · L320-L439 — class ARHModelRouter
- __init__ · method · L327-L330 — def __init__(self, base_url: str = OLLAMA_BASE_URL)
- route_and_analyze · method · L332-L378 — def route_and_analyze( self, text: str, part_hint: Optional[str] = None, lang_hint: Optional[str] = None, multi_part: bool = False, ) -> Dict[str, Any]
- _merge_results · method · L380-L424 — def _merge_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]
- _empty_result · method · L426-L432 — def _empty_result(self) -> Dict[str, Any]
- get_available_models · method · L434-L439 — def get_available_models(self) -> Dict[str, str]
- get_arh_router · function · L448-L454 — def get_arh_router() -> ARHModelRouter
