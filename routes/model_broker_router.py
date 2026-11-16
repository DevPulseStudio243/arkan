# ============================================================
#  Router — Model Broker & Exportations Industrielles
#  Routes: /api/symbol-rules/*, /pid/export/dexpi/*,
#          /api/multi-sheet/*, /api/export/plcopen, /api/system/*-backup
# ============================================================
import os
import io
import zipfile
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response

from symbol_rule_engine import DEFAULT_PRESETS, SymbolRuleEngine, apply_symbol_rules
from dexpi_exporter import export_project_to_dexpi_xml
from opc_stitcher import stitch_multi_sheet_project
from plcopen_exporter import export_logic_to_plcopen_xml

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Model Broker & Industrial Exporters"])


# ─── Endpoints Règles Symboles ──────────────────────────────

@router.get("/api/symbol-rules/presets")
async def get_symbol_rules_presets():
    """Returns standard symbol presets (ISA 5.1, DIN, PIP)."""
    return {"presets": DEFAULT_PRESETS}


@router.post("/api/symbol-rules/custom")
async def save_custom_symbol_rules(payload: Dict[str, Any]):
    """Saves custom symbol pattern matching rules to file."""
    preset_name = payload.get("preset_name", "custom_project")
    rules = payload.get("rules", {})
    os.makedirs("generated_visuals", exist_ok=True)
    file_path = f"generated_visuals/{preset_name}_rules.json"
    engine = SymbolRuleEngine(preset_name=preset_name)
    engine.preset.update(rules)
    engine.save_custom_preset(file_path)
    return {"status": "success", "file_path": file_path, "preset_name": preset_name}


# ─── Endpoints Exportations DEXPI & PLCopen ─────────────────

@router.get("/pid/export/dexpi/{project_id}")
async def export_dexpi_xml_endpoint(project_id: str):
    """Exports plant P&ID data to strict DEXPI 1.3 / ISO 15926 Proteus XML format."""
    project_data = {
        "name": f"Project_{project_id}",
        "equipment": [{"tag": "201-PP-001A", "type": "Pompe centrifuge", "capacity": "1200 m3/h"}],
        "valves": [{"tag": "201-HV-006", "type": "Vanne d'isolement", "size_inch": 4, "normal_state": "NO", "function": "isolement"}],
        "instruments": [{"tag": "201-PT-101", "type": "Transmetteur de pression", "isa_function": "PT", "loop_number": "101"}],
        "lines": [{"line_tag": "14\"-PH-18-20006-9A6A5-N", "from": "201-PP-001A", "to": "201-V-101", "service_code": "PH"}]
    }
    xml_content = export_project_to_dexpi_xml(project_data)
    return Response(content=xml_content, media_type="application/xml", headers={
        "Content-Disposition": f"attachment; filename=DEXPI_ISO15926_{project_id}.xml"
    })


@router.post("/api/multi-sheet/stitch")
async def stitch_multi_sheet_endpoint(payload: Dict[str, Any]):
    """Stitches multiple P&ID sheet analysis results into a single consolidated plant model."""
    sheets = payload.get("sheets", [])
    project_name = payload.get("project_name", "Unified_Plant_Project")
    if not sheets:
        raise HTTPException(status_code=400, detail="Aucune donnée de folio/feuille fournie")
    stitched_result = stitch_multi_sheet_project(sheets, project_name=project_name)
    return stitched_result


@router.post("/api/export/plcopen")
async def export_plcopen_xml_endpoint(payload: Dict[str, Any]):
    """Exports control logic diagram data to PLCopen XML (IEC 61131-3) format."""
    logic_data = payload.get("logic_data", payload)
    xml_content = export_logic_to_plcopen_xml(logic_data)
    return Response(content=xml_content, media_type="application/xml", headers={
        "Content-Disposition": "attachment; filename=PLCopen_IEC61131_ControlLogic.xml"
    })


# ─── Endpoints Sauvegarde & Migration Système ───────────────

@router.get("/api/system/export-backup")
async def export_system_backup_endpoint():
    """Génère et télécharge une archive ZIP complète de toutes les bases de données et configurations."""
    backup_io = io.BytesIO()
    files_to_backup = [
        "planning_knowledge.db",
        "arh_dossiers.db",
        "knowledge_graph.json",
        "feedback_db.json",
        "source_weights.json",
        ".env",
        ".env.example"
    ]
    
    for opt_db in ["materials.db", "procurement.db", "verification.db", "traceability.db", "project_model.json"]:
        if os.path.exists(opt_db):
            files_to_backup.append(opt_db)

    with zipfile.ZipFile(backup_io, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for f in files_to_backup:
            if os.path.exists(f):
                zip_file.write(f, arcname=f)
        
        if os.path.exists("chroma_db"):
            for root, _, filenames in os.walk("chroma_db"):
                for fn in filenames:
                    fp = os.path.join(root, fn)
                    zip_file.write(fp, arcname=os.path.relpath(fp, "."))

    backup_io.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ARKAN_DATA_BACKUP_{timestamp}.zip"
    
    return Response(
        content=backup_io.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.post("/api/system/import-backup")
async def import_system_backup_endpoint(file: UploadFile = File(...)):
    """Restaure une archive ZIP de sauvegarde sur le système."""
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Le fichier doit être une archive .zip")

    content = await file.read()
    zip_io = io.BytesIO(content)
    restored = []

    try:
        with zipfile.ZipFile(zip_io, "r") as zip_file:
            for member in zip_file.infolist():
                if ".." in member.filename or member.filename.startswith("/"):
                    continue
                zip_file.extract(member, path=".")
                restored.append(member.filename)
        
        logger.info("[Backup] Restauration réussie de %d fichiers depuis l'archive", len(restored))
        return {
            "status": "success",
            "message": f"{len(restored)} fichiers et bases restaurés avec succès.",
            "restored_files": restored
        }
    except Exception as e:
        logger.error("[Backup] Échec restauration: %s", e)
        raise HTTPException(status_code=500, detail=f"Erreur lors de la restauration : {str(e)}")
