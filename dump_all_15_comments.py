import sqlite3
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('arh_dossiers.db')
c = conn.cursor()
c.execute("SELECT data_json FROM arh_dossiers WHERE dossier_id='DOSSIER_ARH_26307CC5'")
data = json.loads(c.fetchone()[0])
conn.close()

comments = data.get('comments', [])
for i, c in enumerate(comments):
    print(f"================ COMMENT [{i:02d}] ================")
    for k in ['id', 'title', 'page', 'page_number', 'resolved_page_num', 'document_concerned', 'piece_code', 'target_content', 'quote_snippet', 'snippet', 'action_required', 'observation']:
        print(f"  {k}: {c.get(k)}")

