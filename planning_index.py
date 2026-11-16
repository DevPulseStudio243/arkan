"""
DEERFLOW LITE — Planning Index (SQLite)
Stores and retrieves indexed XER planning results for comparison between versions.
"""
import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
DB_PATH = Path(__file__).parent / "planning_index.db"

def _get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create tables if they do not exist."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS planning_versions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id   TEXT NOT NULL,
                project_name TEXT NOT NULL,
                filename     TEXT NOT NULL,
                imported_at  TEXT NOT NULL,
                stats_json   TEXT NOT NULL,
                health_json  TEXT NOT NULL,
                tasks_json   TEXT NOT NULL,
                label        TEXT DEFAULT ""
            )
        """)
        conn.commit()

def save_planning(project_id: str, project_name: str, filename: str, data: dict, label: str = "") -> int:
    """Save a planning analysis result. Returns the new version ID."""
    init_db()
    with _get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO planning_versions
               (project_id, project_name, filename, imported_at, stats_json, health_json, tasks_json, label)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id,
                project_name,
                filename,
                datetime.now().isoformat(),
                json.dumps(data.get("stats", {})),
                json.dumps(data.get("healthCheck", [])),
                json.dumps(data.get("ganttTasks", data.get("tasks", []))[:10000]),
                label,
            )
        )
        conn.commit()
        return cur.lastrowid

def list_versions(project_id: str) -> list:
    """Return all indexed versions for a given project_id, newest first."""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT id, project_id, project_name, filename, imported_at, label
               FROM planning_versions WHERE project_id = ?
               ORDER BY imported_at DESC""",
            (project_id,)
        ).fetchall()
    return [dict(r) for r in rows]

def list_all_versions() -> list:
    """Return all indexed versions (all projects), newest first."""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT id, project_id, project_name, filename, imported_at, label
               FROM planning_versions ORDER BY imported_at DESC LIMIT 100"""
        ).fetchall()
    return [dict(r) for r in rows]

def get_version(version_id: int) -> dict:
    """Return full data for a specific version."""
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM planning_versions WHERE id = ?", (version_id,)
        ).fetchone()
    if not row:
        return {}
    d = dict(row)
    d["stats"]       = json.loads(d["stats_json"])
    d["healthCheck"] = json.loads(d["health_json"])
    d["tasks"]       = json.loads(d["tasks_json"])
    return d

def compare_versions(id_v1: int, id_v2: int) -> dict:
    """
    Compare two indexed versions.
    Returns a diff report with: added tasks, removed tasks, changed tasks, stat deltas, health deltas.
    """
    v1 = get_version(id_v1)
    v2 = get_version(id_v2)
    if not v1 or not v2:
        return {"error": "Version(s) introuvable(s)"}

    # Task sets by task_code
    def task_dict(tasks):
        return {t["task_code"]: t for t in tasks if t.get("task_code")}

    t1 = task_dict(v1["tasks"])
    t2 = task_dict(v2["tasks"])

    codes_v1 = set(t1.keys())
    codes_v2 = set(t2.keys())

    added   = [t2[c] for c in (codes_v2 - codes_v1)]
    removed = [t1[c] for c in (codes_v1 - codes_v2)]

    changed = []
    for code in codes_v1 & codes_v2:
        a, b = t1[code], t2[code]
        diffs = {}
        for field in ("target_start_date", "target_end_date", "total_float_days",
                      "orig_durn_days", "status_code", "is_critical"):
            if a.get(field) != b.get(field):
                diffs[field] = {"v1": a.get(field), "v2": b.get(field)}
        if diffs:
            changed.append({"task_code": code, "task_name": b.get("task_name", ""), "changes": diffs})

    # Stat deltas
    stat_keys = ["totalTasks","criticalTasks","nearCriticalTasks","delayedTasks","overallScore","negativeFloatCount"]
    stat_delta = {}
    for k in stat_keys:
        val1 = v1["stats"].get(k, 0)
        val2 = v2["stats"].get(k, 0)
        stat_delta[k] = {"v1": val1, "v2": val2, "delta": round(val2 - val1, 2)}

    # Health check deltas
    h1 = {h["key"]: h for h in v1["healthCheck"]}
    h2 = {h["key"]: h for h in v2["healthCheck"]}
    health_delta = []
    for key in h1:
        if key in h2:
            status_changed = h1[key]["status"] != h2[key]["status"]
            val_changed    = h1[key]["actual"] != h2[key]["actual"]
            if status_changed or val_changed:
                health_delta.append({
                    "key":         key,
                    "description": h1[key]["description"],
                    "v1_actual":   h1[key]["actual"],
                    "v2_actual":   h2[key]["actual"],
                    "v1_status":   h1[key]["status"],
                    "v2_status":   h2[key]["status"],
                    "unit":        h1[key]["unit"],
                })

    return {
        "v1_meta": {"id": id_v1, "project_name": v1["project_name"], "filename": v1["filename"], "imported_at": v1["imported_at"], "label": v1.get("label","")},
        "v2_meta": {"id": id_v2, "project_name": v2["project_name"], "filename": v2["filename"], "imported_at": v2["imported_at"], "label": v2.get("label","")},
        "summary": {
            "added_count":   len(added),
            "removed_count": len(removed),
            "changed_count": len(changed),
        },
        "stat_delta":    stat_delta,
        "health_delta":  health_delta,
        "added_tasks":   added[:50],
        "removed_tasks": removed[:50],
        "changed_tasks": changed[:100],
    }
