with open(r"d:\DATA BASE IA\ie_drawing_extractor.py", encoding="utf-8") as f:
    code = f.read()

target_iter = """        if layer.upper() in hidden:
            continue
        stop["count"] += 1"""

replacement_iter = """        if layer.upper() in hidden:
            continue
        l_up = layer.upper()
        if any(x in l_up for x in ("HATCH", "HACH", "WALL", "MUR", "CIVIL", "ARCHI", "GRID", "AXE", "DEFPOINTS")):
            continue
        stop["count"] += 1"""

code = code.replace(target_iter, replacement_iter)

with open(r"d:\DATA BASE IA\ie_drawing_extractor.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Applied smart civil layer filter to iter_entities")
