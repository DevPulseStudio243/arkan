"""
ARKAN — Dynamic Tab-Level Memory Isolation & Resource Manager
Module: tab_resource_manager.py
Description: Active dynamiquement les composants nécessaires pour chaque onglet (Chat, Planning,
ARH, MTO, etc.) et désactive/décharge immédiatement les modèles IA et processus inutilisés
dès que l'utilisateur bascule vers un autre onglet, maintenant ainsi une consommation RAM minimale.
"""

import os
import gc
import logging
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False
import httpx
from typing import Dict, List, Any, Optional

logger = logging.getLogger("arkan.resource_manager")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Spécification stricte des ressources par onglet
TAB_RESOURCES: Dict[str, Dict[str, Any]] = {
    "chat": {
        "models": ["arkan-planning", "arkan-planning:latest"],
        "category": "ai_text",
        "description": "Assistant conversationnel EPC & RAG"
    },
    "dashboard": {
        "models": [],
        "category": "light_data",
        "description": "Tableau de bord synthétique (zéro LLM en mémoire)"
    },
    "scada": {
        "models": [],
        "category": "telemetry",
        "description": "Supervision SCADA & Audit Sentinel (moteur règles local)"
    },
    "projects": {
        "models": [],
        "category": "light_data",
        "description": "Consultation des projets & équipements"
    },
    "verification": {
        "models": [],
        "category": "light_data",
        "description": "Contrôle de cohérence & anomalies"
    },
    "mto": {
        "models": [],
        "category": "calculation",
        "description": "Calculateur de métrés & nomenclatures MTO (moteur regex/tableau)"
    },
    "traceability": {
        "models": [],
        "category": "database",
        "description": "Suivi des spools, soudures et certificats matière"
    },
    "procurement": {
        "models": [],
        "category": "database",
        "description": "Gestion des commandes & stock chantier"
    },
    "arh": {
        "models": ["arkan-arh-14b", "arkan-arh-3b", "arkan-arh-14b:latest", "arkan-arh-3b:latest"],
        "category": "ai_regulatory",
        "description": "Expertise réglementaire ARH Sonatrach"
    },
    "agents": {
        "models": [],
        "category": "orchestration",
        "description": "Architecture et constellation d'agents"
    },
    "planning": {
        "models": [],
        "category": "planning_cpm",
        "description": "Audit DCMA 14-Points des plannings Primavera XER (moteur algorithmique pur)"
    },
    "planning-ia": {
        "models": ["arkan-planning", "arkan-planning:latest"],
        "category": "ai_planning",
        "description": "Swarm Multi-Agents de génération WBS & rendements"
    },
    "pid": {
        "models": ["qwen2.5vl:3b", "qwen2.5vl:3b:latest"],
        "category": "ai_vision",
        "description": "Vision par ordinateur pour schémas P&ID"
    },
    "pid-generator": {
        "models": ["qwen2.5:7b", "qwen2.5:latest"],
        "category": "ai_synthesis",
        "description": "Générateur synthétique de P&ID et schémas tuyauterie normalisés"
    },
    "codebase": {
        "models": [],
        "category": "graph_viz",
        "description": "Cartographie interactive du code source (Graft)"
    }
}


