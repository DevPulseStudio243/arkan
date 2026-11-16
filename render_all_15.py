import sqlite3
import json
import os
import sys
from arh_pdf_annotator import ARHPDFAnnotator

sys.stdout.reconfigure(encoding='utf-8')

os.makedirs('test_renders', exist_ok=True)
annotator = ARHPDFAnnotator(uploads_dir="arh_uploads")

conn = sqlite3.connect('arh_dossiers.db')
c = conn.cursor()
c.execute("SELECT data_json FROM arh_dossiers WHERE dossier_id='DOSSIER_ARH_26307CC5'")
data = json.loads(c.fetchone()[0])
conn.close()

comments = data.get('comments', [])
fname = data['files'][0]

print(f"Testing {len(comments)} comments on {fname}...")

for i, comm in enumerate(comments):
    cid = comm.get('id')
    pnum = comm.get('page_number')
    title = comm.get('title', '')
    snip = comm.get('snippet') or comm.get('target_content') or comm.get('quote_snippet') or ''
    
    png_bytes = annotator.render_page_to_png(
        'DOSSIER_ARH_26307CC5',
        fname,
        pnum,
        target_snippet=snip,
        target_title=title,
        highlight_enabled=True
    )
    
    out_file = f"test_renders/rem_{i:02d}_page_{pnum}_{cid}.png"
    with open(out_file, 'wb') as f:
        f.write(png_bytes)
    print(f"[{i:02d}] P.{pnum:02d} -> {out_file} ({len(png_bytes)} bytes) | snip: '{snip}' | title: '{title[:35]}'")
print("All 15 rendered successfully!")
