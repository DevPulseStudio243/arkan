# ============================================================
#  DEERFLOW LITE - ChromaDB Schema Fix Script
#  Fixes "no such column: collections.topic / segments.topic"
#  Run with: python fix_chromadb.py
# ============================================================

import os
import sys
import sqlite3
import shutil
from datetime import datetime

# --- Configuration ---
CHROMA_DIR = os.environ.get("CHROMA_PERSIST_DIR", "./chroma_db")
SQLITE_PATH = os.path.join(CHROMA_DIR, "chroma.sqlite3")


def find_sqlite_db():
    """Locate the ChromaDB SQLite file."""
    if os.path.exists(SQLITE_PATH):
        return SQLITE_PATH
    # Search common locations
    for candidate in [
        os.path.join(CHROMA_DIR, "chroma.sqlite3"),
        os.path.join(".", "chroma.sqlite3"),
    ]:
        if os.path.exists(candidate):
            return candidate
    return None


def backup_db(db_path):
    """Create a timestamped backup before modifying."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"{db_path}.backup_{ts}"
    shutil.copy2(db_path, backup)
    print(f"[OK] Backup created: {backup}")
    return backup


def get_table_columns(cursor, table_name):
    """Get list of column names for a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cursor.fetchall()]


def get_all_tables(cursor):
    """Get all table names in the database."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [row[0] for row in cursor.fetchall()]


def diagnose(db_path):
    """Diagnose the ChromaDB schema and report issues."""
    print(f"\n{'='*60}")
    print(f"  ChromaDB Schema Diagnostic")
    print(f"  Database: {db_path}")
    print(f"{'='*60}\n")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    tables = get_all_tables(cursor)
    print(f"Tables found: {', '.join(tables)}\n")

    # Known tables that may need 'topic' column
    tables_needing_topic = ["collections", "segments"]
    issues = []

    for table in tables_needing_topic:
        if table not in tables:
            print(f"[SKIP] Table '{table}' does not exist")
            continue

        columns = get_table_columns(cursor, table)
        print(f"[INFO] Table '{table}' columns: {', '.join(columns)}")

        if "topic" not in columns:
            issues.append(table)
            print(f"[ISSUE] Table '{table}' is MISSING 'topic' column")
        else:
            print(f"[OK] Table '{table}' has 'topic' column")

    # Check record counts
    print()
    for table in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"[INFO] Table '{table}': {count} rows")
        except Exception as e:
            print(f"[ERROR] Cannot count '{table}': {e}")

    conn.close()
    return issues


def fix_schema(db_path, issues):
    """Add missing 'topic' columns to tables that need them."""
    if not issues:
        print("\n[OK] No schema issues to fix!")
        return True

    print(f"\n--- Fixing {len(issues)} table(s) ---")
    backup_db(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    for table in issues:
        try:
            # Add 'topic' column with empty string default
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN topic TEXT DEFAULT ''")
            print(f"[FIXED] Added 'topic' column to '{table}'")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print(f"[OK] Column 'topic' already exists in '{table}'")
            else:
                print(f"[ERROR] Failed to fix '{table}': {e}")
                conn.close()
                return False

    conn.commit()
    conn.close()
    print("\n[OK] Schema fixes applied successfully!")
    return True


def verify_fix(db_path):
    """Verify that the fix was applied correctly."""
    print(f"\n--- Verification ---")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    tables_to_check = ["collections", "segments"]
    all_ok = True

    for table in tables_to_check:
        tables = get_all_tables(cursor)
        if table not in tables:
            continue

        columns = get_table_columns(cursor, table)
        if "topic" in columns:
            print(f"[OK] '{table}.topic' column present")
        else:
            print(f"[FAIL] '{table}.topic' still missing!")
            all_ok = False

    # Try a basic query that ChromaDB would run
    try:
        cursor.execute("SELECT id, name, topic FROM collections LIMIT 1")
        row = cursor.fetchone()
        if row:
            print(f"[OK] Test query on collections succeeded: id={row[0]}, name={row[1]}")
        else:
            print(f"[OK] Test query on collections succeeded (empty table)")
    except Exception as e:
        print(f"[FAIL] Test query failed: {e}")
        all_ok = False

    try:
        cursor.execute("SELECT id, topic FROM segments LIMIT 1")
        row = cursor.fetchone()
        if row:
            print(f"[OK] Test query on segments succeeded")
        else:
            print(f"[OK] Test query on segments succeeded (empty table)")
    except Exception as e:
        print(f"[FAIL] Test query on segments failed: {e}")
        all_ok = False

    conn.close()
    return all_ok


def option_rebuild():
    """Option B: Delete chroma_db and let the system rebuild from scratch."""
    if not os.path.exists(CHROMA_DIR):
        print(f"[INFO] Directory '{CHROMA_DIR}' does not exist, nothing to delete")
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = f"{CHROMA_DIR}_backup_{ts}"
    shutil.move(CHROMA_DIR, backup_dir)
    print(f"[OK] Moved '{CHROMA_DIR}' to '{backup_dir}'")
    print(f"[INFO] ChromaDB will be rebuilt on next startup.")
    print(f"[INFO] You will need to re-index all documents (run training cycle).")


def main():
    print("=" * 60)
    print("  DEERFLOW LITE - ChromaDB Fix Tool")
    print("=" * 60)

    # Check Python version
    print(f"\nPython: {sys.version}")
    try:
        import chromadb
        print(f"ChromaDB: {chromadb.__version__}")
    except ImportError:
        print("[ERROR] ChromaDB is not installed in this Python environment!")
        print("Install it with: pip install chromadb")
        sys.exit(1)
    except Exception as e:
        print(f"[WARN] Cannot determine ChromaDB version: {e}")

    db_path = find_sqlite_db()
    if not db_path:
        print(f"\n[INFO] No ChromaDB SQLite database found at '{SQLITE_PATH}'")
        print("[INFO] This is normal if the database hasn't been created yet.")
        print("[INFO] Start the server and run a training cycle to create it.")
        sys.exit(0)

    # Step 1: Diagnose
    issues = diagnose(db_path)

    if not issues:
        print("\n[OK] No schema issues detected. ChromaDB should work correctly.")
        print("\nIf you still have errors, try Option B (rebuild):")
        print(f"  python {sys.argv[0]} --rebuild")
        sys.exit(0)

    # Step 2: Check command line args
    if "--rebuild" in sys.argv:
        print("\n--- Option B: Full Rebuild ---")
        option_rebuild()
        sys.exit(0)

    # Step 3: Fix schema (Option A)
    print("\n--- Option A: Schema Migration ---")
    success = fix_schema(db_path, issues)

    if success:
        all_ok = verify_fix(db_path)
        if all_ok:
            print("\n" + "=" * 60)
            print("  FIX SUCCESSFUL!")
            print("  Restart your Deerflow Lite server to apply changes.")
            print("=" * 60)
        else:
            print("\n[WARN] Some verification checks failed.")
            print("Try Option B (full rebuild) instead:")
            print(f"  python {sys.argv[0]} --rebuild")
    else:
        print("\n[ERROR] Schema fix failed. Try Option B (full rebuild):")
        print(f"  python {sys.argv[0]} --rebuild")
        sys.exit(1)


if __name__ == "__main__":
    main()
