import fitz
import re

doc = fitz.open(r'C:\Users\MSI\Desktop\C3421-ROK1-300-PIG-DW-300016.pdf')
for page_idx in range(2, 33):
    p = doc[page_idx]
    txt = p.get_text()
    cut_section = re.search(r'CUT\s*PIPE\s*LENGTH([\s\S]+?)(?:3-[A-Z0-9\-]+|CONT\.\s*ON|PIPING\s*SPEC|BATCH|$)', txt, re.I)
    target = cut_section.group(1) if cut_section else txt
    cut_matches = re.findall(r'<(\d+)>\s+(\d{2,5})\s+(\d+(?:/\d+)?)', target)
    print(f'Sheet {page_idx+1}: {len(cut_matches)} spools -> {cut_matches}')
