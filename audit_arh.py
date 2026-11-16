
import sys, re

with open('arkan-ui.html', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

print('Scanning ARH definitions...')
funcs = []
for i, l in enumerate(lines):
    # Match function definitions
    m = re.search(r'(?:function\s+([a-zA-Z0-9_$]+)|(?:window\.)?([a-zA-Z0-9_$]+)\s*=\s*async\s*function|(?:window\.)?([a-zA-Z0-9_$]+)\s*=\s*function)', l)
    if m:
        name = m.group(1) or m.group(2) or m.group(3)
        if 'arh' in name.lower() or (9700 <= i <= 13700):
            funcs.append((i+1, name))

for line_no, fn in funcs:
    if 3400 <= line_no <= 14000 or 'arh' in fn.lower():
        print(f'{line_no}: {fn}')
