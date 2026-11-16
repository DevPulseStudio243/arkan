import fitz
import re
from collections import defaultdict
from dwg_iso_extractor import extract_iso_from_pdf

doc_red = fitz.open(r'C:\Users\MSI\Desktop\C3421-ROK1-300-PIG-DW-300016.pdf')
res_orig = extract_iso_from_pdf(r'C:\Users\MSI\Desktop\C3421-ROK1-300-PIG-DW-300016_ORIGINAL_BACKUP.pdf')
items_orig = res_orig['bom_items']

pipe_orig_by_sheet = defaultdict(dict)
for it in items_orig:
    if it['category'] == 'PIPE':
        sh = it['sheet_page']
        sz = it['size'].replace('"', '')
        pipe_orig_by_sheet[sh][sz] = it['quantity']

print("=== COMPARING SPOOL SUMS VS BOM PIPE QUANTITIES ===")
matches = 0
total_checked = 0
for page_idx in range(2, 33):
    sheet_no = page_idx + 1
    p = doc_red[page_idx]
    txt = p.get_text()
    cut_section = re.search(r'CUT\s*PIPE\s*LENGTH([\s\S]+?)(?:3-[A-Z0-9\-]+|CONT\.\s*ON|PIPING\s*SPEC|BATCH|$)', txt, re.I)
    target = cut_section.group(1) if cut_section else txt
    cut_matches = re.findall(r'<(\d+)>\s+(\d{2,5})\s+(\d+(?:/\d+)?)', target)
    
    spool_by_sz = defaultdict(float)
    for p_id, l_mm, sz in cut_matches:
        spool_by_sz[sz] += float(l_mm) / 1000.0
        
    orig_pipes = pipe_orig_by_sheet.get(sheet_no, {})
    total_checked += len(orig_pipes)
    print(f"Sheet {sheet_no}:")
    for sz, q_bom in orig_pipes.items():
        q_spool = round(spool_by_sz.get(sz, 0.0), 1)
        diff = abs(q_bom - q_spool)
        ok = diff <= 0.1
        if ok:
            matches += 1
        print(f"   {sz}\": BOM={q_bom}m | SPOOL={q_spool}m -> {'OK' if ok else 'DIFF'}")

print(f"\nResult: {matches}/{total_checked} matched within 0.1m")
