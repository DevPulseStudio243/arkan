"""
ARKAN — Intelligence EPC & Planification
Module: routes/xer_engine_router.py
Router FastAPI 100% LOCAL & AUTONOME pour le module XER Engine (BOQ ➔ Primavera P6)
ZÉRO connexion externe, ZÉRO clé API.
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, UploadFile, File, Query, HTTPException, Request
from fastapi.responses import JSONResponse, Response, FileResponse

from core_planning_xer_engine import LocalXerEngine, convert_client_boq

logger = logging.getLogger("arkan.xer_engine_router")

router = APIRouter(prefix="/api/xer-engine", tags=["XER Engine (Local)"])

BASE_DIR = Path(__file__).resolve().parent.parent


@router.get("/health")
async def xer_health():
    """Vérifie l'état de fonctionnement du moteur local."""
    return {
        "status": "ok",
        "engine": "ARKAN Local XER Engine",
        "mode": "100% autonomous local (no external connection)",
        "features": [
            "BOQ parsing & auto-recognition",
            "CPM forward & backward pass",
            "DCMA 14-point audit",
            "Automatic task splitting (<= 21 days)",
            "Primavera P6 native .XER generation (ERMHDR 5.0 with full Activity Codes)",
            "Excel Cash Flow & Manpower .XLSX generation",
            "Client BOQ auto-conversion"
        ]
    }


@router.post("/run")
async def run_local_engine(
    request: Request,
    file: Optional[UploadFile] = File(None),
    opts: Optional[str] = Query(None)
):
    """
    Exécute le moteur d'ordonnancement XER Engine 100% localement.
    Prend en charge le fichier .xlsx soit via multipart/form-data soit via corps brut (application/octet-stream).
    """
    try:
        # 1. Extraction du contenu du fichier
        file_bytes = b""
        if file is not None:
            file_bytes = await file.read()
        else:
            # Fallback direct body
            file_bytes = await request.body()

        if not file_bytes:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "errors": ["Aucun fichier classeur .xlsx fourni."]}
            )

        # 2. Extraction des options
        opts_dict = {}
        if opts:
            try:
                opts_dict = json.loads(opts)
            except Exception:
                opts_dict = {}

        logger.info(f"[XER Engine Local] Lancement du calcul (taille fichier: {len(file_bytes)} octets, opts: {opts_dict})")

        # 3. Exécution du moteur autonome
        engine = LocalXerEngine()
        engine.parse_workbook(file_bytes)
        result = engine.run(opts_dict)

        logger.info(f"[XER Engine Local] Calcul réussi : {result['stats']['activities']} activités, {result['stats']['links']} liens, fin le {result['stats']['finish_date']}")
        return JSONResponse(content=result)

    except Exception as exc:
        logger.error(f"[XER Engine Local] Erreur lors de l'exécution : {exc}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"ok": False, "errors": [str(exc)]}
        )


@router.get("/templates/{template_name}")
async def get_template(template_name: str):
    """Téléchargement direct des modèles de classeurs locaux."""
    safe_name = Path(template_name).name
    allowed_templates = ["template.xlsx", "template2.xlsx", "template_blank.xlsx"]
    if safe_name not in allowed_templates:
        raise HTTPException(status_code=404, detail="Modèle non trouvé")

    file_path = BASE_DIR / safe_name
    if not file_path.exists():
        # Fallback si le template blank n'est pas encore généré : servir template.xlsx
        file_path = BASE_DIR / "template.xlsx"
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Fichier {safe_name} introuvable sur le disque.")

    return FileResponse(
        path=str(file_path),
        filename=safe_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.post("/boq/convert")
async def convert_boq_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    mode: str = Query("inspect"),
    pick: Optional[str] = Query(None)
):
    """
    Inspecte ou convertit un classeur BOQ client brut en classeur 4 feuilles standardisé.
    """
    try:
        file_bytes = b""
        if file is not None:
            file_bytes = await file.read()
        else:
            file_bytes = await request.body()

        if not file_bytes:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "errors": ["Aucun fichier BOQ client fourni."]}
            )

        pick_sheets = None
        if mode == "convert" and pick:
            try:
                pick_sheets = json.loads(pick)
            except Exception:
                pick_sheets = None

        res = convert_client_boq(file_bytes, pick_sheets=pick_sheets)
        return JSONResponse(content=res)

    except Exception as exc:
        logger.error(f"[BOQ Converter Local] Erreur : {exc}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"ok": False, "errors": [str(exc)]}
        )
