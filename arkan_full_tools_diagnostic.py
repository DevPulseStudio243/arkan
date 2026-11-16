"""
arkan_full_tools_diagnostic.py
==============================
Diagnostic complet et approfondi de TOUS les outils, moteurs, agents et modules d'ARKAN.

Teste systématiquement :
  1. Importabilité de chaque module Python
  2. Disponibilité des dépendances externes (fitz, docx, openpyxl, torch, ollama, tesseract, etc.)
  3. Disponibilité et intégrité des bases de données SQLite
  4. Instanciation et exécution de tests unitaires sur chaque moteur ARKAN & ARH
  5. Détection des bugs, routes cassées, fichiers manquants ou dégradations silencieuses.
"""

from __future__ import annotations

import sys
import os
import traceback
import importlib
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Tuple

WORKSPACE = Path(r"d:\DATA BASE IA")
sys.path.insert(0, str(WORKSPACE))

results = {
    "total_modules_checked": 0,
    "working_modules": [],
    "broken_modules": [],
    "warnings": [],
    "missing_dependencies": [],
    "databases_checked": [],
    "functional_tests": {},
}

def log_test(category: str, name: str, status: str, details: str = "", error: str = ""):
    print(f"[{status.upper():7s}] {category:25s} | {name:35s} | {details}")
    if error:
        print(f"         |-- ERREUR: {error}")

# ══════════════════════════════════════════════════════════════════════════════
# 1. TEST DES DÉPENDANCES CRITIQUES
# ══════════════════════════════════════════════════════════════════════════════
print("=" * 80)
print("1. VÉRIFICATION DES DÉPENDANCES PYTHON / SYSTÈME")
print("=" * 80)

DEPENDENCIES = [
    ("fitz (PyMuPDF)", "fitz"),
    ("pandas", "pandas"),
    ("numpy", "numpy"),
    ("openpyxl (Excel)", "openpyxl"),
    ("docx (Word)", "docx"),
    ("reportlab (PDF Gen)", "reportlab"),
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("pydantic", "pydantic"),
    ("sqlite3", "sqlite3"),
    ("requests", "requests"),
    ("torch", "torch"),
    ("transformers", "transformers"),
    ("unsloth", "unsloth"),
    ("pytesseract", "pytesseract"),
    ("pdfplumber", "pdfplumber"),
    ("networkx", "networkx"),
]

for dep_name, mod_name in DEPENDENCIES:
    try:
        m = importlib.import_module(mod_name)
        ver = getattr(m, "__version__", "disponible")
        log_test("DEPENDENCY", dep_name, "OK", f"Version: {ver}")
    except ImportError as e:
        log_test("DEPENDENCY", dep_name, "BROKEN", "Module non installé", str(e))
        results["missing_dependencies"].append((dep_name, str(e)))

# ══════════════════════════════════════════════════════════════════════════════
# 2. TEST DES MODULES ET ENGINES ARKAN / ARH
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("2. TEST D'IMPORT ET D'INTÉGRITÉ DES MODULES ARKAN & ARH")
print("=" * 80)

MODULES_TO_TEST = [
    # Moteurs ARH
    ("ARH Regulatory Engine", "arh_regulatory_engine"),
    ("ARH MultiAgent Swarm", "arh_multiagent_engine"),
    ("ARH Temporal Reasoner", "arh_temporal_reasoner"),
    ("ARH Reconciliation Engine", "arh_reconciliation_engine"),
    ("ARH Material Certificate Analyzer", "arh_material_certificate_analyzer"),
    ("ARH Document Processor", "arh_document_processor"),
    ("ARH PDF Annotator", "arh_pdf_annotator"),
    ("ARH Report Generator", "arh_report_generator"),
    ("ARH Revision Comparator", "arh_revision_comparator"),
    ("ARH Reserve Comparator", "arh_reserve_comparator"),
    ("ARH Knowledge Graph", "arh_knowledge_graph"),
    ("ARH Model Router (Multi-LoRA)", "arh_model_router"),
    ("ARH Dataset Cleaner", "arh_dataset_cleaner"),
    ("ARH Dataset Generator v2", "arh_dataset_generator_v2"),
    ("ARH Dataset Merger", "arh_dataset_merger"),
    ("ARH Ground Truth Extractor", "arh_ground_truth_extractor"),
    ("ARH OCR Engine", "arh_ocr_engine"),
    ("ARH Descriptive Sheet Extractor", "arh_descriptive_sheet_extractor"),
    ("ARH NuExtract Engine", "arh_nuextract_engine"),
    ("ARH API Routes", "arh_api_routes"),
    ("ARH AI Engine", "arh_ai_engine"),
    ("ARH Actors Knowledge", "arh_actors_knowledge"),

    # Moteurs Core ARKAN
    ("AI Engine Core", "ai_engine"),
    ("Audit Engine", "audit_engine"),
    ("Agents Core", "agents"),
    ("Agent Memory", "agent_memory"),
    ("Causal Memory", "causal_memory"),
    ("Conversation Memory", "conversation_memory"),
    ("Classifier", "classifier"),
    ("Graph Engine", "graph_engine"),
    ("Hybrid Retriever", "hybrid_retriever"),
    ("Auto Indexer", "auto_indexer"),
    ("BOQ Planner", "boq_planner"),
    ("AutoCAD Worker", "autocad_worker"),
    ("WBS Planner", "wbs_planner"),
    ("Report Generator Core", "report_generator"),
    ("Excel Generator", "excel_generator"),
    ("Config Core", "config"),
    ("Config Enhanced", "config_enhanced"),
    ("API Enhanced", "api_enhanced"),
]

