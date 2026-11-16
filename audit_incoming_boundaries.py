import os
import sys
from pathlib import Path
import fitz

from arh_document_slicer import ARHDocumentSlicer

slicer = ARHDocumentSlicer()
arh_base = Path(r"C:\Users\MSI\Desktop\arh")

incoming_files = []
for root, dirs, files in os.walk(arh_base):
    for f in files:
        if f.lower().endswith(".pdf"):
            full_p = os.path.join(root, f)
            rel_p = os.path.relpath(full_p, arh_base)
            if "incoming" in rel_p.lower() or "incomming" in rel_p.lower():
                incoming_files.append((rel_p, full_p))

print(f"Total incoming files: {len(incoming_files)}")

results = []
for rel, full_p in incoming_files:
    sz_kb = round(os.path.getsize(full_p) / 1024, 1)
    if sz_kb < 500:
        continue
    try:
        doc = fitz.open(full_p)
        total_p = len(doc)
        if total_p < 3:
            doc.close()
            continue
        bounds = slicer.identify_boundaries(doc)
        doc.close()
        valid_bounds = [b for b in bounds if b.get("start", 0) > 0 and not b.get("is_na", False)]
        results.append({
            "rel": rel,
            "pages": total_p,
            "bounds_count": len(bounds),
            "valid_count": len(valid_bounds),
            "codes": [b["spec"]["code"] for b in bounds]
        })
    except Exception as e:
        results.append({
            "rel": rel,
            "error": str(e)
        })

print(f"\nTested {len(results)} multi-page dossiers (>500KB and >3 pages):")
zero_cuts = [r for r in results if r.get("bounds_count", 0) == 0 or "error" in r]
few_cuts = [r for r in results if 0 < r.get("bounds_count", 0) < 5]
good_cuts = [r for r in results if r.get("bounds_count", 0) >= 5]

print(f"Good cuts (>=5): {len(good_cuts)}")
print(f"Few cuts (1..4): {len(few_cuts)}")
print(f"Zero cuts / errors (0): {len(zero_cuts)}")

if zero_cuts:
    print("\n--- ZERO CUTS OR ERRORS ---")
    for r in zero_cuts[:20]:
        print(f"  {r.get('rel')} (pages: {r.get('pages', '?')}): error={r.get('error')}")

if few_cuts:
    print("\n--- FEW CUTS (1..4) ---")
    for r in few_cuts[:20]:
        print(f"  {r.get('rel')} (pages: {r.get('pages')}) -> {r.get('bounds_count')} pieces: {r.get('codes')}")
