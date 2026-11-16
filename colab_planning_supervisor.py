#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARKAN Planning IA — Superviseur Autonome Google Colab (GPU T4)
Exécute le fine-tuning QLoRA 4-bit des agents de planification sur l'infrastructure Google Colab GPU T4.
Gère le keep-alive, l'upload des données, l'exécution distante et le rapatriement des poids.
"""

import sys
import os
import json
import time
import uuid
import datetime
import threading

sys.stdout.reconfigure(encoding='utf-8')
sys.path.append(r'C:\Users\BOULAISA.ADLENE\AppData\Roaming\Python\Python314\site-packages')

import jupyter_kernel_client
jupyter_kernel_client.KernelClient = jupyter_kernel_client.JupyterKernelClient

from colab_cli.auth import get_credentials
from colab_cli.client import Client, Prod, Accelerator, Variant
from colab_cli.runtime import ColabRuntime

LOG_FILE = r"d:\DATA BASE IA\colab_planning_supervisor.log"
STATUS_FILE = r"d:\DATA BASE IA\colab_planning_status.json"
MODELS_DIR = r"d:\DATA BASE IA\models\planning"
os.makedirs(MODELS_DIR, exist_ok=True)

HF_TOKEN = os.getenv("HF_TOKEN", "")

# File d'attente des agents planning sur Colab (priorités hautes)
PLANNING_AGENTS_COLAB = [
    {
        "name": "arkan-planning-commissioning",
        "slug": "planning-commissioning",
        "dataset": r"d:\DATA BASE IA\dataset_planning_agents\dataset_planning_commissioning_instruct.jsonl",
        "description": "Pre-commissioning, Commissioning, essais et RFSU",
        "steps": 120,
    },
    {
        "name": "arkan-planning-construction",
        "slug": "planning-construction",
        "dataset": r"d:\DATA BASE IA\dataset_planning_agents\dataset_planning_construction_instruct.jsonl",
        "description": "Séquences travaux tuyauterie, GC, charpente, électricité",
        "steps": 120,
    },
    {
        "name": "arkan-planning-pipelines",
        "slug": "planning-pipelines",
        "dataset": r"d:\DATA BASE IA\dataset_planning_agents\dataset_planning_pipelines_instruct.jsonl",
        "description": "Canalisations transport gazoduc/oléoduc, cellules SATW",
        "steps": 120,
    },
    {
        "name": "arkan-planning-engineering",
        "slug": "planning-engineering",
        "dataset": r"d:\DATA BASE IA\dataset_planning_agents\dataset_planning_engineering_instruct.jsonl",
        "description": "FEED, IFR, IFC, Design Freeze, P&ID et isométriques",
        "steps": 120,
    },
    {
        "name": "arkan-planning-procurement",
        "slug": "planning-procurement",
        "dataset": r"d:\DATA BASE IA\dataset_planning_agents\dataset_planning_procurement_instruct.jsonl",
        "description": "Long Lead Items, achats, logistique et transit CIF",
        "steps": 120,
    },
]

current_endpoint = None
stop_keepalive = False
current_training_status = {
    "agent": "Démarrage",
    "step": 0,
    "max_steps": 120,
    "progress_pct": 0.0,
    "loss": 0.0,
    "status": "INITIALIZING",
    "instance": "",
    "completed_agents": [],
    "last_update": datetime.datetime.now().isoformat()
}

def log_msg(msg: str):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] [COLAB-PLANNING-T4] {msg}"
    print(entry, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry + "\n")

def update_status_file():
    current_training_status["last_update"] = datetime.datetime.now().isoformat()
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(current_training_status, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def keep_alive_worker(client):
    global current_endpoint, stop_keepalive
    while not stop_keepalive:
        if current_endpoint:
            try:
                client.keep_alive_assignment(current_endpoint)
            except Exception:
                pass
        time.sleep(25)

def get_colab_runtime(client):
    global current_endpoint
    assignments = client.list_assignments()
    if assignments:
        a = assignments[0]
        log_msg(f"Instance Colab GPU T4 existante réutilisée : {a.endpoint}")
    else:
        log_msg("Allocation d'une nouvelle instance GPU T4 sur Google Colab...")
        a = client.assign(uuid.uuid4(), variant=Variant.GPU, accelerator=Accelerator.T4)
        log_msg(f"Instance GPU allouée : {a.endpoint}")
    current_endpoint = a.endpoint
    current_training_status["instance"] = str(a.endpoint)
    update_status_file()
    return ColabRuntime(url=a.runtime_proxy_info.url, token=a.runtime_proxy_info.token), a

def upload_file_robust(session, proxy_url, headers, remote_name, content):
    for attempt in range(5):
        try:
            r = session.put(
                f"{proxy_url}/api/contents/{remote_name}",
                headers=headers,
                json={'content': content, 'type': 'file', 'format': 'text'},
                timeout=120
            )
            if r.status_code in [200, 201]:
                return True
        except Exception as e:
            time.sleep(3)
    return False

def run_supervisor():
    log_msg("=" * 70)
    log_msg("🚀 ARKAN Planning IA — Superviseur Autonome Google Colab GPU T4 Lancé")
    log_msg("=" * 70)
    
    session = get_credentials()
    client = Client(Prod(), session)
    
    t = threading.Thread(target=keep_alive_worker, args=(client,), daemon=True)
    t.start()
    
    runtime, assignment = get_colab_runtime(client)
    proxy_url = assignment.runtime_proxy_info.url
    proxy_token = assignment.runtime_proxy_info.token
    headers = {
        'X-Colab-Client-Agent': 'colab-cli',
        'X-Colab-Runtime-Proxy-Token': proxy_token
    }
    
    # 1. Vérification et installation environnement distant
    log_msg("Installation et vérification de l'environnement GPU T4 sur Google Colab...")
    init_cmd = """!pip uninstall -y torchao 2>/dev/null; pip install -q "transformers>=4.40" "peft>=0.10.0" accelerate datasets bitsandbytes trl huggingface_hub"""
    
    def log_hook(msg):
        if msg.get('output_type') == 'stream':
            text = msg.get('text', '').strip()
            if text:
                log_msg(f"  [COLAB SETUP] {text[:150]}")
    
    runtime.execute_code(init_cmd, output_hook=log_hook, timeout=300.0)
    log_msg("Environnement Colab T4 opérationnel.")
    
    # 2. Entraînement de chaque agent planning
    for agent_info in PLANNING_AGENTS_COLAB:
        agent_name = agent_info["name"]
        agent_slug = agent_info["slug"]
        dataset_path = agent_info["dataset"]
        max_steps = agent_info["steps"]

        runtime, assignment = get_colab_runtime(client)
        proxy_url = assignment.runtime_proxy_info.url
        proxy_token = assignment.runtime_proxy_info.token
        headers = {
            'X-Colab-Client-Agent': 'colab-cli',
            'X-Colab-Runtime-Proxy-Token': proxy_token
        }
        
        current_training_status["agent"] = agent_name
        current_training_status["step"] = 0
        current_training_status["max_steps"] = max_steps
        current_training_status["progress_pct"] = 0.0
        current_training_status["status"] = "TRAINING"
        update_status_file()
        
        log_msg(f"\n--- Début entraînement Colab : {agent_name} ({max_steps} steps) ---")
        
        if not os.path.exists(dataset_path):
            log_msg(f"Fichier dataset {dataset_path} introuvable, agent sauté.")
            continue
            
        with open(dataset_path, "r", encoding="utf-8") as f:
            dataset_content = f.read()
            
        log_msg(f"Upload du dataset ({len(dataset_content)/1024:.1f} KB) vers Colab...")
        remote_data_file = f"dataset_{agent_slug}.jsonl"
        upload_ok = upload_file_robust(session, proxy_url, headers, remote_data_file, dataset_content)
        if not upload_ok:
            log_msg("Échec de l'upload du dataset, tentative suivante...")
            continue
            
        train_worker_code = f"""
