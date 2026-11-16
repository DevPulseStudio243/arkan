# routes/procurement_router.py
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

import procurement_db
from arh_nuextract_engine import arh_nuextract_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Procurement"])

CONTRACTS_UPLOAD_DIR = Path("d:/DATA BASE IA/data/procurement_contracts")
CONTRACTS_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def _safe_notify_vault():
    """Déclenche la mise à jour asynchrone du Vault Obsidian sans bloquer la requête HTTP."""
    try:
        import threading
        import obsidian_vault_engine as ove
        threading.Thread(target=ove.sync_full_vault, daemon=True).start()
    except Exception as _e:
        logger.debug(f"[Vault Notification] Non-bloquante: {_e}")


# --- Procurement schemas ---
class ContractItemCreate(BaseModel):
    designation: str
    reference: Optional[str] = ""
    quantite_contractuelle: float = 1.0
    unite: Optional[str] = "U"
    prix_unitaire: float = 0.0
    delai_livraison: Optional[str] = ""

class ContractCreate(BaseModel):
    numero_contrat: str
    fournisseur: str
    objet: str
    date_signature: Optional[str] = ""
    date_debut: Optional[str] = ""
    date_fin_prevue: Optional[str] = ""
    delai_livraison: Optional[str] = ""
    montant: float = 0.0
    devise: Optional[str] = "DZD"
    statut: Optional[str] = "signé"
    document_path: Optional[str] = ""
    project_id: Optional[str] = "general"
    items: Optional[List[ContractItemCreate]] = None

class MaterialReceiptCreate(BaseModel):
    item_id: str
    date_reception: str
    quantite_recue: float
    numero_bl: str
    lieu_stockage: str
    etat: str
    responsable: str
    remarques: Optional[str] = ""

class BatchReceiptItem(BaseModel):
    item_id: str
    quantite_recue: float
    lieu_stockage: str
    etat: str

class MaterialReceiptBatchCreate(BaseModel):
    items: List[BatchReceiptItem]
    date_reception: str
    numero_bl: str
    responsable: str
    remarques: Optional[str] = ""
    documents: Optional[str] = ""
    numero_pv: Optional[str] = None

class MaterialIssueCreate(BaseModel):
    item_id: str
    date_sortie: str
    quantite_sortie: float
    motif: str
    destination: str
    responsable: str

class BatchIssueItem(BaseModel):
    item_id: str
    quantite_sortie: float

class MaterialIssueBatchCreate(BaseModel):
    items: List[BatchIssueItem]
    date_sortie: str
    motif: str
    destination: str
    responsable: str
    numero_pv: Optional[str] = None

class BatchReturnItem(BaseModel):
    item_id: str
    quantite_retournee: float

class MaterialReturnBatchCreate(BaseModel):
    items: List[BatchReturnItem]
    date_retour: str
    motif: str
    lieu_stockage: str
    responsable: str
    numero_pv: Optional[str] = None

class ProjectCreate(BaseModel):
    name: str
    code: Optional[str] = ""
    description: Optional[str] = ""

class ContractProjectUpdate(BaseModel):
    project_id: str

# --- PROCUREMENT ENDPOINTS ---

@router.get("/procurement/projects")
async def get_procurement_projects():
    try:
        return procurement_db.get_projects()
    except Exception as e:
        logger.error(f"[Procurement API] Error fetching projects: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/procurement/projects")
async def create_procurement_project(proj: ProjectCreate):
    try:
        saved = procurement_db.create_project(
            name=proj.name,
            code=proj.code or "",
            description=proj.description or ""
        )
        _safe_notify_vault()
        return {"status": "success", "project": saved}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Procurement API] Error creating project: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/procurement/projects/{project_id}")
async def delete_procurement_project(project_id: str):
    try:
        procurement_db.delete_project(project_id)
        return {"status": "success"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Procurement API] Error deleting project: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/procurement/contracts/{contract_id}/project")
async def update_procurement_contract_project(contract_id: str, payload: ContractProjectUpdate):
    try:
        res = procurement_db.update_contract_project(contract_id, payload.project_id)
        return {"status": "success", **res}
    except Exception as e:
        logger.error(f"[Procurement API] Error updating contract project: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/procurement/dashboard")
async def get_procurement_dashboard_stats():
    try:
        return procurement_db.get_procurement_stats()
    except Exception as e:
        logger.error(f"[Procurement API] Error fetching dashboard stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/procurement/contracts")
