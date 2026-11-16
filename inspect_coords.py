import json

sem_file = r"generated_visuals\C3421-ROK1-100-PRC-DM-300002_2_pid_pipeline\blocks\semantic_with_equipment.json"
with open(sem_file, "r", encoding="utf-8") as f:
    sem_data = json.load(f)

lines = sem_data.get("lines", [])
elements = sem_data.get("elements", [])
candidates = sem_data.get("equipment_candidates", [])

print(f"Lines count: {len(lines)}")
print(f"Elements count: {len(elements)}")
print(f"Candidates count: {len(candidates)}")

print("\n--- EQUIPMENTS in elements ---")
for e in elements:
    if e.get("kind") == "equipment":
        print(f"Tag={e.get('tag')} bbox={e.get('bbox')} pos={e.get('position')} connected_lines={e.get('connected_lines')}")

print("\n--- CANDIDATES ---")
for c in candidates:
    print(f"Tags={c.get('tags')} bbox={c.get('bbox')}")

print("\n--- INSTRUMENTS in elements (first 10) ---")
for e in elements:
    if e.get("kind") == "instrument":
        print(f"Tag={e.get('tag')} pos={e.get('position')} bbox={e.get('bbox')}")

print("\n--- LINES (first 5) ---")
for l in lines[:5]:
    segs = l.get("segments", [])
    print(f"Line: {l.get('line_number') or l.get('tag_raw')} segs count={len(segs)}")
    if segs:
        print(f"  sample seg: {segs[0]}")
