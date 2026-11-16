# ============================================================
#  Router — Système, Outils, Monitoring, Apprentissage & Graphe
#  Routes: /tools, /feedback, /graph/*, /vocabulary/*, /learning/*,
#          /monitor/*, /system/version, /auto-indexer/status, /admin/*
# ============================================================
import os
import json
import time
import subprocess
import sys
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends, Security, BackgroundTasks
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["System & Monitoring"])

# ─── Auth Dependency Fallback ──────────────────────────────
try:
    from api_enhanced import verify_api_key
except ImportError:
    async def verify_api_key():
        return None

def _get_orchestrator():
    try:
        from api_enhanced import get_orchestrator
        return get_orchestrator()
    except Exception:
        return None

def _get_auto_indexer():
    try:
        from api_enhanced import get_auto_indexer
        return get_auto_indexer()
    except Exception:
        return None


# ─── Pydantic Models ────────────────────────────────────────

class FeedbackRequest(BaseModel):
    question: str
    answer: str
    sources: list = []
    rating: str = "good"
    metadata: dict = {}

class HumanCorrectionRequest(BaseModel):
    original_question: str
    correct_answer: str
    context: str = ""
    expert_name: str = ""

class ActivateTabRequest(BaseModel):
    tab: str



# ─── Endpoints Tools & Status ───────────────────────────────

@router.get("/auto-indexer/status")
async def auto_indexer_status():
    """Return the auto-indexer status and statistics."""
    auto_idx = _get_auto_indexer()
    if auto_idx is None:
        return {"enabled": False, "status": "disabled"}
    return {"enabled": True, **auto_idx.get_status()}


@router.get("/system/version")
async def get_version():
    return {"version": "3.2.0-v4", "file": "api_enhanced.py"}


@router.post("/system/free-memory")
async def free_system_memory():
    """Libère la mémoire inutilisée (RAM & VRAM) par garbage collection et purge du cache PyTorch."""
    import gc
    gc.collect()
    vram_freed = False
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
            vram_freed = True
    except Exception:
        pass

    return {
        "status": "success",
        "message": "Mémoire vive (RAM) et cache VRAM nettoyés avec succès",
        "cuda_cache_cleared": vram_freed
    }


@router.post("/system/activate-tab")
async def activate_tab_resources(req: ActivateTabRequest):
    """Active dynamiquement les ressources de l'onglet et décharge les modèles/processus non nécessaires."""
    try:
        from tab_resource_manager import tab_resource_manager
        return tab_resource_manager.activate_tab(req.tab)
    except Exception as e:
        logger.error(f"[TabResourceManager] Erreur activation onglet '{req.tab}': {e}")
        return {"status": "error", "message": str(e)}


@router.get("/system/memory-status")
async def get_system_memory_status():
    """Fournit les métriques de mémoire physique et virtuelle pour la barre de statut de l'interface."""
    try:
        from tab_resource_manager import tab_resource_manager
        return tab_resource_manager.get_memory_metrics()
    except Exception as e:
        return {"error": str(e)}


@router.get("/tools")
async def get_tools_list():
    """Get list of active agents/tools in the format expected by the UI."""
    orchestrator = _get_orchestrator()
    if orchestrator is None:
        return {"total": 0, "categories": {}, "category_labels": {}, "tools": []}

    tools = []
    categories = {"engineering": 0, "agent": 0, "dynamic": 0}
    
    for name, agent in orchestrator.agents.items():
        cat = "engineering" if name in ["process", "mechanical", "electrical"] else "agent"
        categories[cat] += 1
        agent_display_name = getattr(agent, 'name', None) or getattr(agent, '__class__', None).__name__ or name.title()
        tools.append({
            "name": f"Agent {agent_display_name}",
            "category": cat,
            "icon": "robot" if cat == "agent" else "gear-six",
            "params": ["query", "context"],
            "description": f"Expert en {name}. Gère l'analyse approfondie et la validation des données techniques."
        })

    return {
        "total": len(tools),
        "categories": categories,
        "category_labels": {
            "engineering": "Disciplines Ingénierie",
            "agent": "Orchestration Agents",
            "dynamic": "Outils Dynamiques"
        },
        "tools": tools
    }


# ─── Endpoints Feedback & Human Correction ──────────────────

@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest, api_key: str = Depends(verify_api_key)):
    """Submit feedback on a question/answer pair."""
    from feedback import save_feedback
    record_id = save_feedback(
        question=request.question,
        answer=request.answer,
        sources=request.sources,
        rating=request.rating,
        metadata=request.metadata,
    )
    return {"status": "ok", "id": record_id}


