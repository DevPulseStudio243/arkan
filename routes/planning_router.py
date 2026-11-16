# routes/planning_router.py
# Router FastAPI pour les routes /planning/* (Primavera P6 XER - Planning Analysis)
# Distinct de planning_api_routes.py qui couvre /api/planning-ia/*

import os
import logging
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Lazy resolution pour éviter les imports circulaires avec api_enhanced.py
async def verify_api_key():
    try:
        import api_enhanced
        if hasattr(api_enhanced, 'verify_api_key'):
            res = api_enhanced.verify_api_key()
            if hasattr(res, '__await__'):
                return await res
            return res
    except Exception:
        pass
    return None

def get_project_dir_path(project_id: str) -> Path:
    try:
        import api_enhanced
        if hasattr(api_enhanced, 'get_project_dir_path'):
            return api_enhanced.get_project_dir_path(project_id)
    except Exception:
        pass
    return Path("./data") / project_id

router = APIRouter(tags=["Planning"])


# -----------------------------------------------------------------------
#  Pydantic Models
# -----------------------------------------------------------------------
class AIReportRequest(BaseModel):
    projectName: str
    stats: dict
    healthCheck: list
    delayedTasks: Optional[list] = []
    criticalTasks: Optional[list] = []


class IndexPlanningRequest(BaseModel):
    project_id: str
    project_name: str
    filename: str
    data: dict
    label: Optional[str] = ""


class ComparePlanningRequest(BaseModel):
    id_v1: int
    id_v2: int


# -----------------------------------------------------------------------
#  Routes
# -----------------------------------------------------------------------

