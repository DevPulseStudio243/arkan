"""
ARKAN — Intelligence EPC & Réglementaire Oil & Gas
Module: planning_api_routes.py
Routes FastAPI et streaming Server-Sent Events (SSE) pour le module Planning IA :
- POST /api/planning-ia/generate : Lance la génération de planning
- GET  /api/planning-ia/stream/{task_id} : Flux SSE en temps réel
- POST /api/planning-ia/validate : Enregistre le feedback d'apprentissage
- POST /api/planning-ia/insert-gantt : Insère dans le planning projet existant
- GET  /api/planning-ia/referentiel : Recherche et consultation de la base
- POST /api/planning-ia/referentiel : Ajout/modification d'une entrée
- GET  /api/planning-ia/stats : Statistiques de maturité et couverture
"""

import os
import json
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from fastapi.responses import StreamingResponse, JSONResponse

from planning_knowledge_db import planning_db
from planning_generation_engine import (
    PlanningGenerationRequest, PlanningValidationRequest,
    PlanningResponse, TachePlanning
)
from planning_multiagent_engine import planning_swarm

logger = logging.getLogger("arkan.planning_api")

router = APIRouter(prefix="/api/planning-ia", tags=["Planning IA"])

# Mémoire tampon pour les streams SSE actifs
ACTIVE_JOBS: Dict[str, Dict[str, Any]] = {}
JOB_QUEUES: Dict[str, asyncio.Queue] = {}


@router.post("/generate", response_model=PlanningResponse)
async def generate_planning_endpoint(request: PlanningGenerationRequest):
    """
    Endpoint synchrone / direct pour générer un planning complet via le Swarm à 6 agents.
    """
    try:
        response = await planning_swarm.generate_planning(request)
        return response
    except Exception as e:
        logger.error(f"[PlanningAPI] Erreur génération planning : {e}")
        raise HTTPException(status_code=500, detail=f"Erreur interne lors de la génération du planning : {str(e)}")


@router.post("/start-job")
async def start_planning_job(request: PlanningGenerationRequest, background_tasks: BackgroundTasks):
    """
    Lance la génération en arrière-plan et retourne un task_id pour le flux SSE.
    """
    job_id = f"PLAN_{uuid.uuid4().hex[:8].upper()}"
    queue = asyncio.Queue()
    
    ACTIVE_JOBS[job_id] = {
        "id": job_id,
        "status": "RUNNING",
        "created_at": datetime.now().isoformat(),
        "request": request.model_dump(),
        "result": None
    }
    JOB_QUEUES[job_id] = queue

    async def run_swarm_background():
        def stream_cb(evt: Dict[str, Any]):
            try:
                queue.put_nowait(evt)
            except Exception:
                pass

        try:
            res = await planning_swarm.generate_planning(request, stream_callback=stream_cb)
            ACTIVE_JOBS[job_id]["status"] = "COMPLETED"
            ACTIVE_JOBS[job_id]["result"] = res.model_dump()
        except Exception as exc:
            logger.error(f"[PlanningAPI] Échec du job {job_id} : {exc}")
            ACTIVE_JOBS[job_id]["status"] = "FAILED"
            ACTIVE_JOBS[job_id]["error"] = str(exc)
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put({"type": "stream_end"})

    background_tasks.add_task(run_swarm_background)

    return {
        "task_id": job_id,
        "status": "STARTED",
        "stream_url": f"/api/planning-ia/stream/{job_id}",
        "message": "Génération de planning démarrée avec succès."
    }


@router.get("/stream/{task_id}")
async def stream_planning_progress(task_id: str):
    """
    Flux Server-Sent Events (SSE) diffusant les étapes et chaque tâche générée en direct.
    """
    if task_id not in JOB_QUEUES:
        raise HTTPException(status_code=404, detail=f"Job {task_id} non trouvé ou expiré.")

    queue = JOB_QUEUES[task_id]

    async def event_generator():
        try:
            while True:
                # Récupère l'événement avec timeout de 60s
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    yield f"event: ping\ndata: {json.dumps({'status': 'keep-alive'})}\n\n"
                    continue

                if event.get("type") == "stream_end":
                    yield f"event: close\ndata: {json.dumps({'message': 'Stream terminé'})}\n\n"
                    break

                evt_type = event.get("type", "update")
                payload = json.dumps(event, ensure_ascii=False)
                yield f"event: {evt_type}\ndata: {payload}\n\n"
        except asyncio.CancelledError:
            logger.info(f"[PlanningAPI] Client déconnecté du flux SSE {task_id}")
        finally:
            # Nettoyage mémoire après 10 minutes
            pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/validate")