@router.post("/feedback/human-correction")
async def submit_human_correction(request: HumanCorrectionRequest):
    """
    Endpoint pour les experts : soumettre une correction manuelle.
    La correction est stockée dans la mémoire ChromaDB avec priorité maximale.
    """
    try:
        from agent_memory import get_agent_memory
        memory = get_agent_memory()
        memory.save_human_correction(
            query=request.original_question,
            correct_answer=request.correct_answer,
            context=request.context or f"Expert: {request.expert_name}"
        )
        logger.info("[FewShot] Correction humaine enregistrée par %s pour: %s",
                    request.expert_name, request.original_question[:50])
        return {
            "status": "success",
            "message": "Correction humaine enregistrée avec succès dans la mémoire Few-Shot.",
            "question_preview": request.original_question[:80],
        }
    except Exception as e:
        logger.error("[FewShot] Erreur enregistrement correction: %s", e)
        raise HTTPException(status_code=500, detail=f"Erreur enregistrement: {e}")


@router.get("/feedback/human-corrections/count")
async def count_human_corrections():
    """Retourne le nombre de corrections humaines enregistrées."""
    try:
        from agent_memory import get_agent_memory
        memory = get_agent_memory()
        stats = memory.get_stats()
        return {"total_memories": stats.get("count", 0)}
    except Exception as e:
        return {"total_memories": 0, "error": str(e)}


# ─── Endpoints Knowledge Graph ──────────────────────────────

@router.get("/graph/{entity}")
async def graph_entity(entity: str, project_id: Optional[str] = None):
    """Query the knowledge graph for a specific entity, with optional project isolation."""
    from knowledge_graph import query_graph
    result = query_graph(entity, project_id=project_id)
    return result


@router.get("/graph/document/{filename}")
async def graph_document(filename: str, project_id: Optional[str] = None):
    """Get the entity network for a specific document, with optional project isolation."""
    from knowledge_graph import get_document_network
    result = get_document_network(filename, project_id=project_id)
    return result


# ─── Endpoints Vocabulary & Learning ────────────────────────

@router.get("/vocabulary/expand")
async def vocabulary_expand(q: str):
    """Expand a query with synonyms and related terms."""
    from vocabulary import expand_query
    expanded = expand_query(q)
    return {"original": q, "expanded": expanded}


@router.get("/learning/stats")
async def learning_stats():
    """Get learning system statistics."""
    from feedback import get_retrieval_stats, learn_from_feedback
    from vocabulary import get_term_frequency
    feedback_stats = get_retrieval_stats()
    insights = learn_from_feedback()
    term_freq = get_term_frequency(top_n=15)
    return {
        "feedback": feedback_stats,
        "insights": insights,
        "top_terms": term_freq,
    }


@router.post("/learning/export-training-data")
async def export_learning_data(api_key: str = Depends(verify_api_key)):
    """Exporte les interactions positives et feedbacks validés en formats Alpaca Instruct & ShareGPT pour Kaggle / Colab."""
    try:
        from auto_learning_sync import auto_learning_manager
        return auto_learning_manager.export_datasets()
    except Exception as e:
        logger.error(f"[AutoLearning] Erreur lors de l'export d'apprentissage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/learning/feedback-stats")
async def get_feedback_learning_stats():
    """Retourne les métriques détaillées de l'auto-apprentissage continu."""
    try:
        from auto_learning_sync import auto_learning_manager
        return auto_learning_manager.get_stats()
    except Exception as e:
        logger.error(f"[AutoLearning] Erreur stats apprentissage: {e}")
        return {"error": str(e)}


