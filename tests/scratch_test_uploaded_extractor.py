import sys, os
sys.path.insert(0, r"C:\Users\MSI\.gemini\antigravity\brain\7cc98ab2-f2f2-422e-8a4e-5ed1c47aa104\.user_uploaded\extracted_new")
sys.path.insert(1, r"D:\DATA BASE IA")

import importlib.util
spec = importlib.util.spec_from_file_location(
    "uploaded_extractor",
    r"C:\Users\MSI\.gemini\antigravity\brain\7cc98ab2-f2f2-422e-8a4e-5ed1c47aa104\.user_uploaded\extracted_new\ie_drawing_extractor.py"
)
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)

dxf_path = r"C:\Users\MSI\Desktop\1\C2723-GCB-000-ELE-PLA-006 Plan de cheminement.dxf"
res = extractor.extract_ie_drawing(dxf_path)
items = res.get("items", [])
meta = res.get("metadata", {})
print("Extracted items:", len(items))
print("Metadata units:", meta.get("units"), "scale:", meta.get("scale_to_m"), "warnings:", meta.get("warnings"))

from collections import defaultdict
cats = defaultdict(lambda: {"count": 0, "qty": 0.0, "unit": ""})
for it in items:
    cat = it.get("category")
    u = it.get("unit")
    q = float(it.get("quantity") or 0.0)
    cats[cat]["count"] += 1
    cats[cat]["qty"] += q
    cats[cat]["unit"] = u

for cat, data in sorted(cats.items()):
    print(f" {cat:<22}: count={data['count']:2d} | qty={data['qty']:10.1f} {data['unit']}")