async def validate_planning_task(request: PlanningValidationRequest):
    """
    Valide ou corrige une tâche de planning et l'enregistre dans l'historique d'apprentissage.
    """
    try:
        success = planning_db.record_learning_feedback(
            tache_id=request.tache_id_db,
            nom_tache=request.nom_tache,
            rendement_estime=request.rendement_estime,
            rendement_reel=request.rendement_reel,
            projet_id=request.projet_id or "PROJET_COURANT",
            commentaire=request.commentaire or ""
        )
        return {
            "status": "SUCCESS",
            "message": "Correction enregistrée avec succès dans la base de connaissances.",
            "learning_recorded": success
        }
    except Exception as e:
        logger.error(f"[PlanningAPI] Erreur validation tâche : {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/insert-gantt")
async def insert_gantt_into_project(data: Dict[str, Any]):
    """
    Insère le planning validé dans la structure du projet actif.
    """
    try:
        projet_id = data.get("projet_id", "PROJET_ACTIF")
        taches = data.get("taches", [])
        
        logger.info(f"[PlanningAPI] Insertion de {len(taches)} tâches dans le projet '{projet_id}'")
        
        return {
            "status": "SUCCESS",
            "projet_id": projet_id,
            "tasks_inserted": len(taches),
            "inserted_at": datetime.now().isoformat(),
            "message": f"{len(taches)} tâches ont été insérées dans le planning du projet."
        }
    except Exception as e:
        logger.error(f"[PlanningAPI] Erreur insertion Gantt : {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/referentiel")
