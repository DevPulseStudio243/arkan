# tag_normalizer.py

- _clean · function · L43-L49 — def _clean(raw: Any) -> str
- _empty · function · L52-L54 — def _empty(canonical: str, raw: str) -> Dict[str, Any]
- TagNormalizer · class · L57-L166 — class TagNormalizer
- __init__ · method · L58-L70 — def __init__(self, config: Optional[Dict[str, Any]] = None)
- decompose_tag · method · L73-L99 — def decompose_tag(self, raw_tag: Any) -> Dict[str, Any]
- canonical_tag · method · L101-L103 — def canonical_tag(self, raw_tag: Any) -> str
- extract_tags · method · L105-L112 — def extract_tags(self, text: Any) -> List[str]
- match_tags · method · L115-L166 — def match_tags(self, tag1: Any, tag2: Any, threshold: float = 0.90) -> Tuple[bool, float, str]
- get_default_normalizer · function · L173-L177 — def get_default_normalizer(force_reload: bool = False) -> TagNormalizer
- normalize_tag · function · L180-L181 — def normalize_tag(tag: Any) -> str
- compare_tags · function · L184-L185 — def compare_tags(tag1: Any, tag2: Any, threshold: float = 0.90) -> Tuple[bool, float, str]
