"""
DeepFlow - Injecteur de Raisonnement Logique (Hugging Face)
Ce script télécharge des problèmes de logique complexe depuis Hugging Face 
pour "booster" le cerveau mathématique de Qwen 14B instantanément, 
sans avoir à les calculer localement.
"""

import os
import json
import random

try:
    from datasets import load_dataset
except ImportError:
    print("Veuillez installer la librairie datasets : pip install datasets")
    exit(1)

OUTPUT_FILE = "data/learning/local_distillation_dataset.json"
NUM_EXAMPLES = 500  # Nombre d'exemples de logique pure à injecter

def download_and_merge_logic_dataset():
    print("[NETWORK] Connexion a Hugging Face...")
    
    # GSM8K est une base de données de très haute qualité créée par OpenAI
    # Elle contient des problèmes mathématiques avec une réflexion étape par étape.
    try:
        print("[DOWNLOAD] Telechargement de la base de raisonnement (GSM8K)...")
        dataset = load_dataset("gsm8k", "main", split="train")
    except Exception as e:
        print(f"[ERROR] Erreur lors du telechargement : {e}")
        return

    # Sélectionner des exemples aléatoires
    indices = random.sample(range(len(dataset)), min(NUM_EXAMPLES, len(dataset)))
    
    formatted_data = []
    
    for idx in indices:
        item = dataset[idx]
        
        # Format GSM8K:
        # question: La question mathématique
        # answer: La réflexion étape par étape, suivie de "####" puis la réponse finale
        
        question = item['question']
        full_answer = item['answer']
        
        if "####" in full_answer:
            thought, final_answer = full_answer.split("####")
            thought = thought.strip()
            final_answer = final_answer.strip()
            
            # Reformatage pour DeepFlow
            formatted_data.append({
                "query": f"Résous ce problème complexe étape par étape : {question}",
                "thought": thought,
                "answer": f"La réponse finale est {final_answer}.",
                "score": 1.0,
                "source": "hf_gsm8k_logic_reasoning"
            })
            
    print(f"[SUCCESS] {len(formatted_data)} exemples de reflexion logique parfaitement formates.")
    
    # Créer le dossier si nécessaire
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    # Charger l'existant
    existing_data = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except json.JSONDecodeError:
            pass
            
    # Fusionner les deux mondes (Logique HF + Oil&Gas DeepSeek)
    existing_data.extend(formatted_data)
    
    # Sauvegarder
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=4, ensure_ascii=False)
        
    print(f"[DONE] Succes ! Le fichier de distillation contient desormais {len(existing_data)} scenarios d'entrainement.")
    print("Vous pouvez constater la mise a jour instantanee du compteur dans le Dashboard de DeepFlow !")

if __name__ == "__main__":
    download_and_merge_logic_dataset()