imported_modules = {}

for label, mod_name in MODULES_TO_TEST:
    results["total_modules_checked"] += 1
    py_path = WORKSPACE / f"{mod_name}.py"
    if not py_path.exists():
        log_test("MODULE", label, "MISSING", f"Fichier introuvable : {mod_name}.py")
        results["broken_modules"].append((mod_name, "Fichier inexistant"))
        continue

    try:
        mod = importlib.import_module(mod_name)
        imported_modules[mod_name] = mod
        log_test("MODULE", label, "OK", f"Import réussi ({py_path.stat().st_size // 1024} KB)")
        results["working_modules"].append(mod_name)
    except Exception as e:
        err_msg = traceback.format_exc().splitlines()[-1]
        log_test("MODULE", label, "BROKEN", "Erreur à l'import", err_msg)
        results["broken_modules"].append((mod_name, err_msg))

# ══════════════════════════════════════════════════════════════════════════════
# 3. TESTS FONCTIONNELS UNITAIRES (EXÉCUTION RÉELLE DES MOTEURS)
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("3. TESTS FONCTIONNELS UNITAIRES DES MOTEURS ARKAN")
print("=" * 80)

# ── Test 3.1 : ARH Regulatory Engine (Checklist & Decrets) ────────────────────
try:
    if "arh_regulatory_engine" in imported_modules:
        reg = imported_modules["arh_regulatory_engine"].ARHRegulatoryEngine()
        eq_type = reg.classify_equipment_type("SEPARATEUR TRIPHASIQUE V-101")
        checklist = reg.get_mandatory_checklist(eq_type)
        log_test("FUNCTIONAL", "ARH Regulatory Engine", "OK", f"Type={eq_type} | Items checklist: {len(checklist)}")
        results["functional_tests"]["arh_regulatory_engine"] = "PASSED"
    else:
        log_test("FUNCTIONAL", "ARH Regulatory Engine", "SKIPPED", "Module non importé")
except Exception as e:
    log_test("FUNCTIONAL", "ARH Regulatory Engine", "FAIL", "Erreur d'exécution", str(e))
    results["functional_tests"]["arh_regulatory_engine"] = f"FAILED: {e}"

# ── Test 3.2 : ARH Temporal Reasoner (Dates et péremption) ───────────────────
try:
    if "arh_temporal_reasoner" in imported_modules:
        tr = imported_modules["arh_temporal_reasoner"].ARHTemporalReasoningAgent()
        res = tr.audit_document_dates(
            text="Certificat de qualification soudeur delivre le 12/01/2023. Epreuve hydrostatique le 15/06/2024.",
            doc_type="WELDING_DOSSIER"
        )
        log_test("FUNCTIONAL", "ARH Temporal Reasoner", "OK", f"Anomalies dates detectees: {len(res.get('anomalies', []))}")
        results["functional_tests"]["arh_temporal_reasoner"] = "PASSED"
    else:
        log_test("FUNCTIONAL", "ARH Temporal Reasoner", "SKIPPED", "Module non importé")
except Exception as e:
    log_test("FUNCTIONAL", "ARH Temporal Reasoner", "FAIL", "Erreur d'exécution", str(e))
    results["functional_tests"]["arh_temporal_reasoner"] = f"FAILED: {e}"

# ── Test 3.3 : ARH Material Certificate Analyzer (CEV & NACE) ────────────────
try:
    if "arh_material_certificate_analyzer" in imported_modules:
        mat_analyzer = imported_modules["arh_material_certificate_analyzer"].ARHMaterialCertificateAnalyzer()
        res = mat_analyzer.analyze_certificate_text(
            text="EN 10204 3.1 HEAT NO H-85527 ASTM A350 LF2 %C=0.20 %Mn=1.14 %Si=0.28 %P=0.015 %S=0.004 %Cr=0.06 %Mo=0.08 %Ni=0.17 %Cu=0.18 %V=0.03 ReH=340 Rm=535 A%=28% Charpy -46C = 48J Hardness=220 HV10",
            grade_hint="A350 LF2"
        )
        cev = res.get("calculated_cev")
        log_test("FUNCTIONAL", "ARH Material Analyzer", "OK", f"CEV calcule = {cev} | Grade={res.get('detected_grade')}")
        results["functional_tests"]["arh_material_certificate_analyzer"] = "PASSED"
    else:
        log_test("FUNCTIONAL", "ARH Material Analyzer", "SKIPPED", "Module non importé")
