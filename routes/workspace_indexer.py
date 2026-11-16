import os, sys, re, sqlite3, logging, shutil, json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, Response
from fastapi.responses import FileResponse, JSONResponse

# ── DCC Lifecycles & OCR Service Integrations ──
try:
    from dots.dcc_lifecycles import (
        PREDEFINED_LIFECYCLES,
        EPC_DISCIPLINES,
        validate_codification,
        resolve_lifecycle_for_doc_type,
        get_step_info,
        calculate_weighted_project_progress,
        generate_sequential_codification,
        normalize_epc_discipline,
        normalize_epc_doc_type
    )
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from dots.dcc_lifecycles import (
        PREDEFINED_LIFECYCLES,
        EPC_DISCIPLINES,
        validate_codification,
        resolve_lifecycle_for_doc_type,
        get_step_info,
        calculate_weighted_project_progress,
        generate_sequential_codification,
        normalize_epc_discipline,
        normalize_epc_doc_type
    )

try:
    from routes.ocr_service import extract_document_text
except ImportError:
    from ocr_service import extract_document_text

import fitz  # PyMuPDF engine for instant high-definition rendering

logger = logging.getLogger("arkan.workspace_indexer")

router = APIRouter(prefix="/api/workspace", tags=["Workspace & Plans Indexer"])

# Intégration validation IEC 82045 / DOT-09 Document Control
try:
    from dots.dot_09_doccontrol import validate_iec82045_codification
except ImportError:
    _DOC_CODE_REGEX = re.compile(
        r'^[A-Z0-9]{2,8}(?:[-_][A-Z0-9]{2,6}){2,5}(?:[-_](?:REV[-_]?)?[A-Z0-9]{1,3})?$',
        re.IGNORECASE
    )
    def validate_iec82045_codification(doc_number: str) -> bool:
        if not doc_number or not isinstance(doc_number, str):
            return False
        clean = doc_number.strip().upper()
        if len(clean) < 8 or len(clean) > 50:
            return False
        parts = re.split(r'[-_]', clean)
        if len(parts) < 3:
            return False
        return bool(_DOC_CODE_REGEX.match(clean))

DB_PATH = Path("d:/DATA BASE IA/arkan_workspace.db")
PROJECTS_ROOT = Path(r"D:\DATA BASE IA\data\00-Projet").resolve()
PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)

# Formats supportés par ARKAN : Plans CAO/DAO, Documents Office (Word, Excel, PowerPoint), PDF & Images
VALID_EXTS = {
    # Plans & CAO / DAO
    ".pdf", ".dwg", ".dxf",
    # Traitement de texte (Word)
    ".docx", ".doc",
    # Tableurs (Excel & Données)
    ".xlsx", ".xls", ".csv",
    # Présentations (PowerPoint)
    ".pptx", ".ppt",
    # Images & Scans haute résolution
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".svg", ".bmp"
}

def is_path_in_projects(path: Path) -> bool:
    """Vérifie strictement qu'un chemin réside à l'intérieur de D:\\DATA BASE IA\\data\\00-Projet."""
    try:
        resolved_child = path.resolve()
        resolved_root = PROJECTS_ROOT.resolve()
        return str(resolved_child).lower().startswith(str(resolved_root).lower())
    except Exception:
        return False

# ── 1. Initialisation de la Base de Données ──
def init_workspace_db():
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # Dossiers / Espaces de projets
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        code TEXT UNIQUE NOT NULL,
        folder_path TEXT NOT NULL,
        description TEXT DEFAULT '',
        is_indexed INTEGER DEFAULT 0,
        last_indexed_at TEXT DEFAULT NULL,
        file_count INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """)

    # Plans racine (Master Identity)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS master_drawings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folder_id INTEGER NOT NULL,
        drawing_root_no TEXT NOT NULL,
        title TEXT DEFAULT '',
        discipline TEXT DEFAULT 'PIPING',
        created_at TEXT NOT NULL,
        UNIQUE(folder_id, drawing_root_no),
        FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE
    )
    """)

    # Révisions successives de chaque plan
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS drawing_revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_drawing_id INTEGER NOT NULL,
        folder_id INTEGER NOT NULL,
        revision_label TEXT NOT NULL,
        revision_order INTEGER DEFAULT 0,
        file_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_size INTEGER DEFAULT 0,
        extension TEXT NOT NULL,
        doc_type TEXT DEFAULT 'ISO',
        is_latest INTEGER DEFAULT 1,
        uploaded_at TEXT NOT NULL,
        mto_summary_json TEXT DEFAULT NULL,
        FOREIGN KEY(master_drawing_id) REFERENCES master_drawings(id) ON DELETE CASCADE,
        FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE
    )
    """)

    # FCD (Fiches de Commentaires et Dérogations Client)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fcd_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folder_id INTEGER NOT NULL,
        fcd_number TEXT NOT NULL,
        client_name TEXT DEFAULT 'SONATRACH',
        file_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        upload_date TEXT NOT NULL,
        total_comments INTEGER DEFAULT 0,
        unresolved_comments INTEGER DEFAULT 0,
        FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE
    )
    """)

    # Commentaires Client FCD individuels
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fcd_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fcd_id INTEGER DEFAULT NULL,
        folder_id INTEGER NOT NULL,
        master_drawing_id INTEGER DEFAULT NULL,
        target_drawing_no TEXT NOT NULL,
        target_revision TEXT DEFAULT '',
        item_no TEXT DEFAULT '1',
        page_zone TEXT DEFAULT '',
        comment_text TEXT NOT NULL,
        severity TEXT DEFAULT 'MAJOR',
        status TEXT DEFAULT 'NON_LEVE',
        resolution_note TEXT DEFAULT '',
        resolved_in_revision TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        resolved_at TEXT DEFAULT NULL,
        FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE
    )
    """)

    # Index FTS5 pour recherche ultra-rapide façon Everything (< 5ms)
    cursor.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS indexed_files_fts USING fts5(
        file_name,
        drawing_root_no,
        revision_label,
        file_path,
        doc_type,
        folder_id UNINDEXED
    )
    """)

    
    # ── Tables DCC & Registre TDR ──
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tdr_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folder_id INTEGER NOT NULL,
        doc_number TEXT NOT NULL,
        title TEXT DEFAULT '',
        discipline TEXT NOT NULL,
        doc_type TEXT NOT NULL,
        current_revision TEXT NOT NULL,
        revision_count INTEGER DEFAULT 1,
        status_stage TEXT DEFAULT 'INGESTED',
        last_transmittal_no TEXT DEFAULT '',
        last_sent_date TEXT DEFAULT '',
        last_sent_purpose TEXT DEFAULT 'IFR',
        last_return_date TEXT DEFAULT '',
        last_return_transmittal TEXT DEFAULT '',
        client_approval_code TEXT DEFAULT '',
        iec_82045_valid INTEGER DEFAULT 1,
        active_file_path TEXT NOT NULL,
        active_file_name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(folder_id, doc_number),
        FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tdr_revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tdr_doc_id INTEGER NOT NULL,
        folder_id INTEGER NOT NULL,
        revision_label TEXT NOT NULL,
        revision_order INTEGER DEFAULT 0,
        file_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        transmittal_no TEXT DEFAULT '',
        sent_date TEXT DEFAULT '',
        sent_purpose TEXT DEFAULT '',
        return_date TEXT DEFAULT '',
        client_code TEXT DEFAULT '',
        uploaded_at TEXT NOT NULL,
        FOREIGN KEY(tdr_doc_id) REFERENCES tdr_documents(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tdr_transmittals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folder_id INTEGER NOT NULL,
        transmittal_no TEXT UNIQUE NOT NULL,
        direction TEXT NOT NULL,
        transmittal_date TEXT NOT NULL,
        recipient TEXT DEFAULT 'SONATRACH / CLIENT',
        sender TEXT DEFAULT 'DOCUMENT CONTROLLER',
        purpose TEXT DEFAULT 'IFR',
        total_documents INTEGER DEFAULT 0,
        remarks TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tdr_transmittal_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transmittal_id INTEGER NOT NULL,
        tdr_doc_id INTEGER NOT NULL,
        doc_number TEXT NOT NULL,
        revision_label TEXT NOT NULL,
        client_code TEXT DEFAULT '',
        comments TEXT DEFAULT '',
        FOREIGN KEY(transmittal_id) REFERENCES tdr_transmittals(id) ON DELETE CASCADE,
        FOREIGN KEY(tdr_doc_id) REFERENCES tdr_documents(id) ON DELETE CASCADE
    )
    """)

    try:
        cursor.execute("ALTER TABLE tdr_documents ADD COLUMN iec_82045_valid INTEGER DEFAULT 1")
    except Exception:
        pass

    # ── Tables DCC Enrichies : Cycles de Vie & Historique Délais ──
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tdr_lifecycle_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        associated_types_json TEXT DEFAULT '[]',
        steps_json TEXT NOT NULL,
        is_system INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tdr_document_step_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tdr_doc_id INTEGER NOT NULL,
        folder_id INTEGER NOT NULL,
        step_code TEXT NOT NULL,
        step_label TEXT DEFAULT '',
        actor TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT DEFAULT NULL,
        elapsed_days REAL DEFAULT 0.0,
        sla_limit_days INTEGER DEFAULT 0,
        is_delayed INTEGER DEFAULT 0,
        transmittal_no TEXT DEFAULT '',
        remarks TEXT DEFAULT '',
        FOREIGN KEY(tdr_doc_id) REFERENCES tdr_documents(id) ON DELETE CASCADE,
        FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE
    )
    """)

    # Migrations de colonnes pour 'folders'
    folder_cols = [
        ("codification_standard", "TEXT DEFAULT 'IEC_82045'"),
        ("codification_pattern", "TEXT DEFAULT NULL"),
        ("client_sla_days", "INTEGER DEFAULT 21"),
        ("engineer_sla_days", "INTEGER DEFAULT 14"),
        ("mdr_file_name", "TEXT DEFAULT ''"),
        ("custom_lifecycles_json", "TEXT DEFAULT '{}'")
    ]
    for col_name, col_type in folder_cols:
        try:
            cursor.execute(f"ALTER TABLE folders ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass

    # Migrations de colonnes pour 'tdr_documents'
    doc_cols = [
        ("lifecycle_id", "INTEGER DEFAULT 1"),
        ("current_step", "TEXT DEFAULT 'START'"),
        ("planned_delivery_date", "TEXT DEFAULT ''"),
        ("priority", "TEXT DEFAULT 'MEDIUM'"),
        ("expected_format", "TEXT DEFAULT 'PDF'"),
        ("assigned_author", "TEXT DEFAULT ''"),
        ("contract_weight", "REAL DEFAULT 1.0"),
        ("progress_percent", "REAL DEFAULT 10.0"),
        ("turnaround_count", "INTEGER DEFAULT 0"),
        ("engineer_days_spent", "REAL DEFAULT 0.0"),
        ("client_days_spent", "REAL DEFAULT 0.0"),
        ("step_started_at", "TEXT DEFAULT ''"),
        ("is_delayed", "INTEGER DEFAULT 0"),
        ("ocr_content", "TEXT DEFAULT ''")
    ]
    for col_name, col_type in doc_cols:
        try:
            cursor.execute(f"ALTER TABLE tdr_documents ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass

    # Initialisation des 10 templates systèmes prédéfinis si la table est vide
    cursor.execute("SELECT COUNT(*) FROM tdr_lifecycle_templates")
    if cursor.fetchone()[0] == 0:
        now_init = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for lc in PREDEFINED_LIFECYCLES:
            cursor.execute("""
                INSERT INTO tdr_lifecycle_templates (
                    id, code, name, description, associated_types_json, steps_json, is_system, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """, (
                lc["id"],
                lc["code"],
                lc["name"],
                lc["description"],
                json.dumps(lc["associated_doc_types"], ensure_ascii=False),
                json.dumps(lc["steps"], ensure_ascii=False),
                now_init
            ))


    conn.commit()
    conn.close()
    logger.info("[WorkspaceDB] Base de données workspace et indexation FTS5 initialisée : %s", DB_PATH)

init_workspace_db()


# ── 2. Analyseurs et Extracteurs Intelligents ──

def parse_drawing_root_and_rev(file_name: str) -> Dict[str, Any]:
    """
    Extrait l'identité racine du plan, l'indice de révision et le type de document
    selon les conventions EPC / Oil & Gas (Sonatrach, Saipem, Technip, Petrofac).
    """
    clean_stem = Path(file_name).stem.strip()
    ext = Path(file_name).suffix.lower()

    # 1. Extraction de la révision
    rev_label = "REV 0"
    rev_order = 0

    # Priorité 1: Mots clés explicites REV ou REVISION (ex: REV 0, REV-1, REVISION_B)
    rev_match = re.search(r'\b(?:REV|REVISION)[-_\.\s]*([A-Z0-9]+)\b', clean_stem, re.IGNORECASE)
    if not rev_match:
        # Priorité 2: R suivi strictement de chiffres (ex: R0, R1, R-02), évitant les codes comme ROK1 ou RHB
        rev_match = re.search(r'\bR[-_\.\s]*(\d+)\b', clean_stem, re.IGNORECASE)

    if rev_match:
        val = rev_match.group(1).upper()
        rev_label = f"REV {val}"
        if val.isdigit():
            rev_order = int(val)
        elif len(val) == 1 and val.isalpha():
            rev_order = ord(val) - ord('A') + 10  # REV A = 10, REV B = 11...
    else:
        # Fallback indice en fin de chaîne (ex: _0, _1, -01)
        tail_m = re.search(r'[-_](?:0?(\d+)|([A-Z]))$', clean_stem)
        if tail_m:
            if tail_m.group(1):
                rev_order = int(tail_m.group(1))
                rev_label = f"REV {rev_order}"
            elif tail_m.group(2):
                letter = tail_m.group(2).upper()
                rev_order = ord(letter) - ord('A') + 10
                rev_label = f"REV {letter}"

    # 2. Extraction du Numéro Racine du Plan
    root_candidate = clean_stem
    # Nettoyer les mentions de révision, carnets, et préfixes usuels
    root_candidate = re.sub(r'\b(?:Pages\s+de\s+|Carnet\s+des\s+plans\s+isom[ée]trique[s]?\s*(?:de\s+la\s+tuyauterie\s+anti-incendie\s+zone\s+station\s+principale)?)\b', '', root_candidate, flags=re.IGNORECASE)
    root_candidate = re.sub(r'\b(?:REV|REVISION)[-_\.\s]*[A-Z0-9]+\b', '', root_candidate, flags=re.IGNORECASE)
    root_candidate = re.sub(r'\bR[-_\.\s]*\d+\b', '', root_candidate, flags=re.IGNORECASE)
    root_candidate = root_candidate.strip(" -_.,()")

    # Recherche d'un code plan standardisé (ex: C3421-ROK1-300-PIG-IW-300008, 14-WF-1ACX1PN-301-N-2)
    tag_m = re.search(r'\b([A-Z0-9]+(?:-[A-Z0-9]+){2,})\b', clean_stem, re.IGNORECASE)
    if tag_m:
        drawing_root = tag_m.group(1).upper()
        # Enlever la révision si elle a été capturée dans le tag
        drawing_root = re.sub(r'-(?:REV|REVISION)[-_\.\s]*[0-9A-Z]+$', '', drawing_root, flags=re.IGNORECASE)
        drawing_root = re.sub(r'-R\d+$', '', drawing_root, flags=re.IGNORECASE)
    elif root_candidate:
        drawing_root = root_candidate.upper()
    else:
        drawing_root = clean_stem.upper()

    # 3. Détermination du type de document et sous-discipline
    u_name = file_name.upper()
    sub_discipline = "GENERAL"

    if any(k in u_name for k in ("MALT", "TERRE", "ELE-DW-300001", "FOUDRE", "EARTH")):
        sub_discipline = "ELEC_EARTHING"
    elif any(k in u_name for k in ("CHEMIN", "ROUTING", "DW-300010", "DW-300011", "DW-300012", "DW-300013", "DW-300005")):
        sub_discipline = "ELEC_ROUTING"
    elif any(k in u_name for k in ("ECL", "ECLAIRAGE", "DW-300006", "DW-300007", "LUMINAIRE")):
        sub_discipline = "ELEC_LIGHTING"
    elif any(k in u_name for k in ("DN-300004", "DN-300005", "TGBT", "UPS", "BT")):
        sub_discipline = "ELEC_SLD_BT"
    elif any(k in u_name for k in ("30KV", "5.5KV", "DN-300002", "DN-300003", "DN-300006", "DN-300007", "MT")):
        sub_discipline = "ELEC_SLD_MT"
    elif any(k in u_name for k in ("ISO", "ISOMETRIC", "ISOMÉTRIQUE", "TUYAUTERIE", "IW-", "SP-", "PL-")):
        sub_discipline = "PIPING_ISO"
    elif any(k in u_name for k in ("PID", "P&ID", "P_ID", "FLOWSHEET", "PFD")):
        sub_discipline = "PROCESS_PID"
    elif any(k in u_name for k in ("FCD", "CRS", "COMMENT", "DEROGATION", "RESERVE")):
        sub_discipline = "FCD"

    if ext in (".dwg", ".dxf"):
        doc_type = "DWG"
    elif ext in (".docx", ".doc"):
        doc_type = "WORD"
    elif ext in (".xlsx", ".xls", ".csv"):
        doc_type = "EXCEL"
    elif ext in (".pptx", ".ppt"):
        doc_type = "POWERPOINT"
    elif sub_discipline != "GENERAL":
        doc_type = sub_discipline
    else:
        doc_type = "GENERAL"

    return {
        "drawing_root_no": drawing_root,
        "revision_label": rev_label,
        "revision_order": rev_order,
        "doc_type": doc_type,
        "sub_discipline": sub_discipline
    }


def parse_fcd_file_comments(file_path: str, fcd_number: str) -> List[Dict[str, Any]]:
    """
    Extrait les commentaires client depuis une FCD (PDF, Excel .xlsx ou CSV).
    """
    ext = Path(file_path).suffix.lower()
    comments = []

    if ext in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(file_path, data_only=True)
            sheet = wb.active
            for row in sheet.iter_rows(values_only=True):
                # Chercher une ligne contenant un commentaire
                row_str = " ".join([str(v) for v in row if v is not None])
                if len(row_str) > 15 and not any(k in row_str.upper() for k in ("CLIENT", "COMMENTAIRE", "STATUT", "VISA")):
                    # Tenter d'extraire la référence du plan
                    dwg_m = re.search(r'\b([A-Z0-9]+-[A-Z0-9\-]+)\b', row_str)
                    target_dwg = dwg_m.group(1) if dwg_m else fcd_number
                    comments.append({
                        "target_drawing_no": target_dwg,
                        "target_revision": "REV 0",
                        "comment_text": row_str[:300],
                        "severity": "CRITICAL" if any(w in row_str.upper() for w in ("NON CONFORME", "REJET", "IMPERATIF", "CRITIQUE")) else "MAJOR",
                        "status": "NON_LEVE"
                    })
        except Exception as e:
            logger.warning("[FCD Excel] Erreur parsing FCD Excel %s: %s", file_path, e)

    elif ext == ".pdf":
        try:
            import fitz
            doc = fitz.open(file_path)
            for page_idx, page in enumerate(doc):
                text = page.get_text()
                lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 8]
                for l in lines:
                    if any(k in l.upper() for k in ("DEVIATION", "NON CONFORME", "MODIFIER", "AJOUTER", "INCORRECT", "REVUE", "REMARQUE", "A CORRIGER", "EXIGENCE")):
                        dwg_m = re.search(r'\b([A-Z0-9]+-[A-Z0-9\-]+)\b', l)
                        target_dwg = dwg_m.group(1) if dwg_m else Path(file_path).stem
                        comments.append({
                            "target_drawing_no": target_dwg,
                            "target_revision": "REV 0",
                            "comment_text": l[:350],
                            "page_zone": f"Page {page_idx + 1}",
                            "severity": "CRITICAL" if any(w in l.upper() for w in ("NON CONFORME", "REJET", "IMPERATIF")) else "MAJOR",
                            "status": "NON_LEVE"
                        })
            doc.close()
        except Exception as e:
            logger.warning("[FCD PDF] Erreur parsing FCD PDF %s: %s", file_path, e)

    return comments


# ── 3. Endpoints REST FastAPI ──

@router.get("/root-info")
def get_workspace_root_info():
    """Retourne le répertoire racine unique des projets ARKAN et ses sous-dossiers disponibles."""
    subdirs = []
    if PROJECTS_ROOT.exists():
        for entry in os.scandir(PROJECTS_ROOT):
            if entry.is_dir() and not entry.name.startswith(('.', '$')):
                subdirs.append(entry.name)
    return {
        "status": "success",
        "projects_root": str(PROJECTS_ROOT),
        "available_subdirs": sorted(subdirs)
    }


@router.get("/folders")
def list_workspace_folders():
    """
    Liste tous les dossiers de projet avec leur statut d'indexation et statistiques.
    Prend EXCLUSIVEMENT en considération les dossiers situés dans D:\\DATA BASE IA\\data\\00-Projet.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Éliminer tout dossier hors de 00-Projet ou supprimé du disque
    cursor.execute("SELECT id, folder_path FROM folders")
    existing_folders = cursor.fetchall()
    for f in existing_folders:
        p = Path(f["folder_path"])
        if not is_path_in_projects(p) or not p.exists():
            f_id = f["id"]
            cursor.execute("DELETE FROM drawing_revisions WHERE folder_id = ?", (f_id,))
            cursor.execute("DELETE FROM master_drawings WHERE folder_id = ?", (f_id,))
            cursor.execute("DELETE FROM fcd_comments WHERE folder_id = ?", (f_id,))
            cursor.execute("DELETE FROM fcd_documents WHERE folder_id = ?", (f_id,))
            cursor.execute("DELETE FROM indexed_files_fts WHERE folder_id = ?", (f_id,))
            cursor.execute("DELETE FROM folders WHERE id = ?", (f_id,))
    conn.commit()

    # 2. Synchroniser les sous-dossiers réels de D:\DATA BASE IA\data\00-Projet
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    CODE_MAP = {
        "10-Station boosting": "10-BOOST",
        "Dossier ARH": "ARH-DOSSIER",
        "HSSEN": "HSSEN-01",
        "Station de pompage": "SP-POMPAGE",
        "TEST": "TEST-01",
        "TEST_OG_PROJECT": "TEST-OG",
        "TEST_ONT_PROJECT": "TEST-ONT"
    }

    if PROJECTS_ROOT.exists():
        for entry in os.scandir(PROJECTS_ROOT):
            if entry.is_dir() and not entry.name.startswith(('.', '$')):
                sub_path = str(Path(entry.path).resolve())
                cursor.execute("SELECT id FROM folders WHERE folder_path = ?", (sub_path,))
                if not cursor.fetchone():
                    folder_name = entry.name
                    code = CODE_MAP.get(folder_name, re.sub(r'[^A-Z0-9]', '-', folder_name.upper()).strip('-')[:15] or "PROJ")
                    cursor.execute("SELECT id FROM folders WHERE code = ?", (code,))
                    if cursor.fetchone():
                        code = f"{code}-{int(datetime.now().timestamp()) % 1000}"
                    cursor.execute("""
                    INSERT INTO folders (name, code, folder_path, description, is_indexed, file_count, created_at)
                    VALUES (?, ?, ?, ?, 0, 0, ?)
                    """, (folder_name, code, sub_path, f"Dossier projet local dans {PROJECTS_ROOT.name}", now_str))
        conn.commit()

    cursor.execute("""
    SELECT f.*,
           (SELECT COUNT(DISTINCT m.id) FROM master_drawings m WHERE m.folder_id = f.id) as master_drawings_count,
           (SELECT COUNT(*) FROM drawing_revisions r WHERE r.folder_id = f.id) as total_revisions_count,
           (SELECT COUNT(*) FROM fcd_comments c WHERE c.folder_id = f.id AND c.status = 'NON_LEVE') as unlifted_comments_count
    FROM folders f
    ORDER BY f.id ASC
    """)
    rows = cursor.fetchall()
    folders = [dict(r) for r in rows]
    conn.close()

    return {"status": "success", "folders": folders, "projects_root": str(PROJECTS_ROOT)}


@router.post("/folders/create")
def create_workspace_folder(
    name: str = Form(...),
    code: str = Form(...),
    folder_name: Optional[str] = Form(None),
    folder_path: Optional[str] = Form(None),
    description: str = Form("")
):
    """
    Crée un nouvel espace/dossier de travail dans ARKAN.
    GARANTIE STRICTE : Le dossier est obligatoirement créé à l'intérieur de D:\\DATA BASE IA\\data\\00-Projet.
    """
    # Déterminer le sous-dossier dans 00-Projet
    sub_name = (folder_name or folder_path or name).strip()
    # Si un chemin complet était passé, en extraire le nom final pour rester confiné dans 00-Projet
    if "\\" in sub_name or "/" in sub_name:
        sub_name = Path(sub_name).name

    clean_sub_name = re.sub(r'[\\/:*?"<>|]', '_', sub_name).strip()
    if not clean_sub_name:
        raise HTTPException(status_code=400, detail="Nom de dossier invalide.")

    target_path = (PROJECTS_ROOT / clean_sub_name).resolve()
    if not is_path_in_projects(target_path):
        raise HTTPException(status_code=400, detail="Sécurité : Le dossier doit obligatoirement être créé dans D:\\DATA BASE IA\\data\\00-Projet.")

    if not target_path.exists():
        target_path.mkdir(parents=True, exist_ok=True)

    clean_path = str(target_path)
    clean_code = code.strip().upper()

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
        INSERT INTO folders (name, code, folder_path, description, is_indexed, created_at)
        VALUES (?, ?, ?, ?, 0, ?)
        """, (name.strip(), clean_code, clean_path, description.strip(), now_str))
        folder_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Un dossier avec le code '{clean_code}' ou ce chemin existe déjà.")
    finally:
        conn.close()

    return {
        "status": "success",
        "message": f"Dossier '{name}' créé avec succès dans {clean_path}. L'indexation est requise avant recherche.",
        "folder_id": folder_id,
        "folder_path": clean_path,
        "is_indexed": False
    }


