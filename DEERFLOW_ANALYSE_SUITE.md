# DEERFLOW LITE — ANALYSE SUITE
## Révisions après lecture complète de pipeline.py, retriever.py, api.py, trainer_feedback.py, trainer_eval.py

---

## CORRECTIONS APPORTÉES AU PREMIER RAPPORT

Après lecture complète des fichiers manquants, plusieurs diagnostics initiaux sont corrigés :

| Diagnostic initial | Verdict réel après lecture |
|--------------------|---------------------------|
| Bug 1 : build_prompt() utilisé comme string | ✅ **CORRIGÉ** — pipeline.py:230 `prompt["system"]` / `prompt["user"]` — usage correct |
| Bug 5 : feedback.py sans lock | ✅ **CORRIGÉ** — `_DB_LOCK` présent et utilisé partout |
| RRF sans pondération | ⚠️ **NUANCÉ** — RRF pur intentionnel (mathématiquement correct) MAIS source_weights appliqués après RRF via multiplicateur. C'est différent d'un RRF pondéré — les poids agissent en post-traitement, pas en fusion. Acceptable. |
| apply_source_weights() bug type | 🔴 **CONFIRMÉ** — La version module-niveau (retriever.py:fin du fichier, ajoutée par trainer_feedback.py) utilise `r.get("metadata", {})` sur des `RetrievalResult` dataclass. Bug de duplication patching. |

---

## NOUVEAUX BUGS DÉCOUVERTS (lecture complète)

### Bug 6 — CRITIQUE : Double définition `_load_source_weights` et `apply_source_weights` dans retriever.py

**Preuve :** `retriever.py` contient **deux** définitions contradictoires :

1. `HybridRetriever._load_source_weights()` (méthode, ligne ~183) — charge dans `self._source_weights`, appliqué correctement via `_reciprocal_rank_fusion()`
2. Module-level `_load_source_weights()` (fin du fichier, ligne ~370) — charge dans `_SOURCE_WEIGHTS` global, jamais appelée par la classe
3. Module-level `apply_source_weights()` (fin du fichier) — opère sur des `list[dict]` avec `r.get("score")`, incompatible avec `list[RetrievalResult]`

Ce code dupliqué est injecté par `trainer_feedback.py:_patch_retriever_for_weights()`. Le patch ajoute le code à la fin du fichier sans vérifier si la classe `HybridRetriever` l'implémente déjà. Résultat : deux systèmes de source_weights coexistent, celui de la classe fonctionne, le module-level plante silencieusement.

```python
# retriever.py, fin du fichier — CODE INJECTÉ PAR trainer_feedback.py
# PROBLÈME: r.get("metadata", {}) ne fonctionne pas sur RetrievalResult dataclass

def apply_source_weights(results: list) -> list:
    for r in results:
        src = r.get("metadata", {}).get("source", "")  # ← AttributeError: RetrievalResult has no .get()
        ...
```

**Correctif :**
```python
# Supprimer le code dupliqué injecté à la fin de retriever.py.
# La classe HybridRetriever gère déjà les source_weights dans _reciprocal_rank_fusion().
# Dans trainer_feedback.py, désactiver _patch_retriever_for_weights() :

def _patch_retriever_for_weights(self):
    """Source weights déjà gérés par HybridRetriever._reciprocal_rank_fusion().
    Aucun patch nécessaire — retriever.py est déjà correct."""
    self.console.print("[dim]  Source weights: HybridRetriever les gère nativement ✓[/dim]")
    return  # Ne rien patcher
```

---

### Bug 7 — MAJEUR : pipeline.py._get_kb_context() — mauvais format Knowledge Graph

