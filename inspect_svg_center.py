import re

svg_file = r"generated_visuals\C3421-ROK1-100-PRC-DM-300002_2_pid_pipeline\blocks\pid_schematic_plan.svg"
with open(svg_file, "r", encoding="utf-8") as f:
    svg_content = f.read()

# Count elements
lines = re.findall(r'<line [^>]+>', svg_content)
tags = re.findall(r'<g class="pid-schematic-element pid-line-tag-element"[^>]*>.*?<\/g>', svg_content, re.DOTALL)
valves = re.findall(r'<g class="pid-schematic-element" data-tag="[^"]*" data-kind="valve"[^>]*>.*?<\/g>', svg_content, re.DOTALL)
instruments = re.findall(r'<g class="pid-schematic-element" data-tag="[^"]*" data-kind="instrument"[^>]*>.*?<\/g>', svg_content, re.DOTALL)

print(f"SVG Lines: {len(lines)}")
print(f"SVG Line Tag Labels: {len(tags)}")
print(f"SVG Valves: {len(valves)}")
print(f"SVG Instruments: {len(instruments)}")

# Check line tag labels texts and positions
print("\nFirst 15 line tag labels:")
for t in tags[:15]:
    tag_m = re.search(r'data-tag="([^"]+)"', t)
    trans_m = re.search(r'transform="translate\(([^)]+)\)', t)
    print(" ", tag_m.group(1) if tag_m else "", trans_m.group(1) if trans_m else "")
