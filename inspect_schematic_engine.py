with open("pid_schematic_engine.py", "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

print(f"Total lines in pid_schematic_engine.py: {len(lines)}")
for i in range(0, min(120, len(lines))):
    print(f"{i+1}: {lines[i].strip()}")
