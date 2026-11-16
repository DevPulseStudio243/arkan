import json

with open('ie_drawing_extractor_restored.py', 'r', encoding='utf-8') as f:
    text = f.read()

with open(r'C:\Users\MSI\.gemini\antigravity\brain\7cc98ab2-f2f2-422e-8a4e-5ed1c47aa104\.system_generated\logs\transcript_full.jsonl', encoding='utf-8') as f:
    for line in f:
        obj = json.loads(line)
        idx = obj.get('step_index')
        if idx in (2497, 2501, 2507):
            for tc in obj.get('tool_calls') or []:
                if tc.get('name') == 'edit_file' and 'ie_drawing_extractor.py' in tc.get('args', {}).get('Path', ''):
                    target = tc.get('args', {}).get('Target')
                    repl = tc.get('args', {}).get('Replacement')
                    if target in text:
                        text = text.replace(target, repl)
                        print(f'Successfully applied step {idx}')
                    else:
                        print(f'Could not find target for step {idx}')

with open('ie_drawing_extractor_v4.py', 'w', encoding='utf-8') as f:
    f.write(text)

print('Wrote ie_drawing_extractor_v4.py, length:', len(text))
