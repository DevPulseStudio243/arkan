import logging
import os
import hashlib
from typing import List, Any, Dict

logger = logging.getLogger(__name__)

# Fallback si RERANK_MODEL n'est pas dans config
try:
    from config import RERANK_MODEL
except ImportError:
    RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"  # Fast and lightweight fallback

class NeuralReranker:
    def __init__(self, model_name: str = RERANK_MODEL):
        self.model_name = model_name
        self.model = None
        self._initialized = False
        self._cache: Dict[str, float] = {}
        self._max_cache_size = 5000

    def _ensure_initialized(self):
        if not self._initialized:
            logger.info(f"Initialisation du Reranker Neuronal ({self.model_name})...")
            try:
                from sentence_transformers import CrossEncoder
                import torch
                
                device = "cuda" if torch.cuda.is_available() else "cpu"
                logger.info(f"Loading CrossEncoder on {device}")
                self.model = CrossEncoder(self.model_name, device=device)
                self._initialized = True
                logger.info("Reranker Neuronal prêt.")
            except Exception as e:
                logger.error(f"Erreur lors du chargement du Reranker: {e}")
                self._initialized = True # Mark as initialized to avoid retrying on every request

    def warmup(self):
        """Pre-initialise le CrossEncoder et effectue une passe à vide pour éliminer le cold-start."""
        self._ensure_initialized()
        if self.model:
            try:
                logger.info("Warmup du Reranker Neuronal en cours...")
                self.model.predict([("EPC Engineering Warmup", "Norme ASME B31.3 et tuyauterie industrielle")])
                logger.info("Warmup du Reranker Neuronal terminé avec succès.")
            except Exception as e:
                logger.warning(f"Warmup Reranker non critique échoué: {e}")

    def _get_cache_key(self, query: str, content: str) -> str:
        h = hashlib.md5(f"{query}:::{content[:500]}".encode("utf-8")).hexdigest()
        return h

    def rerank(self, query: str, results: List[Any], top_k: int = 5) -> List[Any]:
        """
        Rerank a list of RetrievalResult objects using a Cross-Encoder with LRU caching.
        """
        self._ensure_initialized()
        
        if not self.model or not results:
            # Fallback : retourne les resultats originaux tronques a top_k
            return results[:top_k]

        try:
            # Prepare pairs (query, document) while checking cache
            pairs_to_predict = []
            pair_indices = []
            scores = [0.0] * len(results)

            for i, r in enumerate(results):
                content = getattr(r, "content", None) or (r.get("content", "") if isinstance(r, dict) else "")
                key = self._get_cache_key(query, content)
                if key in self._cache:
                    scores[i] = self._cache[key]
                else:
                    pairs_to_predict.append((query, content[:2000]))
                    pair_indices.append(i)

            # Predict scores for uncached pairs
            if pairs_to_predict:
                logger.info(f"Reranking {len(pairs_to_predict)} uncached pairs ({len(results) - len(pairs_to_predict)} from cache)...")
                predicted_scores = self.model.predict(pairs_to_predict)
                for idx, score in zip(pair_indices, predicted_scores):
                    s_float = float(score)
                    scores[idx] = s_float
                    # Cache management
                    content = getattr(results[idx], "content", None) or (results[idx].get("content", "") if isinstance(results[idx], dict) else "")
                    k = self._get_cache_key(query, content)
                    if len(self._cache) >= self._max_cache_size:
                        # Simple FIFO prune
                        self._cache.pop(next(iter(self._cache)))
                    self._cache[k] = s_float
            else:
                logger.info(f"Reranking : 100% des {len(results)} paires résolues via le cache mémoire.")

            # Combine and sort results
            reranked_results = []
            for i, score in enumerate(scores):
                reranked_results.append((score, results[i]))
                
            reranked_results.sort(key=lambda x: x[0], reverse=True)
            
            # Extract the original objects and update their score
            final_results = []
            for score, obj in reranked_results[:top_k]:
                if hasattr(obj, "score"):
                    obj.score = score
                elif isinstance(obj, dict):
                    obj["score"] = score
                final_results.append(obj)
                
            top_score = reranked_results[0][0] if reranked_results else 0.0
            logger.info(f"Reranking terminé. Top score: {top_score:.3f}")
            return final_results
            
        except Exception as e:
            logger.error(f"Reranking échoué, fallback sur l'ordre initial: {e}")
            return results[:top_k]

# Singleton instance
_reranker_instance = None

def get_reranker() -> NeuralReranker:
    global _reranker_instance
    if _reranker_instance is None:
        _reranker_instance = NeuralReranker()
    return _reranker_instance
