import os
import sys
import shutil
import glob
from pathlib import Path
import sqlite3
import json

sys.stdout.reconfigure(encoding='utf-8')

os.environ["ARH_DISABLE_OCR"] = "1"
os.environ["ARH_DISABLE_VISION"] = "1"
os.environ["ARH_DISABLE_LLM"] = "1"

from arh_document_processor import ARHDocumentProcessor
from arh_document_slicer import ARHDocumentSlicer
from arh_api_routes import _save_dossier
from reconcile_db_master import reconcile_database

UPLOADS_DIR = Path("d:/DATA BASE IA/arh_uploads")
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# 1. Source files identification
tee_src = glob.glob("arh_uploads/DOSSIER_ARH_05F1708F/*.pdf")
if not tee_src:
    tee_src = glob.glob(r"C:\Users\MSI\Desktop\arh\02-DOSSIER ARH PRELIMINAIRE\05.TEE A BARREAU\INCOMING\REV A0\*.pdf")
tee_pdf = tee_src[0]
tee_fname = os.path.basename(tee_pdf)

fit_src = glob.glob("arh_uploads/DOSSIER_ARH_128D1E2E/*.pdf")
if not fit_src:
    fit_src = glob.glob(r"C:\Users\MSI\Desktop\arh\02-DOSSIER ARH PRELIMINAIRE\12.Fittings\INCOMING\REV 0\*.pdf")
fit_pdf = fit_src[0]
fit_fname = os.path.basename(fit_pdf)

print(f"[SETUP] Tee source PDF: {tee_pdf} ({tee_fname})")
print(f"[SETUP] Fittings source PDF: {fit_pdf} ({fit_fname})")

dossiers_config = [
    {
        "dossier_id": "DOSSIER_ARH_26307CC5",
        "project_name": "TEST",
        "unit_name": "UNIT-01",
        "equipment_type": "FITTING",
        "src_pdf": tee_pdf,
        "fname": tee_fname,
        "vendor": "Hebei Canghai Nuclear Equipment Technology Co., Ltd."
    },
    {
        "dossier_id": "DOSSIER_ARH_A6484846",
        "project_name": "TEST FITTING",
        "unit_name": "UNIT-02",
        "equipment_type": "FITTING",
        "src_pdf": fit_pdf,
        "fname": fit_fname,
        "vendor": "ZICN / GCB"
    },
    {
        "dossier_id": "DOSSIER_ARH_A034FE30",
        "project_name": "TEST TEE A BAREEAU",
        "unit_name": "UNIT-100",
        "equipment_type": "FITTING",
        "src_pdf": tee_pdf,
        "fname": tee_fname,
        "vendor": "Hebei Canghai Nuclear Equipment Technology Co., Ltd."
    }
]

processor = ARHDocumentProcessor()
slicer = ARHDocumentSlicer()

for cfg in dossiers_config:
    d_id = cfg["dossier_id"]
    target_dir = UPLOADS_DIR / d_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_pdf = target_dir / cfg["fname"]
    
    # Copy file if not exists or size differs
    if not target_pdf.exists() or target_pdf.stat().st_size != os.path.getsize(cfg["src_pdf"]):
        shutil.copy2(cfg["src_pdf"], str(target_pdf))
        print(f"  [COPIED] {cfg['fname']} -> {target_dir}")

    print(f"\nProcessing {d_id}...")
    res = processor.process_dossier_batch(
        file_paths=[str(target_pdf)],
        project_name=cfg["project_name"],
        unit_name=cfg["unit_name"],
        dossier_id=d_id,
        dossier_stage="PRELIMINARY",
        forced_equipment_type=cfg["equipment_type"],
        metadata={"vendor_name": cfg["vendor"]}
    )

    _save_dossier(res)
    print(f"  [SAVED] {d_id} in SQLite arh_dossiers")

    pieces = slicer.slice_dossier(d_id)
    print(f"  [SLICED] {len(pieces)} pieces in {target_dir / 'pieces'}")

print("\n--- Running Master Reconciliation ---")
reconcile_database()

# Verification check
conn = sqlite3.connect('arh_dossiers.db')
c = conn.cursor()
c.execute("SELECT dossier_id, project_name, compliance_score, status FROM arh_dossiers")
rows = c.fetchall()
print(f"\n[VERIFICATION] arh_dossiers count: {len(rows)}")
for r in rows:
    print(f"  - {r[0]} | {r[1]} | score={r[2]} | {r[3]}")
conn.close()

print("\n>>> ACTIVE DOSSIERS FULLY POPULATED & CALIBRATED <<<")
