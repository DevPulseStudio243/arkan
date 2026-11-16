from benchmark_full_reconstruction import reconstruct_sheet_items
from dwg_iso_extractor import extract_iso_from_pdf
from collections import defaultdict
import fitz

doc_red = fitz.open(r'C:\Users\MSI\Desktop\C3421-ROK1-300-PIG-DW-300016.pdf')
res_orig = extract_iso_from_pdf(r'C:\Users\MSI\Desktop\C3421-ROK1-300-PIG-DW-300016_ORIGINAL_BACKUP.pdf')
items_orig = res_orig['bom_items']
by_sheet_orig = defaultdict(list)
for it in items_orig:
    by_sheet_orig[it['sheet_page']].append(it)

print("=== DETAILED MISMATCH AUDIT ===")
for page_idx in range(2, 33):
    sheet_no = page_idx + 1
    sh_orig = by_sheet_orig[sheet_no]
    sh_recon = reconstruct_sheet_items(doc_red, page_idx)
    recon_by_no = {it["item_no"]: it for it in sh_recon}
    
    mismatches = []
    for it in sh_orig:
        no = it["item_no"]
        rec = recon_by_no.get(no)
        if not rec:
            mismatches.append(f"  Missing item #{no}: Orig [{it['category']}] {it['size']} {it['description'][:40]}")
        elif rec["category"] != it["category"]:
            mismatches.append(f"  Category mismatch #{no}: Orig=[{it['category']}] vs Recon=[{rec['category']}] | Orig: {it['description'][:40]} | Recon: {rec['description'][:40]}")
            
    # Also check extra items in recon
    orig_nos = set(it["item_no"] for it in sh_orig)
    extra = [it for it in sh_recon if it["item_no"] not in orig_nos]
    
    if mismatches or extra:
        print(f"\n--- Sheet {sheet_no:02d} ---")
        for m in mismatches:
            print(m)
        for ex in extra:
            print(f"  Extra in Recon #{ex['item_no']}: [{ex['category']}] {ex['size']} {ex['description'][:40]}")
