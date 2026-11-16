import ezdxf

doc = ezdxf.readfile(r"C:\Users\MSI\Desktop\1\C2723-GCB-000-ELE-PLA-006 Plan de cheminement.dxf")
msp = doc.modelspace()

dims = []
for d in msp.query("DIMENSION"):
    val = d.dxf.actual_measurement if d.dxf.hasattr("actual_measurement") else None
    txt = d.dxf.text if d.dxf.hasattr("text") else None
    layer = d.dxf.layer
    dims.append((layer, val, txt))

print(f"Total DIMENSION entities: {len(dims)}")
print("Dimensions:")
for l, v, t in dims:
    if v is not None and v > 10:
        print(f"  [{l}] {v:.1f} mm (txt: '{t}')")

# Also check polylines per layer
layer_lengths = {}
for e in msp.query("LWPOLYLINE POLYLINE LINE"):
    lay = e.dxf.layer
    length = 0.0
    if e.dxftype() == "LINE":
        start = e.dxf.start
        end = e.dxf.end
        length = ((end[0] - start[0])**2 + (end[1] - start[1])**2)**0.5
    elif e.dxftype() == "LWPOLYLINE":
        pts = e.get_points()
        for i in range(len(pts) - 1):
            p1, p2 = pts[i][:2], pts[i+1][:2]
            length += ((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)**0.5
        if e.closed:
            p1, p2 = pts[-1][:2], pts[0][:2]
            length += ((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)**0.5
    layer_lengths[lay] = layer_lengths.get(lay, 0.0) + length

print("\nLayer Lengths (raw DXF units):")
for lay, total_l in sorted(layer_lengths.items(), key=lambda x: -x[1]):
    print(f"  Layer '{lay}': raw={total_l:.1f} (in m if mm: {total_l*0.001:.2f} m, if /2: {total_l*0.0005:.2f} m)")