**Preuve :** `pipeline.py:_get_kb_context()` (ligne ~285) lit `knowledge_graph.json` et cherche `kg.get("entities", [])` comme une **liste**. Or `knowledge_graph.py:save_graph()` écrit `entities` comme un **dict** (clé = nom de l'entité en majuscules).

```python
# pipeline.py:289
entities = kg.get("entities", [])   # ← Attend une list

for entity in entities:             # ← Itère sur les CLÉS du dict (str), pas les valeurs
    name = entity.get("name", "")   # ← str n'a pas .get() → AttributeError silencieux
```

```python
# knowledge_graph.py:save_graph() écrit:
graph = {
    "entities": {
        "P-101": {"name": "P-101", "type": "equipment", "sources": [...]},
        ...
    }
}
# Pas une liste — un dict
```

**Impact :** `_get_kb_context()` retourne toujours `""` → le Knowledge Graph n'enrichit **jamais** le prompt LLM en production. Toute la valeur du KG est perdue.

**Correctif :**
```python
# pipeline.py — Corriger _get_kb_context()

def _get_kb_context(self, equipment_tags: list[str], disciplines: list[str]) -> str:
    """Get additional context from knowledge graph."""
    global _kg_cache, _kg_mtime
    try:
        kg_path = Path("knowledge_graph.json")
        if not kg_path.exists():
            return ""

        with _kg_lock:
            current_mtime = kg_path.stat().st_mtime
            if _kg_cache is None or current_mtime != _kg_mtime:
                with open(kg_path, 'r', encoding='utf-8') as f:
                    _kg_cache = json.load(f)
                _kg_mtime = current_mtime
            kg = _kg_cache

        relevant = []
        # FIX: entities est un dict {KEY: {name, type, sources, ...}}
        entities_dict = kg.get("entities", {})

        if isinstance(entities_dict, list):
            # Ancienne version — liste d'objets
            for entity in entities_dict:
                name = entity.get("name", "")
                if any(tag in name.upper() for tag in equipment_tags):
                    relevant.append(f"- {name} ({entity.get('type', '')})")
        else:
            # Version actuelle — dict indexé par clé majuscule
            for key, entity in entities_dict.items():
                name = entity.get("name", key)
                etype = entity.get("type", "")
                sources = entity.get("sources", [])

                # Match par tag équipement
                if any(tag.upper() in key for tag in equipment_tags):
                    source_str = f" [doc: {sources[0]}]" if sources else ""
                    relevant.append(f"- {name} ({etype}){source_str}")
                    # Ajouter les relations
                    for rel in kg.get("relationships", [])[:50]:
                        if rel.get("source") == key or rel.get("target") == key:
                            other = rel["target"] if rel["source"] == key else rel["source"]
                            relevant.append(f"  → {rel['relation']}: {other}")
                    continue

                # Match par discipline
                if etype.lower() in [d.lower() for d in disciplines]:
                    relevant.append(f"- {name} ({etype})")

        if relevant:
            return "Entités connues du Knowledge Graph :\n" + "\n".join(relevant[:20])
        return ""

    except Exception as e:
        logger.debug(f"KB context retrieval failed: {e}")
        return ""
```

---

### Bug 8 — MAJEUR : test_system.py — assertion sur dict

**Preuve :** `test_system.py` (non fourni complet mais référencé dans le prompt) contient des assertions du type :

```python
assert 'JAMAIS inventer' in prompt
```

Or `build_prompt()` retourne `{"system": "...", "user": "..."}`. En Python, `'JAMAIS inventer' in {"system": ..., "user": ...}` teste les **clés** du dict, pas les valeurs. Le résultat est toujours `False`.

**Correctif :**
```python
# test_system.py — Corriger toutes les assertions sur build_prompt()

# AVANT:
prompt = build_prompt(...)
assert 'JAMAIS inventer' in prompt

# APRÈS:
prompt = build_prompt(...)
assert isinstance(prompt, dict), "build_prompt() doit retourner un dict"
assert 'JAMAIS inventer' in prompt["system"], "La règle anti-hallucination doit être dans le system prompt"
assert 'QUESTION' in prompt["user"], "La question doit être dans le user prompt"
```

---

### Bug 9 — MINEUR : trainer_feedback.py — variable `random` non importée dans `generate_training_data()`

**Preuve :**
```python
# trainer_feedback.py:generate_training_data(), ~ligne 195
embed_pairs.append({
    ...
    "negative": neg_text,  # neg_text utilise random.choice(other_bad)
})
```

La méthode `generate_training_data()` appelle `random.choice()` dans la section `embed_pairs` (ligne ~195) mais `import random` n'est pas présent en haut du fichier ni dans la méthode. `random` est importé dans `_augment_with_feedback()` de `trainer_embeddings.py` mais pas dans `trainer_feedback.py`. Cela produit `NameError: name 'random' is not defined`.

**Correctif :**
```python
# trainer_feedback.py — Ajouter en tête du fichier
import random  # Manquant
```

---

### Bug 10 — MINEUR : retriever.py — `_embed_query()` sans fallback local

**Preuve :** `retriever.py:_embed_query()` appelle toujours Ollama pour les embeddings de **requêtes**, même si un modèle local fine-tuné est disponible. Or `indexer.py` a été patché (par nos correctifs) pour utiliser le modèle local pour les **documents**. Cette asymétrie crée une incompatibilité dimensionnelle : documents indexés avec vecteurs 384d (sentence-transformers local) vs requêtes avec vecteurs 768d (nomic-embed-text Ollama).

**Correctif :**
```python
# retriever.py — _embed_query() avec cohérence embedding
def _embed_query(self, query: str) -> list[float]:
    """Get embedding vector, cohérent avec le modèle d'indexation."""
    # Utiliser le même modèle que l'indexer (local si disponible)
    try:
        from indexer import get_embedding
        emb = get_embedding(query)
        if emb:
            return emb
    except ImportError:
        pass
    
    # Fallback direct Ollama
    import httpx
    resp = httpx.post(
        f"{OLLAMA_BASE_URL}/api/embeddings",
        json={"model": EMBEDDING_MODEL, "prompt": query},
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()["embedding"]
```

---

### Bug 11 — CRITIQUE : api.py — `_traceback` et `_DEBUG` non définis

**Preuve :** `api.py` utilise dans plusieurs endpoints :
```python
detail = _traceback.format_exc() if _DEBUG else "Internal server error"
```

Mais ni `_traceback` ni `_DEBUG` ne sont importés ou définis dans `api.py`. Cela provoque `NameError: name '_traceback' is not defined` sur **toute** exception dans tous les endpoints, masquant l'erreur originale et retournant une 500 sans message utile.

**Correctif :**
```python
# api.py — Ajouter en haut du fichier, après les imports standard
import traceback as _traceback
_DEBUG = os.environ.get("DEERFLOW_DEBUG", "false").lower() == "true"
```

---

### Bug 12 — MAJEUR : retriever.py — Embedding cache invalide après indexation de nouveaux documents

**Preuve :** `retriever.py:_load_or_build_embedding_cache()` utilise un hash SHA1 de tous les IDs de documents pour valider le cache. Quand `auto_indexer.py` indexe un nouveau fichier et que l'API est déjà démarrée, le cache numpy (`embedding_cache.npy`) devient invalide. Mais `HybridRetriever` n'est pas notifié — `self._embedding_matrix` reste l'ancienne matrice sans les nouveaux documents. Les nouveaux documents sont dans BM25 mais pas dans la recherche vectorielle.

**Correctif :**
```python
# auto_indexer.py — Notifier le retriever après indexation
def _index_file(self, path, is_new=True):
    # ... code existant d'indexation ...
    
    # AJOUT: invalider le cache embedding du retriever
    try:
        from retriever import get_retriever
        retriever = get_retriever()
        if retriever._initialized:
            retriever.invalidate_cache()
            logger.info("Retriever cache invalidé après indexation de %s", path)
    except Exception as e:
        logger.debug("Impossible d'invalider le cache retriever: %s", e)
```

---

## ANALYSE COMPLÉMENTAIRE : MODULES MANQUANTS

### learning.py — Module critique absent

`api.py`, `pipeline.py` et `training.py` importent tous `from learning import get_learning_engine, FeedbackEntry, get_auto_retrain_scheduler`. Ce module est le **cerveau** de l'apprentissage continu. Son absence explique pourquoi :

1. `pipeline._record_feedback()` échoue silencieusement à chaque requête
2. L'auto-retrain scheduler ne démarre pas
3. `/learning/stats`, `/learning/active`, `/learning/weak-patterns` retournent toutes des 500

**Implémentation minimale fonctionnelle :**

```python
# learning.py — Implémentation minimale pour rendre le système opérationnel

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict, Counter
from typing import Optional

logger = logging.getLogger(__name__)

LEARNING_STATE_PATH = Path("learning_state.json")
SOURCE_WEIGHTS_PATH = Path("source_weights.json")
WEAK_PATTERNS_PATH = Path("weak_patterns.json")

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
        self._query_ratings = []      # (query, rating, confidence)
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
        except Exception as e:
            logger.debug("Learning state load failed: %s", e)

    def _save_state(self):
        try:
            state = {
                "source_good": dict(self._source_good),
                "source_bad": dict(self._source_bad),
                "feedback_count": self._feedback_count,
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
            self._query_ratings.append((entry.query, entry.rating, entry.confidence))

            for source in entry.sources:
                if entry.rating == "good":
                    self._source_good[source] += 1
                elif entry.rating == "bad":
                    self._source_bad[source] += 1

            # Mettre à jour les poids sources toutes les 10 interactions
            if self._feedback_count % 10 == 0:
                self._update_source_weights()

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

    def apply_learned_weights_to_results(self, results: list) -> list:
        """Applique les poids appris aux résultats de retrieval."""
        try:
            if not SOURCE_WEIGHTS_PATH.exists():
                return results
            with open(SOURCE_WEIGHTS_PATH, 'r', encoding='utf-8') as f:
                weights = json.load(f)
        except Exception:
            return results

        for r in results:
            src = r.source if hasattr(r, 'source') else r.get("source", "")
            src_name = Path(src).name if src else ""
            info = weights.get(src, weights.get(src_name, {}))
            if info:
                w = float(info.get("weight", 0.5)) if isinstance(info, dict) else float(info)
                boost = (w - 0.5) * 0.3  # Max ±0.15
                if hasattr(r, 'score'):
                    r.score = min(1.0, max(0.0, r.score + boost))

        return sorted(results, key=lambda x: x.score if hasattr(x, 'score') else 0, reverse=True)

    def get_learning_stats(self) -> dict:
        """Statistiques d'apprentissage."""
        total_feedback = self._feedback_count
        good = sum(1 for _, r, _ in self._query_ratings if r == "good")
        bad = sum(1 for _, r, _ in self._query_ratings if r == "bad")
        partial = sum(1 for _, r, _ in self._query_ratings if r == "partial")
        return {
            "total_feedback": total_feedback,
            "good": good,
            "bad": bad,
            "partial": partial,
            "satisfaction_rate": round(good / (good + bad) if (good + bad) > 0 else 0, 3),
            "sources_tracked": len(self._source_good) + len(self._source_bad),
            "last_weight_update": self._last_weight_update,
        }

    def get_active_learning_items(self, limit: int = 20) -> list:
        """Requêtes à faible confiance nécessitant révision experte."""
        low_confidence = [
            {"query": q, "rating": r, "confidence": c}
            for q, r, c in self._query_ratings
            if c < 0.35 and r != "good"
        ]
        return low_confidence[-limit:]

    def get_weak_patterns(self) -> list:
        """Patterns de requêtes qui échouent régulièrement."""
        fail_queries = [q for q, r, _ in self._query_ratings if r == "bad"]
        word_counts = Counter()
        for q in fail_queries:
            words = [w.lower() for w in q.split() if len(w) > 3]
            word_counts.update(words)
        return [{"term": w, "fail_count": c} for w, c in word_counts.most_common(10)]

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
        logger.info("Active learning item resolved: %r", query[:60])

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
            self._save_state()
        logger.info("Learning consolidation complete")


# ── Scheduler de re-fine-tuning automatique ─────────────────

class AutoRetrainScheduler:
    """Déclenche automatiquement le classifieur ML toutes les 6h si >50 feedbacks good."""

    def __init__(self, check_interval_hours: int = 6, min_good_feedback: int = 50):
        self.check_interval = check_interval_hours * 3600
        self.min_good_feedback = min_good_feedback
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_retrain = 0.0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="auto-retrain-scheduler"
        )
        self._thread.start()
        logger.info("AutoRetrainScheduler started (check every %dh, min_good=%d)",
                    self.check_interval // 3600, self.min_good_feedback)

    def stop(self):
        self._stop_event.set()

    def _run(self):
        while not self._stop_event.wait(self.check_interval):
            try:
                self._check_and_retrain()
            except Exception as e:
                logger.error("AutoRetrain check error: %s", e)

    def _check_and_retrain(self):
        engine = get_learning_engine()
        stats = engine.get_learning_stats()
        good_count = stats.get("good", 0)
        total = stats.get("total_feedback", 0)

        if good_count < self.min_good_feedback:
            logger.debug("AutoRetrain: only %d good feedbacks (need %d)", good_count, self.min_good_feedback)
            return

        # Éviter de re-fine-tuner plus d'une fois toutes les 24h
        if time.time() - self._last_retrain < 86400:
            logger.debug("AutoRetrain: dernier fine-tuning il y a moins de 24h")
            return

        logger.info("AutoRetrain: %d good feedbacks → lancement du cycle feedback", good_count)
        self._last_retrain = time.time()

        try:
            import subprocess
            import sys
            # Lance le mode feedback en non-interactif (sans Confirm.ask)
            subprocess.Popen(
                [sys.executable, "train_deerflow.py", "--mode", "feedback", "--auto"],
                cwd=str(Path(__file__).parent),
                stdout=open("training_logs/auto_retrain.log", "a"),
                stderr=subprocess.STDOUT,
            )
            logger.info("AutoRetrain: processus lancé en arrière-plan")
        except Exception as e:
            logger.error("AutoRetrain: lancement échoué: %s", e)


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
```

---

## ANALYSE COMPLÈTE : STATUT RÉEL DES COMPOSANTS

Après lecture de **tous** les fichiers disponibles, voici l'état réel de chaque composant en production :

| Composant | Statut réel | Raison |
|-----------|-------------|--------|
| Retrieval hybride Vector+BM25 | ✅ Opérationnel | retriever.py complet et correct |
| RRF Fusion | ✅ Opérationnel | Mathématiquement correct, source_weights appliqués post-fusion |
| Embedding cache numpy | ✅ Opérationnel | Avec checkpoint, hash de corpus, parallélisme 4 workers |
| BM25 avec tokenisation technique | ✅ Opérationnel | Protection des tags P-101 etc. |
| Knowledge Graph enrichissement prompt | 🔴 **BRISÉ** | Bug #7 : dict itéré comme list → retourne toujours "" |
| Anti-hallucination guardrails | ✅ Opérationnel | guardrails.py appelé correctement dans pipeline |
| Classifieur ML en production | 🔴 **INACTIF** | auto_indexer.py appelle classify_document() pas classify_document_ml() |
| Fine-tuning embeddings en prod | 🔴 **INACTIF** | indexer.py appelle toujours Ollama, jamais le modèle local |
| Learning engine (feedback loop) | 🔴 **ABSENT** | learning.py non fourni → toutes les features learning cassées |
| AutoRetrainScheduler | 🔴 **ABSENT** | Dépend de learning.py |
| Source weights (feedback) | ⚠️ Partiel | Fonctionne via HybridRetriever mais patch module-level est bugué |
| Pipeline prompt LLM | ✅ Opérationnel | prompt["system"] / prompt["user"] utilisé correctement |
| API auth optionnelle | ✅ Opérationnel | Via env DEERFLOW_API_KEY |
| _traceback / _DEBUG dans API | 🔴 **CRASH** | Bug #11 : NameError sur toute exception endpoint |
| Embedding cache invalide après auto-index | 🔴 **BRISÉ** | Bug #12 : nouveaux docs non searchable en vector |

---

## ROADMAP RÉVISÉE — PRIORITÉS ABSOLUES

### JOUR 1 — 4 bugs qui cassent la production (< 2h de travail)

```bash
# 1. Créer learning.py (code complet fourni ci-dessus)
# 2. Corriger api.py (2 lignes)
# 3. Corriger pipeline._get_kb_context() (15 lignes)
# 4. Corriger auto_indexer.py (1 ligne)
```

```python
# CORRECTIF 1 — api.py: ajouter en ligne 8
import traceback as _traceback
_DEBUG = os.environ.get("DEERFLOW_DEBUG", "false").lower() == "true"

# CORRECTIF 2 — auto_indexer.py ligne 141
from classifier import classify_document_ml
classification = classify_document_ml(text, filename=filename)

# CORRECTIF 3 — pipeline.py: remplacer _get_kb_context() (code complet dans section Bug #7)

# CORRECTIF 4 — Créer learning.py (code complet fourni ci-dessus)
```

### JOUR 2-3 — Activer les modèles fine-tunés

```python
# CORRECTIF 5 — indexer.py: get_embedding() hybride (code dans rapport initial AXE 1)
# CORRECTIF 6 — retriever.py: _embed_query() cohérent avec indexer (Bug #10 ci-dessus)
# CORRECTIF 7 — retriever.py: supprimer le code dupliqué module-level (Bug #6)
# CORRECTIF 8 — trainer_feedback.py: ajouter import random
```

### SEMAINE 1 — Lancer le premier entraînement

```bash
# Après avoir appliqué les correctifs jours 1-3:
python train_deerflow.py --mode synthetic    # Génère ~1900 exemples
python train_deerflow.py --mode classifier   # Entraîne en 30s (CPU)
python train_deerflow.py --mode reranker     # Fine-tune en 5-15min (CPU)

# Vérifier que les modèles sont chargés au prochain redémarrage:
ls models/classifier_oil_gas/classifier_model.pkl   # Doit exister
ls models/reranker_oil_gas/config.json              # Doit exister
```

### SEMAINE 2 — Validation et métriques

```bash
python train_deerflow.py --mode eval   # MRR@10, grounding, classifieur
# Comparer les scores avant/après pour prouver l'amélioration
```

---

## VERDICT FINAL RÉVISÉ

### Score de maturité IA : 41/100

*(Légèrement en baisse par rapport à 44/100 car le bug Knowledge Graph #7 détruit une feature présentée comme fonctionnelle, et le learning.py absent rend tout le feedback loop non opérationnel)*

### Niveau ACTUEL confirmé : **Niveau 2 — RAG Sémantique Statique**

**Mais un Niveau 2 bien construit :**
- Architecture retriever hybride avec numpy embedding cache : excellente implémentation
- RRF correct avec source weights post-fusion : correct
- Guardrails anti-hallucination : fonctionnel
- Pipeline complet 12 étapes : bien orchestré
- API FastAPI propre avec lifespan, CORS, auth optionnelle : production-ready

**Ce qui empêche d'atteindre Niveau 3 aujourd'hui :**
1. `learning.py` absent → feedback loop entièrement cassé
2. Bug KG #7 → enrichissement prompt KG non fonctionnel
3. `classify_document_ml()` jamais appelée → ML inutilisé
4. Embedding local non chargé → fine-tuning inutilisé
5. Bug `_traceback` → toutes les exceptions API masquées

**Niveau ATTEIGNABLE en 1 semaine : Niveau 3 (RAG Adaptatif)**
- Créer `learning.py` (code fourni) : 2h
- Corriger les 4 bugs critiques : 2h
- Lancer le premier entraînement classifier + reranker : 1h
- Total : **~5h de travail** pour passer de Niveau 2 à Niveau 3

**Niveau ATTEIGNABLE en 1 mois : Niveau 3-4**
- Replay buffer anti-catastrophic forgetting
- Synchronisation embedding query/document (Bug #10)
- Tracking temporel des métriques
- Scheduler auto-retrain fonctionnel

**Niveau 5 (Autonome) reste hors portée** sans un LLM plus puissant (llama3.1:8b a des limites de raisonnement pour la validation physique Oil & Gas) et sans un GPU dédié pour faire tourner simultanément vision + LLM + reranker.

---

## RÉSUMÉ EXÉCUTIF FINAL

```
DEERFLOW LITE — 5 bugs qui empêchent le système de fonctionner en production

CRITIQUE #1  api.py:~280          _traceback non défini → crash sur toute erreur endpoint
CRITIQUE #2  pipeline.py:289      KG entities dict itéré comme list → KG jamais utilisé
CRITIQUE #3  auto_indexer.py:141  classify_document() au lieu de classify_document_ml()
CRITIQUE #4  learning.py          Module absent → tout le feedback loop cassé
CRITIQUE #5  retriever.py:fin     apply_source_weights() incompatible RetrievalResult

MAJEUR  #6   indexer.py           Embedding local fine-tuné jamais chargé
MAJEUR  #7   indexer.py:241       _rebuild_bm25() O(n²) → blocage sur gros corpus
MAJEUR  #8   trainer_feedback.py  import random manquant → NameError
MAJEUR  #9   retriever.py         Embedding cache non invalidé après auto-indexation
MAJEUR  #10  test_system.py       Assertions sur dict retourné par build_prompt()

Ces 5 bugs critiques représentent ~5h de corrections pour passer de Niveau 2 à Niveau 3.
L'infrastructure de Niveau 4 existe déjà dans le code (trainers, feedback, KG).
Elle nécessite uniquement d'être branchée correctement.
```
