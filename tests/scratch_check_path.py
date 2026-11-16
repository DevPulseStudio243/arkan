import ezdxf

doc = ezdxf.readfile(r"C:\Users\MSI\Desktop\1\C2723-GCB-000-ELE-PLA-006 Plan de cheminement.dxf")
msp = doc.modelspace()

print("DIMENSIONS et leurs coordonnées:")
for d in msp.query("DIMENSION"):
    val = d.dxf.actual_measurement if d.dxf.hasattr("actual_measurement") else None
    if val is not None and val > 1000:
        # Get defpoint or insert
        p1 = d.dxf.defpoint if d.dxf.hasattr("defpoint") else None
        p2 = d.dxf.defpoint2 if d.dxf.hasattr("defpoint2") else None
        p3 = d.dxf.defpoint3 if d.dxf.hasattr("defpoint3") else None
        print(f"  Val: {val:.1f} mm | defpoint={p1} | defpoint2={p2} | defpoint3={p3}")
