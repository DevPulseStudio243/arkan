import os
import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

# Base path for SQLite database
TRACEABILITY_DB_PATH = Path("d:/DATA BASE IA/data/traceability.db")
TRACEABILITY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_db_connection():
    """Create a thread-safe connection to the SQLite database."""
    conn = sqlite3.connect(str(TRACEABILITY_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_traceability_db():
    """Initialize the SQLite schema for the Material Traceability & Isometrics Module."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. Table for Isometric Drawings
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS isometrics (
            id TEXT PRIMARY KEY,
            line_number TEXT UNIQUE,
            revision TEXT,
            title TEXT,
            project_id TEXT,
            status TEXT,
            file_path TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """)

        # 2. Table for Bill of Materials (BOM) items
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bom_items (
            id TEXT PRIMARY KEY,
            iso_id TEXT,
            category TEXT,
            tag TEXT,
            description TEXT,
            size TEXT,
            material TEXT,
            quantity REAL,
            unit TEXT,
            weight_unit REAL,
            weight_total REAL,
            remarks TEXT,
            heat_number TEXT,
            spool_number TEXT,
            status TEXT,
            FOREIGN KEY (iso_id) REFERENCES isometrics (id) ON DELETE CASCADE
        )
        """)

        # 3. Table for Material Certificates / Heat Numbers (MTC/MTR)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS heat_numbers (
            heat_number TEXT PRIMARY KEY,
            material_spec TEXT,
            diameter TEXT,
            manufacturer TEXT,
            mtr_file_path TEXT,
            chemical_composition TEXT, -- JSON string
            mechanical_properties TEXT, -- JSON string
            inspector TEXT,
            status TEXT,
            created_at TEXT
        )
        """)

        # 4. Table for Welds (Welding log)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS welds (
            id TEXT PRIMARY KEY,
            iso_id TEXT,
            weld_number TEXT,
            type TEXT,
            size TEXT,
            schedule TEXT,
            welder_id TEXT,
            weld_date TEXT,
            fitup_status TEXT,
            fitup_date TEXT,
            visual_status TEXT,
            visual_date TEXT,
            ndt_type TEXT,
            ndt_status TEXT,
            ndt_date TEXT,
            heat_number_1 TEXT,
            heat_number_2 TEXT,
            status TEXT,
            FOREIGN KEY (iso_id) REFERENCES isometrics (id) ON DELETE CASCADE
        )
        """)

        # 5. Table for Spools (Spool tracker)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS spools (
            id TEXT PRIMARY KEY,
            iso_id TEXT,
            spool_number TEXT,
            shop_field TEXT,
            fabricator TEXT,
            fitup_date TEXT,
            welding_date TEXT,
            ndt_date TEXT,
            painting_date TEXT,
            status TEXT,
            FOREIGN KEY (iso_id) REFERENCES isometrics (id) ON DELETE CASCADE
        )
        """)

        conn.commit()
        conn.close()
        logger.info("[Traceability DB] Database initialized successfully.")
        return True
    except Exception as e:
        logger.error("[Traceability DB] Error initializing database: %s", e)
        return False


# ============================================================
#  Isometrics and BOM items queries
# ============================================================

def add_isometric(line_number, revision="0", title="", project_id="Boosting LDBP5", file_path="", status="Draft"):
    """Insert or update an isometric drawing line."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        # Check if line_number already exists
        cursor.execute("SELECT id FROM isometrics WHERE line_number = ?", (line_number,))
        row = cursor.fetchone()
        
        if row:
            iso_id = row["id"]
            cursor.execute("""
            UPDATE isometrics
            SET revision = ?, title = ?, project_id = ?, status = ?, file_path = ?, updated_at = ?
            WHERE id = ?
            """, (revision, title, project_id, status, file_path, now, iso_id))
        else:
            iso_id = str(uuid.uuid4())
            cursor.execute("""
            INSERT INTO isometrics (id, line_number, revision, title, project_id, status, file_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (iso_id, line_number, revision, title, project_id, status, file_path, now, now))
            
        conn.commit()
        conn.close()
        return iso_id
    except Exception as e:
        logger.error("[Traceability DB] Error adding isometric: %s", e)
        return None


