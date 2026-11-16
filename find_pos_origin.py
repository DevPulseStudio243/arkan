import os, json

with open(r"generated_visuals\C3421-ROK1-100-PRC-DM-300002_2_pid_pipeline\blocks\semantic_with_equipment.json", "r", encoding="utf-8") as f:
    data = json.load(f)

for e in data.get("elements", []):
    if e.get("kind") == "equipment":
        print(e.get("tag"), e.get("id"), e.get("handle"), e.get("position"), e.get("bbox"), e.get("link_source"), e.get("block"))
