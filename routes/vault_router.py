# routes/vault_router.py
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import obsidian_vault_engine as ove

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vault", tags=["Obsidian Vault"])


class AgentMemoryCreate(BaseModel):
    title: str
    content: str
    tags: Optional[List[str]] = None
    links: Optional[List[str]] = None


@router.get("/status")
async def get_vault_status():
    """Retourne l'état, l'emplacement et les statistiques du Vault Obsidian."""
    try:
        graph = ove.build_vault_knowledge_graph()
        return {
            "status": "ok",
            "vault_path": graph["vault_path"],
            "total_nodes": graph["total_nodes"],
            "total_edges": graph["total_edges"],
            "clusters": graph["clusters"]
        }
    except Exception as e:
        logger.error(f"[Vault API] Erreur get_vault_status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync")
async def trigger_vault_sync():
    """Déclenche la resynchronisation intégrale des bases ARKAN vers le Vault Markdown."""
    try:
        result = ove.sync_full_vault()
        return result
    except Exception as e:
        logger.error(f"[Vault API] Erreur trigger_vault_sync: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph")
async def get_vault_graph():
    """Retourne la topologie complète du graphe de connaissances (nœuds et arêtes [[wikilinks]])."""
    try:
        return ove.build_vault_knowledge_graph()
    except Exception as e:
        logger.error(f"[Vault API] Erreur get_vault_graph: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/note")
async def get_vault_note(path: str = Query(..., description="Chemin relatif ou identifiant de la note")):
    """Retourne le contenu Markdown d'une note spécifique ainsi que ses rétroliens (backlinks)."""
    try:
        return ove.read_note_content(path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Vault API] Erreur get_vault_note: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agent-memory")
async def create_agent_memory_note(payload: AgentMemoryCreate):
    """Permet aux agents DOTS ou ARH d'enregistrer une réflexion structurée dans le Vault."""
    try:
        res = ove.append_agent_memory(
            title=payload.title,
            content=payload.content,
            tags=payload.tags,
            links=payload.links
        )
        return res
    except Exception as e:
        logger.error(f"[Vault API] Erreur create_agent_memory_note: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/open-local")
async def open_vault_in_os():
    """Ouvre le répertoire du Vault dans l'Explorateur Windows / système."""
    return ove.open_vault_locally()
