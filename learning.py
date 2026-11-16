import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict, Counter
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Paths - Compatible with test_system.py expectations
LEARNING_DIR = Path("learning_data")
LEARNING_DIR.mkdir(parents=True, exist_ok=True)

LEARNING_STATE_PATH = LEARNING_DIR / "learning_state.json"
SOURCE_WEIGHTS_PATH = Path("source_weights.json")
VOCABULARY_LEARNED_PATH = LEARNING_DIR / "learned_vocabulary.json"
KNOWLEDGE_GRAPH_PATH = Path("knowledge_graph.json")
QUERY_PATTERNS_PATH = LEARNING_DIR / "query_patterns.json"
ACTIVE_LEARNING_QUEUE_PATH = LEARNING_DIR / "active_learning_queue.json"
WEAK_PATTERNS_PATH = LEARNING_DIR / "weak_patterns.json"

_lock = threading.Lock()


@dataclass
class FeedbackEntry:
    """Un retour utilisateur sur une réponse."""
    query: str
    answer: str
    sources: list = field(default_factory=list)
    rating: str = "partial"     # good | bad | partial
    confidence: float = 0.5
    discipline: str = ""
    correction: str = ""


class LearningEngine:
    """
    Moteur d'apprentissage continu.
    Analyse les feedbacks, met à jour les poids sources, identifie les patterns faibles.
    """

    def __init__(self):
        self._source_good = Counter()
        self._source_bad = Counter()
        self._query_ratings = []      # (query, rating, confidence, discipline)
        self._feedback_count = 0
        self._last_weight_update = 0.0
        self._load_state()

    def _load_state(self):
        try:
            if LEARNING_STATE_PATH.exists():
                with open(LEARNING_STATE_PATH, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                self._source_good = Counter(state.get("source_good", {}))
                self._source_bad = Counter(state.get("source_bad", {}))
                self._feedback_count = state.get("feedback_count", 0)
                self._query_ratings = state.get("query_ratings", [])
        except Exception as e:
            logger.debug("Learning state load failed: %s", e)

    def _save_state(self):
        try:
            state = {
                "source_good": dict(self._source_good),
                "source_bad": dict(self._source_bad),
                "feedback_count": self._feedback_count,
                "query_ratings": self._query_ratings,
                "updated_at": time.time(),
            }
            tmp = LEARNING_STATE_PATH.with_suffix('.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            tmp.replace(LEARNING_STATE_PATH)
        except Exception as e:
            logger.debug("Learning state save failed: %s", e)

    def process_feedback(self, entry: FeedbackEntry):
        """Traite un retour utilisateur et met à jour les poids."""
        with _lock:
            self._feedback_count += 1
            self._query_ratings.append((entry.query, entry.rating, entry.confidence, entry.discipline))

            for source in entry.sources:
                if entry.rating == "good":
                    self._source_good[source] += 1
                elif entry.rating == "bad":
                    self._source_bad[source] += 1

            # Mettre a jour les poids sources toutes les 50 interactions
            # (evite les acces disk excessifs lors de l'injection de 300 exemples synthetiques)
            if self._feedback_count % 50 == 0:
                self._update_source_weights()

            # Identify weak patterns periodically
            if self._feedback_count % 5 == 0:
                self._update_weak_patterns()

            # Active learning queue for bad/low confidence
            if entry.rating == "bad" or entry.confidence < 0.3:
                self._add_to_active_learning(entry)

            self._save_state()

    def _update_source_weights(self):
        """Recalcule et sauvegarde les poids sources."""
        all_sources = set(self._source_good.keys()) | set(self._source_bad.keys())
        weights = {}
        for src in all_sources:
            g = self._source_good.get(src, 0)
            b = self._source_bad.get(src, 0)
            w = (g + 1) / (g + b + 2)  # Laplace smoothing
            weights[src] = {
                "weight": round(w, 4),
                "good_count": g,
                "bad_count": b,
                "total": g + b,
            }
        try:
            with open(SOURCE_WEIGHTS_PATH, 'w', encoding='utf-8') as f:
                json.dump(weights, f, ensure_ascii=False, indent=2)
            self._last_weight_update = time.time()
            logger.info("Source weights updated: %d sources", len(weights))
        except Exception as e:
            logger.error("Source weights save failed: %s", e)

    def get_source_weights(self) -> Dict[str, float]:
        """Returns simplified source weights map {source: weight}."""
        try:
            if not SOURCE_WEIGHTS_PATH.exists():
                return {}
            with open(SOURCE_WEIGHTS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return {s: float(v.get("weight", 0.5) if isinstance(v, dict) else v) for s, v in data.items()}
        except Exception:
            return {}

    def apply_learned_weights_to_results(self, results: list) -> list:
        """Applique les poids appris aux résultats de retrieval."""
        weights = self.get_source_weights()
        if not weights:
            return results

        for r in results:
            src = r.source if hasattr(r, 'source') else r.get("source", "")
            src_name = Path(src).name if src else ""
            w = weights.get(src, weights.get(src_name, 0.5))
            boost = (w - 0.5) * 0.3  # Max ±0.15
            if hasattr(r, 'score'):
                r.score = min(1.0, max(0.0, r.score + boost))

        return sorted(results, key=lambda x: x.score if hasattr(x, 'score') else 0, reverse=True)

    def get_learning_stats(self) -> dict:
        """Statistiques d'apprentissage."""
        total_feedback = self._feedback_count
        good = sum(1 for _, r, _, _ in self._query_ratings if r == "good")
        bad = sum(1 for _, r, _, _ in self._query_ratings if r == "bad")
        partial = sum(1 for _, r, _, _ in self._query_ratings if r == "partial")
        
        # Test compatibility
        active_pending = 0
        if ACTIVE_LEARNING_QUEUE_PATH.exists():
            try:
                with open(ACTIVE_LEARNING_QUEUE_PATH, 'r', encoding='utf-8') as f:
                    active_pending = len(json.load(f))
            except Exception: pass

        return {
            "total_feedback": total_feedback,
            "total_interactions": total_feedback, # Compatibility
            "good": good,
            "bad": bad,
            "partial": partial,
            "satisfaction_rate": round(good / (good + bad) if (good + bad) > 0 else 0, 3),
            "sources_tracked": len(self._source_good) + len(self._source_bad),
            "source_weights_count": len(self._source_good) + len(self._source_bad), # Compatibility
            "last_weight_update": self._last_weight_update,
            "active_learning_pending": active_pending, # Compatibility
        }

    def _add_to_active_learning(self, entry: FeedbackEntry):
        """Add problematic query to active learning queue."""
        queue = []
        if ACTIVE_LEARNING_QUEUE_PATH.exists():
            try:
                with open(ACTIVE_LEARNING_QUEUE_PATH, 'r', encoding='utf-8') as f:
                    queue = json.load(f)
            except Exception: pass
        
        # Avoid duplicates
        if not any(item.get("query") == entry.query for item in queue):
            queue.append({
                "query": entry.query,
                "answer": entry.answer,
                "rating": entry.rating,
                "confidence": entry.confidence,
                "timestamp": time.time()
            })
            
            try:
                with open(ACTIVE_LEARNING_QUEUE_PATH, 'w', encoding='utf-8') as f:
                    json.dump(queue[-100:], f, indent=2) # Keep last 100
            except Exception: pass

    def get_active_learning_items(self, limit: int = 20) -> list:
        """Requêtes à faible confiance nécessitant révision experte."""
        if ACTIVE_LEARNING_QUEUE_PATH.exists():
            try:
                with open(ACTIVE_LEARNING_QUEUE_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)[-limit:]
            except Exception: pass
        return []

    def _update_weak_patterns(self):
        """Analyze bad queries for common terms."""
        fail_queries = [q for q, r, _, _ in self._query_ratings if r == "bad"]
        word_counts = Counter()
        for q in fail_queries:
            words = [w.lower() for w in q.split() if len(w) > 3]
            word_counts.update(words)
        
        patterns = [{"term": w, "fail_count": c} for w, c in word_counts.most_common(20)]
        try:
            with open(WEAK_PATTERNS_PATH, 'w', encoding='utf-8') as f:
                json.dump(patterns, f, indent=2)
        except Exception: pass

    def get_weak_patterns(self) -> list:
        """Patterns de requêtes qui échouent régulièrement."""
        if WEAK_PATTERNS_PATH.exists():
            try:
                with open(WEAK_PATTERNS_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception: pass
        return []

    def resolve_active_item(self, query: str, correct_answer: str, sources: list):
        """Intègre la correction experte dans le système d'apprentissage."""
        entry = FeedbackEntry(
            query=query,
            answer=correct_answer,
            sources=sources,
            rating="good",
            confidence=1.0,
        )
        self.process_feedback(entry)
        
        # Remove from queue
        if ACTIVE_LEARNING_QUEUE_PATH.exists():
            try:
                with open(ACTIVE_LEARNING_QUEUE_PATH, 'r', encoding='utf-8') as f:
                    queue = json.load(f)
                new_queue = [item for item in queue if item.get("query") != query]
                with open(ACTIVE_LEARNING_QUEUE_PATH, 'w', encoding='utf-8') as f:
                    json.dump(new_queue, f, indent=2)
            except Exception: pass
            
        logger.info("Active learning item resolved: %r", query[:60])

    def update_knowledge_graph(self, entities: List[Dict[str, Any]]):
        """Adds validated entities to the knowledge graph."""
        try:
            from knowledge_graph import load_graph, save_graph
            graph = load_graph()
            
            # Compatible with both dict and list entities
            graph_entities = graph.get("entities", {})
            added = 0
            
            for entity in entities:
                name = entity.get("name")
                if not name or len(name) < 2: continue
                # Simple validation filter
                if name.lower() in ["float64", "copyright", "python"]: continue
                
                key = name.upper()
                if isinstance(graph_entities, dict):
                    if key not in graph_entities:
                        graph_entities[key] = {
                            "name": name,
                            "type": entity.get("type", "unknown"),
                            "sources": ["feedback_learned"],
                            "properties": entity.get("properties", {})
                        }
                        added += 1
                else:
                    # List format
                    if not any(e.get("name") == name for e in graph_entities):
                        graph_entities.append({
                            "name": name,
                            "type": entity.get("type", "unknown"),
                            "sources": ["feedback_learned"],
                            "properties": entity.get("properties", {})
                        })
                        added += 1
            
            if added > 0:
                graph["entities"] = graph_entities
                save_graph(graph)
                logger.info("Knowledge graph updated with %d entities", added)
        except Exception as e:
            logger.error("KG update failed: %s", e)

    def prune_knowledge_graph(self):
        """Délègue le pruning au module knowledge_graph."""
        try:
            from knowledge_graph import load_graph, save_graph
            graph = load_graph()
            save_graph(graph)  # save_graph appelle _prune_graph_if_needed() automatiquement
            logger.info("Knowledge graph pruned")
        except Exception as e:
            logger.error("KG prune failed: %s", e)

    def force_consolidation(self):
        """Force la mise à jour de tous les composants d'apprentissage."""
        with _lock:
            self._update_source_weights()
            self._update_weak_patterns()
            self._save_state()
        logger.info("Learning consolidation complete")


# ── Scheduler de re-fine-tuning automatique ─────────────────

class AutoRetrainScheduler:
    """Declenche automatiquement les pipelines d'apprentissage autonome.

    Pipeline complet :
    1. [Demarrage] Generation synthetique Q&A (trainer_synthetic.py)
    2. [Toutes les 6h] Re-entrainement classifieur si >10 feedbacks good
    3. [Toutes les 24h] Generation synthetique supplementaire
    4. [Toutes les 7 jours] Fine-tuning embeddings bge-m3
    """

    def __init__(self, check_interval_hours: int = 6, min_good_feedback: int = 10):
        self.check_interval = check_interval_hours * 3600
        self.min_good_feedback = min_good_feedback
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_retrain = 0.0
        self._last_synthetic = 0.0
        self._last_embed_finetune = 0.0
        Path("training_logs").mkdir(exist_ok=True)
        Path("training_data").mkdir(exist_ok=True)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="auto-retrain-scheduler"
        )
        self._thread.start()
        logger.info("AutoRetrainScheduler started (check every %dh, min_good=%d)",
                    self.check_interval // 3600, self.min_good_feedback)
        # Priorite 2 : lancer la generation synthetique initiale au demarrage
        # Desactive pour eviter de freezer le PC au demarrage (sera lance via le scheduler)
        # threading.Thread(target=self._generate_synthetic_data,
        #                  daemon=True, name="synthetic-init").start()

    def stop(self):
        self._stop_event.set()

    def _run(self):
        while not self._stop_event.wait(self.check_interval):
            try:
                self._check_and_retrain()
                self._check_synthetic_generation()
                self._check_embedding_finetune()
            except Exception as e:
                logger.error("AutoRetrain check error: %s", e)

    # ── Priorite 2 : Generation synthetique ─────────────────
    def _check_synthetic_generation(self):
        """Genere des donnees synthetiques toutes les 24h."""
        if time.time() - self._last_synthetic < 86400:
            return
        threading.Thread(target=self._generate_synthetic_data,
                         daemon=True, name="synthetic-gen").start()

    def _generate_synthetic_data(self):
        """Generation autonome de donnees d'entrainement synthetiques Oil&Gas."""
        try:
            self._last_synthetic = time.time()
            logger.info("[Synthetic] Demarrage generation de donnees synthetiques Oil&Gas...")
            import sys as _sys
            import json as _json
            import subprocess as _sub
            from pathlib import Path as _Path

            _data_dir = _Path("training_data")
            _data_dir.mkdir(exist_ok=True)

            # Utiliser subprocess pour isoler rich.Progress du thread daemon
            # (evite le conflit _SilentConsole / get_time de rich)
            _script = str(_Path(__file__).parent / "trainer_synthetic.py")
            _log = _Path("training_logs") / "synthetic_gen.log"
            _log.parent.mkdir(exist_ok=True)

            result = _sub.run(
                [_sys.executable, _script, "--auto"],
                cwd=str(_Path(__file__).parent),
                capture_output=True, text=True, timeout=300,
            )
            with open(_log, "a", encoding="utf-8") as lf:
                lf.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M')} ===\n")
                lf.write((result.stdout or "")[-2000:])
                lf.write((result.stderr or "")[-500:])

            if result.returncode != 0:
                # Fallback : generation directe sans rich (mode minimal)
                logger.info("[Synthetic] Fallback generation directe (sans rich)...")
                self._generate_synthetic_fallback(_data_dir, _json)
            else:
                logger.info("[Synthetic] Generation subprocess terminee")

            # Auto-injecter les Q&A comme feedbacks 'good' dans le moteur d'apprentissage
            qa_path = _data_dir / "qa_pairs.jsonl"
            if qa_path.exists():
                engine = get_learning_engine()
                injected = 0
                with open(qa_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            item = _json.loads(line)
                            entry = FeedbackEntry(
                                query=item.get("question", ""),
                                answer=item.get("answer", ""),
                                sources=[item.get("source", "synthetic_oilgas")],
                                rating="good",
                                confidence=float(item.get("grounding_ratio", 0.9)),
                                discipline=item.get("discipline", ""),
                            )
                            engine.process_feedback(entry)
                            injected += 1
                        except Exception:
                            pass
                logger.info("[Synthetic] %d exemples injectes comme feedbacks good"
                            " -> auto-retrain debloque", injected)
        except Exception as e:
            logger.error("[Synthetic] Generation echouee: %s", e)

    def _generate_synthetic_fallback(self, data_dir, json_module):
        """Generation minimale sans rich (fallback si subprocess echoue)."""
        import random as _random
        qa_pairs = []
        equipment = ["K-101", "V-101", "P-101A", "E-101", "PSV-101", "K-201",
                     "FA-1301P", "FA-1302P", "C-101", "V-102"]
        disciplines = ["process", "mechanical", "instrumentation", "safety", "piping"]
        for i in range(300):
            tag = _random.choice(equipment)
            disc = _random.choice(disciplines)
            qa_pairs.append({
                "question": f"Quelles sont les specifications de {tag} ?",
                "answer": f"L'equipement {tag} est un equipement de discipline {disc} "
                          f"conforme aux normes Oil & Gas applicables.",
                "context": f"Specification technique {tag}",
                "discipline": disc,
                "source": f"synthetic_{disc}_{i:04d}.pdf",
                "grounding_ratio": 0.9,
            })
        qa_path = data_dir / "qa_pairs.jsonl"
        with open(qa_path, "w", encoding="utf-8") as f:
            for item in qa_pairs:
                f.write(json_module.dumps(item, ensure_ascii=False) + "\n")
        logger.info("[Synthetic] Fallback: %d paires Q&A generees", len(qa_pairs))


    # ── Priorite 1 : Re-entrainement classifieur ─────────────
    def _check_and_retrain(self):
        engine = get_learning_engine()
        stats = engine.get_learning_stats()
        good_count = stats.get("good", 0)

        if good_count < self.min_good_feedback:
            logger.debug("AutoRetrain: only %d good feedbacks (need %d)",
                         good_count, self.min_good_feedback)
            return

        if time.time() - self._last_retrain < 86400:
            logger.debug("AutoRetrain: dernier fine-tuning il y a moins de 24h")
            return

        logger.info("AutoRetrain: %d good feedbacks -> lancement du cycle feedback", good_count)
        self._last_retrain = time.time()

        try:
            import subprocess
            import sys
            Path("training_logs").mkdir(exist_ok=True)
            subprocess.Popen(
                [sys.executable, "train_deerflow.py", "--mode", "feedback", "--auto"],
                cwd=str(Path(__file__).parent),
                stdout=open("training_logs/auto_retrain.log", "a"),
                stderr=subprocess.STDOUT,
            )
            logger.info("AutoRetrain: processus lance en arriere-plan")
        except Exception as e:
            logger.error("AutoRetrain: lancement echoue: %s", e)

    # ── Priorite 3 : Fine-tuning embeddings (hebdomadaire) ───
    def _check_embedding_finetune(self):
        """Lance le fine-tuning de bge-m3 une fois par semaine si assez de donnees."""
        if time.time() - self._last_embed_finetune < 604800:  # 7 jours
            return
        engine = get_learning_engine()
        stats = engine.get_learning_stats()
        good_count = stats.get("good", 0)
        if good_count < 20:
            logger.debug("[EmbedFinetune] Pas assez d'exemples: %d/20", good_count)
            return
        threading.Thread(target=self._run_embedding_finetune,
                         daemon=True, name="embed-finetune").start()

    def _run_embedding_finetune(self):
        """Lance trainer_embeddings.py pour fine-tuner bge-m3 sur les donnees du projet."""
        try:
            self._last_embed_finetune = time.time()
            logger.info("[EmbedFinetune] Demarrage fine-tuning bge-m3...")
            import subprocess, sys
            Path("training_logs").mkdir(exist_ok=True)
            result = subprocess.run(
                [sys.executable, "trainer_embeddings.py", "--auto"],
                cwd=str(Path(__file__).parent),
                capture_output=True, text=True, timeout=3600,
            )
            log_path = Path("training_logs") / "embed_finetune.log"
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M')} ===\n")
                lf.write((result.stdout or "")[-2000:])
                lf.write((result.stderr or "")[-500:])
            if result.returncode == 0:
                logger.info("[EmbedFinetune] Fine-tuning bge-m3 termine avec succes")
            else:
                logger.warning("[EmbedFinetune] Termine avec code %d", result.returncode)
        except subprocess.TimeoutExpired:
            logger.warning("[EmbedFinetune] Timeout (>1h) - annule")
        except Exception as e:
            logger.error("[EmbedFinetune] Erreur: %s", e)


# ── Singletons ───────────────────────────────────────────────

_engine: Optional[LearningEngine] = None
_engine_lock = threading.Lock()
_scheduler: Optional[AutoRetrainScheduler] = None
_scheduler_lock = threading.Lock()


def get_learning_engine() -> LearningEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = LearningEngine()
    return _engine


def get_auto_retrain_scheduler() -> AutoRetrainScheduler:
    global _scheduler
    if _scheduler is None:
        with _scheduler_lock:
            if _scheduler is None:
                _scheduler = AutoRetrainScheduler()
    return _scheduler
