import re
import json
import subprocess

with open('arkan-ui.html', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = re.compile(r'<script\b[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)

scripts = []
for m in pattern.finditer(content):
    # calculate line number
    line_no = content[:m.start()].count('\n') + 1
    # check if it has src attribute
    tag = content[m.start():m.start() + 50]
    if 'src=' in tag.lower():
        continue
    code = m.group(1).strip()
    if code:
        scripts.append({'line': line_no, 'code': code})

print(f"Extracted {len(scripts)} inline script blocks.")

with open('scripts_debug.json', 'w', encoding='utf-8') as f:
    json.dump(scripts, f)

node_test = """
const vm = require('vm');
const fs = require('fs');

const context = vm.createContext({
    window: { addEventListener: () => {}, removeEventListener: () => {} },
    addEventListener: () => {},
    removeEventListener: () => {},
    document: {
        getElementById: () => null,
        addEventListener: () => {},
        createElement: () => ({ style: {}, classList: { add: ()=>{}, remove: ()=>{} }, appendChild: ()=>{} }),
        querySelector: () => null,
        querySelectorAll: () => [],
        head: { appendChild: ()=>{} },
        body: { appendChild: ()=>{} }
    },
    navigator: { userAgent: '' },
    location: { origin: 'http://127.0.0.1:8000', port: '8000' },
    localStorage: { getItem: () => '', setItem: () => {}, removeItem: ()=>{} },
    sessionStorage: { getItem: () => '', setItem: () => {}, removeItem: ()=>{} },
    console: console,
    setTimeout: (fn) => 1,
    setInterval: (fn) => 1,
    requestAnimationFrame: (fn) => 1,
    clearTimeout: clearTimeout,
    
    clearInterval: clearInterval,
    Event: class Event {},
    CustomEvent: class CustomEvent {},
    FormData: class FormData {},
    Blob: class Blob {},
    File: class File {}
});
context.window = context;
context.global = context;

const scripts = JSON.parse(fs.readFileSync('scripts_debug.json', 'utf-8'));
let errorCount = 0;
scripts.forEach((s, idx) => {
    try {
        const compiled = new vm.Script(s.code, { filename: 'script_' + idx + '_L' + s.line + '.js' });
        compiled.runInContext(context);
        console.log(`[PASS] Script ${idx} (line ~${s.line}) executed successfully.`);
    } catch(e) {
        errorCount++;
        console.error(`[FAIL] Script ${idx} (line ~${s.line}): ${e.name} - ${e.message}`);
    }
});
console.log(`\nTotal: ${scripts.length} scripts tested, ${errorCount} errors.`);
"""

with open('run_node_test.js', 'w', encoding='utf-8') as f:
    f.write(node_test)

res = subprocess.run(['node', 'run_node_test.js'], capture_output=True, text=True, encoding='utf-8')
print(res.stdout)
if res.stderr:
    print("STDERR:", res.stderr)
