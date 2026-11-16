with open('arkan-ui.html', encoding='utf-8', errors='ignore') as f: lines = f.readlines()
print('Lines:', len(lines))
for i, l in enumerate(lines):
    if 'id=' in l and 'arh-' in l:
        pass