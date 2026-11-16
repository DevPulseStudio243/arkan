with open("arkan-ui.html", "r", encoding="utf-8") as f:
    text = f.read()

import re
matches = [m.start() for m in re.finditer(r"id=[\"']file-upload[\"']", text)]
for m in matches:
    print(text[m-200:m+200])

matches2 = [m.start() for m in re.finditer(r"handleFileUpload", text)]
for m in matches2:
    print(text[m-100:m+300])
