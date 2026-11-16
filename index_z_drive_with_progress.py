import os
import json
import time
import fitz
import docx
import openpyxl

BASE_DIR = r"Z:\Department\Qualité\02.ARH\00-TECHNIQUE"
PROGRESS_FILE = r"D:\DATA BASE IA\index_progress.json"
OUTPUT_DB_JSON = r"D:\DATA BASE IA\arh_quality_knowledge_extracted.json"

print("=== INDEXATION EN DIRECT AVEC POURCENTAGE (0% -> 100%) ===")

# Étape 1 : Collecte et décompte total des fichiers
print("1/2 - Analyse de la structure et décompte global des fichiers sur le réseau Z:...")
target_files = []
for root, dirs, files in os.walk(BASE_DIR):
    rel = os.path.relpath(root, BASE_DIR)
    depth = len(rel.split(os.sep)) if rel != "." else 0
    if depth > 4:
        dirs.clear()
        continue
    for f in files:
        if f.startswith("~$"):
            continue
        fl = f.lower()
        if fl.endswith((".pdf", ".docx", ".xlsx", ".xls")):
            target_files.append(os.path.join(root, f))

total_files = len(target_files)
print(f"-> TOTAL FICHIERS IDENTIFIÉS : {total_files} fichiers au total.\n")

if total_files == 0:
    print("Aucun fichier trouvé.")
    exit(0)

# Initialisation du fichier de statut
progress_data = {
    "status": "IN_PROGRESS",
    "total_files": total_files,
    "processed_files": 0,
    "percentage": 0.0,
    "current_file": "",
    "extracted_count": 0,
    "start_time": time.time(),
    "estimated_remaining_seconds": 0
}

with open(PROGRESS_FILE, "w", encoding="utf-8") as pf:
    json.dump(progress_data, pf, indent=2)

extracted_records = []
start_t = time.time()

# Étape 2 : Boucle d'indexation avec calcul du pourcentage
for idx, fpath in enumerate(target_files, 1):
    fname = os.path.basename(fpath)
    pct = round((idx / total_files) * 100, 1)
    elapsed = time.time() - start_t
    avg_per_file = elapsed / idx
    rem_seconds = round(avg_per_file * (total_files - idx))
    
    safe_fname = fname.encode('ascii', 'ignore').decode()
    print(f"[{pct:5.1f}%] ({idx}/{total_files}) Traitement : {safe_fname} (Temps restant estimé : {rem_seconds}s)")
    
    # Mise à jour du fichier de statut
    progress_data["processed_files"] = idx
    progress_data["percentage"] = pct
    progress_data["current_file"] = fname
    progress_data["estimated_remaining_seconds"] = rem_seconds
    with open(PROGRESS_FILE, "w", encoding="utf-8") as pf:
        json.dump(progress_data, pf, indent=2)

    # Extraction du contenu textuel selon le type de fichier
    text_content = ""
    fl = fname.lower()
    try:
        if fl.endswith(".pdf"):
            doc = fitz.open(fpath)
            pages_txt = []
            for pno in range(min(30, len(doc))):
                pt = doc[pno].get_text()
                if pt.strip():
                    pages_txt.append(pt.strip())
            doc.close()
            text_content = "\n".join(pages_txt)
        elif fl.endswith(".docx"):
            doc = docx.Document(fpath)
            text_content = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        elif fl.endswith((".xlsx", ".xls")):
            wb = openpyxl.load_workbook(fpath, data_only=True, read_only=True)
            sheet_txts = []
            for sheet in wb.sheetnames[:3]:
                ws = wb[sheet]
                for r in ws.iter_rows(values_only=True, max_row=50):
                    if r:
                        line = " ".join([str(c) for c in r if c is not None])
                        if line.strip():
                            sheet_txts.append(line.strip())
            text_content = "\n".join(sheet_txts)
    except Exception as e:
        text_content = ""

    if text_content and len(text_content) > 30:
        extracted_records.append({
            "file_name": fname,
            "file_path": fpath,
            "text": text_content[:15000]
        })
        progress_data["extracted_count"] = len(extracted_records)

# Finalisation
progress_data["status"] = "COMPLETED"
progress_data["percentage"] = 100.0
progress_data["estimated_remaining_seconds"] = 0
with open(PROGRESS_FILE, "w", encoding="utf-8") as pf:
    json.dump(progress_data, pf, indent=2)

with open(OUTPUT_DB_JSON, "w", encoding="utf-8") as out:
    json.dump(extracted_records, out, ensure_ascii=False, indent=2)

print(f"\n================================================================================")
print(f"   INDEXATION TERMINÉE À 100.0% ! {len(extracted_records)} DOCUMENTS QUALITÉ EXTRAITS")
print(f"================================================================================")
