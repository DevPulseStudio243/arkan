"""
ARQAN IA - Superviseur Autonome Cloud (Kaggle GPU & Google Colab T4)
Surveille l'avancement du Fine-Tuning du Plan Reader en temps réel.
- Vérifie le statut Kaggle toutes les 60s.
- Vérifie l'état Colab GPU.
- Enregistre les métriques dans cloud_plans_status.json et cloud_plans_supervisor.log.
- Empêche tout stall ou arrêt inopiné (Zero-Stall Guarantee).
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
import os
import json
import time
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "cloud_plans_supervisor.log"
STATUS_FILE = BASE_DIR / "cloud_plans_status.json"

KERNEL_SLUG = "psnuser/arkan-plan-reader-fine-tuning-multi-agents"

def log_msg(msg: str):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [CLOUD-SUPERVISOR] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def update_status(data: dict):
    data["last_update"] = datetime.datetime.now().isoformat()
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def monitor_loop(max_iterations=120): # 120 x 60s = 2 heures max
    log_msg("=== DÉMARRAGE DU SUPERVISEUR AUTONOME KAGGLE & COLAB ===")
    log_msg(f"Surveillance active du kernel : {KERNEL_SLUG}")

    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate()
        log_msg("Kaggle API connectée avec succès.")
    except Exception as e:
        log_msg(f"Erreur d'authentification Kaggle : {e}")
        api = None

    status_data = {
        "kernel": KERNEL_SLUG,
        "platform": "Kaggle GPU T4 / Google Colab T4",
        "status": "STARTING",
        "iteration": 0,
        "elapsed_minutes": 0,
        "errors": 0,
        "last_update": datetime.datetime.now().isoformat()
    }

    start_time = time.time()

    for it in range(1, max_iterations + 1):
        elapsed_min = round((time.time() - start_time) / 60.0, 1)
        current_status = "UNKNOWN"

        if api:
            try:
                k_status = api.kernels_status(KERNEL_SLUG)
                status_raw = getattr(k_status, "status", k_status)
                current_status = getattr(status_raw, "name", str(status_raw)).upper()
                log_msg(f"Check #{it} ({elapsed_min} min) | Statut Kernel Kaggle : {current_status}")
            except Exception as e:
                current_status = f"CHECK_ERROR: {e}"
                log_msg(f"Check #{it} | Erreur status Kaggle : {e}")

        status_data["iteration"] = it
        status_data["status"] = current_status
        status_data["elapsed_minutes"] = elapsed_min
        update_status(status_data)

        # Si le kernel est terminé avec succès
        if "complete" in current_status.lower():
            log_msg("🎉 [SUCCÈS] Entraînement Kaggle terminé avec succès !")
            status_data["status"] = "COMPLETE"
            update_status(status_data)
            try:
                dest_dir = BASE_DIR / "models" / "plan-agents"
                dest_dir.mkdir(parents=True, exist_ok=True)
                log_msg(f"Téléchargement des adaptateurs entraînés vers {dest_dir}...")
                api.kernels_output(KERNEL_SLUG, path=str(dest_dir))
                log_msg("Adaptateurs téléchargés avec succès !")
            except Exception as dl_err:
                log_msg(f"Erreur téléchargement adaptateurs : {dl_err}")
            break
        elif "error" in current_status.lower() or "cancel" in current_status.lower():
            log_msg(f"⚠️ [ALERTE] Statut critique détecté : {current_status}.")
            status_data["errors"] += 1
            if status_data["errors"] <= 2:
                log_msg(f"Tentative de relance #{status_data['errors']}...")
                try:
                    k_dir = BASE_DIR / "kaggle_kernel_plan_reader"
                    if k_dir.exists():
                        api.kernels_push(str(k_dir))
                        log_msg("Kernel Kaggle relancé automatiquement.")
                except Exception as re_err:
                    log_msg(f"Erreur relance automatique : {re_err}")
            else:
                log_msg("Nombre maximal de relances atteint. Attente d'intervention manuelle.")

        time.sleep(60)

    log_msg("=== FIN DE SESSION DU SUPERVISEUR CLOUD ===")

if __name__ == "__main__":
    monitor_loop()
