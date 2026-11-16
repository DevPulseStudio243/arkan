# ============================================================
#  Router — Agents Disciplinaires, Mémoire, Entraînement & Reranker
#  Routes: /agents/*, /memory/*, /training/*, /visualize/*, /admin/toggle-reranker
# ============================================================
import os
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agents & Memory"])

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

def _get_conv_memory():
    try:
        from api_enhanced import get_conv_memory
        return get_conv_memory()
    except Exception:
        return None

def _get_trainer():
    try:
        from api_enhanced import get_trainer
        return get_trainer()
    except Exception:
        return None


# ─── Pydantic Models ────────────────────────────────────────

class TrainingCycleResponse(BaseModel):
    status: str
    summary: dict


# ─── Endpoints Mémoire Conversationnelle ────────────────────

@router.get("/memory/sessions")
async def get_memory_sessions():
    """Liste toutes les sessions de conversation avec leurs métadonnées."""
    conv_mem = _get_conv_memory()
    if conv_mem is None:
        return {"sessions": [], "stats": {}}
    sessions = conv_mem.get_all_sessions()
    stats = conv_mem.get_stats()
    return {"sessions": sessions, "stats": stats}


@router.get("/memory/history/{session_id}")
async def get_session_history(session_id: str, limit: int = 50):
    """Retourne l'historique complet d'une session spécifique."""
    conv_mem = _get_conv_memory()
    if conv_mem is None:
        raise HTTPException(status_code=503, detail="Memory non disponible")
    turns = conv_mem.get_session_turns(session_id=session_id, limit=limit)
    return {
        "session_id": session_id,
        "turns": [t.to_dict() for t in turns],
        "count": len(turns),
    }


@router.post("/memory/new_session")
async def start_new_session(title: str = ""):
    """Crée une nouvelle session de conversation."""
    conv_mem = _get_conv_memory()
    if conv_mem is None:
        raise HTTPException(status_code=503, detail="Memory non disponible")
    new_sid = conv_mem.new_session(title=title)
    return {"session_id": new_sid, "message": "Nouvelle session démarrée"}


@router.get("/memory/search")
async def search_memory(query: str, limit: int = 5):
    """Recherche dans toutes les conversations passées."""
    conv_mem = _get_conv_memory()
    if conv_mem is None:
        return {"results": []}
    turns = conv_mem.search_memory(query, limit=limit)
    return {
        "query": query,
        "results": [t.to_dict() for t in turns],
        "count": len(turns),
    }


# ─── Endpoints Agents Disciplinaires ────────────────────────

@router.get("/agents")
async def list_agents():
    """List all available discipline agents and their capabilities."""
    orchestrator = _get_orchestrator()
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent system not initialised")

    agents_info = []
    for discipline_key, agent in orchestrator.agents.items():
        disc_name = getattr(discipline_key, "value", str(discipline_key))
        agent_name = getattr(agent, "name", f"Agent {disc_name}")
        ontology = getattr(agent, "ontology", None)
        if ontology:
            concepts_count = len(getattr(ontology, "concepts", []))
            standards_count = len(getattr(ontology, "standards", []))
            typical_eq = getattr(ontology, "typical_equipment", [])[:10]
            rules_count = len(getattr(ontology, "reasoning_rules", []))
            links = list(getattr(ontology, "cross_discipline_links", {}).keys())
        else:
            concepts_count = len(getattr(agent, "_keywords", []))
            standards_count = len(getattr(agent, "_norms", []))
            typical_eq = getattr(agent, "_critical_terms", [])[:10]
            rules_count = len(getattr(agent, "_validation_patterns", []))
            links = []

        agents_info.append({
            "name": agent_name,
            "discipline": disc_name,
            "concepts_count": concepts_count,
            "standards_count": standards_count,
            "typical_equipment": typical_eq,
            "reasoning_rules_count": rules_count,
            "cross_discipline_links": links,
        })

    return {
        "total_agents": len(agents_info),
        "agents": agents_info,
    }