async def get_procurement_contracts():
    try:
        return procurement_db.get_contracts(include_items=True)
    except Exception as e:
        logger.error(f"[Procurement API] Error fetching contracts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/procurement/contracts")
async def create_procurement_contract(contract: ContractCreate):
    try:
        if contract.items:
            saved = procurement_db.import_contract_with_items(
                contract_data=contract.model_dump() if hasattr(contract, "model_dump") else contract.dict(),
                project_id=contract.project_id or "general",
                document_path=contract.document_path or ""
            )
            _safe_notify_vault()
            return {"status": "success", "id": saved["id"], "contract": saved}

        c_id = procurement_db.create_contract(
            numero_contrat=contract.numero_contrat,
            fournisseur=contract.fournisseur,
            objet=contract.objet,
            date_signature=contract.date_signature,
            date_debut=contract.date_debut,
            date_fin_prevue=contract.date_fin_prevue,
            montant=contract.montant,
            devise=contract.devise,
            statut=contract.statut,
            document_path=contract.document_path,
            project_id=contract.project_id or "general",
            delai_livraison=contract.delai_livraison or ""
        )
        _safe_notify_vault()
        return {"status": "success", "id": c_id}
    except Exception as e:
        logger.error(f"[Procurement API] Error creating contract: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/procurement/contracts/import-pdf")
async def import_procurement_contract_pdf(
    file: UploadFile = File(...),
    project_id: str = Form("general"),
    auto_insert: bool = Form(True)
):
    """
    Extrait automatiquement un contrat PDF via NuExtract-3 + PyMuPDF Table Extractor :
      - Numéro de contrat
      - Nom du fournisseur
      - Objet du contrat
      - Délai de livraison
      - Bordereau des prix & Liste complète des équipements
    Et l'insère directement dans la base Procurement SQLite si auto_insert=True.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Veuillez fournir un fichier contrat au format PDF (.pdf).")

    try:
        safe_name = re.sub(r'[^A-Za-z0-9_.\-]', '_', Path(file.filename).name)
        saved_path = CONTRACTS_UPLOAD_DIR / f"{int(time.time())}_{safe_name}"
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Le fichier PDF envoyé est vide.")
        saved_path.write_bytes(content)

        import importlib
        import arh_nuextract_engine as _nu_mod
        importlib.reload(_nu_mod)
        extracted = _nu_mod.arh_nuextract_engine.extract_contract_from_pdf(
            pdf_path=str(saved_path),
            filename=file.filename
        )
        extracted["document_path"] = str(saved_path)
        extracted["project_id"] = project_id or "general"

        saved_contract = None
        if auto_insert:
            saved_contract = procurement_db.import_contract_with_items(
                contract_data=extracted,
                project_id=project_id or "general",
                document_path=str(saved_path)
            )
            _safe_notify_vault()

        return {
            "status": "success",
            "auto_inserted": auto_insert,
            "extracted": extracted,
            "contract": saved_contract
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Procurement API] Error importing contract PDF via NuExtract: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'extraction NuExtract du contrat PDF : {e}")

@router.post("/procurement/contracts/import-json")
async def import_procurement_contract_json(payload: Dict[str, Any]):
    """
    Insère directement en base de données un contrat structuré (après prévisualisation/modification NuExtract).
    """
    try:
        saved_contract = procurement_db.import_contract_with_items(
            contract_data=payload,
            project_id=str(payload.get("project_id") or "general"),
            document_path=str(payload.get("document_path") or "")
        )
        _safe_notify_vault()
        return {
            "status": "success",
            "contract": saved_contract
        }
    except Exception as e:
        logger.error(f"[Procurement API] Error importing structured contract JSON: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/procurement/contracts/{contract_id}/pdf")
async def download_procurement_contract_pdf(contract_id: str):
    """Télécharge ou affiche le PDF original du contrat."""
    c = procurement_db.get_contract(contract_id)
    if not c or not c.get("document_path"):
        raise HTTPException(status_code=404, detail="Aucun document PDF associé à ce contrat.")
    pdf_path = Path(c["document_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Fichier PDF introuvable sur le serveur.")
    return FileResponse(str(pdf_path), media_type="application/pdf", filename=pdf_path.name)

@router.put("/procurement/contracts/{contract_id}/document-path")
async def patch_procurement_contract_document_path(contract_id: str, payload: Dict[str, Any]):
    """Associe (ou remplace) le chemin vers le fichier PDF d'un contrat existant."""
    doc_path = str(payload.get("document_path") or "").strip()
    if not doc_path:
        raise HTTPException(status_code=400, detail="Le champ 'document_path' est obligatoire.")
    pdf_path = Path(doc_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"Fichier PDF introuvable : {doc_path}")
    try:
        conn = procurement_db.get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE contracts SET document_path = ?, updated_at = ? WHERE id = ?",
                (doc_path, datetime.now().isoformat(), contract_id)
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Contrat introuvable.")
            conn.commit()
        finally:
            conn.close()
        return {"status": "success", "document_path": doc_path}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Procurement API] Error patching document_path: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/procurement/contracts/{contract_id}")
