# -*- coding: utf-8 -*-
import os
import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
import uuid
import threading

logger = logging.getLogger(__name__)

# Base path for SQLite database
PROCUREMENT_DB_PATH = Path("d:/DATA BASE IA/data/procurement.db")
PROCUREMENT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_db_lock = threading.Lock()

def get_db_connection():
    """Create a thread-safe connection to the SQLite database."""
    conn = sqlite3.connect(str(PROCUREMENT_DB_PATH), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_procurement_db():
    """Initialize the SQLite schema for the Procurement / Achats Module."""
    with _db_lock:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # 1. Table for Contracts
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS contracts (
                id TEXT PRIMARY KEY,
                numero_contrat TEXT UNIQUE NOT NULL,
                fournisseur TEXT NOT NULL,
                objet TEXT NOT NULL,
                date_signature TEXT,
                date_debut TEXT,
                date_fin_prevue TEXT,
                montant REAL,
                devise TEXT DEFAULT 'DZD',
                statut TEXT DEFAULT 'signé', -- en négociation, signé, en cours d'exécution, clôturé, résilié
                document_path TEXT,
                project_id TEXT DEFAULT 'general',
                created_at TEXT,
                updated_at TEXT
            )
            """)

            # 2. Table for Contract Items
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS contract_items (
                id TEXT PRIMARY KEY,
                contract_id TEXT NOT NULL,
                designation TEXT NOT NULL,
                reference TEXT,
                quantite_contractuelle REAL NOT NULL,
                unite TEXT NOT NULL,
                prix_unitaire REAL NOT NULL,
                delai_livraison TEXT,
                statut TEXT DEFAULT 'non livré', -- non livré, partiellement livré, livré, en litige
                FOREIGN KEY (contract_id) REFERENCES contracts (id) ON DELETE CASCADE
            )
            """)

            # 3. Table for Material Receipts (Goods Received)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS material_receipts (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                date_reception TEXT NOT NULL,
                quantite_recue REAL NOT NULL,
                numero_bl TEXT NOT NULL,
                lieu_stockage TEXT NOT NULL,
                etat TEXT NOT NULL, -- conforme, endommagé, non conforme
                responsable TEXT NOT NULL,
                documents TEXT, -- comma-separated or JSON list of file names/paths
                remarques TEXT,
                numero_pv TEXT,
                created_at TEXT,
                FOREIGN KEY (item_id) REFERENCES contract_items (id) ON DELETE CASCADE
            )
            """)

            # 4. Table for Material Issues (Goods Issued to site)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS material_issues (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                date_sortie TEXT NOT NULL,
                quantite_sortie REAL NOT NULL,
                motif TEXT NOT NULL, -- utilisation chantier, transfert, retour fournisseur
                destination TEXT NOT NULL, -- zone d'utilisation
                responsable TEXT NOT NULL,
                numero_pv TEXT NOT NULL,
                created_at TEXT,
                FOREIGN KEY (item_id) REFERENCES contract_items (id) ON DELETE CASCADE
            )
            """)

            # 5. Table for PV (Procès-Verbaux)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS pvs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero_pv TEXT NOT NULL,
                type_pv TEXT NOT NULL, -- RECEIPT, ISSUE, or RETURN
                reference_id TEXT NOT NULL, -- receipt_id, issue_id, return_id, or batch code
                created_at TEXT NOT NULL,
                responsables TEXT NOT NULL, -- JSON or string list
                pdf_path TEXT,
                project_id TEXT DEFAULT 'general'
            )
            """)

            # Run Migrations on Existing DB
            # 1. Add project_id to contracts if not exists
            try:
                cursor.execute("ALTER TABLE contracts ADD COLUMN project_id TEXT DEFAULT 'general'")
            except sqlite3.OperationalError:
                pass
            
            # 2. Add numero_pv to material_receipts if not exists
            try:
                cursor.execute("ALTER TABLE material_receipts ADD COLUMN numero_pv TEXT")
            except sqlite3.OperationalError:
                pass

            # 2b. Add delai_livraison to contracts if not exists
            try:
                cursor.execute("ALTER TABLE contracts ADD COLUMN delai_livraison TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass

            # 3. Create material_returns table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS material_returns (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                date_retour TEXT NOT NULL,
                quantite_retournee REAL NOT NULL,
                motif TEXT NOT NULL,
                responsable TEXT NOT NULL,
                numero_pv TEXT NOT NULL,
                lieu_stockage TEXT NOT NULL,
                created_at TEXT,
                FOREIGN KEY (item_id) REFERENCES contract_items (id) ON DELETE CASCADE
            )
            """)

            # 4. Create procurement_projects table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS procurement_projects (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                code TEXT DEFAULT '',
                description TEXT DEFAULT '',
                created_at TEXT
            )
            """)

            # Seed default project if not exists
            now_init = datetime.now().isoformat()
            cursor.execute("""
                INSERT OR IGNORE INTO procurement_projects (id, name, code, description, created_at)
                VALUES ('general', 'Projet Général / Non classé', 'GEN', 'Contrats généraux ou en attente d''affectation projet', ?)
            """, (now_init,))

            conn.commit()
            conn.close()
            logger.info("Procurement SQLite database initialized and migrated successfully.")
        except Exception as e:
            logger.error(f"Error initializing Procurement SQLite database: {e}", exc_info=True)


# --- PROJECTS CRUD ---

def ensure_project_exists(project_id_or_name: str) -> str:
    """Ensure a project exists in procurement_projects and return its canonical id."""
    val = str(project_id_or_name or "").strip()
    if not val or val.lower() in ("general", "général", "projet général", "tous"):
        return "general"
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM procurement_projects WHERE id = ? OR LOWER(name) = LOWER(?)", (val, val))
            row = cursor.fetchone()
            if row:
                return row["id"]
            slug = "PRJ-" + "".join(ch if ch.isalnum() else "-" for ch in val.upper()).strip("-")[:24]
            if not slug or slug == "PRJ-":
                slug = f"PRJ-{uuid.uuid4().hex[:6].upper()}"
            cursor.execute("SELECT id FROM procurement_projects WHERE id = ?", (slug,))
            if cursor.fetchone():
                slug = f"{slug}-{uuid.uuid4().hex[:4].upper()}"
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO procurement_projects (id, name, code, description, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (slug, val, slug.replace("PRJ-", "")[:10], "", now))
            conn.commit()
            return slug
        finally:
            conn.close()


def get_projects() -> list:
    init_procurement_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    # Sync any project_id present in contracts that isn't in procurement_projects yet
    cursor.execute("SELECT DISTINCT project_id FROM contracts WHERE project_id IS NOT NULL AND project_id != ''")
    distinct_pids = [r[0] for r in cursor.fetchall()]
    conn.close()
    for pid in distinct_pids:
        ensure_project_exists(pid)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM contracts c WHERE c.project_id = p.id) as contracts_count
        FROM procurement_projects p
        ORDER BY CASE WHEN p.id = 'general' THEN 1 ELSE 0 END, p.name ASC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def create_project(name: str, code: str = "", description: str = "") -> dict:
    init_procurement_db()
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("Le nom du projet est obligatoire.")
    pid = ensure_project_exists(clean_name)
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            if code or description:
                cursor.execute("""
                    UPDATE procurement_projects
                    SET code = COALESCE(NULLIF(?, ''), code),
                        description = COALESCE(NULLIF(?, ''), description)
                    WHERE id = ?
                """, (code.strip(), description.strip(), pid))
                conn.commit()
            cursor.execute("SELECT * FROM procurement_projects WHERE id = ?", (pid,))
            row = cursor.fetchone()
            return dict(row) if row else {"id": pid, "name": clean_name, "code": code, "description": description}
        finally:
            conn.close()


def delete_project(project_id: str):
    if not project_id or project_id == "general":
        raise ValueError("Le projet général par défaut ne peut pas être supprimé.")
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE contracts SET project_id = 'general' WHERE project_id = ?", (project_id,))
            cursor.execute("UPDATE pvs SET project_id = 'general' WHERE project_id = ?", (project_id,))
            cursor.execute("DELETE FROM procurement_projects WHERE id = ?", (project_id,))
            conn.commit()
        finally:
            conn.close()


def update_contract_project(contract_id: str, project_id: str) -> dict:
    canon_pid = ensure_project_exists(project_id)
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute("""
                UPDATE contracts SET project_id = ?, updated_at = ?
                WHERE id = ? OR numero_contrat = ?
            """, (canon_pid, now, contract_id, contract_id))
            conn.commit()
        finally:
            conn.close()
    return {"contract_id": contract_id, "project_id": canon_pid}


# --- CONTRACTS CRUD ---

def create_contract(numero_contrat: str, fournisseur: str, objet: str, date_signature: str,
                    date_debut: str, date_fin_prevue: str, montant: float, devise: str,
                    statut: str, document_path: str = None, project_id: str = 'general',
                    delai_livraison: str = '') -> str:
    canon_pid = ensure_project_exists(project_id)
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            c_id = str(uuid.uuid4())
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO contracts (
                    id, numero_contrat, fournisseur, objet, date_signature, date_debut,
                    date_fin_prevue, montant, devise, statut, document_path, project_id,
                    delai_livraison, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (c_id, numero_contrat, fournisseur, objet, date_signature, date_debut,
                  date_fin_prevue, montant, devise, statut, document_path, canon_pid,
                  delai_livraison or '', now, now))
            conn.commit()
            return c_id
        finally:
            conn.close()


def get_contracts(include_items: bool = True, project_id: str = None) -> list:
    init_procurement_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    if project_id:
        cursor.execute("""
            SELECT c.*, 
                   COALESCE(p.name, c.project_id, 'Projet Général / Non classé') as project_name,
                   (SELECT COUNT(*) FROM contract_items WHERE contract_id = c.id) as items_count,
                   (SELECT COALESCE(SUM(quantite_contractuelle * prix_unitaire), 0) FROM contract_items WHERE contract_id = c.id) as computed_montant
            FROM contracts c
            LEFT JOIN procurement_projects p ON p.id = c.project_id
            WHERE c.project_id = ?
            ORDER BY c.created_at DESC
        """, (project_id,))
    else:
        cursor.execute("""
            SELECT c.*, 
                   COALESCE(p.name, c.project_id, 'Projet Général / Non classé') as project_name,
                   (SELECT COUNT(*) FROM contract_items WHERE contract_id = c.id) as items_count,
                   (SELECT COALESCE(SUM(quantite_contractuelle * prix_unitaire), 0) FROM contract_items WHERE contract_id = c.id) as computed_montant
            FROM contracts c
            LEFT JOIN procurement_projects p ON p.id = c.project_id
            ORDER BY c.created_at DESC
        """)
    rows = cursor.fetchall()
    conn.close()
    contracts = [dict(r) for r in rows]
    if include_items:
        for c in contracts:
            c["items"] = get_contract_items(c["id"])
            if not c.get("delai_livraison") and c["items"]:
                first_dl = next((it.get("delai_livraison") for it in c["items"] if it.get("delai_livraison")), "")
                c["delai_livraison"] = first_dl
    return contracts


def get_contract(contract_id: str) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.*, COALESCE(p.name, c.project_id, 'Projet Général / Non classé') as project_name
        FROM contracts c
        LEFT JOIN procurement_projects p ON p.id = c.project_id
        WHERE c.id = ?
    """, (contract_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["items"] = get_contract_items(contract_id)
    return d


def update_contract(contract_id: str, numero_contrat: str, fournisseur: str, objet: str,
                    date_signature: str, date_debut: str, date_fin_prevue: str,
                    montant: float, devise: str, statut: str, document_path: str = None,
                    project_id: str = 'general', delai_livraison: str = ''):
    canon_pid = ensure_project_exists(project_id)
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute("""
                UPDATE contracts
                SET numero_contrat = ?, fournisseur = ?, objet = ?, date_signature = ?,
                    date_debut = ?, date_fin_prevue = ?, montant = ?, devise = ?,
                    statut = ?, document_path = ?, project_id = ?, delai_livraison = ?, updated_at = ?
                WHERE id = ?
            """, (numero_contrat, fournisseur, objet, date_signature, date_debut,
                  date_fin_prevue, montant, devise, statut, document_path, canon_pid,
                  delai_livraison or '', now, contract_id))
            conn.commit()
        finally:
            conn.close()


def delete_contract(contract_id: str):
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM contracts WHERE id = ?", (contract_id,))
            conn.commit()
        finally:
            conn.close()


def import_contract_with_items(contract_data: dict, project_id: str = 'general', document_path: str = None) -> dict:
    """
    Insère (ou met à jour si le numéro de contrat existe déjà) un contrat complet
    extrait par NuExtract-3 avec toute sa liste d'équipements et son bordereau de prix.
    Préserve les réceptions existantes en cas de réimportation.
    """
    init_procurement_db()
    numero_contrat = str(contract_data.get("numero_contrat") or "").strip()
    if not numero_contrat:
        numero_contrat = f"CTR-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    fournisseur = str(contract_data.get("fournisseur") or "Fournisseur non spécifié").strip()
    objet = str(contract_data.get("objet") or f"Contrat {numero_contrat}").strip()
    delai_global = str(contract_data.get("delai_livraison") or "").strip()
    date_signature = str(contract_data.get("date_signature") or datetime.now().strftime("%Y-%m-%d")).strip()
    date_debut = str(contract_data.get("date_debut") or date_signature).strip()
    date_fin_prevue = str(contract_data.get("date_fin_prevue") or "").strip()
    devise = str(contract_data.get("devise") or "DZD").strip().upper()
    statut = str(contract_data.get("statut") or "signé").strip()
    doc_path = document_path or str(contract_data.get("document_path") or "")
    raw_proj = project_id if (project_id and project_id != "general") else (contract_data.get("project_id") if contract_data.get("project_id") not in (None, "", "general") else (contract_data.get("projet") or "general"))
    proj_id = ensure_project_exists(raw_proj)

    raw_items = contract_data.get("items") or []
    computed_total = 0.0
    normalized_items = []
    for idx, it in enumerate(raw_items):
        if not isinstance(it, dict):
            continue
        desig = str(it.get("designation") or it.get("name") or "").strip()
        if not desig:
            continue
        ref = str(it.get("reference") or it.get("code") or f"EQ-{idx + 1:02d}").strip()
        try:
            qty = float(it.get("quantite_contractuelle") if it.get("quantite_contractuelle") is not None else it.get("ordered", 1.0))
        except (ValueError, TypeError):
            qty = 1.0
        if qty <= 0:
            qty = 1.0
        unite = str(it.get("unite") or "U").strip() or "U"
        try:
            pu = float(it.get("prix_unitaire") if it.get("prix_unitaire") is not None else 0.0)
        except (ValueError, TypeError):
            pu = 0.0
        delai_it = str(it.get("delai_livraison") or delai_global or "").strip()
        computed_total += qty * pu
        normalized_items.append({
            "reference": ref,
            "designation": desig,
            "quantite_contractuelle": qty,
            "unite": unite,
            "prix_unitaire": pu,
            "delai_livraison": delai_it
        })

    try:
        montant = float(contract_data.get("montant") or 0.0)
    except (ValueError, TypeError):
        montant = 0.0
    if computed_total > 0 and montant <= 0:
        montant = round(computed_total, 2)

    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute("SELECT id, document_path FROM contracts WHERE numero_contrat = ?", (numero_contrat,))
            existing = cursor.fetchone()

            if existing:
                c_id = existing["id"]
                final_doc_path = doc_path or existing["document_path"] or ""
                cursor.execute("""
                    UPDATE contracts
                    SET fournisseur = ?, objet = ?, date_signature = ?, date_debut = ?,
                        date_fin_prevue = ?, montant = ?, devise = ?, statut = ?,
                        document_path = ?, project_id = ?, delai_livraison = ?, updated_at = ?
                    WHERE id = ?
                """, (fournisseur, objet, date_signature, date_debut, date_fin_prevue,
                      montant, devise, statut, final_doc_path, proj_id, delai_global, now, c_id))
                action_mode = "updated"
            else:
                c_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO contracts (
                        id, numero_contrat, fournisseur, objet, date_signature, date_debut,
                        date_fin_prevue, montant, devise, statut, document_path, project_id,
                        delai_livraison, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (c_id, numero_contrat, fournisseur, objet, date_signature, date_debut,
                      date_fin_prevue, montant, devise, statut, doc_path, proj_id,
                      delai_global, now, now))
                action_mode = "created"

            # Synchroniser les équipements du contrat sans supprimer les réceptions liées
            cursor.execute("SELECT id, reference, designation FROM contract_items WHERE contract_id = ?", (c_id,))
            existing_items = cursor.fetchall()
            by_ref = {str(r["reference"] or "").strip().lower(): r["id"] for r in existing_items if r["reference"]}
            by_desig = {str(r["designation"] or "").strip().lower(): r["id"] for r in existing_items if r["designation"]}

            inserted_item_ids = []
            used_existing_ids = set()
            for it in normalized_items:
                ref_key = it["reference"].lower()
                desig_key = it["designation"].lower()
                cand_ref_id = by_ref.get(ref_key)
                cand_desig_id = by_desig.get(desig_key)
                matched_id = None
                if cand_ref_id and cand_ref_id not in used_existing_ids:
                    matched_id = cand_ref_id
                elif cand_desig_id and cand_desig_id not in used_existing_ids and ref_key not in by_ref:
                    matched_id = cand_desig_id
                if matched_id:
                    used_existing_ids.add(matched_id)
                    cursor.execute("""
                        UPDATE contract_items
                        SET designation = ?, reference = ?, quantite_contractuelle = ?,
                            unite = ?, prix_unitaire = ?, delai_livraison = ?
                        WHERE id = ?
                    """, (it["designation"], it["reference"], it["quantite_contractuelle"],
                          it["unite"], it["prix_unitaire"], it["delai_livraison"], matched_id))
                    inserted_item_ids.append(matched_id)
                else:
                    new_item_id = str(uuid.uuid4())
                    cursor.execute("""
                        INSERT INTO contract_items (
                            id, contract_id, designation, reference, quantite_contractuelle,
                            unite, prix_unitaire, delai_livraison, statut
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (new_item_id, c_id, it["designation"], it["reference"],
                          it["quantite_contractuelle"], it["unite"], it["prix_unitaire"],
                          it["delai_livraison"], "non livré"))
                    inserted_item_ids.append(new_item_id)

            # Supprimer les anciens articles obsolètes qui n'ont aucune réception liée
            for r in existing_items:
                old_id = r["id"]
                if old_id not in inserted_item_ids:
                    cursor.execute("SELECT COUNT(*) as cnt FROM material_receipts WHERE item_id = ?", (old_id,))
                    if cursor.fetchone()["cnt"] == 0:
                        cursor.execute("DELETE FROM contract_items WHERE id = ?", (old_id,))

            conn.commit()
        finally:
            conn.close()

    saved_contract = get_contract(c_id)
    saved_contract["action"] = action_mode
    saved_contract["items_imported_count"] = len(inserted_item_ids)
    return saved_contract



# --- CONTRACT ITEMS CRUD ---

def create_contract_item(contract_id: str, designation: str, reference: str,
                         quantite_contractuelle: float, unite: str,
                         prix_unitaire: float, delai_livraison: str) -> str:
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            item_id = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO contract_items (
                    id, contract_id, designation, reference, quantite_contractuelle,
                    unite, prix_unitaire, delai_livraison, statut
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (item_id, contract_id, designation, reference, quantite_contractuelle,
                  unite, prix_unitaire, delai_livraison, 'non livré'))
            conn.commit()
            return item_id
        finally:
            conn.close()


def get_contract_items(contract_id: str) -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    # Fetch items with computed received, issued and returned quantities
    cursor.execute("""
        SELECT ci.*, 
               COALESCE((SELECT SUM(quantite_recue) FROM material_receipts WHERE item_id = ci.id AND etat = 'conforme'), 0) as quantite_livree,
               COALESCE((SELECT SUM(quantite_sortie) FROM material_issues WHERE item_id = ci.id), 0) as quantite_sortie,
               COALESCE((SELECT SUM(quantite_retournee) FROM material_returns WHERE item_id = ci.id), 0) as quantite_retournee
        FROM contract_items ci
        WHERE ci.contract_id = ?
    """, (contract_id,))
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for r in rows:
        d = dict(r)
        # Compute remaining and total line amount
        d["quantite_restante"] = max(0.0, d["quantite_contractuelle"] - d["quantite_livree"])
        d["montant_total"] = round(float(d.get("quantite_contractuelle") or 0.0) * float(d.get("prix_unitaire") or 0.0), 2)
        results.append(d)
    return results


def update_contract_item(item_id: str, designation: str, reference: str,
                         quantite_contractuelle: float, unite: str,
                         prix_unitaire: float, delai_livraison: str, statut: str):
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE contract_items
                SET designation = ?, reference = ?, quantite_contractuelle = ?,
                    unite = ?, prix_unitaire = ?, delai_livraison = ?, statut = ?
                WHERE id = ?
            """, (designation, reference, quantite_contractuelle, unite, prix_unitaire,
                  delai_livraison, statut, item_id))
            conn.commit()
        finally:
            conn.close()


def delete_contract_item(item_id: str):
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM contract_items WHERE id = ?", (item_id,))
            conn.commit()
        finally:
            conn.close()


# --- STOCK COMPUTATION ---

def get_item_stock_stats(item_id: str) -> dict:
    """Get the live stock statistics for a specific contract item including returns."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Total conforming received
    cursor.execute("""
        SELECT COALESCE(SUM(quantite_recue), 0) 
        FROM material_receipts 
        WHERE item_id = ? AND etat = 'conforme'
    """, (item_id,))
    total_received = cursor.fetchone()[0]
    
    # 2. Total issued
    cursor.execute("""
        SELECT COALESCE(SUM(quantite_sortie), 0) 
        FROM material_issues 
        WHERE item_id = ?
    """, (item_id,))
    total_issued = cursor.fetchone()[0]

    # 3. Total returned
    cursor.execute("""
        SELECT COALESCE(SUM(quantite_retournee), 0) 
        FROM material_returns 
        WHERE item_id = ?
    """, (item_id,))
    total_returned = cursor.fetchone()[0]
    
    conn.close()
    
    available = max(0.0, total_received + total_returned - total_issued)
    return {
        "received": total_received,
        "issued": total_issued,
        "returned": total_returned,
        "available": available
    }


def get_realtime_stock() -> list:
    """Get real-time balance of stock for all items of all contracts."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ci.id as item_id, ci.designation, ci.reference, ci.unite,
               c.id as contract_id, c.project_id, c.numero_contrat, c.fournisseur,
               COALESCE((SELECT SUM(quantite_recue) FROM material_receipts WHERE item_id = ci.id AND etat = 'conforme'), 0) as total_received,
               COALESCE((SELECT SUM(quantite_sortie) FROM material_issues WHERE item_id = ci.id), 0) as total_issued,
               COALESCE((SELECT SUM(quantite_retournee) FROM material_returns WHERE item_id = ci.id), 0) as total_returned
        FROM contract_items ci
        JOIN contracts c ON ci.contract_id = c.id
        ORDER BY c.numero_contrat, ci.designation
    """)
    rows = cursor.fetchall()
    conn.close()
    
    stock = []
    for r in rows:
        d = dict(r)
        d["available"] = max(0.0, d["total_received"] + d["total_returned"] - d["total_issued"])
        stock.append(d)
    return stock


# --- MATERIAL MOVEMENTS & PV GENERATION ---

def _generate_pv_number(type_pv: str, cursor) -> str:
    """Generate an auto-incremented professional PV number (e.g. PV-REC-2026-0001)."""
    current_year = datetime.now().year
    if type_pv == "RECEIPT":
        prefix = "REC"
    elif type_pv == "ISSUE":
        prefix = "SRT"
    else:
        prefix = "RET"
    
    cursor.execute("""
        SELECT COUNT(*) FROM pvs WHERE numero_pv LIKE ?
    """, (f"PV-{prefix}-{current_year}-%",))
    count = cursor.fetchone()[0]
    
    next_num = count + 1
    return f"PV-{prefix}-{current_year}-{next_num:04d}"


def receive_material(item_id: str, date_reception: str, quantite_recue: float,
                     numero_bl: str, lieu_stockage: str, etat: str,
                     responsable: str, remarques: str = "", documents: str = "") -> dict:
    """Record single material receipt, update status, and generate receipt PV."""
    # Legacy wrapper delegating to batch function
    items_list = [{
        "item_id": item_id,
        "quantite_recue": quantite_recue,
        "lieu_stockage": lieu_stockage,
        "etat": etat
    }]
    pv_number = receive_materials_batch(items_list, date_reception, numero_bl, responsable, remarques, documents)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.*, ci.designation, ci.reference, c.numero_contrat, c.fournisseur
        FROM material_receipts r
        JOIN contract_items ci ON r.item_id = ci.id
        JOIN contracts c ON ci.contract_id = c.id
        WHERE r.numero_pv = ? AND r.item_id = ?
    """, (pv_number, item_id))
    row = cursor.fetchone()
    conn.close()
    
    res = dict(row) if row else {}
    res["numero_pv"] = pv_number
    return res