@router.get("/agents/{discipline}")
async def get_agent_detail(discipline: str):
    """Get detailed information about a specific discipline agent."""
    orchestrator = _get_orchestrator()
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent system not initialised")

    # Match by key or string value
    target_agent = None
    target_key = None
    for k, a in orchestrator.agents.items():
        if str(k).lower() == discipline.lower() or getattr(k, "value", "").lower() == discipline.lower() or getattr(a, "name", "").lower() == discipline.lower():
            target_agent = a
            target_key = k
            break

    if target_agent is None:
        available = [getattr(k, "value", str(k)) for k in orchestrator.agents.keys()]
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{discipline}' not found. Available: {available}",
        )

    ontology = getattr(target_agent, "ontology", None)
    if ontology:
        return {
            "name": getattr(target_agent, "name", str(target_key)),
            "discipline": getattr(target_key, "value", str(target_key)),
            "concepts": getattr(ontology, "concepts", []),
            "standards": getattr(ontology, "standards", []),
            "typical_equipment": getattr(ontology, "typical_equipment", []),
            "reasoning_rules": [
                {"id": getattr(r, "rule_id", ""), "description": getattr(r, "description", ""), "condition": getattr(r, "condition", "")}
                for r in getattr(ontology, "reasoning_rules", [])
            ],
            "cross_discipline_links": getattr(ontology, "cross_discipline_links", {}),
            "relationships_count": len(getattr(ontology, "relationships", [])),
        }
    else:
        return {
            "name": getattr(target_agent, "name", str(target_key)),
            "discipline": getattr(target_key, "value", str(target_key)),
            "concepts": getattr(target_agent, "_keywords", []),
            "standards": getattr(target_agent, "_norms", []),
            "typical_equipment": getattr(target_agent, "_critical_terms", []),
            "reasoning_rules": [
                {"id": str(i), "description": str(pattern), "condition": str(msg)}
                for i, (pattern, msg) in enumerate(getattr(target_agent, "_validation_patterns", []))
            ],
            "cross_discipline_links": {},
            "relationships_count": 0,
        }


# ─── Endpoints Visual Summary Card ──────────────────────────

@router.post("/visualize/summary")
async def create_visual_summary(project_name: str, data: dict, api_key: str = Depends(verify_api_key)):
    """Generate a professional visual summary card for a project."""
    from vision_generator import get_vision_generator
    viz = get_vision_generator()
    sections = data.get("sections", [])
    path = viz.generate_project_summary_card(project_name, sections)
    
    if not path:
        raise HTTPException(status_code=500, detail="Echec de la génération visuelle")
    
    filename = os.path.basename(path)
    return {"status": "success", "url": f"/visuals/{filename}"}


# ─── Endpoints Reranker Toggle ──────────────────────────────

@router.post("/admin/toggle-reranker")
async def toggle_reranker(request: Request, active: bool, api_key: str = Depends(verify_api_key)):
    """Toggle the neural reranker active state on the server."""
    request.app.state.reranker_active = active
    logger.info("[Reranker] Toggled active state to %s", active)
    return {"status": "success", "reranker_active": active}


# ─── Endpoints Training Pipeline ────────────────────────────

@router.get("/training/status")
async def get_training_status():
    """Get training pipeline status and metrics."""
    trainer = _get_trainer()
    if trainer is None:
        return {"status": "not_initialised"}

    try:
        status = trainer.get_training_status()
        return {"status": "active", **status}
    except Exception as exc:
        logger.error("Training status error: %s", exc)
        return {"status": "error", "detail": "Internal server error"}


@router.post("/training/cycle", response_model=TrainingCycleResponse)
async def trigger_training_cycle(api_key: str = Depends(verify_api_key)):
    """Trigger a full training cycle (feedback + knowledge graph + vocab)."""
    trainer = _get_trainer()
    if trainer is None:
        raise HTTPException(status_code=503, detail="Training pipeline not initialised")

    try:
        summary = trainer.run_training_cycle()
        return TrainingCycleResponse(status="completed", summary=summary)
    except Exception as exc:
        logger.error("Training cycle failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/training/incremental", response_model=TrainingCycleResponse)
async def trigger_incremental_update(api_key: str = Depends(verify_api_key)):
    """Trigger an incremental training update (lightweight)."""
    trainer = _get_trainer()
    if trainer is None:
        raise HTTPException(status_code=503, detail="Training pipeline not initialised")

    try:
        summary = trainer.incremental_update()
        return TrainingCycleResponse(status="completed", summary=summary)
    except Exception as exc:
        logger.error("Incremental update failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
