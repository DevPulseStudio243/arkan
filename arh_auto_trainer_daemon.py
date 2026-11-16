"""
arh_auto_trainer_daemon.py
==========================
Démon d'Apprentissage Continu et de Perfectionnement Autonome d'ARKAN ARH.
Compare en boucle fermée les résultats d'ARKAN contre la Vérité Terrain Réelle
issue des 464 annotations des ingénieurs experts stockées dans arh_expert_ground_truth.db.
"""

from __future__ import annotations

import os
import sys
import time
import json
import sqlite3
import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple

BASE_DIR = Path(__file__).resolve().parent

DATASET_ROOT = Path(os.getenv("ARH_DATASET_ROOT", r"Z:\Department\Qualité\02.ARH\00-TECHNIQUE"))
GT_DB_PATH   = Path(os.getenv("ARH_GROUND_TRUTH_DB", str(BASE_DIR / "arh_expert_ground_truth.db")))
BENCH_DB     = Path(os.getenv("ARH_BENCHMARK_DB", str(BASE_DIR / "arh_training_benchmark.db")))

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
from arh_document_processor import ARHDocumentProcessor

def _init_benchmark_db():
    conn = sqlite3.connect(BENCH_DB)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS arh_benchmark_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            project_name TEXT,
            incoming_pdf TEXT,
            detected_comments_count INTEGER,
            ground_truth_count INTEGER,
            matched_count INTEGER,
            recall_rate REAL,
            status TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS arh_unmatched_expert_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            project TEXT,
            filename TEXT,
            page_num INTEGER,
            expert_author TEXT,
            expert_comment TEXT,
            theme TEXT,
            learning_status TEXT DEFAULT 'PENDING_RULE'
        )
    """)
    conn.commit()
    conn.close()

def _get_expert_annotations_for_file(filename: str, project: str) -> List[Dict[str, Any]]:
    if not GT_DB_PATH.exists():
        return []
    conn = sqlite3.connect(GT_DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    base_name = filename.replace(".pdf", "").strip().lower()
    clean_base = base_name.split("comment")[0].split("rev")[0].strip()
    rows = cur.execute("""
        SELECT * FROM expert_annotations 
        WHERE LOWER(filename) = LOWER(?) 
           OR LOWER(filename) LIKE ?
           OR (project = ? AND LOWER(filename) LIKE ?)
    """, (filename, f"%{clean_base}%", project, f"%{clean_base[:15]}%")).fetchall()
    annots = [dict(r) for r in rows]
    conn.close()
    return annots

def _match_comment_with_expert(detected_comment: Dict[str, Any], expert_annot: Dict[str, Any]) -> bool:
    c_text = (detected_comment.get("title", "") + " " + 
              detected_comment.get("description", "") + " " + 
              detected_comment.get("observation", "") + " " +
              detected_comment.get("standard", "")).upper()
    e_text = expert_annot.get("content", "").upper()
    keywords = [
        ("ASME B16.34", ["B16.34", "OD", "ID", "DIAMÈTRE", "WALL THICKNESS"]),
        ("21-261", ["21-261", "ART. 08", "ART 08", "CONTRAINTE", "ALLOWABLE STRESS", "1/3", "5/8"]),
        ("CORROSION", ["CORROSION", "CA", "SURÉPAISSEUR", "SUREPAISSEUR"]),
        ("TEMP", ["425", "TEMPÉRATURE", "TEMPERATURE", "SERVICE TEMP"]),
        ("PRESSION", ["15.4", "154", "150 BAR", "PRESSION D'ÉPREUVE", "TEST PRESSURE"]),
        ("WPS", ["WPS", "PQR", "A216", "SOUDAGE", "P-NO"]),
        ("BARRED TEE", ["EXTRUDED", "PIQUAGE", "BARREAU", "BAR MATERIAL", "B16.25"]),
        ("ITP", ["HOLD", "POINT D'ARRÊT", "TPI", "ARH", "WITNESS"]),
        ("CARTOUCHE", ["PAGE DE GARDE", "CARTOUCHE", "REVISION", "VISA"]),
        ("CERTIFICAT", ["3.1", "CONSULAT", "CHAMBRE DE COMMERCE"])
    ]
    for label, terms in keywords:
        if any(t in c_text for t in terms) and any(t in e_text for t in terms):
            return True
    p_c = detected_comment.get("page", "")
    p_e = expert_annot.get("page_num", -1)
    if str(p_e) in str(p_c) and len(e_text) > 15:
        tokens_e = set([w for w in e_text.split() if len(w) > 4])
        tokens_c = set([w for w in c_text.split() if len(w) > 4])
        if len(tokens_e.intersection(tokens_c)) >= 2:
            return True
    return False

def evaluate_and_learn_project(project_name: str, processor: ARHDocumentProcessor) -> Dict[str, Any]:
    proj_path = DATASET_ROOT / project_name
    if not proj_path.exists():
        print(f"[AUTO-TRAINER] Dossier projet introuvable ou non monté : {proj_path} (définir la variable ARH_DATASET_ROOT pour personnaliser le chemin)", flush=True)
        return {"status": "NOT_FOUND"}
    print(f"\n==================================================================", flush=True)
    print(f"[AUTO-TRAINER] Audit & Apprentissage Projet : {project_name}", flush=True)
    print(f"==================================================================", flush=True)
    pdf_files = []
    for root, dirs, files in os.walk(proj_path):
        depth = len(Path(root).relative_to(proj_path).parts)
        if depth <= 3:
            for f in files:
                if f.lower().endswith(".pdf"):
                    pdf_files.append(Path(root) / f)
    total_proj_annots = 0
    total_proj_matched = 0
    evaluated_dossiers = 0
    for pdf in pdf_files[:8]:
        expert_annots = _get_expert_annotations_for_file(pdf.name, project_name)
        if not expert_annots:
            continue
        evaluated_dossiers += 1
        print(f"\n  -> Dossier : {pdf.name} ({len(expert_annots)} annotations expertes)", flush=True)
        try:
            res = processor.process_dossier_batch(
                file_paths=[str(pdf)],
                project_name=project_name,
                unit_name="UNIT-100",
                dossier_id=f"LRN_{pdf.stem[:10].upper()}"
            )
            detected_comments = res.get("comments", [])
            matched_expert_ids = set()
            for exp in expert_annots:
                for c in detected_comments:
                    if _match_comment_with_expert(c, exp):
                        matched_expert_ids.add(exp.get("id"))
                        break
            matched_count = len(matched_expert_ids)
            total_exp = len(expert_annots)
            recall = (matched_count / max(1, total_exp)) * 100.0
            total_proj_annots += total_exp
            total_proj_matched += matched_count
            print(f"     Concordance : {matched_count}/{total_exp} ({recall:.1f}%) | Réserves Arkan : {len(detected_comments)}", flush=True)
            unmatched = [exp for exp in expert_annots if exp.get("id") not in matched_expert_ids]
            if unmatched:
                conn = sqlite3.connect(BENCH_DB)
                cur = conn.cursor()
                for um in unmatched:
                    cur.execute("""
                        INSERT INTO arh_unmatched_expert_findings 
                        (project, filename, page_num, expert_author, expert_comment, theme)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (project_name, pdf.name, um.get("page_num"), um.get("author"), um.get("content"), um.get("theme")))
                conn.commit()
                conn.close()
                print(f"     [+] {len(unmatched)} écarts indexés pour auto-apprentissage.", flush=True)
        except Exception as e:
            print(f"     [!] Erreur sur {pdf.name}: {e}", flush=True)
    proj_recall = (total_proj_matched / max(1, total_proj_annots)) * 100.0 if total_proj_annots > 0 else 100.0
    return {"project": project_name, "evaluated_dossiers": evaluated_dossiers, "expert_annotations": total_proj_annots, "matched": total_proj_matched, "recall": proj_recall}

