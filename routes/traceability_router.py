# ============================================================
#  Router — Traçabilité Matérielle & Isométriques
#  Routes: /materials/*
# ============================================================
from fastapi import APIRouter, HTTPException
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
import logging
import traceability_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Materials & Traceability"])


# ─── Pydantic Models ────────────────────────────────────────

class IsometricCreate(BaseModel):
    line_number: str
    revision: Optional[str] = "0"
    title: Optional[str] = ""
    project_id: Optional[str] = "Boosting LDBP5"
    file_path: Optional[str] = ""
    status: Optional[str] = "Draft"

class BOMItemCreate(BaseModel):
    category: str
    tag: Optional[str] = ""
    description: str
    size: str
    material: str
    quantity: float
    unit: Optional[str] = "U"
    weight_unit: Optional[float] = 0.0
    weight_total: Optional[float] = 0.0
    remarks: Optional[str] = ""
    heat_number: Optional[str] = ""
    spool_number: Optional[str] = ""
    status: Optional[str] = "Pending"

class BOMImportList(BaseModel):
    items: List[BOMItemCreate]

class HeatNumberCreate(BaseModel):
    heat_number: str
    material_spec: Optional[str] = ""
    diameter: Optional[str] = ""
    manufacturer: Optional[str] = ""
    mtr_file_path: Optional[str] = ""
    chemical_composition: Optional[Dict[str, Any]] = None
    mechanical_properties: Optional[Dict[str, Any]] = None
    inspector: Optional[str] = ""
    status: Optional[str] = "Accepted"

class AllocateHeatRequest(BaseModel):
    bom_item_id: str
    heat_number: str

class WeldCreate(BaseModel):
    weld_number: str
    weld_type: Optional[str] = "Butt"
    size: Optional[str] = ""
    schedule: Optional[str] = ""
    welder_id: Optional[str] = ""
    weld_date: Optional[str] = ""
    fitup_status: Optional[str] = "Pending"
    fitup_date: Optional[str] = ""
    visual_status: Optional[str] = "Pending"
    visual_date: Optional[str] = ""
    ndt_type: Optional[str] = "RT"
    ndt_status: Optional[str] = "Pending"
    ndt_date: Optional[str] = ""
    heat_number_1: Optional[str] = ""
    heat_number_2: Optional[str] = ""
    status: Optional[str] = "Pending"

class SpoolCreate(BaseModel):
    spool_number: str
    shop_field: Optional[str] = "Shop"
    fabricator: Optional[str] = ""
    fitup_date: Optional[str] = ""
    welding_date: Optional[str] = ""
    ndt_date: Optional[str] = ""
    painting_date: Optional[str] = ""
    status: Optional[str] = "Design"


# ─── Routes ─────────────────────────────────────────────────

@router.get("/materials/dashboard")
async def get_materials_dashboard():
    """Retrieve summary metrics for the material traceability dashboard."""
    try:
        return traceability_db.get_traceability_kpi()
    except Exception as e:
        logger.error("[Traceability API] Error fetching dashboard: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/materials/isometrics")
async def get_isometrics(project_id: Optional[str] = None):
    """List all isometrics drawings."""
    try:
        return traceability_db.get_isometrics_list(project_id)
    except Exception as e:
        logger.error("[Traceability API] Error fetching isometrics: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/materials/isometrics")
async def create_isometric(iso: IsometricCreate):
    """Create or update an isometric drawing line."""
    try:
        iso_id = traceability_db.add_isometric(
            line_number=iso.line_number,
            revision=iso.revision,
            title=iso.title,
            project_id=iso.project_id,
            file_path=iso.file_path,
            status=iso.status
        )
        if not iso_id:
            raise HTTPException(status_code=500, detail="Failed to save isometric drawing")
        return {"status": "success", "id": iso_id, "line_number": iso.line_number}
    except Exception as e:
        logger.error("[Traceability API] Error creating isometric: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/materials/isometrics/{iso_id}/bom")
async def get_isometric_bom(iso_id: str):
    """Retrieve BOM items associated with an isometric drawing."""
    try:
        return traceability_db.get_bom_items(iso_id)
    except Exception as e:
        logger.error("[Traceability API] Error fetching BOM: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/materials/isometrics/{iso_id}/bom")
