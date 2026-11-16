with open("arkan-ui.html", "r", encoding="utf-8") as f:
    text = f.read()

import re
matches = [m.start() for m in re.finditer(r"id=[\"'](?:btn-attach|attach|chat-upload|file-upload)[\"']", text)]
print("Attach buttons:")
for m in matches:
    print(text[m-50:m+200])

# Also check paperclip icon
matches2 = [m.start() for m in re.finditer(r"ph-(?:paperclip|upload)", text)]
print(f"Total icon matches: {len(matches2)}")
for m in matches2[:10]:
    print(text[m-50:m+150])
