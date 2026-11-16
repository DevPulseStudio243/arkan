import re, json

with open('arkan-ui.html', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

print('Lines:', len(lines))

id_map = {}
for idx, line in enumerate(lines):
    parts = line.split('id=')
    for p in parts[1:]:
        if len(p) > 1 and p[0] in ('\"', "'"):
            q = p[0]
            end = p.find(q, 1)
            if end != -1:
                eid = p[1:end].split()
                if eid:
                    id_map.setdefault(eid[0], []).append(idx + 1)

print('Total unique ids:', len(id_map))
dups = { k:v for k, v in id_map.items() if len(v) > 1 }
print('Total dups in whole file:', len(dups))
for k, v: in sorted(dups.items()):
    print(f'{k} ({len(v)}): {v}')
