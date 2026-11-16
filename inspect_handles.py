import ezdxf

dxf_file = r"cad_cache\dxf\C3421-ROK1-100-PRC-DM-300002_2_de42ac89c0df.dxf"
doc = ezdxf.readfile(dxf_file)

for h in ["6C19", "6C29", "6000", "6079", "92EE", "92F0", "92F7", "92F8", "92FA"]:
    try:
        e = doc.entitydb.get(h)
        if e:
            t = e.dxftype()
            layer = e.dxf.layer if hasattr(e.dxf, "layer") else ""
            txt = ""
            if t in ("TEXT", "MTEXT"):
                txt = e.plain_text() if hasattr(e, "plain_text") else getattr(e.dxf, "text", "")
            ins = getattr(e.dxf, "insert", None)
            print(f"Handle {h}: type={t} layer={layer} text='{txt}' insert={ins}")
        else:
            print(f"Handle {h}: not found")
    except Exception as err:
        print(f"Handle {h}: error {err}")
