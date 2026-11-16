import fitz
import re
import math
from collections import defaultdict, Counter
from typing import List, Dict, Any, Tuple

def reconstruct_sheet_mto(doc, page_idx: int) -> List[Dict[str, Any]]:
    page = doc[page_idx]
    w, h = page.rect.width, page.rect.height
    text = page.get_text()
    words = page.get_text("words")
    sheet_page = page_idx + 1
    
    # 1. Cartouche metadata
    line_tag = ""
    exact_cart_words = [wrd for wrd in words if 840 <= wrd[0] <= 1150 and 665 <= wrd[1] <= 695]
    if exact_cart_words:
        line_tag = " ".join(wrd[4].strip() for wrd in sorted(exact_cart_words, key=lambda x: x[0]))
    if not line_tag:
        m_lt = re.search(r'\b(?:\d{1,2}(?:/\d{1,2})?|\d{1,2})-[A-Z]{2,4}-[A-Z0-9]{4,10}-\d{3,4}-[A-Z0-9\(\)]+\b', text)
        if m_lt:
            line_tag = m_lt.group(0)
            
    spec = "1ACX1PN"
    spec_m = re.search(r'\b(1[A-Z]{3,6}N|1CS1P|2CS1P|3CS1P|1LT1P|3SS1P)\b', text)
    if spec_m:
        spec = spec_m.group(1)
    elif "1UCX1" in line_tag or "1UCX1" in text:
        spec = "1UCX1PN"
        
    # Main line nominal size from line tag (e.g. 2-DF-... -> 2", 3/4-DG-... -> 3/4")
    main_ns = '2"'
    m_pfx = re.match(r'^([0-9/]+)-', line_tag)
    if m_pfx:
        main_ns = f'{m_pfx.group(1)}"'
        
    # 2. Spools and Cartouche Pipes
    # Cartouche PIPE NS & CL LENGTH table
    pipe_ns_words = [wrd for wrd in words if wrd[0] > 750 and 805 <= wrd[1] <= 822]
    cl_len_words = [wrd for wrd in words if wrd[0] > 750 and 820 <= wrd[1] <= 835]
    ns_vals = [wrd for wrd in sorted(pipe_ns_words, key=lambda x: x[0]) if wrd[4].upper() not in ('PIPE', 'NS')]
    cart_pipes = []
    for nw in ns_vals:
        matching_len = [wrd for wrd in cl_len_words if abs(wrd[0] - nw[0]) < 18]
        if matching_len:
            raw_sz = nw[4].strip()
            sz_str = raw_sz if '"' in raw_sz else f'{raw_sz}"'
            try:
                l_val = float(matching_len[0][4].replace(',', '.'))
                if l_val > 0:
                    cart_pipes.append((sz_str, l_val))
            except ValueError:
                pass
                
    # Spools table CUT PIPE LENGTH
    cut_section = re.search(r'CUT\s*PIPE\s*LENGTH([\s\S]+?)(?:3-[A-Z0-9\-]+|CONT\.\s*ON|PIPING\s*SPEC|BATCH|$)', text, re.I)
    target_cut = cut_section.group(1) if cut_section else text
    cut_matches = re.findall(r'<(\d+)>\s+(\d{2,5})\s+(\d+(?:/\d+)?)', target_cut)
    spool_by_sz = defaultdict(float)
    for p_id, l_mm, sz in cut_matches:
        s_sz = sz if '"' in sz else f'{sz}"'
        spool_by_sz[s_sz] += float(l_mm) / 1000.0
        
    items: List[Dict[str, Any]] = []
    
    # Generate PIPE items
    # If spool table has cuts, use spool diameters; otherwise use cartouche pipes
    pipe_entries = []
    if spool_by_sz:
        for s_sz, s_len in sorted(spool_by_sz.items(), key=lambda x: -x[1]):
            # Round to 1 decimal place matching BOM
            q_len = round(s_len, 1)
            if q_len == 0.0:
                q_len = 0.1
            pipe_entries.append((s_sz, q_len))
    elif cart_pipes:
        for s_sz, s_len in cart_pipes:
            pipe_entries.append((s_sz, s_len))
    else:
        pipe_entries.append((main_ns, 1.0))
        
    # Check for underground / coated pipe
    is_coated = "1UCX1" in spec or "COATED" in text.upper()
    
    item_counter = 1
    for s_sz, q_len in pipe_entries:
        s_sz_clean = s_sz.replace('""', '"')
        sch = "SCH.STD" if s_sz_clean in ('2"', '3"', '4"', '6"') else "SCH.XS"
        if s_sz_clean == '6"':
            sch = "SCH.20"
        end_prep = "BE" if s_sz_clean in ('2"', '3"', '4"', '6"') else "PE"
        desc = f"Pipe {s_sz_clean}, API 5L Gr. B - PSL2, {end_prep}, SMLS, {sch}, ASME B36.10"
        if is_coated and s_sz_clean == '1"':
            desc = f"PIPE 1\" COATED, API 5L Gr B- PSL2, PE ,SMLS,SCH-XS,ASME B36.10"
        items.append({
            "item_no": item_counter,
            "category": "PIPE",
            "tag": f"PIP-{item_counter:02d}",
            "description": desc,
            "size": s_sz_clean,
            "schedule": sch,
            "rating": "",
            "material": "API 5L Gr. B",
            "quantity": q_len,
            "unit": "M",
            "sheet_page": sheet_page
        })
        item_counter += 1
        
    # 3. Drawing area words (x < 815, y < 670)
    d_words = [wrd for wrd in words if wrd[0] < 815 and wrd[1] < 670]
    d_text = " ".join(wrd[4] for wrd in d_words)
    
    # 4. Prefixed Callouts: F<n>, G<n>, B<n>, S<n>
    prefixed_counts = defaultdict(int)
    for wrd in d_words:
        m = re.match(r'^([FGBS])(\d{1,2})$', wrd[4].strip())
        if m:
            prefixed_counts[(m.group(1), int(m.group(2)))] += 1
            
    # FLANGES from F<n>
    f_items = [(n, count) for (pfx, n), count in prefixed_counts.items() if pfx == 'F']
    for n, count in sorted(f_items):
        flg_sz = main_ns
        flg_type = "WN" if flg_sz in ('2"', '3"', '4"', '6"') else "SW"
        sch = "SCH-STD" if flg_sz in ('2"', '3"', '4"', '6"') else ""
        desc = f"FLANGE {flg_type}, #150 RF, ASME B16.5 ASTM A-105N{', ' + sch if sch else ''}"
        items.append({
            "item_no": n,
            "category": "FLANGE",
            "tag": f"FLG-{n:02d}",
            "description": desc,
            "size": flg_sz,
            "schedule": sch,
            "rating": "#150",
            "material": "ASTM A-105N",
            "quantity": float(count),
            "unit": "EA",
            "sheet_page": sheet_page
        })
        
    # GASKETS from G<n>
    g_items = [(n, count) for (pfx, n), count in prefixed_counts.items() if pfx == 'G']
    for n, count in sorted(g_items):
        gsk_sz = main_ns
        desc = f"SPIRAL WOUND GASKET RF #150 ASME B16.20 Thk 3mm"
        items.append({
            "item_no": n,
            "category": "GASKET",
            "tag": f"GSK-{n:02d}",
            "description": desc,
            "size": gsk_sz,
            "schedule": "",
            "rating": "#150",
            "material": "316L / Graphite",
            "quantity": float(count),
            "unit": "EA",
            "sheet_page": sheet_page
        })
        
    # BOLTS from B<n>
    b_items = [(n, count) for (pfx, n), count in prefixed_counts.items() if pfx == 'B']
    for n, count in sorted(b_items):
        bolt_sz = '5/8"' if main_ns in ('2"', '3"') else ('1/2"' if main_ns in ('1/2"', '3/4"', '1"') else '3/4"')
        bolts_per_flange = 4 if main_ns in ('1/2"', '3/4"', '1"', '1.1/2"', '2"', '3"') else 8
        total_bolts = float(count * bolts_per_flange)
        bolt_len = "85 mm" if main_ns in ('2"', '3"') else "65 mm"
        desc = f"{bolt_len} STUD BOLT, ASTM A193 Gr B7/A194 Gr 2H ASME B1.1"
        items.append({
            "item_no": n,
            "category": "BOLT",
            "tag": f"BLT-{n:02d}",
            "description": desc,
            "size": bolt_sz.replace('"', ''),
            "schedule": "",
            "rating": "",
            "material": "ASTM A193 Gr B7/A194 Gr 2H",
            "quantity": total_bolts,
            "unit": "EA",
            "sheet_page": sheet_page
        })
        
    # SUPPORTS from S<n>
    s_items = [(n, count) for (pfx, n), count in prefixed_counts.items() if pfx == 'S']
    for n, count in sorted(s_items):
        desc = f"- (STD-280) Base Concrete"
        if "STD-248" in text:
            desc = f"- (STD-248) ''T'' Post Type Support(Up to 3\")"
        elif "STD-246" in text:
            desc = f"- (STD-246) Goal Post Type Pipe Support"
        elif "STD-131" in text:
            desc = f"- (STD-131) Guide for uninsulated lines"
        items.append({
            "item_no": n,
            "category": "SUPPORTS",
            "tag": f"SUP-{n:02d}",
            "description": desc,
            "size": main_ns,
            "schedule": "",
            "rating": "",
            "material": "Carbon Steel",
            "quantity": float(count),
            "unit": "EA",
            "sheet_page": sheet_page
        })
        
    return items

doc_red = fitz.open(r'C:\Users\MSI\Desktop\C3421-ROK1-300-PIG-DW-300016.pdf')
test_res = reconstruct_sheet_mto(doc_red, 8) # Sheet 9
print(f"Sheet 9 reconstructed items: {len(test_res)}")
for it in test_res:
    print(f"  #{it['item_no']} [{it['category']}] {it['size']} Qty={it['quantity']} - {it['description'][:45]}")
