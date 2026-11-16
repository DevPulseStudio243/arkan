import re
with open("api_enhanced.py", "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        if "/projects" in line:
            print(f"{i}: {line.strip()}")
