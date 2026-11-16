import sqlite3
import json
import re
from pathlib import Path

conn = sqlite3.connect('arh_dossiers.db')
c = conn.cursor()

c.execute("SELECT dossier_id, data_json FROM arh_dossiers")
rows = c.fetchall()

for dossier_id, data_json in rows:
    if not data_json:
        continue
    data = json.loads(data_json)
    all_comments = data.get("comments", [])
    sheet_audit_log = data.get("sheet_audit_log", [])
    
    # 1. Dossier specific fixes
    if dossier_id == "DOSSIER_ARH_26307CC5":
        data["total_pages"] = 73
    elif dossier_id == "DOSSIER_ARH_A6484846":
        data["total_pages"] = 90
        for cm in all_comments:
            if cm.get("id", "").startswith("REM_FIT_STRESS_B313") or cm.get("id", "").startswith("REM_FIT_RE_RM"):
                cm["page_number"] = 62
                cm["page"] = "Page 62 sur 90"

    # 2. Reset sheet_audit_log
    if sheet_audit_log:
        for entry in sheet_audit_log:
            entry["anomalies"] = []
            entry["status"] = "✅ CONFORME"
            entry["details"] = "Aucun écart réglementaire ou erreur de calcul détectée."

        # 3. Reconcile comments to sheet_audit_log
        for comment in all_comments:
            c_doc = comment.get("document_concerned", "")
            c_page_num = comment.get("page_number")
            if not c_page_num or not isinstance(c_page_num, int) or c_page_num < 1:
                c_page_str = comment.get("page", "Page 1")
                m_p = re.search(r'Page\s*(\d+)', str(c_page_str), re.IGNORECASE)
                c_page_num = int(m_p.group(1)) if m_p else 0

            if comment.get("is_missing_document") or c_page_num <= 0:
                continue

            matched_entry = None
            # Match 1: exact document and page
            for entry in sheet_audit_log:
                entry_doc = entry.get("document", "")
                entry_pg = entry.get("page", 1)
                if c_doc and (c_doc == entry_doc or Path(c_doc).stem == Path(entry_doc).stem):
                    if entry_pg == c_page_num:
                        matched_entry = entry
                        break

            # Match 2: stem partial
            if not matched_entry:
                for entry in sheet_audit_log:
                    entry_doc = entry.get("document", "")
                    entry_pg = entry.get("page", 1)
                    if c_doc and (Path(c_doc).stem.lower() in entry_doc.lower() or entry_doc.lower() in c_doc.lower()):
                        if entry_pg == c_page_num:
                            matched_entry = entry
                            break

            # Match 3: direct page number
            if not matched_entry:
                for entry in sheet_audit_log:
                    if entry.get("page") == c_page_num:
                        matched_entry = entry
                        break

            if matched_entry:
                matched_entry["status"] = "❌ ÉCART DÉTECTÉ"
                existing_anomalies = matched_entry.setdefault("anomalies", [])
                if not any(a.get("id") == comment.get("id") for a in existing_anomalies):
                    existing_anomalies.append(comment)
                anomaly_count = len(existing_anomalies)
                matched_entry["details"] = f"{anomaly_count} écart(s) détecté(s) : " + ", ".join([a.get("title", "") for a in existing_anomalies[:3]])

    # Update data_json
    data["sheet_audit_log"] = sheet_audit_log
    data["comments"] = all_comments

    # Also clean up non-mandatory pieces in composition_summary so that MAT_CERT, DIM_CERT, HYDRO_PV don't show Page 1
    if "composition_summary" in data:
        non_mand = data["composition_summary"].get("non_mandatory_pieces", [])
        for nm in non_mand:
            if nm.get("status") == "NOT_APPLICABLE_STAGE" or nm.get("criticality") == "Stage_Optional":
                if nm.get("start_page") == 1 and nm.get("end_page") == 1 and not nm.get("file_name"):
                    nm["start_page"] = None
                    nm["end_page"] = None
                    nm["pages_display"] = "—"
                    nm["is_received"] = False

    updated_json = json.dumps(data, ensure_ascii=False)
    c.execute("UPDATE arh_dossiers SET data_json = ? WHERE dossier_id = ?", (updated_json, dossier_id))
    print(f"Updated dossier: {dossier_id}")

conn.commit()
conn.close()
print("Database update successfully committed!")