@router.delete("/folders/{folder_id}")
def delete_workspace_folder(folder_id: int):
    """Supprime un espace dossier et ses index d'ARKAN (et son dossier physique sous 00-Projet)."""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, folder_path FROM folders WHERE id = ?", (folder_id,))
    f_row = cursor.fetchone()
    if not f_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Dossier introuvable.")

    folder_name = f_row[1]
    folder_path_str = f_row[2]
    project_id_clean = folder_name.lower().replace(" ", "_").replace("&", "and")

    # 1. Nettoyage complet arkan_workspace.db
    cursor.execute("DELETE FROM drawing_revisions WHERE folder_id = ?", (folder_id,))
    cursor.execute("DELETE FROM master_drawings WHERE folder_id = ?", (folder_id,))
    cursor.execute("DELETE FROM fcd_comments WHERE folder_id = ?", (folder_id,))
    cursor.execute("DELETE FROM fcd_documents WHERE folder_id = ?", (folder_id,))
    cursor.execute("DELETE FROM indexed_files_fts WHERE folder_id = ?", (folder_id,))
    cursor.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
    conn.commit()
    conn.close()

    # 2. Nettoyage synchronisé dans data/verification.db (Cohérence & Anomalies)
    try:
        from verification_db import VERIFICATION_DB_PATH
        if VERIFICATION_DB_PATH.exists():
            v_conn = sqlite3.connect(str(VERIFICATION_DB_PATH))
            v_cur = v_conn.cursor()
            v_cur.execute("DELETE FROM verification_results WHERE project_id = ? OR project_id = ?", (project_id_clean, folder_name))
            v_cur.execute("DELETE FROM equipment_attributes WHERE project_id = ? OR project_id = ?", (project_id_clean, folder_name))
            v_conn.commit()
            v_conn.close()
    except Exception as e_v:
        logger.warning("[Workspace] Erreur nettoyage verification.db: %s", e_v)

    # 3. Suppression physique du dossier sur disque si situé strictement sous 00-Projet
    f_path = Path(folder_path_str).resolve()
    if is_path_in_projects(f_path) and f_path != PROJECTS_ROOT.resolve() and f_path.exists():
        try:
            shutil.rmtree(f_path, ignore_errors=True)
            logger.info("[Workspace] Dossier physique supprimé avec succès : %s", f_path)
        except Exception as e_rm:
            logger.warning("[Workspace] Impossible de supprimer le dossier physique %s : %s", f_path, e_rm)

    return {"status": "success", "message": f"Dossier '{folder_name}' supprimé avec succès de tous les onglets ARKAN."}


