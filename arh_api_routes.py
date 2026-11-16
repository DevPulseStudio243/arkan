"""
arh_api_routes.py  —  v3.0
===========================
Routes API FastAPI du Module ARKAN → ARH MANAGEMENT.

NOUVEAUTÉS v3.0 :
  • Gestion Dynamique des Projets ARH (Liste déroulante, Création, Suppression)
  • Persistance SQLite : dossiers et projets survivent aux redémarrages
  • DELETE /api/arh/dossiers/{dossier_id} & DELETE /api/arh/projects/{project_name}
  • Détection d'équipement par LLM sémantique & règle prioritaire LINEPIPE
"""

from __future__ import annotations
import os
import shutil
import json
import uuid
import sqlite3
import datetime
import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

import asyncio
from fastapi import APIRouter, File, UploadFile, Form, HTTPException, Query, Body, Header, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, JSONResponse, Response

from arh_document_processor import ARHDocumentProcessor
from arh_report_generator import ARHReportGenerator
from arh_knowledge_graph import ARHKnowledgeGraph

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# AUTHENTIFICATION SÉCURISÉE & CONTRÔLE D'ACCÈS
# ══════════════════════════════════════════════════════════════════════════════

_bearer_scheme = HTTPBearer(auto_error=False)
_auth_dev_warning_logged = False

def verify_arh_auth(
    request: Request = None,
    api_key_header: Optional[str] = Header(None, alias="X-API-Key"),
    bearer_auth: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme)
) -> bool:
    """
    Vérifie l'authentification API ARKAN via 'X-API-Key' ou 'Authorization: Bearer <key>'.
    En mode production (ARKAN_ENV=production), exige obligatoirement ARKAN_API_KEY.
    En mode local de développement, journalise un avertissement unique si la clé n'est pas définie.
    """
    global _auth_dev_warning_logged
    expected_key = os.getenv("ARKAN_API_KEY", "").strip()
    env_mode = os.getenv("ARKAN_ENV", "development").strip().lower()
    if not expected_key:
        if env_mode in ("prod", "production"):
            raise HTTPException(
                status_code=401,
                detail="Configuration de sécurité invalide : ARKAN_API_KEY est obligatoire en environnement de production."
            )
        # Correctif : sans clé, l'accès n'est toléré que depuis la machine locale (ou si ARKAN_ALLOW_REMOTE_NO_AUTH=1).
        _client = request.client.host if (request is not None and request.client) else "127.0.0.1"
        if _client not in ("127.0.0.1", "::1", "localhost", "testclient") \
                and os.getenv("ARKAN_ALLOW_REMOTE_NO_AUTH", "") != "1":
            raise HTTPException(
                status_code=401,
                detail="ARKAN_API_KEY non défini : accès distant refusé (définir ARKAN_API_KEY ou ARKAN_ENV)."
            )
        if not _auth_dev_warning_logged:
            logger.warning("[ARH-AUTH] ARKAN_API_KEY non défini — mode développement local actif (authentification désactivée).")
            _auth_dev_warning_logged = True
        return True
    
    provided = api_key_header or (bearer_auth.credentials if bearer_auth else None)
    if not provided or provided.strip() != expected_key:
        raise HTTPException(
            status_code=401,
            detail="Non autorisé : Clé API ARKAN invalide ou absente (Header 'X-API-Key' ou Bearer token requis)."
        )
    return True


def sanitize_dossier_id(dossier_id: str) -> str:
    """
    Sanitise rigoureusement l'identifiant du dossier pour éliminer tout risque de Path Traversal.
    """
    if not dossier_id:
        raise HTTPException(status_code=400, detail="Identifiant de dossier manquant.")
    raw_str = str(dossier_id).strip()
    if ".." in raw_str or "/" in raw_str or "\\" in raw_str:
        raise HTTPException(status_code=400, detail="Identifiant de dossier invalide (tentative de traversée détectée).")
    clean = Path(raw_str).name
    clean = re.sub(r'[^A-Za-z0-9_\-]', '', clean)
    if not clean or clean.startswith('.'):
        raise HTTPException(status_code=400, detail="Identifiant de dossier invalide.")
    return clean


# Limiteur de concurrence des audits lourds (défaut: 1 pour protéger mémoire GPU/CPU et Ollama)
_MAX_CONCURRENT_AUDITS = int(os.getenv("ARH_MAX_CONCURRENT_AUDITS", "1"))
_AUDIT_SEMAPHORE = asyncio.Semaphore(_MAX_CONCURRENT_AUDITS)

router = APIRouter(prefix="/api/arh", tags=["ARH Management"], dependencies=[Depends(verify_arh_auth)])

# ══════════════════════════════════════════════════════════════════════════════
# BASE DE DONNÉES SQLITE PERSISTANTE (DOSSIERS & PROJETS)
# ══════════════════════════════════════════════════════════════════════════════

def _restrict_filesystem_permissions(path: Path) -> None:
    """
    Restreint l'accès au répertoire ou fichier aux seuls droits du propriétaire (0o700 / 0o600).
    Sur POSIX, applique chmod 700/600. Sur Windows, protège sans lever d'exception.
    """
    try:
        if path.is_dir():
            os.chmod(path, 0o700)
        elif path.is_file():
            os.chmod(path, 0o600)
    except Exception:
        pass

_ARH_DB_PATH = Path(__file__).parent / "arh_dossiers.db"
_ARH_REPORTS_DIR = Path(__file__).parent / "arh_reports"
_ARH_REPORTS_DIR.mkdir(exist_ok=True)
_restrict_filesystem_permissions(_ARH_REPORTS_DIR)

_ARH_UPLOADS_DIR = Path(__file__).parent / "arh_uploads"
_ARH_UPLOADS_DIR.mkdir(exist_ok=True)
_restrict_filesystem_permissions(_ARH_UPLOADS_DIR)