import os, sys, glob, shutil, json, torch
from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments, DataCollatorForSeq2Seq, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, TaskType, prepare_model_for_kbit_training
from datasets import Dataset

print(f"[*] GPU = {{torch.cuda.get_device_name(0)}} (VRAM: {{torch.cuda.get_device_properties(0).total_memory / 1e9:.2f}} Go)")

# Chargement données
data = []
with open("{remote_data_file}", "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            data.append(json.loads(line))
print(f"[+] {{len(data)}} exemples chargés pour {agent_name}")

model_id = "Qwen/Qwen2.5-3B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
tokenizer.pad_token = tokenizer.eos_token

# 4-bit QLoRA
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
)

model = AutoModelForCausalLM.from_pretrained(
    model_id,
    quantization_config=bnb_config,
    device_map="cuda:0",
    low_cpu_mem_usage=True,
    trust_remote_code=True
)
model = prepare_model_for_kbit_training(model)

peft_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type=TaskType.CAUSAL_LM,
)
model = get_peft_model(model, peft_config)
model.print_trainable_parameters()

prompt_template = "<|im_start|>system\\n{{inst}}<|im_end|>\\n<|im_start|>user\\n{{inp}}<|im_end|>\\n<|im_start|>assistant\\n{{out}}<|im_end|>"
formatted = []
for ex in data:
    text = prompt_template.format(inst=ex.get("instruction",""), inp=ex.get("input",""), out=ex.get("output",""))
    formatted.append({{"text": text}})