def add_bom_item(iso_id, category, tag, description, size, material, quantity, unit="U", weight_unit=0.0, weight_total=0.0, remarks="", heat_number="", spool_number="", status="Pending"):
    """Insert a new Bill of Material item."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        item_id = str(uuid.uuid4())
        
        cursor.execute("""
        INSERT INTO bom_items (id, iso_id, category, tag, description, size, material, quantity, unit, weight_unit, weight_total, remarks, heat_number, spool_number, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (item_id, iso_id, category, tag, description, size, material, quantity, unit, weight_unit, weight_total, remarks, heat_number, spool_number, status))
        
        conn.commit()
        conn.close()
        return item_id
    except Exception as e:
        logger.error("[Traceability DB] Error adding BOM item: %s", e)
        return None


def clear_isometric_bom(iso_id):
    """Clear all BOM items associated with an isometric."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bom_items WHERE iso_id = ?", (iso_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error("[Traceability DB] Error clearing BOM: %s", e)
        return False


def get_isometrics_list(project_id=None):
    """Get list of all isometrics, optionally filtered by project_id."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if project_id:
            cursor.execute("SELECT * FROM isometrics WHERE project_id = ? ORDER BY line_number", (project_id,))
        else:
            cursor.execute("SELECT * FROM isometrics ORDER BY line_number")
        rows = cursor.fetchall()
        
        # Format as list of dicts with extra count statistics
        iso_list = []
        for r in rows:
            iso_dict = dict(r)
            # Add stats
            cursor.execute("SELECT COUNT(*) as total, SUM(CASE WHEN heat_number IS NOT NULL AND heat_number != '' THEN 1 ELSE 0 END) as allocated FROM bom_items WHERE iso_id = ?", (iso_dict["id"],))
            stats = cursor.fetchone()
            iso_dict["bom_total_items"] = stats["total"]
            iso_dict["bom_allocated_items"] = stats["allocated"] or 0
            
            cursor.execute("SELECT COUNT(*) as total, SUM(CASE WHEN ndt_status = 'Accepted' THEN 1 ELSE 0 END) as approved FROM welds WHERE iso_id = ?", (iso_dict["id"],))
            w_stats = cursor.fetchone()
            iso_dict["welds_total"] = w_stats["total"]
            iso_dict["welds_approved"] = w_stats["approved"] or 0
            
            iso_list.append(iso_dict)
            
        conn.close()
        return iso_list
    except Exception as e:
        logger.error("[Traceability DB] Error getting isometrics: %s", e)
        return []


