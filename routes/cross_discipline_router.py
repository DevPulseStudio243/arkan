# -*- coding: utf-8 -*-
"""
routes/cross_discipline_router.py
Router FastAPI pour le Moteur de Recoupement Croisé Inter-Disciplines ARKAN v3.
Expose les endpoints de corrélation triangulaire et d'injection en réserves.
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from cross_discipline_reconciler import run_cross_discipline_reconciliation

router = APIRouter(prefix="/api/mto", tags=["Cross Discipline Reconciliation"])

class CrossCheckRequest(BaseModel):
    project_id: Optional[str] = "C3421-ROK1-SP1-OK1"
    piping_items: List[Dict[str, Any]] = []
    sld_feeders: List[Dict[str, Any]] = []
    routing_items: List[Dict[str, Any]] = []
    earthing_items: List[Dict[str, Any]] = []
    pid_equipment: Optional[List[Dict[str, Any]]] = None

@router.post("/cross-check")
def run_cross_check(req: CrossCheckRequest):
    """
    Exécute les 7 contrôles de recoupement croisé inter-disciplines et retourne
    la liste des écarts et réserves proposées avec score de confiance.
    """
    try:
        anomalies = run_cross_discipline_reconciliation(
            piping_items=req.piping_items,
            sld_feeders=req.sld_feeders,
            routing_items=req.routing_items,
            earthing_items=req.earthing_items,
            pid_equipment=req.pid_equipment
        )
        return {
            "status": "success",
            "project_id": req.project_id,
            "total_anomalies": len(anomalies),
            "certain_count": len([a for a in anomalies if a.get("confidence_level") == "CERTAIN"]),
            "probable_count": len([a for a in anomalies if a.get("confidence_level") == "PROBABLE"]),
            "to_verify_count": len([a for a in anomalies if a.get("confidence_level") == "TO_VERIFY"]),
            "anomalies": anomalies
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors du recoupement croisé : {str(e)}")
