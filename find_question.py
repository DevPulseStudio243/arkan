import re
with open("api_enhanced.py", "r", encoding="utf-8") as f:
    lines = f.read().splitlines()
    for i, line in enumerate(lines, 1):
        if "/question" in line or "async def ask" in line or "class QuestionRequest" in line:
            # Print 5 lines before and 35 lines after
            start = max(1, i-5)
            end = min(len(lines), i+35)
            print(f"--- MATCH AT LINE {i} ---")
            for j in range(start, end):
                print(f"{j}: {lines[j-1]}")