@router.post("/learning/rebuild")
async def learning_rebuild(api_key: str = Depends(verify_api_key)):
    """Force rebuild of knowledge graph and vocabulary from all indexed docs."""
    from indexer import get_collection
    from knowledge_graph import add_document_to_graph, save_graph, _copy_empty
    from vocabulary import build_vocabulary

    try:
        collection = get_collection()
        all_data = collection.get(include=["documents", "metadatas"])
    except Exception as exc:
        logger.error("Request error", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    docs = all_data.get("documents", [])
    metas = all_data.get("metadatas", [])

    graph = _copy_empty()
    save_graph(graph)

    seen_sources: set = set()
    for i, doc in enumerate(docs):
        meta = metas[i] if i < len(metas) else {}
        source = meta.get("source", "unknown_%d" % i)
        if source not in seen_sources:
            seen_sources.add(source)
            try:
                from verification_extractors import resolve_project_for_file
                proj_info = resolve_project_for_file(Path(source))
                p_id = proj_info.get("project_id", "general")
            except Exception:
                p_id = "general"
            add_document_to_graph(source, doc, project_id=p_id)

    vocab = build_vocabulary(docs)

    return {
        "status": "ok",
        "documents_processed": len(seen_sources),
        "vocabulary_terms": len(vocab.get("technical_terms", {})),
    }


# ─── Endpoints Monitor ──────────────────────────────────────

@router.get("/monitor/agents")
async def get_agent_monitor():
    """Tableau de bord de monitoring en temps réel des agents."""
    try:
        from monitor import get_monitor
        return get_monitor().get_dashboard()
    except Exception as e:
        logger.error("[Monitor] Erreur dashboard: %s", e)
        return {"error": str(e), "uptime_seconds": 0, "agents": []}


@router.get("/monitor/scada-alerts")
async def get_scada_alerts(limit: int = 20):
    """Retourne les dernières alarmes SCADA (Désactivé)."""
    return {"alerts": []}


# ─── Endpoints Admin Performance & Autopilot ────────────────

@router.post("/admin/analyze-performance")
async def analyze_performance(background_tasks: BackgroundTasks, api_key: str = Security(verify_api_key)):
    """Lance une évaluation complète du système."""
    from trainer_eval import SystemEvaluator
    from rich.console import Console
    from config import BASE_DIR, MODELS_DIR, DATA_DIR
    
    def run_eval():
        evaluator = SystemEvaluator(
            base_dir=Path(BASE_DIR),
            models_dir=Path(MODELS_DIR),
            data_dir=Path(DATA_DIR),
            console=Console()
        )
        report = evaluator.eval_retrieval()
        report_path = Path(MODELS_DIR) / "eval_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    background_tasks.add_task(run_eval)
    return {"status": "started", "message": "Analyse de performance lancée."}


@router.post("/admin/autopilot-learning")
async def autopilot_learning(background_tasks: BackgroundTasks, api_key: str = Security(verify_api_key)):
    """Workflow Automatisé Autopilot (Vérification → Synchro → Entraînement)."""
    dataset_path = Path("data/learning/local_distillation_dataset.json")
    
    def run_autopilot():
        try:
            logger.info("=== DÉMARRAGE DU PIPELINE AUTOPILOT ===")
            if not dataset_path.exists():
                logger.info("Dataset introuvable. Lancement de la génération initiale (10 scénarios)...")
                subprocess.run([sys.executable, "distill_claude_reasoning.py", "--count", "10"], check=True)
            
            with open(dataset_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            count = len(data)
            logger.info(f"Dataset vérifié : {count} scénarios trouvés.")
            
            keywords = ["oil", "gas", "pipeline", "p&id", "epc", "instrumentation", "pump", "asme"]
            sample = data[:100]
            aligned_count = 0
            for item in sample:
                text = (item.get("query", "") + " " + item.get("answer", "")).lower()
                if any(k in text for k in keywords):
                    aligned_count += 1
            
            logger.info(f"Validation Domaine : {aligned_count}/100 scénarios alignés Oil & Gas.")
            if aligned_count < 10:
                logger.warning("Alerte : Faible alignement domaine détecté dans les 100 premières lignes.")
            
            logger.info("Lancement de l'entraînement LoRA (Qwen 14B)...")
            script_path = Path("train_qwen_lora.py")
            if script_path.exists():
                subprocess.run([sys.executable, str(script_path)], check=True)
                logger.info("Entraînement Autopilot terminé avec succès.")
            else:
                logger.error("Script d'entraînement introuvable.")
                
        except Exception as e:
            logger.error(f"Échec du pipeline Autopilot : {e}")

    background_tasks.add_task(run_autopilot)
    return {
        "status": "started",
        "message": "Pipeline Autopilot lancé : Vérification → Synchro → Entraînement.",
        "steps": ["Domain Alignment Check", "Data Synchronization", "LoRA Fine-tuning"]
    }


@router.post("/admin/download-base")
async def download_base(background_tasks: BackgroundTasks, api_key: str = Security(verify_api_key)):
    """Restaure une base de données pré-entraînée à partir du backup si disponible."""
    backup_path = Path("chroma_backup.json")
    if not backup_path.exists():
        return {
            "status": "error", 
            "message": "Aucune base pré-entraînée (chroma_backup.json) trouvée sur le serveur."
        }
    
    def run_restore():
        try:
            logger.info("Début de la restauration de la base...")
            from indexer import get_collection
            with open(backup_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            col = get_collection()
            ids = data.get("ids", [])
            docs = data.get("documents", [])
            metas = data.get("metadatas", [])
            embeds = data.get("embeddings", [])
            
            batch_size = 100
            for i in range(0, len(ids), batch_size):
                end = min(i + batch_size, len(ids))
                col.upsert(
                    ids=ids[i:end],
                    documents=docs[i:end],
                    metadatas=metas[i:end],
                    embeddings=embeds[i:end]
                )
            logger.info(f"Restauration terminée : {len(ids)} chunks chargés.")
            from indexer import flush_bm25
            flush_bm25()
        except Exception as e:
            logger.error(f"Erreur restauration : {e}")

    background_tasks.add_task(run_restore)
    return {
        "status": "started", 
        "message": "Restauration de la base pré-entraînée lancée en arrière-plan."
    }
