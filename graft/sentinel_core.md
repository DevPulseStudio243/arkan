# sentinel_core.py

- SentinelResponse · class · L25-L55 — class SentinelResponse
- to_dict · method · L38-L39 — def to_dict(self)
- to_display · method · L41-L55 — def to_display(self)
- SentinelCore · class · L87-L178 — class SentinelCore
- __init__ · method · L90-L92 — def __init__(self, model: str = SENTINEL_MODEL)
- _call_llm · method · L94-L109 — def _call_llm(self, prompt: str) -> str
- _parse_initial · method · L111-L122 — def _parse_initial(self, raw)
- _parse_challenge · method · L124-L135 — def _parse_challenge(self, raw, initial_answer)
- _confidence · method · L137-L140 — def _confidence(self, verdict, alerte)
- reason · method · L142-L169 — def reason(self, question: str, context: str, sources=None, causal_context: str = "") -> SentinelResponse
- close · method · L171-L172 — def close(self)
- __enter__ · method · L174-L175 — def __enter__(self)
- __exit__ · method · L177-L178 — def __exit__(self, *_)
- get_sentinel · function · L183-L187 — def get_sentinel() -> SentinelCore
