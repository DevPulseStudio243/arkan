import json, os

template_path = r'd:\DATA BASE IA\kaggle_kernel_specialist-fitting\notebook.ipynb'
target_path = r'd:\DATA BASE IA\kaggle_kernel_planning_expert\notebook.ipynb'

with open(template_path, 'r', encoding='utf-8') as tf:
    nb = json.load(tf)

nb['cells'][0]['source'] = [
    '# ARKAN Planning EPCC - Fine-Tuning Agent Specialiste Planning IA (Qwen2.5-3B LoRA)\n',
    '**Objectif :** Fine-tuning Qwen2.5-3B LoRA GPU T4 sur 2500 projets EPCC complets.\n'
]

nb['cells'][1]['source'] = [
    "# 1. Nettoyage et installation des dependances optimisees QLoRA 4-bit\n",
    "import subprocess, sys\n",
    "print('[*] Nettoyage dependances et installation PEFT/Transformers/BitsAndBytes...')\n",
    "subprocess.run([sys.executable, '-m', 'pip', 'uninstall', '-y', 'torchao'], check=False)\n",
    "subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', '--upgrade', 'transformers>=4.45.0', 'peft>=0.13.0', 'accelerate>=0.34.0', 'datasets', 'bitsandbytes'], check=True)\n",
    "print('[+] Dependances pretes !')\n"
]

with open(r'd:\DATA BASE IA\train_script_content.py', 'r', encoding='utf-8') as sf:
    train_code = sf.read()

nb['cells'][2]['source'] = [
    '# 2. Ecriture du script d entrainement optimise\n',
    'with open("train_planning_expert.py", "w", encoding="utf-8") as f:\n    f.write(' + json.dumps(train_code) + ')\n',
    'print("[+] Script train_planning_expert.py genere !")\n'
]

if len(nb['cells']) > 3:
    nb['cells'][3]['source'] = [
        '# 3. Execution de l entrainement GPU\n',
        'import subprocess, sys\n',
        'print("[*] Lancement de l entrainement Planning Expert sur GPU...")\n',
        'res = subprocess.run([sys.executable, "train_planning_expert.py"], check=True)\n',
        'print("[+] SUCCES COMPLET ! Code de sortie =", res.returncode)\n'
    ]

with open(target_path, 'w', encoding='utf-8') as out:
    json.dump(nb, out, indent=2)

print('[+] notebook.ipynb generated successfully at:', target_path)
