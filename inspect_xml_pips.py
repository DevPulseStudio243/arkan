import xml.etree.ElementTree as ET

tree = ET.parse(r"uploads\C3421-ROK1-100-PRC-DM-300002_2.xml")
root = tree.getroot()

for el in root.iter():
    tag_local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
    if tag_local in ("Equipment", "PipingComponent", "Instrumentation", "SignalComponent", "Actuator"):
        tname = el.find("TagName")
        desc = el.find("Description")
        extent = el.find("Extent")
        min_pt = extent.find("Min") if extent is not None else None
        max_pt = extent.find("Max") if extent is not None else None
        t_text = tname.text if tname is not None else ""
        if "PIP" in t_text or "11883" in t_text or "VALVE" in t_text:
            print(f"ID={el.get('ID')} tag={t_text} desc={desc.text if desc is not None else ''} min=({min_pt.get('X')}, {min_pt.get('Y')})")
