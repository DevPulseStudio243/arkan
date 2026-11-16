"""
DEERFLOW LITE — Local Feedback & Correction Memory (SQLite)
Allows learning from user corrections on MTO tables to auto-adjust future extractions.
"""
import sqlite3
import os
import time
import logging

logger = logging.getLogger(__name__)

DB_PATH = "feedback_memory.db"

def init_db():
    """Initializes the feedback SQLite database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS mto_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                category TEXT NOT NULL,
                tag TEXT,
                size TEXT,
                material TEXT,
                quantity REAL,
                unit TEXT,
                corrected_at REAL NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        logger.info("[Feedback Memory] Database initialized at %s", DB_PATH)
    except Exception as e:
        logger.error("[Feedback Memory] Failed to initialize database: %s", e)

def save_feedback(filename: str, category: str, tag: str, size: str, material: str, quantity: float, unit: str):
    """Saves a user MTO line correction to database."""
    try:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Check if identical correction already exists to avoid duplication
        c.execute("""
            SELECT id FROM mto_feedback 
            WHERE filename = ? AND category = ? AND tag = ? AND size = ? AND material = ? AND unit = ?
        """, (filename, category, tag or "", size or "", material or "", unit or ""))
        row = c.fetchone()
        
        if row:
            # Update quantity
            c.execute("""
                UPDATE mto_feedback 
                SET quantity = ?, corrected_at = ? 
                WHERE id = ?
            """, (quantity, time.time(), row[0]))
        else:
            # Insert new record
            c.execute("""
                INSERT INTO mto_feedback (filename, category, tag, size, material, quantity, unit, corrected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (filename, category, tag or "", size or "", material or "", quantity, unit or "", time.time()))
            
        conn.commit()
        conn.close()
        logger.info("[Feedback Memory] Saved correction for %s - %s: qty=%s", filename, category, quantity)
    except Exception as e:
        logger.error("[Feedback Memory] Error saving feedback: %s", e)

def get_feedback_for_file(filename: str):
    """Retrieves all historical corrections saved for a file."""
    try:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT category, tag, size, material, quantity, unit 
            FROM mto_feedback 
            WHERE filename = ?
            ORDER BY corrected_at DESC
        """, (filename,))
        rows = c.fetchall()
        conn.close()
        
        return [
            {
                "category": r[0],
                "tag": r[1],
                "size": r[2],
                "material": r[3],
                "quantity": r[4],
                "unit": r[5]
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("[Feedback Memory] Error reading feedback: %s", e)
        return []

def get_learned_adjustments(filename: str):
    """
    Analyzes historical corrections to build correction templates for recurring layouts.
    Returns a dict of corrections to apply as adjustment boosts.
    """
    feedback = get_feedback_for_file(filename)
    adjustments = {}
    for item in feedback:
        # Key on category and size/tag
        key = (item["category"], item["tag"], item["size"])
        adjustments[key] = item["quantity"]
    return adjustments

# Initialize on import
init_db()
