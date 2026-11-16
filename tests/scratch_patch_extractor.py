with open(r"C:\Users\MSI\.gemini\antigravity\brain\7cc98ab2-f2f2-422e-8a4e-5ed1c47aa104\.user_uploaded\extracted_new\ie_drawing_extractor.py", encoding="utf-8") as f:
    code = f.read()

code = code.replace(
    'cap = int((ie["_thresholds"] or {}).get("dwg_max_entities_memory_cap", 100000) or 100000)',
    'cap = int((ie["_thresholds"] or {}).get("dwg_max_entities_memory_cap", 1000000) or 1000000)'
)

old_resolve = """    if code in INSUNITS_TO_M:
        return INSUNITS_TO_M[code], f"INSUNITS={code}", False"""

new_resolve = """    try:
        msp = doc.modelspace()
        dim_measurements = []
        for e in msp:
            if e.dxftype() == "DIMENSION":
                meas = getattr(e.dxf, "actual_measurement", None)
                if meas is not None and meas > 0:
                    dim_measurements.append(meas)
                    if len(dim_measurements) >= 25:
                        break
        if dim_measurements:
            dim_measurements.sort()
            median_dim = dim_measurements[len(dim_measurements) // 2]
            if median_dim > 50.0 and code in (6, 0):
                warnings.append(f"Ajustement d'échelle automatique : dessin coté en millimètres (médiane cotations={median_dim:.0f} mm) malgré $INSUNITS={code}. Échelle fixée à 0.001 m.")
                return 0.001, f"mm (cotation médiane {median_dim:.0f})", False
    except Exception:
        pass
    if code in INSUNITS_TO_M:
        return INSUNITS_TO_M[code], f"INSUNITS={code}", False"""

code = code.replace(old_resolve, new_resolve)

with open(r"d:\DATA BASE IA\ie_drawing_extractor.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Successfully written hybrid ie_drawing_extractor.py")
