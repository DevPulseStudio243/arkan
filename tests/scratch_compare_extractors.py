with open(r"C:\Users\MSI\.gemini\antigravity\brain\7cc98ab2-f2f2-422e-8a4e-5ed1c47aa104\.user_uploaded\extracted_new\ie_drawing_extractor.py", encoding="utf-8") as f:
    up_text = f.read()

with open(r"D:\DATA BASE IA\ie_drawing_extractor.py", encoding="utf-8") as f:
    ws_text = f.read()

print("Uploaded lines:", len(up_text.splitlines()))
print("Workspace lines:", len(ws_text.splitlines()))

import re
up_funcs = set(re.findall(r"^def ([a-zA-Z0-9_]+)\(", up_text, re.MULTILINE))
ws_funcs = set(re.findall(r"^def ([a-zA-Z0-9_]+)\(", ws_text, re.MULTILINE))

print("\nFunctions only in uploaded:", up_funcs - ws_funcs)
print("Functions only in workspace:", ws_funcs - up_funcs)
print("Common functions:", len(up_funcs & ws_funcs))
