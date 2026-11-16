import ezdxf

dxf_file = r"cad_cache\dxf\C3421-ROK1-100-PRC-DM-300002_2_de42ac89c0df.dxf"
doc = ezdxf.readfile(dxf_file)
msp = doc.modelspace()

print("Searching entities near X=[32250, 32380], Y=[29850, 29890]:")
for e in msp:
    t = e.dxftype()
    if t in ("INSERT", "TEXT", "MTEXT", "CIRCLE"):
        ins = getattr(e.dxf, "insert", None) or getattr(e.dxf, "center", None)
        if ins and 32250 <= ins.x <= 32380 and 29850 <= ins.y <= 29890:
            txt = ""
            if t in ("TEXT", "MTEXT"):
                txt = e.plain_text() if hasattr(e, "plain_text") else getattr(e.dxf, "text", "")
            bname = e.dxf.name if t == "INSERT" else ""
            rad = getattr(e.dxf, "radius", "") if t == "CIRCLE" else ""
            print(f"  {t} {bname} text='{txt}' rad={rad} pos=({ins.x:.2f}, {ins.y:.2f})")