async def update_procurement_contract(contract_id: str, contract: ContractCreate):
    try:
        procurement_db.update_contract(
            contract_id=contract_id,
            numero_contrat=contract.numero_contrat,
            fournisseur=contract.fournisseur,
            objet=contract.objet,
            date_signature=contract.date_signature,
            date_debut=contract.date_debut,
            date_fin_prevue=contract.date_fin_prevue,
            montant=contract.montant,
            devise=contract.devise,
            statut=contract.statut,
            document_path=contract.document_path,
            project_id=contract.project_id or "general",
            delai_livraison=contract.delai_livraison or ""
        )
        return {"status": "success"}
    except Exception as e:
        logger.error(f"[Procurement API] Error updating contract: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/procurement/contracts/{contract_id}")
async def delete_procurement_contract(contract_id: str):
    try:
        procurement_db.delete_contract(contract_id)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"[Procurement API] Error deleting contract: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/procurement/contracts/{contract_id}/items")
async def get_procurement_contract_items(contract_id: str):
    try:
        return procurement_db.get_contract_items(contract_id)
    except Exception as e:
        logger.error(f"[Procurement API] Error fetching contract items: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/procurement/contracts/{contract_id}/items")
async def create_procurement_contract_item(contract_id: str, item: ContractItemCreate):
    try:
        item_id = procurement_db.create_contract_item(
            contract_id=contract_id,
            designation=item.designation,
            reference=item.reference,
            quantite_contractuelle=item.quantite_contractuelle,
            unite=item.unite,
            prix_unitaire=item.prix_unitaire,
            delai_livraison=item.delai_livraison
        )
        return {"status": "success", "id": item_id}
    except Exception as e:
        logger.error(f"[Procurement API] Error creating contract item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/procurement/items/{item_id}")
async def update_procurement_item(item_id: str, item: ContractItemCreate, statut: Optional[str] = "non livré"):
    try:
        procurement_db.update_contract_item(
            item_id=item_id,
            designation=item.designation,
            reference=item.reference,
            quantite_contractuelle=item.quantite_contractuelle,
            unite=item.unite,
            prix_unitaire=item.prix_unitaire,
            delai_livraison=item.delai_livraison,
            statut=statut
        )
        return {"status": "success"}
    except Exception as e:
        logger.error(f"[Procurement API] Error updating item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/procurement/items/{item_id}")
async def delete_procurement_item(item_id: str):
    try:
        procurement_db.delete_contract_item(item_id)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"[Procurement API] Error deleting item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/procurement/stock")
async def get_procurement_stock():
    try:
        return procurement_db.get_realtime_stock()
    except Exception as e:
        logger.error(f"[Procurement API] Error fetching stock balance: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/procurement/receipts")
async def record_procurement_receipt(receipt: MaterialReceiptBatchCreate):
    try:
        items_list = [dict(it) for it in receipt.items]
        pv_number = procurement_db.receive_materials_batch(
            items_list=items_list,
            date_reception=receipt.date_reception,
            numero_bl=receipt.numero_bl,
            responsable=receipt.responsable,
            remarques=receipt.remarques or "",
            documents=receipt.documents or "",
            numero_pv=receipt.numero_pv
        )
        return {"status": "success", "numero_pv": pv_number}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Procurement API] Error recording receipt batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/procurement/issues")
async def record_procurement_issue(issue: MaterialIssueBatchCreate):
    try:
        items_list = [dict(it) for it in issue.items]
        pv_number = procurement_db.issue_materials_batch(
            items_list=items_list,
            date_sortie=issue.date_sortie,
            motif=issue.motif,
            destination=issue.destination,
            responsable=issue.responsable,
            numero_pv=issue.numero_pv
        )
        return {"status": "success", "numero_pv": pv_number}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Procurement API] Error recording issue batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/procurement/returns")
