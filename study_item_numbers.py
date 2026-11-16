import fitz
import re
from collections import defaultdict
from dwg_iso_extractor import extract_iso_from_pdf

doc_red = fitz.open(r'C:\Users\MSI\Desktop\C3421-ROK1-300-PIG-DW-300016.pdf')
res_orig = extract_iso_from_pdf(r'C:\Users\MSI\Desktop\C3421-ROK1-300-PIG-DW-300016_ORIGINAL_BACKUP.pdf')
items_orig = res_orig['bom_items']

by_sheet_orig = defaultdict(list)
for it in items_orig:
    by_sheet_orig[it['sheet_page']].append(it)

print("=== STUDYING ALL NON-PIPE ITEMS ON 5 DIVERSE SHEETS ===")
test_sheets = [3, 9, 11, 16, 22]

for sh in test_sheets:
    page_idx = sh - 1
    p = doc_red[page_idx]
    words = p.get_text('words')
    d_words = [w for w in words if w[0] < 815 and w[1] < 670]
    d_txt = ' '.join(w[4] for w in d_words)
    
    print(f"\n--- SHEET {sh} (Page {page_idx}) ---")
    orig_items = by_sheet_orig[sh]
    for it in orig_items:
        no = it['item_no']
        cat = it['category']
        sz = it['size']
        qty = it['quantity']
        u = it['unit']
        desc = it['description'][:50]
        
        # Search for occurrences of 'no' in drawing words
        # 1. Exact match on number
        exact_no_words = [w for w in d_words if w[4] == str(no)]
        # 2. Prefixed: F<no>, G<no>, B<no>, S<no>
        prefixed_words = [w for w in d_words if w[4] in (f"F{no}", f"G{no}", f"B{no}", f"S{no}")]
        # 3. Tags or other text
        print(f"  Item #{no} [{cat}] {sz} (Qty {qty} {u}) - {desc}")
        print(f"      Exact matches on '{no}': {len(exact_no_words)}, Prefixed: {[w[4] for w in prefixed_words]}")
