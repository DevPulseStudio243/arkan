# ============================================================
#  Router — Générateur de P&ID & Schémas Tuyauterie IA
#  Routes: /api/pid-gen/*
# ============================================================

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from pid_generator_engine import pid_master_generator

logger = logging.getLogger("PID_Generator_Router")

router = APIRouter(prefix="/api/pid-gen", tags=["PID Generator"])

class GeneratePidRequest(BaseModel):
    prompt: str = ""
    process_type: str = "separation"  # "separation", "pig_trap", "wellhead", "pumping", "flare"
    project_code: str = "ARKAN-SONATRACH"

@router.post("/generate")
async def generate_pid(payload: GeneratePidRequest):
    """Génère un schéma P&ID complet (topologie, SVG orthogonal, DXF AutoCAD, DEXPI XML et MTO)."""
    try:
        res = pid_master_generator.generate(
            prompt=payload.prompt,
            process_type=payload.process_type,
            project_code=payload.project_code
        )
        return res.dict()
    except Exception as e:
        logger.error(f"[PID-Gen] Erreur lors de la génération : {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/templates")
async def get_pid_reference_templates():
    """Renvoie les modèles et projets de référence extraits des 559 plans du dataset."""
    catalog_path = Path("data/pid_catalog.json")
    if not catalog_path.exists():
        return {"total_plans": 0, "projects": {}}
    
    with open(catalog_path, encoding="utf-8") as f:
        catalog = json.load(f)

    # 4 Archétypes prédéfinis prêts à l'emploi
    presets = [
        {
            "id": "separation",
            "name": "Séparateur de Production Biphasique HP",
            "description": "Séparateur 68 bar avec boucle de niveau LIC-101, LCV-101, pompes 1+1 et PSV vers torche.",
            "project_ref": "Projet C1124 / Sonatrach Touat Gaz"
        },
        {
            "id": "pig_trap",
            "name": "Gare de Racleurs Départ 12\" (Pig Launcher)",
            "description": "Fût 12\" classe 600, vanne d'isolement MOV-2001, ligne kicker et décharge thermique.",
            "project_ref": "Gare de Racleurs Mobile / Touat Gaz"
        },
        {
            "id": "wellhead",
            "name": "Tête de Puits Éruptif (Christmas Tree)",
            "description": "Arbre de Noël 5000 psi, vanne de sécurité de fond SSSV, duse de réglage et injection chimique.",
            "project_ref": "Projet DZ-GHBR / Rhourde El Baguel"
        },
        {
            "id": "pumping",
            "name": "Poste de Pompage & Régulation Débit Minimum",
            "description": "2 Pompes centrifuges (1 Service + 1 Secours) avec boucle de débit minimum FIC-201.",
            "project_ref": "Projet C3421-ROK1 / Rhourde Oulad Kechkeche"
        },
        {
            "id": "flare",
            "name": "Knock-Out Drum & Collecteur Torche HP",
            "description": "Ballon de torche avec régulation de purge automatique et détection haut niveau LAHH.",
            "project_ref": "Standard Sonatrach EPF"
        }
    ]

    return {
        "total_catalog_plans": catalog.get("total_plans", 0),
        "projects_summary": catalog.get("projects_summary", {}),
        "presets": presets
    }

@router.get("/download-dxf/{filename}")
async def download_dxf(filename: str):
    """Permet de télécharger le fichier DXF généré pour ouverture sous AutoCAD."""
    file_path = Path("generated_visuals") / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Fichier DXF introuvable.")
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/dxf"
    )

@router.get("/sonatrach-rules")
async def get_sonatrach_rules():
    """Renvoie un résumé des règles d'ingénierie issues des commentaires Sonatrach."""
    dataset_path = Path("data/training_pid_dataset.jsonl")
    rules = []
    if dataset_path.exists():
        with open(dataset_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    if "Sonatrach" in item.get("source", ""):
                        rules.append({
                            "question": item.get("instruction"),
                            "regle": item.get("output")
                        })
    return {"total_rules": len(rules), "rules": rules}

@router.get("/model-status")
async def get_model_status():
    """Renvoie le statut et les métriques de l'adaptateur LoRA P&ID entraîné."""
    adapter_path = Path("arkan_pid_lora_adapter")
    weights_path = adapter_path / "adapter_model.safetensors"
    has_weights = weights_path.exists()
    return {
        "status": "ready" if has_weights else "not_found",
        "lora_adapter_path": str(adapter_path.resolve()),
        "has_weights": has_weights,
        "weights_size_mb": round(weights_path.stat().st_size / (1024 * 1024), 2) if has_weights else 0,
        "base_model": "Qwen/Qwen2.5-1.5B-Instruct",
        "peft_type": "LoRA (r=16, alpha=32, target: q,k,v,o,gate,up,down)",
        "training_framework": "HuggingFace Transformers / PEFT",
        "final_loss": 0.7602,
        "training_epochs": 1,
        "training_steps": 30,
        "training_runtime_min": 31.39,
        "dataset_samples": 68
    }
