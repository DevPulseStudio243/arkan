"""
DeerFlow Lite - Continuous Training v2.0
Coordinates vocabulary, knowledge graph, feedback learning, and model updates.
"""
import json
import time
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

TRAINING_STATE_PATH = Path("training_state.json")


class ContinuousTrainer:
    """
    Orchestrates continuous learning across all system components.

    Two modes:
    - Incremental: lightweight, after each interaction (vocabulary + source weights)
    - Full cycle: heavy, periodic (rebuild indexes, retrain models, evaluate)
    """

    def __init__(self):
        self._state = self._load_state()

    def _load_state(self) -> dict:
        if TRAINING_STATE_PATH.exists():
            try:
                with open(TRAINING_STATE_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "full_cycles": 0,
            "incremental_updates": 0,
            "last_full_cycle": None,
            "last_incremental": None,
            "documents_processed": 0,
            "vocabulary_size": 0,
            "graph_entities": 0,
        }

    def _save_state(self):
        tmp = TRAINING_STATE_PATH.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)
        tmp.replace(TRAINING_STATE_PATH)

    def incremental_update(self, query: str = None, answer: str = None, sources: list[str] = None,
                           rating: str = "auto", confidence: float = 0.5,
                           new_feedback: list = None, new_documents: list = None):
        """
        Flexible update supporting multiple signatures:
        - query, answer, sources (direct feedback)
        - new_feedback (batch feedback from API)
        - new_documents (newly indexed documents)
        - no args (consolidates training state)
        """
        try:
            from learning import get_learning_engine
            engine = get_learning_engine()

            processed_count = 0

            # 1. Handle new_feedback list
            if new_feedback:
                for fb in new_feedback:
                    q = fb.get("question") or fb.get("query")
                    a = fb.get("answer")
                    s = fb.get("sources", [])
                    r = fb.get("rating", "auto")
                    c = fb.get("confidence", fb.get("score", 0.5))
                    if q and a:
                        self._process_single_feedback(engine, q, a, s, r, c)
                        processed_count += 1

            # 2. Handle direct parameters
            elif query and answer:
                self._process_single_feedback(engine, query, answer, sources or [], rating, confidence)
                processed_count += 1

            # 3. Handle new_documents list
            elif new_documents:
                for doc in new_documents:
                    logger.info(f"Incremental document training received for: {doc.get('source')}")
                    self._state["documents_processed"] += 1
                self._save_state()

            # 4. Consolidate/No-op
            else:
                logger.info("Incremental update called with no new items; consolidating.")
                engine.force_consolidation()

            if processed_count > 0:
                self._state["incremental_updates"] += processed_count
                self._state["last_incremental"] = datetime.now(timezone.utc).isoformat()
                self._save_state()
                logger.info(f"Incremental update complete. Processed {processed_count} feedback entries.")

            return {
                "status": "success",
                "processed_feedback": processed_count,
                "incremental_updates_total": self._state["incremental_updates"]
            }

        except Exception as e:
            logger.error(f"Incremental update failed: {e}")
            return {"status": "error", "message": str(e)}

    def _process_single_feedback(self, engine, query: str, answer: str, sources: list[str],
                                 rating: str, confidence: float):
        # Convert "auto" rating to concrete rating based on confidence
        if rating == "auto":
            if confidence >= 0.7:
                rating = "good"
            elif confidence <= 0.3:
                rating = "bad"
            else:
                rating = "partial"

        from learning import FeedbackEntry
        entry = FeedbackEntry(
            query=query,
            answer=answer,
            sources=sources,
            rating=rating,
            confidence=confidence,
        )
        engine.process_feedback(entry)

    def run_full_cycle(self, rebuild_bm25: bool = True, rebuild_vocab: bool = True,
                       prune_graph: bool = True):
        """
        Full training cycle: rebuild all indexes and learning components.
        Should be run periodically (e.g., daily or after batch document ingestion).
        """
        logger.info("=== Starting full training cycle ===")
        start = time.time()
        errors = []

        # 1. Rebuild vocabulary
        if rebuild_vocab:
            try:
                self._rebuild_vocabulary()
            except Exception as e:
                errors.append(f"Vocabulary rebuild: {e}")
                logger.error(f"Vocabulary rebuild failed: {e}")

        # 2. Prune knowledge graph
        if prune_graph:
            try:
                from learning import get_learning_engine
                engine = get_learning_engine()
                engine.prune_knowledge_graph()
            except Exception as e:
                errors.append(f"Graph pruning: {e}")
                logger.error(f"Graph pruning failed: {e}")

        # 3. Rebuild BM25 index
        if rebuild_bm25:
            try:
                from retriever import get_retriever
                retriever = get_retriever()
                retriever.invalidate_cache()
                logger.info("BM25 index will be rebuilt on next query")
            except Exception as e:
                errors.append(f"BM25 rebuild: {e}")
                logger.error(f"BM25 rebuild failed: {e}")

        # 4. Force learning consolidation
        try:
            from learning import get_learning_engine
            engine = get_learning_engine()
            engine.force_consolidation()
        except Exception as e:
            errors.append(f"Consolidation: {e}")
            logger.error(f"Consolidation failed: {e}")

        # Update state
        self._state["full_cycles"] += 1
        self._state["last_full_cycle"] = datetime.now(timezone.utc).isoformat()
        self._save_state()

        elapsed = time.time() - start
        logger.info(f"=== Full training cycle complete in {elapsed:.1f}s "
                    f"({len(errors)} errors) ===")

        return {
            "success": len(errors) == 0,
            "errors": errors,
            "duration": elapsed,
            "cycle_number": self._state["full_cycles"],
        }

    def _rebuild_vocabulary(self):
        """Rebuild vocabulary from all indexed documents."""
        # Compatibilité : config.py utilise CHROMA_PERSIST_DIR (pas CHROMA_PATH)
        try:
            from config import CHROMA_PERSIST_DIR as CHROMA_PATH, CHROMA_COLLECTION
        except ImportError:
            try:
                from config import CHROMA_PATH, CHROMA_COLLECTION
            except ImportError:
                CHROMA_PATH = "./chroma_db"
                CHROMA_COLLECTION = "oil_gas_docs"

        try:
            import chromadb
            client = chromadb.PersistentClient(path=CHROMA_PATH)
            collection = client.get_collection(CHROMA_COLLECTION)
            all_docs = collection.get(include=["documents"])
            documents = all_docs["documents"]
        except Exception as e:
            logger.warning(f"Cannot access ChromaDB for vocab rebuild: {e}")
            return

        if not documents:
            return

        from vocabulary import build_vocabulary
        result = build_vocabulary(documents)

        self._state["documents_processed"] = len(documents)
        self._state["vocabulary_size"] = result.get("num_terms", 0)

        logger.info(f"Vocabulary rebuilt: {result.get('num_terms', 0)} terms "
                    f"from {len(documents)} documents")

    def get_status(self) -> dict:
        """Get training status."""
        status = dict(self._state)

        try:
            from learning import get_learning_engine
            engine = get_learning_engine()
            status["learning_stats"] = engine.get_learning_stats()
            status["weak_patterns"] = engine.get_weak_patterns()
            status["active_learning_pending"] = len(engine.get_active_learning_items())
        except Exception:
            pass

        return status


# Module-level singleton
_trainer = None
_trainer_lock = threading.Lock()

def get_trainer() -> ContinuousTrainer:
    global _trainer
    if _trainer is None:
        with _trainer_lock:
            if _trainer is None:
                _trainer = ContinuousTrainer()
    return _trainer
