"""
DeerFlow Lite — Agent Episodic Memory
Sauvegarde et rappel continu des raisonnements réussis pour éviter 
à l'agent de recalculer des questions déjà résolues.
"""
import time
import json
import logging
import hashlib
from typing import Optional, Dict, Any

import chromadb

logger = logging.getLogger(__name__)

try:
    from config import CHROMA_PERSIST_DIR
except ImportError:
    CHROMA_PERSIST_DIR = "./chroma_db"

MEMORY_COLLECTION = "agent_episodic_memory"
SIMILARITY_THRESHOLD = 0.85  # Si > 85% similaire, on rappelle le souvenir


class AgentMemory:
    """Gestionnaire de mémoire continue pour l'Agent Raisonneur."""

    def __init__(self, persist_dir: str = CHROMA_PERSIST_DIR):
        self.persist_dir = persist_dir
        try:
            from config import CHROMA_MODE, CHROMA_HOST, CHROMA_PORT
        except ImportError:
            import os
            CHROMA_MODE = os.environ.get("CHROMA_MODE", "local")
            CHROMA_HOST = os.environ.get("CHROMA_HOST", "chromadb")
            CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8000"))

        self.client = None
        if CHROMA_MODE == "server":
            try:
                self.client = chromadb.HttpClient(host=CHROMA_HOST, port=int(CHROMA_PORT))
                # Vérifier que le client répond réellement
                self.client.heartbeat()
            except Exception as e:
                logger.warning(f"[Memory] Impossible de se connecter au serveur ChromaDB ({e}). Tentative de fallback local...")
                self.client = None

        if self.client is None:
            try:
                self.client = chromadb.PersistentClient(path=self.persist_dir)
            except Exception as e:
                logger.warning(f"[Memory] Impossible d'initialiser le client local persistant ({e}). Utilisation d'un client éphémère en mémoire...")
                self.client = chromadb.EphemeralClient()
        
        # On essaie d'utiliser la fonction d'embedding du projet
        try:
            from indexer import get_embedding_function
            self.embedding_fn = get_embedding_function()
        except ImportError:
            self.embedding_fn = None

        self.collection = self.client.get_or_create_collection(
            name=MEMORY_COLLECTION,
            embedding_function=self.embedding_fn
        )

    def _hash_query(self, query: str) -> str:
        return hashlib.md5(query.encode('utf-8')).hexdigest()

    def save_experience(self, query: str, final_answer: str, steps: list, model_used: str):
        """
        Enregistre un raisonnement réussi dans la mémoire.
        """
        try:
            # Ne pas sauvegarder s'il n'y a pas d'observations réelles (ex: hallucination ou fallback)
            has_observations = any(s.step_type == "observation" for s in steps)
            if not has_observations and len(steps) <= 2:
                return

            qid = self._hash_query(query)
            
            # Formater la trace pour le rappel
            trace_summary = []
            for step in steps:
                if step.step_type == "thought":
                    trace_summary.append(f"Thought: {step.content}")
                elif step.step_type == "action":
                    trace_summary.append(f"Action: {step.content}")
                elif step.step_type == "observation":
                    # On tronque l'observation pour ne garder que l'essentiel
                    obs_trunc = step.content[:300].replace('\n', ' ')
                    trace_summary.append(f"Observation: {obs_trunc}...")
            
            metadata = {
                "answer": final_answer,
                "trace_summary": json.dumps(trace_summary, ensure_ascii=False),
                "iterations": len(steps),
                "model_used": model_used,
                "timestamp": time.time()
            }

            self.collection.add(
                ids=[qid],
                documents=[query],
                metadatas=[metadata]
            )
            logger.info(f"[Memory] Nouvelle expérience sauvegardée : {query[:50]}")
        except Exception as e:
            logger.error(f"[Memory] Erreur sauvegarde expérience: {e}")

    def save_human_correction(self, query: str, correct_answer: str, context: str = ""):
        """Enregistre une correction humaine (Few-Shot) dans ChromaDB."""
        try:
            qid = self._hash_query(f"CORRECTION_{query}")
            
            metadata = {
                "answer": correct_answer,
                "trace_summary": json.dumps([f"Contexte: {context}", "HUMAN_CORRECTION"], ensure_ascii=False),
                "iterations": 1,
                "model_used": "human_expert",
                "is_human": True,
                "timestamp": time.time()
            }

            self.collection.add(
                ids=[qid],
                documents=[query],
                metadatas=[metadata]
            )
            logger.info(f"[Memory] Correction humaine sauvegardée : {query[:50]}")
        except Exception as e:
            logger.error(f"[Memory] Erreur sauvegarde correction: {e}")

    def recall_experience(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Cherche si une question similaire a déjà été résolue.
        Retourne le souvenir si la similarité est > SIMILARITY_THRESHOLD.
        """
        try:
            if self.collection.count() == 0:
                return None

            results = self.collection.query(
                query_texts=[query],
                n_results=1
            )
            
            if not results['documents'][0]:
                return None

            # ChromaDB distance : plus bas = plus proche.
            # Avec L2 (défaut ChromaDB) : < 0.2 = très similaire avec nomic-embed-text 768D
            # Avec cosine : < 0.15 = très similaire
            # L'ancien seuil 0.4 était trop permissif → faux hits mémoire fréquents
            distance = results['distances'][0][0]
            is_match = distance < 0.2  # CORRIGÉ : était 0.4

            if is_match:
                doc = results['documents'][0][0]
                meta = results['metadatas'][0][0]
                
                logger.info(f"[Memory] Rappel réussi (dist: {distance:.3f}) pour '{doc[:50]}'")
                
                return {
                    "past_query": doc,
                    "answer": meta.get("answer"),
                    "trace_summary": json.loads(meta.get("trace_summary", "[]")),
                    "model_used": meta.get("model_used", "unknown"),
                    "is_human": meta.get("is_human", False),
                    "distance": distance
                }
            return None
        except Exception as e:
            logger.error(f"[Memory] Erreur rappel expérience: {e}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques de la mémoire pour le dashboard."""
        try:
            return {"count": self.collection.count()}
        except Exception:
            return {"count": 0}


# --- Singleton ---
_memory_instance = None

def get_agent_memory() -> AgentMemory:
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = AgentMemory()
    return _memory_instance
