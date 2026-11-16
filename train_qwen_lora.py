"""
DeerFlow Lite - Pipeline d'entraînement LoRA pour Qwen 14B
Ce script permet de fine-tuner Qwen 14B pour qu'il adopte le raisonnement "Claude-style"
sur les données d'ingénierie Oil & Gas.

Pré-requis :
pip install torch transformers peft trl datasets bitsandbytes
"""

import os
import json
import torch
from datasets import Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer

# Configuration
MODEL_ID = "Qwen/Qwen2.5-14B-Instruct"  # Ou le chemin de votre modèle local
DATASET_PATH = "data/learning/feedback_expert_dataset.json" # Fichier généré par ContinuousTrainer
OUTPUT_DIR = "models/qwen-14b-oil-gas-lora"

def load_and_format_dataset(file_path):
    """Charge les feedbacks positifs et les formate en prompts d'entraînement ReAct."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Dataset introuvable: {file_path}. Générez quelques réponses via le système d'abord.")
        
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    formatted_data = {"text": []}
    
    for item in data:
        # On n'entraîne que sur les réponses jugées "bonnes" (score élevé)
        if item.get("score", 0) >= 0.8:
            # Format instruct
            prompt = (
                f"<|im_start|>user\n{item['query']}<|im_end|>\n"
                f"<|im_start|>assistant\n"
                f"<thought>\n"
                f"1. Analyser la requête Oil & Gas.\n"
                f"2. Utiliser l'outil pertinent (simulé dans l'entraînement).\n"
                f"3. Formuler une réponse technique structurée.\n"
                f"</thought>\n"
                f"<answer>\n{item['answer']}\n</answer><|im_end|>"
            )
            formatted_data["text"].append(prompt)
            
    print(f"[{len(formatted_data['text'])}] exemples d'entraînement chargés.")
    return Dataset.from_dict(formatted_data)

def train_lora():
    print("=== Démarrage de l'entraînement LoRA (Qwen 14B) ===")
    
    # 1. Charger le Dataset
    dataset = load_and_format_dataset(DATASET_PATH)
    
    # 2. Configuration Quantization 4-bit (pour que ça tourne sur 1-2 GPUs standard type RTX 3090/4090)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16
    )
    
    print("Chargement du modèle de base (peut prendre du temps)...")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=bnb_config,
        device_map="auto"
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model)
    
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    
    # 3. Configuration LoRA (Low-Rank Adaptation)
    # On cible spécifiquement les couches d'attention (q_proj, v_proj)
    peft_config = LoraConfig(
        r=16,               # Rang de la matrice (plus grand = plus de capacité, mais plus lourd)
        lora_alpha=32,      # Scaling factor
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM"
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()
    
    # 4. Paramètres d'entraînement
    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=1,   # Très bas pour économiser la VRAM
        gradient_accumulation_steps=4,   # Compense le petit batch size
        warmup_steps=10,
        max_steps=200,                   # Ajuster selon la taille de vos données
        learning_rate=2e-4,
        fp16=True,
        logging_steps=10,
        optim="paged_adamw_8bit",
        save_strategy="steps",
        save_steps=50,
    )
    
    # 5. Lancer SFT (Supervised Fine-Tuning)
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        peft_config=peft_config,
        dataset_text_field="text",
        max_seq_length=2048,
        tokenizer=tokenizer,
        args=training_args,
    )
    
    print("Entraînement en cours...")
    trainer.train()
    
    # 6. Sauvegarder l'adapteur
    trainer.model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(f"✅ Adapteur LoRA sauvegardé dans : {OUTPUT_DIR}")
    print("Pour l'utiliser dans Ollama, il faudra fusionner ces poids avec le modèle de base.")

if __name__ == "__main__":
    train_lora()
