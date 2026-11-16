# monitor.py

- AgentMetrics · class · L22-L61 — class AgentMetrics
- __init__ · method · L25-L32 — def __init__(self, agent_name: str, history_size: int = 100)
- record_call · method · L34-L43 — def record_call(self, duration_s: float, confidence: float = 1.0, error: str = None)
- get_stats · method · L45-L61 — def get_stats(self) -> Dict[str, Any]
- DeerFlowMonitor · class · L64-L138 — class DeerFlowMonitor
- __init__ · method · L70-L75 — def __init__(self)
- _get_or_create · method · L77-L80 — def _get_or_create(self, agent_name: str) -> AgentMetrics
- record_agent_call · method · L82-L100 — def record_agent_call(self, agent_name: str, duration_s: float, confidence: float = 1.0, error: str = None)
- record_pipeline · method · L102-L105 — def record_pipeline(self, duration_s: float)
- record_scada_alert · method · L107-L114 — def record_scada_alert(self, tag: str, status: str, value: Any)
- get_dashboard · method · L116-L133 — def get_dashboard(self) -> Dict[str, Any]
- get_scada_alerts · method · L135-L138 — def get_scada_alerts(self, limit: int = 20) -> List[Dict]
- _format_uptime · function · L141-L146 — def _format_uptime(seconds: float) -> str
- get_monitor · function · L154-L161 — def get_monitor() -> DeerFlowMonitor
