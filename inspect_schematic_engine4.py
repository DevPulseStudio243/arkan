with open("pid_schematic_engine.py", "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

for i in range(420, 560):
    if i < len(lines):
        print(f"{i+1}: {lines[i].strip()}")
