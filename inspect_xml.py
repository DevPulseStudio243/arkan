import os
import xml.etree.ElementTree as ET

xml_file = r"uploads\C3421-ROK1-100-PRC-DM-300002_2.xml"
if os.path.exists(xml_file):
    print("XML exists, size:", os.path.getsize(xml_file))
    tree = ET.parse(xml_file)
    root = tree.getroot()
    count = 0
    tags = []
    for el in root.iter():
        tag_local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag_local in ("Equipment", "PipingComponent", "Instrumentation", "SignalComponent", "Actuator"):
            count += 1
            t_name = ""
            for child in el:
                c_local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if c_local == "TagName":
                    t_name = child.text
            tags.append((tag_local, t_name))
    print(f"Total matching elements in XML: {count}")
    for t in tags:
        print(" ", t)
else:
    print("XML does not exist")
