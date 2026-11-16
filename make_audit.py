import re, json

with open('arkan-ui.html', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

print('Total lines:', len(lines))

id_counts = {}
for idx, line in enumerate(lines):
    parts = line.split('id=')
    for p in parts[1:]:
        if len(p) > 1 and p[0] in ('\"', "'"):
            q = p[0]
            end = p.find(q, 1)
            if end != -1:
                eid = p[1:end].split()
                if eid:
                    id_counts.setdefault(eid[0], []).append(idx + 1)

dups = {k:v for k,v in id_counts.items() if len(v) > 1}
print(f'Total unique ids: {len(id_counts)}, duplicates in entire file: {len(dups)}')
for k, v in sorted(dups.items()):
    print(f'{k} ({len(v)}): {v}')
