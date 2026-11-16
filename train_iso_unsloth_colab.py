"""
Arkan_Isometric_MTO_FineTuning.py
Script d'entraînement autonome pour Google Colab (GPU T4 / A100) et Kaggle.
Fine-tuning Qwen2.5-VL / Qwen2.5-7B avec Unsloth QLoRA pour l'extraction MTO Isométrique.
"""

import os
import torch
import json
from datasets import Dataset
from transformers import TrainingArguments

def main():
    print("=== ARKAN ISOMETRIC MTO FINE-TUNING (UNSLOTH QLORA) ===")
    print(f"CUDA disponible : {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU Actif : {torch.cuda.get_device_name(0)}")
        print(f"VRAM Totale : {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")

    # 1. Chargement du modèle avec Unsloth (Accélération 2x, Mémoire réduite de 70%)
    try:
        from unsloth import FastLanguageModel
        from trl import SFTTrainer
    except ImportError:
        print("[Install] Installation d'Unsloth en cours...")
        os.system("pip install --no-deps \"unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git\"")
        os.system("pip install --no-deps trl peft accelerate bitsandbytes")
        from unsloth import FastLanguageModel
        from trl import SFTTrainer

    max_seq_length = 2048
    load_in_4bit = True

    model_name = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
    print(f"[Loading] Téléchargement du modèle de base : {model_name}...")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_name,
        max_seq_length=max_seq_length,
        dtype=None,
        load_in_4bit=load_in_4bit,
    )

    # 2. Configuration des adaptateurs LoRA
    print("[LoRA] Configuration des couches LoRA de précision...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )

    # 3. Préparation du Dataset
    train_file = "data/fine_tuning_iso/iso_mto_train.jsonl"
    eval_file = "data/fine_tuning_iso/iso_mto_eval.jsonl"

    if not os.path.exists(train_file):
        print(f"[Warning] {train_file} non trouvé. Génération du dataset...")
        from dataset_iso_generator import generate_dataset
        generate_dataset()

    def load_jsonl_conversations(file_path):
        data = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    # Formater en prompt ChatML / Qwen
                    conv = item["conversations"]
                    formatted_text = tokenizer.apply_chat_template(conv, tokenize=False, add_generation_prompt=False)
                    data.append({"text": formatted_text})
        return Dataset.from_list(data)

    print("[Dataset] Chargement et tokenisation du jeu de données...")
    train_dataset = load_jsonl_conversations(train_file)
    eval_dataset = load_jsonl_conversations(eval_file)
    print(f" -> Train: {len(train_dataset)} conversations | Eval: {len(eval_dataset)} conversations")

    # 4. Paramètres d'entraînement SFT
    training_args = TrainingArguments(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        max_steps=120,
        learning_rate=2e-4,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=10,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="cosine",
        seed=3407,
        output_dir="arkan_iso_lora_outputs",
        report_to="none"
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_dataset,
        dataset_text_field="text",
        max_seq_length=max_seq_length,
        dataset_num_proc=2,
        packing=False,
        args=training_args,
    )

    # 5. Démarrage du Fine-Tuning
    print("\n[Training] Lancement de l'entraînement QLoRA...")
    trainer_stats = trainer.train()
    print("[Training] Entraînement terminé avec succès !")

    # 6. Sauvegarde des poids LoRA et du modèle exportable GGUF
    export_dir = "models/arkan_iso_qwen_lora"
    os.makedirs(export_dir, exist_ok=True)
    model.save_pretrained(export_dir)
    tokenizer.save_pretrained(export_dir)
    print(f"[Export] Poids LoRA sauvegardés dans {export_dir}")

    print("\n[Export GGUF] Pour exporter en GGUF 16bit ou q4_k_m pour inférence locale dans ARKAN :")
    print("model.save_pretrained_gguf('models/arkan_iso_q4_k_m', tokenizer, quantization_method='q4_k_m')")
    print("=== FIN DU PROCESSUS D'ENTRAÎNEMENT ===")

if __name__ == "__main__":
    main()
