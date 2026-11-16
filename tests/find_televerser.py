with open("arkan-ui.html", "r", encoding="utf-8") as f:
    text = f.read()

import re
matches = [m.start() for m in re.finditer(r"[Tt][eé]l[eé]verser", text)]
print(f"Total 'téléverser' occurrences: {len(matches)}")
for m in matches:
    line_start = text.rfind("\n", 0, m)
    line_end = text.find("\n", m)
    line_no = text.count("\n", 0, m) + 1
    print(f"Line {line_no}: {text[line_start:line_end].strip()[:120].encode('ascii', errors='replace').decode('ascii')}")
