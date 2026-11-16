import fitz
import sys

sys.stdout.reconfigure(encoding='utf-8')

pdf_path = 'arh_uploads/DOSSIER_ARH_A6484846/PST 3.24 - GCB CS 19 - Dossier Preliminaire ARH - FITTINGS - ZICN - REV0 (002).pdf'
doc = fitz.open(pdf_path)

print(f"Total pages: {len(doc)}")

# Look for text on all pages that have annotations or stamps
for p in range(len(doc)):
    txt = doc[p].get_text()
    if any(k in txt.lower() for k in [
        'remarque', 'reserve', 'erreur', 'note', 'corriger', 'conforme', 
        'consulat', 'etat descriptif', 'b31.3', 'b16.9', 'zicn', 'itp'
    ]):
        # Check if there are handwritten/drawn annotations
        annots = list(doc[p].annots()) if doc[p].annots() else []
        print(f"Page {p+1}: len={len(txt)}, annots={len(annots)}")

doc.close()
