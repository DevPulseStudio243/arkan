svg_file = r"generated_visuals\C3421-ROK1-100-PRC-DM-300002_2_pid_pipeline\blocks\pid_schematic_plan.svg"
with open(svg_file, "r", encoding="utf-8") as f:
    svg_content = f.read()

import re
viewbox = re.search(r'viewBox="([^"]+)"', svg_content)
print("ViewBox:", viewbox.group(1) if viewbox else "Not found")

# Find equipment rects
rects = re.findall(r'<g class="pid-schematic-element pid-equipment-group"[^>]*>.*?<\/g>', svg_content, re.DOTALL)
print(f"Equipment groups found: {len(rects)}")
for r in rects:
    tag_m = re.search(r'data-tag="([^"]+)"', r)
    trans_m = re.search(r'transform="translate\(([^)]+)\)"', r)
    rect_m = re.search(r'<rect x="([^"]+)" y="([^"]+)" width="([^"]+)" height="([^"]+)"', r)
    print("  Tag:", tag_m.group(1) if tag_m else "", "Pos:", trans_m.group(1) if trans_m else "", "Rect:", rect_m.groups() if rect_m else "")