@router.get("/planning/list")
async def planning_list_stored(api_key: str = Depends(verify_api_key)):
    """
    Scan all project directories and return all stored .XER files with metadata.
    Used to populate the 'previously uploaded plannings' dropdown in the UI.
    """
    from datetime import datetime
    from config import DATA_DIR

    results = []

    # 1. Scan uploads/ folder
    upload_dir = Path("./uploads")
    if upload_dir.exists():
        for f in sorted(upload_dir.iterdir()):
            if f.suffix.lower() == ".xer":
                stat = f.stat()
                results.append({
                    "project_id": "uploads",
                    "filename": f.name,
                    "path": str(f),
                    "size_kb": round(stat.st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "label": f"[uploads] â€” {f.name}",
                })

    # 2. Scan data/ subdirectories recursively
    data_path = Path(DATA_DIR)
    if data_path.exists():
        for item in sorted(data_path.iterdir()):
            if item.is_dir():
                if item.name.lower() == "00-projet":
                    # Look inside data/00-Projet/
                    for sub in sorted(item.iterdir()):
                        if sub.is_dir():
                            for f in sorted(sub.iterdir()):
                                if f.suffix.lower() == ".xer":
                                    stat = f.stat()
                                    results.append({
                                        "project_id": sub.name,
                                        "filename": f.name,
                                        "path": str(f),
                                        "size_kb": round(stat.st_size / 1024, 1),
                                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                                        "label": f"{sub.name} â€” {f.name}",
                                    })
                else:
                    # Look directly inside data/<subdir>/
                    for f in sorted(item.iterdir()):
                        if f.suffix.lower() == ".xer":
                            stat = f.stat()
                            results.append({
                                "project_id": item.name,
                                "filename": f.name,
                                "path": str(f),
                                "size_kb": round(stat.st_size / 1024, 1),
                                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                                "label": f"{item.name} â€” {f.name}",
                            })

    return {"status": "success", "files": results}


@router.get("/planning/load")
async def planning_load_stored(path: str, api_key: str = Depends(verify_api_key)):
    """
    Load and analyze a previously stored XER file by its server path.
    Returns the same structure as /planning/analyze.
    """
    import planning_analyzer

    target = Path(path)
    if not target.exists() or target.suffix.lower() != ".xer":
        raise HTTPException(status_code=404, detail=f"Fichier XER introuvable : {path}")

    # Security: must be inside the project data directory or uploads/
    resolved = target.resolve()
    allowed_roots = [
        Path("./data").resolve(),
        Path("./uploads").resolve(),
    ]
    if not any(str(resolved).startswith(str(r)) for r in allowed_roots):
        raise HTTPException(status_code=403, detail="AccÃ¨s refusÃ© Ã  ce chemin.")

    logger.info("[Planning API] Loading stored XER: %s", resolved)
    try:
        content_bytes = resolved.read_bytes()
        try:
            content_str = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content_str = content_bytes.decode("latin-1")
            except UnicodeDecodeError:
                content_str = content_bytes.decode("windows-1252", errors="replace")

        data = planning_analyzer.parse_xer_file(content_str)
        return {
            "status": "success",
            "filename": target.name,
            "data": data
        }
    except Exception as e:
        logger.error("[Planning API] Error loading stored XER %s: %s", path, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/planning/delete")
async def planning_delete_file(path: str, api_key: str = Depends(verify_api_key)):
    """
    Delete a stored Primavera P6 .XER file from the server.
    """
    target = Path(path)
    if not target.exists() or target.suffix.lower() != ".xer":
        raise HTTPException(status_code=404, detail=f"Fichier XER introuvable : {path}")

    # Security: must be inside the project data directory or uploads/
    resolved = target.resolve()
    allowed_roots = [
        Path("./data").resolve(),
        Path("./uploads").resolve(),
    ]
    if not any(str(resolved).startswith(str(r)) for r in allowed_roots):
        raise HTTPException(status_code=403, detail="AccÃ¨s refusÃ© Ã  ce chemin.")

    try:
        os.remove(resolved)
        logger.info("[Planning API] Deleted stored XER file: %s", resolved)

        # Also clean up the parent directory if it's empty and under data/ (except data itself)
        parent_dir = resolved.parent
        if parent_dir != Path("./data").resolve() and parent_dir != Path("./uploads").resolve():
            if parent_dir.exists() and not any(parent_dir.iterdir()):
                parent_dir.rmdir()
                logger.info("[Planning API] Cleaned up empty project folder: %s", parent_dir)

        return {"status": "success", "message": "Fichier supprimÃ© avec succÃ¨s."}
    except Exception as e:
        logger.error("[Planning API] Error deleting XER %s: %s", path, e)
        raise HTTPException(status_code=500, detail=f"Impossible de supprimer le fichier: {str(e)}")


@router.post("/planning/analyze")
async def planning_analyze(file: UploadFile = File(...), api_key: str = Depends(verify_api_key)):
    """
    Upload a Primavera P6 .XER file, parse it, and run DCMA checks instantly.
    """
    logger.info("[Planning API] Upload and audit P6 XER file: %s", file.filename)
    try:
        content_bytes = await file.read()
        try:
            content_str = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content_str = content_bytes.decode("latin-1")
            except UnicodeDecodeError:
                content_str = content_bytes.decode("windows-1252", errors="replace")

        # Import local analyzer
        import planning_analyzer

        # Parse XER file
        data = planning_analyzer.parse_xer_file(content_str)

        # Sauvegarder le fichier de planification dans le rÃ©pertoire du projet
        project_id = data.get("stats", {}).get("projectId") or data.get("projectId")
        if project_id:
            try:
                project_dir = get_project_dir_path(project_id)
                project_dir.mkdir(parents=True, exist_ok=True)
                dest_path = project_dir / Path(file.filename).name
                with open(dest_path, "wb") as out_f:
                    out_f.write(content_bytes)
                logger.info("[Planning API] Saved uploaded XER file to: %s", dest_path)
            except Exception as save_err:
                logger.error("[Planning API] Failed to save XER to project directory: %s", save_err)

        return {
            "status": "success",
            "filename": file.filename,
            "data": data
        }
    except Exception as e:
        logger.error("[Planning API] Error auditing schedule: %s", e)
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'audit de planification: {str(e)}")


@router.post("/planning/ai-report")
async def planning_ai_report(req: AIReportRequest, lang: str = "fr", api_key: str = Depends(verify_api_key)):
    """
    Call local LLM to generate planning strategic report based on calculated metrics and corporate RAG guidelines.
    """
    logger.info("[Planning API] Generating AI recommendations with RAG context, lang: %s", lang)
    try:
        # 1. RAG retrieval for corporate planning guidelines
        rag_context = ""
        try:
            from retriever import hybrid_retrieve, build_context_string
            # Query the VDB for corporate manual constraints, planning best practices, etc.
            rag_results = hybrid_retrieve(query="normes planification Primavera P6 DCMA chemin critique marges", top_k=5)
            rag_context = build_context_string(rag_results)
            logger.info("[Planning API] RAG Context successfully retrieved (%d chars)", len(rag_context))
        except Exception as r_err:
            logger.warning("[Planning API] RAG retrieval failed (continuing without RAG context): %s", r_err)

        # 2. Call the generator
        import planning_analyzer
        data = {
            "projectName": req.projectName,
            "stats": req.stats,
            "healthCheck": req.healthCheck,
            "delayedTasks": req.delayedTasks,
            "criticalTasks": req.criticalTasks or []
        }
        ai_report = await planning_analyzer.generate_ai_planning_report(data, lang=lang, rag_context=rag_context)
        return {
            "status": "success",
            "ai_report": ai_report
        }
    except Exception as e:
        logger.error("[Planning API] Error generating AI report: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/planning/index")
async def planning_index(req: IndexPlanningRequest, api_key: str = Depends(verify_api_key)):
    """Save/index planning analysis data for comparison."""
    try:
        import planning_index
        version_id = planning_index.save_planning(
            project_id=req.project_id,
            project_name=req.project_name,
            filename=req.filename,
            data=req.data,
            label=req.label or ""
        )
        return {"status": "success", "version_id": version_id}
    except Exception as e:
        logger.error("[Planning API] Error indexing planning: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/planning/index")
async def planning_index_list_all(api_key: str = Depends(verify_api_key)):
    """List all indexed planning versions across all projects."""
    try:
        import planning_index
        versions = planning_index.list_all_versions()
        return {"status": "success", "versions": versions}
    except Exception as e:
        logger.error("[Planning API] Error listing all planning versions: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/planning/index/{project_id}")
async def planning_index_list(project_id: str, api_key: str = Depends(verify_api_key)):
    """List all indexed planning versions for a specific project."""
    try:
        import planning_index
        versions = planning_index.list_versions(project_id)
        return {"status": "success", "versions": versions}
    except Exception as e:
        logger.error("[Planning API] Error listing project planning versions: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/planning/compare")
async def planning_compare(req: ComparePlanningRequest, api_key: str = Depends(verify_api_key)):
    """Compare two indexed planning versions."""
    try:
        import planning_index
        comparison = planning_index.compare_versions(req.id_v1, req.id_v2)
        return {"status": "success", "comparison": comparison}
    except Exception as e:
        logger.error("[Planning API] Error comparing planning versions: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

