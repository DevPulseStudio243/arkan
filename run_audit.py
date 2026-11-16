import re, json

with open('arkan-ui.html', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

print('Total lines in arkan-ui.html:', len(lines))
