"""
train_arkan_pid_lora.py
=======================
Script de Fine-Tuning QLoRA avec Unsloth AI pour entraîner ARKAN-PID-7B sur les 559 plans réels Sonatrach & EPC.

Modèle de base : unsloth/Qwen2.5-7B-Instruct-bnb-4bit
Dataset : data/training_pid_dataset.jsonl
Sortie : arkan_pid_lora_adapter (Sauvegarde LoRA 16-rank)
"""

import os
import torch
import json
from pathlib import Path

def main():
    try:
        from unsloth import FastLanguageModel
        from datasets import load_dataset
        from trl import SFTTrainer
        from transformers import TrainingArguments
    except ImportError:
        print("[INFO] Unsloth n'est pas installé dans l'environnement local.")
        print("[INFO] Ce script est prêt pour exécution sur GPU Local (avec Unsloth), Kaggle ou Google Colab.")
        return

    MAX_SEQ_LENGTH = 2048
    DTYPE = None
    LOAD_IN_4BIT = True
    OUTPUT_DIR = "arkan_pid_lora_adapter"

    print("[1/5] Chargement du modèle Qwen2.5-7B-Instruct 4-bit...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name="unsloth/Qwen2.5-7B-Instruct-bnb-4bit",
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=DTYPE,
        load_in_4bit=LOAD_IN_4BIT,
    )

    print("[2/5] Configuration des adaptateurs QLoRA (r=16, alpha=32)...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=32,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    dataset_path = "data/training_pid_dataset.jsonl"
    print(f"[3/5] Chargement du dataset {dataset_path}...")
    dataset = load_dataset("json", data_files=dataset_path, split="train")

    def formatting_prompts_func(examples):
        instructions = examples["instruction"]
        inputs = examples["input"]
        outputs = examples["output"]
        texts = []
        for instruction, input_text, output in zip(instructions, inputs, outputs):
            prompt = (
                f"<|im_start|>system\n{instruction}<|im_end|>\n"
                f"<|im_start|>user\n{input_text}<|im_end|>\n"
                f"<|im_start|>assistant\n{output}<|im_end|>"
            )
            texts.append(prompt)
        return {"text": texts}

    dataset = dataset.map(formatting_prompts_func, batched=True)

    print("[4/5] Initialisation du SFTTrainer...")
    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        max_steps=120,
        learning_rate=2e-4,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=5,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=42,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=MAX_SEQ_LENGTH,
        dataset_num_proc=2,
        packing=False,
        args=training_args,
    )

    print("[5/5] Lancement de l'entraînement LoRA...")
    trainer.train()

    print(f"[OK] Sauvegarde de l'adaptateur LoRA dans {OUTPUT_DIR}...")
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(" Entraînement terminé avec succès !")

if __name__ == "__main__":
    main()
