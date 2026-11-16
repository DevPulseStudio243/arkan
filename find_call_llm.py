import re
with open("api_enhanced.py", "r", encoding="utf-8") as f:
    lines = f.read().splitlines()
    for i, line in enumerate(lines, 1):
        if "async def call_llm" in line or "def call_llm" in line:
            start = max(1, i-5)
            end = min(len(lines), i+30)
            print(f"--- MATCH AT LINE {i} ---")
            for j in range(start, end):
                print(f"{j}: {lines[j-1]}")