@router.post("/folders/{folder_id}/index")
def index_folder_everything(folder_id: int):
    """
    Exécute une indexation ultra-rapide façon Everything (Voidtools) :
    - Parcours récursif haute vitesse (os.scandir)
    - Analyse de toutes les révisions et classement parent/enfant
    - Parsing des FCD client et extraction des commentaires non levés
    - Remplissage de la table FTS5 pour recherche à la milliseconde
    """
    t0 = datetime.now()
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    cursor.execute("SELECT folder_path, name FROM folders WHERE id = ?", (folder_id,))
    f_row = cursor.fetchone()
    if not f_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Dossier introuvable.")

    folder_path, folder_name = f_row[0], f_row[1]
    f_path_obj = Path(folder_path).resolve()
    if not is_path_in_projects(f_path_obj):
        conn.close()
        raise HTTPException(status_code=403, detail="Accès refusé : Le dossier ne réside pas dans D:\\DATA BASE IA\\data\\00-Projet.")

    if not f_path_obj.exists():
        conn.close()
        raise HTTPException(status_code=400, detail=f"Le chemin disque n'existe pas : {folder_path}")

    # Réinitialiser les index existants pour ce dossier
    cursor.execute("DELETE FROM drawing_revisions WHERE folder_id = ?", (folder_id,))
    cursor.execute("DELETE FROM master_drawings WHERE folder_id = ?", (folder_id,))
    cursor.execute("DELETE FROM fcd_comments WHERE folder_id = ?", (folder_id,))
    cursor.execute("DELETE FROM fcd_documents WHERE folder_id = ?", (folder_id,))
    cursor.execute("DELETE FROM indexed_files_fts WHERE folder_id = ?", (folder_id,))

    valid_exts = VALID_EXTS

    # Parcours récursif haute vitesse (os.scandir)
    scanned_files = []
    stack = [folder_path]
    while stack:
        curr_dir = stack.pop()
        try:
            with os.scandir(curr_dir) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        if not entry.name.startswith((".", "$", "venv", "node_modules")):
                            stack.append(entry.path)
                    elif entry.is_file():
                        if entry.name.startswith(("~$", ".~")):
                            continue
                        p = Path(entry.path)
                        if p.suffix.lower() in valid_exts:
                            stat = entry.stat()
                            scanned_files.append({
                                "name": entry.name,
                                "path": entry.path,
                                "size": stat.st_size,
                                "ext": p.suffix.lower()
                            })
        except Exception as e_scan:
            logger.debug("[Everything Indexer] Erreur scan %s: %s", curr_dir, e_scan)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Regrouper par plan racine
    groups: Dict[str, List[Dict[str, Any]]] = {}
    fcd_files = []

    for f in scanned_files:
        meta = parse_drawing_root_and_rev(f["name"])
        f.update(meta)
        if meta["doc_type"] == "FCD":
            fcd_files.append(f)
        else:
            root = meta["drawing_root_no"]
            if root not in groups:
                groups[root] = []
            groups[root].append(f)

    # 1. Enregistrement des Plans et de leurs Révisions Successives
    for root_no, revs in groups.items():
        # Déterminer la discipline générale
        disc = revs[0]["doc_type"]
        cursor.execute("""
        INSERT INTO master_drawings (folder_id, drawing_root_no, title, discipline, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, (folder_id, root_no, f"Plan {root_no}", disc, now_str))
        master_id = cursor.lastrowid

        # Trier les révisions pour déterminer avec certitude la plus récente
        revs.sort(key=lambda r: (r["revision_order"], r["size"]), reverse=True)

        for idx, r in enumerate(revs):
            is_latest = 1 if idx == 0 else 0
            cursor.execute("""
            INSERT INTO drawing_revisions (
                master_drawing_id, folder_id, revision_label, revision_order,
                file_name, file_path, file_size, extension, doc_type, is_latest, uploaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                master_id, folder_id, r["revision_label"], r["revision_order"],
                r["name"], r["path"], r["size"], r["ext"], r["doc_type"], is_latest, now_str
            ))

            # Insertion dans l'index FTS5 Everything
            cursor.execute("""
            INSERT INTO indexed_files_fts (file_name, drawing_root_no, revision_label, file_path, doc_type, folder_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (r["name"], root_no, r["revision_label"], r["path"], r["doc_type"], folder_id))

    # 2. Parsing et Enregistrement des FCD Client
    total_unlifted = 0
    for fcd in fcd_files:
        fcd_no = Path(fcd["name"]).stem
        comments = parse_fcd_file_comments(fcd["path"], fcd_no)

        unlifted_count = sum(1 for c in comments if c["status"] == "NON_LEVE")
        total_unlifted += unlifted_count

        cursor.execute("""
        INSERT INTO fcd_documents (folder_id, fcd_number, file_name, file_path, upload_date, total_comments, unresolved_comments)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (folder_id, fcd_no, fcd["name"], fcd["path"], now_str, len(comments), unlifted_count))
        fcd_id = cursor.lastrowid

        for c in comments:
            cursor.execute("""
            INSERT INTO fcd_comments (
                fcd_id, folder_id, target_drawing_no, target_revision,
                page_zone, comment_text, severity, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fcd_id, folder_id, c["target_drawing_no"], c.get("target_revision", "REV 0"),
                c.get("page_zone", ""), c["comment_text"], c.get("severity", "MAJOR"), c["status"], now_str
            ))

    # Mettre à jour le statut du dossier
    cursor.execute("""
    UPDATE folders
    SET is_indexed = 1, last_indexed_at = ?, file_count = ?
    WHERE id = ?
    """, (now_str, len(scanned_files), folder_id))

    conn.commit()
    conn.close()

    elapsed_ms = (datetime.now() - t0).total_seconds() * 1000.0
    logger.info("[Everything Indexer] %d fichiers indexés dans '%s' en %.1f ms (%d plans maîtres, %d FCD)",
                len(scanned_files), folder_name, elapsed_ms, len(groups), len(fcd_files))

    return {
        "status": "success",
        "message": f"Indexation Everything réussie : {len(scanned_files)} fichiers traités en {elapsed_ms:.1f} ms.",
        "folder_id": folder_id,
        "is_indexed": True,
        "file_count": len(scanned_files),
        "master_drawings_count": len(groups),
        "fcd_count": len(fcd_files),
        "unlifted_comments_count": total_unlifted,
        "elapsed_ms": round(elapsed_ms, 1)
    }


@router.get("/folders/{folder_id}/search")
def search_workspace_drawings(
    folder_id: int,
    q: str = Query("", description="Terme de recherche instantané"),
    doc_type: Optional[str] = Query(None, description="Filtre doc_type (ISO, PID, DWG...)"),
    latest_only: bool = Query(True, description="Uniquement la dernière révision en vigueur")
):
    """
    Recherche instantanée type Everything :
    CONDITION STRICTE : Bloqué et renvoie une erreur si le dossier n'est pas indexé !
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Vérification stricte du statut d'indexation
    cursor.execute("SELECT is_indexed, name FROM folders WHERE id = ?", (folder_id,))
    f_row = cursor.fetchone()
    if not f_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Dossier introuvable.")

    if not f_row["is_indexed"]:
        conn.close()
        return JSONResponse(status_code=403, content={
            "status": "error",
            "error_code": "FOLDER_NOT_INDEXED",
            "message": f"Le dossier '{f_row['name']}' n'est pas encore indexé. La recherche et la visualisation sont verrouillées. Veuillez lancer l'indexation.",
            "is_indexed": False
        })

    # 2. Recherche rapide B-Tree / FTS5
    term = q.strip()
    results = []

    sql = """
    SELECT m.id as master_id, m.drawing_root_no, m.title, m.discipline,
           r.id as revision_id, r.revision_label, r.revision_order, r.file_name,
           r.file_path, r.file_size, r.extension, r.doc_type, r.is_latest, r.uploaded_at,
           (SELECT COUNT(*) FROM fcd_comments c WHERE c.folder_id = m.folder_id AND (c.target_drawing_no = m.drawing_root_no OR c.target_drawing_no LIKE '%' || m.drawing_root_no || '%') AND c.status = 'NON_LEVE') as unlifted_fcd_count
    FROM master_drawings m
    JOIN drawing_revisions r ON r.master_drawing_id = m.id
    WHERE m.folder_id = ?
    """
    params = [folder_id]

    if latest_only:
        sql += " AND r.is_latest = 1 "

    if doc_type and doc_type != "ALL":
        sql += " AND r.doc_type = ? "
        params.append(doc_type.upper())

    if term:
        sql += " AND (m.drawing_root_no LIKE ? OR r.file_name LIKE ? OR r.revision_label LIKE ?) "
        like_term = f"%{term}%"
        params.extend([like_term, like_term, like_term])

    sql += " ORDER BY m.drawing_root_no ASC, r.revision_order DESC LIMIT 100 "

    cursor.execute(sql, params)
    rows = cursor.fetchall()

    # Récupérer les sous-révisions pour chaque master drawing trouvé
    master_dict: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        m_id = r["master_id"]
        if m_id not in master_dict:
            master_dict[m_id] = {
                "master_id": m_id,
                "drawing_root_no": r["drawing_root_no"],
                "title": r["title"],
                "discipline": r["discipline"],
                "unlifted_fcd_count": r["unlifted_fcd_count"],
                "latest_revision": None,
                "all_revisions": []
            }

        rev_data = {
            "revision_id": r["revision_id"],
            "revision_label": r["revision_label"],
            "revision_order": r["revision_order"],
            "file_name": r["file_name"],
            "file_path": r["file_path"],
            "file_size": r["file_size"],
            "extension": r["extension"],
            "doc_type": r["doc_type"],
            "is_latest": bool(r["is_latest"]),
            "uploaded_at": r["uploaded_at"]
        }
        if r["is_latest"]:
            master_dict[m_id]["latest_revision"] = rev_data

        # Chercher toutes les révisions de ce plan
        cursor.execute("""
        SELECT id, revision_label, revision_order, file_name, file_path, file_size, is_latest, uploaded_at
        FROM drawing_revisions
        WHERE master_drawing_id = ?
        ORDER BY revision_order DESC
        """, (m_id,))
        sub_revs = [dict(sub) for sub in cursor.fetchall()]
        master_dict[m_id]["all_revisions"] = sub_revs

    conn.close()

    return {
        "status": "success",
        "folder_id": folder_id,
        "query": term,
        "count": len(master_dict),
        "results": list(master_dict.values())
    }


@router.get("/masters/{master_id}")
def get_master_drawing_details(master_id: int):
    """
    Récupère instantanément un plan maître et toutes ses révisions par son ID unique.
    Garantit une visualisation sans échec quel que soit le filtre ou le statut de recherche.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
    SELECT m.id as master_id, m.folder_id, m.drawing_root_no, m.title, m.discipline,
           (SELECT COUNT(*) FROM fcd_comments c WHERE c.folder_id = m.folder_id AND (c.target_drawing_no = m.drawing_root_no OR c.target_drawing_no LIKE '%' || m.drawing_root_no || '%') AND c.status = 'NON_LEVE') as unlifted_fcd_count
    FROM master_drawings m
    WHERE m.id = ?
    """, (master_id,))
    m_row = cursor.fetchone()
    if not m_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Plan maître introuvable.")

    master = dict(m_row)

    cursor.execute("""
    SELECT id, revision_label, revision_order, file_name, file_path, file_size, extension, doc_type, is_latest, uploaded_at
    FROM drawing_revisions
    WHERE master_drawing_id = ?
    ORDER BY revision_order DESC, id DESC
    """, (master_id,))
    rev_rows = cursor.fetchall()
    conn.close()

    all_revisions = [dict(r) for r in rev_rows]
    latest = next((r for r in all_revisions if r.get("is_latest")), all_revisions[0] if all_revisions else None)
    master["latest_revision"] = latest
    master["all_revisions"] = all_revisions

    return {"status": "success", "master": master}


@router.post("/folders/{folder_id}/insert-plan")
async def insert_single_plan(
    folder_id: int,
    file: UploadFile = File(...)
):
    """
    Insère un plan un par un dans le dossier indexé :
    - Détecte automatiquement s'il s'agit d'une NOUVELLE RÉVISION d'un plan existant
    - Archive l'ancienne révision et active la nouvelle (is_latest = 1)
    - Alerte si des commentaires FCD étaient ouverts sur l'ancienne version
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    cursor.execute("SELECT folder_path, is_indexed FROM folders WHERE id = ?", (folder_id,))
    f_row = cursor.fetchone()
    if not f_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Dossier introuvable.")

    folder_path, is_indexed = f_row[0], bool(f_row[1])
    dest_path = (Path(folder_path) / file.filename).resolve()
    if not is_path_in_projects(dest_path):
        conn.close()
        raise HTTPException(status_code=403, detail="Accès refusé : Le dossier ne réside pas dans D:\\DATA BASE IA\\data\\00-Projet.")

    with open(dest_path, "wb") as f_out:
        shutil.copyfileobj(file.file, f_out)

    file_size = dest_path.stat().st_size
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Analyse du nom de fichier et extraction racine / révision
    meta = parse_drawing_root_and_rev(file.filename)
    root_no = meta["drawing_root_no"]
    rev_label = meta["revision_label"]
    rev_order = meta["revision_order"]
    doc_type = meta["doc_type"]
    ext = dest_path.suffix.lower()

    # Vérifier si le plan maître existe déjà
    cursor.execute("SELECT id FROM master_drawings WHERE folder_id = ? AND drawing_root_no = ?", (folder_id, root_no))
    master_row = cursor.fetchone()

    is_new_revision = False
    old_rev_label = None

    if master_row:
        master_id = master_row[0]
        # Obtenir la révision active actuelle
        cursor.execute("SELECT revision_label, revision_order FROM drawing_revisions WHERE master_drawing_id = ? AND is_latest = 1", (master_id,))
        curr_active = cursor.fetchone()

        if curr_active:
            old_rev_label = curr_active[0]
            old_order = curr_active[1]
            if rev_order >= old_order:
                is_new_revision = True
                # Rétrograder l'ancienne version en archive
                cursor.execute("UPDATE drawing_revisions SET is_latest = 0 WHERE master_drawing_id = ?", (master_id,))
    else:
        cursor.execute("""
        INSERT INTO master_drawings (folder_id, drawing_root_no, title, discipline, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, (folder_id, root_no, f"Plan {root_no}", doc_type, now_str))
        master_id = cursor.lastrowid

    # Enregistrer la nouvelle révision
    cursor.execute("""
    INSERT INTO drawing_revisions (
        master_drawing_id, folder_id, revision_label, revision_order,
        file_name, file_path, file_size, extension, doc_type, is_latest, uploaded_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (master_id, folder_id, rev_label, rev_order, file.filename, str(dest_path), file_size, ext, doc_type, 1, now_str))
    new_rev_id = cursor.lastrowid

    # Ajouter dans FTS5
    cursor.execute("""
    INSERT INTO indexed_files_fts (file_name, drawing_root_no, revision_label, file_path, doc_type, folder_id)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (file.filename, root_no, rev_label, str(dest_path), doc_type, folder_id))

    # Mettre à jour le compteur du dossier
    cursor.execute("UPDATE folders SET file_count = file_count + 1 WHERE id = ?", (folder_id,))

    # Vérifier s'il y a des commentaires FCD non levés pour ce plan
    cursor.execute("""
    SELECT COUNT(*) FROM fcd_comments
    WHERE folder_id = ? AND (target_drawing_no = ? OR target_drawing_no LIKE '%' || ? || '%') AND status = 'NON_LEVE'
    """, (folder_id, root_no, root_no))
    pending_fcd = cursor.fetchone()[0]

    conn.commit()
    conn.close()

    msg = f"Plan {root_no} ({rev_label}) inséré et indexé avec succès."
    if is_new_revision:
        msg = f"Nouvelle révision détectée ! {rev_label} remplace la version {old_rev_label}."
    if pending_fcd > 0:
        msg += f" ⚠️ Attention : {pending_fcd} commentaire(s) client sont actuellement non levés sur ce plan."

    return {
        "status": "success",
        "message": msg,
        "is_new_revision": is_new_revision,
        "drawing_root_no": root_no,
        "revision_label": rev_label,
        "previous_revision": old_rev_label,
        "pending_fcd_comments": pending_fcd,
        "revision_id": new_rev_id,
        "file_path": str(dest_path)
    }


@router.get("/folders/{folder_id}/fcd-comments")
def list_fcd_comments_dashboard(
    folder_id: int,
    status_filter: str = Query("ALL", description="ALL, NON_LEVE, EN_COURS, LEVE"),
    target_drawing: Optional[str] = Query(None)
):
    """Retourne la liste des commentaires client pour le tableau de bord FCD."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # KPIs globaux
    cursor.execute("""
    SELECT
        COUNT(*) as total,
        SUM(CASE WHEN status = 'NON_LEVE' THEN 1 ELSE 0 END) as non_leve_count,
        SUM(CASE WHEN status = 'EN_COURS' THEN 1 ELSE 0 END) as en_cours_count,
        SUM(CASE WHEN status = 'LEVE' THEN 1 ELSE 0 END) as leve_count
    FROM fcd_comments
    WHERE folder_id = ?
    """, (folder_id,))
    kpi_row = cursor.fetchone()
    kpis = {
        "total": kpi_row["total"] or 0,
        "non_leve": kpi_row["non_leve_count"] or 0,
        "en_cours": kpi_row["en_cours_count"] or 0,
        "leve": kpi_row["leve_count"] or 0
    }

    sql = """
    SELECT c.*, f.fcd_number, f.client_name
    FROM fcd_comments c
    LEFT JOIN fcd_documents f ON f.id = c.fcd_id
    WHERE c.folder_id = ?
    """
    params = [folder_id]

    if status_filter != "ALL":
        sql += " AND c.status = ? "
        params.append(status_filter.upper())

    if target_drawing:
        sql += " AND (c.target_drawing_no = ? OR c.target_drawing_no LIKE '%' || ? || '%') "
        params.extend([target_drawing, target_drawing])

    sql += " ORDER BY CASE c.status WHEN 'NON_LEVE' THEN 1 WHEN 'EN_COURS' THEN 2 ELSE 3 END, c.id DESC "

    cursor.execute(sql, params)
    comments = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return {
        "status": "success",
        "kpis": kpis,
        "comments_count": len(comments),
        "comments": comments
    }


@router.put("/fcd-comments/{comment_id}/resolve")
def resolve_fcd_comment(
    comment_id: int,
    status: str = Form("LEVE"),
    resolution_note: str = Form(""),
    resolved_in_revision: str = Form("")
):
    """Met à jour le statut d'un commentaire FCD (lever la réserve client)."""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    resolved_at = now_str if status == "LEVE" else None

    cursor.execute("""
    UPDATE fcd_comments
    SET status = ?, resolution_note = ?, resolved_in_revision = ?, resolved_at = ?
    WHERE id = ?
    """, (status.upper(), resolution_note.strip(), resolved_in_revision.strip(), resolved_at, comment_id))

    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Commentaire introuvable.")

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "message": f"Commentaire #{comment_id} mis à jour : {status}",
        "comment_id": comment_id,
        "new_status": status
    }


@router.get("/view-file")
def stream_plan_file(path: str = Query(...)):
    """
    Permet la visualisation sécurisée de n'importe quel plan (PDF, PNG, JPG, DWG visual)
    dans la visionneuse intégrée d'ARKAN en mode INLINE (sans téléchargement forcé).
    """
    file_path = Path(path).resolve()
    if not is_path_in_projects(file_path):
        raise HTTPException(status_code=403, detail="Accès refusé : Le fichier ne réside pas dans D:\\DATA BASE IA\\data\\00-Projet.")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Fichier plan introuvable : {path}")

    ext = file_path.suffix.lower()
    media_types = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".svg": "image/svg+xml",
        ".bmp": "image/bmp",
        ".dwg": "application/acad",
        ".dxf": "application/dxf",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".csv": "text/csv; charset=utf-8",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".ppt": "application/vnd.ms-powerpoint"
    }
    media_type = media_types.get(ext, "application/octet-stream")

    headers = {
        "Content-Disposition": f'inline; filename="{file_path.name}"',
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=3600"
    }

    return FileResponse(str(file_path), media_type=media_type, headers=headers)


@router.get("/doc-info")
def get_document_info(path: str = Query(...)):
    """
    Retourne les métadonnées et le nombre exact de pages du document (PDF ou image).
    Permet la navigation multipages dans le visualiseur sans télécharger le fichier complet.
    """
    file_path = Path(path).resolve()
    if not is_path_in_projects(file_path):
        raise HTTPException(status_code=403, detail="Accès refusé : Le fichier ne réside pas dans D:\\DATA BASE IA\\data\\00-Projet.")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable.")

    ext = file_path.suffix.lower()
    page_count = 1
    w, h = 0, 0

    if ext == ".pdf":
        try:
            doc = fitz.open(str(file_path))
            page_count = len(doc)
            if page_count > 0:
                p0 = doc.load_page(0)
                rect = p0.rect
                w, h = int(rect.width), int(rect.height)
            doc.close()
        except Exception as e:
            logger.warning("[DocInfo] Erreur lecture PDF : %s", e)
            page_count = 1

    return {
        "status": "success",
        "file_name": file_path.name,
        "extension": ext,
        "size_bytes": file_path.stat().st_size,
        "page_count": page_count,
        "width": w,
        "height": h
    }


