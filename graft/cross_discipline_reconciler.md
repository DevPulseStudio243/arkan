# cross_discipline_reconciler.py

- _a · function · L35-L39 — def _a(check, severity, tag, title, message, norm, reco, status="PROPOSED", **extra)
- CrossDisciplineReconciler · class · L42-L276 — class CrossDisciplineReconciler
- __init__ · method · L43-L55 — def __init__(self, config: Optional[Dict[str, Any]] = None, normalizer: Optional[TagNormalizer] = None)
- _match · method · L58-L64 — def _match(self, tag: Any, candidates: List[Dict[str, Any]], key: str = "tag") -> Tuple[Optional[Dict[str, Any]], float, str]
- _not_evaluated · method · L66-L68 — def _not_evaluated(self, out: List[Dict[str, Any]], check: str, title: str, why: str, reco: str) -> None
- reconcile_all · method · L71-L90 — def reconcile_all( self, piping_items: Optional[List[Dict[str, Any]]] = None, sld_feeders: Optional[List[Dict[str, Any]]] = None, routing_items: Optional[List[Dict[str, Any]]] = None, earthing_items: Optional[List[Dict[str, Any]]] = None, pid_equipment: Optional[List[Dict[str, Any]]] = None, cable_list: Optional[List[Dict[str, Any]]] = None, panels: Optional[List[Dict[str, Any]]] = None, ) -> List[Dict[str, Any]]
- _cross_01 · method · L93-L114 — def _cross_01(self, out, piping_items, pid)
- _cross_02 · method · L117-L142 — def _cross_02(self, out, feeders, pid)
- _cross_03 · method · L145-L175 — def _cross_03(self, out, feeders, cable_list)
- _cross_04 · method · L178-L192 — def _cross_04(self, out, routing_items, cable_list)
- _cross_05 · method · L195-L222 — def _cross_05(self, out, earthing_items, pid)
- _cross_06 · method · L225-L256 — def _cross_06(self, out, routing_items, cable_list)
- _cross_07 · method · L259-L276 — def _cross_07(self, out, feeders, panels, pid)
- run_cross_discipline_reconciliation · function · L279-L300 — def run_cross_discipline_reconciliation( piping_items: Optional[List[Dict[str, Any]]] = None, sld_feeders: Optional[List[Dict[str, Any]]] = None, routing_items: Optional[List[Dict[str, Any]]] = None, earthing_items: Optional[List[Dict[str, Any]]] = None, pid_equipment: Optional[List[Dict[str, Any]]] = None, cable_list: Optional[List[Dict[str, Any]]] = None, panels: Optional[List[Dict[str, Any]]] = None, config: Optional[Dict[str, Any]] = None, normalizer: Optional[TagNormalizer] = None ) -> List[Dict[str, Any]]
