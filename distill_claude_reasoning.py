"""
DeerFlow Lite - Distillation Continue Locale (DeepSeek-R1 vers Qwen 14B)
Ce script utilise votre modèle DeepSeek-R1 local via Ollama pour générer
des problèmes complexes d'ingénierie fictifs et leurs résolutions.
100% Gratuit, 100% Privé, 100% Local.
"""

import os
import json
import time
import random
import requests
from typing import Optional

OUTPUT_FILE = "data/learning/local_distillation_dataset.json"
PAUSE_MINUTES = 2 # Pause plus courte car c'est gratuit

DOMAINS = [
    "Cost Control (EVM, CPI, SPI, Analyse de variance)",
    "Planning (Chemin critique, Primavera P6, Retards)",
    "Process Engineering (Pertes de charge, Pompes centrifuges, API 610)",
    "Piping & Layout (ASME B31.3, Supports, Stress Analysis)",
    "Instrumentation (Vannes de contrôle, Transmetteurs, SIL)",
    "Contrats EPC (Change Orders, Réclamations, Clauses de pénalité)"
]

SYSTEM_PROMPT = """Tu es un ingénieur Principal expert en Oil & Gas.
Ta tâche est de générer UNE paire (Question / Raisonnement / Réponse) extrêmement pointue 
et réaliste dans le domaine demandé. Utilise des données totalement fictives.

Tu DOIS répondre UNIQUEMENT avec un objet JSON valide, sans markdown autour.
Format exact attendu :
{
  "query": "La question posée par un ingénieur junior",
  "thought": "1. J'analyse... 2. Je calcule...",
  "answer": "La réponse finale d'expert."
}
"""

def generate_continuous_knowledge(max_iterations: Optional[int] = None, topic: Optional[str] = None):
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    print("[DEEPFLOW] Demarrage du Generateur de Connaissances Continu (Professeur: DeepSeek-R1)")
    if topic:
        print(f"[FOCUS] Sujet specifique: {topic}")
    print(f"[FILE] Fichier: {OUTPUT_FILE}")
    print("[INFO] Cout: 0 euro (100% Local)\n")
    
    iteration = 1
    while True:
        if max_iterations and iteration > max_iterations:
            print(f"[FINISH] Atteint le nombre d'itérations demandé ({max_iterations}).")
            break
            
        current_domain = topic if topic else random.choice(DOMAINS)
        print(f"[{iteration}] Génération d'un scénario expert en: {current_domain}...")
        
        try:
            # Appel à Ollama Local (DeepSeek-R1)
            response = requests.post("http://localhost:11434/api/generate", json={
                "model": "deepseek-r1:latest",
                "system": SYSTEM_PROMPT,
                "prompt": f"Génère un scénario complexe en {current_domain}. Rends ça très technique et renvoie uniquement le JSON.",
                "stream": False,
                "options": {
                    "temperature": 0.7
                }
            })
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "")
                
                # DeepSeek-R1 génère souvent ses pensées dans des balises <think>
                # On nettoie le texte pour extraire juste le JSON
                if "</think>" in response_text:
                    response_text = response_text.split("</think>")[-1]
                
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                
                if json_start >= 0 and json_end > 0:
                    try:
                        qa = json.loads(response_text[json_start:json_end])
                        
                        new_data = {
                            "query": qa["query"],
                            "answer": qa["answer"],
                            "thought": qa.get("thought", ""),
                            "score": 1.0,
                            "source": f"deepseek_distillation_{current_domain.split()[0]}"
                        }
                        
                        # Charger l'existant et ajouter
                        dataset = []
                        if os.path.exists(OUTPUT_FILE):
                            try:
                                with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                                    dataset = json.load(f)
                            except json.JSONDecodeError:
                                pass
                        
                        dataset.append(new_data)
                        
                        # Sauvegarder
                        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                            json.dump(dataset, f, indent=4, ensure_ascii=False)
                            
                        print(f"[SUCCESS] La base contient {len(dataset)} exemples de reflexion DeepSeek.")
                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"[WARNING] Erreur parsing JSON: {e}")
                else:
                    print("[WARNING] JSON non trouve dans la reponse.")
            else:
                print(f"[ERROR] Erreur Ollama: {response.status_code}")
                
        except requests.exceptions.ConnectionError:
            print("[FATAL] Impossible de se connecter a Ollama. Est-il lance ?")
            break
        except Exception as e:
            print(f"[ERROR] Erreur inattendue: {e}")
            
        if max_iterations and iteration >= max_iterations:
             break

        print(f"[PAUSE] Pause de {PAUSE_MINUTES} minutes pour laisser refroidir le PC...\n")
        time.sleep(PAUSE_MINUTES * 60)
        iteration += 1

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=None, help="Nombre d'iterations a effectuer")
    parser.add_argument("--topic", type=str, default=None, help="Sujet specifique pour la distillation")
    args = parser.parse_args()
    
    generate_continuous_knowledge(args.count, args.topic)
