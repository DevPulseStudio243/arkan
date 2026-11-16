import os
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
import json
import sys
import shutil
import time
import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
    DataCollatorForSeq2Seq,
    BitsAndBytesConfig,
)
from peft import prepare_model_for_kbit_training, LoraConfig, get_peft_model, TaskType
from datasets import Dataset

print(f"[*] Processus Demarre : PyTorch = {torch.__version__}")
print(f"[*] CUDA disponible = {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"[*] GPU = {torch.cuda.get_device_name(0)} (VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} Go)")

model_id = "Qwen/Qwen2.5-3B-Instruct"
print(f"[*] Chargement Tokenizer {model_id}...")
tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
tokenizer.pad_token = tokenizer.eos_token

print(f"[*] Configuration QLoRA 4-bit (VRAM ultra-optimisee ~2.5 Go)...")
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True,
)

model = AutoModelForCausalLM.from_pretrained(
    model_id,
    quantization_config=bnb_config,
    device_map={"": 0},
    trust_remote_code=True,
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

# Recherche du Dataset
dataset_filename = "dataset_planning_epc_instruct.jsonl"
dataset_path = f"/kaggle/input/arkan-planning-epc-datasets/{dataset_filename}"
if not os.path.exists(dataset_path):
    for root, dirs, files in os.walk("/kaggle/input"):
        if dataset_filename in files:
            dataset_path = os.path.join(root, dataset_filename)
            break

print(f"[*] Lecture du Dataset depuis {dataset_path}...")
data = []
with open(dataset_path, "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            data.append(json.loads(line))

print(f"[+] {len(data)} exemples experts charges pour le Planning EPCC.")

prompt_template = "<|im_start|>system\n{inst}<|im_end|>\n<|im_start|>user\n{inp}<|im_end|>\n<|im_start|>assistant\n{out}<|im_end|>"
formatted = []
for ex in data:
    text = prompt_template.format(
        inst=ex.get("instruction", "Tu es l ingenieur planificateur en chef EPC ARKAN."),
        inp=ex.get("input", ""),
        out=ex.get("output", "")
    )
    formatted.append({"text": text})

raw_ds = Dataset.from_list(formatted)

def tokenize_fn(examples):
    inputs = tokenizer(examples["text"], truncation=True, max_length=1024)
    inputs["labels"] = inputs["input_ids"].copy()
    return inputs

print("[*] Tokenisation du dataset en cours...")
train_ds = raw_ds.map(tokenize_fn, batched=True, remove_columns=["text"])

training_args = TrainingArguments(
    output_dir="/kaggle/working/checkpoints",
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    warmup_steps=10,
    max_steps=120,
    learning_rate=2e-4,
    fp16=True,
    logging_steps=10,
    optim="paged_adamw_8bit",
    weight_decay=0.01,
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
)

print("[*] Demarrage du Fine-Tuning SFT Planning IA sur GPU...")
t_start = time.time()
trainer.train()
print(f"[+] Entrainement termine en {time.time() - t_start:.1f}s !")

save_dir = "/kaggle/working/arkan_planning_expert_lora"
os.makedirs(save_dir, exist_ok=True)
print(f"[*] Sauvegarde de l adaptateur LoRA dans {save_dir}...")
trainer.model.save_pretrained(save_dir)
tokenizer.save_pretrained(save_dir)

for f in os.listdir(save_dir):
    src = os.path.join(save_dir, f)
    dst = os.path.join("/kaggle/working", f)
    if os.path.isfile(src):
        shutil.copy2(src, dst)

print(f"[+] Modele LoRA Planning Expert sauvegarde avec succes dans {save_dir} et exporte !")

print("\n[*] TEST DE VALIDATION EN INFERENCE DU MODELE FINETUNE...")
test_prompt = "<|im_start|>system\nTu es l ingenieur planificateur en chef EPC ARKAN.<|im_end|>\n<|im_start|>user\nPlanification EPC complete d un Gazoduc 28 pouces sur 65 km avec epreuves hydrostatiques et mise en gaz ARH.<|im_end|>\n<|im_start|>assistant\n"
inputs = tokenizer(test_prompt, return_tensors="pt").to("cuda:0")
with torch.no_grad():
    outputs = model.generate(**inputs, max_new_tokens=350, temperature=0.2, do_sample=True)
response = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
print("[+] REPONSE DU MODELE APRES FINE-TUNING :\n" + response[:500] + "...")
print("[*] VALIDATION TERMINEE AVEC SUCCES.")