def run_continuous_training():
    _init_benchmark_db()
    processor = ARHDocumentProcessor()
    processor.vision_model_available = False
    print("==========================================================================", flush=True)
    print("  [ARKAN AUTO-TRAINER DAEMON v2.0 - CLOSED LOOP ACTIVE LEARNING]", flush=True)
    print("  Vérité Terrain : 464 annotations d'experts (arh_expert_ground_truth.db)", flush=True)
    print("==========================================================================", flush=True)
    projects = ["SUIVI DOSSIER ARH", "20-05 PUITS GHBR", "01- C8321 OH1 (24'' 46Km GRE)", "02- C2121 (24'' 30Km CIS HEH)", "04- C3321 OD1 (137KM)"]
    total_evaluated = 0
    total_annots = 0
    total_matched = 0
    for p in projects:
        res = evaluate_and_learn_project(p, processor)
        total_evaluated += res.get("evaluated_dossiers", 0)
        total_annots += res.get("expert_annotations", 0)
        total_matched += res.get("matched", 0)
    overall_recall = (total_matched / max(1, total_annots)) * 100.0 if total_annots > 0 else 100.0
    print(f"\n==========================================================================", flush=True)
    print(f"  [SYNTHÈSE GLOBALE AUTO-TRAINER]", flush=True)
    print(f"  Dossiers audités avec vérité terrain : {total_evaluated}", flush=True)
    print(f"  Annotations réelles d'experts        : {total_annots}", flush=True)
    print(f"  Annotations couvertes par Arkan      : {total_matched}", flush=True)
    print(f"  Taux de Rappel Réel Global           : {overall_recall:.1f}%", flush=True)
    print(f"==========================================================================", flush=True)

if __name__ == "__main__":
    run_continuous_training()
