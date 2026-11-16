with open(r"C:\Users\MSI\.gemini\antigravity\brain\7cc98ab2-f2f2-422e-8a4e-5ed1c47aa104\.user_uploaded\extracted_new\ie_mto_router.py", encoding="utf-8") as f:
    text = f.read()

import re
routes = re.findall(r"@router\.(get|post|put|delete)\(([^)]+)\)", text)
print("Routes in uploaded ie_mto_router.py:")
for m, r in routes:
    print(" -", m.upper(), r.strip().split(",")[0])
