import json

with open(r"generated_visuals\C3421-ROK1-100-PRC-DM-300002_2_pid_pipeline\blocks\semantic_with_equipment.json", "r", encoding="utf-8") as f:
    data = json.load(f)

print("Keys in semantic_with_equipment.json:", list(data.keys()))
elements = data.get("elements", [])
print(f"Total elements: {len(elements)}")

# Count by kind
kinds = {}
for e in elements:
    k = e.get("kind", "UNKNOWN")
    kinds[k] = kinds.get(k, 0) + 1
print("Kinds count in elements:", kinds)

# Look for PIP-11883 or VALVE-2
for e in elements:
    tag = e.get("tag", "")
    if "PIP" in tag or "11883" in tag or "VALVE" in tag:
        print("Special element:", e)

# Print first 10 elements
for e in elements[:10]:
    print("  Elem:", e.get("tag"), e.get("kind"), e.get("type"), e.get("box") or e.get("bbox"))