except Exception as e:
    log_test("FUNCTIONAL", "ARH Material Analyzer", "FAIL", "Erreur d'exécution", str(e))
    results["functional_tests"]["arh_material_certificate_analyzer"] = f"FAILED: {e}"

# ── Test 3.4 : ARH Reconciliation Engine (Cohérence inter-documents) ──────────
try:
    if "arh_reconciliation_engine" in imported_modules:
        rec = imported_modules["arh_reconciliation_engine"].ARHReconciliationEngine()
        doc_params = {
            "ANNEXE_E": {"pressure": 50.0, "temp": 80.0, "material": "ASTM A350 LF2", "heat_number": "H1234"},
            "CALCULATION_NOTE": {"pressure": 50.0, "temp": 80.0, "material": "ASTM A350 LF2"},
            "MTC_3_1": {"material": "ASTM A350 LF2", "heat_number": "H1234"},
        }
        res = rec.reconcile_dossier(doc_params)
        log_test("FUNCTIONAL", "ARH Reconciliation Engine", "OK", f"Conflits trouves: {len(res.get('conflicts', []))}")
        results["functional_tests"]["arh_reconciliation_engine"] = "PASSED"
    else:
        log_test("FUNCTIONAL", "ARH Reconciliation Engine", "SKIPPED", "Module non importé")
except Exception as e:
    log_test("FUNCTIONAL", "ARH Reconciliation Engine", "FAIL", "Erreur d'exécution", str(e))
    results["functional_tests"]["arh_reconciliation_engine"] = f"FAILED: {e}"

# ── Test 3.5 : ARH Multi-Agent Engine (Swarm 7 agents) ───────────────────────
try:
    if "arh_multiagent_engine" in imported_modules:
        swarm_cls = getattr(imported_modules["arh_multiagent_engine"], "ARHMultiAgentSwarm", None)
        if swarm_cls:
            swarm = swarm_cls()
            log_test("FUNCTIONAL", "ARH MultiAgent Swarm", "OK", f"Swarm initialisé ({len(getattr(swarm, 'agents', {}))} agents)")
            results["functional_tests"]["arh_multiagent_engine"] = "PASSED"
        else:
            log_test("FUNCTIONAL", "ARH MultiAgent Swarm", "WARN", "Classe ARHMultiAgentSwarm non trouvée")
    else:
        log_test("FUNCTIONAL", "ARH MultiAgent Swarm", "SKIPPED", "Module non importé")
except Exception as e:
    log_test("FUNCTIONAL", "ARH MultiAgent Swarm", "FAIL", "Erreur d'exécution", str(e))
    results["functional_tests"]["arh_multiagent_engine"] = f"FAILED: {e}"

# ── Test 3.6 : ARH Model Router ──────────────────────────────────────────────
try:
    if "arh_model_router" in imported_modules:
        router = imported_modules["arh_model_router"].ARHModelRouter()
        part = router.classifier.classify("ETAT DESCRIPTIF ANNEXE E - PMA 70 bar")
        lang = router.lang_detector.detect("ETAT DESCRIPTIF ANNEXE E")
        model = router.dispatcher.select_model(part, lang)
        log_test("FUNCTIONAL", "ARH Model Router", "OK", f"Classifié: Part={part}, Lang={lang}, Modèle={model}")
        results["functional_tests"]["arh_model_router"] = "PASSED"
    else:
        log_test("FUNCTIONAL", "ARH Model Router", "SKIPPED", "Module non importé")
except Exception as e:
    log_test("FUNCTIONAL", "ARH Model Router", "FAIL", "Erreur d'exécution", str(e))
    results["functional_tests"]["arh_model_router"] = f"FAILED: {e}"

# ── Test 3.7 : ARH PDF Annotator ─────────────────────────────────────────────
try:
    if "arh_pdf_annotator" in imported_modules:
        annotator_cls = getattr(imported_modules["arh_pdf_annotator"], "ARHPDFAnnotator", None)
        if annotator_cls:
            annotator = annotator_cls()
            log_test("FUNCTIONAL", "ARH PDF Annotator", "OK", "Annotator instancié avec succès")
            results["functional_tests"]["arh_pdf_annotator"] = "PASSED"
        else:
            log_test("FUNCTIONAL", "ARH PDF Annotator", "WARN", "Classe ARHPDFAnnotator introuvable")
    else:
        log_test("FUNCTIONAL", "ARH PDF Annotator", "SKIPPED", "Module non importé")
