with open("arkan-ui.html", "r", encoding="utf-8") as f:
    text = f.read()

import re
matches = [m.start() for m in re.finditer(r"([Tt][eé]l[eé]verser|Upload|Parcourir)", text)]
print(f"Total occurrences: {len(matches)}")
for m in matches[:30]:
    line_start = text.rfind("\n", 0, m)
    line_end = text.find("\n", m)
    print(text[line_start:line_end].strip()[:100].encode('ascii', errors='replace').decode('ascii'))
