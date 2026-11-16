import sqlite3, json, sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


con = sqlite3.connect('d:/DATA BASE IA/arh_dossiers.db')
cur = con.cursor()
for (d_id, raw_json) in cur.execute("SELECT dossier_id, data_json FROM arh_dossiers").fetchall():
    print(f"==================== DOSSIER: {d_id} ====================")
    d = json.loads(raw_json)
    for i, c in enumerate(d.get('comments', [])):
        print(f"\n--- Comment {i+1} ---")
        print(f"Title: {c.get('title')}")
        print(f"Doc: {c.get('document_concerned')}")
        print(f"Page: {c.get('page')} (num: {c.get('page_number')})")
        print(f"Snippet: {c.get('quote_snippet')}")
        print(f"Target Content: {c.get('target_content')}")
        print(f"Observation: {c.get('observation')}")

