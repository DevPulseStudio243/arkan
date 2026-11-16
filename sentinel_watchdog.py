"""
SENTINEL-OG — Couche 3 : Vigilance Proactive
=============================================
Thread de fond qui surveille les patterns et genere des alertes
avant que l utilisateur pose la question.

Sources de surveillance :
  1. SCADA simulator (derive de capteurs > 10%)
  2. Historique des questions (patterns repetitifs)
  3. Alertes manuelles depuis l API
"""

import time
import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger("sentinel_watchdog")

ALERTS_FILE = Path(__file__).parent / "sentinel_alerts.json"
SCAN_INTERVAL_S = 60  # Verification toutes les 60 secondes

@dataclass
class SentinelAlert:
    id:          str
    niveau:      str        # FAIBLE | MOYEN | ELEVE | CRITIQUE
    titre:       str
    description: str
    source:      str        # SCADA | PATTERN | MANUEL
    equipement:  str = ""
    action:      str = ""
    timestamp:   str = field(default_factory=lambda: datetime.now().isoformat())
    acquittee:   bool = False

    def to_dict(self):
        return asdict(self)


class SentinelWatchdog:
    """
    Chien de garde proactif de Sentinel-OG.
    Tourne en thread de fond et genere des alertes automatiquement.
    """

    def __init__(self):
        self._alerts: list[SentinelAlert] = []
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._question_history: list[str] = []
        self._alert_counter = 0
        self._load_alerts()

    # ── Persistance ─────────────────────────────────────────────────────────────
    def _load_alerts(self):
        if ALERTS_FILE.exists():
            try:
                data = json.loads(ALERTS_FILE.read_text(encoding="utf-8"))
                self._alerts = [SentinelAlert(**a) for a in data]
                logger.info(f"[Watchdog] {len(self._alerts)} alertes chargees.")
            except Exception as e:
                logger.warning(f"[Watchdog] Impossible de charger les alertes: {e}")

    def _save_alerts(self):
        try:
            ALERTS_FILE.write_text(
                json.dumps([a.to_dict() for a in self._alerts[-200:]], indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"[Watchdog] Sauvegarde alertes echouee: {e}")

    # ── Gestion des alertes ──────────────────────────────────────────────────────
    def _new_alert_id(self) -> str:
        self._alert_counter += 1
        return f"SG-{datetime.now().strftime('%Y%m%d')}-{self._alert_counter:04d}"

    def add_alert(self, niveau: str, titre: str, description: str,
                  source: str, equipement: str = "", action: str = "") -> SentinelAlert:
        alert = SentinelAlert(
            id=self._new_alert_id(), niveau=niveau, titre=titre,
            description=description, source=source,
            equipement=equipement, action=action
        )
        with self._lock:
            self._alerts.insert(0, alert)
            self._save_alerts()
        logger.info(f"[Watchdog] ALERTE {alert.niveau}: {alert.titre}")
        return alert

    def get_active_alerts(self, max_n: int = 10) -> list[dict]:
        with self._lock:
            actives = [a for a in self._alerts if not a.acquittee]
            return [a.to_dict() for a in actives[:max_n]]

    def acquitter(self, alert_id: str) -> bool:
        with self._lock:
            for a in self._alerts:
                if a.id == alert_id:
                    a.acquittee = True
                    self._save_alerts()
                    return True
        return False

    # ── Surveillance SCADA ───────────────────────────────────────────────────────
    def _scan_scada(self):
        """Surveillance SCADA désactivée (Focus Ingénierie)."""
        pass

    # ── Surveillance patterns de questions ───────────────────────────────────────
    def _scan_question_patterns(self):
        """Detecte si les memes sujets sont poses plusieurs fois (signe de probleme)."""
        if len(self._question_history) < 3:
            return

        recent = self._question_history[-10:]
        keywords = {}
        for q in recent:
            words = q.lower().split()
            for w in words:
                if len(w) > 4:
                    keywords[w] = keywords.get(w, 0) + 1

        # Déduplication : ne pas créer d'alerte si elle existe déjà pour ce mot-clé
        existing_keys = {a.titre for a in self._alerts if not a.acquittee}
        for kw, count in keywords.items():
            if count >= 3:
                titre_alerte = f"Pattern repetitif detecte : '{kw}'"
                if titre_alerte in existing_keys:
                    break  # Alerte déjà active pour ce pattern
                self.add_alert(
                    niveau      = "MOYEN",
                    titre       = titre_alerte,
                    description = f"Le terme '{kw}' apparait {count} fois dans les {len(recent)} dernieres questions. Cela peut indiquer un probleme persistant non resolu.",
                    source      = "PATTERN",
                    action      = "Verifier si le probleme sous-jacent a ete resolu."
                )
                break  # Une seule alerte de pattern par scan

    # ── Thread principal ─────────────────────────────────────────────────────────
    def _run_loop(self):
        logger.info("[Watchdog] Surveillance proactive demarree.")
        while self._running:
            try:
                self._scan_scada()
                self._scan_question_patterns()
            except Exception as e:
                logger.error(f"[Watchdog] Erreur scan: {e}")
            time.sleep(SCAN_INTERVAL_S)
        logger.info("[Watchdog] Surveillance arretee.")

    def start(self):
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="SentinelWatchdog")
            self._thread.start()

    def stop(self):
        self._running = False

    def register_question(self, question: str):
        """Appeler a chaque nouvelle question utilisateur pour le scan de patterns."""
        self._question_history.append(question)
        if len(self._question_history) > 100:
            self._question_history = self._question_history[-50:]


_watchdog_instance: Optional[SentinelWatchdog] = None

def get_watchdog() -> SentinelWatchdog:
    global _watchdog_instance
    if _watchdog_instance is None:
        _watchdog_instance = SentinelWatchdog()
        _watchdog_instance.start()
    return _watchdog_instance


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    wg = SentinelWatchdog()
    
    # Simuler des questions repetitives
    for q in ["probleme pression T-201", "alarme pression separateur",
              "T-201 pression haute", "que faire pression T-201"]:
        wg.register_question(q)
    
    wg._scan_question_patterns()
    wg._scan_scada()
    
    alerts = wg.get_active_alerts()
    print("\n=== " + str(len(alerts)) + " ALERTE(S) ACTIVE(S) ===")
    for a in alerts:
        print("[" + a["niveau"] + "] " + a["titre"])
        print("  " + a["description"])
        print("  Action : " + a["action"])
        print()
