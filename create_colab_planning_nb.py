import json, os

colab_nb = {
  "cells": [
    {
      "cell_type": "markdown",
      "metadata": {
        "id": "intro_header"
      },
      "source": [
        "# 🏗️ ARKAN Planning EPCC — Studio Parallèle Multi-Agents Google Colab (GPU T4)\n",
        "**URL Officielle du Notebook :** https://colab.research.google.com/drive/1cVXbSH0gaCRhawtp9X8i26h6WOdYIq2k\n",
        "**Modèle de base :** Qwen/Qwen2.5-3B-Instruct (4-bit QLoRA bitsandbytes)\n",
        "**Objectif :** Entraîner les agents spécialisés de planification ARKAN en parallèle avec Kaggle sur GPU Tesla T4.\n",
        "\n",
        "### ⚡ Instructions Rapides :\n",
        "1. Menu **Exécution** > **Modifier le type d'exécution** > Sélectionnez **GPU T4**.\n",
        "2. Sélectionnez l'agent à entraîner ou 'ALL_AGENTS' pour tout entraîner à la suite.\n",
        "3. Cliquez sur **Exécution** > **Tout exécuter**."
      ]
    },
    {
      "cell_type": "code",
      "execution_count": None,
      "metadata": {
        "id": "step1_deps"
      },
      "outputs": [],
      "source": [
        "#@title 1. Installation des Dépendances Accélérées (GPU T4)\n",
        "!pip uninstall -y torchao 2>/dev/null; pip install -q --upgrade transformers peft accelerate datasets bitsandbytes trl kaggle huggingface_hub\n",
        "import torch\n",
        "print(f'[+] GPU Détecté : {torch.cuda.get_device_name(0)} ({torch.cuda.get_device_properties(0).total_memory/1e9:.2f} Go VRAM)')\n",
        "print('[+] Dépendances prêtes !')"
      ]
    },
    {
      "cell_type": "code",
      "execution_count": None,
      "metadata": {
        "id": "step2_config"
      },
      "outputs": [],
      "source": [
        "#@title 2. Sélection de l'Agent de Planification à Fine-Tuner\n",
        "AGENT_SELECTION = \"ALL_AGENTS\" #@param [\"ALL_AGENTS\", \"CPM_CRITICAL_PATH\", \"RENDEMENTS_CADENCES\", \"WBS_DECOMPOSITION\", \"COMMISSIONING_STARTUP\", \"CONSTRUCTION_DISCIPLINES\", \"PIPELINES_TRANSPORTS\", \"ENGINEERING_IFC\", \"PROCUREMENT_LLI\", \"SOLAR_PV\", \"STORAGE_TANKS\", \"HSE_SAFETY\", \"RESOURCES_MANNING\", \"ORCHESTRATEUR_MASTER\"]\n",
        "NUM_TRAIN_STEPS = 120 #@param {type:\"integer\"}\n",
        "LEARNING_RATE = 2e-4 #@param {type:\"number\"}\n",
        "BATCH_SIZE = 2 #@param {type:\"integer\"}\n",
        "GRAD_ACCUM = 4 #@param {type:\"integer\"}\n",
        "\n",
        "AGENT_DATASET_MAP = {\n",
        "    \"CPM_CRITICAL_PATH\": (\"arkan-planning-cpm\", \"dataset_planning_cpm_instruct.jsonl\"),\n",
        "    \"RENDEMENTS_CADENCES\": (\"arkan-planning-rendements\", \"dataset_planning_rendements_instruct.jsonl\"),\n",
        "    \"WBS_DECOMPOSITION\": (\"arkan-planning-wbs\", \"dataset_planning_wbs_instruct.jsonl\"),\n",
        "    \"COMMISSIONING_STARTUP\": (\"arkan-planning-commissioning\", \"dataset_planning_commissioning_instruct.jsonl\"),\n",
        "    \"CONSTRUCTION_DISCIPLINES\": (\"arkan-planning-construction\", \"dataset_planning_construction_instruct.jsonl\"),\n",
        "    \"PIPELINES_TRANSPORTS\": (\"arkan-planning-pipelines\", \"dataset_planning_pipelines_instruct.jsonl\"),\n",
        "    \"ENGINEERING_IFC\": (\"arkan-planning-engineering\", \"dataset_planning_engineering_instruct.jsonl\"),\n",
        "    \"PROCUREMENT_LLI\": (\"arkan-planning-procurement\", \"dataset_planning_procurement_instruct.jsonl\"),\n",
        "    \"SOLAR_PV\": (\"arkan-planning-solaire\", \"dataset_planning_solaire_instruct.jsonl\"),\n",
        "    \"STORAGE_TANKS\": (\"arkan-planning-bacs\", \"dataset_planning_bacs_instruct.jsonl\"),\n",
        "    \"HSE_SAFETY\": (\"arkan-planning-hse\", \"dataset_planning_hse_instruct.jsonl\"),\n",
        "    \"RESOURCES_MANNING\": (\"arkan-planning-ressources\", \"dataset_planning_ressources_instruct.jsonl\"),\n",
        "    \"ORCHESTRATEUR_MASTER\": (\"arkan-orchestrateur\", \"dataset_planning_orchestrateur_instruct.jsonl\"),\n",
        "}\n",
        "\n",
        "print(f\"[*] Option sélectionnée : {AGENT_SELECTION}\")\n",
        "print(f\"[*] Paramètres : {NUM_TRAIN_STEPS} steps, LR={LEARNING_RATE}, Batch={BATCH_SIZE}x{GRAD_ACCUM}\")"
      ]
    },
    {
      "cell_type": "code",
      "execution_count": None,
      "metadata": {
        "id": "step3_download_data"
      },
      "outputs": [],
      "source": [
        "#@title 3. Téléchargement des Datasets Multi-Agents depuis Kaggle\n",
        "import os\n",
        "os.environ['KAGGLE_USERNAME'] = 'psnuser'\n",
        "os.environ['KAGGLE_KEY'] = 'fd84a193ab60af795f7e2bc4b35603ab'\n",
        "\n",
        "import kaggle\n",
        "kaggle.api.authenticate()\n",
        "print('[*] Authentification Kaggle réussie.')\n",
        "\n",
        "print('[*] Téléchargement du pack datasets multi-agents...')\n",
        "try:\n",
        "    kaggle.api.dataset_download_files('psnuser/arkan-planning-agents-datasets', unzip=True)\n",
        "    print('[+] Pack arkan-planning-agents-datasets extrait avec succès !')\n",
        "except Exception as e:\n",
        "    print(f'[!] Info : {e}')\n",
        "    kaggle.api.dataset_download_files('psnuser/arkan-planning-epc-datasets', unzip=True)\n",
        "    print('[+] Dataset master arkan-planning-epc-datasets extrait en fallback !')\n"
      ]
    },
    {
      "cell_type": "code",
      "execution_count": None,
      "metadata": {
        "id": "step4_train"
      },
      "outputs": [],
      "source": [
        "#@title 4. Entraînement QLoRA 4-bit Accéléré (GPU T4)\n",
        "import torch, json, time\n",
        "from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments, DataCollatorForSeq2Seq, BitsAndBytesConfig\n",
        "from peft import LoraConfig, get_peft_model, TaskType, prepare_model_for_kbit_training\n",
        "from datasets import Dataset\n",
        "\n",
        "model_id = 'Qwen/Qwen2.5-3B-Instruct'\n",
        "tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)\n",
        "tokenizer.pad_token = tokenizer.eos_token\n",
        "\n",
        "bnb_config = BitsAndBytesConfig(\n",
        "    load_in_4bit=True,\n",
        "    bnb_4bit_use_double_quant=True,\n",
        "    bnb_4bit_quant_type='nf4',\n",
        "    bnb_4bit_compute_dtype=torch.float16,\n",
        ")\n",
        "\n",
        "agents_to_run = list(AGENT_DATASET_MAP.items()) if AGENT_SELECTION == 'ALL_AGENTS' else [(AGENT_SELECTION, AGENT_DATASET_MAP[AGENT_SELECTION])]\n",
        "\n",
        "for key, (agent_name, dataset_file) in agents_to_run:\n",
        "    print(f'\\n======================================================================')\n",
        "    print(f'🚀 ENTRAÎNEMENT AGENT : {agent_name} ({dataset_file})')\n",
        "    print(f'======================================================================')\n",
        "    \n",
        "    if not os.path.exists(dataset_file):\n",
        "        dataset_file = 'dataset_planning_epc_instruct.jsonl'\n",
        "        \n",
        "    data = []\n",
        "    with open(dataset_file, 'r', encoding='utf-8') as f:\n",
        "        for line in f:\n",
        "            if line.strip(): data.append(json.loads(line))\n",
        "    print(f'[+] {len(data)} exemples experts chargés.')\n",
        "    \n",
        "    model = AutoModelForCausalLM.from_pretrained(model_id, quantization_config=bnb_config, device_map='cuda:0', low_cpu_mem_usage=True, trust_remote_code=True)\n",
        "    model = prepare_model_for_kbit_training(model)\n",
        "    \n",
        "    peft_config = LoraConfig(\n",
        "        r=16, lora_alpha=32,\n",
        "        target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj'],\n",
        "        lora_dropout=0.05, bias='none', task_type=TaskType.CAUSAL_LM,\n",
        "    )\n",
        "    model = get_peft_model(model, peft_config)\n",
        "    \n",
        "    prompt_template = '<|im_start|>system\\n{inst}<|im_end|>\\n<|im_start|>user\\n{inp}<|im_end|>\\n<|im_start|>assistant\\n{out}<|im_end|>'\n",
        "    formatted = [{'text': prompt_template.format(inst=ex.get('instruction',''), inp=ex.get('input',''), out=ex.get('output',''))} for ex in data]\n",
        "    raw_ds = Dataset.from_list(formatted)\n",
        "    train_ds = raw_ds.map(lambda ex: tokenizer(ex['text'], truncation=True, max_length=1024), batched=True, remove_columns=['text'])\n",
        "    \n",
        "    out_dir = f'./checkpoints_{agent_name}'\n",
        "    training_args = TrainingArguments(\n",
        "        output_dir=out_dir,\n",
        "        per_device_train_batch_size=BATCH_SIZE,\n",
        "        gradient_accumulation_steps=GRAD_ACCUM,\n",
        "        warmup_steps=10,\n",
        "        max_steps=NUM_TRAIN_STEPS,\n",
        "        learning_rate=LEARNING_RATE,\n",
        "        fp16=True,\n",
        "        logging_steps=10,\n",
        "        optim='paged_adamw_8bit',\n",
        "        lr_scheduler_type='cosine',\n",
        "        report_to='none',\n",
        "    )\n",
        "    trainer = Trainer(model=model, train_dataset=train_ds, data_collator=DataCollatorForSeq2Seq(tokenizer=tokenizer, pad_to_multiple_of=8, return_tensors='pt'), args=training_args)\n",
        "    trainer.train()\n",
        "    \n",
        "    save_path = f'./{agent_name}_lora'\n",
        "    model.save_pretrained(save_path)\n",
        "    tokenizer.save_pretrained(save_path)\n",
        "    print(f'[+] Modèle sauvegardé dans {save_path}')\n",
        "    \n",
        "    del model, trainer\n",
        "    torch.cuda.empty_cache()\n",
        "    print(f'✅ Agent {agent_name} terminé avec succès !')\n"
      ]
    },
    {
      "cell_type": "code",
      "execution_count": None,
      "metadata": {
        "id": "step5_eval"
      },
      "outputs": [],
      "source": [
        "#@title 5. Test d'Inférence Structurée de Validation\n",
        "test_prompt = '<|im_start|>user\\nCalcule le chemin critique, les marges libres et les rendements de soudage pour un gazoduc 36 pouces de 180 km en Algérie.<|im_end|>\\n<|im_start|>assistant\\n'\n",
        "from transformers import AutoModelForCausalLM, AutoTokenizer\n",
        "from peft import PeftModel\n",
        "\n",
        "eval_tok = AutoTokenizer.from_pretrained('Qwen/Qwen2.5-3B-Instruct', trust_remote_code=True)\n",
        "eval_base = AutoModelForCausalLM.from_pretrained('Qwen/Qwen2.5-3B-Instruct', quantization_config=bnb_config, device_map='cuda:0', trust_remote_code=True)\n",
        "eval_model = PeftModel.from_pretrained(eval_base, './arkan-planning-cpm_lora')\n",
        "\n",
        "inputs = eval_tok(test_prompt, return_tensors='pt').to('cuda')\n",
        "with torch.no_grad():\n",
        "    outputs = eval_model.generate(**inputs, max_new_tokens=400, temperature=0.1, do_sample=True)\n",
        "print(eval_tok.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True))\n"
      ]
    }
  ],
  "metadata": {
    "accelerator": "GPU",
    "colab": {
      "gpuType": "T4",
      "provenance": []
    },
    "kernelspec": {
      "display_name": "Python 3",
      "name": "python3"
    },
    "language_info": {
      "name": "python"
    }
  },
  "nbformat": 4,
  "nbformat_minor": 0
}

nb_colab_path = r'd:\DATA BASE IA\ARKAN_Planning_Colab_FineTuning.ipynb'
with open(nb_colab_path, 'w', encoding='utf-8') as f:
    json.dump(colab_nb, f, indent=2)

print('[+] Colab notebook updated at:', nb_colab_path)
