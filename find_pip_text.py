import os, re
import ezdxf

dxf_file = r"cad_cache\dxf\C3421-ROK1-100-PRC-DM-300002_2_de42ac89c0df.dxf"
if not os.path.exists(dxf_file):
    print("DXF file not found in cad_cache")
else:
    doc = ezdxf.readfile(dxf_file)
    msp = doc.modelspace()
    texts = []
    for e in msp:
        if e.dxftype() in ("TEXT", "MTEXT"):
            t = e.plain_text() if hasattr(e, "plain_text") else getattr(e, "dxf", {}).get("text", "")
            if "11883" in t or "PIP" in t:
                texts.append((e.dxftype(), t, e.dxf.insert))
    print(f"Found {len(texts)} texts matching 11883 or PIP:")
    for t in texts:
        print(" ", t)
