#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARKAN Planning IA — Orchestrateur Multi-Plateformes Fine-Tuning
Lance et surveille TOUS les fine-tunings sur Kaggle (multi-kernels)
Architecture : 13 agents spécialisés + 1 orchestrateur = 14 modèles
"""

import os
import sys
import json
import time
import subprocess
import threading
from datetime import datetime
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────────────────

KAGGLE_USERNAME = "psnuser"
KAGGLE_KEY = "fd84a193ab60af795f7e2bc4b35603ab"
os.environ["KAGGLE_USERNAME"] = KAGGLE_USERNAME
os.environ["KAGGLE_KEY"] = KAGGLE_KEY

import urllib3, requests
urllib3.disable_warnings()
_old_send = requests.Session.send
requests.Session.send = lambda self, req, **kw: _old_send(self, req, **{**kw, "verify": False})

from kaggle.api.kaggle_api_extended import KaggleApi

DATASET_PLANNING_AGENTS = r"d:\DATA BASE IA\dataset_planning_agents"
KERNELS_BASE = r"d:\DATA BASE IA\kaggle_kernels_planning_agents"
BASE_DATASET_KAGGLE = "psnuser/arkan-planning-epc-datasets"

# Agents à fine-tuner (par priorité)
AGENTS = [
    # name, kernel_slug, dataset_file, priority
    ("rendements",    "arkan-agent-rendements-ft",      "dataset_planning_rendements_instruct.jsonl",    1),
    ("cpm",           "arkan-agent-cpm-ft",             "dataset_planning_cpm_instruct.jsonl",           1),
    ("wbs",           "arkan-agent-wbs-ft",             "dataset_planning_wbs_instruct.jsonl",           1),
    ("commissioning", "arkan-agent-commissioning-ft",   "dataset_planning_commissioning_instruct.jsonl", 2),
    ("construction",  "arkan-agent-construction-ft",    "dataset_planning_construction_instruct.jsonl",  2),
    ("pipelines",     "arkan-agent-pipelines-ft",       "dataset_planning_pipelines_instruct.jsonl",     2),
    ("engineering",   "arkan-agent-engineering-ft",     "dataset_planning_engineering_instruct.jsonl",   3),
    ("procurement",   "arkan-agent-procurement-ft",     "dataset_planning_procurement_instruct.jsonl",   3),
    ("solaire",       "arkan-agent-solaire-ft",         "dataset_planning_solaire_instruct.jsonl",       3),
    ("bacs",          "arkan-agent-bacs-ft",            "dataset_planning_bacs_instruct.jsonl",          4),
    ("hse",           "arkan-agent-hse-ft",             "dataset_planning_hse_instruct.jsonl",           4),
    ("ressources",    "arkan-agent-ressources-ft",      "dataset_planning_ressources_instruct.jsonl",    4),
    ("orchestrateur", "arkan-orchestrateur-ft",         "dataset_planning_orchestrateur_instruct.jsonl", 5),
]

LOG_FILE = r"d:\DATA BASE IA\multiagent_finetuning_log.txt"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_api():
    api = KaggleApi()
    api.authenticate()
    return api


def generate_agent_notebook(agent_name, dataset_file, kernel_slug):
    """Generate a fine-tuning notebook for a specific agent"""
    script_content = f'''
import subprocess, sys, os

# Install dependencies
subprocess.run([sys.executable, "-m", "pip", "uninstall", "torchao", "-y"], capture_output=True)
subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "transformers>=4.40",
    "peft>=0.10.0",
    "trl>=0.8.6",
    "datasets>=2.18",
    "accelerate>=0.27",
    "bitsandbytes>=0.43",
    "scipy",
    "einops",
], check=True)

import torch
print(f"GPU: {{torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None'}}")
print(f"VRAM: {{torch.cuda.get_device_properties(0).total_memory / 1e9:.1f}} GB" if torch.cuda.is_available() else "No GPU")

from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer
import json

# ── Config ──────────────────────────────
AGENT_NAME = "{agent_name}"
MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"
OUTPUT_DIR = f"/kaggle/working/arkan_{{AGENT_NAME}}_lora"
DATASET_FILE = "{dataset_file}"

print(f"\\n{'='*60}")
print(f"ARKAN Agent Fine-Tuning: {{AGENT_NAME}}")
print(f"{'='*60}\\n")

# ── Load dataset ──
dataset_path = f"/kaggle/input/arkan-planning-agents-datasets/{{DATASET_FILE}}"
if not os.path.exists(dataset_path):
    # Fallback to main EPC dataset
    dataset_path = "/kaggle/input/arkan-planning-epc-datasets/dataset_planning_epc_instruct.jsonl"
    print(f"WARNING: Agent dataset not found, using main EPC dataset")

dataset = load_dataset("json", data_files={{"train": dataset_path}}, split="train")
print(f"Dataset loaded: {{len(dataset)}} examples")

# ── BitsAndBytes 4-bit ──
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
)

# ── Load model ──
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "right"

model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    quantization_config=bnb_config,
    device_map="auto",
    trust_remote_code=True,
)
model = prepare_model_for_kbit_training(model)

# ── LoRA Config ──
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()

# ── Format data ──
def format_prompt(sample):
    instruction = sample.get("instruction", "")
    inp = sample.get("input", "")
    output = sample.get("output", "")
    if inp:
        text = f"<|im_start|>user\\n{{instruction}}\\n\\n{{inp}}<|im_end|>\\n<|im_start|>assistant\\n{{output}}<|im_end|>"
    else:
        text = f"<|im_start|>user\\n{{instruction}}<|im_end|>\\n<|im_start|>assistant\\n{{output}}<|im_end|>"
    return {{"text": text}}

dataset = dataset.map(format_prompt)

# ── Training args ──
training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    num_train_epochs=3,
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    warmup_steps=10,
    max_steps=150,
    learning_rate=2e-4,
    fp16=True,
    logging_steps=10,
    save_steps=75,
    optim="paged_adamw_8bit",
    lr_scheduler_type="cosine",
    report_to="none",
    dataloader_num_workers=0,
)

# ── Trainer ──
trainer = SFTTrainer(
    model=model,
    train_dataset=dataset,
    args=training_args,
    dataset_text_field="text",
    max_seq_length=1024,
    tokenizer=tokenizer,
)

print(f"\\nStarting training for ARKAN-{{AGENT_NAME}}...")
trainer.train()
print("\\nTraining complete!")

# ── Save ──
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
print(f"Model saved to {{OUTPUT_DIR}}")

# ── Quick inference test ──
test_questions = {{
    "rendements": "Quel est le rendement de soudage pour un gazoduc 36\\\" ?",
    "cpm": "Calcule le chemin critique pour un planning gazoduc.",
    "wbs": "Génère la WBS pour un projet gazoduc de 200 km.",
    "commissioning": "Quelles sont les étapes de commissioning d\'une unité TEG ?",
    "construction": "Quelle est la séquence optimale de construction d\'une unité de procédé ?",
    "pipelines": "Comment planifier un gazoduc de 300 km en terrain désertique ?",
    "engineering": "Quels sont les livrables Engineering phase IFC ?",
    "procurement": "Quels sont les Long Lead Items d\'un projet compression gaz ?",
    "solaire": "Comment planifier une centrale PV 50 MW ?",
    "bacs": "Planifie la construction de 5 bacs API 650 de 50 000 m³.",
    "hse": "Quels risques majeurs sur un chantier de gazoduc ?",
    "ressources": "Propose l\'organigramme d\'un projet EPC 200M USD.",
    "orchestrateur": "Génère le planning EPCC complet pour un projet gazoduc.",
}}

q = test_questions.get(AGENT_NAME, "Génère un planning EPCC complet.")
inputs = tokenizer(f"<|im_start|>user\\n{{q}}<|im_end|>\\n<|im_start|>assistant\\n", return_tensors="pt").to("cuda")
with torch.no_grad():
    outputs = model.generate(**inputs, max_new_tokens=200, do_sample=False, temperature=1.0)
response = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
print(f"\\n=== Test Inference ARKAN-{{AGENT_NAME}} ===")
print(f"Q: {{q}}")
print(f"R: {{response[:300]}}")
print("\\n✅ Fine-tuning COMPLET pour ARKAN-" + AGENT_NAME)
'''
    
    notebook = {
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
        "nbformat": 4,
        "nbformat_minor": 4,
        "cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": script_content}]
    }
    return notebook


def upload_agent_dataset_to_kaggle(api):
    """Upload the multi-agent datasets to a new Kaggle dataset"""
    log("Upload datasets multi-agents vers Kaggle...")
    
    dataset_dir = r"d:\DATA BASE IA\kaggle_dataset_planning_agents"
    os.makedirs(dataset_dir, exist_ok=True)
    
    # Copy all agent datasets to upload folder
    import shutil
    copied = 0
    for f in Path(DATASET_PLANNING_AGENTS).glob("*.jsonl"):
        if "instruct" in f.name:  # only instruct format
            dest = os.path.join(dataset_dir, f.name)
            shutil.copy2(str(f), dest)
            copied += 1
            log(f"  Copié: {f.name} ({f.stat().st_size/1024/1024:.1f} MB)")
    
    log(f"Total: {copied} fichiers copiés dans {dataset_dir}")
    
    # Create dataset-metadata.json
    metadata = {
        "title": "ARKAN Planning Agents Datasets",
        "id": f"{KAGGLE_USERNAME}/arkan-planning-agents-datasets",
        "licenses": [{"name": "CC0-1.0"}],
        "keywords": ["planning", "EPCC", "construction", "oil-gas", "Algeria"],
        "collaborators": [],
        "data": []
    }
    with open(os.path.join(dataset_dir, "dataset-metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    
    try:
        # Try to create new dataset (if not exists)
        api.dataset_create_new(dataset_dir, public=False, quiet=False)
        log("✅ Dataset 'arkan-planning-agents-datasets' créé sur Kaggle!")
    except Exception as e:
        try:
            # If exists, create new version
            api.dataset_create_version(dataset_dir, version_notes="Multi-agent datasets v1", quiet=False)
            log("✅ Dataset mis à jour sur Kaggle!")
        except Exception as e2:
            log(f"⚠️ Erreur upload dataset: {e2}")
    
    return f"{KAGGLE_USERNAME}/arkan-planning-agents-datasets"


def create_and_push_agent_kernel(api, agent_name, kernel_slug, dataset_file, dataset_ref):
    """Create kernel folder and push to Kaggle"""
    kernel_dir = os.path.join(KERNELS_BASE, f"kernel_{agent_name}")
    os.makedirs(kernel_dir, exist_ok=True)
    
    # Generate notebook
    notebook = generate_agent_notebook(agent_name, dataset_file, kernel_slug)
    nb_path = os.path.join(kernel_dir, "notebook.ipynb")
    with open(nb_path, "w", encoding="utf-8") as f:
        json.dump(notebook, f, indent=2)
    
    # Create kernel metadata
    metadata = {
        "id": f"{KAGGLE_USERNAME}/{kernel_slug}",
        "title": f"ARKAN Agent {agent_name.title()} Fine-Tuning",
        "code_file": "notebook.ipynb",
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": True,
        "dataset_sources": [
            f"{KAGGLE_USERNAME}/arkan-planning-agents-datasets",
            BASE_DATASET_KAGGLE,
        ],
        "competition_sources": [],
        "kernel_sources": [],
        "machine_shape": "NvidiaTeslaT4",
    }
    meta_path = os.path.join(kernel_dir, "kernel-metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    
    try:
        api.kernels_push(kernel_dir)
        log(f"  ✅ Kernel '{kernel_slug}' poussé sur Kaggle!")
        return True
    except Exception as e:
        log(f"  ❌ Erreur push kernel '{kernel_slug}': {e}")
        return False


def check_all_kernels_status(api, agents_status):
    """Check status of all running kernels"""
    for agent_name, kernel_slug, _ in [(a[0], a[1], a[2]) for a in AGENTS]:
        if agent_name in agents_status and agents_status[agent_name] in ["COMPLETE", "ERROR"]:
            continue
        try:
            s = api.kernels_status(f"{KAGGLE_USERNAME}/{kernel_slug}")
            status = s.to_dict().get("status", "UNKNOWN")
            agents_status[agent_name] = status
        except Exception as e:
            agents_status[agent_name] = f"ERROR_CHECK: {str(e)[:50]}"
    return agents_status


def print_status_report(agents_status, start_time):
    """Print a comprehensive status report"""
    elapsed = int(time.time() - start_time)
    h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
    
    log("\n" + "="*70)
    log(f"📊 RAPPORT DE SITUATION — ARKAN Multi-Agent Fine-Tuning")
    log(f"⏱️  Temps écoulé : {h:02d}h{m:02d}m{s:02d}s")
    log("="*70)
    
    running = [a for a, st in agents_status.items() if st == "RUNNING"]
    complete = [a for a, st in agents_status.items() if st == "COMPLETE"]
    errors = [a for a, st in agents_status.items() if "ERROR" in str(st)]
    pending = [a for a, _ in AGENTS if a not in agents_status]
    
    log(f"\n✅ TERMINÉS  ({len(complete)}/13) : {', '.join(complete) if complete else 'aucun'}")
    log(f"🔄 EN COURS  ({len(running)}/13) : {', '.join(running) if running else 'aucun'}")
    log(f"⏳ EN ATTENTE ({len(pending)}/13) : {', '.join(pending) if pending else 'aucun'}")
    log(f"❌ ERREURS   ({len(errors)}/13) : {', '.join(errors) if errors else 'aucun'}")
    
    log("\n| Agent | Statut |")
    log("|-------|--------|")
    for agent_name, kernel_slug, _, _ in AGENTS:
        status = agents_status.get(agent_name, "⏳ PENDING")
        icon = {"COMPLETE": "✅", "RUNNING": "🔄", "PENDING": "⏳"}.get(status, "❓")
        if "ERROR" in str(status):
            icon = "❌"
        log(f"| {agent_name:25s} | {icon} {status} |")
    
    log("="*70 + "\n")
    return len(complete), len(running), len(errors)


def main():
    os.makedirs(KERNELS_BASE, exist_ok=True)
    
    log("="*70)
    log("🚀 ARKAN Planning IA — Orchestrateur Multi-Plateformes Fine-Tuning")
    log(f"📅 Démarrage : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"🤖 Agents à fine-tuner : {len(AGENTS)}")
    log("="*70)
    
    api = get_api()
    log("✅ API Kaggle authentifiée")
    
    # Step 1: Upload all agent datasets to Kaggle
    log("\n📤 ÉTAPE 1 : Upload datasets multi-agents vers Kaggle...")
    dataset_ref = upload_agent_dataset_to_kaggle(api)
    log(f"Dataset ref: {dataset_ref}")
    
    # Step 2: Push kernels by priority groups (max 2 simultaneous to save GPU quota)
    log("\n🔧 ÉTAPE 2 : Création et push des kernels Kaggle...")
    
    agents_status = {}
    start_time = time.time()
    
    # Group by priority
    by_priority = {}
    for agent_name, kernel_slug, dataset_file, priority in AGENTS:
        by_priority.setdefault(priority, []).append((agent_name, kernel_slug, dataset_file))
    
    MAX_CONCURRENT = 2  # Kaggle limits concurrent GPU kernels
    
    for priority in sorted(by_priority.keys()):
        group = by_priority[priority]
        log(f"\n[Priority {priority}] Launching {len(group)} agents: {[g[0] for g in group]}")
        
        for agent_name, kernel_slug, dataset_file in group:
            log(f"  Pushing kernel: {kernel_slug}")
            success = create_and_push_agent_kernel(api, agent_name, kernel_slug, dataset_file, dataset_ref)
            if success:
                agents_status[agent_name] = "RUNNING"
                time.sleep(5)  # Small delay between pushes
            else:
                agents_status[agent_name] = "ERROR_PUSH"
        
        # Wait for this priority group to complete (or timeout 90 min)
        log(f"\n⏳ Attente completion du groupe priorité {priority}...")
        timeout = 90 * 60  # 90 minutes
        t_start = time.time()
        
        while time.time() - t_start < timeout:
            agents_status = check_all_kernels_status(api, agents_status)
            group_agents = [g[0] for g in group]
            group_status = {k: v for k, v in agents_status.items() if k in group_agents}
            
            still_running = [k for k, v in group_status.items() if v == "RUNNING"]
            if not still_running:
                break
            
            elapsed_group = int(time.time() - t_start)
            log(f"  [{elapsed_group}s] Encore en cours: {still_running}")
            time.sleep(60)
        
        # Print report every time a group finishes
        print_status_report(agents_status, start_time)
    
    # Final report
    log("\n" + "="*70)
    log("🎉 TOUS LES FINE-TUNINGS LANCÉS!")
    complete, running, errors = print_status_report(agents_status, start_time)
    log(f"📊 Résumé final: {complete} terminés, {running} en cours, {errors} erreurs")
    log("="*70)
    
    # Save status to file
    with open(r"d:\DATA BASE IA\multiagent_status.json", "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "agents_status": agents_status,
            "elapsed_seconds": int(time.time() - start_time)
        }, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