async def record_procurement_return(ret: MaterialReturnBatchCreate):
    try:
        items_list = [dict(it) for it in ret.items]
        pv_number = procurement_db.return_materials_batch(
            items_list=items_list,
            date_retour=ret.date_retour,
            motif=ret.motif,
            lieu_stockage=ret.lieu_stockage,
            responsable=ret.responsable,
            numero_pv=ret.numero_pv
        )
        return {"status": "success", "numero_pv": pv_number}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Procurement API] Error recording return batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/procurement/pvs")
async def get_procurement_pvs():
    try:
        return procurement_db.get_pvs()
    except Exception as e:
        logger.error(f"[Procurement API] Error fetching PVs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/procurement/pvs/{numero_pv}")
async def delete_procurement_pv(numero_pv: str):
    try:
        procurement_db.delete_pv(numero_pv)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"[Procurement API] Error deleting PV {numero_pv}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/procurement/pvs/{numero_pv}/html", response_class=HTMLResponse)
async def get_pv_printable_html(numero_pv: str):
    try:
        pv = procurement_db.get_pv_by_number(numero_pv)
        if not pv:
            raise HTTPException(status_code=404, detail="PV non trouvé")
            
        items = pv.get("items", [])
        first_item = items[0] if items else {}
        
        if pv["type_pv"] == "RECEIPT":
            type_lbl = "RÉCEPTION DE MATÉRIEL"
            date_lbl = first_item.get("date_reception", "")
        elif pv["type_pv"] == "ISSUE":
            type_lbl = "SORTIE DE MATÉRIEL"
            date_lbl = first_item.get("date_sortie", "")
        else:
            type_lbl = "RETOUR DE MATÉRIEL EN STOCK"
            date_lbl = first_item.get("date_retour", "")
            
        rows_html = ""
        total_operation_value = 0
        
        for it in items:
            qty = it.get("quantite_recue") or it.get("quantite_sortie") or it.get("quantite_retournee") or 0
            pu = it.get("prix_unitaire", 0)
            subtotal = qty * pu
            total_operation_value += subtotal
            
            desig = it.get("designation", "")
            ref = it.get("reference", "") or "-"
            unite = it.get("unite", "")
            
            if pv["type_pv"] == "RECEIPT":
                col_loc = it.get("lieu_stockage", "")
                col_status = it.get("etat", "conforme").upper()
                status_color = "#10B981" if col_status == "CONFORME" else "#EF4444"
            elif pv["type_pv"] == "ISSUE":
                col_loc = f"{it.get('destination', '')} ({it.get('motif', '')})"
                col_status = "VALIDÉ"
                status_color = "#10B981"
            else: # RETURN
                col_loc = it.get("lieu_stockage", "")
                col_status = f"RETOURNÉ ({it.get('motif', '')})"
                status_color = "#3B82F6"
                
            rows_html += f"""
            <tr>
                <td style="padding: 10px 12px; border-bottom: 1px solid #e5e7eb;">{desig}</td>
                <td style="padding: 10px 12px; border-bottom: 1px solid #e5e7eb;">{ref}</td>
                <td style="padding: 10px 12px; border-bottom: 1px solid #e5e7eb; text-align:right;"><strong>{qty}</strong></td>
                <td style="padding: 10px 12px; border-bottom: 1px solid #e5e7eb;">{unite}</td>
                <td style="padding: 10px 12px; border-bottom: 1px solid #e5e7eb; text-align:right;">{pu:,.2f} DZD</td>
                <td style="padding: 10px 12px; border-bottom: 1px solid #e5e7eb; text-align:right;">{subtotal:,.2f} DZD</td>
                <td style="padding: 10px 12px; border-bottom: 1px solid #e5e7eb;">{col_loc}</td>
                <td style="padding: 10px 12px; border-bottom: 1px solid #e5e7eb;"><span style="font-weight:600; color: {status_color}">{col_status}</span></td>
            </tr>
            """
            
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Procès-Verbal {pv["numero_pv"]}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            color: #1f2937;
            margin: 0;
            padding: 40px;
            background: #fff;
            line-height: 1.5;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid #d4a373;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        .logo {{
            font-size: 24px;
            font-weight: bold;
            color: #d4a373;
            letter-spacing: 0.1em;
        }}
        .pv-title {{
            font-size: 20px;
            font-weight: 700;
            color: #111827;
            text-align: right;
        }}
        .pv-number {{
            color: #d4a373;
            font-size: 16px;
            margin-top: 4px;
        }}
        .section-title {{
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #d4a373;
            border-bottom: 1px solid #e5e7eb;
            padding-bottom: 6px;
            margin-top: 30px;
            margin-bottom: 15px;
            font-weight: 600;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px 30px;
            font-size: 13px;
        }}
        .info-item {{
            display: flex;
            justify-content: space-between;
            border-bottom: 1px dashed #f3f4f6;
            padding-bottom: 4px;
        }}
        .info-label {{
            color: #6b7280;
            font-weight: 500;
        }}
        .info-val {{
            color: #111827;
            font-weight: 600;
            text-align: right;
        }}
        .details-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
            font-size: 13px;
        }}
        .details-table th {{
            background: #f9fafb;
            color: #4b5563;
            text-align: left;
            padding: 10px 12px;
            border-bottom: 1px solid #e5e7eb;
            font-weight: 600;
        }}
        .signatures-container {{
            display: flex;
            justify-content: space-between;
            margin-top: 60px;
            gap: 50px;
        }}
        .signature-box {{
            flex: 1;
            border: 1px solid #e5e7eb;
            border-radius: 6px;
            padding: 20px;
            text-align: center;
            background: #fafafa;
        }}
        .signature-title {{
            font-size: 12px;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 40px;
        }}
        .signature-name {{
            font-size: 13px;
            font-weight: 600;
            color: #111827;
            border-top: 1px solid #e5e7eb;
            padding-top: 8px;
        }}
        .footer {{
            margin-top: 100px;
            text-align: center;
            font-size: 11px;
            color: #9ca3af;
            border-top: 1px solid #e5e7eb;
            padding-top: 15px;
        }}
        @media print {{
            body {{
                padding: 20px;
            }}
            .signature-box {{
                background: none !important;
            }}
        }}
    </style>
