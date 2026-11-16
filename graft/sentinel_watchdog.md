# sentinel_watchdog.py

- SentinelAlert · class · L28-L40 — class SentinelAlert
- to_dict · method · L39-L40 — def to_dict(self)
- SentinelWatchdog · class · L43-L169 — class SentinelWatchdog
- __init__ · method · L49-L56 — def __init__(self)
- _load_alerts · method · L59-L66 — def _load_alerts(self)
- _save_alerts · method · L68-L75 — def _save_alerts(self)
- _new_alert_id · method · L78-L80 — def _new_alert_id(self) -> str
- add_alert · method · L82-L93 — def add_alert(self, niveau: str, titre: str, description: str, source: str, equipement: str = "", action: str = "") -> SentinelAlert
- get_active_alerts · method · L95-L98 — def get_active_alerts(self, max_n: int = 10) -> list[dict]
- acquitter · method · L100-L107 — def acquitter(self, alert_id: str) -> bool
- _scan_scada · method · L110-L112 — def _scan_scada(self)
- _scan_question_patterns · method · L115-L142 — def _scan_question_patterns(self)
- _run_loop · method · L145-L154 — def _run_loop(self)
- start · method · L156-L160 — def start(self)
- stop · method · L162-L163 — def stop(self)
- register_question · method · L165-L169 — def register_question(self, question: str)
- get_watchdog · function · L174-L179 — def get_watchdog() -> SentinelWatchdog
