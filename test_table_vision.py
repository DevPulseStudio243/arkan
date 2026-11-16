import httpx, base64, time, json

with open("d:/DATA BASE IA/bom_table_crop.png", "rb") as f:
    b64 = base64.b64encode(f.read()).decode("utf-8")

prompt = """You are a precision table OCR engine for technical engineering drawings.
Transcribe the table 'NOMENCLATURE DE MATERIEL' in this image.
Return a valid JSON array of objects, each with:
- "id": integer ID (1, 2, 3...)
- "category": section header (PIPE, FITTINGS, FLANGES, FASTENERS, VALVES)
- "size": nominal diameter string (e.g. "14\\"")
- "description": exact text in the description column
- "quantity": string in QTE column (e.g. "2.0M", "1", "2", "3", "36", "1")

Return ONLY the raw JSON array starting with [ and ending with ], no markdown formatting."""

t0 = time.time()
resp = httpx.post(
    "http://localhost:11434/api/generate",
    json={
        "model": "qwen2.5vl:3b",
        "prompt": prompt,
        "images": [b64],
        "stream": False,
        "options": {"temperature": 0.0}
    },
    timeout=60.0
)
t1 = time.time()
print(f"Ollama took {t1 - t0:.2f}s, HTTP status: {resp.status_code}")
raw = resp.json().get("response", "")
print("Raw Response:")
print(raw)
