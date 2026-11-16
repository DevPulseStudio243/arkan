"""
DeepFlow - Agent Curateur Autonome (LLM-as-a-Judge)
Ce script est un agent intelligent qui scanne Hugging Face, 
analyse les bases de données d'ingénierie, et demande à DeepSeek-R1 
de juger (sur 100) si la base est pertinente pour le domaine de l'Oil & Gas 
avant de l'autoriser à être téléchargée.
"""

import requests
import json
import time

try:
    from huggingface_hub import HfApi
    from datasets import load_dataset
except ImportError:
    print("Veuillez installer: pip install huggingface_hub datasets")
    exit(1)

OUTPUT_FILE = "data/learning/local_distillation_dataset.json"
KEYWORDS = ["engineering", "oil", "gas", "thermodynamics", "physics", "mechanics", "materials"]
MINIMUM_SCORE = 90  # La barre d'admission (très stricte)

# Prompt pour le Juge (DeepSeek-R1)
JUDGE_PROMPT = """Tu es un Ingénieur Principal Senior dans l'industrie pétrolière (Oil & Gas).
On te propose d'acheter une nouvelle base de données d'apprentissage pour tes ingénieurs juniors.
Voici la description de la base de données et 2 exemples de son contenu.

Ta tâche est d'évaluer STRICTEMENT si cette base de données est utile pour l'ingénierie industrielle, le pétrole, le gaz, le cost control, ou les sciences dures.
Rejette formellement (donne un score bas) tout ce qui concerne l'informatique web, la médecine, la pop culture, ou les mathématiques de niveau primaire.

Tu DOIS répondre avec un JSON strict:
{
    "score": <un nombre entre 0 et 100>,
    "justification": "Une phrase d'explication de ton verdict."
}
"""

def evaluate_dataset_with_deepseek(dataset_id, description, sample_text):
    """Demande à DeepSeek-R1 de noter le dataset sur 100."""
    print(f"\n[JUGE] DeepSeek analyse le candidat : {dataset_id}...")
    
    prompt = f"Nom: {dataset_id}\nDescription: {description[:500]}\nExemples de contenu: {sample_text}\n\nDonne ton verdict en JSON."
    
    try:
        response = requests.post("http://localhost:11434/api/generate", json={
            "model": "deepseek-r1:latest",
            "system": JUDGE_PROMPT,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1} # Basse température pour un juge objectif
        })
        
        if response.status_code == 200:
            result = response.json()
            response_text = result.get("response", "")
            
            # Nettoyage de la balise <think>
            if "</think>" in response_text:
                response_text = response_text.split("</think>")[-1]
                
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start >= 0 and json_end > 0:
                evaluation = json.loads(response_text[json_start:json_end])
                return evaluation.get("score", 0), evaluation.get("justification", "")
                
    except Exception as e:
        print(f"[ERROR] Le juge a eu un problème technique : {e}")
        
    return 0, "Erreur d'évaluation"

def scan_and_curate():
    api = HfApi()
    print("🕵️‍♂️ L'Agent Curateur DeepFlow commence sa patrouille sur Hugging Face...\n")
    
    # On cherche les datasets récents contenant un des mots clés
    for keyword in KEYWORDS:
        print(f"🔍 Recherche de datasets avec le mot-clé : '{keyword}'")
        datasets = api.list_datasets(search=keyword, limit=3, sort="lastModified", direction=-1)
        
        for ds in datasets:
            ds_id = ds.id
            print(f"\n--------------------------------------------------")
            print(f"📦 Candidat trouvé : {ds_id}")
            
            # On tente de télécharger un échantillon robuste (100 lignes) pour l'évaluer
            sample_text = ""
            try:
                # Mode streaming : on ne télécharge pas tout le fichier !
                iterable_dataset = load_dataset(ds_id, split="train", streaming=True, trust_remote_code=True)
                sample_rows = list(iterable_dataset.take(100))
                # On ne convertit pas les 100 en texte complet pour éviter de faire exploser la fenêtre de contexte de DeepSeek.
                # On prend un échantillon représentatif condensé des 100 lignes.
                sample_text = json.dumps(sample_rows)[:4000] 
            except Exception as e:
                print(f"[SKIP] Impossible de lire un echantillon de {ds_id}. Raison : {str(e)[:50]}")
                continue
                
            # Le Juge DeepSeek intervient
            score, justification = evaluate_dataset_with_deepseek(ds_id, ds.description or "Pas de description", sample_text)
            
            print(f"⚖️ Verdict du Juge : {score}/100")
            print(f"📝 Justification : {justification}")
            
            if score >= MINIMUM_SCORE:
                print(f"✅ APPROUVÉ ! Ce dataset est un ajout précieux pour l'Oil & Gas.")
                print(f"➡️ (Dans une future itération, le script téléchargera et formatera {ds_id} ici)")
                # Ici nous ajouterions la logique de téléchargement complet et fusion (comme download_hf_dataset.py)
            else:
                print(f"❌ REJETÉ ! Ne correspond pas aux standards de l'ingénierie DeepFlow.")
            
            time.sleep(2) # Pause courtoise pour l'API Hugging Face

if __name__ == "__main__":
    scan_and_curate()