@router.get("/render-page")
def render_document_page(
    path: str = Query(...),
    page: int = Query(0),
    dpi: int = Query(150)
):
    """
    Effectue un rendu raster haute définition instantané (< 100 ms) de la page demandée
    via le moteur PyMuPDF. Supprime tout écran noir ou blocage lié aux iframes.
    """
    file_path = Path(path).resolve()
    if not is_path_in_projects(file_path):
        raise HTTPException(status_code=403, detail="Accès refusé : Le fichier ne réside pas dans D:\\DATA BASE IA\\data\\00-Projet.")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable.")

    ext = file_path.suffix.lower()

    if ext == ".pdf":
        try:
            doc = fitz.open(str(file_path))
            total = len(doc)
            if total == 0:
                doc.close()
                raise HTTPException(status_code=400, detail="Document PDF vide.")

            target_page = max(0, min(page, total - 1))
            p = doc.load_page(target_page)
            # Rendu haute fidélité à 150 DPI (netteté optimale pour plans d'ingénierie)
            pix = p.get_pixmap(dpi=dpi)
            png_bytes = pix.tobytes("png")
            doc.close()

            return Response(content=png_bytes, media_type="image/png", headers={
                "Cache-Control": "public, max-age=3600",
                "Access-Control-Allow-Origin": "*"
            })
        except HTTPException:
            raise
        except Exception as e:
            logger.error("[RenderPage] Erreur rendu PDF : %s", e)
            raise HTTPException(status_code=500, detail=f"Erreur de rendu graphique : {e}")

    elif ext in [".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".gif"]:
        media_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
            ".gif": "image/gif"
        }
        return FileResponse(str(file_path), media_type=media_types.get(ext, "image/png"))

    else:
        raise HTTPException(status_code=400, detail=f"Format {ext} non supporté pour rendu direct.")


@router.post("/open-native")
def open_file_in_native_app(path: str = Query(...)):
    """
    Ouvre instantanément le document ou plan dans son application native installée sur Windows
    (AutoCAD, Autodesk DWG TrueView, Microsoft Word, Microsoft Excel, Microsoft PowerPoint, etc.).
    """
    file_path = Path(path).resolve()
    if not is_path_in_projects(file_path):
        raise HTTPException(status_code=403, detail="Accès refusé : Le fichier ne réside pas dans D:\\DATA BASE IA\\data\\00-Projet.")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable.")

    try:
        if hasattr(os, "startfile"):
            os.startfile(str(file_path))
        else:
            import subprocess
            subprocess.Popen(["start", "", str(file_path)], shell=True)
        return {
            "status": "success",
            "message": f"Fichier ouvert avec succès dans l'application locale : {file_path.name}",
            "file_name": file_path.name,
            "path": str(file_path)
        }
    except Exception as e:
        logger.error("[OpenNative] Erreur ouverture locale : %s", e)
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'ouverture locale : {str(e)}")


@router.get("/preview-content")
def get_document_preview_content(
    path: str = Query(...),
    sheet: Optional[str] = Query(None),
    max_rows: int = Query(100),
    max_cols: int = Query(30)
):
    """
    Extrait le contenu structuré d'un tableur Excel (.xlsx, .xls, .csv), document Word (.docx),
    présentation PowerPoint (.pptx) ou fichier CAO (.dxf, .dwg) pour affichage interactif direct dans l'interface.
    """
    file_path = Path(path).resolve()
    if not is_path_in_projects(file_path):
        raise HTTPException(status_code=403, detail="Accès refusé : Le fichier ne réside pas dans D:\\DATA BASE IA\\data\\00-Projet.")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable.")

    ext = file_path.suffix.lower()

    # 1. EXCEL / TABLEURS (.xlsx, .xls, .csv)
    if ext in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(file_path), data_only=True, read_only=True)
            sheet_names = wb.sheetnames
            target_sheet_name = sheet if (sheet and sheet in sheet_names) else sheet_names[0]
            ws = wb[target_sheet_name]

            rows_data = []
            for r_idx, row in enumerate(ws.iter_rows(values_only=True)):
                if r_idx >= max_rows:
                    break
                row_vals = []
                for c_idx, val in enumerate(row):
                    if c_idx >= max_cols:
                        break
                    if val is None:
                        row_vals.append("")
                    elif isinstance(val, datetime):
                        row_vals.append(val.strftime("%Y-%m-%d %H:%M"))
                    else:
                        row_vals.append(str(val).strip())
                rows_data.append(row_vals)

            total_rows = getattr(ws, "max_row", len(rows_data)) or len(rows_data)
            total_cols = getattr(ws, "max_column", len(rows_data[0]) if rows_data else 0) or 0
            wb.close()

            return {
                "status": "success",
                "doc_type": "EXCEL",
                "file_name": file_path.name,
                "sheets": sheet_names,
                "active_sheet": target_sheet_name,
                "rows": rows_data,
                "total_rows": total_rows,
                "total_cols": total_cols
            }
        except Exception as e_xl:
            logger.warning("[PreviewContent] Erreur Excel : %s", e_xl)
            return {
                "status": "error",
                "doc_type": "EXCEL",
                "file_name": file_path.name,
                "message": f"Erreur de lecture du classeur Excel : {e_xl}"
            }

    elif ext == ".csv":
        try:
            import csv
            encodings = ["utf-8", "latin-1", "cp1252"]
            rows_data = []
            for enc in encodings:
                try:
                    with open(file_path, "r", encoding=enc, errors="replace") as f_csv:
                        reader = csv.reader(f_csv)
                        for r_idx, r in enumerate(reader):
                            if r_idx >= max_rows:
                                break
                            rows_data.append([str(c).strip() for c in r[:max_cols]])
                    break
                except Exception:
                    continue

            return {
                "status": "success",
                "doc_type": "EXCEL",
                "file_name": file_path.name,
                "sheets": ["Données CSV"],
                "active_sheet": "Données CSV",
                "rows": rows_data,
                "total_rows": len(rows_data),
                "total_cols": len(rows_data[0]) if rows_data else 0
            }
        except Exception as e_csv:
            return {
                "status": "error",
                "doc_type": "EXCEL",
                "file_name": file_path.name,
                "message": f"Erreur de lecture CSV : {e_csv}"
            }

    # 2. WORD (.docx, .doc)
    elif ext in (".docx", ".doc"):
        if ext == ".doc":
            return {
                "status": "success",
                "doc_type": "WORD",
                "file_name": file_path.name,
                "native_only": True,
                "message": "Fichier Word format binaire hérité (.doc). Utilisez le bouton Ouvrir en local pour l'ouvrir dans Microsoft Word."
            }

        try:
            import docx
            doc = docx.Document(str(file_path))
            elements = []

            for p in doc.paragraphs:
                text = p.text.strip()
                if not text:
                    continue
                style_name = p.style.name.lower() if p.style else "normal"
                if "heading 1" in style_name or "titre 1" in style_name:
                    el_type = "h1"
                elif "heading 2" in style_name or "titre 2" in style_name:
                    el_type = "h2"
                elif "heading 3" in style_name or "titre 3" in style_name:
                    el_type = "h3"
                elif "bullet" in style_name or "liste" in style_name:
                    el_type = "bullet"
                else:
                    el_type = "p"
                elements.append({"type": el_type, "text": text})

            tables_data = []
            for t_idx, t in enumerate(doc.tables[:15]):
                t_rows = []
                for row in t.rows[:50]:
                    t_rows.append([c.text.strip().replace("\n", " ") for c in row.cells])
                if t_rows:
                    tables_data.append({"table_index": t_idx + 1, "rows": t_rows})

            return {
                "status": "success",
                "doc_type": "WORD",
                "file_name": file_path.name,
                "elements": elements[:200],
                "tables": tables_data,
                "total_paragraphs": len(elements),
                "total_tables": len(doc.tables)
            }
        except Exception as e_docx:
            return {
                "status": "error",
                "doc_type": "WORD",
                "file_name": file_path.name,
                "message": f"Erreur de lecture Word : {e_docx}"
            }

    # 3. POWERPOINT (.pptx, .ppt)
    elif ext in (".pptx", ".ppt"):
        if ext == ".ppt":
            return {
                "status": "success",
                "doc_type": "POWERPOINT",
                "file_name": file_path.name,
                "native_only": True,
                "message": "Présentation PowerPoint binaire héritée (.ppt). Utilisez le bouton Ouvrir en local pour l'ouvrir dans Microsoft PowerPoint."
            }

        try:
            import pptx
            prs = pptx.Presentation(str(file_path))
            slides_data = []

            for s_idx, slide in enumerate(prs.slides):
                title = ""
                paragraphs = []
                tables = []
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for p in shape.text_frame.paragraphs:
                            t = p.text.strip()
                            if t:
                                if not title and hasattr(shape, "is_placeholder") and shape.is_placeholder:
                                    title = t
                                else:
                                    paragraphs.append(t)
                    elif shape.has_table:
                        tbl_rows = []
                        for row in shape.table.rows:
                            tbl_rows.append([c.text.strip().replace("\n", " ") for c in row.cells])
                        if tbl_rows:
                            tables.append(tbl_rows)

                slides_data.append({
                    "slide_number": s_idx + 1,
                    "title": title or f"Diapositive {s_idx + 1}",
                    "paragraphs": paragraphs[:20],
                    "tables": tables
                })

            return {
                "status": "success",
                "doc_type": "POWERPOINT",
                "file_name": file_path.name,
                "slides": slides_data,
                "total_slides": len(prs.slides)
            }
        except Exception as e_ppt:
            return {
                "status": "error",
                "doc_type": "POWERPOINT",
                "file_name": file_path.name,
                "message": f"Erreur de lecture PowerPoint : {e_ppt}"
            }

    # 4. CAD / DAO (.dxf, .dwg)
    elif ext in (".dxf", ".dwg"):
        if ext == ".dxf":
            try:
                import ezdxf
                doc = ezdxf.readfile(str(file_path))
                layers = [l.dxf.name for l in doc.layers]
                entity_counts = {}
                msp = doc.modelspace()
                for e in msp:
                    t = e.dxftype()
                    entity_counts[t] = entity_counts.get(t, 0) + 1

                return {
                    "status": "success",
                    "doc_type": "DWG",
                    "file_name": file_path.name,
                    "extension": ext,
                    "is_dxf": True,
                    "layers": layers[:40],
                    "total_layers": len(layers),
                    "entity_counts": entity_counts,
                    "native_launch_recommended": True,
                    "info": "Fichier DAO / CAO DXF lisible. Ouvrez en local pour l'édition et le traçage complet."
                }
            except Exception as e_dxf:
                logger.warning("[PreviewContent] Erreur DXF : %s", e_dxf)

        return {
            "status": "success",
            "doc_type": "DWG",
            "file_name": file_path.name,
            "extension": ext,
            "is_dxf": False,
            "native_launch_recommended": True,
            "info": "Dessin industriel natif AutoCAD / DWG. Utilisez le bouton '🚀 Ouvrir dans AutoCAD / DWG TrueView' pour une ouverture instantanée à l'échelle et avec gestion des calques."
        }

    else:
        raise HTTPException(status_code=400, detail=f"Aperçu structuré non supporté pour {ext}.")



# ── Endpoint Lancement MTO Multi-Disciplines Complet (ARKAN v3) ──

@router.post("/folders/{folder_id}/launch-mto-complete")
def launch_mto_complete_from_folder(folder_id: int):
    """
    Lance le calcul consolidé MTO multi-disciplines sur l'intégralité des plans d'un dossier.
    Traite Tuyauterie, Schémas Unifilaires, Cheminements, Réseau de Terre, Éclairage,
    exécute les 7 contrôles de recoupement croisé et génère le classeur maître 9 onglets.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM folders WHERE id = ?", (folder_id,))
    folder = cursor.fetchone()
    conn.close()

    if not folder:
        raise HTTPException(status_code=404, detail=f"Dossier {folder_id} introuvable.")

    folder_dir = Path(folder["folder_path"])
    if not folder_dir.exists():
        raise HTTPException(status_code=400, detail=f"Le répertoire {folder_dir} n'existe pas sur le disque.")

    from ie_drawing_extractor import extract_ie_drawing
    from ie_mto_validator import validate_ie_mto
    from cross_discipline_reconciler import run_cross_discipline_reconciliation
    from mto_consolidator import generate_master_multidiscipline_excel

    all_extracted_items = []
    processed_files = []
    failed_files = []

    # Balayage des fichiers récents (PDF et DWG)
    for root, dirs, files in os.walk(folder_dir):
        for f in files:
            ext = Path(f).suffix.lower()
            if ext in (".dwg", ".pdf") and not any(k in f.lower() for k in ["fcd", "comment", "bak", "plot"]):
                f_path = os.path.join(root, f)
                try:
                    # Traitement spécialisé
                    res = extract_ie_drawing(f_path)
                    items = res.get("items", [])
                    all_extracted_items.extend(items)
                    processed_files.append({"file": f, "items_count": len(items)})
                except Exception as e_f:
                    logger.warning("[BatchMTO] Échec traitement %s: %s", f, e_f)
                    failed_files.append({"file": f, "error": str(e_f)})

    # Validation technique I&E
    ie_anomalies = validate_ie_mto(all_extracted_items)

    # Recoupement croisé inter-disciplines
    piping_items = [it for it in all_extracted_items if it.get("category") in ("PIPE", "VALVE", "FLANGE", "FITTING")]
    sld_feeders = [it for it in all_extracted_items if it.get("category") == "SWITCHGEAR_FEEDER"]
    routing_items = [it for it in all_extracted_items if it.get("category") in ("CABLE_TRAY", "CONDUIT", "PULL_BOX")]
    earthing_items = [it for it in all_extracted_items if it.get("category") == "EARTHING"]

    cross_anomalies = run_cross_discipline_reconciliation(
        piping_items=piping_items,
        sld_feeders=sld_feeders,
        routing_items=routing_items,
        earthing_items=earthing_items
    )

    all_anomalies = ie_anomalies + cross_anomalies

    # Génération du classeur maître 9 onglets
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"MTO_GLOBAL_PROJET_FOLDER_{folder_id}.xlsx"

    generate_master_multidiscipline_excel(
        items=all_extracted_items,
        metadata={"project": folder["name"], "folder_id": folder_id},
        anomalies=all_anomalies,
        output_path=str(report_file)
    )

    return {
        "status": "success",
        "folder_id": folder_id,
        "folder_name": folder["name"],
        "total_files_processed": len(processed_files),
        "total_files_failed": len(failed_files),
        "total_items_extracted": len(all_extracted_items),
        "total_anomalies_detected": len(all_anomalies),
        "master_excel_report": str(report_file),
        "processed_files_sample": processed_files[:15]
    }


# ══════════════════════════════════════════════════════════════════════════════
# ── MODULE DOCUMENT CONTROL (DCC) & REGISTRE TDR ──
# ══════════════════════════════════════════════════════════════════════════════

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

DCC_DISCIPLINE_MAP = {
    "PIPING": {
        "folder": "01_Tuyauterie",
        "subfolders": {
            "PLANS_ISO": "Plans_Isometriques",
            "PLANS_INSTALLATION": "Plans_Installation",
            "SPECS": "Specifications"
        },
        "default_sub": "Plans_Isometriques"
    },
    "PROCESS": {
        "folder": "02_Procede",
        "subfolders": {
            "PID": "PID",
            "PFD": "PFD",
            "CALCULATIONS": "Notes_Calcul"
        },
        "default_sub": "PID"
    },
    "CIVIL": {
        "folder": "03_Genie_Civil",
        "subfolders": {
            "PLANS_COFFRAGE": "Plans_Coffrage_Ferraillage",
            "CALCULATIONS": "Notes_Calcul"
        },
        "default_sub": "Plans_Coffrage_Ferraillage"
    },
    "ELECTRICAL": {
        "folder": "04_Electricite",
        "subfolders": {
            "SCHEMAS": "Schemas_Unifilaires",
            "PLANS_CABLING": "Plans_Cablage"
        },
        "default_sub": "Schemas_Unifilaires"
    },
    "INSTRUMENTATION": {
        "folder": "05_Instrumentation",
        "subfolders": {
            "BOUCLES": "Boucles",
            "DATASHEETS": "Fiches_Techniques"
        },
        "default_sub": "Boucles"
    },
    "MECHANICAL": {
        "folder": "06_Mecanique",
        "subfolders": {
            "PLANS_EQUIPEMENTS": "Plans_Equipements",
            "DATASHEETS": "Datasheets"
        },
        "default_sub": "Plans_Equipements"
    },
    "SAFETY": {
        "folder": "07_Securite_Incendie",
        "subfolders": {
            "RESEAU_INCENDIE": "Reseau_Incendie",
            "PLANS_EVACUATION": "Plans_Evacuation"
        },
        "default_sub": "Reseau_Incendie"
    },
    "GENERAL": {
        "folder": "00_General",
        "subfolders": {
            "TRANSMITTALS": "Transmittals",
            "SPECS": "Specifications",
            "PROCEDURES": "Procedures"
        },
        "default_sub": "Transmittals"
    }
}

DCC_DISCIPLINE_PATTERNS = [
    (r'\b(PIG|PIP|ISO|TUYAUTERIE|TUY)\b', "PIPING"),
    (r'\b(PID|PFD|PROCEDE|PROCESS|PRD)\b', "PROCESS"),
    (r'\b(GCL|CIVIL|CIV|STR|COFFRAGE|FERRAILLAGE)\b', "CIVIL"),
    (r'\b(ELC|ELEC|ELECTRIQUE|SLD|SCH)\b', "ELECTRICAL"),
    (r'\b(INS|INST|INSTRUMENTATION|BOUCLE)\b', "INSTRUMENTATION"),
    (r'\b(MEC|MECH|MECANIQUE|EQUIPEMENT)\b', "MECHANICAL"),
    (r'\b(HSE|SECURITE|INCENDIE|SAFETY)\b', "SAFETY"),
    (r'\b(TEL|TELECOM)\b', "TELECOM"),
    (r'\b(GNL|GEN|GENERAL|MGF|QTE|PCT|COMMUN)\b', "GENERAL"),
]

DCC_TYPE_PATTERNS = [
    (r'\b(IW|ISO|ISOMETRIQUE)\b', "PLANS_ISO"),
    (r'\b(PID)\b', "PID"),
    (r'\b(PFD)\b', "PFD"),
    (r'\b(SLD|UNIFILAIRE)\b', "SCHEMAS"),
    (r'\b(PR|PROC|PROCEDURE)\b', "PROCEDURES"),
    (r'\b(DS|DATASHEET|FICHE)\b', "DATASHEETS"),
    (r'\b(SP|SPEC|SPECIFICATION)\b', "SPECS"),
    (r'\b(CALC|NC|NOTE)\b', "CALCULATIONS"),
    (r'\b(PL|PLAN|COFFRAGE)\b', "PLANS_COFFRAGE"),
    (r'\b(LL|LINE\s*LIST)\b', "LISTS"),
    (r'\b(DWG|DW)\b', "PLANS_INSTALLATION"),
]

def detect_dcc_metadata(file_name: str) -> Dict[str, Any]:
    """Extrait automatiquement l'identité racine, la révision, la discipline et le type d'un document technique."""
    raw_stem = Path(file_name).stem.strip()
    # Remplacer les tirets unicode non standard par le tiret ASCII
    clean_stem = raw_stem.replace("\u2010", "-").replace("\u2013", "-").replace("\u2014", "-")

    # 1. Extraction de la révision
    rev_label = "REV 0"
    rev_order = 0

    rev_m = re.search(r'\b(?:REV|REVISION)[-_\.\s]*([A-Z0-9]+)\b', clean_stem, re.IGNORECASE)
    if rev_m:
        val = rev_m.group(1).upper()
        rev_label = f"REV {val}"
        rev_order = int(val) if val.isdigit() else (ord(val) - ord('A') + 10 if len(val) == 1 else 0)
    else:
        tail_m = re.search(r'[-_](0?(\d+)|([A-Z]))$', clean_stem)
        if tail_m:
            if tail_m.group(2):
                num = int(tail_m.group(2))
                rev_label = f"REV {num}"
                rev_order = num
            elif tail_m.group(3):
                letter = tail_m.group(3).upper()
                rev_label = f"REV {letter}"
                rev_order = ord(letter) - ord('A') + 10

    # 2. Extraction du numéro de document
    tag_m = re.search(r'\b([A-Z0-9]+(?:[-_][A-Z0-9]+){2,})\b', clean_stem, re.IGNORECASE)
    if tag_m:
        doc_number = tag_m.group(1).upper()
        doc_number = re.sub(r'[-_](?:REV[-_]?)?(?:0?(\d+)|([A-Z]))$', '', doc_number, flags=re.IGNORECASE)
    else:
        doc_number = clean_stem.upper()

    # 3. Détection de la discipline
    discipline = "GENERAL"
    for pat, disc in DCC_DISCIPLINE_PATTERNS:
        if re.search(pat, doc_number, re.IGNORECASE) or re.search(pat, clean_stem, re.IGNORECASE):
            discipline = disc
            break

    # 4. Détection du type de document
    doc_type = "GENERAL"
    for pat, dtype in DCC_TYPE_PATTERNS:
        if re.search(pat, doc_number, re.IGNORECASE) or re.search(pat, clean_stem, re.IGNORECASE):
            doc_type = dtype
            break

    if doc_type == "GENERAL":
        disc_cfg = DCC_DISCIPLINE_MAP.get(discipline, DCC_DISCIPLINE_MAP["GENERAL"])
        default_sub = disc_cfg.get("default_sub", "Transmittals")
        doc_type = default_sub.upper()

    # 5. Titre
    title = clean_stem.replace(doc_number, "").strip(" -_.,()")
    if not title:
        title = f"Document {discipline} {doc_number}"

    iec_valid = validate_iec82045_codification(doc_number)
    return {
        "file_name": file_name,
        "doc_number": doc_number,
        "revision": rev_label,
        "revision_order": rev_order,
        "discipline": discipline,
        "doc_type": doc_type,
        "title": title,
        "iec_82045_valid": iec_valid
    }

def resolve_dcc_physical_path(folder_path: Path, discipline: str, doc_type: str) -> Path:
    """Détermine le dossier physique exact et crée l'arborescence sur le disque dur."""
    disc_info = DCC_DISCIPLINE_MAP.get(discipline.upper(), DCC_DISCIPLINE_MAP["GENERAL"])
    disc_folder = disc_info["folder"]
    sub_folder = disc_info["subfolders"].get(doc_type.upper(), disc_info["default_sub"])
    target_dir = folder_path / disc_folder / sub_folder
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir

def archive_previous_revision_physical(target_dir: Path, active_file_name: str, old_rev_label: str) -> Optional[Path]:
    """Déplace l'ancienne version active dans _Historique_Revisions/ avec suffixe explicite."""
    active_path = target_dir / active_file_name
    if not active_path.exists():
        return None
    archive_dir = target_dir / "_Historique_Revisions"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stem = active_path.stem
    ext = active_path.suffix
    clean_rev = old_rev_label.replace(" ", "_").upper()
    archived_name = f"{stem}_{clean_rev}{ext}"
    archived_path = archive_dir / archived_name
    try:
        shutil.move(str(active_path), str(archived_path))
        logger.info("[DCC Archive] Déplacement révision passée vers : %s", archived_path)
        return archived_path
    except Exception as e:
        logger.error("[DCC Archive] Erreur archivage : %s", e)
        return None


# ── Endpoints FastAPI DCC ──

TEMP_DCC_UPLOAD_DIR = Path(r"D:/DATA BASE IA/arh_uploads/dcc_temp")
TEMP_DCC_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@router.post("/dcc/preview-upload")
async def preview_dcc_upload(
    folder_id: int = Form(...),
    files: List[UploadFile] = File(...)
):
    """
    Étape 1 Ingestion DCC : Analyse les fichiers déposés, extrait les métadonnées
    et vérifie les conflits de révision avec les documents déjà présents dans le TDR.
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    items = []
    now_ts = int(datetime.now().timestamp() * 1000)

    for idx, f in enumerate(files):
        # Sauvegarde temporaire
        safe_name = f.filename.replace(" ", "_")
        temp_token = f"dcc_{now_ts}_{idx}_{safe_name}"
        temp_path = TEMP_DCC_UPLOAD_DIR / temp_token
        with open(temp_path, "wb") as out_fp:
            shutil.copyfileobj(f.file, out_fp)

        meta = detect_dcc_metadata(f.filename)
        doc_num = meta["doc_number"]
        rev_lbl = meta["revision"]

        # Vérifier si le document existe déjà dans le projet
        cursor.execute("""
            SELECT id, current_revision, revision_count, active_file_name, discipline, doc_type, title
            FROM tdr_documents
            WHERE folder_id = ? AND doc_number = ?
        """, (folder_id, doc_num))
        row = cursor.fetchone()

        if row:
            doc_id, curr_rev, rev_cnt, act_file, ex_disc, ex_type, ex_title = row
            is_existing = True
            current_active_rev = curr_rev
            status_alert = f"Mise à jour : Remplacement de {curr_rev} par {rev_lbl} (Archivage automatique)"
            title_to_use = ex_title or meta["title"]
            disc_to_use = ex_disc or meta["discipline"]
            type_to_use = ex_type or meta["doc_type"]
        else:
            is_existing = False
            current_active_rev = None
            status_alert = "Nouveau document"
            title_to_use = meta["title"]
            disc_to_use = meta["discipline"]
            type_to_use = meta["doc_type"]

        items.append({
            "temp_token": temp_token,
            "temp_file_path": str(temp_path),
            "original_name": f.filename,
            "doc_number": doc_num,
            "title": title_to_use,
            "discipline": disc_to_use,
            "doc_type": type_to_use,
            "revision": rev_lbl,
            "revision_order": meta["revision_order"],
            "is_existing": is_existing,
            "current_active_rev": current_active_rev,
            "status_alert": status_alert,
            "iec_82045_valid": meta.get("iec_82045_valid", True)
        })

    conn.close()
    return {"status": "success", "folder_id": folder_id, "total_files": len(items), "items": items}


@router.post("/dcc/commit-ingestion")
async def commit_dcc_ingestion(
    folder_id: int = Form(...),
    manifest_json: str = Form(...)
):
    """
    Étape 2 Ingestion DCC : Applique le classement physique sur le disque sous Projet / Discipline / Type_Doc/,
    archive les révisions antérieures dans _Historique_Revisions/ et persiste dans tdr_documents & tdr_revisions.
    """
    try:
        manifest = json.loads(manifest_json)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON manifest invalide : {e}")

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    cursor.execute("SELECT name, folder_path FROM folders WHERE id = ?", (folder_id,))
    f_row = cursor.fetchone()
    if not f_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Projet/dossier introuvable.")

    proj_name, proj_folder_str = f_row
    proj_folder_path = Path(proj_folder_str).resolve()
    proj_folder_path.mkdir(parents=True, exist_ok=True)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ingested_count = 0
    archived_count = 0
    results = []

    for item in manifest:
        temp_token = item.get("temp_token")
        temp_file_path = Path(item.get("temp_file_path") or (TEMP_DCC_UPLOAD_DIR / temp_token))
        if not temp_file_path.exists():
            continue

        doc_num = str(item.get("doc_number", "")).strip().upper()
        title = str(item.get("title", "")).strip()
        discipline = str(item.get("discipline", "GENERAL")).strip().upper()
        doc_type = str(item.get("doc_type", "GENERAL")).strip().upper()
        revision = str(item.get("revision", "REV 0")).strip().upper()
        rev_order = int(item.get("revision_order", 0))

        # Résolution du dossier physique de destination
        target_dir = resolve_dcc_physical_path(proj_folder_path, discipline, doc_type)

        ext = temp_file_path.suffix.lower()
        active_file_name = f"{doc_num}{ext}"
        final_dest_path = target_dir / active_file_name

        # Vérifier si le document existe déjà en DB
        cursor.execute("""
            SELECT id, current_revision, revision_count, active_file_path, active_file_name
            FROM tdr_documents
            WHERE folder_id = ? AND doc_number = ?
        """, (folder_id, doc_num))
        existing_doc = cursor.fetchone()

        if existing_doc:
            doc_id, old_rev, rev_count, old_path_str, old_file_name = existing_doc

            # 1. Archiver physiquement l'ancienne version active
            archive_res = archive_previous_revision_physical(target_dir, old_file_name, old_rev)
            if archive_res:
                archived_count += 1
                archived_path_str = str(archive_res)
                # Mettre à jour l'ancienne révision en inactive dans la DB
                cursor.execute("""
                    UPDATE tdr_revisions
                    SET is_active = 0, file_path = ?
                    WHERE tdr_doc_id = ? AND is_active = 1
                """, (archived_path_str, doc_id))
            else:
                cursor.execute("""
                    UPDATE tdr_revisions
                    SET is_active = 0
                    WHERE tdr_doc_id = ? AND is_active = 1
                """, (doc_id,))

            # 2. Copier le nouveau fichier actif
            shutil.copy2(str(temp_file_path), str(final_dest_path))

            # 3. Mettre à jour tdr_documents
            new_rev_count = rev_count + 1
            iec_valid = 1 if validate_iec82045_codification(doc_num) else 0
            cursor.execute("""
                UPDATE tdr_documents
                SET title = ?, discipline = ?, doc_type = ?, current_revision = ?,
                    revision_count = ?, active_file_path = ?, active_file_name = ?,
                    status_stage = 'INGESTED', iec_82045_valid = ?, updated_at = ?
                WHERE id = ?
            """, (title, discipline, doc_type, revision, new_rev_count, str(final_dest_path), active_file_name, iec_valid, now_str, doc_id))

            # 4. Insérer la nouvelle révision
            cursor.execute("""
                INSERT INTO tdr_revisions (
                    tdr_doc_id, folder_id, revision_label, revision_order,
                    file_name, file_path, is_active, uploaded_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """, (doc_id, folder_id, revision, rev_order, active_file_name, str(final_dest_path), now_str))

        else:
            # Nouveau document
            shutil.copy2(str(temp_file_path), str(final_dest_path))

            iec_valid = 1 if validate_iec82045_codification(doc_num) else 0
            cursor.execute("""
                INSERT INTO tdr_documents (
                    folder_id, doc_number, title, discipline, doc_type,
                    current_revision, revision_count, status_stage,
                    active_file_path, active_file_name, iec_82045_valid, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 'INGESTED', ?, ?, ?, ?, ?)
            """, (folder_id, doc_num, title, discipline, doc_type, revision, str(final_dest_path), active_file_name, iec_valid, now_str, now_str))
            new_doc_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO tdr_revisions (
                    tdr_doc_id, folder_id, revision_label, revision_order,
                    file_name, file_path, is_active, uploaded_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """, (new_doc_id, folder_id, revision, rev_order, active_file_name, str(final_dest_path), now_str))

        # Indexer dans FTS5
        try:
            cursor.execute("""
                INSERT INTO indexed_files_fts (file_name, drawing_root_no, revision_label, file_path, doc_type, folder_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (active_file_name, doc_num, revision, str(final_dest_path), doc_type, folder_id))
        except Exception:
            pass

        # Nettoyage fichier temporaire
        try:
            temp_file_path.unlink(missing_ok=True)
        except Exception:
            pass

        ingested_count += 1
        results.append({
            "doc_number": doc_num,
            "revision": revision,
            "active_path": str(final_dest_path)
        })

    # Mettre à jour le compteur de fichiers du dossier projet
    cursor.execute("SELECT COUNT(*) FROM tdr_documents WHERE folder_id = ?", (folder_id,))
    total_docs = cursor.fetchone()[0]
    cursor.execute("UPDATE folders SET file_count = ?, is_indexed = 1, last_indexed_at = ? WHERE id = ?", (total_docs, now_str, folder_id))

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "ingested_count": ingested_count,
        "archived_count": archived_count,
        "total_documents": total_docs,
        "items": results
    }


@router.get("/tdr/list/{folder_id}")
async def get_tdr_list(
    folder_id: int,
    discipline: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None
):
    """
    Récupère le registre complet TDR d'un projet avec calcul en temps réel des KPIs EPC :
    Total Documents, En attente retour client (>21j), Code 1, Code 2, Code 3, Révisions multiples.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT d.*,
               (SELECT COUNT(*) FROM tdr_revisions r WHERE r.tdr_doc_id = d.id) as total_revs
        FROM tdr_documents d
        WHERE d.folder_id = ?
    """
    params = [folder_id]

    if discipline and discipline.upper() != "ALL":
        query += " AND d.discipline = ?"
        params.append(discipline.upper())

    if status and status.upper() != "ALL":
        query += " AND (d.status_stage = ? OR d.client_approval_code = ?)"
        params.append(status.upper())
        params.append(status.upper())

    if search and search.strip():
        term = f"%{search.strip().upper()}%"
        query += " AND (UPPER(d.doc_number) LIKE ? OR UPPER(d.title) LIKE ? OR UPPER(d.last_transmittal_no) LIKE ?)"
        params.extend([term, term, term])

    query += " ORDER BY d.discipline ASC, d.doc_number ASC"
    cursor.execute(query, params)
    rows = cursor.fetchall()

    # Calcul KPIs
    cursor.execute("SELECT * FROM tdr_documents WHERE folder_id = ?", (folder_id,))
    all_docs = cursor.fetchall()

    now = datetime.now()
    kpis = {
        "total_documents": len(all_docs),
        "pending_review": 0,
        "code_1_count": 0,
        "code_2_count": 0,
        "code_3_count": 0,
        "code_4_count": 0,
        "multi_revisions_count": 0,
        "sla_exceeded_21d": 0,
        "compliant_iec_count": 0,
        "non_compliant_iec_count": 0
    }

    docs_out = []
    for r in rows:
        d = dict(r)
        # Récupérer l'historique complet des révisions du document
        cursor.execute("""
            SELECT id, revision_label, revision_order, file_name, file_path, is_active,
                   transmittal_no, sent_date, return_date, client_code, uploaded_at
            FROM tdr_revisions
            WHERE tdr_doc_id = ?
            ORDER BY revision_order DESC, id DESC
        """, (d["id"],))
        d["revisions"] = [dict(rev) for rev in cursor.fetchall()]

        # Calcul SLA pour chaque document
        sent_date_str = d.get("last_sent_date")
        ret_date_str = d.get("last_return_date")
        d["sla_days_elapsed"] = None
        d["sla_overdue_days"] = 0
        d["is_exceeded_21d"] = False

        if sent_date_str:
            try:
                sent_dt = datetime.strptime(sent_date_str[:10], "%Y-%m-%d")
                if ret_date_str:
                    ret_dt = datetime.strptime(ret_date_str[:10], "%Y-%m-%d")
                    elapsed = (ret_dt - sent_dt).days
                else:
                    elapsed = (now - sent_dt).days
                    if elapsed > 21:
                        d["is_exceeded_21d"] = True
                        d["sla_overdue_days"] = elapsed - 21

                d["sla_days_elapsed"] = elapsed
            except Exception:
                pass

        docs_out.append(d)

    # Calcul des compteurs KPI globaux
    for d in all_docs:
        c_code = (d["client_approval_code"] or "").upper()
        if c_code == "CODE_1": kpis["code_1_count"] += 1
        elif c_code == "CODE_2": kpis["code_2_count"] += 1
        elif c_code == "CODE_3": kpis["code_3_count"] += 1
        elif c_code == "CODE_4": kpis["code_4_count"] += 1

        is_iec = d["iec_82045_valid"] if "iec_82045_valid" in d.keys() and d["iec_82045_valid"] is not None else 1
        if is_iec == 0:
            kpis["non_compliant_iec_count"] += 1
        else:
            kpis["compliant_iec_count"] += 1

        if d["revision_count"] > 1:
            kpis["multi_revisions_count"] += 1

        if d["last_sent_date"] and not d["last_return_date"]:
            kpis["pending_review"] += 1
            try:
                s_dt = datetime.strptime(d["last_sent_date"][:10], "%Y-%m-%d")
                if (now - s_dt).days > 21:
                    kpis["sla_exceeded_21d"] += 1
            except Exception:
                pass

    conn.close()
    return {
        "status": "success",
        "folder_id": folder_id,
        "kpis": kpis,
        "documents": docs_out
    }


@router.post("/tdr/update-entry")
async def update_tdr_entry(
    doc_id: int = Form(...),
    title: Optional[str] = Form(None),
    discipline: Optional[str] = Form(None),
    doc_type: Optional[str] = Form(None)
):
    """Met à jour les métadonnées de titre, discipline ou type d'un livrable TDR."""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    updates = []
    params = []
    if title is not None:
        updates.append("title = ?")
        params.append(title.strip())
    if discipline is not None:
        updates.append("discipline = ?")
        params.append(discipline.strip().upper())
    if doc_type is not None:
        updates.append("doc_type = ?")
        params.append(doc_type.strip().upper())

    if not updates:
        conn.close()
        return {"status": "unchanged"}

    updates.append("updated_at = ?")
    params.append(now_str)
    params.append(doc_id)

    query = f"UPDATE tdr_documents SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(query, params)
    conn.commit()
    conn.close()
    return {"status": "success", "doc_id": doc_id}


@router.post("/tdr/create-transmittal")
async def create_transmittal(
    folder_id: int = Form(...),
    transmittal_no: str = Form(...),
    direction: str = Form("OUTGOING"),
    recipient: str = Form("SONATRACH / CLIENT"),
    purpose: str = Form("IFR"),
    doc_ids_json: str = Form(...),
    remarks: str = Form("")
):
    """
    Crée un bordereau de transmission sortant (Transmittal OUTGOING), y associe les documents
    sélectionnés et bascule leur statut en 'SENT_FOR_REVIEW'.
    """
    try:
        doc_ids = json.loads(doc_ids_json)
        if not isinstance(doc_ids, list) or not doc_ids:
            raise ValueError("La liste de documents est vide.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"doc_ids_json invalide : {e}")

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_date = datetime.now().strftime("%Y-%m-%d")
    clean_tn = transmittal_no.strip().upper()

    # 1. Création de l'enregistrement de bordereau
    try:
        cursor.execute("""
            INSERT INTO tdr_transmittals (
                folder_id, transmittal_no, direction, transmittal_date,
                recipient, sender, purpose, total_documents, remarks, created_at
            ) VALUES (?, ?, ?, ?, ?, 'DOCUMENT CONTROLLER', ?, ?, ?, ?)
        """, (folder_id, clean_tn, direction.upper(), today_date, recipient.strip(), purpose.strip().upper(), len(doc_ids), remarks.strip(), now_str))
        transmittal_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Le numéro de bordereau '{clean_tn}' existe déjà.")

    # 2. Association des items et mise à jour des documents
    for doc_id in doc_ids:
        cursor.execute("SELECT doc_number, current_revision FROM tdr_documents WHERE id = ?", (doc_id,))
        d_row = cursor.fetchone()
        if not d_row:
            continue
        doc_num, curr_rev = d_row

        cursor.execute("""
            INSERT INTO tdr_transmittal_items (transmittal_id, tdr_doc_id, doc_number, revision_label, comments)
            VALUES (?, ?, ?, ?, ?)
        """, (transmittal_id, doc_id, doc_num, curr_rev, remarks.strip()))

        # Mettre à jour tdr_documents
        cursor.execute("""
            UPDATE tdr_documents
            SET last_transmittal_no = ?, last_sent_date = ?, last_sent_purpose = ?,
                status_stage = 'SENT_FOR_REVIEW', updated_at = ?
            WHERE id = ?
        """, (clean_tn, today_date, purpose.strip().upper(), now_str, doc_id))

        # Mettre à jour la révision active
        cursor.execute("""
            UPDATE tdr_revisions
            SET transmittal_no = ?, sent_date = ?, sent_purpose = ?
            WHERE tdr_doc_id = ? AND is_active = 1
        """, (clean_tn, today_date, purpose.strip().upper(), doc_id))

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "transmittal_id": transmittal_id,
        "transmittal_no": clean_tn,
        "total_documents": len(doc_ids),
        "transmittal_date": today_date
    }


@router.post("/tdr/record-return")
async def record_client_return(
    folder_id: int = Form(...),
    return_transmittal_no: str = Form(...),
    return_date: str = Form(...),
    client_code: str = Form(...),
    doc_ids_json: str = Form(...),
    comments: str = Form("")
):
    """
    Enregistre le retour et le visa client (FCD / Bordereau de retour entrant) avec le code
    d'approbation (Code 1 Approuvé, Code 2 Approuvé avec com, Code 3 Rejeté, Code 4 Info).
    """
    try:
        doc_ids = json.loads(doc_ids_json)
        if not isinstance(doc_ids, list) or not doc_ids:
            raise ValueError("La liste de documents est vide.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"doc_ids_json invalide : {e}")

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_fcd = return_transmittal_no.strip().upper()
    clean_code = client_code.strip().upper()

    # Déterminer le statut stage
    if clean_code == "CODE_1":
        stage = "APPROVED"
    elif clean_code == "CODE_2":
        stage = "APPROVED_WITH_COMMENTS"
    elif clean_code == "CODE_3":
        stage = "REJECTED"
    else:
        stage = "FOR_INFO"

    # Enregistrer le transmittal de réception INCOMING
    cursor.execute("""
        INSERT OR IGNORE INTO tdr_transmittals (
            folder_id, transmittal_no, direction, transmittal_date,
            recipient, sender, purpose, total_documents, remarks, created_at
        ) VALUES (?, ?, 'INCOMING', ?, 'DOCUMENT CONTROLLER', 'SONATRACH / CLIENT', 'RETURN', ?, ?, ?)
    """, (folder_id, clean_fcd, return_date.strip(), len(doc_ids), comments.strip(), now_str))

    cursor.execute("SELECT id FROM tdr_transmittals WHERE transmittal_no = ?", (clean_fcd,))
    t_row = cursor.fetchone()
    transmittal_id = t_row[0] if t_row else None

    for doc_id in doc_ids:
        cursor.execute("SELECT doc_number, current_revision FROM tdr_documents WHERE id = ?", (doc_id,))
        d_row = cursor.fetchone()
        if not d_row:
            continue
        doc_num, curr_rev = d_row

        if transmittal_id:
            cursor.execute("""
                INSERT INTO tdr_transmittal_items (transmittal_id, tdr_doc_id, doc_number, revision_label, client_code, comments)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (transmittal_id, doc_id, doc_num, curr_rev, clean_code, comments.strip()))

        # Mettre à jour tdr_documents
        cursor.execute("""
            UPDATE tdr_documents
            SET last_return_date = ?, last_return_transmittal = ?, client_approval_code = ?,
                status_stage = ?, updated_at = ?
            WHERE id = ?
        """, (return_date.strip(), clean_fcd, clean_code, stage, now_str, doc_id))

        # Mettre à jour la révision active
        cursor.execute("""
            UPDATE tdr_revisions
            SET return_date = ?, client_code = ?
            WHERE tdr_doc_id = ? AND is_active = 1
        """, (return_date.strip(), clean_code, doc_id))

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "return_transmittal": clean_fcd,
        "client_code": clean_code,
        "status_stage": stage,
        "updated_documents": len(doc_ids)
    }


@router.get("/tdr/transmittals/{folder_id}")
async def list_transmittals(folder_id: int):
    """Renvoie l'historique chronologique des bordereaux d'envoi et de retour d'un projet."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT t.*,
               (SELECT COUNT(*) FROM tdr_transmittal_items ti WHERE ti.transmittal_id = t.id) as item_count
        FROM tdr_transmittals t
        WHERE t.folder_id = ?
        ORDER BY t.transmittal_date DESC, t.id DESC
    """, (folder_id,))
    rows = cursor.fetchall()
    conn.close()
    return {"status": "success", "transmittals": [dict(r) for r in rows]}



@router.get("/tdr/next-transmittal-number/{folder_id}")
def get_next_transmittal_number(
    folder_id: int,
    prefix: str = Query("TR", description="Préfixe du bordereau (ex: TR, TRANS)"),
    purpose: str = Query("IFR", description="Motif contractuel (IFR, IFA, IFC, ASB)")
):
    """
    Génère automatiquement le prochain numéro de bordereau d'envoi officiel selon la norme EPC :
    Format : [PREFIX]-[PROJET]-[ANNEE]-[SEQ:04d]
    Exemple : TR-CPF-2026-0001
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM folders WHERE id = ?", (folder_id,))
    f_row = cursor.fetchone()
    folder_name = f_row[0] if f_row else "PRJ"

    clean_prj = re.sub(r'[^A-Z0-9]', '', folder_name.upper())[:6] or "PRJ"
    current_year = datetime.now().year
    pref_str = getattr(prefix, 'default', prefix) or 'TR'
    p_str = getattr(purpose, 'default', purpose) or 'IFR'
    pattern_base = f"{str(pref_str).strip().upper()}-{clean_prj}-{current_year}-"

    cursor.execute("""
        SELECT transmittal_no FROM tdr_transmittals
        WHERE folder_id = ? AND transmittal_no LIKE ?
        ORDER BY id DESC LIMIT 1
    """, (folder_id, f"{pattern_base}%"))
    last_row = cursor.fetchone()

    next_seq = 1
    if last_row and last_row[0]:
        match = re.search(r'(\d+)$', last_row[0])
        if match:
            next_seq = int(match.group(1)) + 1

    next_no = f"{pattern_base}{next_seq:04d}"
    conn.close()

    return {
        "status": "success",
        "folder_id": folder_id,
        "project_code": clean_prj,
        "next_transmittal_no": next_no,
        "suggested_purpose": str(p_str).upper()
    }


@router.post("/tdr/audit-compliance/{folder_id}")
async def audit_tdr_compliance(folder_id: int):
    """
    Exécute l'audit de conformité documentaire DOT-09 (ISO 15489 & IEC 82045)
    sur l'ensemble des documents d'un projet.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tdr_documents WHERE folder_id = ?", (folder_id,))
    docs = cursor.fetchall()

    audited_docs = []
    compliant_count = 0
    non_compliant_count = 0

    for d in docs:
        doc_num = d["doc_number"]
        is_valid = validate_iec82045_codification(doc_num)
        cursor.execute("""
            UPDATE tdr_documents SET iec_82045_valid = ? WHERE id = ?
        """, (1 if is_valid else 0, d["id"]))

        if is_valid:
            compliant_count += 1
        else:
            non_compliant_count += 1

        audited_docs.append({
            "doc_id": d["id"],
            "doc_number": doc_num,
            "discipline": d["discipline"],
            "revision": d["current_revision"],
            "iec_82045_valid": is_valid,
            "recommendation": "Conforme IEC 82045-1" if is_valid else "Nomenclature non standard (attendu: [PROJET]-[DISC]-[TYPE]-[NUMÉRO])"
        })

    conn.commit()
    conn.close()

    compliance_rate = round((compliant_count / len(docs) * 100), 1) if docs else 100.0

    return {
        "status": "success",
        "folder_id": folder_id,
        "total_documents": len(docs),
        "compliant_count": compliant_count,
        "non_compliant_count": non_compliant_count,
        "compliance_rate_percent": compliance_rate,
        "norm": "IEC 82045-1 / ISO 15489",
        "items": audited_docs
    }


@router.get("/tdr/export-excel/{folder_id}")
async def export_tdr_excel(folder_id: int):
    """
    Génère et télécharge le registre TDR complet au format Excel (.xlsx) aux standards
    officiels Sonatrach / EPC Oil & Gas avec mise en forme automatique et indicateurs.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT name, code FROM folders WHERE id = ?", (folder_id,))
    f_row = cursor.fetchone()
    if not f_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Projet introuvable.")

    proj_name = f_row["name"]

    cursor.execute("""
        SELECT * FROM tdr_documents
        WHERE folder_id = ?
        ORDER BY discipline ASC, doc_number ASC
    """, (folder_id,))
    docs = cursor.fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TDR REGISTER"

    # Styles
    navy_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Calibri", size=14, bold=True, color="1E3A8A")
    border_thin = Side(border_style="thin", color="CBD5E1")
    cell_border = Border(left=border_thin, right=border_thin, top=border_thin, bottom=border_thin)

    # Titre du classeur
    ws["A1"] = f"REGISTRE DE TRANSMISSION DOCUMENTAIRE (TDR) — {proj_name.upper()}"
    ws["A1"].font = title_font
    ws["A2"] = f"Date d'export : {datetime.now().strftime('%Y-%m-%d %H:%M')} | Total Livrables : {len(docs)}"
    ws["A2"].font = Font(name="Calibri", size=10, italic=True, color="64748B")

    headers = [
        "S.NO", "N° Document", "Titre du Document", "Discipline", "Type",
        "Rév. Active", "Nb Révs", "Dernier Bordereau Envoi", "Date Envoi", "But Envoi",
        "Date Retour Client", "N° Bordereau Client (FCD)", "Code Approbation", "Statut", "Fichier Actif"
    ]

    ws.append([]) # Row 3
    ws.append(headers) # Row 4

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=4, column=col_idx)
        cell.fill = navy_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for idx, d in enumerate(docs, 1):
        c_code = d["client_approval_code"] or ""
        row_vals = [
            idx,
            d["doc_number"],
            d["title"],
            d["discipline"],
            d["doc_type"],
            d["current_revision"],
            d["revision_count"],
            d["last_transmittal_no"] or "-",
            d["last_sent_date"] or "-",
            d["last_sent_purpose"] or "-",
            d["last_return_date"] or "-",
            d["last_return_transmittal"] or "-",
            c_code or "EN ATTENTE",
            d["status_stage"],
            d["active_file_name"]
        ]
        ws.append(row_vals)

        r_num = 4 + idx
        for c_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=r_num, column=c_idx)
            cell.border = cell_border
            cell.font = Font(name="Calibri", size=10)

            # Mise en valeur des codes d'approbation
            if c_idx == 13:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                if c_code == "CODE_1":
                    cell.fill = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")
                    cell.font = Font(name="Calibri", size=10, bold=True, color="065F46")
                elif c_code == "CODE_2":
                    cell.fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
                    cell.font = Font(name="Calibri", size=10, bold=True, color="92400E")
                elif c_code == "CODE_3":
                    cell.fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
                    cell.font = Font(name="Calibri", size=10, bold=True, color="991B1B")

    # Ajustement largeur automatique
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    # Onglet Synthèse KPIs
    ws_kpi = wb.create_sheet(title="SYNTHESE DCC")
    ws_kpi["A1"] = f"SYNTHÈSE QUALITÉ DOCUMENTAIRE & APPROBATIONS — {proj_name.upper()}"
    ws_kpi["A1"].font = title_font

    ws_kpi.append([])
    ws_kpi.append(["Discipline", "Total Documents", "Approuvé (Code 1)", "Approuvé avec Com. (Code 2)", "Rejeté (Code 3)", "En Attente"])
    for c in range(1, 7):
        cell = ws_kpi.cell(row=3, column=c)
        cell.fill = navy_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    cursor.execute("""
        SELECT discipline,
               COUNT(*) as total,
               SUM(CASE WHEN client_approval_code = 'CODE_1' THEN 1 ELSE 0 END) as c1,
               SUM(CASE WHEN client_approval_code = 'CODE_2' THEN 1 ELSE 0 END) as c2,
               SUM(CASE WHEN client_approval_code = 'CODE_3' THEN 1 ELSE 0 END) as c3,
               SUM(CASE WHEN client_approval_code IS NULL OR client_approval_code = '' THEN 1 ELSE 0 END) as pending
        FROM tdr_documents
        WHERE folder_id = ?
        GROUP BY discipline
        ORDER BY discipline ASC
    """, (folder_id,))
    kpi_rows = cursor.fetchall()
    for kr in kpi_rows:
        ws_kpi.append([kr["discipline"], kr["total"], kr["c1"], kr["c2"], kr["c3"], kr["pending"]])

    for col in ws_kpi.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_kpi.column_dimensions[col_letter].width = max(max_len + 3, 14)

    conn.close()

    reports_dir = Path(r"D:/DATA BASE IA/arh_reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_file = reports_dir / f"TDR_REGISTER_{folder_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    wb.save(out_file)

    return FileResponse(
        path=str(out_file),
        filename=f"TDR_{proj_name.replace(' ', '_')}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.get("/tdr/transmittal-sheet/{transmittal_id}")
async def get_transmittal_sheet(transmittal_id: int):
    """
    Génère la fiche officielle de bordereau de transmission (Transmittal Form) prête à l'impression
    avec cartouche, tableau des pièces jointes et blocs de signature.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tdr_transmittals WHERE id = ?", (transmittal_id,))
    t_row = cursor.fetchone()
    if not t_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Bordereau introuvable.")

    cursor.execute("""
        SELECT ti.*, d.title as doc_title, d.discipline, d.doc_type, d.active_file_name
        FROM tdr_transmittal_items ti
        LEFT JOIN tdr_documents d ON ti.tdr_doc_id = d.id
        WHERE ti.transmittal_id = ?
        ORDER BY ti.id ASC
    """, (transmittal_id,))
    items = cursor.fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TRANSMITTAL"

    navy_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    border_thin = Side(border_style="thin", color="CBD5E1")
    cell_border = Border(left=border_thin, right=border_thin, top=border_thin, bottom=border_thin)

    # Cartouche officiel de bordereau
    ws["B2"] = "BORDEREAU D'ENVOI DE DOCUMENTS TECHNIQUES / TRANSMITTAL SHEET"
    ws["B2"].font = Font(name="Calibri", size=14, bold=True, color="1E3A8A")

    ws["B4"] = "N° Bordereau :"
    ws["C4"] = t_row["transmittal_no"]
    ws["C4"].font = Font(name="Calibri", size=11, bold=True)

    ws["E4"] = "Date d'émission :"
    ws["F4"] = t_row["transmittal_date"]

    ws["B5"] = "Émetteur :"
    ws["C5"] = t_row["sender"]

    ws["E5"] = "Destinataire :"
    ws["F5"] = t_row["recipient"]

    ws["B6"] = "But de l'envoi :"
    ws["C6"] = t_row["purpose"]

    ws["E6"] = "Direction :"
    ws["F6"] = t_row["direction"]

    headers = ["Item", "Numéro de Document", "Rév.", "Titre du Document", "Discipline", "Statut / Code", "Observations"]
    ws.append([]) # Row 7
    ws.append([]) # Row 8

    # Row 9: Headers
    start_row = 9
    for idx, h in enumerate(headers, 1):
        cell = ws.cell(row=start_row, column=idx)
        cell.value = h
        cell.fill = navy_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for idx, it in enumerate(items, 1):
        r_num = start_row + idx
        row_vals = [
            idx,
            it["doc_number"],
            it["revision_label"],
            it["doc_title"] or "-",
            it["discipline"] or "-",
            it["client_code"] or t_row["purpose"],
            it["comments"] or "-"
        ]
        for c_idx, val in enumerate(row_vals, 1):
            cell = ws.cell(row=r_num, column=c_idx)
            cell.value = val
            cell.border = cell_border
            cell.font = Font(name="Calibri", size=10)

    # Bloc signatures
    sig_row = start_row + len(items) + 3
    ws.cell(row=sig_row, column=2, value="Émis par (Document Controller) :").font = Font(name="Calibri", bold=True)
    ws.cell(row=sig_row, column=5, value="Accusé de réception Client :").font = Font(name="Calibri", bold=True)

    ws.cell(row=sig_row + 1, column=2, value="Nom & Signature : .........................................")
    ws.cell(row=sig_row + 1, column=5, value="Visé / Tamponné le : .....................................")

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    conn.close()

    reports_dir = Path(r"D:/DATA BASE IA/arh_reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_file = reports_dir / f"TRANSMITTAL_{t_row['transmittal_no']}.xlsx"
    wb.save(out_file)

    return FileResponse(
        path=str(out_file),
        filename=f"TRANSMITTAL_{t_row['transmittal_no']}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )



# ══════════════════════════════════════════════════════════════════════════════
# ── ENDPOINTS DCC ENRICHIS : SETUP PROJET MDR, CYCLES DE VIE, SLA & DASHBOARD ──
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/tdr/lifecycles/templates")
async def get_lifecycle_templates():
    """Retourne la bibliothèque complète des cycles de vie EPC (10 standards + personnalisés)."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tdr_lifecycle_templates ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        try:
            d["associated_types"] = json.loads(d["associated_types_json"] or "[]")
        except Exception:
            d["associated_types"] = []
        try:
            d["steps"] = json.loads(d["steps_json"] or "[]")
        except Exception:
            d["steps"] = []
        result.append(d)

    return {"status": "success", "templates": result}


@router.post("/tdr/project-init/upload-mdr")
async def upload_mdr_file(file: UploadFile = File(...)):
    """
    Étape 1 du Wizard : Parse le fichier Excel de la liste de livrables (MDR),
    reconnaît les 10 colonnes obligatoires et suggère les cycles de vie par type de document.
    """
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Format invalide. Fichier Excel (.xlsx ou .xls) requis.")

    import tempfile
    import openpyxl

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        wb = openpyxl.load_workbook(str(tmp_path), data_only=True)
        sheet = wb.active

        # Recherche de la ligne d'en-tête (première ligne avec >= 3 colonnes renseignées)
        header_row_idx = None
        headers = {}
        for r_idx, row in enumerate(sheet.iter_rows(values_only=True), 1):
            row_vals = [str(v or "").strip().lower() for v in row]
            if len([v for v in row_vals if v]) >= 3:
                header_row_idx = r_idx
                for c_idx, val in enumerate(row_vals):
                    headers[val] = c_idx
                break

        if header_row_idx is None:
            raise HTTPException(status_code=400, detail="Impossible d'identifier la ligne d'en-tête du fichier Excel.")

        # Mapping flexible des colonnes
        def find_col_idx(candidates: List[str]) -> Optional[int]:
            for cand in candidates:
                for h_text, idx in headers.items():
                    if cand in h_text:
                        return idx
            return None

        idx_doc_no = find_col_idx(["doc_number", "n°", "numero", "numéro", "document", "tag", "code"])
        idx_title = find_col_idx(["titre", "title", "designation", "description", "nom"])
        idx_disc = find_col_idx(["discipline", "disc", "secteur"])
        idx_type = find_col_idx(["type", "doc_type", "typologie", "nature"])
        idx_rev = find_col_idx(["revision", "révision", "rev", "indice"])
        idx_date = find_col_idx(["date", "date_prevue", "date prévue", "deadline", "livraison", "target"])
        idx_priority = find_col_idx(["priorite", "priorité", "priority"])
        idx_format = find_col_idx(["format", "extension"])
        idx_author = find_col_idx(["responsable", "auteur", "author", "lead", "ingenieur", "ingénieur"])
        idx_weight = find_col_idx(["poids", "weight", "pondération", "%"])

        if idx_doc_no is None:
            raise HTTPException(status_code=400, detail="Colonne obligatoire 'N° Document' introuvable dans le fichier Excel.")

        items = []
        disc_summary = {}
        type_summary = {}

        for row in sheet.iter_rows(min_row=header_row_idx + 1, values_only=True):
            if not row or not any(row):
                continue
            doc_no = str(row[idx_doc_no] or "").strip()
            if not doc_no or doc_no.lower() in ["none", "total", "nb"]:
                continue

            title = str(row[idx_title] or "").strip() if idx_title is not None and idx_title < len(row) else ""
            disc = str(row[idx_disc] or "GENERAL").strip().upper() if idx_disc is not None and idx_disc < len(row) else "GENERAL"
            doc_type = str(row[idx_type] or "PLAN").strip().upper() if idx_type is not None and idx_type < len(row) else "PLAN"
            initial_rev = str(row[idx_rev] or "A").strip().upper() if idx_rev is not None and idx_rev < len(row) else "A"
            planned_date = str(row[idx_date] or "")[:10] if idx_date is not None and idx_date < len(row) else ""
            priority = str(row[idx_priority] or "MEDIUM").strip().upper() if idx_priority is not None and idx_priority < len(row) else "MEDIUM"
            fmt = str(row[idx_format] or "PDF").strip().upper() if idx_format is not None and idx_format < len(row) else "PDF"
            author = str(row[idx_author] or "").strip() if idx_author is not None and idx_author < len(row) else ""
            
            weight = 1.0
            if idx_weight is not None and idx_weight < len(row) and row[idx_weight] is not None:
                try:
                    weight = float(row[idx_weight])
                except Exception:
                    weight = 1.0

            # Auto-mapping cycle de vie
            suggested_lc = resolve_lifecycle_for_doc_type(doc_type)

            disc_summary[disc] = disc_summary.get(disc, 0) + 1
            type_summary[doc_type] = type_summary.get(doc_type, 0) + 1

            items.append({
                "doc_number": doc_no,
                "title": title,
                "discipline": disc,
                "doc_type": doc_type,
                "initial_revision": initial_rev,
                "planned_delivery_date": planned_date,
                "priority": priority,
                "expected_format": fmt,
                "assigned_author": author,
                "contract_weight": weight,
                "suggested_lifecycle_id": suggested_lc["id"],
                "suggested_lifecycle_code": suggested_lc["code"],
                "suggested_lifecycle_name": suggested_lc["name"]
            })

        wb.close()
        tmp_path.unlink(missing_ok=True)

        return {
            "status": "success",
            "file_name": file.filename,
            "total_documents_detected": len(items),
            "disciplines_summary": disc_summary,
            "types_summary": type_summary,
            "deliverables": items
        }

    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        logger.error("[MDR Upload] Erreur d'analyse : %s", e)
        raise HTTPException(status_code=500, detail=f"Erreur d'analyse du fichier Excel MDR : {str(e)}")


@router.post("/tdr/codification/auto-generate")
async def api_auto_generate_codification(
    deliverables_json: str = Form(...),
    project_code: str = Form("PRJ"),
    area_code: str = Form("U10"),
    standard: str = Form("IEC_82045"),
    padding_digits: int = Form(4),
    step_increment: int = Form(1),
    separator: str = Form("-"),
    initial_rev: str = Form("0"),
    counter_scope: str = Form("DISCIPLINE_TYPE"),
    overwrite_all: bool = Form(False)
):
    """
    Assistant de codification séquentielle EPC :
    Numérote automatiquement les livrables non codés (ou l'intégralité du registre)
    en respectant la taxonomie de discipline et le format normé (IEC 82045 ou Sonatrach).
    """
    try:
        deliverables = json.loads(deliverables_json)
        if not isinstance(deliverables, list):
            raise ValueError("deliverables_json doit être une liste.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"deliverables_json invalide: {e}")

    updated, stats = generate_sequential_codification(
        deliverables=deliverables,
        project_code=project_code,
        area_code=area_code,
        standard=standard,
        padding_digits=padding_digits,
        step_increment=step_increment,
        separator=separator,
        initial_rev=initial_rev,
        counter_scope=counter_scope,
        overwrite_all=overwrite_all
    )

    preview = []
    for orig, up in zip(deliverables[:15], updated[:15]):
        is_val, msg = validate_codification(up.get("doc_number", ""), standard)
        preview.append({
            "original_number": orig.get("doc_number") or "",
            "generated_number": up.get("doc_number") or "",
            "title": up.get("title") or "Sans titre",
            "discipline": up.get("discipline") or "GEN",
            "doc_type": up.get("doc_type") or "DOC",
            "is_valid": is_val,
            "validation_msg": msg
        })

    return {
        "status": "success",
        "deliverables": updated,
        "stats": stats,
        "preview": preview,
        "taxonomy": EPC_DISCIPLINES
    }


@router.post("/tdr/project-init/confirm-setup")
async def confirm_project_setup(
    project_name: str = Form(...),
    project_code: str = Form(...),
    codification_standard: str = Form("IEC_82045"),
    custom_regex: Optional[str] = Form(None),
    client_sla_days: int = Form(21),
    engineer_sla_days: int = Form(14),
    deliverables_json: str = Form(...),
    custom_lifecycles_json: Optional[str] = Form(None)
):
    """
    Étape finale du Wizard : Crée ou sélectionne le projet, enregistre la codification,
    les délais SLAs et injecte l'ensemble des livrables avec leur cycle de vie configuré.
    """
    try:
        deliverables = json.loads(deliverables_json)
        if not isinstance(deliverables, list):
            raise ValueError("La liste des livrables doit être une liste (peut être vide).")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"deliverables_json invalide : {e}")

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Création ou mise à jour du dossier projet dans 'folders'
    clean_code = project_code.strip().upper()
    clean_name = project_name.strip()
    proj_folder_path = (PROJECTS_ROOT / clean_name).resolve()
    proj_folder_path.mkdir(parents=True, exist_ok=True)

    cursor.execute("SELECT id FROM folders WHERE code = ?", (clean_code,))
    existing_f = cursor.fetchone()

    if existing_f:
        folder_id = existing_f[0]
        custom_lc_map = {}
        if custom_lifecycles_json:
            try:
                custom_lc_map = json.loads(custom_lifecycles_json)
            except Exception:
                custom_lc_map = {}

        cursor.execute("""
            UPDATE folders
            SET name = ?, folder_path = ?, codification_standard = ?, codification_pattern = ?,
                client_sla_days = ?, engineer_sla_days = ?, custom_lifecycles_json = ?
            WHERE id = ?
        """, (clean_name, str(proj_folder_path), codification_standard.upper(), custom_regex, client_sla_days, engineer_sla_days, json.dumps(custom_lc_map, ensure_ascii=False), folder_id))
    else:
        custom_lc_map = {}
        if custom_lifecycles_json:
            try:
                custom_lc_map = json.loads(custom_lifecycles_json)
            except Exception:
                custom_lc_map = {}

        cursor.execute("""
            INSERT INTO folders (
                name, code, folder_path, description, is_indexed, file_count, created_at,
                codification_standard, codification_pattern, client_sla_days, engineer_sla_days,
                custom_lifecycles_json
            ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
        """, (
            clean_name, clean_code, str(proj_folder_path), f"Projet configuré via MDR : {clean_name}",
            len(deliverables), now_str, codification_standard.upper(), custom_regex, client_sla_days, engineer_sla_days,
            json.dumps(custom_lc_map, ensure_ascii=False)
        ))
        folder_id = cursor.lastrowid

    # 2. Injection des livrables dans tdr_documents et création de l'étape initiale START
    inserted_count = 0
    updated_count = 0

    for item in deliverables:
        doc_num = str(item.get("doc_number", "")).strip().upper()
        if not doc_num:
            continue

        title = str(item.get("title", "")).strip()
        discipline = str(item.get("discipline", "GENERAL")).strip().upper()
        doc_type = str(item.get("doc_type", "PLAN")).strip().upper()
        init_rev = str(item.get("initial_revision", "A")).strip().upper()
        planned_date = str(item.get("planned_delivery_date", "")).strip()
        priority = str(item.get("priority", "MEDIUM")).strip().upper()
        fmt = str(item.get("expected_format", "PDF")).strip().upper()
        author = str(item.get("assigned_author", "")).strip()
        weight = float(item.get("contract_weight") or 1.0)
        lc_id = int(item.get("lifecycle_id") or item.get("suggested_lifecycle_id") or 1)

        # Validation de codification selon le standard du projet
        is_codif_valid, codif_msg = validate_codification(doc_num, codification_standard, custom_regex)
        iec_valid_flag = 1 if is_codif_valid else 0

        # Résolution du cycle pour identifier la première étape (standard ou personnalisée)
        custom_lc = custom_lc_map.get(str(lc_id)) or custom_lc_map.get(lc_id)
        if custom_lc and "steps" in custom_lc and custom_lc["steps"]:
            steps = custom_lc["steps"]
        else:
            cursor.execute("SELECT steps_json FROM tdr_lifecycle_templates WHERE id = ?", (lc_id,))
            t_row = cursor.fetchone()
            steps = json.loads(t_row[0]) if t_row else PREDEFINED_LIFECYCLES[0]["steps"]

        first_step = steps[0]
        start_step_code = first_step["code"]
        start_step_label = first_step.get("label", start_step_code)
        start_progress = float(first_step.get("cumulative_percent") or first_step.get("weight_percent") or 10.0)
        start_actor = first_step.get("actor", "ENGINEER")

        # Dossier physique prévisionnel
        target_dir = resolve_dcc_physical_path(proj_folder_path, discipline, doc_type)
        dummy_file_path = str(target_dir / f"{doc_num}.{fmt.lower()}")

        cursor.execute("SELECT id FROM tdr_documents WHERE folder_id = ? AND doc_number = ?", (folder_id, doc_num))
        d_exists = cursor.fetchone()

        if d_exists:
            doc_id = d_exists[0]
            cursor.execute("""
                UPDATE tdr_documents
                SET title = ?, discipline = ?, doc_type = ?, current_revision = ?,
                    lifecycle_id = ?, planned_delivery_date = ?, priority = ?,
                    expected_format = ?, assigned_author = ?, contract_weight = ?,
                    iec_82045_valid = ?, updated_at = ?
                WHERE id = ?
            """, (title, discipline, doc_type, init_rev, lc_id, planned_date, priority, fmt, author, weight, iec_valid_flag, now_str, doc_id))
            updated_count += 1
        else:
            cursor.execute("""
                INSERT INTO tdr_documents (
                    folder_id, doc_number, title, discipline, doc_type, current_revision,
                    revision_count, status_stage, lifecycle_id, current_step,
                    planned_delivery_date, priority, expected_format, assigned_author,
                    contract_weight, progress_percent, turnaround_count, engineer_days_spent,
                    client_days_spent, step_started_at, is_delayed, iec_82045_valid,
                    active_file_path, active_file_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 'INGESTED', ?, ?, ?, ?, ?, ?, ?, ?, 0, 0.0, 0.0, ?, 0, ?, ?, ?, ?, ?)
            """, (
                folder_id, doc_num, title, discipline, doc_type, init_rev,
                lc_id, start_step_code, planned_date, priority, fmt, author,
                weight, start_progress, now_str, iec_valid_flag, dummy_file_path,
                f"{doc_num}.{fmt.lower()}", now_str, now_str
            ))
            doc_id = cursor.lastrowid
            inserted_count += 1

            # Créer la révision A initiale
            cursor.execute("""
                INSERT INTO tdr_revisions (
                    tdr_doc_id, folder_id, revision_label, revision_order, file_name, file_path, is_active, uploaded_at
                ) VALUES (?, ?, ?, 0, ?, ?, 1, ?)
            """, (doc_id, folder_id, init_rev, f"{doc_num}.{fmt.lower()}", dummy_file_path, now_str))

            # Initialiser l'historique d'étape
            cursor.execute("""
                INSERT INTO tdr_document_step_history (
                    tdr_doc_id, folder_id, step_code, step_label, actor, started_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (doc_id, folder_id, start_step_code, start_step_label, start_actor, now_str))

    cursor.execute("UPDATE folders SET file_count = (SELECT COUNT(*) FROM tdr_documents WHERE folder_id = ?) WHERE id = ?", (folder_id, folder_id))
    conn.commit()
    conn.close()

    return {
        "status": "success",
        "folder_id": folder_id,
        "project_name": clean_name,
        "project_code": clean_code,
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "total_documents": inserted_count + updated_count
    }


@router.post("/tdr/document/advance-step")
async def advance_document_step(
    doc_id: int = Form(...),
    target_step_code: Optional[str] = Form(None),
    transmittal_no: Optional[str] = Form(None),
    remarks: Optional[str] = Form("")
):
    """
    Fait progresser un livrable vers l'étape suivante de son cycle de vie.
    Calcule automatiquement le temps passé dans l'étape achevée, met à jour les jours ingénieur vs client,
    vérifie le dépassement de SLA et actualise le pourcentage d'avancement.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT d.*, f.client_sla_days, f.engineer_sla_days, f.custom_lifecycles_json
        FROM tdr_documents d
        JOIN folders f ON f.id = d.folder_id
        WHERE d.id = ?
    """, (doc_id,))
    doc_row = cursor.fetchone()
    if not doc_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Document introuvable.")

    doc = dict(doc_row)
    folder_id = doc["folder_id"]
    client_sla = doc["client_sla_days"] or 21
    engineer_sla = doc["engineer_sla_days"] or 14
    curr_step = doc["current_step"] or "START"
    started_at_str = doc["step_started_at"] or doc["created_at"]

    # Récupération du cycle de vie (personnalisé pour le projet ou standard)
    custom_lc_map = {}
    if "custom_lifecycles_json" in doc_row.keys() and doc_row["custom_lifecycles_json"]:
        try:
            custom_lc_map = json.loads(doc_row["custom_lifecycles_json"])
        except Exception:
            pass

    lc_id_key = str(doc.get("lifecycle_id") or 1)
    if lc_id_key in custom_lc_map and "steps" in custom_lc_map[lc_id_key]:
        steps = custom_lc_map[lc_id_key]["steps"]
    else:
        cursor.execute("SELECT steps_json FROM tdr_lifecycle_templates WHERE id = ?", (doc["lifecycle_id"],))
        lc_row = cursor.fetchone()
        if lc_row:
            steps = json.loads(lc_row["steps_json"])
        else:
            steps = PREDEFINED_LIFECYCLES[0]["steps"]

    curr_idx = -1
    for i, s in enumerate(steps):
        if s["code"].upper() == curr_step.upper():
            curr_idx = i
            break

    if curr_idx == -1:
        curr_idx = 0

    current_step_meta = steps[curr_idx]
    current_actor = current_step_meta.get("actor", "ENGINEER")

    # Calcul de la durée écoulée dans l'étape
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    elapsed_days = 0.0
    try:
        dt_start = datetime.strptime(started_at_str[:19], "%Y-%m-%d %H:%M:%S")
        elapsed_days = round((now - dt_start).total_seconds() / 86400.0, 2)
    except Exception:
        elapsed_days = 0.0

    # Détection de retard SLA
    sla_limit = client_sla if current_actor == "CLIENT" else engineer_sla
    is_delayed = 1 if elapsed_days > sla_limit else 0

    clean_transmittal = str(transmittal_no) if transmittal_no and not hasattr(transmittal_no, 'default') else ""
    clean_remarks = str(remarks) if remarks and not hasattr(remarks, 'default') else ""

    # Clôture de l'étape courante dans tdr_document_step_history
    cursor.execute("""
        UPDATE tdr_document_step_history
        SET completed_at = ?, elapsed_days = ?, sla_limit_days = ?, is_delayed = ?, transmittal_no = ?, remarks = ?
        WHERE tdr_doc_id = ? AND step_code = ? AND completed_at IS NULL
    """, (now_str, elapsed_days, sla_limit, is_delayed, clean_transmittal, clean_remarks, doc_id, curr_step))

    # Mise à jour des compteurs horaires cumulés
    eng_spent = (doc["engineer_days_spent"] or 0.0) + (elapsed_days if current_actor in ["ENGINEER", "DOC_CONTROL"] else 0.0)
    cli_spent = (doc["client_days_spent"] or 0.0) + (elapsed_days if current_actor == "CLIENT" else 0.0)
    turnarounds = doc["turnaround_count"] or 0
    if current_actor == "CLIENT":
        turnarounds += 1

    # Détermination de la prochaine étape
    if target_step_code:
        next_step_meta = None
        for s in steps:
            if s["code"].upper() == target_step_code.upper():
                next_step_meta = s
                break
        if not next_step_meta:
            next_step_meta = steps[-1]
    else:
        if curr_idx + 1 < len(steps):
            next_step_meta = steps[curr_idx + 1]
        else:
            next_step_meta = steps[-1]

    new_step_code = next_step_meta["code"]
    new_step_label = next_step_meta.get("label", new_step_code)
    new_actor = next_step_meta.get("actor", "ENGINEER")
    new_progress = next_step_meta.get("cumulative_percent", 100.0)

    # Mise à jour tdr_documents
    cursor.execute("""
        UPDATE tdr_documents
        SET current_step = ?, progress_percent = ?, engineer_days_spent = ?, client_days_spent = ?,
            turnaround_count = ?, step_started_at = ?, is_delayed = ?, updated_at = ?
        WHERE id = ?
    """, (new_step_code, new_progress, eng_spent, cli_spent, turnarounds, now_str, 0, now_str, doc_id))

    # Ouverture de la nouvelle étape dans l'historique
    cursor.execute("""
        INSERT INTO tdr_document_step_history (
            tdr_doc_id, folder_id, step_code, step_label, actor, started_at
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (doc_id, folder_id, new_step_code, new_step_label, new_actor, now_str))

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "doc_id": doc_id,
        "previous_step": curr_step,
        "new_step": new_step_code,
        "new_progress_percent": new_progress,
        "elapsed_days_previous_step": elapsed_days,
        "is_delayed_previous_step": bool(is_delayed),
        "turnaround_count": turnarounds
    }


@router.get("/tdr/dashboard-analytics/{folder_id}")
async def get_tdr_dashboard_analytics(folder_id: int):
    """
    Dashboard analytique complet en temps réel selon les 10 KPIs EPC :
    - Avancement global pondéré par poids contractuel (S-Curve)
    - Compteurs de retard Client vs Ingénieur
    - Délais moyens constatés
    - Répartition par discipline et par étape de cycle
    - Top 5 des documents les plus en retard avec responsable
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM folders WHERE id = ?", (folder_id,))
    f_row = cursor.fetchone()
    if not f_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Projet introuvable.")

    client_sla = f_row["client_sla_days"] or 21
    engineer_sla = f_row["engineer_sla_days"] or 14

    cursor.execute("""
        SELECT d.*, t.steps_json
        FROM tdr_documents d
        LEFT JOIN tdr_lifecycle_templates t ON t.id = d.lifecycle_id
        WHERE d.folder_id = ?
    """, (folder_id,))
    doc_rows = cursor.fetchall()

    docs = [dict(r) for r in doc_rows]
    total_docs = len(docs)
    now = datetime.now()

    global_progress = calculate_weighted_project_progress(docs)

    client_delayed_count = 0
    engineer_delayed_count = 0
    total_client_days = 0.0
    total_client_responses = 0
    total_engineer_days = 0.0
    total_turnarounds = 0
    discipline_stats = {}
    step_stats = {}
    delayed_candidates = []

    for d in docs:
        curr_step = d.get("current_step") or "START"
        step_stats[curr_step] = step_stats.get(curr_step, 0) + 1

        disc = d.get("discipline") or "GENERAL"
        if disc not in discipline_stats:
            discipline_stats[disc] = {"count": 0, "sum_progress": 0.0, "sum_weight": 0.0}
        discipline_stats[disc]["count"] += 1
        discipline_stats[disc]["sum_progress"] += (float(d.get("progress_percent") or 0.0) * float(d.get("contract_weight") or 1.0))
        discipline_stats[disc]["sum_weight"] += float(d.get("contract_weight") or 1.0)

        turnarounds = int(d.get("turnaround_count") or 0)
        total_turnarounds += turnarounds

        total_engineer_days += float(d.get("engineer_days_spent") or 0.0)
        total_client_days += float(d.get("client_days_spent") or 0.0)
        if turnarounds > 0:
            total_client_responses += turnarounds

        # Vérification du temps passé dans l'étape active
        started_str = d.get("step_started_at") or d.get("created_at") or ""
        elapsed_days = 0.0
        if started_str:
            try:
                st_dt = datetime.strptime(started_str[:19], "%Y-%m-%d %H:%M:%S")
                elapsed_days = round((now - st_dt).total_seconds() / 86400.0, 1)
            except Exception:
                pass

        # Identifier l'acteur de l'étape courante
        steps = []
        if d.get("steps_json"):
            try:
                steps = json.loads(d["steps_json"])
            except Exception:
                steps = []
        if not steps:
            steps = PREDEFINED_LIFECYCLES[0]["steps"]

        actor = "ENGINEER"
        for s in steps:
            if s["code"].upper() == curr_step.upper():
                actor = s.get("actor", "ENGINEER")
                break

        limit_sla = client_sla if actor == "CLIENT" else engineer_sla
        if elapsed_days > limit_sla:
            overdue = elapsed_days - limit_sla
            if actor == "CLIENT":
                client_delayed_count += 1
            else:
                engineer_delayed_count += 1

            delayed_candidates.append({
                "doc_id": d["id"],
                "doc_number": d["doc_number"],
                "title": d["title"],
                "discipline": disc,
                "current_step": curr_step,
                "actor": actor,
                "days_elapsed": elapsed_days,
                "sla_limit": limit_sla,
                "days_overdue": round(overdue, 1),
                "assigned_author": d.get("assigned_author") or "Non assigné",
                "progress_percent": d.get("progress_percent") or 0.0
            })

    # Tri du Top 5 des retards par dépassement décroissant
    delayed_candidates.sort(key=lambda x: x["days_overdue"], reverse=True)
    top_5_delayed = delayed_candidates[:5]

    # Moyennes
    avg_engineer_days = round(total_engineer_days / total_docs, 1) if total_docs > 0 else 0.0
    avg_client_days = round(total_client_days / total_client_responses, 1) if total_client_responses > 0 else round(total_client_days / max(total_docs, 1), 1)

    # Calcul final des pourcentages par discipline
    discipline_output = {}
    for k, v in discipline_stats.items():
        avg_p = round(v["sum_progress"] / v["sum_weight"], 1) if v["sum_weight"] > 0 else 0.0
        discipline_output[k] = {
            "count": v["count"],
            "avg_progress_percent": avg_p
        }

    # Points pour la courbe en S (S-Curve)
    s_curve = [
        {"milestone": "Start", "planned_percent": 10.0, "actual_percent": min(10.0, global_progress)},
        {"milestone": "IDC", "planned_percent": 30.0, "actual_percent": min(30.0, global_progress)},
        {"milestone": "IFR", "planned_percent": 60.0, "actual_percent": min(60.0, global_progress)},
        {"milestone": "Client Return", "planned_percent": 75.0, "actual_percent": min(75.0, global_progress)},
        {"milestone": "IFC", "planned_percent": 95.0, "actual_percent": min(95.0, global_progress)},
        {"milestone": "As-Built", "planned_percent": 100.0, "actual_percent": global_progress}
    ]

    conn.close()

    return {
        "status": "success",
        "folder_id": folder_id,
        "project_name": f_row["name"],
        "project_code": f_row["code"],
        "codification_standard": f_row["codification_standard"],
        "client_sla_days": client_sla,
        "engineer_sla_days": engineer_sla,
        "global_progress_percent": global_progress,
        "total_documents": total_docs,
        "client_delayed_count": client_delayed_count,
        "engineer_delayed_count": engineer_delayed_count,
        "total_delayed_count": client_delayed_count + engineer_delayed_count,
        "avg_client_response_days": avg_client_days,
        "avg_engineer_elaboration_days": avg_engineer_days,
        "total_turnarounds": total_turnarounds,
        "discipline_distribution": discipline_output,
        "status_distribution": step_stats,
        "s_curve_points": s_curve,
        "top_delayed_documents": top_5_delayed
    }


@router.post("/tdr/ocr/extract-and-index/{doc_id}")
async def extract_and_index_document(doc_id: int):
    """
    Exécute l'extraction OCR / cartouche via fitz / pytesseract sur le document actif,
    met à jour son contenu textuel et enrichit l'index SQLite FTS5 pour recherche plein texte.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tdr_documents WHERE id = ?", (doc_id,))
    doc_row = cursor.fetchone()
    if not doc_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Document introuvable.")

    active_path = doc_row["active_file_path"]
    if not active_path or not Path(active_path).exists():
        conn.close()
        raise HTTPException(status_code=400, detail="Fichier physique introuvable sur le disque.")

    ocr_res = extract_document_text(active_path)
    if not ocr_res.get("success"):
        conn.close()
        return {"status": "warning", "message": ocr_res.get("error", "Aucun texte extrait")}

    extracted_txt = ocr_res.get("text", "")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        UPDATE tdr_documents
        SET ocr_content = ?, updated_at = ?
        WHERE id = ?
    """, (extracted_txt[:50000], now_str, doc_id))

    # Mise à jour FTS5
    try:
        cursor.execute("""
            INSERT INTO indexed_files_fts (file_name, drawing_root_no, revision_label, file_path, doc_type, folder_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (doc_row["active_file_name"], doc_row["doc_number"], doc_row["current_revision"], active_path, doc_row["doc_type"], doc_row["folder_id"]))
    except Exception:
        pass

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "doc_id": doc_id,
        "method": ocr_res.get("method"),
        "extracted_chars": ocr_res.get("extracted_chars", 0),
        "cartouche_metadata": ocr_res.get("cartouche_metadata", {})
    }