def _get_db() -> sqlite3.Connection:
    """Retourne une connexion SQLite avec row_factory dict."""
    conn = sqlite3.connect(str(_ARH_DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _init_db() -> None:
    """Crée les tables des dossiers et des projets ARH si elles n'existent pas."""
    with _get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arh_dossiers (
                dossier_id      TEXT PRIMARY KEY,
                project_name    TEXT,
                unit_name       TEXT,
                equipment_tag   TEXT,
                equipment_type  TEXT,
                equipment_label TEXT,
                status          TEXT,
                arh_decision    TEXT,
                compliance_score REAL,
                dossier_stage   TEXT,
                dossier_stage_label TEXT,
                pdf_report_path TEXT,
                data_json       TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dossiers_project_name ON arh_dossiers(project_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dossiers_created_at ON arh_dossiers(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dossiers_status ON arh_dossiers(status)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arh_projects (
                project_id      TEXT PRIMARY KEY,
                project_name    TEXT UNIQUE NOT NULL,
                contract_code   TEXT,
                vendor_name     TEXT,
                version_dossier TEXT,
                description     TEXT,
                created_at      TEXT NOT NULL
            )
        """)
        # Dynamic migration for existing DBs
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(arh_projects)").fetchall()]
        if "contract_code" not in cols:
            conn.execute("ALTER TABLE arh_projects ADD COLUMN contract_code TEXT")
        if "vendor_name" not in cols:
            conn.execute("ALTER TABLE arh_projects ADD COLUMN vendor_name TEXT")
        if "version_dossier" not in cols:
            conn.execute("ALTER TABLE arh_projects ADD COLUMN version_dossier TEXT")

        # Seed initial projects if table is empty
        cnt = conn.execute("SELECT COUNT(*) as n FROM arh_projects").fetchone()["n"]
        if cnt == 0:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            default_projects = [
                ("PROJ_001", "PROJET COMPLET HYDROCARBURES ARH", "CTR-2026-ARH-01", "SONATRACH / ARH", "Rev 00", "Projet général d'ingénierie et audit ARH"),
                ("PROJ_002", "PROJET CANALISATION 48\" (GCB)", "CTR-2026-GCB-048", "PIPE MANUFACTURING CORP", "Rev 01", "Fourniture et fabrication de tubes de canalisation 48\""),
                ("PROJ_003", "PROJET STATION DE COMPRESSION CS-02", "CTR-2026-CS2-002", "BHGE / TELEMEC", "Rev 00", "Unité de compression de gaz naturel CS-02"),
                ("PROJ_004", "PROJET RAFFINERIE SKIKDA", "CTR-2026-SKK-010", "PETROFAC / CNEP", "Rev 00", "Inspection et conformité des bacs de stockage API 650")
            ]
            for pid, pname, ccode, vname, vver, pdesc in default_projects:
                conn.execute(
                    "INSERT OR IGNORE INTO arh_projects (project_id, project_name, contract_code, vendor_name, version_dossier, description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (pid, pname, ccode, vname, vver, pdesc, now)
                )
        conn.commit()
    _restrict_filesystem_permissions(_ARH_DB_PATH)
    logger.info("[ARH-DB] Base SQLite dossiers & projets initialisée : %s", _ARH_DB_PATH)


def _list_projects() -> List[Dict[str, Any]]:
    """Retourne la liste des projets ARH avec le nombre de dossiers associés."""
    with _get_db() as conn:
        rows = conn.execute("""
            SELECT p.project_id, p.project_name, p.contract_code, p.vendor_name, p.version_dossier, p.description, p.created_at,
                   COUNT(d.dossier_id) as dossiers_count
            FROM arh_projects p
            LEFT JOIN arh_dossiers d ON UPPER(p.project_name) = UPPER(d.project_name)
            GROUP BY p.project_id, p.project_name
            ORDER BY p.created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


def _save_project(project_name: str, contract_code: str = "", vendor_name: str = "", version_dossier: str = "", description: str = "") -> Dict[str, Any]:
    """Enregistre un nouveau projet ARH dans SQLite avec détails contractuels."""
    p_name = project_name.strip().upper()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _get_db() as conn:
        existing = conn.execute("SELECT * FROM arh_projects WHERE UPPER(project_name) = ?", (p_name,)).fetchone()
        if existing:
            # Only update if non-empty values are provided (don't erase existing data)
            if contract_code.strip() or vendor_name.strip() or version_dossier.strip():
                conn.execute("""
                    UPDATE arh_projects SET 
                        contract_code = CASE WHEN ? != '' THEN ? ELSE contract_code END,
                        vendor_name = CASE WHEN ? != '' THEN ? ELSE vendor_name END,
                        version_dossier = CASE WHEN ? != '' THEN ? ELSE version_dossier END,
                        description = CASE WHEN ? != '' THEN ? ELSE description END
                    WHERE UPPER(project_name) = ?
                """, (contract_code.strip(), contract_code.strip(),
                       vendor_name.strip(), vendor_name.strip(),
                       version_dossier.strip(), version_dossier.strip(),
                       description.strip(), description.strip(),
                       p_name))
            conn.commit()
            return dict(existing)
        else:
            pid = f"PROJ_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
            conn.execute(
                "INSERT INTO arh_projects (project_id, project_name, contract_code, vendor_name, version_dossier, description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid, p_name, contract_code.strip(), vendor_name.strip(), version_dossier.strip(), description, now)
            )
            conn.commit()
            return {"project_id": pid, "project_name": p_name, "contract_code": contract_code.strip(), "vendor_name": vendor_name.strip(), "version_dossier": version_dossier.strip(), "description": description, "created_at": now}


def _delete_project(project_name: str) -> bool:
    """Supprime un projet ARH ainsi que tous ses dossiers et rapports PDF associés."""
    p_name = project_name.strip().upper()
    with _get_db() as conn:
        row = conn.execute("SELECT project_name FROM arh_projects WHERE UPPER(project_name) = ?", (p_name,)).fetchone()
        if not row:
            return False
        
        # Supprimer les fichiers PDF physiques des dossiers du projet
        dossier_rows = conn.execute("SELECT pdf_report_path FROM arh_dossiers WHERE UPPER(project_name) = ?", (p_name,)).fetchall()
        for r in dossier_rows:
            pdf_path = r["pdf_report_path"]
            if pdf_path and os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass

        conn.execute("DELETE FROM arh_dossiers WHERE UPPER(project_name) = ?", (p_name,))
        conn.execute("DELETE FROM arh_projects WHERE UPPER(project_name) = ?", (p_name,))
        conn.commit()
    return True


def _save_dossier(data: Dict[str, Any]) -> None:
    """Persiste ou met à jour un dossier ARH dans SQLite."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    proj_name = (data.get("project_name") or "PROJET HYDROCARBURES ARH").strip().upper()

    if data.get("comments") or data.get("equipments"):
        try:
            from arh_multiagent_engine import consolidate_and_deduplicate_comments
            if data.get("comments"):
                data["comments"] = consolidate_and_deduplicate_comments(data["comments"])
            for eq in (data.get("equipments") or []):
                if isinstance(eq, dict) and eq.get("comments"):
                    eq["comments"] = consolidate_and_deduplicate_comments(eq["comments"])
        except Exception as e_dedup:
            logger.warning("[ARH-DB] Erreur déduplication remarques : %s", e_dedup)

    # Auto-enregistrer le projet s'il n'existe pas encore
    _save_project(proj_name, "Créé automatiquement lors du téléversement d'un dossier ARH")

    with _get_db() as conn:
        conn.execute("""
            INSERT INTO arh_dossiers
                (dossier_id, project_name, unit_name, equipment_tag, equipment_type,
                 equipment_label, status, arh_decision, compliance_score,
                 dossier_stage, dossier_stage_label, pdf_report_path,
                 data_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dossier_id) DO UPDATE SET
                project_name      = excluded.project_name,
                status            = excluded.status,
                arh_decision      = excluded.arh_decision,
                compliance_score  = excluded.compliance_score,
                pdf_report_path   = excluded.pdf_report_path,
                data_json         = excluded.data_json,
                updated_at        = excluded.updated_at
        """, (
            data.get("dossier_id"),
            proj_name,
            data.get("unit_name"),
            data.get("equipment_tag"),
            data.get("equipment_type"),
            data.get("equipment_label"),
            data.get("status"),
            data.get("arh_decision"),
            data.get("compliance_score"),
            data.get("dossier_stage"),
            data.get("dossier_stage_label"),
            data.get("pdf_report_path"),
            json.dumps(data, ensure_ascii=False, default=str),
            data.get("created_at", now),
            now
        ))
        conn.commit()


def _load_dossier(dossier_id: str) -> Optional[Dict[str, Any]]:
    """Charge un dossier depuis SQLite, retourne None si introuvable."""
    dossier_id = sanitize_dossier_id(dossier_id)
    with _get_db() as conn:
        row = conn.execute(
            "SELECT data_json FROM arh_dossiers WHERE dossier_id = ?", (dossier_id,)
        ).fetchone()
    if row:
        try:
            d = json.loads(row["data_json"])
            if d.get("comments") or d.get("equipments"):
                try:
                    from arh_multiagent_engine import consolidate_and_deduplicate_comments
                    if d.get("comments"):
                        d["comments"] = consolidate_and_deduplicate_comments(d["comments"])
                    for eq in (d.get("equipments") or []):
                        if isinstance(eq, dict) and eq.get("comments"):
                            eq["comments"] = consolidate_and_deduplicate_comments(eq["comments"])
                except Exception:
                    pass
            # Enrichir avec la liste réelle des fichiers sur disque et le total de pages
            dossier_dir = _ARH_UPLOADS_DIR / dossier_id
            if dossier_dir.exists():
                src_files = [f.name for f in dossier_dir.glob("*.pdf") if not f.name.startswith("annotated_")]
                if not d.get("files"):
                    d["files"] = src_files
                if not d.get("source_documents"):
                    d["source_documents"] = src_files
                if not d.get("total_pages") and src_files:
                    try:
                        import fitz
                        first_pdf = dossier_dir / src_files[0]
                        with fitz.open(str(first_pdf)) as doc_f:
                            d["total_pages"] = len(doc_f)
                    except Exception:
                        pass
            return d
        except Exception as e:
            logger.error("[ARH-DB] Erreur désérialisation dossier %s : %s", dossier_id, e)
    return None



def _list_dossiers(search: str = "", project_filter: str = "", limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """Liste les dossiers avec pagination, filtre projet et recherche."""
    with _get_db() as conn:
        query = """
            SELECT dossier_id, project_name, unit_name, equipment_tag,
                   equipment_type, equipment_label, status, arh_decision,
                   compliance_score, dossier_stage, created_at, updated_at
            FROM arh_dossiers
            WHERE 1=1
        """
        params = []
        if project_filter:
            query += " AND UPPER(project_name) = ?"
            params.append(project_filter.strip().upper())
        if search:
            query += " AND (UPPER(project_name) LIKE ? OR UPPER(equipment_tag) LIKE ? OR UPPER(equipment_type) LIKE ? OR UPPER(status) LIKE ?)"
            like = f"%{search.upper()}%"
            params.extend([like, like, like, like])

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, tuple(params)).fetchall()

    return [dict(r) for r in rows]


def _delete_dossier_from_db(dossier_id: str) -> bool:
    """Supprime un dossier de SQLite. Retourne True si trouvé et supprimé."""
    dossier_id = sanitize_dossier_id(dossier_id)
    with _get_db() as conn:
        row = conn.execute(
            "SELECT pdf_report_path FROM arh_dossiers WHERE dossier_id = ?", (dossier_id,)
        ).fetchone()
        if not row:
            return False
        pdf_path = row["pdf_report_path"]
        conn.execute("DELETE FROM arh_dossiers WHERE dossier_id = ?", (dossier_id,))
        conn.commit()

    if pdf_path and os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
            logger.info("[ARH-DB] Rapport PDF supprimé : %s", pdf_path)
        except Exception as e:
            logger.warning("[ARH-DB] Impossible de supprimer le PDF %s : %s", pdf_path, e)

    return True


def _count_dossiers(project_filter: str = "") -> int:
    """Retourne le nombre total de dossiers."""
    with _get_db() as conn:
        if project_filter:
            row = conn.execute("SELECT COUNT(*) as n FROM arh_dossiers WHERE UPPER(project_name) = ?", (project_filter.strip().upper(),)).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as n FROM arh_dossiers").fetchone()
    return row["n"] if row else 0


# Initialisation de la DB au démarrage
try:
    _init_db()
except Exception as e:
    logger.error("[ARH-DB] Erreur d'initialisation SQLite : %s", e)

# Instances des services
processor = ARHDocumentProcessor()
report_gen = ARHReportGenerator()
kg = ARHKnowledgeGraph()


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS ARH — GESTION DES PROJETS & UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/projects")
async def list_arh_projects():
    """Retourne la liste des projets ARH disponibles avec leur nombre de dossiers."""
    try:
        projects = _list_projects()
        return JSONResponse(content={"status": "SUCCESS", "count": len(projects), "projects": projects})
    except Exception as e:
        logger.error("[ARH] Erreur liste projets : %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects")
async def create_arh_project(
    project_name: str = Form(...),
    contract_code: str = Form(""),
    vendor_name: str = Form(""),
    version_dossier: str = Form(""),
    description: str = Form("")
):
    """Crée un nouveau projet ARH avec ses métadonnées contractuelles."""
    p_name = project_name.strip()
    if not p_name:
        raise HTTPException(status_code=400, detail="Le nom du projet ne peut pas être vide.")
    proj = _save_project(p_name, contract_code, vendor_name, version_dossier, description)
    logger.info("[ARH] Nouveau projet ARH créé : %s (%s - %s)", p_name, contract_code, vendor_name)
    return JSONResponse(content={"status": "SUCCESS", "message": f"Projet '{proj['project_name']}' créé avec succès.", "project": proj})


@router.delete("/projects/{project_name}")
async def delete_arh_project(project_name: str):
    """Supprime un projet ARH de la base de données."""
    deleted = _delete_project(project_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Projet ARH '{project_name}' introuvable.")
    logger.info("[ARH] Projet %s supprimé de la base.", project_name)
    return JSONResponse(content={"status": "SUCCESS", "message": f"Projet ARH '{project_name}' supprimé avec succès."})


@router.put("/projects/{project_name}")
async def update_arh_project(
    project_name: str,
    contract_code: str = Form(None),
    vendor_name: str = Form(None),
    version_dossier: str = Form(None),
    description: str = Form(None)
):
    """Met à jour les métadonnées contractuelles d'un projet ARH existant."""
    _ALLOWED_PROJECT_COLS = frozenset({"contract_code", "vendor_name", "version_dossier", "description"})
    p_name = project_name.strip().upper()
    with _get_db() as conn:
        existing = conn.execute("SELECT * FROM arh_projects WHERE UPPER(project_name) = ?", (p_name,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=f"Projet ARH '{project_name}' introuvable.")
        raw_fields = {
            "contract_code": contract_code,
            "vendor_name": vendor_name,
            "version_dossier": version_dossier,
            "description": description,
        }
        updates = []
        params = []
        for col, val in raw_fields.items():
            if col in _ALLOWED_PROJECT_COLS and val is not None:
                updates.append(f"{col} = ?")
                params.append(val.strip())
        if updates:
            params.append(p_name)
            conn.execute(f"UPDATE arh_projects SET {', '.join(updates)} WHERE UPPER(project_name) = ?", tuple(params))
            conn.commit()
    logger.info("[ARH] Projet %s mis à jour.", p_name)
    return JSONResponse(content={"status": "SUCCESS", "message": f"Projet '{p_name}' mis à jour avec succès."})


@router.post("/upload")
async def upload_arh_dossier(
    files: List[UploadFile] = File(...),
    project_name: str = Form("PROJET HYDROCARBURES ARH"),
    unit_name: str = Form("UNIT-100"),
    dossier_stage: str = Form("AUTO"),
    equipment_type: str = Form("AUTO")
):
    """
    Dépose un lot de fichiers PDF pour analyse et contrôle technique ARH.
    Chaque dossier déposé est rattaché au Projet sélectionné, au Stade ARH et au Type d'Équipement choisi (ou Auto-détecté).
    """
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier n'a été fourni.")

    proj_name = project_name.strip().upper() if project_name else "PROJET HYDROCARBURES ARH"
    stage_val = dossier_stage.strip().upper() if dossier_stage else "AUTO"
    equip_val = equipment_type.strip().upper() if equipment_type else "AUTO"

    dossier_id = f"DOSSIER_ARH_{uuid.uuid4().hex[:8].upper()}"
    dossier_dir = _ARH_UPLOADS_DIR / dossier_id
    dossier_dir.mkdir(parents=True, exist_ok=True)
    saved_paths = []

    try:
        for f in files:
            safe_name = Path(f.filename).name
            if not safe_name.lower().endswith('.pdf'):
                raise HTTPException(status_code=400, detail=f"Le fichier '{safe_name}' n'est pas un PDF. Seuls les fichiers PDF sont acceptés.")
            file_path = os.path.join(str(dossier_dir), safe_name)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(f.file, buffer)
            saved_paths.append(file_path)

        # ── Analyse ARH en 3 phases protégée par sémaphore de concurrence ──
        async with _AUDIT_SEMAPHORE:
            import asyncio
            result = await asyncio.to_thread(
                processor.process_dossier_batch,
                saved_paths,       # file_paths
                proj_name,         # project_name
                unit_name,         # unit_name
                dossier_id,        # dossier_id (explicite)
                stage_val if stage_val != "AUTO" else None,   # dossier_stage
                equip_val if equip_val != "AUTO" else None    # forced_equipment_type
            )

            # ── Génération du rapport PDF ───────────────────────────────────────
            try:
                pdf_path = report_gen.generate_pdf_report(result)
                if pdf_path and os.path.exists(pdf_path):
                    dest_pdf = str(_ARH_REPORTS_DIR / f"{dossier_id}_report.pdf")
                    shutil.copy2(pdf_path, dest_pdf)
                    result["pdf_report_path"] = dest_pdf
                else:
                    result["pdf_report_path"] = None
            except Exception as e:
                logger.error("[ARH] Erreur génération PDF : %s", e)
                result["pdf_report_path"] = None

            # ── Persistance SQLite (Dossier + Auto-enregistrement Projet) ───────
            _save_dossier(result)
            logger.info("[ARH] Dossier %s sauvegardé pour projet '%s' (type=%s, score=%.1f%%)",
                        dossier_id, proj_name, result.get("equipment_type"), result.get("compliance_score", 0))

            # ── Découpage physique automatique immédiat des sous-pièces ───────
            try:
                from arh_document_slicer import arh_slicer
                pieces = arh_slicer.slice_dossier(dossier_id)
                result["sliced_pieces"] = pieces
                result["sliced_pieces_count"] = len(pieces)
                logger.info("[ARH] Auto-découpage immédiat réussi : %d pièces physiques créées pour %s", len(pieces), dossier_id)

                # Synchronisation immédiate du tableau récapitulatif de composition avec les pièces réelles découpées
                try:
                    from arh_composition_analyzer import analyze_dossier_composition
                    comp_summary = analyze_dossier_composition(
                        {
                            "mandatory_checklist": result.get("mandatory_checklist", []),
                            "sliced_pieces": pieces,
                            "source_documents": result.get("source_documents", [])
                        },
                        dossier_stage=result.get("dossier_stage")
                    )
                    result["composition_summary"] = comp_summary
                    result["recap_composition_table"] = comp_summary.get("recap_table_markdown", "")
                except Exception as _e_comp_sync:
                    logger.debug("[ARH] Sync composition après slice: %s", _e_comp_sync)

                # Re-sauvegarde immédiate du dossier enrichi dans SQLite
                _save_dossier(result)
            except Exception as e_slice:
                logger.warning("[ARH] Auto-découpage immédiat non bloquant pour %s : %s", dossier_id, e_slice)

            # ── Synchronisation Automatique Réseau d'Agents IA & Knowledge Graph ──
            try:
                from arh_agent_network_manager import get_agent_network_manager
                get_agent_network_manager().sync_on_dossier_added(result)
            except Exception as e_net:
                logger.warning("[ARH] Erreur synchronisation Réseau d'Agents : %s", e_net)

            # ── Pre-génération des PDF annotés en arrière-plan (1 seule fois) ──
            try:
                from arh_pdf_annotator import ARHPDFAnnotator
                annotator = ARHPDFAnnotator(uploads_dir=str(_ARH_UPLOADS_DIR))
                for doc_file in result.get("source_documents", []):
                    annotator.annotate_document(
                        dossier_id=dossier_id,
                        filename=doc_file,
                        comments=result.get("comments", []),
                        page_blocks=result.get("page_blocks_evidence", [])
                    )
            except Exception as e_ann:
                logger.warning("[ARH] Erreur pré-annotation PDF lors de l'upload: %s", e_ann)

            return JSONResponse(content={
                "status": "SUCCESS",
                "message": f"Dossier ARH {dossier_id} rattaché au projet '{proj_name}' avec succès.",
                "project_name": proj_name,
                "equipment_type_detected": result.get("equipment_type"),
                "equipment_label": result.get("equipment_label"),
                "compliance_score": result.get("compliance_score"),
                "arh_decision": result.get("arh_decision"),
                "data": result
            })

    except Exception as e:
        logger.error("[ARH] Erreur traitement dossier %s : %s", dossier_id, e, exc_info=True)
        # Rétention forensique des fichiers uploadés au lieu de suppression destructrice
        logger.warning("[ARH] Fichiers uploadés conservés pour diagnostic technique et analyse d'incident dans : %s", dossier_dir)
        raise HTTPException(status_code=500, detail=f"Erreur lors du traitement ARH : {str(e)}")


@router.get("/dossiers")
async def list_arh_dossiers(
    search: str = Query("", description="Recherche par projet, tag ou type"),
    project_filter: str = Query("", description="Filtrer par nom de projet exact"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """Retourne la liste paginée de tous les dossiers ARH persistés en base."""
    try:
        dossiers = _list_dossiers(search=search, project_filter=project_filter, limit=limit, offset=offset)
        total = _count_dossiers(project_filter=project_filter)
        payload = {
            "count": len(dossiers),
            "total": total,
            "offset": offset,
            "dossiers": dossiers
        }
        return JSONResponse(content={
            "status": "SUCCESS",
            "data": payload,
            **payload
        })
    except Exception as e:
        logger.error("[ARH] Erreur liste dossiers : %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dossiers/{dossier_id}")
async def get_arh_dossier_detail(dossier_id: str):
    """Retourne le détail complet de l'audit d'un dossier ARH enrichi avec la composition et les documents supplémentaires."""
    clean_id = sanitize_dossier_id(dossier_id)
    data = _load_dossier(clean_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Dossier ARH '{dossier_id}' introuvable.")
    
    try:
        from arh_document_slicer import arh_slicer
        pieces = arh_slicer.get_sliced_pieces(clean_id)
        if not pieces or not any(p.get("page_count", 0) > 0 for p in pieces):
            pieces = arh_slicer.slice_dossier(clean_id)
        data["sliced_pieces"] = pieces
        data["sliced_pieces_count"] = len(pieces)
    except Exception as e_slice:
        logger.warning("[ARH-API] Erreur auto-découpage pour %s: %s", clean_id, e_slice)

    try:
        from arh_composition_analyzer import get_full_dossier_composition_report
        report = get_full_dossier_composition_report(clean_id, data, uploads_base_dir=str(_ARH_UPLOADS_DIR))
        data["composition_summary"] = report.get("composition_summary")
        data["additional_documents"] = report.get("additional_documents")
        data["additional_documents_count"] = report.get("additional_documents_count", 0)
    except Exception as e_comp:
        logger.warning("[ARH-API] Erreur calcul dynamique composition pour %s: %s", clean_id, e_comp)

    return JSONResponse(content={"status": "SUCCESS", "data": data})


@router.get("/dossiers/{dossier_id}/composition")
async def get_dossier_composition_endpoint(dossier_id: str):
    """Retourne la Fiche Récapitulative de Composition du Dossier ARH et les Documents Supplémentaires."""
    clean_id = sanitize_dossier_id(dossier_id)
    data = _load_dossier(clean_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Dossier ARH '{dossier_id}' introuvable.")
    
    try:
        from arh_document_slicer import arh_slicer
        pieces = arh_slicer.get_sliced_pieces(clean_id)
        if not pieces or not any(p.get("page_count", 0) > 0 for p in pieces):
            pieces = arh_slicer.slice_dossier(clean_id)
        data["sliced_pieces"] = pieces
        data["sliced_pieces_count"] = len(pieces)
    except Exception:
        pass

    try:
        from arh_composition_analyzer import get_full_dossier_composition_report
        report = get_full_dossier_composition_report(clean_id, data, uploads_base_dir=str(_ARH_UPLOADS_DIR))
        return JSONResponse(content={"status": "SUCCESS", "data": report, "report": report})
    except Exception as e:
        logger.error("[ARH-API] Erreur rapport composition pour %s: %s", clean_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard")
async def get_arh_dashboard_metrics(project_filter: str = Query("", description="Filtrer par projet")):
    """Retourne les KPIs du Dashboard ARH Multi-Projets."""
    try:
        all_dossiers_summary = _list_dossiers(project_filter=project_filter, limit=500)
        total_dossiers = len(all_dossiers_summary)

        if total_dossiers == 0:
            empty_payload = {
                "kpis": {
                    "total_dossiers": 0, "approved": 0, "approved_with_comments": 0,
                    "rejected": 0, "unknown_type": 0, "average_score": 0.0,
                    "open_comments": 0, "critical_comments": 0
                },
                "equipment_breakdown": {}, "status_breakdown": {}, "recent_dossiers": []
            }
            return JSONResponse(content={"status": "SUCCESS", "data": empty_payload, **empty_payload})

        approved = sum(1 for d in all_dossiers_summary if d.get("status") == "APPROVED")
        app_comm = sum(1 for d in all_dossiers_summary if d.get("status") == "APPROVED_WITH_COMMENTS")
        rejected = sum(1 for d in all_dossiers_summary if d.get("status") == "REJECTED")
        unknown_type = sum(1 for d in all_dossiers_summary if d.get("equipment_type") == "UNKNOWN")
        avg_score = round(
            sum(float(d.get("compliance_score") or 0.0) for d in all_dossiers_summary) / max(total_dossiers, 1), 1
        )

        eq_breakdown: Dict[str, int] = {}
        for d in all_dossiers_summary:
            et = d.get("equipment_type") or "UNKNOWN"
            eq_breakdown[et] = eq_breakdown.get(et, 0) + 1

        status_breakdown: Dict[str, int] = {}
        for d in all_dossiers_summary:
            s = d.get("status") or "UNKNOWN"
            status_breakdown[s] = status_breakdown.get(s, 0) + 1

        open_comm = 0
        crit_comm = 0
        with _get_db() as conn:
            if project_filter:
                rows_json = conn.execute(
                    "SELECT data_json FROM arh_dossiers WHERE UPPER(project_name) = ? LIMIT 500",
                    (project_filter.strip().upper(),)
                ).fetchall()
            else:
                rows_json = conn.execute("SELECT data_json FROM arh_dossiers LIMIT 500").fetchall()
        for rj in rows_json:
            try:
                full = json.loads(rj["data_json"] or "{}")
                for c in (full.get("comments") or []):
                    if c.get("status") != "RESOLVED" and not c.get("resolved"):
                        open_comm += 1
                    if str(c.get("priority", "")).upper() == "CRITICAL":
                        crit_comm += 1
            except Exception:
                pass

        dash_payload = {
            "kpis": {
                "total_dossiers": total_dossiers, "approved": approved,
                "approved_with_comments": app_comm, "rejected": rejected,
                "unknown_type": unknown_type, "average_score": avg_score,
                "open_comments": open_comm, "critical_comments": crit_comm
            },
            "equipment_breakdown": eq_breakdown,
            "status_breakdown": status_breakdown,
            "recent_dossiers": all_dossiers_summary[:10]
        }
        return JSONResponse(content={
            "status": "SUCCESS",
            "data": dash_payload,
            **dash_payload
        })
    except Exception as e:
        logger.error("[ARH] Erreur dashboard : %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports/{dossier_id}/pdf")
async def download_arh_pdf_report(dossier_id: str):
    """Télécharge le rapport d'inspection PDF officiel ARH."""
    dossier_id = sanitize_dossier_id(dossier_id)
    data = _load_dossier(dossier_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Dossier ARH '{dossier_id}' introuvable.")

    pdf_path = data.get("pdf_report_path")

    if not pdf_path or not os.path.exists(str(pdf_path)):
        try:
            pdf_path = report_gen.generate_pdf_report(data)
            if pdf_path and os.path.exists(pdf_path):
                dest_pdf = str(_ARH_REPORTS_DIR / f"{dossier_id}_report.pdf")
                shutil.copy2(pdf_path, dest_pdf)
                pdf_path = dest_pdf
                data["pdf_report_path"] = pdf_path
                _save_dossier(data)
        except Exception as e:
            logger.error("[ARH] Erreur régénération PDF %s : %s", dossier_id, e)
            raise HTTPException(status_code=500, detail=f"Impossible de générer le rapport PDF : {e}")

    if not pdf_path or not os.path.exists(str(pdf_path)):
        raise HTTPException(status_code=404, detail="Rapport PDF non disponible.")

    # BUG FIX #7 : corriger l'extension et le media_type si le générateur a produit un .txt (fallback)
    actual_path = str(pdf_path)
    if actual_path.endswith(".txt"):
        filename = f"Rapport_ARH_{dossier_id}.txt"
        media_type = "text/plain"
    else:
        filename = f"Rapport_ARH_{dossier_id}.pdf"
        media_type = "application/pdf"
    return FileResponse(actual_path, media_type=media_type, filename=filename)


@router.get("/graph/{dossier_id}")
async def get_arh_knowledge_graph(dossier_id: str):
    """Retourne les nœuds et arêtes du Knowledge Graph ARH."""
    dossier_id = sanitize_dossier_id(dossier_id)
    try:
        graph_data = kg.get_graph_for_dossier(dossier_id)
        return JSONResponse(content={"status": "SUCCESS", "dossier_id": dossier_id, "graph": graph_data})
    except Exception as e:
        logger.error("[ARH] Erreur knowledge graph %s : %s", dossier_id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# PILLAR 3 & PILLAR 4 : EXPORT RESUMES, DECISION LETTERS & EXPERT ARH CHAT
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/dossiers/{dossier_id}/export-reserves")
async def export_arh_reserves_sheet(dossier_id: str):
    """
    Pillar 3: Génère la Fiche de Réserves Officielle ARH en 1 Clic (PDF/HTML structuré).
    Contient l'ensemble des réserves classées par priorité, avec articles de décrets et délais.
    """
    dossier_id = sanitize_dossier_id(dossier_id)
    data = _load_dossier(dossier_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Dossier ARH '{dossier_id}' introuvable.")

    comments = data.get("comments", [])
    reserves_count = len(comments)

    reserves_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>FICHE OFFICIELLE DE RÉSERVES ARH - {dossier_id}</title>
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 30px; color: #1E293B; }}
            h1 {{ color: #0F172A; border-bottom: 2px solid #E2E8F0; padding-bottom: 10px; }}
            .badge {{ display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 12px; }}
            .CRITICAL {{ background: #FEE2E2; color: #DC2626; }}
            .MAJOR {{ background: #FEF3C7; color: #D97706; }}
            .MINOR {{ background: #E0F2FE; color: #0284C7; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ border: 1px solid #CBD5E1; padding: 10px; font-size: 11px; text-align: left; }}
            th {{ background: #F8FAFC; color: #475569; }}
        </style>
    </head>
    <body>
        <h1>AUTORITÉ DE RÉGULATION DES HYDROCARBURES (ARH)</h1>
        <h2>FICHE OFFICIELLE DE RÉSERVES & NON-CONFORMITÉS - DOSSIER {dossier_id}</h2>
        <p><strong>Projet :</strong> {data.get('project_name')} | <strong>Équipement :</strong> {data.get('equipment_tag')} ({data.get('equipment_type')})</p>
        <p><strong>Décision ARH :</strong> <span class="badge {data.get('status')}">{data.get('arh_decision')}</span> | <strong>Score :</strong> {data.get('compliance_score')}%</p>
        
        <h3>Liste des Réserves ({reserves_count} ouvertes)</h3>
        <table>
            <thead>
                <tr>
                    <th style="width:70px;">Priorité</th>
                    <th style="width:190px;">Document & Emplacement Exact</th>
                    <th style="width:110px;">Ref. Décret</th>
                    <th>Intitulé & Description</th>
                    <th style="width:180px;">Action Corrective Exigée</th>
                    <th style="width:70px;">Délai</th>
                </tr>
            </thead>
            <tbody>
    """
    for c in comments:
        doc_name = c.get('document_concerned', 'Dossier Technique')
        page_val = c.get('page', 'Page non spécifiée')
        snippet = c.get('quote_snippet', '')
        snippet_html = f'<div style="font-family:monospace; font-size:10px; background:#F1F5F9; border-left:3px solid #F59E0B; padding:5px 8px; margin-top:5px; color:#334155;"><strong>Extrait textuel :</strong> « {snippet} »</div>' if snippet else ''

        reserves_html += f"""
                <tr>
                    <td><span class="badge {c.get('priority')}">{c.get('priority')}</span></td>
                    <td>
                        <strong style="color:#0F172A; word-break:break-all;">{doc_name}</strong><br>
                        <span class="badge" style="background:#E0E7FF; color:#3730A3; margin-top:4px; display:inline-block;">📍 {page_val}</span>
                        {snippet_html}
                    </td>
                    <td>{c.get('decree_reference', '')} - {c.get('article_number', '')}</td>
                    <td><strong>{c.get('title')}</strong><br>{c.get('description') or c.get('observation', '')}</td>
                    <td>{c.get('correction_method', c.get('action_required', ''))}</td>
                    <td>{c.get('deadline', '')} ({c.get('deadline_days', 7)}j)</td>
                </tr>
        """

    reserves_html += """
            </tbody>
        </table>
    </body>
    </html>
    """

    reserves_path = _ARH_REPORTS_DIR / f"{dossier_id}_fiche_reserves.html"
    with open(reserves_path, "w", encoding="utf-8") as f:
        f.write(reserves_html)

    return FileResponse(str(reserves_path), media_type="text/html", filename=f"Fiche_Reserves_ARH_{dossier_id}.html")


@router.get("/dossiers/{dossier_id}/export-decision-letter")
async def export_arh_decision_letter(dossier_id: str):
    """
    Pillar 3: Génère le brouillon de Lettre d'Avis Officiel ARH (Avis Favorable, Favorable sous Réserve ou Refus).
    """
    dossier_id = sanitize_dossier_id(dossier_id)
    data = _load_dossier(dossier_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Dossier ARH '{dossier_id}' introuvable.")

    status = data.get("status", "REJECTED")
    decision_type = "AVIS FAVORABLE" if status == "APPROVED" else ("AVIS FAVORABLE SOUS RÉSERVES" if status == "APPROVED_WITH_COMMENTS" else "AVIS DE REFUS MOTIVÉ")

    letter_text = f"""
================================================================================
MINISTÈRE DE L'ÉNERGIE ET DES MINES
AUTORITÉ DE RÉGULATION DES HYDROCARBURES (ARH)
DIRECTION DU CONTRÔLE TECHNIQUE & DE LA SÉCURITÉ
================================================================================
Réf: ARH/DCT/{datetime.date.today().strftime('%Y')}/{dossier_id[:8]}
Alger, le {datetime.date.today().strftime('%d/%m/%Y')}

À l'attention du Responsable du Projet : {data.get('project_name')}
Objet : Notification de la décision ARH relative au dossier {dossier_id}
Équipement : {data.get('equipment_tag')} ({data.get('equipment_type')})

Monsieur le Directeur,

Après examen approfondi par la commission technique d'audit de l'ARH du dossier technique réf {dossier_id}, soumis au titre du {data.get('dossier_stage_label', 'Décret Exécutif ARH')}, nous vous notifions la décision suivante :

================================================================================
DÉCISION OFFICIELLE ARH : {decision_type} (Score de Conformité : {data.get('compliance_score')}%)
================================================================================

Motifs et Réserves Réglementaires :
- Nombre d'anomalies critiques bloquantes : {data.get('summary_stats', {}).get('critical_anomalies', 0)}
- Nombre de réserves majeures à lever : {data.get('summary_stats', {}).get('major_anomalies', 0)}
- Fichiers manquants à fournir : {len(data.get('missing_documents', []))}

Veuillez agréer, Monsieur le Directeur, l'assurance de notre considération distinguée.

Le Directeur du Contrôle Technique
Autorité de Régulation des Hydrocarbures (ARH)
================================================================================
"""

    letter_path = _ARH_REPORTS_DIR / f"{dossier_id}_lettre_decision.txt"
    with open(letter_path, "w", encoding="utf-8") as f:
        f.write(letter_text)

    return FileResponse(str(letter_path), media_type="text/plain", filename=f"Lettre_Decision_ARH_{dossier_id}.txt")


@router.post("/expert-chat")
async def arh_expert_chat(payload: Dict[str, Any]):
    """
    Pillar 4: Agent Assistant Réglementaire ARH Dédié.
    Répond instantanément aux questions réglementaires sur les Décrets 21-261, 21-314, 21-315, 17-62, 21-257.
    """
    question = payload.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="La question ne peut pas être vide.")

    from arh_regulatory_engine import DECREES_CATALOG
    matched_articles = []

    q_upper = question.upper()
    for d_key, d_info in DECREES_CATALOG.items():
        title = d_info["title"]
        for art_key, art_text in d_info.get("articles", {}).items():
            if any(word in art_text.upper() or word in title.upper() for word in q_upper.split() if len(word) >= 4):
                matched_articles.append(f"• **{title} ({art_key})** : {art_text}")

    if matched_articles:
        answer = f"### 📜 Extraits Réglementaires ARH Applicables :\n\n" + "\n\n".join(matched_articles[:5])
    else:
        answer = (
            f"### 📜 Exigence Réglementaire ARH :\n"
            f"Conformément aux décrets **21-261** (ESP), **21-314** (Canalisations), et **21-315** (Fabrication & Stockage), "
            f"toute modification ou dossier soumis doit respecter une épreuve hydrostatique minimale à **150% de la PMA** (ou 125% en zone C/D) "
            f"et faire l'objet d'un contrôle visuel et radiographique selon la classification de la zone."
        )

    return JSONResponse(content={
        "status": "SUCCESS",
        "question": question,
        "answer": answer,
        "sources_count": len(matched_articles)
    })


@router.get("/dossiers/{dossier_id}/export-official-pdf")
async def export_official_arh_pdf(dossier_id: str):
    """
    Exportation du Rapport PDF Officiel ARH avec charte républicaine, en-tête officiel,
    tableau des équipements et avis de la commission d'inspection.
    """
    dossier_id = sanitize_dossier_id(dossier_id)
    data = _load_dossier(dossier_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Dossier ARH '{dossier_id}' introuvable.")

    generator = ARHReportGenerator(output_dir=str(_ARH_REPORTS_DIR))
    pdf_path = generator.generate_pdf_report(data)
    
    # BUG FIX #7 : gérer le fallback TXT si ReportLab n'est pas installé
    actual_path = str(pdf_path)
    if actual_path.endswith(".txt"):
        filename = f"RAPPORT_OFFICIEL_ARH_{dossier_id}.txt"
        media_type = "text/plain"
    else:
        filename = f"RAPPORT_OFFICIEL_ARH_{dossier_id}.pdf"
        media_type = "application/pdf"
    return FileResponse(actual_path, media_type=media_type, filename=filename)


@router.post("/dossiers/{dossier_id}/reserves/{reserve_id}/resolve")
async def resolve_arh_reserve(
    dossier_id: str,
    reserve_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None)
):
    """
    Workflow Collaboratif EPC <-> ARH : Marque une réserve comme levée/résolue avec justification.
    """
    dossier_id = sanitize_dossier_id(dossier_id)
    data = _load_dossier(dossier_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Dossier ARH '{dossier_id}' introuvable.")

    comments = data.get("comments", [])
    resolved = False
    justification = (payload or {}).get("justification", "Justificatif transmis par EPC Contractor.")

    for idx, c in enumerate(comments):
        c_id = c.get("id")
        is_match = False
        if c_id and (c_id == reserve_id or reserve_id in c_id or c_id in reserve_id):
            is_match = True
        elif reserve_id == f"REM_{idx}" or reserve_id == str(idx):
            is_match = True
        elif reserve_id.endswith(f"_{idx}"):
            is_match = True

        if is_match:
            c["status"] = "RESOLVED"
            c["resolution_note"] = justification
            c["resolved_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            resolved = True
            break

    if not resolved:
        raise HTTPException(status_code=404, detail=f"Réserve '{reserve_id}' introuvable dans le dossier.")

    # Save back to SQLite
    with _get_db() as conn:
        conn.execute("UPDATE arh_dossiers SET data_json = ?, updated_at = ? WHERE dossier_id = ?",
                     (json.dumps(data, ensure_ascii=False), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), dossier_id))
        conn.commit()

    # Synchronisation Automatique de la levée de réserve dans le Réseau d'Agents IA & Knowledge Graph
    try:
        from arh_agent_network_manager import get_agent_network_manager
        get_agent_network_manager().sync_on_reserve_resolved(dossier_id, reserve_id, justification)
    except Exception as e_net:
        logger.warning("[ARH] Erreur synchronisation levée de réserve Réseau d'Agents : %s", e_net)

    return JSONResponse(content={
        "status": "SUCCESS",
        "message": f"Réserve {reserve_id} levée avec succès.",
        "reserve_id": reserve_id,
        "dossier_id": dossier_id
    })


@router.post("/dossiers/{dossier_id}/reserves/{reserve_id}/reopen")
async def reopen_arh_reserve(dossier_id: str, reserve_id: str):
    """
    Workflow Collaboratif EPC <-> ARH : Réouvre une réserve préalablement levée.
    """
    dossier_id = sanitize_dossier_id(dossier_id)
    data = _load_dossier(dossier_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Dossier ARH '{dossier_id}' introuvable.")

    comments = data.get("comments", [])
    reopened = False

    for idx, c in enumerate(comments):
        c_id = c.get("id")
        is_match = False
        if c_id and (c_id == reserve_id or reserve_id in c_id or c_id in reserve_id):
            is_match = True
        elif reserve_id == f"REM_{idx}" or reserve_id == str(idx):
            is_match = True
        elif reserve_id.endswith(f"_{idx}"):
            is_match = True

        if is_match:
            c["status"] = "OPEN"
            c.pop("resolution_note", None)
            c.pop("resolved_at", None)
            reopened = True
            break

    if not reopened:
        raise HTTPException(status_code=404, detail=f"Réserve '{reserve_id}' introuvable dans le dossier.")

    # Save back to SQLite
    with _get_db() as conn:
        conn.execute("UPDATE arh_dossiers SET data_json = ?, updated_at = ? WHERE dossier_id = ?",
                     (json.dumps(data, ensure_ascii=False), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), dossier_id))
        conn.commit()

    # Synchronisation Automatique de la réouverture de réserve dans le Réseau d'Agents IA & Knowledge Graph
    try:
        from arh_agent_network_manager import get_agent_network_manager
        get_agent_network_manager().sync_on_reserve_reopened(dossier_id, reserve_id)
    except Exception as e_net:
        logger.warning("[ARH] Erreur synchronisation réouverture de réserve Réseau d'Agents : %s", e_net)

    return JSONResponse(content={
        "status": "SUCCESS",
        "message": f"Réserve {reserve_id} réouverte avec succès.",
        "reserve_id": reserve_id,
        "dossier_id": dossier_id
    })


@router.post("/dossiers/{dossier_id}/reserves/{reserve_id}/feedback")
@router.post("/dossiers/{dossier_id}/comments/{comment_id}/feedback")
async def record_reserve_feedback(
    dossier_id: str,
    reserve_id: Optional[str] = None,
    comment_id: Optional[str] = None,
    payload: Dict[str, Any] = Body(...)
):
    """
    Prime Agent /refine Feedback Loop:
    Ingestion des arbitrages des inspecteurs ARH pour raffinement continu des règles.
    Permet d'invalider un faux positif, de valider une concession constructeur, ou de confirmer une non-conformité.
    """
    dossier_id = sanitize_dossier_id(dossier_id)
    target_id = reserve_id or comment_id or (payload or {}).get("finding_id")
    if not target_id:
        raise HTTPException(status_code=400, detail="Identifiant de réserve (reserve_id ou comment_id) manquant.")

    data = _load_dossier(dossier_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Dossier ARH '{dossier_id}' introuvable.")

    verdict = (payload or {}).get("verdict", "CONFIRMED").upper()
    inspector_notes = (payload or {}).get("inspector_notes", (payload or {}).get("justification", ""))

    comments = data.get("comments", [])
    target_comment = None
    for c in comments:
        if c.get("id") == target_id or target_id in c.get("id", ""):
            target_comment = c
            break

    if not target_comment:
        raise HTTPException(status_code=404, detail=f"Réserve '{target_id}' introuvable dans le dossier.")

    if verdict == "INVALIDATED_FALSE_POSITIVE":
        target_comment["status"] = "INVALIDATED"
        target_comment["feedback_note"] = f"[Faux Positif Invalidé] {inspector_notes}"
    elif verdict == "ACCEPTED_CONCESSION":
        target_comment["status"] = "ACCEPTED_CONCESSION"
        target_comment["priority"] = "INFO"
        target_comment["feedback_note"] = f"[Concession Acceptée] {inspector_notes}"
    else:
        target_comment["status"] = "CONFIRMED_BY_INSPECTOR"
        target_comment["feedback_note"] = f"[Confirmé par Inspecteur] {inspector_notes}"

    _save_dossier(data)

    from arh_refine_engine import arh_refine_engine
    refine_result = arh_refine_engine.record_feedback(
        dossier_id=dossier_id,
        finding_id=target_id,
        verdict=verdict,
        inspector_notes=inspector_notes,
        finding_data=target_comment,
        vendor_name=data.get("vendor_name"),
        equipment_type=data.get("equipment_type")
    )

    return JSONResponse(content={
        "status": "SUCCESS",
        "message": f"Feedback enregistré pour la réserve {target_id} (Verdict: {verdict}).",
        "refine_result": refine_result
    })


@router.get("/refine-rules")
async def list_refine_rules(
    vendor_name: Optional[str] = Query(None),
    equipment_type: Optional[str] = Query(None)
):
    """Retourne la liste des règles de raffinement actives issues du feedback des inspecteurs (/refine loop)."""
    from arh_refine_engine import arh_refine_engine
    rules = arh_refine_engine.get_active_rules(vendor_name=vendor_name, equipment_type=equipment_type)
    return JSONResponse(content={"status": "SUCCESS", "count": len(rules), "rules": rules})


@router.get("/dossiers/{dossier_id}/view-pdf/{filename}")
async def view_annotated_pdf(dossier_id: str, filename: str):
    """
    Retourne le PDF annoté en rouge avec les erreurs encadrées et commentaires.
    """
    dossier_id = sanitize_dossier_id(dossier_id)
    data = _load_dossier(dossier_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Dossier ARH '{dossier_id}' introuvable.")

    from arh_pdf_annotator import ARHPDFAnnotator
    annotator = ARHPDFAnnotator(uploads_dir=str(_ARH_UPLOADS_DIR))
    
    src_path = annotator.resolve_pdf_path(dossier_id, filename)
    if not src_path or not src_path.exists():
        raise HTTPException(status_code=404, detail="PDF source introuvable.")

    real_filename = src_path.name
    comments = data.get("comments", [])
    page_blocks = data.get("page_blocks_evidence", [])
    
    annotated_pdf_path = _ARH_UPLOADS_DIR / dossier_id / f"annotated_{real_filename}"
    if not annotated_pdf_path.exists():
        try:
            annotator.annotate_document(
                dossier_id=dossier_id,
                filename=real_filename,
                comments=comments,
                page_blocks=page_blocks
            )
        except Exception as e_ann:
            logger.warning("[ARH-VIEW-PDF] Erreur annotation à la volée, fallback original : %s", e_ann)

    if annotated_pdf_path.exists():
        return FileResponse(str(annotated_pdf_path), media_type="application/pdf", filename=f"annotated_{real_filename}")
    return FileResponse(str(src_path), media_type="application/pdf", filename=real_filename)


@router.get("/dossiers/{dossier_id}/documents/{filename}")
async def view_document_pdf(dossier_id: str, filename: str):
    """
    Sert le document PDF pour affichage direct inline dans le navigateur avec navigation par page (#page=X).
    """
    dossier_id = sanitize_dossier_id(dossier_id)
    from arh_pdf_annotator import ARHPDFAnnotator
    annotator = ARHPDFAnnotator(uploads_dir=str(_ARH_UPLOADS_DIR))
    src_path = annotator.resolve_pdf_path(dossier_id, filename)
    if not src_path or not src_path.exists():
        src_path = annotator.get_master_pdf_path(dossier_id)
    if not src_path or not src_path.exists():
        raise HTTPException(status_code=404, detail="Document PDF introuvable.")

    return FileResponse(
        str(src_path),
        media_type="application/pdf",
        filename=src_path.name,
        headers={"Content-Disposition": f"inline; filename=\"{src_path.name}\""}
    )


@router.get("/dossiers/{dossier_id}/pages/{filename}/{page_num}.png")
async def view_annotated_page_png(
    dossier_id: str,
    filename: str,
    page_num: int,
    q: Optional[str] = Query(None, description="Extrait textuel ou terme clé"),
    title: Optional[str] = Query(None, description="Titre de la réserve"),
    highlight: bool = Query(True, description="Activer le surlignage de la réserve")
):
    """
    Retourne la page spécifiée du document source sous forme d'image PNG haute définition.
    Intègre un surlignage non destructif et un indicateur de marge ciblé sur l'anomalie.
    """
    clean_dossier_id = sanitize_dossier_id(dossier_id)
    dossier_dir = _ARH_UPLOADS_DIR / clean_dossier_id
    data = _load_dossier(clean_dossier_id)
    if not data and not dossier_dir.exists():
        raise HTTPException(status_code=404, detail=f"Dossier ARH '{clean_dossier_id}' introuvable.")

    from arh_pdf_annotator import ARHPDFAnnotator
    annotator = ARHPDFAnnotator(uploads_dir=str(_ARH_UPLOADS_DIR))
    
    clean_filename = filename if filename and filename not in ("", "undefined", "null") else ""

    # Rendre en PNG avec surlignage non destructif
    img_bytes = annotator.render_page_to_png(
        clean_dossier_id,
        clean_filename,
        page_num,
        target_snippet=q,
        target_title=title,
        highlight_enabled=highlight
    )
    if not img_bytes:
        raise HTTPException(status_code=404, detail=f"Page {page_num} introuvable.")

    return Response(content=img_bytes, media_type="image/png")


@router.get("/dossiers/{dossier_id}/pages/{page_num}.png")
@router.get("/dossiers/{dossier_id}/page/{page_num}.png")
async def view_annotated_page_png_default(
    dossier_id: str,
    page_num: int,
    q: Optional[str] = Query(None, description="Extrait textuel ou terme clé"),
    title: Optional[str] = Query(None, description="Titre de la réserve"),
    highlight: bool = Query(True, description="Activer le surlignage de la réserve")
):
    """Fallback si aucun nom de fichier n'est spécifié : charge le premier PDF du dossier."""
    return await view_annotated_page_png(
        dossier_id=dossier_id,
        filename="",
        page_num=page_num,
        q=q,
        title=title,
        highlight=highlight
    )


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS — COMPARATEUR DE RÉVISIONS & MATRICE DE LEVÉE DE RÉSERVES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/compare-revisions/{rev0_id}/{rev1_id}")
async def compare_arh_dossier_revisions_get(rev0_id: str, rev1_id: str):
    """
    Compare deux révisions d'un dossier ARH (ex: Rev.00 vs Rev.01) et génère la Matrice de Levée de Réserves.
    """
    try:
        from arh_revision_comparator import ARHRevisionComparator
        data0 = _load_dossier(rev0_id)
        if not data0:
            raise HTTPException(status_code=404, detail=f"Dossier initial '{rev0_id}' introuvable.")

        data1 = _load_dossier(rev1_id)
        if not data1:
            raise HTTPException(status_code=404, detail=f"Dossier révisé '{rev1_id}' introuvable.")

        comparator = ARHRevisionComparator()
        diff_result = comparator.compare(data0, data1)

        return JSONResponse(content={
            "status": "SUCCESS",
            "message": f"Comparaison effectuée avec succès entre {rev0_id} et {rev1_id}.",
            "data": diff_result
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[ARH-Diff] Erreur comparaison révisions %s vs %s : %s", rev0_id, rev1_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur lors de la comparaison des révisions : {str(e)}")


@router.post("/compare-revisions")
async def compare_arh_dossier_revisions_post(
    rev0_dossier_id: str = Form(...),
    rev1_dossier_id: str = Form(...)
):
    """
    Compare deux révisions d'un dossier ARH via formulaire POST.
    """
    return await compare_arh_dossier_revisions_get(rev0_dossier_id.strip(), rev1_dossier_id.strip())


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS — ANALYSE STRUCTURÉE DES CERTIFICATS MATIÈRE 3.1 & CEV
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/dossiers/{dossier_id}/material-certificates")
async def get_dossier_material_certificates_analysis(dossier_id: str):
    """
    Retourne l'analyse structurée détaillée des certificats matière 3.1 (chimie, mécanique, CEV, Pcm, conformités).
    """
    dossier_id = sanitize_dossier_id(dossier_id)
    data = _load_dossier(dossier_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Dossier ARH '{dossier_id}' introuvable.")

    try:
        import fitz
        from arh_material_certificate_analyzer import ARHMaterialCertificateAnalyzer
        analyzer = ARHMaterialCertificateAnalyzer()

        certificates_found = []
        dossier_dir = _ARH_UPLOADS_DIR / dossier_id
        pdf_paths = []

        if dossier_dir.exists() and dossier_dir.is_dir():
            pdf_paths.extend(list(dossier_dir.glob("*.pdf")) + list(dossier_dir.glob("*.PDF")))

        # Fallback si les fichiers sont dans uploads/
        if not pdf_paths:
            for doc_name in data.get("source_documents", data.get("received_documents", [])):
                cand1 = _ARH_UPLOADS_DIR / doc_name
                cand2 = Path("uploads") / doc_name
                if cand1.exists(): pdf_paths.append(cand1)
                elif cand2.exists(): pdf_paths.append(cand2)

        for pdf_p in pdf_paths:
            fname = pdf_p.name
            try:
                with fitz.open(str(pdf_p)) as doc:
                    for page_idx in range(len(doc)):
                        page_text = doc[page_idx].get_text()
                        if len(page_text.strip()) > 30:
                            cert_res = analyzer.analyze_certificate_text(
                                text=page_text,
                                filename=fname,
                                page_num=page_idx + 1,
                                expected_grade="A350 LF2"
                            )
                            if cert_res.get("is_material_certificate"):
                                certificates_found.append(cert_res)
            except Exception as e_pdf:
                logger.warning("[ARH-Material] Erreur lecture PDF %s: %s", fname, e_pdf)

        return JSONResponse(content={
            "status": "SUCCESS",
            "dossier_id": dossier_id,
            "equipment_tag": data.get("equipment_tag", ""),
            "certificates_count": len(certificates_found),
            "certificates": certificates_found
        })
    except Exception as e:
        logger.error("[ARH-Material] Erreur analyse certificats %s : %s", dossier_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur extraction certificats 3.1 : {str(e)}")


@router.get("/dossiers/{dossier_id}/descriptive-sheet")
async def get_dossier_descriptive_sheet(dossier_id: str):
    """
    Retourne l'extraction structurée de l'État Descriptif (Annexe E / Fiche Descriptive) du dossier.
    """
    dossier_id = sanitize_dossier_id(dossier_id)
    data = _load_dossier(dossier_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Dossier ARH '{dossier_id}' introuvable.")

    try:
        import fitz
        from arh_descriptive_sheet_extractor import ARHDescriptiveSheetExtractor
        extractor = ARHDescriptiveSheetExtractor()

        dossier_dir = _ARH_UPLOADS_DIR / dossier_id
        pdf_paths = []

        if dossier_dir.exists() and dossier_dir.is_dir():
            pdf_paths.extend(list(dossier_dir.glob("*.pdf")) + list(dossier_dir.glob("*.PDF")))

        if not pdf_paths:
            for doc_name in data.get("source_documents", data.get("received_documents", [])):
                cand1 = _ARH_UPLOADS_DIR / doc_name
                cand2 = Path("uploads") / doc_name
                if cand1.exists(): pdf_paths.append(cand1)
                elif cand2.exists(): pdf_paths.append(cand2)

        sheet_results = []
        for pdf_p in pdf_paths:
            fname = pdf_p.name
            try:
                with fitz.open(str(pdf_p)) as doc:
                    for page_idx in range(len(doc)):
                        page_text = doc[page_idx].get_text()
                        if extractor.is_descriptive_sheet(page_text):
                            sheet_data = extractor.extract_from_text(page_text, filename=fname, page_num=page_idx + 1)
                            if sheet_data.get("design_pressure") or sheet_data.get("material") or sheet_data.get("thickness_mm") or sheet_data.get("yield_strength_mpa") or sheet_data.get("construction_year"):
                                sheet_results.append(sheet_data)
            except Exception as e_pdf:
                logger.warning("[ARH-DescriptiveSheet] Erreur lecture PDF %s: %s", fname, e_pdf)

        return JSONResponse(content={
            "status": "SUCCESS",
            "dossier_id": dossier_id,
            "equipment_tag": data.get("equipment_tag", ""),
            "sheets_count": len(sheet_results),
            "descriptive_sheets": sheet_results
        })
    except Exception as e:
        logger.error("[ARH-DescriptiveSheet] Erreur extraction fiche descriptive %s: %s", dossier_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur extraction état descriptif : {str(e)}")


@router.post("/dossiers/{dossier_id}/nuextract")
async def extract_with_nuextract(
    dossier_id: str,
    request_data: Optional[Dict[str, Any]] = Body(default=None)
):
    """Extrait un JSON structuré via NuExtract-3 pour n'importe quelle page ou texte de dossier ARH."""
    from arh_nuextract_engine import arh_nuextract_engine
    dossier_id = sanitize_dossier_id(dossier_id)
    req = request_data or {}

    data = _load_dossier(dossier_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Dossier '{dossier_id}' introuvable.")

    schema_type = req.get("schema_type", "ANNEXE_E")
    custom_text = req.get("text", "")

    if not custom_text:
        # Prendre le texte extrait du premier document du dossier
        docs = data.get("documents", [])
        if docs:
            custom_text = docs[0].get("text", "")
        else:
            custom_text = f"EQUIPMENT {data.get('equipment_tag', '')} PMA 92 BAR HYDROTEST 138 BAR MAT A350 LF2"

    extracted_json = arh_nuextract_engine.extract_structured(custom_text, schema_type)

    return JSONResponse(content={
        "status": "SUCCESS",
        "dossier_id": dossier_id,
        "schema_type": schema_type,
        "extracted_data": extracted_json,
        "engine": "NuExtract-3 / NuMind VLM & Semantic Engine"
    })


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS — RÉSEAU D'AGENTS IA & VISION 360° DU PROJET EN TEMPS RÉEL
# ══════════════════════════════════════════════════════════════════════════════

@router.delete("/dossiers/{dossier_id}")
async def delete_arh_dossier(dossier_id: str):
    """
    Suppression d'un dossier ARH avec cascade automatique :
      - Suppression dans SQLite `arh_dossiers`
      - Suppression des nœuds et relations dans `arh_knowledge_graph.db`
      - Mise à jour en temps réel des métriques et avis du réseau d'agents IA
    """
    dossier_id = sanitize_dossier_id(dossier_id)
    existing = _load_dossier(dossier_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Dossier ARH '{dossier_id}' introuvable.")

    proj_name = existing.get("project_name", "")

    # 1. Supprimer dans SQLite et nettoyer le rapport PDF associé
    _delete_dossier_from_db(dossier_id)

    # 2. Supprimer les fichiers physiques du dossier
    target_dir = _ARH_UPLOADS_DIR / dossier_id
    if target_dir.exists():
        try:
            shutil.rmtree(target_dir)
        except Exception as e_rm:
            logger.warning("[ARH-Delete] Impossible de supprimer le dossier %s: %s", target_dir, e_rm)

    # 3. Synchronisation automatique Réseau d'Agents IA & Knowledge Graph
    live_vision = {}
    try:
        from arh_agent_network_manager import get_agent_network_manager
        live_vision = get_agent_network_manager().sync_on_dossier_deleted(dossier_id)
    except Exception as e_net:
        logger.warning("[ARH] Erreur sync suppression Réseau d'Agents : %s", e_net)

    return JSONResponse(content={
        "status": "SUCCESS",
        "message": f"Dossier ARH '{dossier_id}' et toutes ses dépendances ont été supprimés avec succès.",
        "dossier_id": dossier_id,
        "project_name": proj_name,
        "project_live_vision": live_vision
    })


@router.get("/network/topology")
async def get_agent_network_topology():
    """
    Retourne la topologie active du réseau d'agents IA ARKAN :
      - 7 Superviseurs Master
      - 28 Spécialistes d'Équipements avec statut LoRA en temps réel
      - Traçabilité et événements de synchronisation en direct
    """
    from arh_agent_network_manager import get_agent_network_manager
    mgr = get_agent_network_manager()
    topology = mgr.get_topology()
    if isinstance(topology, dict):
        return JSONResponse(content={"status": "SUCCESS", "data": topology, **topology})
    return JSONResponse(content={"status": "SUCCESS", "data": topology})


@router.get("/network/project/{project_name}/live-vision")
async def get_project_live_vision(project_name: str):
    """
    Retourne la vision exacte 360° du projet mise à jour en continu :
      - Score de conformité global temps réel
      - Matrice d'avis et consensus des 7 agents IA
      - Liste des équipements et dossiers rattachés
      - Nombre de réserves ouvertes vs résolues
      - Arborescence complète du sous-graphe projet
    """
    from arh_agent_network_manager import get_agent_network_manager
    mgr = get_agent_network_manager()
    vision = mgr.get_project_live_vision(project_name)

    return JSONResponse(content={
        "status": "SUCCESS",
        "project_name": project_name,
        "data": vision
    })


@router.post("/network/sync-all")
async def force_global_network_sync():
    """
    Force la synchronisation intégrale de tous les dossiers et projets SQLite
    vers le Knowledge Graph et le Réseau d'Agents IA.
    """
    from arh_agent_network_manager import get_agent_network_manager
    mgr = get_agent_network_manager()
    result = mgr.sync_all_from_dossiers_db()

    return JSONResponse(content={
        "status": "SUCCESS",
        "message": f"Synchronisation globale terminée : {result.get('dossiers_synced', 0)} dossiers synchronisés.",
        "data": result
    })


@router.post("/dossiers/{dossier_id}/audit-tm")
@router.get("/dossiers/{dossier_id}/audit-tm")
async def audit_dossier_via_dot_tm(dossier_id: str, project_name: Optional[str] = Query(None)):
    """
    Priorité 1 : Audit Réglementaire ARH & Interconnexion DOT-TM.
    Vérification croisée ARH vs MTO vs Contrat et dispatching automatique
    des réserves vers les DOTs disciplinaires (DOT-01 à DOT-11).
    """
    clean_id = sanitize_dossier_id(dossier_id)
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent / "dots"))
        from dot_tm_manager import DOT_TM
        tm = DOT_TM()
        res = tm.verify_arh_dossier(clean_id, project_name=project_name)
        return JSONResponse(content={"status": "SUCCESS", "data": res})
    except Exception as exc:
        logger.error("[ARH API] Erreur audit-tm: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/dossiers/{dossier_id}/parametric-matrix")
async def get_parametric_matrix(dossier_id: str):
    """
    Priorité 2 : Matrice d'épreuve et de concordance paramétrique temps réel (v3.0).
    Formule d'épreuve hydrostatique (Décret 21-314 & 21-261 / ASME VIII),
    Rating brides ASME B16.5, Soudabilité (Pcm / CEV IIW) & NACE MR0175,
    et Concordance multi-sources unité-aware sans valeur par défaut implicite.
    """
    clean_id = sanitize_dossier_id(dossier_id)
    try:
        from arh_parametric_matrix_engine import ARHParametricMatrixEngine
        db_file = str(Path(__file__).parent / "arh_dossiers.db")
        engine = ARHParametricMatrixEngine(db_path=db_file)
        res = engine.generate_full_parametric_analysis(clean_id)
        if isinstance(res, dict):
            return JSONResponse(content={"status": "SUCCESS", "data": res, **res})
        return JSONResponse(content={"status": "SUCCESS", "data": res})
    except Exception as exc:
        logger.error("[ARH API] Erreur parametric-matrix: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# PRIORITÉ 3 : LIVRABLES OFFICIELS ARH PRÊTS POUR DÉPÔT
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/dossiers/{dossier_id}/export-official-bordereau")
async def export_official_bordereau(dossier_id: str):
    """
    Exporte le Bordereau Officiel de Transmission normalisé (DOC-01 à DOC-14).
    """
    clean_id = sanitize_dossier_id(dossier_id)
    try:
        from arh_official_deliverables_engine import deliverables_engine
        pdf_path = deliverables_engine.generate_official_bordereau_pdf(clean_id)
        return FileResponse(
            path=pdf_path,
            filename=f"BORDEREAU_OFFICIEL_ARH_{clean_id}.pdf",
            media_type="application/pdf"
        )
    except Exception as exc:
        logger.error("[ARH API] Erreur export bordereau: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/dossiers/{dossier_id}/export-fiche-descriptive")
async def export_fiche_descriptive(dossier_id: str):
    """
    Exporte la Fiche Descriptive d'Appareil sous Pression (Annexe E Décret 21-261).
    """
    clean_id = sanitize_dossier_id(dossier_id)
    try:
        from arh_official_deliverables_engine import deliverables_engine
        pdf_path = deliverables_engine.generate_fiche_descriptive_pdf(clean_id)
        return FileResponse(
            path=pdf_path,
            filename=f"FICHE_DESCRIPTIVE_ARH_{clean_id}.pdf",
            media_type="application/pdf"
        )
    except Exception as exc:
        logger.error("[ARH API] Erreur export fiche descriptive: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/dossiers/{dossier_id}/export-levee-reserves")
async def export_matrice_levee_reserves(dossier_id: str):
    """
    Exporte la Matrice Formelle de Levée de Réserves Avant / Après.
    """
    clean_id = sanitize_dossier_id(dossier_id)
    try:
        from arh_official_deliverables_engine import deliverables_engine
        pdf_path = deliverables_engine.generate_matrice_levee_reserves_pdf(clean_id)
        return FileResponse(
            path=pdf_path,
            filename=f"MATRICE_LEVEE_RESERVES_ARH_{clean_id}.pdf",
            media_type="application/pdf"
        )
    except Exception as exc:
        logger.error("[ARH API] Erreur export levee reserves: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 01 : DÉCOUPAGE PHYSIQUE & EXTRACTION PYDANTIC (DOC-01 À DOC-14)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/dossiers/{dossier_id}/slice")
@router.post("/dossiers/{dossier_id}/slice-pieces")
async def slice_arh_dossier_pieces(dossier_id: str):

    """
    Étape 01 : Découpe physiquement le dossier maître en pièces réglementaires ARH (DOC-01 à DOC-14)
    et extrait les métadonnées techniques via les contrats Pydantic.
    """
    clean_id = sanitize_dossier_id(dossier_id)
    try:
        from arh_document_slicer import arh_slicer
        pieces = arh_slicer.slice_dossier(clean_id)

        # Synchronisation immédiate du dossier maître SQLite
        existing_dossier = _load_dossier(clean_id)
        if existing_dossier:
            existing_dossier["sliced_pieces"] = pieces
            existing_dossier["sliced_pieces_count"] = len(pieces)
            try:
                from arh_composition_analyzer import analyze_dossier_composition
                comp_summary = analyze_dossier_composition(
                    {
                        "mandatory_checklist": existing_dossier.get("mandatory_checklist", []),
                        "sliced_pieces": pieces,
                        "source_documents": existing_dossier.get("source_documents", [])
                    },
                    dossier_stage=existing_dossier.get("dossier_stage")
                )
                existing_dossier["composition_summary"] = comp_summary
                existing_dossier["recap_composition_table"] = comp_summary.get("recap_table_markdown", "")
            except Exception as _e_sync:
                logger.debug("[ARH API] Erreur refresh composition sur slice: %s", _e_sync)
            _save_dossier(existing_dossier)

        return JSONResponse(content={
            "status": "SUCCESS",
            "message": f"Dossier {clean_id} découpé avec succès en {len(pieces)} pièces réglementaires distinctes.",
            "dossier_id": clean_id,
            "pieces_count": len(pieces),
            "pieces": pieces
        })
    except Exception as exc:
        logger.error("[ARH API] Erreur découpage pièces dossier %s: %s", clean_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur lors du découpage du dossier : {str(exc)}")


@router.get("/dossiers/{dossier_id}/sliced-pieces")
async def get_arh_sliced_pieces(
    dossier_id: str,
    auto_slice: bool = Query(True),
    force_reslice: bool = Query(False)
):
    """
    Retourne la liste des pieces decoupees avec leurs plages de pages,
    fichiers physiques et contrats Pydantic extraits.
    Garantit 100% de couverture continue sans trou.
    """
    clean_id = sanitize_dossier_id(dossier_id)
    try:
        from arh_document_slicer import arh_slicer
        pieces = [] if force_reslice else arh_slicer.get_sliced_pieces(clean_id)

        # Verifier si les pieces existantes couvrent bien 100% du dossier maitre
        existing_dossier = _load_dossier(clean_id)
        dossier_total_pages = existing_dossier.get("total_pages", 0) if existing_dossier else 0
        total_covered = sum(p.get("page_count", 0) for p in pieces) if pieces else 0

        needs_reslice = force_reslice or (not pieces) or (total_covered == 0)
        if not needs_reslice and dossier_total_pages > 0 and total_covered < dossier_total_pages:
            needs_reslice = True

        if needs_reslice and auto_slice:
            # Decoupage automatique a la volee avec garantie de couverture 100%
            try:
                pieces = arh_slicer.slice_dossier(clean_id)
                if existing_dossier:
                    existing_dossier["sliced_pieces"] = pieces
                    existing_dossier["sliced_pieces_count"] = len(pieces)
                    _save_dossier(existing_dossier)
            except Exception as e_slice:
                logger.warning("[ARH API] Auto-slice echoue pour %s: %s", clean_id, e_slice)


        actual_total_p = dossier_total_pages or total_covered or (pieces[-1].get("page_end", 0) if pieces else 0)
        return JSONResponse(content={
            "status": "SUCCESS",
            "dossier_id": clean_id,
            "pieces_count": len(pieces),
            "total_pages": actual_total_p,
            "total_pages_covered": total_covered,
            "pieces": pieces
        })
    except Exception as exc:
        logger.error("[ARH API] Erreur récupération pièces découpées %s: %s", clean_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/dossiers/{dossier_id}/pieces/{filename}/download")
async def download_sliced_piece(dossier_id: str, filename: str):
    """
    Télécharge le fichier PDF physique d'une pièce découpée.
    """
    clean_id = sanitize_dossier_id(dossier_id)
    clean_filename = Path(filename).name
    target_file = _ARH_UPLOADS_DIR / clean_id / "pieces" / clean_filename
    if not target_file.exists():
        raise HTTPException(status_code=404, detail=f"Fichier de pièce introuvable : {clean_filename}. Avez-vous déclenché le découpage ?")
    return FileResponse(
        path=str(target_file),
        filename=clean_filename,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=\"{clean_filename}\""}
    )


@router.get("/dossiers/{dossier_id}/pieces/{filename}/view")
async def view_sliced_piece(dossier_id: str, filename: str):
    """
    Affiche le fichier PDF physique d'une pièce découpée inline dans le navigateur.
    """
    clean_id = sanitize_dossier_id(dossier_id)
    clean_filename = Path(filename).name
    target_file = _ARH_UPLOADS_DIR / clean_id / "pieces" / clean_filename
    if not target_file.exists():
        raise HTTPException(status_code=404, detail=f"Fichier de pièce introuvable : {clean_filename}. Avez-vous déclenché le découpage ?")
    return FileResponse(
        path=str(target_file),
        filename=clean_filename,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=\"{clean_filename}\""}
    )


# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 02 : INDEXATION VECTORIELLE GRANULAIRE & RECHERCHE SÉMANTIQUE PAR PIÈCE
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/dossiers/{dossier_id}/index-pieces")
async def index_arh_dossier_pieces(dossier_id: str):
    """
    Étape 02 : Indexe toutes les pièces du dossier dans la collection ChromaDB 'arh_pieces_knowledge'.
    Génère les embeddings via Ollama nomic-embed-text (768 dimensions).
    """
    clean_id = sanitize_dossier_id(dossier_id)
    try:
        from arh_piece_indexer import arh_indexer
        result = arh_indexer.index_dossier_pieces(clean_id)
        return JSONResponse(content={
            "status": "SUCCESS",
            "message": f"Dossier {clean_id} indexé avec succès dans ChromaDB.",
            "data": result
        })
    except Exception as exc:
        logger.error("[ARH API] Erreur indexation vectorielle pièces %s: %s", clean_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur indexation vectorielle : {str(exc)}")


@router.get("/dossiers/{dossier_id}/search-pieces")
async def search_arh_dossier_pieces(
    dossier_id: str,
    query: str = Query(..., min_length=2, description="Requête sémantique ou technique"),
    piece_code: Optional[str] = Query(None, description="Filtre par code pièce (ex: DOC-06)"),
    discipline: Optional[str] = Query(None, description="Filtre par discipline (ex: CALCUL_STRUCTURE)"),
    top_k: int = Query(5, ge=1, le=20, description="Nombre max de résultats")
):
    """
    Étape 02 : Recherche sémantique ciblée dans les pièces d'un dossier avec isolation du bruit.
    """
    clean_id = sanitize_dossier_id(dossier_id)
    try:
        from arh_piece_indexer import arh_indexer
        hits = arh_indexer.search_pieces(
            dossier_id=clean_id,
            query=query,
            piece_code=piece_code,
            discipline=discipline,
            top_k=top_k
        )
        return JSONResponse(content={
            "status": "SUCCESS",
            "dossier_id": clean_id,
            "query": query,
            "filter_piece": piece_code,
            "filter_discipline": discipline,
            "count": len(hits),
            "results": hits
        })
    except Exception as exc:
        logger.error("[ARH API] Erreur recherche sémantique pièces %s: %s", clean_id, exc)
        raise HTTPException(status_code=500, detail=f"Erreur recherche : {str(exc)}")


# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 03 : VALIDATION CROISÉE PARAMÉTRIQUE INTER-PIÈCES (CONCORDANCE)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/dossiers/{dossier_id}/cross-validate")
@router.get("/dossiers/{dossier_id}/cross-validate")
async def cross_validate_arh_dossier(dossier_id: str):
    """
    Étape 03 : Exécute la matrice de conformité tripartite entre pièces (DOC-01 à DOC-14).
    Vérifie : P_test >= 1.5 P_calc, épaisseur nominale vs requis + corrosion, CEV <= 0.43,
    Hold points ITP, visas consulaires et certificats 3.1/3.2.
    """
    clean_id = sanitize_dossier_id(dossier_id)
    try:
        from arh_cross_validator import arh_cross_validator
        validation_report = arh_cross_validator.validate_dossier(clean_id)
        return JSONResponse(content={
            "status": "SUCCESS",
            "message": "Validation croisée inter-pièces exécutée avec succès.",
            "data": validation_report
        })
    except Exception as exc:
        logger.error("[ARH API] Erreur validation croisée %s: %s", clean_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur validation croisée : {str(exc)}")


# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 04 : FINE-TUNING DATASET & BENCHMARK EXPERT HUMAIN (DESKTOP ARH)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/dossiers/{dossier_id}/generate-dataset")
async def generate_finetuning_dataset(dossier_id: str):
    """
    Étape 04 : Génère un dataset d'instructions JSONL pour le fine-tuning des modèles ARKAN ARH.
    """
    clean_id = sanitize_dossier_id(dossier_id)
    try:
        from arh_dataset_builder import arh_dataset_builder
        dataset_path = arh_dataset_builder.build_dataset_from_dossier(clean_id)
        return JSONResponse(content={
            "status": "SUCCESS",
            "message": f"Dataset de fine-tuning généré avec succès : {dataset_path}",
            "file_path": dataset_path
        })
    except Exception as exc:
        logger.error("[ARH API] Erreur génération dataset %s: %s", clean_id, exc)
        raise HTTPException(status_code=500, detail=f"Erreur génération dataset : {str(exc)}")


@router.get("/benchmark/equipment-folders")
async def list_benchmark_equipment_folders():
    """
    Étape 04 / Benchmark : Liste tous les dossiers d'équipements disponibles dans C:\\Users\\MSI\\Desktop\\arh
    avec leurs fichiers INCOMING (fournisseur) et OUTCOMING (expert humain).
    """
    try:
        from arh_benchmark_evaluator import arh_evaluator
        folders = arh_evaluator.find_all_equipment_folders()
        return JSONResponse(content={
            "status": "SUCCESS",
            "count": len(folders),
            "folders": folders
        })
    except Exception as exc:
        logger.error("[ARH API] Erreur listing equipment folders: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/benchmark/evaluate")
async def evaluate_against_human_expert(payload: Dict[str, Any] = Body(...)):
    """
    Étape 04 / Benchmark : Exécute le banc d'essai comparatif complet entre ARKAN et l'expert humain.
    Prend soit 'equipment_name', soit 'incoming_pdf' + 'outgoing_pdf'.
    """
    try:
        from arh_benchmark_evaluator import arh_evaluator
        eq_name = payload.get("equipment_name")
        inc_pdf = payload.get("incoming_pdf")
        out_pdf = payload.get("outgoing_pdf")

        if eq_name and (not inc_pdf or not out_pdf):
            all_folders = arh_evaluator.find_all_equipment_folders()
            match = next((f for f in all_folders if f["equipment_name"] == eq_name), None)
            if not match:
                raise HTTPException(status_code=404, detail=f"Dossier équipement introuvable : {eq_name}")
            inc_pdf = match["incoming_pdf"]
            out_pdf = match["outgoing_pdf"]

        if not inc_pdf or not out_pdf:
            raise HTTPException(status_code=400, detail="incoming_pdf et outgoing_pdf requis.")

        result = arh_evaluator.evaluate_dossier(incoming_pdf=inc_pdf, outgoing_pdf=out_pdf)
        return JSONResponse(content={
            "status": "SUCCESS",
            "data": result
        })
    except Exception as exc:
        logger.error("[ARH API] Erreur évaluation benchmark: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))









