"""
ARKAN DOTS Router — Intégration Native dans ARKAN Desktop
Gère les statuts des 12 DOTs, les messages d'intervention humaine, les logs et le suivi fine-tuning.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import sqlite3
import pathlib
import threading
import time
import os

router = APIRouter(tags=["ARKAN DOTS"])

DB_PATH = pathlib.Path(__file__).parent.parent / "dots" / "dots_runtime.db"

def get_db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS dots (
        id TEXT PRIMARY KEY,
        name TEXT,
        icon TEXT,
        discipline TEXT,
        status TEXT,
        progress INTEGER,
        last_action TEXT,
        confidence INTEGER,
        pending_messages INTEGER
    )
    ''')
    c.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dot_id TEXT,
        mission_id TEXT,
        question TEXT,
        context TEXT,
        status TEXT,
        timestamp REAL
    )
    ''')
    c.execute('''
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL,
        dot_id TEXT,
        message TEXT,
        type TEXT
    )
    ''')
    c.execute('''
    CREATE TABLE IF NOT EXISTS missions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        status TEXT
    )
    ''')
    c.execute('''
    CREATE TABLE IF NOT EXISTS training (
        platform TEXT PRIMARY KEY,
        name TEXT,
        progress INTEGER,
        status TEXT,
        step TEXT
    )
    ''')

    # Statuts initiaux neutres — seules les vraies exécutions de DOTs alimentent ces valeurs.
    initial_dots = [
        ("DOT-00", "Directeur de Projet",        "🧠", "director", "IDLE", 0, "En attente de mission", 100, 0),
        ("DOT-01", "Piping & Isométriques",       "🔧", "piping",   "IDLE", 0, "En attente de mission", 100, 0),
        ("DOT-02", "Instrumentation & Contrôle",  "🔌", "instru",   "IDLE", 0, "En attente de mission", 100, 0),
        ("DOT-03", "Électricité & SAS",           "⚡", "elec",     "IDLE", 0, "En attente de mission", 100, 0),
        ("DOT-04", "Génie Civil & Structures",    "🏗️", "civil",   "IDLE", 0, "En attente de mission", 100, 0),
        ("DOT-05", "Procédé & Thermodynamique",   "🔥", "process",  "IDLE", 0, "En attente de mission", 100, 0),
        ("DOT-06", "Sécurité Procédé & HSE",      "🛡️", "hse",    "IDLE", 0, "En attente de mission", 100, 0),
        ("DOT-07", "Procurement & Achats",         "📦", "achats",  "IDLE", 0, "En attente de mission", 100, 0),
        ("DOT-08", "Planning & Scheduling",        "📅", "planning","IDLE", 0, "En attente de mission", 100, 0),
        ("DOT-09", "Document Control",             "📋", "docctrl", "IDLE", 0, "En attente de mission", 100, 0),
        ("DOT-10", "Auditeur Qualité Croisée",     "🔍", "auditeur","IDLE", 0, "En attente de mission", 100, 0),
        ("DOT-11", "Synthétiseur de Projet",       "📊", "synthese","IDLE", 0, "En attente de mission", 100, 0),
    ]
    for d in initial_dots:
        c.execute("INSERT OR IGNORE INTO dots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", d)

    # Pas de missions fictives ni de données training inventées.
    # Les missions et trainings sont créés uniquement via les routes POST.

    conn.commit()
    conn.close()

init_db()

@router.get("/api/dots/status")
def get_dots_status():
    conn = get_db()
    dots = conn.execute("SELECT * FROM dots").fetchall()
    missions_active = conn.execute("SELECT COUNT(*) as c FROM missions WHERE status='ACTIVE'").fetchone()['c']
    missions_waiting = conn.execute("SELECT COUNT(*) as c FROM missions WHERE status='WAITING'").fetchone()['c']
    missions_completed = conn.execute("SELECT COUNT(*) as c FROM missions WHERE status='COMPLETED'").fetchone()['c']
    conn.close()
    return {
        "dots": [dict(d) for d in dots],
        "stats": {
            "active": missions_active,
            "waiting": missions_waiting,
            "completed": missions_completed
        }
    }

@router.get("/api/dots/messages")
def get_messages():
    conn = get_db()
    msgs = conn.execute("SELECT * FROM messages WHERE status='PENDING' ORDER BY timestamp DESC").fetchall()
    conn.close()
    return [dict(m) for m in msgs]

class AnswerModel(BaseModel):
    answer: str

@router.post("/api/dots/answer/{msg_id}")
def post_answer(msg_id: int, payload: AnswerModel):
    conn = get_db()
    c = conn.cursor()
    msg = c.execute("SELECT dot_id FROM messages WHERE id=?", (msg_id,)).fetchone()
    if not msg:
        conn.close()
        raise HTTPException(status_code=404, detail="Message introuvable")

    dot_id = msg['dot_id']
    c.execute("UPDATE messages SET status='RESOLVED' WHERE id=?", (msg_id,))

    # Log de l'intervention
    c.execute("INSERT INTO logs (timestamp, dot_id, message, type) VALUES (?, ?, ?, 'decision')",
              (time.time(), dot_id, f"Décision humaine validée : {payload.answer}"))

    # Vérification des messages restants
    pending = c.execute("SELECT COUNT(*) as c FROM messages WHERE dot_id=? AND status='PENDING'", (dot_id,)).fetchone()['c']
    c.execute("UPDATE dots SET pending_messages=? WHERE id=?", (pending, dot_id))
    if pending == 0:
        c.execute("UPDATE dots SET status='ACTIVE', last_action='Reprise autonome suite validation humaine' WHERE id=?", (dot_id,))

    conn.commit()
    conn.close()
    return {"status": "ok", "message": "Réponse prise en compte par le DOT"}

@router.get("/api/dots/logs")
def get_logs(since: float = 0.0):
    conn = get_db()
    logs = conn.execute("SELECT * FROM logs WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 60", (since,)).fetchall()
    conn.close()
    return [dict(l) for l in reversed(logs)]

class MissionModel(BaseModel):
    name: str
    description: str = ""

@router.post("/api/dots/mission")
def create_mission(mission: MissionModel):
    conn = get_db()
    conn.execute("INSERT INTO missions (name, status) VALUES (?, 'ACTIVE')", (mission.name,))
    conn.execute("UPDATE dots SET status='ACTIVE', progress=5, last_action='Nouvelle mission: ' || ? WHERE status='INACTIVE'", (mission.name,))
    conn.execute("INSERT INTO logs (timestamp, dot_id, message, type) VALUES (?, 'DOT-00', ?, 'mission')",
                 (time.time(), f"Mission lancée par l'utilisateur : {mission.name}"))
    conn.commit()
    conn.close()
    return {"status": "ok", "message": f"Mission '{mission.name}' distribuée aux DOTs"}

@router.get("/api/training/status")
def get_training_status():
    conn = get_db()
    trainings = conn.execute("SELECT * FROM training").fetchall()
    conn.close()
    return [dict(t) for t in trainings]
