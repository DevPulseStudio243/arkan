# arh_concordance_graph.py

- MultiDocumentConcordanceGraph · class · L17-L202 — class MultiDocumentConcordanceGraph
- __init__ · method · L20-L23 — def __init__(self)
- add_document · method · L25-L36 — def add_document(self, doc_name: str, doc_type: str = "GENERAL", metadata: Optional[Dict[str, Any]] = None)
- add_assertion · method · L38-L83 — def add_assertion( self, doc_name: str, equipment_tag: str, parameter_name: str, raw_value: Any, raw_unit: str = "", page: str = "", snippet: str = "", dimension_type: str = "pressure" )
- detect_discrepancies · method · L85-L185 — def detect_discrepancies(self, tolerance_pct: float = 2.0) -> List[Dict[str, Any]]
- export_concordance_matrix · method · L187-L202 — def export_concordance_matrix(self) -> Dict[str, Any]
