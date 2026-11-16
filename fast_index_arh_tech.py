import os
import json
import re
import fitz

BASE_DIR = r"Z:\Department\Qualité\02.ARH\00-TECHNIQUE"
OUTPUT_JSON = r"D:\DATA BASE IA\arh_quality_comments_db.json"

extracted = []
print("=== FAST INDEXING ARH QUALITY COMMENTS FROM Z DRIVE ===")

for root, dirs, files in os.walk(BASE_DIR):
    # limiter la profondeur
    rel = os.path.relpath(root, BASE_DIR)
    depth = len(rel.split(os.sep)) if rel != "." else 0
    if depth > 4:
        dirs.clear()
        continue
    for f in files:
        if f.startswith("~$"):
            continue
        fl = f.lower()
        if any(k in fl for k in ["commentaire", "remarque", "reserve", "levee", "avis", "follow", "suivi", "fiche"]):
            fpath = os.path.join(root, f)
            print(f"Indexation : {f}")
            if fl.endswith(".pdf"):
                try:
                    doc = fitz.open(fpath)
                    txt = "\n".join([p.get_text() for p in doc if p.get_text().strip()])
                    doc.close()
                    if txt.strip():
                        extracted.append({
                            "file": f,
                            "path": fpath,
                            "type": "PDF",
                            "text": txt[:10000]
                        })
                except Exception:
                    pass
            elif fl.endswith(".docx"):
                try:
                    import docx
                    doc = docx.Document(fpath)
                    txt = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
                    if txt.strip():
                        extracted.append({
                            "file": f,
                            "path": fpath,
                            "type": "DOCX",
                            "text": txt[:10000]
                        })
                except Exception:
                    pass

print(f"\nExtraction terminee : {len(extracted)} documents d'expertise et de suivi traites.")

with open(OUTPUT_JSON, "w", encoding="utf-8") as out:
    json.dump(extracted, out, ensure_ascii=False, indent=2)

print(f"Base de connaissances enregistree dans : {OUTPUT_JSON}")
