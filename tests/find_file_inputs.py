with open("arkan-ui.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, l in enumerate(lines):
    if 'type="file"' in l or "type='file'" in l:
        print(f"Line {i+1}: {l.strip()}")