class TabResourceManager:
    """Gestionnaire de mémoire vive et d'isolation des ressources par onglet."""

    def __init__(self):
        self.current_active_tab: str = "dashboard"

    def get_memory_metrics(self) -> Dict[str, Any]:
        """Retourne les métriques instantanées de RAM et VRAM."""
        total_gb, available_gb, used_percent = 16.0, 8.0, 50.0
        if HAS_PSUTIL and psutil:
            try:
                vm = psutil.virtual_memory()
                total_gb = round(vm.total / (1024 ** 3), 2)
                available_gb = round(vm.available / (1024 ** 3), 2)
                used_percent = round(vm.percent, 1)
            except Exception:
                pass

        return {
            "total_ram_gb": total_gb,
            "available_ram_gb": available_gb,
            "used_ram_percent": used_percent,
            "status_label": f"{available_gb} Go libre / {total_gb} Go ({100 - used_percent}% dispo)"
        }

    def get_running_ollama_models(self) -> List[str]:
        """Interroge Ollama pour lister les modèles actuellement en mémoire vive / VRAM."""
        try:
            with httpx.Client(timeout=1.5) as client:
                resp = client.get(f"{OLLAMA_BASE_URL}/api/ps")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
                    return models
        except Exception:
            pass
        return []

    def unload_unneeded_ollama_models(self, allowed_models: List[str]) -> List[str]:
        """Décharge immédiatement d'Ollama tout modèle qui n'est pas autorisé pour l'onglet actif."""
        running = self.get_running_ollama_models()
        unloaded = []

        allowed_clean = [m.split(":")[0].strip().lower() for m in allowed_models]

        for model_name in running:
            clean_name = model_name.split(":")[0].strip().lower()
            if clean_name not in allowed_clean:
                try:
                    with httpx.Client(timeout=2.0) as client:
                        resp = client.post(
                            f"{OLLAMA_BASE_URL}/api/generate",
                            json={"model": model_name, "keep_alive": 0}
                        )
                        if resp.status_code == 200:
                            unloaded.append(model_name)
                            logger.info(f"[TabResourceManager] Modèle déchargé avec succès : {model_name}")
                except Exception as e:
                    logger.warning(f"[TabResourceManager] Erreur déchargement {model_name}: {e}")

        return unloaded

    def kill_nuextract_process_if_present(self) -> bool:
        """Arrête le processus NuExtract (port 11435) s'il tourne alors que l'onglet ARH est inactif."""
        if not HAS_PSUTIL or not psutil:
            return False
        killed = False
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline') or []
                    cmd_str = " ".join(cmdline).lower()
                    if "llama-server" in proc.info.get('name', '').lower() and ("11435" in cmd_str or "nuextract" in cmd_str):
                        logger.info(f"[TabResourceManager] Arrêt du processus NuExtract superflu PID={proc.pid} (Économie 3.1 Go RAM)")
                        proc.kill()
                        killed = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            logger.warning(f"[TabResourceManager] Erreur vérification NuExtract: {e}")
        return killed

    def perform_garbage_collection(self):
        """Purge le garbage collector Python et le cache CUDA."""
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass

    def activate_tab(self, tab_name: str) -> Dict[str, Any]:
        """Bascule le contexte système vers l'onglet sélectionné et libère le reste."""
        clean_tab = tab_name.lower().replace("-view", "").replace("nav-", "").strip()
        if clean_tab == "dash":
            clean_tab = "dashboard"

        spec = TAB_RESOURCES.get(clean_tab, {
            "models": [],
            "category": "general",
            "description": "Onglet standard"
        })

        self.current_active_tab = clean_tab
        allowed_models = spec.get("models", [])

        # 1. Déchargement des modèles IA inutilisés
        unloaded_models = self.unload_unneeded_ollama_models(allowed_models)

        # 2. Si ce n'est pas l'onglet ARH, s'assurer que NuExtract ne monopolise pas 3.1 Go
        nuextract_killed = False
        if clean_tab != "arh":
            nuextract_killed = self.kill_nuextract_process_if_present()

        # 3. Libération de mémoire vive interne
        self.perform_garbage_collection()

        # 4. Métriques de mémoire après isolation
        mem_after = self.get_memory_metrics()

        logger.info(
            f"[TabResourceManager] Bascule vers onglet '{clean_tab}' | "
            f"Modèles autorisés: {allowed_models or ['Aucun (mode économique)']} | "
            f"Modèles déchargés: {unloaded_models} | "
            f"RAM dispo: {mem_after['available_ram_gb']} Go"
        )

        return {
            "status": "success",
            "active_tab": clean_tab,
            "category": spec.get("category", "general"),
            "description": spec.get("description", ""),
            "models_allowed": allowed_models,
            "models_unloaded": unloaded_models,
            "nuextract_stopped": nuextract_killed,
            "memory": mem_after
        }


tab_resource_manager = TabResourceManager()
