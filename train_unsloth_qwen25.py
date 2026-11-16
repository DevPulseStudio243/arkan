"""
train_unsloth_qwen25.py
=======================
Script de Fine-Tuning QLoRA ultra-optimisé avec Unsloth AI pour entraîner ARKAN-ARH-7B sur Kaggle / Google Colab / GPU Local.

Modèle de base : Qwen/Qwen2.5-7B-Instruct (ou unsloth/Qwen2.5-7B-Instruct-bnb-4bit)
Temps d'entraînement sur GPU Kaggle T4 : ~30 minutes pour 1 500 exemples.
"""

import torch
import json
from unsloth import FastLanguageModel
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments

# ── 1. CONFIGURATION DU MODÈLE & HYPERPARAMÈTRES ──
MAX_SEQ_LENGTH = 2048
DTYPE = None # Auto detection (Float16 ou Bfloat16)
LOAD_IN_4BIT = True # Quantization 4-bit pour économiser la VRAM

print("[1/5] Chargement du modèle de base Qwen2.5-7B-Instruct (4-bit)...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Qwen2.5-7B-Instruct-bnb-4bit",
    max_seq_length=MAX_SEQ_LENGTH,
    dtype=DTYPE,
    load_in_4bit=LOAD_IN_4BIT,
)

# ── 2. CONFIGURATION DES ADAPTATEURS LoRA ──
print("[2/5] Injection des adaptateurs QLoRA (r=16, alpha=32)...")
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
    lora_alpha=32,
    lora_dropout=0, # Unsloth optimise avec 0 dropout
    bias="none",
    use_gradient_checkpointing="unsloth", # 30% VRAM en moins
    random_state=42,
)

# ── 3. CHARGEMENT ET FORMATTAGE DU DATASET ARH ──
print("[3/5] Chargement du dataset dataset_arh_1500.jsonl...")

def formatting_prompts_func(examples):
    instructions = examples["instruction"]
    inputs = examples["input"]
    outputs = examples["output"]
    texts = []
    
    # Template ChatML officiel de Qwen2.5
    for instruction, input_text, output in zip(instructions, inputs, outputs):
        prompt = (
            f"<|im_start|>system\n{instruction}<|im_end|>\n"
            f"<|im_start|>user\n{input_text}<|im_end|>\n"
            f"<|im_start|>assistant\n{output}<|im_end|>"
        )
        texts.append(prompt)
    return {"text": texts}

dataset = load_dataset("json", data_files={"train": "dataset_arh_1500.jsonl"}, split="train")
dataset = dataset.map(formatting_prompts_func, batched=True)

# ── 4. LANCEMENT DE L'ENTRAÎNEMENT (3 ÉPOQUES) ──
print("[4/5] Configuration du Trainer (3 Époques, Batch Size=2, Grad Accum=4)...")
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=MAX_SEQ_LENGTH,
    dataset_num_proc=2,
    packing=False, # Conserve les frontières de documents
    args=TrainingArguments(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_ratio=0.05,
        num_train_epochs=3, # 3 époques pour assimilation complète
        learning_rate=2e-4,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=10,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="cosine",
        seed=42,
        output_dir="outputs_arh_7b",
        report_to="none"
    ),
)

print("\n🚀 Démarrage de l'entraînement d'ARKAN-ARH-7B...")
trainer_stats = trainer.train()
print("✅ Entraînement terminé avec succès !")

# ── 5. EXPORT DU MODÈLE AU FORMAT GGUF (POUR OLLAMA & ARKAN LOCAL) ──
print("\n[5/5] Exportation et conversion au format GGUF (Q4_K_M)...")
model.save_pretrained_gguf("arkan_arh_7b_gguf", tokenizer, quantization_method="q4_k_m")
print("🎉 Modèle exporté dans le dossier 'arkan_arh_7b_gguf/arkan_arh_7b_q4_k_m.gguf' !")
