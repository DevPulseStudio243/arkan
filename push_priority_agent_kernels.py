#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crée et pousse les kernels Kaggle pour les 3 premiers agents prioritaires
(rendements, cpm, wbs) en attente que le dataset soit disponible.
"""
import os, json, sys, time
os.environ['KAGGLE_USERNAME'] = 'psnuser'
os.environ['KAGGLE_KEY'] = 'fd84a193ab60af795f7e2bc4b35603ab'

import urllib3, requests
urllib3.disable_warnings()
_old_send = requests.Session.send
requests.Session.send = lambda self, req, **kw: _old_send(self, req, **{**kw, 'verify': False})
from kaggle.api.kaggle_api_extended import KaggleApi

api = KaggleApi()
api.authenticate()
print("✅ API Kaggle authentifiée")

KAGGLE_USERNAME = 'psnuser'
KERNELS_BASE = r'd:\DATA BASE IA\kaggle_kernels_planning_agents'
os.makedirs(KERNELS_BASE, exist_ok=True)

# Les 3 agents prioritaires à lancer en premier
PRIORITY_AGENTS = [
    ("rendements",    "arkan-agent-rendements-fine-tuning-qwen2-5",    "dataset_planning_rendements_instruct.jsonl"),
    ("cpm",           "arkan-agent-cpm-fine-tuning-qwen2-5",           "dataset_planning_cpm_instruct.jsonl"),
    ("wbs",           "arkan-agent-wbs-fine-tuning-qwen2-5",           "dataset_planning_wbs_instruct.jsonl"),
]

def get_script(agent_name, dataset_file):
    return f'''
import subprocess, sys, os, torch, json

subprocess.run([sys.executable, "-m", "pip", "uninstall", "torchao", "-y"], capture_output=True)
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--upgrade",
    "transformers>=4.45.0", "peft>=0.13.0", "accelerate>=0.34.0", "datasets", "bitsandbytes"
], check=True)

from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments, Trainer, DataCollatorForSeq2Seq
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training, TaskType
from datasets import Dataset

AGENT_NAME = "{agent_name}"
DATASET_FILE = "{dataset_file}"
MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"
OUTPUT_DIR = f"/kaggle/working/arkan_{{AGENT_NAME}}_lora"

print(f"GPU: {{torch.cuda.get_device_name(0)}}, VRAM: {{torch.cuda.get_device_properties(0).total_memory/1e9:.1f}} GB")
print(f"Agent: ARKAN-{{AGENT_NAME}}")

# Load dataset
import glob
print(f"Recherche du dataset {{DATASET_FILE}} sous /kaggle/input/...")
found_files = glob.glob(f"/kaggle/input/**/{{DATASET_FILE}}", recursive=True)
if found_files:
    dataset_path = found_files[0]
else:
    fallback_files = glob.glob("/kaggle/input/**/dataset_planning_epc_instruct.jsonl", recursive=True)
    if fallback_files:
        dataset_path = fallback_files[0]
    else:
        print("Available in /kaggle/input/:", os.listdir("/kaggle/input") if os.path.exists("/kaggle/input") else "None")
        sys.exit(1)

print(f"Using dataset: {{dataset_path}}")
data = []
with open(dataset_path, "r", encoding="utf-8") as f:
    for line in f:
        if line.strip(): data.append(json.loads(line))
print(f"Loaded {{len(data)}} examples")

# 4-bit quantization
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True, bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16,
)

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "right"

model = AutoModelForCausalLM.from_pretrained(MODEL_ID, quantization_config=bnb_config, device_map="auto", trust_remote_code=True)
model = prepare_model_for_kbit_training(model)

lora_config = LoraConfig(r=16, lora_alpha=32,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    lora_dropout=0.05, bias="none", task_type=TaskType.CAUSAL_LM)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()

prompt_template = "<|im_start|>system\\n{{inst}}<|im_end|>\\n<|im_start|>user\\n{{inp}}<|im_end|>\\n<|im_start|>assistant\\n{{out}}<|im_end|>"
formatted = [{{"text": prompt_template.format(inst=ex.get("instruction",""), inp=ex.get("input",""), out=ex.get("output",""))}} for ex in data]
raw_ds = Dataset.from_list(formatted)

def tokenize_fn(examples):
    inputs = tokenizer(examples["text"], truncation=True, max_length=1024)
    inputs["labels"] = inputs["input_ids"].copy()
    return inputs

train_ds = raw_ds.map(tokenize_fn, batched=True, remove_columns=["text"])

args = TrainingArguments(
    output_dir=OUTPUT_DIR, num_train_epochs=3,
    per_device_train_batch_size=2, gradient_accumulation_steps=4,
    warmup_steps=10, max_steps=120, learning_rate=2e-4, fp16=True,
    logging_steps=10, save_steps=60, optim="paged_adamw_8bit",
    lr_scheduler_type="cosine", report_to="none", dataloader_num_workers=0,
)
trainer = Trainer(model=model, train_dataset=train_ds, data_collator=DataCollatorForSeq2Seq(tokenizer=tokenizer, pad_to_multiple_of=8, return_tensors="pt"), args=args)

print(f"\\n🚀 Starting fine-tuning ARKAN-{{AGENT_NAME}}...")
trainer.train()
print("\\n✅ Training complete!")
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
print(f"Saved to {{OUTPUT_DIR}}")

# Quick inference test
test_q = {{
    "rendements": "Quel est le rendement de soudage pour un gazoduc 36\\" ? Donne les valeurs typiques.",
    "cpm": "Calcule le chemin critique d\'un planning gazoduc. Quelles tâches sont critiques ?",
    "wbs": "Génère la WBS complète pour un projet gazoduc de 300 km.",
}}[AGENT_NAME]

inputs = tokenizer(f"<|im_start|>user\\n{{test_q}}<|im_end|>\\n<|im_start|>assistant\\n", return_tensors="pt").to("cuda")
with torch.no_grad():
    out = model.generate(**inputs, max_new_tokens=300, do_sample=False)
resp = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
print(f"\\n=== Test ARKAN-{{AGENT_NAME}} ===")
print(f"Q: {{test_q}}")
print(f"R: {{resp[:400]}}")
print(f"\\n🎉 ARKAN-{{AGENT_NAME}} Fine-Tuning COMPLETE!")
'''

for agent_name, kernel_slug, dataset_file in PRIORITY_AGENTS:
    print(f"\n[{agent_name}] Création kernel '{kernel_slug}'...")
    
    kernel_dir = os.path.join(KERNELS_BASE, f'kernel_{agent_name}')
    os.makedirs(kernel_dir, exist_ok=True)
    
    # Write notebook
    nb = {
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
        "nbformat": 4, "nbformat_minor": 4,
        "cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": get_script(agent_name, dataset_file)}]
    }
    with open(os.path.join(kernel_dir, 'notebook.ipynb'), 'w', encoding='utf-8') as f:
        json.dump(nb, f, indent=2)
    
    # Write kernel metadata
    meta = {
        "id": f"{KAGGLE_USERNAME}/{kernel_slug}",
        "title": f"ARKAN Agent {agent_name.title()} Fine-Tuning Qwen2.5",
        "code_file": "notebook.ipynb",
        "language": "python", "kernel_type": "notebook",
        "is_private": True, "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [
            "psnuser/arkan-planning-agents-datasets",
            "psnuser/arkan-planning-epc-datasets",
        ],
        "competition_sources": [], "kernel_sources": [],
        "machine_shape": "NvidiaTeslaT4",
    }
    with open(os.path.join(kernel_dir, 'kernel-metadata.json'), 'w') as f:
        json.dump(meta, f, indent=2)
    
    # Push to Kaggle
    try:
        api.kernels_push(kernel_dir)
        print(f"  ✅ Kernel '{kernel_slug}' poussé avec succès!")
    except Exception as e:
        print(f"  ❌ Erreur push: {e}")
    
    time.sleep(3)

print("\n✅ Tous les kernels prioritaires ont été poussés sur Kaggle!")
print("Kernels lancés:")
for agent_name, kernel_slug, _ in PRIORITY_AGENTS:
    print(f"  - psnuser/{kernel_slug}")
