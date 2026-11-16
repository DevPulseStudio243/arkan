import os
import glob
import json
import re
import openpyxl
import fitz

BASE_DIR = r"Z:\Department\Qualité\02.ARH\00-TECHNIQUE"
OUTPUT_JSON = r"D:\DATA BASE IA\arh_quality_comments_db.json"

extracted_records = []

print(f"=== Extraction des commentaires d'audit ARH depuis {BASE_DIR} ===")

# 1. Extraction depuis les fichiers Excel de suivi (.xlsx / .xls)
excel_files = []
for root, dirs, files in os.walk(BASE_DIR):
    for f in files:
        if f.startswith("~$"):
            continue
        if f.lower().endswith((".xlsx", ".xlsm")):
            excel_files.append(os.path.join(root, f))

print(f"Fichiers Excel détectés : {len(excel_files)}")

for ex_path in excel_files[:100]:
    try:
        wb = openpyxl.load_workbook(ex_path, data_only=True)
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            headers = []
            for row in ws.iter_rows(values_only=True):
                if not row:
                    continue
                row_str = [str(c).strip() if c is not None else "" for c in row]
                if any(k in " ".join(row_str).upper() for k in ["COMMENTAIRE", "REMARQUE", "OBSERVATION", "RESERVE", "AVIS", "ACTION"]):
                    headers = [c.upper() for c in row_str]
                    continue
                
                if headers:
                    for i, val in enumerate(row_str):
                        if i < len(headers) and val and len(val) > 10:
                            h_name = headers[i]
                            if any(k in h_name for k in ["COMMENTAIRE", "REMARQUE", "OBSERVATION", "RESERVE", "AVIS", "ACTION", "MOTIF"]):
                                extracted_records.append({
                                    "source_file": os.path.basename(ex_path),
                                    "source_path": ex_path,
                                    "type": "EXCEL_COMMENT",
                                    "column": h_name,
                                    "comment_text": val
                                })
    except Exception as e:
        pass

print(f"Commentaires Excel extraits : {len(extracted_records)}")

# 2. Extraction depuis les fichiers PDF de commentaires / remarques
pdf_comment_files = []
for root, dirs, files in os.walk(BASE_DIR):
    for f in files:
        if f.lower().endswith(".pdf") and any(k in f.lower() for k in ["commentaire", "remarque", "reserve", "levee", "avis"]):
            pdf_comment_files.append(os.path.join(root, f))

print(f"Fichiers PDF de commentaires détectés : {len(pdf_comment_files)}")

for pdf_path in pdf_comment_files[:100]:
    try:
        doc = fitz.open(pdf_path)
        full_text = []
        for pno in range(len(doc)):
            full_text.append(doc[pno].get_text())
        doc.close()
        text_blob = "\n".join(full_text).strip()
        if len(text_blob) > 20:
            extracted_records.append({
                "source_file": os.path.basename(pdf_path),
                "source_path": pdf_path,
                "type": "PDF_COMMENT_DOCUMENT",
                "comment_text": text_blob[:5000]
            })
    except Exception as e:
        pass

print(f"Total enregistrements d'expertise extraits : {len(extracted_records)}")

with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
    json.dump(extracted_records, f, ensure_ascii=False, indent=2)

print(f"Enregistré dans {OUTPUT_JSON}")