except Exception as e:
    log_test("FUNCTIONAL", "ARH PDF Annotator", "FAIL", "Erreur d'exécution", str(e))
    results["functional_tests"]["arh_pdf_annotator"] = f"FAILED: {e}"

# ── Test 3.8 : ARH Report Generator ──────────────────────────────────────────
try:
    if "arh_report_generator" in imported_modules:
        rep_cls = getattr(imported_modules["arh_report_generator"], "ARHReportGenerator", None)
        if rep_cls:
            rep_gen = rep_cls()
            log_test("FUNCTIONAL", "ARH Report Generator", "OK", "Report Generator initialisé")
            results["functional_tests"]["arh_report_generator"] = "PASSED"
        else:
            log_test("FUNCTIONAL", "ARH Report Generator", "WARN", "Classe ARHReportGenerator introuvable")
    else:
        log_test("FUNCTIONAL", "ARH Report Generator", "SKIPPED", "Module non importé")
except Exception as e:
    log_test("FUNCTIONAL", "ARH Report Generator", "FAIL", "Erreur d'exécution", str(e))
    results["functional_tests"]["arh_report_generator"] = f"FAILED: {e}"

# ══════════════════════════════════════════════════════════════════════════════
# 4. TEST DES BASES DE DONNÉES SQLITE
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("4. TEST D'INTÉGRITÉ DES BASES DE DONNÉES SQLITE")
print("=" * 80)

DATABASES = [
    "arh_dossiers.db",
    "arh_knowledge_graph.db",
    "arh_training_benchmark.db",
    "arh_memory.db",
    "knowledge_graph.db",
    "vector_store.db",
    "epc_knowledge.db",
]

for db_name in DATABASES:
    db_path = WORKSPACE / db_name
    if not db_path.exists():
        log_test("DATABASE", db_name, "MISSING", f"Fichier non encore créé ({db_name})")
        results["databases_checked"].append({"name": db_name, "status": "MISSING"})
        continue

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cur.fetchall()]
        conn.close()
        log_test("DATABASE", db_name, "OK", f"Tables: {', '.join(tables) if tables else 'Vide (0 table)'}")
        results["databases_checked"].append({"name": db_name, "status": "OK", "tables": tables})
    except Exception as e:
        log_test("DATABASE", db_name, "CORRUPT", "Erreur de lecture", str(e))
        results["databases_checked"].append({"name": db_name, "status": "CORRUPT", "error": str(e)})

# ══════════════════════════════════════════════════════════════════════════════
# 5. TEST DES SERVEURS / SERVICES EXTERNES (OLLAMA, OCR, ETC.)
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("5. TEST DES SERVICES EXTERNES (OLLAMA, OCR TESSERACT)")
print("=" * 80)

# Test Ollama API
try:
    import urllib.request
    with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name") for m in data.get("models", [])]
        log_test("SERVICE", "Ollama Local Daemon", "OK", f"Actif | Modèles: {', '.join(models[:5])}")
except Exception as e:
    log_test("SERVICE", "Ollama Local Daemon", "WARN", "Non actif ou non démarré sur http://localhost:11434", str(e))

# Test Tesseract OCR
try:
    import pytesseract
    # Tester si l'exécutable tesseract est trouvé
    ver = pytesseract.get_tesseract_version()
    log_test("SERVICE", "Tesseract OCR Engine", "OK", f"Version: {ver}")
except Exception as e:
    log_test("SERVICE", "Tesseract OCR Engine", "WARN", "Tesseract non configuré dans le PATH", str(e))

# ══════════════════════════════════════════════════════════════════════════════
# RAPPORT FINAL
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("RESUME GLOBAL DU DIAGNOSTIC ARKAN")
print("=" * 80)

total = results["total_modules_checked"]
working = len(results["working_modules"])
broken = len(results["broken_modules"])

print(f"Total modules verifies     : {total}")
print(f"Modules operationnels      : {working} ({working/total*100:.1f}%)" if total else "0")
print(f"Modules defaillants/absents: {broken}")
print(f"Dependances manquantes     : {len(results['missing_dependencies'])}")

if results["broken_modules"]:
    print("\n[ATTENTION] MODULES NECESSITANT UNE CORRECTION :")
    for mod, err in results["broken_modules"]:
        print(f"  - {mod:35s} : {err}")
else:
    print("\n[OK] TOUS les modules majeurs d'ARKAN & ARH sont operationnels !")

out_report = WORKSPACE / "arkan_diagnostic_report.json"
with open(out_report, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\nRapport detaille sauvegarde dans : {out_report}")
