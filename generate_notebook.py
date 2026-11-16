import json

notebook = {
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "# 🧠 Fine-Tuning ARKAN-ARH-7B sur Kaggle (GPU T4 Gratuit)\n",
    "Ce notebook permet d'entraîner le modèle spécialisé **ARKAN-ARH-7B** (basé sur `Qwen2.5-7B-Instruct`) sur le dataset de 1 500 cas d'ingénierie et de réglementation ARH (Décrets 21-261, 21-314, 21-315, 24-278, ASME, API 5L, NACE MR0175).\n",
    "\n",
    "**Durée estimée : ~30 minutes sur GPU T4.**"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "### Étape 1 : Installation de la bibliothèque ultra-rapide Unsloth"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "!pip install --no-deps \"unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git\"\n",
    "!pip install --no-deps \"xformers<0.0.27\" \"trl<0.9.0\" peft accelerate bitsandbytes datasets"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "### Étape 2 : Chargement du Modèle de Base Qwen2.5-7B (4-bit QLoRA)"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "import torch\n",
    "from unsloth import FastLanguageModel\n",
    "\n",
    "max_seq_length = 2048\n",
    "dtype = None\n",
    "load_in_4bit = True\n",
    "\n",
    "model, tokenizer = FastLanguageModel.from_pretrained(\n",
    "    model_name = \"unsloth/Qwen2.5-7B-Instruct-bnb-4bit\",\n",
    "    max_seq_length = max_seq_length,\n",
    "    dtype = dtype,\n",
    "    load_in_4bit = load_in_4bit,\n",
    ")\n",
    "\n",
    "# Ajout des adaptateurs LoRA\n",
    "model = FastLanguageModel.get_peft_model(\n",
    "    model,\n",
    "    r = 16,\n",
    "    target_modules = [\"q_proj\", \"k_proj\", \"v_proj\", \"o_proj\", \"gate_proj\", \"up_proj\", \"down_proj\"],\n",
    "    lora_alpha = 32,\n",
    "    lora_dropout = 0,\n",
    "    bias = \"none\",\n",
    "    use_gradient_checkpointing = \"unsloth\",\n",
    "    random_state = 42,\n",
    ")\n",
    "print(\"Modèle et adaptateurs LoRA initialisés avec succès !\")"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "### Étape 3 : Chargement et Formattage du Dataset ARH (1 500 Cas)"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "from datasets import load_dataset\n",
    "\n",
    "def formatting_prompts_func(examples):\n",
    "    instructions = examples[\"instruction\"]\n",
    "    inputs = examples[\"input\"]\n",
    "    outputs = examples[\"output\"]\n",
    "    texts = []\n",
    "    for instruction, input_text, output in zip(instructions, inputs, outputs):\n",
    "        prompt = f\"<|im_start|>system\\n{instruction}<|im_end|>\\n<|im_start|>user\\n{input_text}<|im_end|>\\n<|im_start|>assistant\\n{output}<|im_end|>\"\n",
    "        texts.append(prompt)\n",
    "    return {\"text\": texts}\n",
    "\n",
    "# Remplacez par le chemin de votre dataset uploadé sur Kaggle (ex: /kaggle/input/... ou dataset_arh_1500.jsonl)\n",
    "import os\n",
    "dataset_path = \"dataset_arh_1500.jsonl\"\n",
    "if not os.path.exists(dataset_path):\n",
    "    # Chercher dans les datasets Kaggle input\n",
    "    for root, dirs, files in os.walk(\"/kaggle/input\"):\n",
    "        if \"dataset_arh_1500.jsonl\" in files:\n",
    "            dataset_path = os.path.join(root, \"dataset_arh_1500.jsonl\")\n",
    "            break\n",
    "\n",
    "print(\"Chargement du dataset depuis :\", dataset_path)\n",
    "dataset = load_dataset(\"json\", data_files={\"train\": dataset_path}, split=\"train\")\n",
    "dataset = dataset.map(formatting_prompts_func, batched=True)\n",
    "print(f\"Total exemples prêts : {len(dataset)}\")"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "### Étape 4 : Lancement du Fine-Tuning (3 Époques)"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "from trl import SFTTrainer\n",
    "from transformers import TrainingArguments\n",
    "\n",
    "trainer = SFTTrainer(\n",
    "    model = model,\n",
    "    tokenizer = tokenizer,\n",
    "    train_dataset = dataset,\n",
    "    dataset_text_field = \"text\",\n",
    "    max_seq_length = max_seq_length,\n",
    "    dataset_num_proc = 2,\n",
    "    packing = False,\n",
    "    args = TrainingArguments(\n",
    "        per_device_train_batch_size = 2,\n",
    "        gradient_accumulation_steps = 4,\n",
    "        warmup_ratio = 0.05,\n",
    "        num_train_epochs = 3,\n",
    "        learning_rate = 2e-4,\n",
    "        fp16 = not torch.cuda.is_bf16_supported(),\n",
    "        bf16 = torch.cuda.is_bf16_supported(),\n",
    "        logging_steps = 10,\n",
    "        optim = \"adamw_8bit\",\n",
    "        weight_decay = 0.01,\n",
    "        lr_scheduler_type = \"cosine\",\n",
    "        seed = 42,\n",
    "        output_dir = \"outputs_arh_7b\",\n",
    "        report_to = \"none\"\n",
    "    ),\n",
    ")\n",
    "\n",
    "print(\"Démarrage du Fine-Tuning...\")\n",
    "trainer_stats = trainer.train()\n",
    "print(\"Fine-Tuning terminé avec succès !\")"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "### Étape 5 : Export et Téléchargement au format GGUF (Q4_K_M)"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "# Export en GGUF 4-bit pour Ollama / ARKAN Local\n",
    "model.save_pretrained_gguf(\"arkan_arh_7b_gguf\", tokenizer, quantization_method = \"q4_k_m\")\n",
    "print(\"Modèle GGUF généré dans le dossier 'arkan_arh_7b_gguf' !\")\n",
    "\n",
    "# Créer une archive zip téléchargeable\n",
    "!zip -r arkan_arh_7b_model.zip arkan_arh_7b_gguf/\n",
    "print(\"Archive arkan_arh_7b_model.zip prête à être téléchargée dans le volet Output de Kaggle !\")"
   ]
  }
 ],
 "metadata": {
  "accelerator": "GPU",
  "kernelspec": {
   "display_name": "Python 3",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.10.12"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 2
}

with open("d:/DATA BASE IA/train_arkan_arh_7b_kaggle.ipynb", "w", encoding="utf-8") as f:
    json.dump(notebook, f, indent=1, ensure_ascii=False)

print("Notebook d:/DATA BASE IA/train_arkan_arh_7b_kaggle.ipynb créé avec succès !")