def get_isometric_details(iso_id):
    """Get detailed fields of an isometric drawing by ID."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM isometrics WHERE id = ?", (iso_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        logger.error("[Traceability DB] Error getting isometric details: %s", e)
        return None


def get_bom_items(iso_id):
    """Get BOM items of an isometric drawing."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bom_items WHERE iso_id = ?", (iso_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("[Traceability DB] Error getting BOM items: %s", e)
        return []


# ============================================================
#  Heat Numbers / Materials queries
# ============================================================

def add_heat_number(heat_number, material_spec="", diameter="", manufacturer="", mtr_file_path="", chemical_composition=None, mechanical_properties=None, inspector="", status="Accepted"):
    """Insert or update a material Heat Number certificate."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        chem_json = json.dumps(chemical_composition) if chemical_composition else "{}"
        mech_json = json.dumps(mechanical_properties) if mechanical_properties else "{}"
        
        cursor.execute("SELECT heat_number FROM heat_numbers WHERE heat_number = ?", (heat_number,))
        row = cursor.fetchone()
        
        if row:
            cursor.execute("""
            UPDATE heat_numbers
            SET material_spec = ?, diameter = ?, manufacturer = ?, mtr_file_path = ?, chemical_composition = ?, mechanical_properties = ?, inspector = ?, status = ?
            WHERE heat_number = ?
            """, (material_spec, diameter, manufacturer, mtr_file_path, chem_json, mech_json, inspector, status, heat_number))
        else:
            cursor.execute("""
            INSERT INTO heat_numbers (heat_number, material_spec, diameter, manufacturer, mtr_file_path, chemical_composition, mechanical_properties, inspector, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (heat_number, material_spec, diameter, manufacturer, mtr_file_path, chem_json, mech_json, inspector, status, now))
            
        conn.commit()
        conn.close()
        return heat_number
    except Exception as e:
        logger.error("[Traceability DB] Error adding heat number: %s", e)
        return None


def get_heat_numbers_list():
    """Get list of all Heat Numbers."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM heat_numbers ORDER BY heat_number")
        rows = cursor.fetchall()
        
        heat_list = []
        for r in rows:
            h_dict = dict(r)
            h_dict["chemical_composition"] = json.loads(h_dict["chemical_composition"] or "{}")
            h_dict["mechanical_properties"] = json.loads(h_dict["mechanical_properties"] or "{}")
            
            # Count allocations
            cursor.execute("SELECT COUNT(*) as count FROM bom_items WHERE heat_number = ?", (h_dict["heat_number"],))
            alloc_bom = cursor.fetchone()["count"]
            cursor.execute("SELECT COUNT(*) as count FROM welds WHERE heat_number_1 = ? OR heat_number_2 = ?", (h_dict["heat_number"], h_dict["heat_number"]))
            alloc_welds = cursor.fetchone()["count"]
            
            h_dict["allocations_count"] = alloc_bom + alloc_welds
            heat_list.append(h_dict)
            
        conn.close()
        return heat_list
    except Exception as e:
        logger.error("[Traceability DB] Error getting heat numbers: %s", e)
        return []


def allocate_heat_number_to_bom(bom_item_id, heat_number):
    """Allocate a Heat Number to a specific BOM item."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        status = "Matched" if heat_number else "Pending"
        cursor.execute("""
        UPDATE bom_items
        SET heat_number = ?, status = ?
        WHERE id = ?
        """, (heat_number, status, bom_item_id))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error("[Traceability DB] Error allocating heat number to BOM: %s", e)
        return False


# ============================================================
#  Welds queries
# ============================================================

def add_weld(iso_id, weld_number, weld_type="Butt", size="", schedule="", welder_id="", weld_date="", fitup_status="Pending", fitup_date="", visual_status="Pending", visual_date="", ndt_type="RT", ndt_status="Pending", ndt_date="", heat_number_1="", heat_number_2="", status="Pending"):
    """Insert or update a weld log."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if weld exists on this isometric
        cursor.execute("SELECT id FROM welds WHERE iso_id = ? AND weld_number = ?", (iso_id, weld_number))
        row = cursor.fetchone()
        
        if row:
            weld_id = row["id"]
            cursor.execute("""
            UPDATE welds
            SET type = ?, size = ?, schedule = ?, welder_id = ?, weld_date = ?, fitup_status = ?, fitup_date = ?, visual_status = ?, visual_date = ?, ndt_type = ?, ndt_status = ?, ndt_date = ?, heat_number_1 = ?, heat_number_2 = ?, status = ?
            WHERE id = ?
            """, (weld_type, size, schedule, welder_id, weld_date, fitup_status, fitup_date, visual_status, visual_date, ndt_type, ndt_status, ndt_date, heat_number_1, heat_number_2, status, weld_id))
        else:
            weld_id = str(uuid.uuid4())
            cursor.execute("""
            INSERT INTO welds (id, iso_id, weld_number, type, size, schedule, welder_id, weld_date, fitup_status, fitup_date, visual_status, visual_date, ndt_type, ndt_status, ndt_date, heat_number_1, heat_number_2, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (weld_id, iso_id, weld_number, weld_type, size, schedule, welder_id, weld_date, fitup_status, fitup_date, visual_status, visual_date, ndt_type, ndt_status, ndt_date, heat_number_1, heat_number_2, status))
            
        conn.commit()
        conn.close()
        return weld_id
    except Exception as e:
        logger.error("[Traceability DB] Error adding weld: %s", e)
        return None


def get_welds_list(iso_id=None):
    """Get list of welds, optionally filtered by iso_id."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if iso_id:
            cursor.execute("""
            SELECT w.*, i.line_number 
            FROM welds w
            JOIN isometrics i ON w.iso_id = i.id
            WHERE w.iso_id = ?
            ORDER BY w.weld_number
            """, (iso_id,))
        else:
            cursor.execute("""
            SELECT w.*, i.line_number 
            FROM welds w
            JOIN isometrics i ON w.iso_id = i.id
            ORDER BY i.line_number, w.weld_number
            """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("[Traceability DB] Error getting welds: %s", e)
        return []


# ============================================================
#  Spools queries
# ============================================================

def add_spool(iso_id, spool_number, shop_field="Shop", fabricator="", fitup_date="", welding_date="", ndt_date="", painting_date="", status="Design"):
    """Insert or update a spool tracking status."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM spools WHERE iso_id = ? AND spool_number = ?", (iso_id, spool_number))
        row = cursor.fetchone()
        
        if row:
            spool_id = row["id"]
            cursor.execute("""
            UPDATE spools
            SET shop_field = ?, fabricator = ?, fitup_date = ?, welding_date = ?, ndt_date = ?, painting_date = ?, status = ?
            WHERE id = ?
            """, (shop_field, fabricator, fitup_date, welding_date, ndt_date, painting_date, status, spool_id))
        else:
            spool_id = str(uuid.uuid4())
            cursor.execute("""
            INSERT INTO spools (id, iso_id, spool_number, shop_field, fabricator, fitup_date, welding_date, ndt_date, painting_date, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (spool_id, iso_id, spool_number, shop_field, fabricator, fitup_date, welding_date, ndt_date, painting_date, status))
            
        conn.commit()
        conn.close()
        return spool_id
    except Exception as e:
        logger.error("[Traceability DB] Error adding spool: %s", e)
        return None


def get_spools_list(iso_id=None):
    """Get list of spools, optionally filtered by iso_id."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if iso_id:
            cursor.execute("""
            SELECT s.*, i.line_number 
            FROM spools s
            JOIN isometrics i ON s.iso_id = i.id
            WHERE s.iso_id = ?
            ORDER BY s.spool_number
            """, (iso_id,))
        else:
            cursor.execute("""
            SELECT s.*, i.line_number 
            FROM spools s
            JOIN isometrics i ON s.iso_id = i.id
            ORDER BY i.line_number, s.spool_number
            """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("[Traceability DB] Error getting spools: %s", e)
        return []


# ============================================================
#  Dashboard & Traceability Report
# ============================================================

def get_traceability_kpi():
    """Get summary statistics (KPIs) for the traceability dashboard."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Isometrics counts
        cursor.execute("SELECT COUNT(*) FROM isometrics")
        total_isos = cursor.fetchone()[0]
        
        # 2. BOM Items statistics
        cursor.execute("SELECT COUNT(*) FROM bom_items")
        total_bom_items = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM bom_items WHERE heat_number IS NOT NULL AND heat_number != ''")
        allocated_bom_items = cursor.fetchone()[0]
        
        # 3. Heat numbers counts
        cursor.execute("SELECT COUNT(*) FROM heat_numbers")
        total_heats = cursor.fetchone()[0]
        
        # 4. Welds statistics
        cursor.execute("SELECT COUNT(*) FROM welds")
        total_welds = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM welds WHERE status = 'Approved' OR ndt_status = 'Accepted'")
        approved_welds = cursor.fetchone()[0]
        
        # 5. Spools statistics
        cursor.execute("SELECT COUNT(*) FROM spools")
        total_spools = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM spools WHERE status = 'Completed' OR status = 'Installed'")
        completed_spools = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "total_isometrics": total_isos,
            "total_bom_items": total_bom_items,
            "allocated_bom_items": allocated_bom_items,
            "allocation_rate": round((allocated_bom_items / total_bom_items * 100), 1) if total_bom_items > 0 else 0.0,
            "total_heat_numbers": total_heats,
            "total_welds": total_welds,
            "approved_welds": approved_welds,
            "weld_acceptance_rate": round((approved_welds / total_welds * 100), 1) if total_welds > 0 else 0.0,
            "total_spools": total_spools,
            "completed_spools": completed_spools,
            "spool_progress": round((completed_spools / total_spools * 100), 1) if total_spools > 0 else 0.0,
        }
    except Exception as e:
        logger.error("[Traceability DB] Error getting traceability KPI: %s", e)
        return {
            "total_isometrics": 0,
            "total_bom_items": 0,
            "allocated_bom_items": 0,
            "allocation_rate": 0.0,
            "total_heat_numbers": 0,
            "total_welds": 0,
            "approved_welds": 0,
            "weld_acceptance_rate": 0.0,
            "total_spools": 0,
            "completed_spools": 0,
            "spool_progress": 0.0,
        }