async def import_isometric_bom(iso_id: str, bom: BOMImportList):
    """Import/Replace BOM items for a specific isometric drawing."""
    try:
        traceability_db.clear_isometric_bom(iso_id)
        imported_ids = []
        for item in bom.items:
            item_id = traceability_db.add_bom_item(
                iso_id=iso_id,
                category=item.category,
                tag=item.tag,
                description=item.description,
                size=item.size,
                material=item.material,
                quantity=item.quantity,
                unit=item.unit,
                weight_unit=item.weight_unit,
                weight_total=item.weight_total,
                remarks=item.remarks,
                heat_number=item.heat_number,
                spool_number=item.spool_number,
                status=item.status
            )
            if item_id:
                imported_ids.append(item_id)
        return {"status": "success", "count": len(imported_ids), "items": imported_ids}
    except Exception as e:
        logger.error("[Traceability API] Error importing BOM: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/materials/heat-numbers")
async def get_heat_numbers():
    """Retrieve all material Heat Number certificates."""
    try:
        return traceability_db.get_heat_numbers_list()
    except Exception as e:
        logger.error("[Traceability API] Error fetching heat numbers: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/materials/heat-numbers")
async def create_heat_number(heat: HeatNumberCreate):
    """Create or update a material Heat Number certificate."""
    try:
        res = traceability_db.add_heat_number(
            heat_number=heat.heat_number,
            material_spec=heat.material_spec,
            diameter=heat.diameter,
            manufacturer=heat.manufacturer,
            mtr_file_path=heat.mtr_file_path,
            chemical_composition=heat.chemical_composition,
            mechanical_properties=heat.mechanical_properties,
            inspector=heat.inspector,
            status=heat.status
        )
        if not res:
            raise HTTPException(status_code=500, detail="Failed to save heat number")
        return {"status": "success", "heat_number": res}
    except Exception as e:
        logger.error("[Traceability API] Error creating heat number: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/materials/allocate-heat")
async def allocate_heat_number(req: AllocateHeatRequest):
    """Allocate a Heat Number to a specific BOM item."""
    try:
        success = traceability_db.allocate_heat_number_to_bom(req.bom_item_id, req.heat_number)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to allocate heat number")
        return {"status": "success"}
    except Exception as e:
        logger.error("[Traceability API] Error allocating heat: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/materials/welds")
async def get_welds(iso_id: Optional[str] = None):
    """Retrieve welding log entries, optionally filtered by isometric id."""
    try:
        return traceability_db.get_welds_list(iso_id)
    except Exception as e:
        logger.error("[Traceability API] Error fetching welds: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/materials/isometrics/{iso_id}/welds")
async def create_weld(iso_id: str, weld: WeldCreate):
    """Create or update a weld log entry."""
    try:
        w_id = traceability_db.add_weld(
            iso_id=iso_id,
            weld_number=weld.weld_number,
            weld_type=weld.weld_type,
            size=weld.size,
            schedule=weld.schedule,
            welder_id=weld.welder_id,
            weld_date=weld.weld_date,
            fitup_status=weld.fitup_status,
            fitup_date=weld.fitup_date,
            visual_status=weld.visual_status,
            visual_date=weld.visual_date,
            ndt_type=weld.ndt_type,
            ndt_status=weld.ndt_status,
            ndt_date=weld.ndt_date,
            heat_number_1=weld.heat_number_1,
            heat_number_2=weld.heat_number_2,
            status=weld.status
        )
        if not w_id:
            raise HTTPException(status_code=500, detail="Failed to save weld")
        return {"status": "success", "id": w_id}
    except Exception as e:
        logger.error("[Traceability API] Error creating weld: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/materials/spools")
async def get_spools(iso_id: Optional[str] = None):
    """Retrieve spool status tracking list, optionally filtered by isometric id."""
    try:
        return traceability_db.get_spools_list(iso_id)
    except Exception as e:
        logger.error("[Traceability API] Error fetching spools: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/materials/isometrics/{iso_id}/spools")
async def create_spool(iso_id: str, spool: SpoolCreate):
    """Create or update a spool tracking entry."""
    try:
        s_id = traceability_db.add_spool(
            iso_id=iso_id,
            spool_number=spool.spool_number,
            shop_field=spool.shop_field,
            fabricator=spool.fabricator,
            fitup_date=spool.fitup_date,
            welding_date=spool.welding_date,
            ndt_date=spool.ndt_date,
            painting_date=spool.painting_date,
            status=spool.status
        )
        if not s_id:
            raise HTTPException(status_code=500, detail="Failed to save spool")
        return {"status": "success", "id": s_id}
    except Exception as e:
        logger.error("[Traceability API] Error creating spool: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