</head>
<body onload="window.print()">
    <div class="header">
        <div>
            <div class="logo">ARKAN SYSTEMS</div>
            <div style="font-size: 11px; color: #6b7280; margin-top: 4px;">SYSTEME DE TRAÇABILITE & PROCUREMENT</div>
        </div>
        <div class="pv-title">
            <div>PROCES-VERBAL DE {type_lbl}</div>
            <div class="pv-number">{pv["numero_pv"]}</div>
        </div>
    </div>

    <div class="section-title">Informations Générales</div>
    <div class="info-grid">
        <div class="info-item">
            <span class="info-label">Numéro de Contrat :</span>
            <span class="info-val">{first_item.get("numero_contrat", "")}</span>
        </div>
        <div class="info-item">
            <span class="info-label">Fournisseur / Prestataire :</span>
            <span class="info-val">{first_item.get("fournisseur", "")}</span>
        </div>
        <div class="info-item">
            <span class="info-label">Date de l'Opération :</span>
            <span class="info-val">{date_lbl}</span>
        </div>
        <div class="info-item">
            <span class="info-label">Responsable ARKAN :</span>
            <span class="info-val">{pv["responsables"]}</span>
        </div>
        {"<div class='info-item'><span class='info-label'>Numéro de BL :</span><span class='info-val'>" + first_item.get("numero_bl","") + "</span></div>" if pv["type_pv"] == "RECEIPT" else ""}
    </div>

    <div class="section-title">Détails de l'Objet du Contrat</div>
    <div style="font-size: 13px; margin-bottom: 20px;">
        <strong>Objet :</strong> {first_item.get("objet", "")}
    </div>

    <div class="section-title">Désignation du Matériel Concerné</div>
    <table class="details-table">
        <thead>
            <tr>
                <th style="text-align:left;">Désignation Article</th>
                <th style="text-align:left;">Référence</th>
                <th style="text-align:right;">Quantité</th>
                <th style="text-align:left;">Unité</th>
                <th style="text-align:right;">Prix Unitaire</th>
                <th style="text-align:right;">Montant HT</th>
                <th style="text-align:left;">{ "Lieu Stockage" if pv["type_pv"] == "RECEIPT" or pv["type_pv"] == "RETURN" else "Destination / Motif" }</th>
                <th style="text-align:left;">Statut / État</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
            <tr style="background:#f9fafb; font-weight:700;">
                <td colspan="5" style="padding:12px; text-align:right; border-top: 2px solid #e5e7eb;">VALEUR TOTAL OPERATION (HT) :</td>
                <td style="padding:12px; text-align:right; border-top: 2px solid #e5e7eb; color:#d4a373;">{total_operation_value:,.2f} DZD</td>
                <td colspan="2" style="border-top: 2px solid #e5e7eb;"></td>
            </tr>
        </tbody>
    </table>

    <div class="signatures-container">
        <div class="signature-box">
            <div class="signature-title">Pour le Fournisseur / Client</div>
            <div class="signature-name">Nom et Signature</div>
        </div>
        <div class="signature-box">
            <div class="signature-title">Pour la Direction de Projet (ARKAN)</div>
            <div class="signature-name">{pv["responsables"]}</div>
        </div>
    </div>

    <div class="footer">
        Document officiel généré électroniquement par le système de gestion ARKAN EPC Intelligence.
    </div>