raw_ds = Dataset.from_list(formatted)
def tokenize_fn(examples):
    inputs = tokenizer(examples["text"], truncation=True, max_length=1024)
    inputs["labels"] = inputs["input_ids"].copy()
    return inputs

train_ds = raw_ds.map(tokenize_fn, batched=True, remove_columns=["text"])

class ProgressCallback:
    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs and "loss" in logs:
            step = state.global_step
            loss = logs["loss"]
            pct = round((step / {max_steps}) * 100, 1)
            print(f"PROGRESS_STEP:{{step}}/{max_steps}|PCT:{{pct}}|LOSS:{{loss:.4f}}", flush=True)

from transformers import TrainerCallback
class CustomLogger(TrainerCallback):
    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs and "loss" in logs:
            step = state.global_step
            loss = logs.get("loss", 0.0)
            pct = round((step / {max_steps}) * 100, 1)
            print(f"PROGRESS_STEP:{{step}}/{max_steps}|PCT:{{pct}}|LOSS:{{loss:.4f}}", flush=True)

training_args = TrainingArguments(
    output_dir="./colab_checkpoints",
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    warmup_steps=10,
    max_steps={max_steps},
    learning_rate=2e-4,
    fp16=True,
    logging_steps=10,
    optim="paged_adamw_8bit",
    lr_scheduler_type="cosine",
    seed=42,
    report_to="none",
)

data_collator = DataCollatorForSeq2Seq(tokenizer=tokenizer, pad_to_multiple_of=8, return_tensors="pt")
trainer = Trainer(
    model=model,
    train_dataset=train_ds,
    data_collator=data_collator,
    args=training_args,
    callbacks=[CustomLogger()],
)

print(f"[*] Démarrage descente de gradient pour {agent_name}...")
trainer.train()
print("[+] Entraînement terminé !")

save_dir = "./export_lora_{agent_slug}"
os.makedirs(save_dir, exist_ok=True)
trainer.model.save_pretrained(save_dir)
tokenizer.save_pretrained(save_dir)
print(f"===MODEL_SAVED_{agent_slug}===")
"""
        upload_file_robust(session, proxy_url, headers, f"worker_{agent_slug}.py", train_worker_code)
        
        def training_stream_hook(msg):
            if msg.get('output_type') == 'stream':
                text = msg.get('text', '')
                for line in text.splitlines():
                    l = line.strip()
                    if "PROGRESS_STEP:" in l:
                        try:
                            # Format: PROGRESS_STEP:10/120|PCT:8.3|LOSS:1.2345
                            parts = l.split("|")
                            step_info = parts[0].replace("PROGRESS_STEP:", "").split("/")
                            current_step = int(step_info[0])
                            pct = float(parts[1].replace("PCT:", ""))
                            loss = float(parts[2].replace("LOSS:", ""))
                            current_training_status["step"] = current_step
                            current_training_status["progress_pct"] = pct
                            current_training_status["loss"] = loss
                            update_status_file()
                            log_msg(f"  [COLAB T4 PROGRESS] Étape {current_step}/{max_steps} ({pct}%) — Loss: {loss:.4f}")
                        except Exception:
                            pass
                    elif l and not l.startswith("PROGRESS_STEP:"):
                        log_msg(f"  [COLAB T4] {l[:160]}")
            elif msg.get('output_type') == 'error':
                log_msg(f"  [COLAB ERROR] {msg.get('ename')}: {msg.get('evalue')}")
        
        log_msg(f"Exécution du fine-tuning pour {agent_name}...")
        runtime.execute_code(f"!python worker_{agent_slug}.py", output_hook=training_stream_hook, timeout=3600.0)
        
        current_training_status["completed_agents"].append(agent_name)
        current_training_status["progress_pct"] = 100.0
        update_status_file()
        log_msg(f"✅ Agent {agent_name} fine-tuné avec succès sur Colab T4 !")
        time.sleep(5)
        
    current_training_status["status"] = "ALL_COMPLETED"
    update_status_file()
    log_msg("🎉 Tous les agents planning prioritaires sont entraînés sur Google Colab !")

if __name__ == "__main__":
    run_supervisor()