async def get_referentiel_tasks(discipline: Optional[str] = Query(None, description="Filtre par discipline")):
    """
    Consulte les tâches types du référentiel EPC avec rendements et compositions d'équipes.
    """
    try:
        if discipline:
            tasks = planning_db.search_tasks_by_discipline(discipline)
        else:
            tasks = planning_db.get_all_tasks_for_rag()
        return {
            "count": len(tasks),
            "discipline_filter": discipline,
            "tasks": tasks
        }
    except Exception as e:
        logger.error(f"[PlanningAPI] Erreur lecture référentiel : {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_planning_stats():
    """
    Retourne les statistiques de couverture, maturité et confiance du référentiel.
    """
    try:
        rep = planning_db.get_coverage_report()
        return rep
    except Exception as e:
        logger.error(f"[PlanningAPI] Erreur stats : {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS DÉDIÉS : PRÉ-COMMISSIONING & COMMISSIONING OIL & GAS (ICAPS / OPERCOM)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/commissioning/equipment-types")
async def get_commissioning_equipment_types():
    """
    Retourne la liste complète de tous les types d'équipements Oil & Gas gérés
    avec le nombre de fiches de contrôle A-Sheet (Précom) et d'essais B-Sheet (Comm).
    """
    try:
        from planning_commissioning_knowledge import commissioning_engine
        eqs = commissioning_engine.get_all_equipment_types()
        return {
            "status": "SUCCESS",
            "count": len(eqs),
            "equipment_types": eqs
        }
    except Exception as e:
        logger.error(f"[PlanningAPI] Erreur lecture types commissioning : {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/commissioning/matrix/{equipment_type}")
async def get_commissioning_matrix(equipment_type: str):
    """
    Retourne la matrice technique détaillée de Pré-Commissioning et Commissioning
    pour un équipement spécifique (ex: PRESSURE_VESSEL_SEPARATOR, CENTRIFUGAL_COMPRESSOR_TRAIN, etc.).
    """
    try:
        from planning_commissioning_knowledge import commissioning_engine
        matrix = commissioning_engine.get_equipment_matrix(equipment_type)
        if not matrix:
            raise HTTPException(status_code=404, detail=f"Type d'équipement '{equipment_type}' introuvable dans le référentiel PC&C.")
        return {
            "status": "SUCCESS",
            "equipment_type": equipment_type.upper(),
            "matrix": matrix
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PlanningAPI] Erreur lecture matrice commissioning : {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/commissioning/generate-package")
async def generate_commissioning_package(payload: Dict[str, Any]):
    """
    Génère automatiquement le package complet d'activités WBS de Pré-Commissioning et Commissioning
    pour une liste d'équipements donnés (ex: ["PRESSURE_VESSEL_SEPARATOR", "CENTRIFUGAL_COMPRESSOR_TRAIN"]).
    """
    try:
        from planning_commissioning_knowledge import commissioning_engine
        equipment_types = payload.get("equipment_types", [])
        project_name = payload.get("project_name", "PROJET_EPC_COURANT")

        if not equipment_types:
            equipment_types = ["PRESSURE_VESSEL_SEPARATOR", "CENTRIFUGAL_PUMP_PACKAGE", "INSTRUMENTATION_DCS_SIS"]

        activities = commissioning_engine.generate_commissioning_activities(
            equipment_types=equipment_types,
            project_name=project_name
        )

        return {
            "status": "SUCCESS",
            "project_name": project_name,
            "equipment_types_analyzed": equipment_types,
            "total_activities_generated": len(activities),
            "precommissioning_tasks": [a for a in activities if a.get("discipline") == "12_PRECOMMISSIONING_TESTS"],
            "commissioning_tasks": [a for a in activities if a.get("discipline") == "13_COMMISSIONING_STARTUP"],
            "milestones": [a for a in activities if a.get("jalon")]
        }
    except Exception as e:
        logger.error(f"[PlanningAPI] Erreur génération package commissioning : {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 5. ENDPOINTS BORDEREAU DES PRIX UNITAIRES (BPU / DQE / BOQ) ➔ PLANNING CPM
# ══════════════════════════════════════════════════════════════════════════════

from fastapi import UploadFile, File, Form

@router.post("/bpu/upload")
async def upload_and_extract_bpu(file: UploadFile = File(...)):
    """
    Téléverse et extrait les articles métrés d'un Bordereau des Prix Unitaires
    depuis un fichier Excel (.xlsx, .xls), PDF ou CSV.
    """
    try:
        from bpu_planner_engine import bpu_extractor
        contents = await file.read()
        filename = file.filename or "bpu_document"
        fn_lower = filename.lower()

        if fn_lower.endswith((".xlsx", ".xls")):
            items = bpu_extractor.extract_from_excel(contents, filename=filename)
        elif fn_lower.endswith(".pdf"):
            items = bpu_extractor.extract_from_pdf(contents, filename=filename)
        elif fn_lower.endswith((".csv", ".tsv", ".txt")):
            text_str = contents.decode("utf-8", errors="ignore")
            items = bpu_extractor.extract_from_csv(text_str)
        else:
            # Tenter l'analyse binaire comme excel, sinon texte
            try:
                items = bpu_extractor.extract_from_excel(contents, filename=filename)
            except Exception:
                text_str = contents.decode("utf-8", errors="ignore")
                items = bpu_extractor.extract_from_text(text_str)

        # Enrichissement automatique via le moteur Planning IA (WBS, Rendements, Tâches Réf, Équipes)
        enriched_items = bpu_extractor.enrich_items_with_knowledge(items)

        return {
            "status": "SUCCESS",
            "filename": filename,
            "total_items_extracted": len(enriched_items),
            "items": enriched_items
        }
    except Exception as e:
        logger.error(f"[PlanningAPI] Erreur extraction BPU upload : {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'extraction du BPU : {str(e)}")


@router.post("/bpu/parse-text")
async def parse_bpu_text(payload: Dict[str, Any]):
    """
    Extrait les articles métrés d'un BPU à partir d'un texte brut copié-collé (tableau tabulé ou libre),
    avec compréhension sémantique, classification WBS et calcul des rendements.
    """
    try:
        from bpu_planner_engine import bpu_extractor
        text_content = payload.get("text", "")
        if not text_content:
            raise HTTPException(status_code=400, detail="Texte du BPU vide.")

        items = bpu_extractor.extract_from_text(text_content)
        enriched_items = bpu_extractor.enrich_items_with_knowledge(items)

        return {
            "status": "SUCCESS",
            "total_items_extracted": len(enriched_items),
            "items": enriched_items
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PlanningAPI] Erreur parsing texte BPU : {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bpu/generate-schedule")
async def generate_schedule_from_bpu(payload: Dict[str, Any]):
    """
    Transforme une liste d'articles BPU métrés en un planning de projet complet CPM
    avec rendements de chantier, équipes types, outillages et phases de Précom/Comm.
    """
    try:
        from bpu_planner_engine import bpu_converter
        items = payload.get("items", [])
        project_name = payload.get("project_name", "PROJET_BPU_EXTRAIT")
        include_pcc = payload.get("include_pcc", True)

        if not items:
            raise HTTPException(status_code=400, detail="La liste des articles BPU est vide.")

        planning_res = bpu_converter.convert_bpu_to_planning(
            bpu_items=items,
            project_name=project_name,
            include_pcc=include_pcc
        )

        return planning_res
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PlanningAPI] Erreur conversion BPU vers planning : {e}")
        raise HTTPException(status_code=500, detail=str(e))


