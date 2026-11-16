with open(r"d:\DATA BASE IA\ie_drawing_extractor.py", encoding="utf-8") as f:
    code = f.read()

target = """        if e.dxftype() == "INSERT":
            yield e, layer
            name = _norm(e.dxf.get("name", ""))
            if depth < 6 and not any(_norm(p) in name for p in no_explode_patterns):"""

replacement = """        if e.dxftype() == "INSERT":
            yield e, layer
            name = _norm(e.dxf.get("name", ""))
            # N'exploser que les blocs pertinents pour l'E&I (évite d'exploser le génie civil et de saturer le cap)
            is_ei_block = (any(_norm(p) in name for p in ("ELEC", "CABLE", "CHEMIN", "CDC", "TRAY", "MALT", "TERRE", "EARTH", "FOURREAU", "BUSE")) or
                           any(_norm(p) in layer for p in ("ELEC", "CABLE", "CHEMIN", "CDC", "TRAY", "MALT", "TERRE", "EARTH", "FOURREAU", "BUSE")))
            if is_ei_block and depth < 6 and not any(_norm(p) in name for p in no_explode_patterns):"""

code = code.replace(target, replacement)

with open(r"d:\DATA BASE IA\ie_drawing_extractor.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Targeted block explosion applied to ie_drawing_extractor.py")
