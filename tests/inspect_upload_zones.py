with open("arkan-ui.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

print("=== MTO UPLOAD ZONE ===")
for i in range(20720, 20760):
    if i < len(lines):
        print(f"{i+1}: {lines[i].strip()}")

print("=== IE UPLOAD AREA ===")
for i in range(26735, 26775):
    if i < len(lines):
        print(f"{i+1}: {lines[i].strip()}")
