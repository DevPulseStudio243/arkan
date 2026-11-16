import os
import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

VERIFICATION_DB_PATH = Path("d:/DATA BASE IA/data/verification.db")
VERIFICATION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_db_connection():
    """Create a thread-safe connection to the SQLite database."""
    conn = sqlite3.connect(str(VERIFICATION_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_verification_db():
    """Initialize the SQLite schema for the Verification Engine."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. Table for extracted equipment attributes
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipment_attributes (
            project_id TEXT,
            tag TEXT,
            document TEXT,
            attribute_name TEXT,
            attribute_value TEXT,
            unit TEXT,
            confidence REAL,
            timestamp TEXT,
            PRIMARY KEY (project_id, tag, document, attribute_name)
        )
        """)

        # 2. Table for verification anomalies/results
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS verification_results (
            result_id TEXT PRIMARY KEY,
            project_id TEXT,
            tag TEXT,
            rule_id TEXT,
            severity TEXT,
            description TEXT,
            doc_source_a TEXT,
            value_a TEXT,
            doc_source_b TEXT,
            value_b TEXT,
            status TEXT, -- pending_expert | corrected | ignored
            expert_comment TEXT,
            timestamp TEXT
        )
        """)

        # 3. Table for exceptions learned from human decisions
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS verified_exceptions (
            exception_id TEXT PRIMARY KEY,
            project_id TEXT,
            tag TEXT,
            rule_id TEXT,
            condition_scope TEXT, -- JSON string representing custom exception conditions
            justification TEXT,
            approved_by TEXT,
            timestamp TEXT
        )
        """)

        # 4. Table for tracking processed documents (to prevent rescanning unchanged files)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_documents (
            project_id TEXT,
            filename TEXT,
            file_path TEXT UNIQUE,
            file_size INTEGER,
            last_modified TEXT,
            file_hash TEXT,
            scan_timestamp TEXT,
            PRIMARY KEY (project_id, filename)
        )
        """)

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attr_project ON equipment_attributes(project_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attr_tag ON equipment_attributes(tag)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_project ON verification_results(project_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_tag ON verification_results(tag)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_exc_project ON verified_exceptions(project_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_exc_tag ON verified_exceptions(tag)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_proc_docs_project ON processed_documents(project_id)")

        conn.commit()
        conn.close()
        logger.info("Verification database initialized successfully.")
    except Exception as e:
        logger.error("Failed to initialize verification database: %s", e)
        raise


def save_attributes(attributes: list[dict]):
    """Insert or replace attributes in bulk."""
    if not attributes:
        return
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        
        data = [
            (
                a.get("project_id", "general"),
                a["tag"].upper().strip(),
                a["document"],
                a["attribute_name"],
                str(a["attribute_value"]),
                a.get("unit", ""),
                a.get("confidence", 1.0),
                now
            )
            for a in attributes
        ]
        
        cursor.executemany("""
        INSERT OR REPLACE INTO equipment_attributes 
        (project_id, tag, document, attribute_name, attribute_value, unit, confidence, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, data)
        conn.commit()
        conn.close()
        logger.info("Saved %d attributes to SQLite", len(attributes))
    except Exception as e:
        logger.error("Failed to save attributes: %s", e)
        raise


def save_verification_results(project_id: str, results: list[dict]):
    """Clear previous results for the project and save the new list of anomalies."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Keep status and comments of existing anomalies to prevent overwriting expert inputs
        cursor.execute("SELECT result_id, status, expert_comment FROM verification_results WHERE project_id = ?", (project_id,))
        existing_states = {row["result_id"]: (row["status"], row["expert_comment"]) for row in cursor.fetchall()}
        
        # Clear previous anomalies for this project
        cursor.execute("DELETE FROM verification_results WHERE project_id = ?", (project_id,))
        
        now = datetime.utcnow().isoformat()
        
        data = []
        seen_rids = set()
        for r in results:
            rid = r["result_id"]
            if rid in seen_rids:
                continue
            seen_rids.add(rid)
            
            # Restore state if existed
            status = existing_states.get(rid, ("pending_expert", ""))[0]
            comment = existing_states.get(rid, ("pending_expert", ""))[1]
            
            data.append((
                rid,
                project_id,
                r["tag"].upper().strip(),
                r["rule_id"],
                r["severity"],
                r["description"],
                r.get("doc_source_a", ""),
                str(r.get("value_a", "")),
                r.get("doc_source_b", ""),
                str(r.get("value_b", "")),
                status,
                comment,
                now
            ))
            
        cursor.executemany("""
        INSERT OR REPLACE INTO verification_results 
        (result_id, project_id, tag, rule_id, severity, description, doc_source_a, value_a, doc_source_b, value_b, status, expert_comment, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, data)
        
        conn.commit()
        conn.close()
        logger.info("Saved %d verification results for project %s", len(seen_rids), project_id)
    except Exception as e:
        logger.error("Failed to save verification results: %s", e)
        raise


