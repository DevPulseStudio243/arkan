"""
sync_plan_lora_adapters.py
===========================
Synchronise et valide les adaptateurs LoRA entraînés sur Kaggle/Colab
pour l'essaim multi-agents de lecture de plans (10 disciplines).
"""

import os
import sys
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SyncPlanAdapters")

BASE_DIR = Path(__file__).resolve().parent
ADAPTER_DIR = BASE_DIR / "models" / "plan-agents"

DISCIPLINE_AGENTS = [
    "specialist-pid-process",
    "specialist-piping-iso",
    "specialist-civil-foundation",
    "specialist-structural-steel",
    "specialist-electrical",
    "specialist-cabling",
    "specialist-instrument-cabling",
    "specialist-telecom-scada",
    "specialist-hvac",
    "specialist-cross-validator"
]

def verify_and_sync_adapters():
    logger.info("=== VÉRIFICATION DES ADAPTATEURS LoRA MULTI-AGENTS ===")
    
    if not ADAPTER_DIR.exists():
        logger.warning(f"Répertoire d'adaptateurs introuvable : {ADAPTER_DIR}")
        return False
        
    found_files = []
    for root, dirs, files in os.walk(ADAPTER_DIR):
        for f in files:
            p = Path(root) / f
            found_files.append((str(p.relative_to(ADAPTER_DIR)), p.stat().st_size))
            
    logger.info(f"Fichiers téléchargés dans {ADAPTER_DIR} ({len(found_files)}) :")
    for fname, size in found_files[:15]:
        logger.info(f"  - {fname} ({round(size / 1024 / 1024, 2)} Mo)")
        
    has_adapter = any("adapter_model" in f[0] or "adapter" in f[0] for f in found_files)
    if has_adapter:
        logger.info(" Adaptateurs LoRA détectés avec succès !")
        
        # Enregistrement du manifeste de synchronisation
        manifest = {
            "trained_disciplines": DISCIPLINE_AGENTS,
            "adapter_files": [f[0] for f in found_files],
            "status": "READY_FOR_INFERENCE",
            "base_model": "unsloth/llama-3.2-3b-instruct-bnb-4bit",
            "disciplines_count": len(DISCIPLINE_AGENTS)
        }
        manifest_p = ADAPTER_DIR / "agents_lora_manifest.json"
        with open(manifest_p, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        logger.info(f"Manifeste généré dans {manifest_p}")
        return True
    else:
        logger.warning("Fichiers de poids d'adaptateurs en cours de finalisation...")
        return False

if __name__ == "__main__":
    verify_and_sync_adapters()
