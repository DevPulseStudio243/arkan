import json
from pathlib import Path

# Charger le dataset extrait
with open("data/training_pid_dataset.jsonl", "r", encoding="utf-8") as f:
    dataset_lines = [json.loads(line) for line in f if line.strip()]

dataset_json_str = json.dumps(dataset_lines, ensure_ascii=False)

nb = {
    "cells": [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# 🔬 ARKAN PID GENERATOR EXPERT — FINE-TUNING GOOGLE COLAB\n",
                "### Entraînement LoRA sur Qwen2.5-7B-Instruct avec les 559 plans réels Sonatrach & standards ISA 5.1 / ASME\n",
                "\n",
                "**Instructions :**\n",
                "1. Allez dans le menu **Exécution > Modifier le type d'exécution** et sélectionnez un **GPU T4**.\n",
                "2. Cliquez sur **Exécution > Tout exécuter**.\n",
                "3. À la fin de l'entraînement (~15-20 min), l'archive `arkan_pid_lora_adapter.zip` sera automatiquement téléchargée sur votre PC pour être déposée dans ARKAN."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# 1. Installation optimisée d'Unsloth (Accélération x2, Mémoire -70%)\n",
                "!pip install --no-deps \"unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git\"\n",
                "!pip install --no-deps xformers \"trl<0.9.0\" peft accelerate bitsandbytes datasets transformers"
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
                "# 2. Chargement du modèle de base Qwen2.5-7B-Instruct en 4-bit\n",
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
                "# 3. Configuration des adaptateurs LoRA (r=16, alpha=32)\n",
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
                "print('✅ Modèle et adaptateurs LoRA configurés !')"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "import json\n",
                "from datasets import Dataset\n",
                "\n",
                "# 4. Chargement des 68 exemples d'ingénierie Sonatrach et EPC\n",
                f"raw_data = {dataset_json_str}\n\n",
                "def format_chatml(example):\n",
                "    prompt = (\n",
                "        f\"<|im_start|>system\\n{example['instruction']}<|im_end|>\\n\"\n",
                "        f\"<|im_start|>user\\n{example['input']}<|im_end|>\\n\"\n",
                "        f\"<|im_start|>assistant\\n{example['output']}<|im_end|>\"\n",
                "    )\n",
                "    return {'text': prompt}\n\n",
                "dataset = Dataset.from_list(raw_data).map(format_chatml)\n",
                "print(f'✅ Dataset chargé : {len(dataset)} exemples réels d\\'entraînement.')"
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
                "# 5. Lancement de l'Entraînement LoRA\n",
                "output_dir = 'arkan_pid_lora_adapter'\n",
                "\n",
                "training_args = TrainingArguments(\n",
                "    output_dir = output_dir,\n",
                "    per_device_train_batch_size = 2,\n",
                "    gradient_accumulation_steps = 4,\n",
                "    warmup_steps = 10,\n",
                "    max_steps = 120,\n",
                "    learning_rate = 2e-4,\n",
                "    fp16 = not torch.cuda.is_bf16_supported(),\n",
                "    bf16 = torch.cuda.is_bf16_supported(),\n",
                "    logging_steps = 10,\n",
                "    optim = 'adamw_8bit',\n",
                "    weight_decay = 0.01,\n",
                "    lr_scheduler_type = 'linear',\n",
                "    seed = 42,\n",
                "    report_to = 'none'\n",
                ")\n",
                "\n",
                "trainer = SFTTrainer(\n",
                "    model = model,\n",
                "    tokenizer = tokenizer,\n",
                "    train_dataset = dataset,\n",
                "    dataset_text_field = 'text',\n",
                "    max_seq_length = max_seq_length,\n",
                "    dataset_num_proc = 2,\n",
                "    packing = False,\n",
                "    args = training_args,\n",
                ")\n",
                "\n",
                "print('🚀 Entraînement en cours...')\n",
                "trainer_stats = trainer.train()\n",
                "print('✅ Entraînement terminé avec succès !')"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "import shutil\n",
                "from google.colab import files\n",
                "\n",
                "# 6. Sauvegarde et Téléchargement Automatique\n",
                "model.save_pretrained(output_dir)\n",
                "tokenizer.save_pretrained(output_dir)\n",
                "\n",
                "zip_file = shutil.make_archive(output_dir, 'zip', output_dir)\n",
                "print(f'Archive prête : {zip_file}')\n",
                "print('Téléchargement en cours vers votre PC portable...')\n",
                "files.download(zip_file)"
            ]
        }
    ],
    "metadata": {
        "accelerator": "GPU",
        "colab": {"gpuType": "T4", "provenance": []},
        "language_info": {"name": "python"}
    },
    "nbformat": 4,
    "nbformat_minor": 0
}

output_path = Path("train_arkan_pid_colab.ipynb")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=2)

print(f"Notebook Google Colab généré avec succès dans {output_path} ({output_path.stat().st_size} octets)")
