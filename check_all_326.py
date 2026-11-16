import fitz
import math
import re
from collections import defaultdict
from dwg_iso_extractor import extract_iso_from_pdf

doc_red = fitz.open(r'C:\Users\MSI\Desktop\C3421-ROK1-300-PIG-DW-300016.pdf')
res_orig = extract_iso_from_pdf(r'C:\Users\MSI\Desktop\C3421-ROK1-300-PIG-DW-300016_ORIGINAL_BACKUP.pdf')
items_orig = res_orig['bom_items']
by_sheet_orig = defaultdict(list)
for it in items_orig:
    by_sheet_orig[it['sheet_page']].append(it)

print("=== CHECKING HOW EVERY BOM ITEM MAPS TO DRAWING TEXT ===")
total_items = 0
identified_items = 0

for page_idx in range(2, 33):
    sheet_no = page_idx + 1
    p = doc_red[page_idx]
    words = p.get_text('words')
    d_words = [w for w in words if w[0] < 815 and w[1] < 670]
    sh_orig = by_sheet_orig[sheet_no]
    total_items += len(sh_orig)
    
    for it in sh_orig:
        no = str(it['item_no'])
        cat = it['category']
        sz = it['size']
        desc = it['description']
        
        # Check F, G, B, S prefix
        found_how = None
        has_f = any(w[4] == f'F{no}' for w in d_words)
        has_g = any(w[4] == f'G{no}' for w in d_words)
        has_b = any(w[4] == f'B{no}' for w in d_words)
        has_s = any(w[4] == f'S{no}' for w in d_words)
        if has_f: found_how = f"F{no}"
        elif has_g: found_how = f"G{no}"
        elif has_b: found_how = f"B{no}"
        elif has_s: found_how = f"S{no}"
        elif cat == 'PIPE':
            found_how = "PIPE_TABLE"
        else:
            # Standalone number matching
            matching_words = [w for w in d_words if w[4] == no]
            if matching_words:
                # Find near words
                tw = matching_words[0]
                neighbors = [nw[4] for nw in d_words if math.hypot(nw[0]-tw[0], nw[1]-tw[1]) < 60.0 and nw != tw]
                found_how = f"CALLOUT_{no}: {' '.join(neighbors[:5])}"
            elif any(k in desc.upper() for k in ('STD-280', 'STD-248', 'STD-246', 'STD-131')):
                found_how = "SUPPORT_STD"
            elif any(k in desc.upper() for k in ('GATE', 'BALL', 'VALVE', 'CHECK', 'TSV')):
                found_how = "VALVE_TAG"
            elif any(k in desc.upper() for k in ('ORIFICE', 'RO-301', 'RO-302', 'INSULATION KIT')):
                found_how = "INST_TAG"
                
        if found_how:
            identified_items += 1
        else:
            print(f"Sheet {sheet_no:02d} #{no} [{cat}] {sz} NOT IDENTIFIED: {desc[:40]}")

print(f"\nFinal: {identified_items}/{total_items} items identified ({identified_items/total_items*100:.1f}%)")