</body>
</html>
"""
        return HTMLResponse(content=html_content, status_code=200)
    except Exception as e:
        logger.error(f"[Procurement API] Error generating PV HTML: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# ── MTO to Procurement Injection & Comparison (ARKAN v3) ──

class MtoInjectionRequest(BaseModel):
    contract_id: str
    items: List[Dict[str, Any]]
    source_project: Optional[str] = "C3421-ROK1-SP1-OK1"

@router.post("/procurement/mto/inject")
def inject_mto_to_procurement(req: MtoInjectionRequest):
    """
    Injecte les articles validés du MTO dans un contrat d'achat / BoQ existant.
    Prend en compte la quantité à commander (avec marge) et la traçabilité.
    """
    try:
        contract = procurement_db.get_contract(req.contract_id)
        if not contract:
            raise HTTPException(status_code=404, detail=f"Contrat {req.contract_id} non trouvé.")

        injected_count = 0
        for it in req.items:
            desig = it.get("description") or it.get("designation") or "Article MTO"
            ref = it.get("tag") or it.get("size") or ""
            # Utilise la quantité à commander si disponible, sinon la quantité nette
            qty = float(it.get("quantity_ordered") or it.get("quantity") or 1.0)
            unit = str(it.get("unit") or "EA")
            unit_price = float(it.get("unit_price") or 0.0)

            procurement_db.create_contract_item(
                contract_id=req.contract_id,
                designation=desig,
                reference=ref,
                quantite_contractuelle=qty,
                unite=unit,
                prix_unitaire=unit_price,
                delai_livraison=str(it.get("source_drawing", "MTO"))
            )
            injected_count += 1

        _safe_notify_vault()
        return {
            "status": "success",
            "contract_id": req.contract_id,
            "injected_count": injected_count,
            "message": f"{injected_count} article(s) injecté(s) avec succès dans le contrat {req.contract_id}."
        }
    except Exception as e:
        logger.error(f"[Procurement API] Erreur injection MTO : {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/procurement/mto/compare/{project_id}")
def compare_mto_with_procurement(project_id: str):
    """
    Rapproche les quantités théoriques MTO et les quantités commandées / reçues au contrat
    pour dégager la balance des écarts (surplus ou pénuries de chantier).
    """
    try:
        contracts = procurement_db.get_contracts()
        project_contracts = [
            c for c in contracts
            if project_id.lower() in ("all", "*")
            or project_id.lower() in str(c.get("project_id", "")).lower()
            or str(c.get("project_id", "")).lower() in project_id.lower()
        ]

        comparison = []
        for c in project_contracts:
            c_id = c["id"]
            items = procurement_db.get_contract_items(c_id)
            for it in items:
                q_contract = float(it.get("quantite_contractuelle") or 0.0)
                q_recue = float(it.get("quantite_recue") or 0.0)
                delta = q_recue - q_contract
                comparison.append({
                    "contract_id": c_id,
                    "contract_number": c.get("numero_contrat"),
                    "fournisseur": c.get("fournisseur"),
                    "item_id": it.get("id"),
                    "designation": it.get("designation"),
                    "reference": it.get("reference"),
                    "quantite_commandee": q_contract,
                    "quantite_recue": q_recue,
                    "delta": delta,
                    "status": "CONFORME" if delta == 0 else ("SURPLUS" if delta > 0 else "MANQUANT"),
                    "unite": it.get("unite", "EA")
                })

        return {
            "status": "success",
            "project_id": project_id,
            "total_items_compared": len(comparison),
            "surplus_count": len([i for i in comparison if i["status"] == "SURPLUS"]),
            "shortage_count": len([i for i in comparison if i["status"] == "MANQUANT"]),
            "comparison": comparison
        }
    except Exception as e:
        logger.error(f"[Procurement API] Erreur comparaison MTO vs Achats : {e}")
        raise HTTPException(status_code=500, detail=str(e))
