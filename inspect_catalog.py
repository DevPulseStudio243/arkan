from dwg_iso_extractor import extract_iso_from_pdf
from collections import defaultdict
import json

res = extract_iso_from_pdf(r'C:\Users\MSI\Desktop\C3421-ROK1-300-PIG-DW-300016_ORIGINAL_BACKUP.pdf')
items = res['bom_items']

# Group items by (category, size, item type)
catalog = {}
for it in items:
    cat = it['category']
    sz = it['size']
    desc = it['description']
    # Extract short type
    k = (cat, sz, desc[:40])
    if k not in catalog:
        catalog[k] = {
            "category": cat,
            "size": sz,
            "description": desc,
            "schedule": it.get("schedule", ""),
            "rating": it.get("rating", ""),
            "material": it.get("material", ""),
            "unit": it.get("unit", "EA"),
            "count": 0,
            "sheets": set()
        }
    catalog[k]["count"] += 1
    catalog[k]["sheets"].add(it.get("sheet_page"))

print(f"Total catalog components: {len(catalog)}")
for k, v in sorted(catalog.items(), key=lambda x: (x[0][0], x[0][1])):
    print(f"[{v['category']}] {v['size']} -> {v['description'][:60]} | rating={v['rating']} | mat={v['material']} | {v['count']} occurrences on sheets {sorted(v['sheets'])}")
