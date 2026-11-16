import json

with open(r"schematic_output\C3421-ROK1-100-PRC-DM-300002_2.json", "r", encoding="utf-8") as f:
    data = json.load(f)

print("Keys in schematic_output JSON:", list(data.keys()))
for k in data.keys():
    val = data[k]
    if isinstance(val, list):
        print(f"  {k}: list of {len(val)} items")
        if val:
            print(f"    sample[0]: {val[0]}")
    elif isinstance(val, dict):
        print(f"  {k}: dict with keys {list(val.keys())[:10]}")
    else:
        print(f"  {k}: {val}")
