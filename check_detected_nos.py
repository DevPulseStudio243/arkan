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

print("=== CHECKING ITEM NUMBERS ON EACH SHEET IN REDACTED PDF ===")
for page_idx in range(2, 33):
    sheet_no = page_idx + 1
    p = doc_red[page_idx]
    words = p.get_text('words')
    d_words = [w for w in words if w[0] < 815 and w[1] < 670]
    
    # Extract all F<n>, G<n>, B<n>, S<n>
    prefixed = set()
    for w in d_words:
        m = re.match(r'^([FGBS])(\d{1,2})$', w[4].strip())
        if m:
            prefixed.add((m.group(1), int(m.group(2))))
            
    # Extract standalone numbers that could be item callouts
    standalone = set()
    for w in d_words:
        txt = w[4].strip()
        if re.match(r'^\d{1,2}$', txt):
            val = int(txt)
            # Filter out obvious coordinate or dimension numbers
            # Usually coordinates have decimals or are > 25, or near E/N/EL
            # In our sheets, item numbers are between 1 and 25
            if 1 <= val <= 25:
                standalone.add(val)
                
    sh_orig = by_sheet_orig[sheet_no]
    orig_nos = set(it['item_no'] for it in sh_orig)
    
    all_detected_nos = set(n for prefix, n in prefixed) | standalone
    # Item 1 and 2 are usually PIPE, which might be in cut spools <1>, <2>
    cut_spools = set(int(m[0]) for m in re.findall(r'<(\d+)>', p.get_text()))
    
    missing_nos = orig_nos - all_detected_nos
    extra_nos = (all_detected_nos - orig_nos) - {22} # 22 is sometimes weld or code
    
    print(f"Sheet {sheet_no:02d}: Orig count={len(orig_nos)}, Detected={sorted(all_detected_nos)} | Missing from orig={sorted(missing_nos)}")
