"""
DeerFlow V4 — scada_simulator.py
Simulateur SCADA avec historique des mesures pour l'analyse de tendance.
"""
import random
import time
from datetime import datetime
from collections import deque
from typing import Dict, List

_HISTORY_SIZE = 50  # Nombre de mesures historisées par tag

class ScadaSimulator:
    """Simulateur de données temps réel SCADA avec historique pour trending."""
    
    def __init__(self):
        self.profiles = {
            "P-101":  {"type": "Pump",   "pressure_out_bar": 15.0, "vibration_mm_s": 2.5, "temp_c": 45.0},
            "P-101A": {"type": "Pump",   "pressure_out_bar": 15.0, "vibration_mm_s": 2.3, "temp_c": 46.0},
            "V-200":  {"type": "Vessel", "level_pct": 50.0,        "pressure_bar": 5.0,   "temp_c": 80.0},
            "XV-101": {"type": "Valve",  "position_pct": 100.0,    "flow_m3_h": 120.0},
        }
        # Historique des mesures : {tag: deque([{ts, key, value}, ...])}
        self._history: Dict[str, deque] = {}

    def get_live_data(self, tag: str) -> dict:
        """Retourne des données simulées pour un équipement spécifique."""
        tag = tag.upper()
        
        if tag not in self.profiles:
            if tag.startswith("P"):
                base = {"type": "Pump", "pressure_out_bar": random.uniform(10, 20), "vibration_mm_s": random.uniform(1, 5)}
            elif tag.startswith("V") and not tag.startswith("XV") and not tag.startswith("LV"):
                base = {"type": "Vessel", "level_pct": random.uniform(20, 80), "pressure_bar": random.uniform(2, 10)}
            elif tag.endswith("V") or tag.startswith("XV"):
                base = {"type": "Valve", "position_pct": random.choice([0.0, 100.0]), "flow_m3_h": random.uniform(0, 150)}
            else:
                base = {"type": "General_Equipment", "status": "Running", "temp_c": random.uniform(20, 90)}
        else:
            base = self.profiles[tag].copy()
            for k, v in base.items():
                if isinstance(v, (float, int)):
                    variation = v * 0.05
                    base[k] = round(v + random.uniform(-variation, variation), 2)
        
        base["timestamp"] = datetime.now().isoformat()
        base["tag"] = tag
        base["status"] = "OK" if random.random() > 0.1 else "WARNING"
        
        # Stocker dans l'historique
        ts = time.time()
        if tag not in self._history:
            self._history[tag] = deque(maxlen=_HISTORY_SIZE)
        for k, v in base.items():
            if isinstance(v, (float, int)) and k not in ("timestamp",):
                self._history[tag].append({"ts": ts, "key": k, "value": v})
        
        # Notifier le monitor si alarme
        if base["status"] == "WARNING":
            try:
                from monitor import get_monitor
                get_monitor().record_scada_alert(tag, "WARNING", base)
            except Exception:
                pass
        
        return base

    def get_trend(self, tag: str, metric: str, last_n: int = 20) -> Dict:
        """
        Retourne l'analyse de tendance pour une métrique d'un équipement.
        Calcule la moyenne, le min, le max et la dérive sur les N dernières mesures.
        """
        tag = tag.upper()
        if tag not in self._history:
            # Générer quelques points d'historique simulés
            self.get_live_data(tag)
            for _ in range(min(last_n, 15)):
                self.get_live_data(tag)
        
        hist = self._history.get(tag, deque())
        points = [h["value"] for h in hist if h["key"] == metric][-last_n:]
        
        if not points:
            return {"error": f"Métrique '{metric}' non disponible pour {tag}"}
        
        avg = sum(points) / len(points)
        trend = "STABLE"
        drift_pct = 0.0
        
        if len(points) >= 5:
            first_half = points[:len(points)//2]
            second_half = points[len(points)//2:]
            avg_first = sum(first_half) / len(first_half)
            avg_second = sum(second_half) / len(second_half)
            if avg_first != 0:
                drift_pct = round((avg_second - avg_first) / abs(avg_first) * 100, 2)
                if drift_pct > 5:
                    trend = "HAUSSE ⬆"
                elif drift_pct < -5:
                    trend = "BAISSE ⬇"
        
        return {
            "tag": tag,
            "metric": metric,
            "samples": len(points),
            "avg": round(avg, 3),
            "min": round(min(points), 3),
            "max": round(max(points), 3),
            "latest": round(points[-1], 3),
            "trend": trend,
            "drift_pct": drift_pct,
            "alert": "⚠ DÉRIVE SIGNIFICATIVE" if abs(drift_pct) > 10 else "Normal",
        }

    def get_all_live(self, tags: List[str] = None) -> List[Dict]:
        """Retourne les données live de plusieurs tags (pour le dashboard)."""
        target_tags = tags or list(self.profiles.keys())
        return [self.get_live_data(t) for t in target_tags]


# ── Singleton ───────────────────────────────────────────────
_simulator = ScadaSimulator()

def get_live_tag_data(tag: str) -> dict:
    """Point d'entrée principal pour les outils agents."""
    return _simulator.get_live_data(tag)

def get_trend_data(tag: str, metric: str, last_n: int = 20) -> dict:
    """Analyse de tendance pour un tag + métrique."""
    return _simulator.get_trend(tag, metric, last_n)

def get_dashboard_data(tags: List[str] = None) -> List[Dict]:
    """Données pour le dashboard SCADA."""
    return _simulator.get_all_live(tags)

if __name__ == "__main__":
    print(get_live_tag_data("P-101"))
    print(get_trend_data("P-101", "vibration_mm_s"))
