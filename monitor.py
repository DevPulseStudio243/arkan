"""
DeerFlow V4 — monitor.py
Module de monitoring des agents en temps réel.
Collecte : temps de réponse, erreurs, scores de confiance, usage mémoire.
Thread-safe, zéro dépendance externe.
"""
import time
import logging
import threading
import json
from collections import deque
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

METRICS_FILE = Path("logs/agent_metrics.jsonl")
METRICS_FILE.parent.mkdir(exist_ok=True)

_lock = threading.Lock()

class AgentMetrics:
    """Collecteur de métriques pour un agent spécifique."""
    
    def __init__(self, agent_name: str, history_size: int = 100):
        self.agent_name = agent_name
        self._response_times: deque = deque(maxlen=history_size)
        self._error_count: int = 0
        self._success_count: int = 0
        self._confidence_scores: deque = deque(maxlen=history_size)
        self._last_called: Optional[float] = None
        self._last_error: Optional[str] = None

    def record_call(self, duration_s: float, confidence: float = 1.0, error: str = None):
        """Enregistre un appel à l'agent."""
        self._last_called = time.time()
        self._response_times.append(duration_s)
        if error:
            self._error_count += 1
            self._last_error = error
        else:
            self._success_count += 1
            self._confidence_scores.append(confidence)

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques de l'agent."""
        times = list(self._response_times)
        scores = list(self._confidence_scores)
        total = self._success_count + self._error_count
        return {
            "agent": self.agent_name,
            "total_calls": total,
            "success_rate": round(self._success_count / max(total, 1) * 100, 1),
            "error_count": self._error_count,
            "avg_response_s": round(sum(times) / max(len(times), 1), 2),
            "max_response_s": round(max(times, default=0), 2),
            "min_response_s": round(min(times, default=0), 2),
            "avg_confidence": round(sum(scores) / max(len(scores), 1), 3),
            "last_called": self._last_called,
            "last_error": self._last_error,
        }


class DeerFlowMonitor:
    """
    Moniteur global de DeerFlow.
    Collecte les métriques de tous les agents et du pipeline RAG.
    """
    
    def __init__(self):
        self._agents: Dict[str, AgentMetrics] = {}
        self._pipeline_times: deque = deque(maxlen=200)
        self._scada_alerts: List[Dict] = []
        self._start_time = time.time()
        logger.info("[Monitor] DeerFlow Monitor initialisé.")

    def _get_or_create(self, agent_name: str) -> AgentMetrics:
        if agent_name not in self._agents:
            self._agents[agent_name] = AgentMetrics(agent_name)
        return self._agents[agent_name]

    def record_agent_call(self, agent_name: str, duration_s: float, 
                          confidence: float = 1.0, error: str = None):
        """Enregistre un appel agent."""
        with _lock:
            m = self._get_or_create(agent_name)
            m.record_call(duration_s, confidence, error)
            # Persister en JSONL pour analyse ultérieure
            try:
                entry = {
                    "ts": time.time(),
                    "agent": agent_name,
                    "duration_s": round(duration_s, 3),
                    "confidence": round(confidence, 3),
                    "error": error,
                }
                with open(METRICS_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass

    def record_pipeline(self, duration_s: float):
        """Enregistre la durée totale d'un pipeline RAG."""
        with _lock:
            self._pipeline_times.append(duration_s)

    def record_scada_alert(self, tag: str, status: str, value: Any):
        """Enregistre une alarme SCADA pour le webhook."""
        with _lock:
            alert = {"ts": time.time(), "tag": tag, "status": status, "value": str(value)}
            self._scada_alerts.append(alert)
            if len(self._scada_alerts) > 100:
                self._scada_alerts = self._scada_alerts[-100:]
            logger.warning("[Monitor] SCADA ALERTE : %s → %s = %s", tag, status, value)

    def get_dashboard(self) -> Dict[str, Any]:
        """Retourne le tableau de bord complet du monitoring."""
        with _lock:
            uptime_s = time.time() - self._start_time
            pipeline_times = list(self._pipeline_times)
            return {
                "uptime_seconds": round(uptime_s, 0),
                "uptime_human": _format_uptime(uptime_s),
                "pipeline": {
                    "total_requests": len(pipeline_times),
                    "avg_response_s": round(sum(pipeline_times) / max(len(pipeline_times), 1), 2),
                    "p95_response_s": round(sorted(pipeline_times)[int(len(pipeline_times)*0.95)] 
                                           if len(pipeline_times) > 10 else 0, 2),
                },
                "agents": [m.get_stats() for m in self._agents.values()],
                "scada_alerts_recent": self._scada_alerts[-10:],
                "timestamp": time.time(),
            }

    def get_scada_alerts(self, limit: int = 20) -> List[Dict]:
        """Retourne les dernières alarmes SCADA."""
        with _lock:
            return list(reversed(self._scada_alerts[-limit:]))


def _format_uptime(seconds: float) -> str:
    """Formate la durée en format lisible."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}h {m}m {s}s"


# ── Singleton ──────────────────────────────────────────────
_monitor_instance: Optional[DeerFlowMonitor] = None
_monitor_lock = threading.Lock()


def get_monitor() -> DeerFlowMonitor:
    """Retourne le singleton DeerFlowMonitor (thread-safe)."""
    global _monitor_instance
    if _monitor_instance is None:
        with _monitor_lock:
            if _monitor_instance is None:
                _monitor_instance = DeerFlowMonitor()
    return _monitor_instance
