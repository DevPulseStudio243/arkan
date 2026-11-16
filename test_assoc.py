import fitz, math, re
from piping_topology_tracer import PipingTopologyTracer, parse_line_tag

doc = fitz.open(r'd:\DATA BASE IA\uploads\C3421-ROK1-081-PRC-DM-300001_2.pdf')
page = doc[0]
blocks = page.get_text('blocks')

# Line regex for real lines
real_line_pattern = re.compile(
    r'\b(\d{1,2}(?:\.\d+)?(?:/\d+)?["\'”]?)\s*-\s*([A-Z0-9]{2,6})\s*-\s*([A-Z0-9]+)\s*-\s*(\d{2,6})(?:\s*-\s*([A-Z0-9]+))?\b',
    re.I
)
exist_line_pattern = re.compile(
    r'\b([A-Z0-9]{2,6})\s+(\d{1,2}(?:\.\d+)?["\'”])\s+(?:EXISTANT|EXISTING)\b',
    re.I
)

labels = []
seen_tags = set()
for b in blocks:
    t = b[4].strip()
    m = real_line_pattern.search(t)
    if m:
        tag = m.group(0).replace(' ', '')
        if tag not in seen_tags:
            seen_tags.add(tag)
            labels.append({'text': tag, 'x': (b[0] + b[2]) / 2, 'y': (b[1] + b[3]) / 2})
            continue
    m2 = exist_line_pattern.search(t)
    if m2:
        tag = m2.group(0)
        if tag not in seen_tags:
            seen_tags.add(tag)
            labels.append({'text': tag, 'x': (b[0] + b[2]) / 2, 'y': (b[1] + b[3]) / 2})

# Components
comp_pattern = re.compile(r'\b(081-(?:HV|JI|CH|XV|MOV|CV|PSV|PIT|FIT|LIT|TIT|TW)-\d{3}[A-Z]?)\b', re.I)
components = []
for b in blocks:
    t = b[4].strip()
    m = comp_pattern.search(t)
    if m:
        tag = m.group(1).upper()
        if not any(c['tag'] == tag for c in components):
            components.append({'tag': tag, 'x': (b[0] + b[2]) / 2, 'y': (b[1] + b[3]) / 2})

# PDF drawing segments
pdf_segments = []
for draw in page.get_drawings():
    if draw.get('type') in ('s', 'p'):
        for item in draw.get('items', []):
            if item[0] == 'l':
                p0, p1 = item[1], item[2]
                pdf_segments.append(((p0.x, p0.y), (p1.x, p1.y), {}))

tracer = PipingTopologyTracer(tolerance=20.0, box_tolerance=250.0)
traced = tracer.trace_drawing(segments=pdf_segments, labels=labels, blocks=components, opcs=[], filename='test.pdf')

# Consolidate traced lines by unique tag
consolidated = {}
for l in traced:
    ltag = l['line_number']
    if ltag not in consolidated:
        consolidated[ltag] = dict(l)
        consolidated[ltag]['segments'] = list(l.get('path_coords', []))
    else:
        for s in l.get('path_coords', []):
            if s not in consolidated[ltag]['segments']:
                consolidated[ltag]['segments'].append(s)

def dist_point_to_segment(px, py, x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)

print('=== COMPONENT TO LINE ASSOCIATION ===')
for c in components:
    best_line = 'Non associé'
    min_dist = float('inf')
    for ltag, ldata in consolidated.items():
        # 1. Check distance to traced segments
        for seg in ldata['segments']:
            x1, y1, x2, y2 = seg[:4]
            d = dist_point_to_segment(c['x'], c['y'], x1, y1, x2, y2)
            if d < min_dist:
                min_dist = d
                best_line = ltag
    # If segments didn't match closely, check distance to line label
    if min_dist > 300.0:
        for l in labels:
            d = math.hypot(c['x'] - l['x'], c['y'] - l['y'])
            if d < min_dist:
                min_dist = d
                best_line = l['text']
                
    print(f"Component: {c['tag']} -> Line: {best_line} (dist: {min_dist:.1f}px)")
