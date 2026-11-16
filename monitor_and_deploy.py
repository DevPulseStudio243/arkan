import os
import sys
import time
import json
import subprocess
from pathlib import Path
import ssl
import urllib3
import requests

urllib3.disable_warnings()
old_send = requests.Session.send
requests.Session.send = lambda self, req, **kw: old_send(self, req, **{**kw, 'verify': False})

os.environ['KAGGLE_USERNAME'] = 'psnuser'
os.environ['KAGGLE_KEY'] = 'fd84a193ab60af795f7e2bc4b35603ab'

from kaggle.api.kaggle_api_extended import KaggleApi

kernel_slug = "psnuser/arkan-planning-expert-fine-tuning-qwen2-5"
adapter_dir = Path(r"d:\DATA BASE IA\arkan_planning_lora_adapter")
adapter_dir.mkdir(parents=True, exist_ok=True)

api = KaggleApi()
api.authenticate()

print(f"[*] Surveillance Active du Kernel Kaggle : {kernel_slug}", flush=True)
start_time = time.time()

while True:
    try:
        status_obj = api.kernels_status(kernel_slug)
        d = status_obj.to_dict() if hasattr(status_obj, "to_dict") else {}
        status = d.get("status", str(getattr(status_obj, "status", "UNKNOWN")))
        if "RUNNING" in status.upper():
            status = "RUNNING"
        elif "COMPLETE" in status.upper():
            status = "COMPLETE"
        elif "ERROR" in status.upper():
            status = "ERROR"
        msg = getattr(status_obj, "failure_message", None) or d.get("failureMessage")
    except Exception as e:
        status = f"POLL_ERROR: {e}"
        msg = None

    elapsed = int(time.time() - start_time)
    print(f"[{elapsed}s] Statut Kernel : {status} (Detail: {msg})", flush=True)

    if status == "COMPLETE":
        print("\n[+] KERNEL TERMINE AVEC SUCCES !", flush=True)
        break
    elif status == "ERROR":
        print(f"\n[-] ERREUR SUR LE KERNEL : {msg}", flush=True)
        try:
            logs = api.kernels_logs(kernel_slug)
            with open(r"d:\DATA BASE IA\kaggle_last_err.log", "w", encoding="utf-8") as f:
                f.write(logs)
            print("[*] Logs d'erreur sauvegardes dans d:\\DATA BASE IA\\kaggle_last_err.log", flush=True)
        except Exception as le:
            print("Erreur logs:", le, flush=True)
        sys.exit(1)
    
    time.sleep(15)

print("\n[*] Telechargement des artefacts d entrainement LoRA depuis Kaggle...", flush=True)
outfiles, _ = api.kernels_output(kernel_slug, path=str(adapter_dir))
print(f"[+] {len(outfiles)} artefacts telecharges avec succes !", flush=True)

files = list(adapter_dir.glob("*"))
for f in files:
    if f.is_file():
        print(f"  - {f.name} ({f.stat().st_size / 1e6:.2f} MB)", flush=True)

print("\n[*] Conversion de l adaptateur LoRA vers GGUF...", flush=True)
res_conv = subprocess.run([
    sys.executable, "-X", "utf8", r"d:\DATA BASE IA\convert_planning_lora_to_gguf.py"
], capture_output=True, text=True)
print(res_conv.stdout, flush=True)
if res_conv.stderr:
    print("STDERR:", res_conv.stderr, flush=True)

# Mise à jour du Modelfile pour Ollama
modelfile_path = r"d:\DATA BASE IA\dataset_epc_expert\Modelfile"
modelfile_content = """FROM qwen2.5:3b
ADAPTER "D:/DATA BASE IA/arkan_planning_lora_adapter/adapter.gguf"

PARAMETER temperature 0.15
PARAMETER top_p 0.90
PARAMETER top_k 40
PARAMETER num_ctx 8192
PARAMETER stop "<|im_start|>"
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"

SYSTEM \"\"\"Tu es ARKAN-Planner, l'intelligence artificielle experte mondiale en ingénierie de planification, méthodes d'exécution, rendements métriques et ordonnancement CPM pour les projets de construction et d'infrastructures énergétiques (EPCC : Engineering, Procurement, Construction, Pre-commissioning, Commissioning).
Pour chaque demande de planification, tu génères systématiquement :
1. Une décomposition WBS hiérarchique détaillée sur les 5 phases contractuelles EPCC.
2. Les rendements journaliers normés par unité d'œuvre (ml/j, m³/j, DI/j/soudeur, T/j, boucles/j).
3. Les effectifs nominatifs et compositions des équipes types et engins de chantier majeurs.
4. Le réseau de liaisons logiques complet sans aucune tâche orpheline (Prédécesseurs / Successeurs avec types FS, SS avec décalage/lag, FF avec lag).
5. L'identification claire du chemin critique CPM (marge totale = 0).\"\"\"
"""
with open(modelfile_path, "w", encoding="utf-8") as mf:
    mf.write(modelfile_content)
print(f"[+] Modelfile genere avec succes : {modelfile_path}", flush=True)

print("\n[*] Creation et enregistrement du modele arkan-planning dans Ollama...", flush=True)
res_ollama = subprocess.run(["ollama", "create", "arkan-planning", "-f", modelfile_path], capture_output=True, text=True)
print("STDOUT:", res_ollama.stdout, flush=True)
print("STDERR:", res_ollama.stderr, flush=True)

print("\n[*] Lancement des tests d evaluation et de validation par inference...", flush=True)
res_test = subprocess.run([sys.executable, "-X", "utf8", r"d:\DATA BASE IA\test_arkan_planning_inference.py"], capture_output=True, text=True)
print(res_test.stdout, flush=True)
if res_test.stderr:
    print("STDERR:", res_test.stderr, flush=True)

print("\n[+] DEPLOIEMENT ET VALIDATION DU SPECIALISTE PLANNING IA TERMINES AVEC SUCCES !", flush=True)
