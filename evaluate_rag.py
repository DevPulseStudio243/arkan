import json
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

# Questions de référence (Golden Dataset)
GROUND_TRUTH = [
    {
        "question": "Quelle est la pression de design de la pompe P-101A ?",
        "expected_answer": "18 bar",
        "context": "Item: P-101A. Operating Pressure: 15 bar. Design Pressure: 18 bar."
    },
    {
        "question": "Où est connecté la vanne XV-101 ?",
        "expected_answer": "Ligne 10\"-HC-1001",
        "context": "Vanne XV-101 est installée sur la ligne 10\"-HC-1001 en aval du séparateur V-200."
    }
]

class SimpleRAGASEvaluator:
    """
    Un framework léger simulant RAGAS pour évaluer la fidélité (Faithfulness) 
    et la pertinence (Answer Relevance) du système DeerFlow.
    """
    
    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator
        
    def evaluate(self, dataset: List[Dict] = GROUND_TRUTH) -> Dict:
        """Évalue le système sur le dataset de référence."""
        if not self.orchestrator:
            print("Orchestrator non fourni. Évaluation simulée.")
            return {"faithfulness_score": 0.0, "answer_relevance_score": 0.0, "details": []}
            
        results = []
        total_faithfulness = 0.0
        total_relevance = 0.0
        
        print(f"Début de l'évaluation sur {len(dataset)} questions...")
        
        for item in dataset:
            q = item["question"]
            expected = item["expected_answer"]
            
            try:
                # Appeler le système réel
                response_obj = self.orchestrator.run(q)
                actual_answer = response_obj.answer
                
                # Mesure naïve de pertinence (vérifie si la réponse attendue est présente)
                # Dans un vrai RAGAS, on utiliserait un LLM as-a-judge
                is_relevant = expected.lower() in actual_answer.lower()
                relevance_score = 1.0 if is_relevant else 0.0
                
                # Mesure naïve de fidélité (vérifie si l'agent a cité une source ou utilisé des observations)
                has_source = "[Source:" in actual_answer or len(response_obj.sources) > 0
                faithfulness_score = 1.0 if has_source else 0.5
                
                total_faithfulness += faithfulness_score
                total_relevance += relevance_score
                
                results.append({
                    "question": q,
                    "expected": expected,
                    "actual": actual_answer[:100] + "...",
                    "relevance": relevance_score,
                    "faithfulness": faithfulness_score
                })
                print(f"✓ Évalué: {q[:30]}... Score: {relevance_score + faithfulness_score}/2.0")
                
            except Exception as e:
                logger.error(f"Erreur évaluation pour la question '{q}': {e}")
                
        metrics = {
            "faithfulness_score": total_faithfulness / len(dataset) if dataset else 0,
            "answer_relevance_score": total_relevance / len(dataset) if dataset else 0,
            "details": results
        }
        
        self.print_report(metrics)
        return metrics
        
    def print_report(self, metrics: Dict):
        print("\n" + "="*50)
        print(" RAPPORT D'ÉVALUATION (RAGAS Local)")
        print("="*50)
        print(f"Score de Fidélité (Faithfulness) : {metrics['faithfulness_score']*100:.1f}%")
        print(f"Score de Pertinence (Relevance)  : {metrics['answer_relevance_score']*100:.1f}%")
        print("="*50)

if __name__ == "__main__":
    evaluator = SimpleRAGASEvaluator()
    evaluator.evaluate()