def receive_materials_batch(items_list: list, date_reception: str, numero_bl: str,
                            responsable: str, remarques: str = "", documents: str = "",
                            numero_pv: str = None) -> str:
    """Record batch material receipts under a single generated PV."""
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            
            # Determine project_id from the first item
            project_id = 'general'
            if items_list:
                cursor.execute("""
                    SELECT c.project_id FROM contracts c
                    JOIN contract_items ci ON ci.contract_id = c.id
                    WHERE ci.id = ?
                """, (items_list[0]["item_id"],))
                proj_row = cursor.fetchone()
                if proj_row:
                    project_id = proj_row[0] or 'general'

            if numero_pv and numero_pv.strip():
                pv_number = numero_pv.strip()
                # Check for duplicate PV number in this project
                cursor.execute("SELECT COUNT(*) FROM pvs WHERE numero_pv = ? AND project_id = ?", (pv_number, project_id))
                if cursor.fetchone()[0] > 0:
                    raise ValueError(f"Le numéro de PV '{pv_number}' existe déjà pour ce projet.")
            else:
                pv_number = _generate_pv_number("RECEIPT", cursor)
            
            for it in items_list:
                item_id = it["item_id"]
                quantite_recue = it["quantite_recue"]
                lieu_stockage = it["lieu_stockage"]
                etat = it["etat"]
                receipt_id = str(uuid.uuid4())
                
                cursor.execute("""
                    INSERT INTO material_receipts (
                        id, item_id, date_reception, quantite_recue, numero_bl,
                        lieu_stockage, etat, responsable, documents, remarques, numero_pv, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (receipt_id, item_id, date_reception, quantite_recue, numero_bl,
                      lieu_stockage, etat, responsable, documents, remarques, pv_number, now))
                
                # Update item delivery status
                cursor.execute("""
                    SELECT quantite_contractuelle, 
                           (SELECT COALESCE(SUM(quantite_recue), 0) FROM material_receipts WHERE item_id = ? AND etat = 'conforme') as total_conforming
                    FROM contract_items WHERE id = ?
                """, (item_id, item_id))
                item_row = cursor.fetchone()
                
                if item_row:
                    qty_contractual = item_row[0]
                    total_conforming = item_row[1]
                    
                    if total_conforming >= qty_contractual:
                        new_status = "livré"
                    elif total_conforming > 0:
                        new_status = "partiellement livré"
                    else:
                        new_status = "non livré"
                        
                    if etat == "non conforme" or etat == "en litige":
                        new_status = "en litige"
                        
                    cursor.execute("""
                        UPDATE contract_items SET statut = ? WHERE id = ?
                    """, (new_status, item_id))
            
            # Insert PV record using pv_number as reference_id to denote a batch
            cursor.execute("""
                INSERT INTO pvs (numero_pv, type_pv, reference_id, created_at, responsables, project_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (pv_number, "RECEIPT", pv_number, now, responsable, project_id))
            
            conn.commit()
            return pv_number
        except Exception as e:
            conn.rollback()
            logger.error(f"Error executing receive_materials_batch: {e}", exc_info=True)
            raise e
        finally:
            conn.close()


def issue_material(item_id: str, date_sortie: str, quantite_sortie: float,
                   motif: str, destination: str, responsable: str) -> dict:
    """Record single material issue with stock verification, and auto-generate issue PV."""
    items_list = [{
        "item_id": item_id,
        "quantite_sortie": quantite_sortie
    }]
    pv_number = issue_materials_batch(items_list, date_sortie, motif, destination, responsable)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT i.*, ci.designation, ci.reference, c.numero_contrat, c.fournisseur
        FROM material_issues i
        JOIN contract_items ci ON i.item_id = ci.id
        JOIN contracts c ON ci.contract_id = c.id
        WHERE i.numero_pv = ? AND i.item_id = ?
    """, (pv_number, item_id))
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else {}


def issue_materials_batch(items_list: list, date_sortie: str, motif: str,
                          destination: str, responsable: str, numero_pv: str = None) -> str:
    """Record batch material issues under a single generated PV, with strict atomic stock checks."""
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            # 1. Verification of stock for all items
            for it in items_list:
                item_id = it["item_id"]
                quantite_sortie = it["quantite_sortie"]
                
                # Conforming received
                cursor.execute("""
                    SELECT COALESCE(SUM(quantite_recue), 0) 
                    FROM material_receipts 
                    WHERE item_id = ? AND etat = 'conforme'
                """, (item_id,))
                total_received = cursor.fetchone()[0]
                
                # Issued
                cursor.execute("""
                    SELECT COALESCE(SUM(quantite_sortie), 0) 
                    FROM material_issues 
                    WHERE item_id = ?
                """, (item_id,))
                total_issued = cursor.fetchone()[0]

                # Returned
                cursor.execute("""
                    SELECT COALESCE(SUM(quantite_retournee), 0) 
                    FROM material_returns 
                    WHERE item_id = ?
                """, (item_id,))
                total_returned = cursor.fetchone()[0]
                
                available = total_received + total_returned - total_issued
                if quantite_sortie > available:
                    raise ValueError(f"Stock insuffisant pour l'article ID {item_id}. Disponible: {available}, Demandée: {quantite_sortie}")
            
            # 2. If all ok, insert issues
            now = datetime.now().isoformat()
            
            # Determine project_id from the first item
            project_id = 'general'
            if items_list:
                cursor.execute("""
                    SELECT c.project_id FROM contracts c
                    JOIN contract_items ci ON ci.contract_id = c.id
                    WHERE ci.id = ?
                """, (items_list[0]["item_id"],))
                proj_row = cursor.fetchone()
                if proj_row:
                    project_id = proj_row[0] or 'general'

            if numero_pv and numero_pv.strip():
                pv_number = numero_pv.strip()
                # Check for duplicate PV number in this project
                cursor.execute("SELECT COUNT(*) FROM pvs WHERE numero_pv = ? AND project_id = ?", (pv_number, project_id))
                if cursor.fetchone()[0] > 0:
                    raise ValueError(f"Le numéro de PV '{pv_number}' existe déjà pour ce projet.")
            else:
                pv_number = _generate_pv_number("ISSUE", cursor)
            
            for it in items_list:
                item_id = it["item_id"]
                quantite_sortie = it["quantite_sortie"]
                issue_id = str(uuid.uuid4())
                
                cursor.execute("""
                    INSERT INTO material_issues (
                        id, item_id, date_sortie, quantite_sortie, motif,
                        destination, responsable, numero_pv, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (issue_id, item_id, date_sortie, quantite_sortie, motif,
                      destination, responsable, pv_number, now))
            
            # Insert PV
            cursor.execute("""
                INSERT INTO pvs (numero_pv, type_pv, reference_id, created_at, responsables, project_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (pv_number, "ISSUE", pv_number, now, responsable, project_id))
            
            conn.commit()
            return pv_number
        except Exception as e:
            conn.rollback()
            logger.error(f"Error executing issue_materials_batch: {e}", exc_info=True)
            raise e
        finally:
            conn.close()


def return_materials_batch(items_list: list, date_retour: str, motif: str,
                           lieu_stockage: str, responsable: str, numero_pv: str = None) -> str:
    """Record batch material returns under a single generated Return PV."""
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            
            # Determine project_id from the first item
            project_id = 'general'
            if items_list:
                cursor.execute("""
                    SELECT c.project_id FROM contracts c
                    JOIN contract_items ci ON ci.contract_id = c.id
                    WHERE ci.id = ?
                """, (items_list[0]["item_id"],))
                proj_row = cursor.fetchone()
                if proj_row:
                    project_id = proj_row[0] or 'general'

            if numero_pv and numero_pv.strip():
                pv_number = numero_pv.strip()
                # Check for duplicate PV number in this project
                cursor.execute("SELECT COUNT(*) FROM pvs WHERE numero_pv = ? AND project_id = ?", (pv_number, project_id))
                if cursor.fetchone()[0] > 0:
                    raise ValueError(f"Le numéro de PV '{pv_number}' existe déjà pour ce projet.")
            else:
                pv_number = _generate_pv_number("RETURN", cursor)
            
            for it in items_list:
                item_id = it["item_id"]
                quantite_retournee = it["quantite_retournee"]
                return_id = str(uuid.uuid4())
                
                cursor.execute("""
                    INSERT INTO material_returns (
                        id, item_id, date_retour, quantite_retournee, motif,
                        responsable, numero_pv, lieu_stockage, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (return_id, item_id, date_retour, quantite_retournee, motif,
                      responsable, pv_number, lieu_stockage, now))
            
            # Insert PV
            cursor.execute("""
                INSERT INTO pvs (numero_pv, type_pv, reference_id, created_at, responsables, project_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (pv_number, "RETURN", pv_number, now, responsable, project_id))
            
            conn.commit()
            return pv_number
        except Exception as e:
            conn.rollback()
            logger.error(f"Error executing return_materials_batch: {e}", exc_info=True)
            raise e
        finally:
            conn.close()


# --- PV HISTORY & RETRIEVAL ---

def get_pvs() -> list:
    """Retrieve all PVs sorted by date, with aggregated description for batches."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM material_receipts WHERE numero_pv = p.numero_pv) as receipts_count,
               (SELECT COUNT(*) FROM material_issues WHERE numero_pv = p.numero_pv) as issues_count,
               (SELECT COUNT(*) FROM material_returns WHERE numero_pv = p.numero_pv) as returns_count
        FROM pvs p
        ORDER BY p.id DESC
    """)
    rows = cursor.fetchall()
    
    pvs_list = []
    for r in rows:
        d = dict(r)
        items_count = d["receipts_count"] or d["issues_count"] or d["returns_count"] or 0
        
        if items_count == 0:
            # Fallback for old single-item PVs
            if d["type_pv"] == "RECEIPT":
                cursor.execute("""
                    SELECT ci.designation, c.numero_contrat, r.quantite_recue as quantity
                    FROM material_receipts r
                    JOIN contract_items ci ON r.item_id = ci.id
                    JOIN contracts c ON ci.contract_id = c.id
                    WHERE r.id = ?
                """, (d["reference_id"],))
            else:
                cursor.execute("""
                    SELECT ci.designation, c.numero_contrat, i.quantite_sortie as quantity
                    FROM material_issues i
                    JOIN contract_items ci ON i.item_id = ci.id
                    JOIN contracts c ON ci.contract_id = c.id
                    WHERE i.id = ?
                """, (d["reference_id"],))
            details = cursor.fetchone()
            if details:
                d["item_designation"] = details[0]
                d["contract_number"] = details[1]
                d["quantity"] = details[2]
            else:
                d["item_designation"] = "-"
                d["contract_number"] = "-"
                d["quantity"] = 0
        else:
            # It's a batch PV
            if d["type_pv"] == "RECEIPT":
                cursor.execute("""
                    SELECT ci.designation, c.numero_contrat, SUM(r.quantite_recue)
                    FROM material_receipts r
                    JOIN contract_items ci ON r.item_id = ci.id
                    JOIN contracts c ON ci.contract_id = c.id
                    WHERE r.numero_pv = ?
                    GROUP BY c.numero_contrat
                """, (d["numero_pv"],))
            elif d["type_pv"] == "ISSUE":
                cursor.execute("""
                    SELECT ci.designation, c.numero_contrat, SUM(i.quantite_sortie)
                    FROM material_issues i
                    JOIN contract_items ci ON i.item_id = ci.id
                    JOIN contracts c ON ci.contract_id = c.id
                    WHERE i.numero_pv = ?
                    GROUP BY c.numero_contrat
                """, (d["numero_pv"],))
            else: # RETURN
                cursor.execute("""
                    SELECT ci.designation, c.numero_contrat, SUM(ret.quantite_retournee)
                    FROM material_returns ret
                    JOIN contract_items ci ON ret.item_id = ci.id
                    JOIN contracts c ON ci.contract_id = c.id
                    WHERE ret.numero_pv = ?
                    GROUP BY c.numero_contrat
                """, (d["numero_pv"],))
            
            rows_details = cursor.fetchall()
            if rows_details:
                d["contract_number"] = ", ".join(list(set(row[1] for row in rows_details)))
                d["quantity"] = sum(row[2] for row in rows_details)
                first_desig = rows_details[0][0]
                if items_count > 1:
                    d["item_designation"] = f"{first_desig} (+ {items_count - 1} autres)"
                else:
                    d["item_designation"] = first_desig
            else:
                d["item_designation"] = "-"
                d["contract_number"] = "-"
                d["quantity"] = 0
                
        pvs_list.append(d)
        
    conn.close()
    return pvs_list


def get_pv_by_number(numero_pv: str) -> dict:
    """Retrieve full details of a PV (including all batch items) by its unique number."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pvs WHERE numero_pv = ?", (numero_pv,))
    pv_row = cursor.fetchone()
    
    if not pv_row:
        conn.close()
        return None
        
    pv = dict(pv_row)
    ref_id = pv["reference_id"]
    
    if pv["type_pv"] == "RECEIPT":
        cursor.execute("""
            SELECT r.*, ci.designation, ci.reference, ci.unite, ci.prix_unitaire, c.numero_contrat, c.fournisseur, c.objet
            FROM material_receipts r
            JOIN contract_items ci ON r.item_id = ci.id
            JOIN contracts c ON ci.contract_id = c.id
            WHERE r.numero_pv = ?
        """, (numero_pv,))
        rows = cursor.fetchall()
        
        # Fallback for old single-item PVs
        if not rows:
            cursor.execute("""
                SELECT r.*, ci.designation, ci.reference, ci.unite, ci.prix_unitaire, c.numero_contrat, c.fournisseur, c.objet
                FROM material_receipts r
                JOIN contract_items ci ON r.item_id = ci.id
                JOIN contracts c ON ci.contract_id = c.id
                WHERE r.id = ?
            """, (ref_id,))
            rows = cursor.fetchall()
            
        pv["items"] = [dict(r) for r in rows]
        
    elif pv["type_pv"] == "ISSUE":
        cursor.execute("""
            SELECT i.*, ci.designation, ci.reference, ci.unite, ci.prix_unitaire, c.numero_contrat, c.fournisseur, c.objet
            FROM material_issues i
            JOIN contract_items ci ON i.item_id = ci.id
            JOIN contracts c ON ci.contract_id = c.id
            WHERE i.numero_pv = ?
        """, (numero_pv,))
        rows = cursor.fetchall()
        
        # Fallback
        if not rows:
            cursor.execute("""
                SELECT i.*, ci.designation, ci.reference, ci.unite, ci.prix_unitaire, c.numero_contrat, c.fournisseur, c.objet
                FROM material_issues i
                JOIN contract_items ci ON i.item_id = ci.id
                JOIN contracts c ON ci.contract_id = c.id
                WHERE i.id = ?
            """, (ref_id,))
            rows = cursor.fetchall()
            
        pv["items"] = [dict(r) for r in rows]
        
    else: # RETURN
        cursor.execute("""
            SELECT ret.*, ci.designation, ci.reference, ci.unite, ci.prix_unitaire, c.numero_contrat, c.fournisseur, c.objet
            FROM material_returns ret
            JOIN contract_items ci ON ret.item_id = ci.id
            JOIN contracts c ON ci.contract_id = c.id
            WHERE ret.numero_pv = ?
        """, (numero_pv,))
        rows = cursor.fetchall()
        pv["items"] = [dict(r) for r in rows]
        
    conn.close()
    return pv


def delete_pv(numero_pv: str):
    """Delete a PV and all its associated material movements (receipts, issues, returns)."""
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT type_pv, reference_id FROM pvs WHERE numero_pv = ?", (numero_pv,))
            row = cursor.fetchone()
            if not row:
                return
            type_pv = row[0]
            ref_id = row[1]
            
            if type_pv == "RECEIPT":
                cursor.execute("DELETE FROM material_receipts WHERE numero_pv = ?", (numero_pv,))
                cursor.execute("DELETE FROM material_receipts WHERE id = ?", (ref_id,))
            elif type_pv == "ISSUE":
                cursor.execute("DELETE FROM material_issues WHERE numero_pv = ?", (numero_pv,))
                cursor.execute("DELETE FROM material_issues WHERE id = ?", (ref_id,))
            elif type_pv == "RETURN":
                cursor.execute("DELETE FROM material_returns WHERE numero_pv = ?", (numero_pv,))
                cursor.execute("DELETE FROM material_returns WHERE id = ?", (ref_id,))
                
            cursor.execute("DELETE FROM pvs WHERE numero_pv = ?", (numero_pv,))
            conn.commit()
        finally:
            conn.close()


# --- DASHBOARD METRICS ---

def get_procurement_stats() -> dict:
    """Retrieve summarized statistics for the procurement dashboard."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Total contracts count
    cursor.execute("SELECT COUNT(*) FROM contracts")
    total_contracts = cursor.fetchone()[0]
    
    # 2. Total contract items value (sum of Qty * Unit Price)
    cursor.execute("SELECT COALESCE(SUM(quantite_contractuelle * prix_unitaire), 0) FROM contract_items")
    total_value = cursor.fetchone()[0]
    
    # 3. Value-based stats
    # Conforming received value
    cursor.execute("""
        SELECT COALESCE(SUM(r.quantite_recue * ci.prix_unitaire), 0)
        FROM material_receipts r
        JOIN contract_items ci ON r.item_id = ci.id
        WHERE r.etat = 'conforme'
    """)
    total_received_value = cursor.fetchone()[0]
    
    # Issued value
    cursor.execute("""
        SELECT COALESCE(SUM(i.quantite_sortie * ci.prix_unitaire), 0)
        FROM material_issues i
        JOIN contract_items ci ON i.item_id = ci.id
    """)
    total_issued_value = cursor.fetchone()[0]
    
    # Returned value
    cursor.execute("""
        SELECT COALESCE(SUM(ret.quantite_retournee * ci.prix_unitaire), 0)
        FROM material_returns ret
        JOIN contract_items ci ON ret.item_id = ci.id
    """)
    total_returned_value = cursor.fetchone()[0]
    
    # Available stock value
    total_available_value = max(0.0, total_received_value + total_returned_value - total_issued_value)
    
    # Percentages weighted by contract value
    pct_received = round((total_received_value / total_value * 100), 1) if total_value > 0 else 0.0
    pct_issued = round((total_issued_value / total_value * 100), 1) if total_value > 0 else 0.0
    pct_available = round((total_available_value / total_value * 100), 1) if total_value > 0 else 0.0
    
    # Live quantity stats
    cursor.execute("SELECT COALESCE(SUM(quantite_recue), 0) FROM material_receipts WHERE etat = 'conforme'")
    total_received_qty = cursor.fetchone()[0]
    
    cursor.execute("SELECT COALESCE(SUM(quantite_sortie), 0) FROM material_issues")
    total_issued_qty = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(quantite_retournee), 0) FROM material_returns")
    total_returned_qty = cursor.fetchone()[0]
    
    # 4. Total non-conformities count
    cursor.execute("SELECT COUNT(*) FROM material_receipts WHERE etat = 'non conforme' OR etat = 'en litige'")
    total_non_conformities = cursor.fetchone()[0]
    
    # 5. Delivery compliance % (partially or fully delivered vs total items)
    cursor.execute("SELECT COUNT(*) FROM contract_items")
    total_items = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM contract_items WHERE statut IN ('livré', 'partiellement livré')")
    delivered_items = cursor.fetchone()[0]
    
    compliance_rate = (delivered_items / total_items * 100) if total_items > 0 else 100.0
    
    # 6. Generate dynamic alerts & deviations
    deviations = []
    # Let's get all items and their aggregated metrics
    cursor.execute("""
        SELECT 
            ci.id,
            ci.designation,
            ci.reference,
            ci.quantite_contractuelle,
            ci.unite,
            c.numero_contrat,
            COALESCE((SELECT SUM(quantite_recue) FROM material_receipts WHERE item_id = ci.id AND etat = 'conforme'), 0) as total_received,
            COALESCE((SELECT SUM(quantite_sortie) FROM material_issues WHERE item_id = ci.id), 0) as total_issued,
            COALESCE((SELECT SUM(quantite_retournee) FROM material_returns WHERE item_id = ci.id), 0) as total_returned
        FROM contract_items ci
        JOIN contracts c ON ci.contract_id = c.id
    """)
    items_data = cursor.fetchall()
    
    for row in items_data:
        item = dict(row)
        designation = item["designation"]
        ref = item["reference"] or "-"
        c_num = item["numero_contrat"]
        unite = item["unite"]
        q_contract = item["quantite_contractuelle"]
        q_received = item["total_received"]
        q_issued = item["total_issued"]
        q_returned = item["total_returned"]
        
        # 1. Received vs Contract
        if q_received > q_contract:
            deviations.append({
                "type": "warning",
                "message": f"Sur-livraison : L'article '{designation}' ({ref}) du contrat {c_num} a été reçu en surplus : {q_received} {unite} reçus contre {q_contract} {unite} prévus."
            })
        elif q_received > 0 and q_received < q_contract:
            deviations.append({
                "type": "info",
                "message": f"Livraison incomplète : L'article '{designation}' ({ref}) du contrat {c_num} a été reçu à {q_received} {unite} sur {q_contract} {unite} contractuels (Manque {round(q_contract - q_received, 3)} {unite})."
            })
            
        # 2. Issued vs Received + Returned
        q_avail_before_issue = q_received + q_returned
        if q_issued > q_avail_before_issue:
            deviations.append({
                "type": "danger",
                "message": f"Alerte de stock négatif : L'article '{designation}' ({ref}) du contrat {c_num} a des sorties chantier ({q_issued} {unite}) supérieures au stock disponible entré ({q_avail_before_issue} {unite})."
            })
            
        # 3. Issued vs Contract
        if q_issued > q_contract:
            deviations.append({
                "type": "warning",
                "message": f"Écart de consommation : Les sorties pour '{designation}' ({ref}) du contrat {c_num} dépassent la quantité contractuelle ({q_issued} {unite} sortis contre {q_contract} {unite} prévus)."
            })
            
    conn.close()
    
    return {
        "total_contracts": total_contracts,
        "total_value": total_value,
        "total_received_value": total_received_value,
        "total_issued_value": total_issued_value,
        "total_returned_value": total_returned_value,
        "total_available_value": total_available_value,
        "pct_received": pct_received,
        "pct_issued": pct_issued,
        "pct_available": pct_available,
        "total_received_qty": total_received_qty,
        "total_issued_qty": total_issued_qty,
        "total_returned_qty": total_returned_qty,
        "total_available_qty": max(0.0, total_received_qty + total_returned_qty - total_issued_qty),
        "total_non_conformities": total_non_conformities,
        "compliance_rate": round(compliance_rate, 1),
        "deviations": deviations
    }


init_procurement_db()