def resolve_anomaly(result_id: str, status: str, comment: str) -> bool:
    """Update status and comments for an anomaly."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE verification_results 
        SET status = ?, expert_comment = ?
        WHERE result_id = ?
        """, (status, comment, result_id))
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        return rows_affected > 0
    except Exception as e:
        logger.error("Failed to resolve anomaly %s: %s", result_id, e)
        return False


def get_project_anomalies(project_id: str) -> list[dict]:
    """Retrieve all anomalies for a given project."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT * FROM verification_results 
        WHERE project_id = ? 
        ORDER BY CASE severity WHEN 'BLOQUANT' THEN 1 WHEN 'MAJEUR' THEN 2 WHEN 'MINEUR' THEN 3 END
        """, (project_id,))
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        logger.error("Failed to get anomalies for project %s: %s", project_id, e)
        return []


def get_project_attributes(project_id: str) -> list[dict]:
    """Retrieve all attributes for a given project."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM equipment_attributes WHERE project_id = ?", (project_id,))
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        logger.error("Failed to get attributes for project %s: %s", project_id, e)
        return []


def add_exception(project_id: str, tag: str, rule_id: str, justification: str, condition_scope: dict = None, approved_by: str = "Expert") -> str:
    """Learn an exception to suppress subsequent rules violations."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        import uuid
        exception_id = uuid.uuid4().hex[:12]
        now = datetime.utcnow().isoformat()
        scope = json.dumps(condition_scope or {})
        
        cursor.execute("""
        INSERT INTO verified_exceptions 
        (exception_id, project_id, tag, rule_id, condition_scope, justification, approved_by, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (exception_id, project_id, tag.upper().strip() if tag else None, rule_id, scope, justification, approved_by, now))
        
        conn.commit()
        conn.close()
        logger.info("Learned exception %s for tag %s (rule %s)", exception_id, tag, rule_id)
        return exception_id
    except Exception as e:
        logger.error("Failed to add exception: %s", e)
        raise


def get_exceptions(project_id: str) -> list[dict]:
    """Get exceptions for a project."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM verified_exceptions WHERE project_id = ?", (project_id,))
        rows = [dict(r) for r in cursor.fetchall()]
        for r in rows:
            r["condition_scope"] = json.loads(r["condition_scope"] or "{}")
        conn.close()
        return rows
    except Exception as e:
        logger.error("Failed to get exceptions: %s", e)
        return []


def get_processed_documents_metadata(project_id: str) -> dict:
    """Retrieve metadata of all processed documents for a project.
    Returns:
        dict: {file_path: {"filename": filename, "file_size": file_size, "last_modified": last_modified, "file_hash": file_hash}}
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT file_path, filename, file_size, last_modified, file_hash 
        FROM processed_documents 
        WHERE project_id = ?
        """, (project_id,))
        rows = cursor.fetchall()
        conn.close()
        
        result = {}
        for r in rows:
            result[r["file_path"]] = {
                "filename": r["filename"],
                "file_size": r["file_size"],
                "last_modified": r["last_modified"],
                "file_hash": r["file_hash"]
            }
        return result
    except Exception as e:
        logger.error("Failed to get processed documents metadata for project %s: %s", project_id, e)
        return {}


def save_processed_document(project_id: str, filename: str, file_path: str, file_size: int, last_modified: str, file_hash: str):
    """Save or update tracking metadata for a processed document."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
        INSERT OR REPLACE INTO processed_documents 
        (project_id, filename, file_path, file_size, last_modified, file_hash, scan_timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (project_id, filename, file_path, file_size, last_modified, file_hash, now))
        conn.commit()
        conn.close()
        logger.info("Saved tracking metadata for document %s (project %s)", filename, project_id)
    except Exception as e:
        logger.error("Failed to save processed document tracking for %s: %s", filename, e)
        raise


def delete_processed_document(project_id: str, file_path: str):
    """Delete tracking metadata for a document."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        DELETE FROM processed_documents 
        WHERE project_id = ? AND file_path = ?
        """, (project_id, file_path))
        conn.commit()
        conn.close()
        logger.info("Deleted tracking metadata for file path %s (project %s)", file_path, project_id)
    except Exception as e:
        logger.error("Failed to delete processed document tracking for %s: %s", file_path, e)
        raise


def clear_document_attributes(project_id: str, document: str):
    """Delete all extracted equipment attributes for a specific document."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        DELETE FROM equipment_attributes 
        WHERE project_id = ? AND document = ?
        """, (project_id, document))
        conn.commit()
        conn.close()
        logger.info("Cleared all attributes for document %s (project %s)", document, project_id)
    except Exception as e:
        logger.error("Failed to clear document attributes for %s: %s", document, e)
        raise


# Initialize database automatically when imported
init_verification_db()
