import os

for fname in ["api_enhanced.py", "pid_analyzer.py", "dxf_to_pid_json.py"]:
    with open(fname, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    for i, l in enumerate(lines):
        if "try_autocad_dexpi_conversion" in l:
            print(f"{fname}:{i+1}: {l.strip()[:120]}")
