import os
import fitz
from arh_document_slicer import ARHDocumentSlicer

slicer = ARHDocumentSlicer()
base_dir = r"C:\Users\MSI\Desktop\arh"

results = []
for root, dirs, files in os.walk(base_dir):
    if "incoming" in root.lower():
        for f in files:
            if f.lower().endswith(".pdf"):
                p = os.path.join(root, f)
                try:
                    doc = fitz.open(p)
                    bounds = slicer.identify_boundaries(doc)
                    valid_cuts = [b for b in bounds if b.get("start", 0) > 0 and not b.get("is_na", False)]
                    zero_cuts = [b for b in bounds if b.get("start", 0) == 0 or b.get("is_na", False)]
                    results.append({
                        "path": p,
                        "name": f,
                        "pages": len(doc),
                        "total_cuts": len(bounds),
                        "valid_cuts": len(valid_cuts),
                        "zero_cuts": len(zero_cuts)
                    })
                except Exception as e:
                    results.append({
                        "path": p,
                        "name": f,
                        "pages": 0,
                        "error": str(e)
                    })

print(f"Total PDFs audited: {len(results)}")
broken = [r for r in results if r.get("zero_cuts", 0) > 0 or (r.get("pages", 0) > 10 and r.get("valid_cuts", 0) <= 2)]
print(f"Broken / severely degraded slicing: {len(broken)} / {len(results)}")
for b in broken:
    rel = os.path.relpath(b["path"], base_dir)
    print(f"  [FAIL] {rel} (Pages: {b['pages']}) -> Valid: {b.get('valid_cuts')}, Zero/NA: {b.get('zero_cuts')}")
