# arh_ollama_client.py

- parse_json_3tier · function · L39-L139 — def parse_json_3tier(raw_text: str) -> Optional[Dict[str, Any]]
- ARHOllamaClient · class · L142-L335 — class ARHOllamaClient
- __init__ · method · L149-L160 — def __init__( self, base_url: str = _DEFAULT_OLLAMA_URL, timeout: float = _DEFAULT_TIMEOUT, max_retries: int = _DEFAULT_MAX_RETRIES )
- is_available · method · L162-L197 — def is_available(self, model_name: Optional[str] = None, cache_ttl: float = 10.0) -> bool
- list_models · method · L199-L203 — def list_models(self) -> List[str]
- generate · method · L205-L261 — def generate( self, model: str, prompt: str, system: Optional[str] = None, options: Optional[Dict[str, Any]] = None, images: Optional[List[str]] = None, timeout: Optional[float] = None ) -> Optional[str]
- generate_json · method · L263-L287 — def generate_json( self, model: str, prompt: str, system: Optional[str] = None, options: Optional[Dict[str, Any]] = None, images: Optional[List[str]] = None, timeout: Optional[float] = None ) -> Optional[Dict[str, Any]]
- embed · method · L289-L313 — def embed( self, model: str, prompt: str, timeout: Optional[float] = None ) -> List[float]
- post_completion · method · L315-L335 — def post_completion( self, url: str, payload: Dict[str, Any], timeout: Optional[float] = None ) -> Optional[Dict[str, Any]]
- get_ollama_client · function · L341-L346 — def get_ollama_client() -> ARHOllamaClient
