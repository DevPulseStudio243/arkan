with open("arkan-ui.html", "r", encoding="utf-8") as f:
    text = f.read()

import re
matches = [m.start() for m in re.finditer(r"currentView\s*=\s*", text)]
for m in matches[:10]:
    print(text[m-30:m+70].strip())
