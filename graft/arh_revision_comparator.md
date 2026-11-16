# arh_revision_comparator.py

- ARHRevisionComparator · class · L25-L317 — class ARHRevisionComparator
- __init__ · method · L30-L31 — def __init__(self)
- compare · method · L33-L240 — def compare( self, dossier_rev0: Dict[str, Any], dossier_rev1: Dict[str, Any] ) -> Dict[str, Any]
- _are_comments_matching · method · L242-L280 — def _are_comments_matching(self, c0: Dict[str, Any], c1: Dict[str, Any]) -> bool
- _generate_comparison_narrative · method · L282-L317 — def _generate_comparison_narrative( self, id0: str, id1: str, tag: str, eq_type: str, score0: float, score1: float, score_delta: float, resolved: int, persisting: int, new_cnt: int, rate: float, decision: str ) -> str
