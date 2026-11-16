with open("arkan-ui.html", "r", encoding="utf-8") as f:
    text = f.read()

import re
matches = [m.start() for m in re.finditer(r"(?:Importer|Charger|Parcourir|Upload)", text, re.IGNORECASE)]
print(f"Total occurrences: {len(matches)}")
for m in matches[:30]:
    line_start = text.rfind("\n", 0, m)
    line_end = text.find("\n", m)
    line_no = text.count("\n", 0, m) + 1
    print(f"Line {line_no}: {text[line_start:line_end].strip()[:120].encode('ascii', errors='replace').decode('ascii')}")
