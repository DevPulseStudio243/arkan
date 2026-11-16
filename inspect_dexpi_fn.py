with open("api_enhanced.py", "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

for i in range(2860, 2920):
    if i < len(lines):
        print(f"{i+1}: {lines[i].strip()}")
