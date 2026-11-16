with open("pid_analyzer.py", "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

for i in range(2040, 2150):
    if i < len(lines):
        print(f"{i+1}: {lines[i].strip()}")
