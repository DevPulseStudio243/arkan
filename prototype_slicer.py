import re
import fitz
from typing import List, Dict, Any, Optional

def normalize(text: str) -> str:
    import unicodedata
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', text)
    cleaned = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return re.sub(r'[^A-Z0-9\s/_\-]', ' ', cleaned.upper())

def is_running_header(line: str) -> bool:
    norm = normalize(line)
    # Exclude: "DOC. N° 1 À 10", "DOC 1 TO 10", "DOC. 1 - 10"
    if re.search(r'\bDOC(?:UMENT)?\.?\s*N[°O]?\s*\d+\s*(?:A|TO|\-)\s*\d+\b', norm):
        return True
    if any(h in norm for h in ['FIELD DEVELOPMENT', 'PROVISION OF', 'HASSI BIR REKAIZ', 'DUSSELDORF', 'GCB CF']):
        return True
    return False

def test_enhanced_slice(pdf_path: str):
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    print(f"\n==========================================")
    print(f"Testing: {pdf_path}")
    print(f"Total Pages: {total_pages}")
    
    # Tier 1: Sommaire
    sommaire_page_idx = None
    sommaire_text = ""
    
    for p_idx in range(min(6, total_pages)):
        txt = doc[p_idx].get_text()
        u = normalize(txt)
        # Check Sommaire / Table des matières / Index / PRELIMINARY ARH DOSSIER
        is_somm = any(h in u for h in ['SOMMAIRE', 'TABLE OF CONTENTS', 'TABLE DES MATIERES', 'INDEX DES PIECES', 'INDEX DES DOCUMENTS'])
        is_arh_table = 'PRELIMINANRY ARH DOSSIER' in u or 'PRELIMINARY ARH DOSSIER' in u or (re.search(r'\bDOSSIER\s+PRELIMINAIRE\b', u) and re.search(r'\bPAGE\b', u))
        if (is_somm or is_arh_table) and any(w in u for w in ['DEMANDE', 'COMMERCE', 'CALCUL', 'WPS', 'DESCRIPTIF', 'MATERIELS', 'LIST', 'VALVE', 'CERTIFICAT', 'INSPECTION', 'DOCUMENT']):
            sommaire_page_idx = p_idx
            sommaire_text = txt
            break
            
    cuts = []
    if sommaire_page_idx is not None:
        print(f"Sommaire found on page {sommaire_page_idx + 1}")
        blocks = doc[sommaire_page_idx].get_text('blocks')
        raw_lines = [l.strip() for l in sommaire_text.split('\n') if l.strip()]
        
        # Pattern for items: "1.", "1.1", "1 -", "1 )", or number alone on its line followed by text
        marker_pat = re.compile(r'^\s*([0-9]{1,2}(?:\.[0-9]{1,2})?|[IVXLCDM]{1,6})\s*(?:[\.\-\)]\s*(.*)|$)', re.I)
        
        items_raw = []
        current_item = None
        for line in raw_lines:
            if is_running_header(line):
                continue
            m = marker_pat.match(line)
            # Make sure it's an item number, not page or revision
            if m and (m.group(1).isdigit() and int(float(m.group(1))) <= 15):
                # Don't treat standalone "02" or year "2026" as an item if after item 10
                num_val = float(m.group(1))
                if current_item and num_val < float(current_item['num']) and num_val != 1:
                    # Possibly a page number or revision date, not a new item
                    current_item['lines'].append(line)
                    continue
                if current_item:
                    items_raw.append(current_item)
                item_rem = m.group(2).strip() if (m.lastindex >= 2 and m.group(2)) else ""
                current_item = {'num': m.group(1), 'lines': [item_rem] if item_rem else []}
            else:
                if current_item:
                    current_item['lines'].append(line)
        if current_item:
            items_raw.append(current_item)
            
        print(f"Found {len(items_raw)} items in Sommaire: {[it['num'] for it in items_raw]}")
        
        # Extract page numbers from Sommaire
        items_with_pages = []
        
        # Spatial number blocks
        num_blocks = []
        for b in blocks:
            txt_b = b[4].strip()
            b_lines = [l.strip() for l in txt_b.split('\n') if l.strip()]
            for bl in b_lines:
                if bl.isdigit() or bl.upper() in ['N/A', 'NA', 'NON APPLICABLE', 'NOT APPLICABLE']:
                    # Only numbers that could be page numbers in this document
                    if bl.isdigit() and 1 <= int(bl) <= total_pages:
                        num_blocks.append({'rect': b[:4], 'val': bl, 'y0': b[1], 'y1': b[3]})
                    elif not bl.isdigit():
                        num_blocks.append({'rect': b[:4], 'val': bl, 'y0': b[1], 'y1': b[3]})
                        
        for itm in items_raw:
            full_txt = " ".join(itm['lines']).strip()
            # 1. Inline check
            p_match = re.search(r'(?:[\.\s_]{2,}|\s+)(\d{1,3}|N/?A)\s*$', full_txt, re.I)
            p_val = None
            if p_match:
                p_val = p_match.group(1).strip()
                title = full_txt[:p_match.start()].strip(' .-_')
            else:
                # 2. Spatial matching: find block whose Y is close to item block
                item_y = None
                for b in blocks:
                    if itm['num'] in b[4] and (not itm['lines'] or any(w in b[4] for w in itm['lines'][0].split()[:3])):
                        item_y = (b[1] + b[3]) / 2.0
                        break
                if item_y is not None:
                    closest_nb = None
                    min_dy = 999
                    for nb in num_blocks:
                        nb_y = (nb['y0'] + nb['y1']) / 2.0
                        dy = abs(nb_y - item_y)
                        if dy < 25 and dy < min_dy:
                            min_dy = dy
                            closest_nb = nb
                    if closest_nb:
                        p_val = closest_nb['val']
                title = full_txt
                
            items_with_pages.append({
                'num': itm['num'],
                'title': title,
                'page': int(p_val) if (p_val and p_val.isdigit()) else (0 if p_val and 'N' in p_val.upper() else None)
            })
            
        valid_with_pages = [x for x in items_with_pages if x['page'] is not None and x['page'] > 0]
        print(f"Items with resolved pages from Sommaire: {len(valid_with_pages)} / {len(items_with_pages)}")
        
        # If no pages resolved from Sommaire table, search the body of the PDF for each declared item!
        if len(valid_with_pages) < 2 and len(items_raw) >= 3:
            print("Sommaire has declared items but no page numbers -> searching PDF body for declared items...")
            body_start = sommaire_page_idx + 1
            resolved_body_items = []
            
            # Distinctive keywords per item number
            doc_keywords = {
                1: ['LETTRE DE DEMANDE', 'DEMANDE D AVIS', 'DEMANDE D APPROBATION'],
                2: ['CERTIFICAT DES SIGNATURES', 'LEGALISATION DES SIGNATURES', 'FORMULAIRE 1', 'CHAMBRE DE COMMERCE'],
                3: ['PAYS D ORIGINE', 'FORMULAIRE 2', 'CONSTRUCTION CONFORME', 'COUNTRY OF ORIGIN'],
                4: ['VISITE INTERIEURE', 'CERTIFICAT D ESSAI', 'VISITE USINE', 'FORMULAIRE 3', 'FORMULAIRE 4', 'ESSAI HYDROSTATIQUE'],
                5: ['ETAT DESCRIPTIF', 'FORMULAIRE 5', 'DESCRIPTION OF EQUIPMENT'],
                6: ['NOTES DE CALCUL', 'NOTE DE CALCUL', 'CALCULATION NOTE', 'CALCUL DE RESISTANCE'],
                7: ['PLAN DETAILLE', 'DETAILLED DRAWING', 'GENERAL ARRANGEMENT', 'DESSIN'],
                8: ['PROCEDURES DE SOUDAGE', 'WELDING PROCEDURE', 'WPS', 'PQR'],
                9: ['TRAITEMENT THERMIQUE', 'TRAITEMENTS THERMIQUES', 'HEAT TREATMENT', 'PWHT'],
                10: ['PLAN D INSPECTION ET CONTROLE', 'PLAN D INSPECTION', 'INSPECTION AND TEST PLAN', 'ITP', 'QCP']
            }
            
            last_p = body_start
            for itm in items_raw:
                try:
                    num_int = int(float(itm['num']))
                except Exception:
                    continue
                found_p = None
                
                # Scan body pages starting after previous item
                for p_idx in range(body_start, total_pages):
                    p_txt = doc[p_idx].get_text()
                    lines = [l.strip() for l in p_txt.split('\n') if l.strip()]
                    header_lines = [l for l in lines[:10] if not is_running_header(l)]
                    hdr_full = normalize(" ".join(header_lines))
                    
                    # Pattern 1: Exact Document Number: "DOCUMENT No. 10", "Document no 6", "DOCUMENT N° 1"
                    m_doc_num = re.search(r'\bDOCUMENT\s*(?:N[°O]?|NO\.?|#)?\s*[:\.]?\s*0?' + str(num_int) + r'\b', hdr_full)
                    if m_doc_num:
                        found_p = p_idx + 1
                        break
                        
                    # Pattern 2: FORMULAIRE-X
                    if num_int in [1, 2, 3, 4, 5]:
                        # Map doc num to formulaire if applicable
                        # In QHP/Proserv: Formulaire 1 = Doc 2, Formulaire 2 = Doc 4 or 3, Formulaire 5 = Doc 5
                        m_f = re.search(r'\bFORMULAIRE\s*[\-_]?\s*0?(\d+)\b', hdr_full)
                        if m_f:
                            f_num = int(m_f.group(1))
                            if (num_int == 2 and f_num == 1) or (num_int == 4 and f_num in [2, 3]) or (num_int == 5 and f_num == 5):
                                found_p = p_idx + 1
                                break
                                
                    # Pattern 3: Distinctive keywords
                    kws = doc_keywords.get(num_int, [])
                    for kw in kws:
                        if kw in hdr_full:
                            # Avoid false match of "PLAN" on ITP or vice versa
                            if num_int == 7 and any(bad in hdr_full for bad in ['INSPECTION', 'ITP', 'WPS']):
                                continue
                            if num_int == 10 and 'PLAN DETAILLE' in hdr_full and 'INSPECTION' not in hdr_full:
                                continue
                            found_p = p_idx + 1
                            break
                    if found_p:
                        break
                        
                if found_p:
                    resolved_body_items.append({
                        'num': itm['num'],
                        'title': " ".join(itm['lines']),
                        'page': found_p
                    })
                    print(f"   -> Item {itm['num']} found on page {found_p}")
                    
            if len(resolved_body_items) >= 2:
                items_with_pages = resolved_body_items
                valid_with_pages = [x for x in items_with_pages if x['page'] is not None and x['page'] > 0]
                
        if len(valid_with_pages) >= 2:
            valid_with_pages.sort(key=lambda x: x['page'])
            dedup = []
            for v in valid_with_pages:
                if not dedup or dedup[-1]['page'] != v['page']:
                    dedup.append(v)
            first_p = dedup[0]['page']
            if first_p > 1:
                cuts.append({'code': 'DOC-00', 'start': 1, 'end': first_p - 1, 'title': 'Page de Garde & Sommaire'})
            for i, itm in enumerate(dedup):
                st = itm['page']
                en = dedup[i+1]['page'] - 1 if i+1 < len(dedup) else total_pages
                if en < st: en = st
                cuts.append({'num': itm['num'], 'start': st, 'end': en, 'title': itm['title']})
                
    print(f"\nResulting Cuts ({len(cuts)} pieces):")
    for c in cuts:
        print(f"   [{c.get('num', c.get('code'))}] {c['start']}..{c['end']} ({c['end']-c['start']+1} pages) - {c['title'][:50]}")

if __name__ == "__main__":
    test_files = [
        r"C:\Users\MSI\Desktop\arh\06- WELL HEAD CONTROL PANEL\Incoming\Rev A\Preliminary Dossier (002).pdf",
        r"C:\Users\MSI\Desktop\arh\10-SAMPLING SYSTEM\Incoming\Rev 00\Preliminary dossier_sampling cylinder_16-07-2026.pdf",
        r"C:\Users\MSI\Desktop\arh\07- FITTING + flange\01- incoming\Rev C\DZ-GHBR-1B-WSX-CFL-PIP-VDR-0001 R2..pdf"
    ]
    for tf in test_files:
        test_enhanced_slice(tf)
