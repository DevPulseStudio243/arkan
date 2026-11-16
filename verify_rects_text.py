import sqlite3
import json
import fitz
import sys
from arh_pdf_annotator import ARHPDFAnnotator

sys.stdout.reconfigure(encoding='utf-8')

annotator = ARHPDFAnnotator(uploads_dir="arh_uploads")

conn = sqlite3.connect('arh_dossiers.db')
c = conn.cursor()
c.execute("SELECT data_json FROM arh_dossiers WHERE dossier_id='DOSSIER_ARH_26307CC5'")
data = json.loads(c.fetchone()[0])
conn.close()

comments = data.get('comments', [])
fname = data['files'][0]
doc_path = f"arh_uploads/DOSSIER_ARH_26307CC5/{fname}"
doc = fitz.open(doc_path)

print(f"Checking 15 comments on {fname} (73 pages)...")

for i, comm in enumerate(comments):
    cid = comm.get('id')
    pnum = comm.get('page_number')
    title = comm.get('title', '')
    snip = comm.get('snippet') or comm.get('target_content') or comm.get('quote_snippet') or ''
    
    page = doc[pnum - 1]
    rects = annotator.find_target_rects(page, title=title, snippet=snip, target_content=snip)
    
    print(f"\n--- [{i:02d}] {cid} | Page {pnum} | Title: '{title[:40]}' ---")
    print(f"    Expected Snippet: '{snip}'")
    if not rects:
        print("    ❌ NO RECTS FOUND!")
    else:
        for r in rects:
            # Extract text inside rect with small padding
            r_pad = fitz.Rect(r.x0 - 2, r.y0 - 2, r.x1 + 2, r.y1 + 2)
            extracted = page.get_textbox(r_pad).strip().replace('\n', ' ')
            print(f"    Target Rect: {r} -> Text inside: '{extracted}'")

doc.close()
