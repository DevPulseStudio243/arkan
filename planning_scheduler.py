"""
ARKAN — Intelligence EPC & Réglementaire Oil & Gas
Module: planning_scheduler.py
Job périodique d'auto-apprentissage et de recalibrage continu des rendements
à partir des retours d'expérience et plannings réels validés.
"""

import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from planning_knowledge_db import planning_db
from planning_generation_engine import planning_rag

logger = logging.getLogger("arkan.planning_scheduler")

_scheduler: BackgroundScheduler = None


def run_recalibration_job():
    """Exécute le cycle de recalibrage et met à jour l'index RAG."""
    try:
        logger.info("[PlanningScheduler] Démarrage du cycle de recalibrage des rendements...")
        recalibrated = planning_db.recalibrate_yields_batch()
        if recalibrated > 0:
            # Réindexation de l'index BM25 et du cache
            planning_rag.refresh_index()
            logger.info(f"[PlanningScheduler] Cycle achevé : {recalibrated} rendements ajustés et index RAG rafraîchi.")
        else:
            logger.info("[PlanningScheduler] Aucun nouveau retour de chantier nécessitant un ajustement.")
    except Exception as e:
        logger.error(f"[PlanningScheduler] Erreur pendant le cycle de recalibrage : {e}")


def init_planning_scheduler(interval_hours: int = 24) -> BackgroundScheduler:
    """Initialise et démarre le scheduler de recalibrage continu."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        run_recalibration_job,
        trigger=IntervalTrigger(hours=interval_hours),
        id="planning_recalibration_job",
        name="Recalibrage des rendements EPC",
        replace_existing=True,
        next_run_time=datetime.now()  # Exécute un premier passage
    )
    _scheduler.start()
    logger.info(f"[PlanningScheduler] Scheduler actif (intervalle: {interval_hours}h).")
    return _scheduler
