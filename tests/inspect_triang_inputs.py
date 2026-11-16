with open("arkan-ui.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i in range(145770, min(len(lines), 145830)):
    print(f"{i+1}: {lines[i].strip()}")
