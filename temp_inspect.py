import os
import json

files = ["api_enhanced.py", "pid_analyzer.py", "pid_schematic_engine.py", "dxf_to_pid_json.py"]
for fname in files:
    if os.path.exists(fname):
        with open(fname, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        for i, l in enumerate(lines):
            if any(term in l for term in ['"elements"', "'elements'", "elements ="]):
                print(f"{fname}:{i+1}: {l.strip()[:120]}")
