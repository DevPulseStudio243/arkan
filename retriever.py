"""
DeerFlow Lite - Hybrid Retriever v2.0
Semantic + BM25 with Reciprocal Rank Fusion
"""
import json
import math
import os
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

# Imports critiques — protégés contre le crash au démarrage
try:
    import chromadb
    CHROMADB_AVAILABLE = True
except ImportError:
    chromadb = None
    CHROMADB_AVAILABLE = False
    logging.getLogger(__name__).critical("chromadb non installé — recherche vectorielle désactivée")

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    np = None
    NUMPY_AVAILABLE = False

try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25Okapi = None
    BM25_AVAILABLE = False
    logging.getLogger(__name__).warning("rank_bm25 non installé — BM25 désactivé")

logger = logging.getLogger(__name__)

# --- Config constants (imported from config in production) ---
# Fallback defaults if config module unavailable
try:
    from config import (
        CHROMA_COLLECTION, CHROMA_PATH, VECTOR_WEIGHT, BM25_WEIGHT,
        TOP_K, RRF_K, RERANK_ENABLED, EMBEDDING_MODEL, OLLAMA_BASE_URL,
        FEEDBACK_DB_PATH, SOURCE_WEIGHTS_PATH, EMBEDDING_DIM
    )
except ImportError:
    CHROMA_COLLECTION = "oil_gas_docs"
    CHROMA_PATH = "./chroma_db"
    VECTOR_WEIGHT = 0.6
    BM25_WEIGHT = 0.4
    TOP_K = 10
    RRF_K = 60
    RERANK_ENABLED = True
    EMBEDDING_MODEL = "nomic-embed-text"
    OLLAMA_BASE_URL = "http://localhost:11434"
    FEEDBACK_DB_PATH = "feedback_db.json"
    SOURCE_WEIGHTS_PATH = "source_weights.json"
    EMBEDDING_DIM = 768


@dataclass
class RetrievalResult:
    """Single retrieval result with metadata."""
    content: str
    source: str
    score: float
    chunk_id: str = ""
    discipline: str = ""
    metadata: dict = field(default_factory=dict)


class HybridRetriever:
    """
    Hybrid retrieval engine combining dense vector search and sparse BM25
    with Reciprocal Rank Fusion (RRF).
    """

    def __init__(self):
        self._chroma_client = None
        self._collection = None
        self._bm25_index = None
        self._bm25_corpus_ids = []
        self._bm25_corpus_texts = []
        self._bm25_corpus_metadatas = []
        self._embedding_matrix = None
        self._source_weights: dict[str, float] = {}
        self._source_weights_mtime = 0.0  # Toujours initialisé pour éviter AttributeError
        self._initialized = False

    def _ensure_initialized(self):
        if not self._initialized:
            self._init_chroma()
            self._build_bm25_index()
            self._load_source_weights()
            self._initialized = True

    def _init_chroma(self):
        try:
            from config import CHROMA_MODE, CHROMA_HOST, CHROMA_PORT
        except ImportError:
            CHROMA_MODE = os.environ.get("CHROMA_MODE", "local")
            CHROMA_HOST = os.environ.get("CHROMA_HOST", "chromadb")
            CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8000"))

        if CHROMA_MODE == "server":
            self._chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=int(CHROMA_PORT))
        else:
            self._chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

        try:
            self._collection = self._chroma_client.get_collection(CHROMA_COLLECTION)
            logger.info(f"ChromaDB collection '{CHROMA_COLLECTION}' loaded: {self._collection.count()} documents")
        except Exception as e:
            logger.warning(f"ChromaDB collection not found: {e}")
            self._collection = self._chroma_client.get_or_create_collection(CHROMA_COLLECTION)

    def _build_bm25_index(self):
        if self._collection is None or self._collection.count() == 0:
            logger.warning("No documents in ChromaDB, BM25 index empty")
            return

        # Chargement par batches pour contourner le bug ChromaDB 0.4.24
        # (TypeError: object of type 'int' has no len() dans _decode_seq_id)
        total = self._collection.count()
        BATCH = 500
        all_ids, all_texts, all_metas, all_embeddings = [], [], [], []

        logger.info(f"Loading {total} documents from ChromaDB (batch={BATCH})...")
        for offset in range(0, total, BATCH):
            try:
                batch = self._collection.get(
                    limit=BATCH,
                    offset=offset,
                    include=["documents", "metadatas", "embeddings"],
                )
                all_ids.extend(batch.get("ids", []))
                all_texts.extend(batch.get("documents", []))
                all_metas.extend(batch.get("metadatas", []) or [{}] * len(batch.get("ids", [])))
                if batch.get("embeddings") is not None:
                    all_embeddings.extend(batch.get("embeddings", []))
            except Exception as e:
                logger.warning(f"ChromaDB batch {offset}-{offset+BATCH} failed: {e} — skipping")
                continue

        self._bm25_corpus_ids = all_ids
        self._bm25_corpus_texts = all_texts
        self._bm25_corpus_metadatas = all_metas
        logger.info(f"ChromaDB loaded: {len(all_texts)} documents in corpus")

        tokenized = [self._tokenize(doc) for doc in self._bm25_corpus_texts]
        self._bm25_index = BM25Okapi(tokenized)
        logger.info(f"BM25 index built: {len(tokenized)} documents")

        # Load embedding matrix directly from ChromaDB embeddings if available
        if len(all_embeddings) == len(all_ids) and len(all_embeddings) > 0:
            try:
                self._embedding_matrix = np.array(all_embeddings, dtype=np.float32)
                logger.info(f"[Embeddings] Matrice d'embeddings chargee directement depuis ChromaDB : {self._embedding_matrix.shape}")
                return
            except Exception as e:
                logger.error(f"[Embeddings] Impossible d'assembler la matrice depuis ChromaDB : {e} — repli sur le cache disque/Ollama")

        # Build embedding cache in background with a DELAY to avoid RAM saturation at startup
        # The delay allows the server to fully start before the heavy embedding operation begins
        import threading
        _delay = int(os.environ.get("ARKAN_EMBED_DELAY_SECS", os.environ.get("DEERFLOW_EMBED_DELAY_SECS", "90")))
        _auto_build = os.environ.get("ARKAN_AUTO_BUILD_EMBEDDINGS", os.environ.get("DEERFLOW_AUTO_BUILD_EMBEDDINGS", "true")).lower() == "true"
        if _auto_build and len(self._bm25_corpus_texts) > 0:
            def _delayed_embed():
                import time
                logger.info(f"[Embeddings] Reconstruction differee dans {_delay}s (serveur en cours de demarrage)...")
                time.sleep(_delay)
                logger.info("[Embeddings] Debut de la reconstruction du cache...")
                self._load_or_build_embedding_cache()
            thread = threading.Thread(target=_delayed_embed, daemon=True, name="embed-cache-builder")
            thread.start()
        else:
            logger.info("[Embeddings] Reconstruction automatique desactivee (ARKAN_AUTO_BUILD_EMBEDDINGS=false)")

    def _load_or_build_embedding_cache(self):
        """
        Cache d'embeddings INCRÉMENTAL par document.
        
        Format v2 : fichier JSON dict {chunk_id -> [vector]} sur disque.
        Au redémarrage :
          - Les IDs déjà présents dans le cache sont chargés instantanément.
          - Seuls les nouveaux IDs (non présents) sont envoyés à Ollama.
          → Plus de reconstruction globale de 30-90 min sur ajout d'un seul document.
        """
        num_docs = len(self._bm25_corpus_texts)
        if num_docs == 0:
            return

        # Chemins des fichiers de cache (persistés dans data/ pour survivre aux recreations de conteneur)
        cache_dir = Path("data") if Path("data").exists() else Path(CHROMA_PATH).parent
        incremental_path = cache_dir / "embedding_cache_incremental.json"
        legacy_npy_path = cache_dir / "embedding_cache.npy"
        legacy_ids_path = cache_dir / "embedding_cache_ids.json"

        # ── Chargement du cache incrémental existant ──────────────────
        cached_vectors: dict = {}  # {chunk_id -> list[float]}

        if incremental_path.exists():
            try:
                with open(incremental_path, "r", encoding="utf-8") as f:
                    cached_vectors = json.load(f)
                logger.info(
                    "[EmbCache] Cache incrémental chargé : %d vecteurs en cache / %d docs total",
                    len(cached_vectors), num_docs
                )
            except Exception as e:
                logger.warning("[EmbCache] Impossible de lire le cache incrémental : %s — rebuild", e)
                cached_vectors = {}

        elif legacy_npy_path.exists() and legacy_ids_path.exists():
            # ── Migration automatique depuis l'ancien format numpy ──────
            try:
                with open(legacy_ids_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                old_ids = meta.get("ids", []) if isinstance(meta, dict) else []
                if old_ids:
                    old_matrix = np.load(str(legacy_npy_path))
                    if len(old_ids) == len(old_matrix):
                        cached_vectors = {
                            old_ids[i]: old_matrix[i].tolist()
                            for i in range(len(old_ids))
                        }
                        logger.info(
                            "[EmbCache] Migration ancien format numpy → incrémental : %d vecteurs migrés",
                            len(cached_vectors)
                        )
                        # Sauvegarder le nouveau format
                        with open(incremental_path, "w", encoding="utf-8") as f:
                            json.dump(cached_vectors, f)
            except Exception as e:
                logger.warning("[EmbCache] Migration ancien format échouée : %s", e)
                cached_vectors = {}

        # ── Identification des IDs manquants ──────────────────────────
        missing_indices = [
            i for i, doc_id in enumerate(self._bm25_corpus_ids)
            if doc_id not in cached_vectors
        ]

        if missing_indices:
            logger.info(
                "[EmbCache] %d nouveaux documents à encoder (sur %d total)...",
                len(missing_indices), num_docs
            )
        else:
            logger.info("[EmbCache] Cache complet — aucun nouvel encodage nécessaire.")

        # ── Encodage des documents manquants ─────────────────────────
        if missing_indices:
            import httpx as _httpx
            from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed

            MAX_WORKERS = int(os.environ.get("ARKAN_EMBED_WORKERS", os.environ.get("DEERFLOW_EMBED_WORKERS", "2")))

            def _embed_one(idx: int):
                text = self._bm25_corpus_texts[idx]
                doc_id = self._bm25_corpus_ids[idx]
                try:
                    resp = _httpx.post(
                        f"{OLLAMA_BASE_URL}/api/embeddings",
                        json={"model": EMBEDDING_MODEL, "prompt": text[:2000]},
                        timeout=120,
                    )
                    resp.raise_for_status()
                    return doc_id, resp.json()["embedding"]
                except Exception as e:
                    logger.warning("[EmbCache] Embedding échoué pour doc %s : %s", doc_id, e)
                    return doc_id, [0.0] * EMBEDDING_DIM

            done_count = 0
            total_missing = len(missing_indices)
            SAVE_EVERY = 200  # Sauvegarde incrémentale tous les 200 nouveaux vecteurs

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {executor.submit(_embed_one, idx): idx for idx in missing_indices}
                for future in _as_completed(futures):
                    doc_id, vector = future.result()
                    cached_vectors[doc_id] = vector
                    done_count += 1

                    if done_count % 50 == 0 or done_count == total_missing:
                        pct = done_count * 100 // total_missing
                        logger.info(
                            "[EmbCache] Encodage : %d/%d (%d%%)", done_count, total_missing, pct
                        )

                    # Sauvegarde incrémentale pour résistance aux crashes
                    if done_count % SAVE_EVERY == 0:
                        try:
                            with open(incremental_path, "w", encoding="utf-8") as f:
                                json.dump(cached_vectors, f)
                            logger.info(
                                "[EmbCache] Checkpoint sauvegardé (%d vecteurs)", len(cached_vectors)
                            )
                        except Exception as ce:
                            logger.warning("[EmbCache] Sauvegarde checkpoint échouée : %s", ce)

            # Sauvegarde finale
            try:
                with open(incremental_path, "w", encoding="utf-8") as f:
                    json.dump(cached_vectors, f)
                logger.info(
                    "[EmbCache] Cache incrémental sauvegardé → %s (%d vecteurs)",
                    incremental_path, len(cached_vectors)
                )
            except Exception as e:
                logger.warning("[EmbCache] Sauvegarde finale échouée : %s", e)

        # ── Assemblage de la matrice numpy dans l'ordre du corpus ─────
        try:
            self._embedding_matrix = np.array(
                [
                    cached_vectors.get(self._bm25_corpus_ids[i], [0.0] * EMBEDDING_DIM)
                    for i in range(num_docs)
                ],
                dtype=np.float32,
            )
            logger.info("[EmbCache] Matrice d'embeddings prête : %s", self._embedding_matrix.shape)
        except Exception as e:
            logger.error("[EmbCache] Assemblage matrice échoué : %s", e)
            self._embedding_matrix = None

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Use the same tokenizer as the indexer for BM25 consistency."""
        try:
            from indexer import tokenize_for_bm25
            return tokenize_for_bm25(text)
        except ImportError:
            # Fallback: basic tokenization with tag protection
            import re
            STOPWORDS_FR = {"le", "la", "les", "de", "du", "des", "un", "une", "et", "en",
                            "est", "sont", "pour", "par", "sur", "dans", "avec", "qui", "que",
                            "ce", "cette", "ces", "au", "aux", "ne", "pas", "ou", "se", "sa",
                            "son", "ses", "il", "elle", "ils", "nous", "vous", "ont", "être",
                            "avoir", "fait", "mais", "donc", "car", "ni", "si"}
            tag_pattern = r'\b([A-Z]{1,4}-\d{2,5}[A-Z]?(?:-[A-Z0-9]+)?)\b'
            tags = re.findall(tag_pattern, text)
            protected = text
            tag_map = {}
            for i, tag in enumerate(tags):
                ph = f"__TAG{i}__"
                tag_map[ph.lower()] = tag.lower()
                protected = protected.replace(tag, ph)
            tokens = re.findall(r'\b[a-zA-Z0-9_-]{2,}\b', protected.lower())
            return [tag_map.get(t, t) for t in tokens if t not in STOPWORDS_FR and len(t) >= 2]

    def _load_source_weights(self):
        """Load source weights from disk at startup."""
        self._source_weights_mtime = 0.0
        try:
            path = Path(SOURCE_WEIGHTS_PATH)
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    self._source_weights = json.load(f)
                self._source_weights_mtime = path.stat().st_mtime
                logger.info(f"Source weights loaded: {len(self._source_weights)} sources")
        except Exception as e:
            logger.debug(f"No source weights available: {e}")

    def _refresh_source_weights_if_needed(self):
        """Hot-reload source_weights.json if it changed on disk (zero-restart update).
        Called at start of every retrieve() -- O(1) stat, no disk read unless mtime changed.
        """
        try:
            path = Path(SOURCE_WEIGHTS_PATH)
            if not path.exists():
                return
            mtime = path.stat().st_mtime
            if mtime != self._source_weights_mtime:
                with open(path, 'r', encoding='utf-8') as f:
                    self._source_weights = json.load(f)
                self._source_weights_mtime = mtime
                logger.info(f"Source weights hot-reloaded: {len(self._source_weights)} sources")
        except Exception as e:
            logger.debug(f"Source weights refresh failed: {e}")

    def _embed_query(self, query: str) -> list[float]:
        """
        Get embedding vector for a query.
        Utilise le meme modele que indexer.get_embedding() pour garantir
        la coherence dimensionnelle entre documents indexes et requetes.
        Retry avec backoff si Ollama est occupe par l'indexation en cours.
        """
        # Fast check if Ollama is online to prevent blocking the event loop on offline ports
        import httpx
        try:
            resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2.0)
            if resp.status_code != 200:
                logger.warning("Ollama is offline. Bypassing vector embedding query.")
                return [0.0] * EMBEDDING_DIM
        except Exception:
            logger.warning("Ollama is offline. Bypassing vector embedding query.")
            return [0.0] * EMBEDDING_DIM

        import time as _time
        MAX_RETRIES = 3
        RETRY_DELAY = 5  # secondes entre chaque tentative

        for attempt in range(MAX_RETRIES):
            try:
                from indexer import get_embedding
                emb = get_embedding(query)
                if emb:
                    return emb
            except ImportError:
                pass
            except Exception as _e:
                logger.warning(f"_embed_query via indexer attempt {attempt+1} failed: {_e}")
                if attempt < MAX_RETRIES - 1:
                    _time.sleep(RETRY_DELAY)
                    continue

        # Fallback direct Ollama avec timeout augmente et retry
        import httpx
        for attempt in range(MAX_RETRIES):
            try:
                resp = httpx.post(
                    f"{OLLAMA_BASE_URL}/api/embeddings",
                    json={"model": EMBEDDING_MODEL, "prompt": query},
                    timeout=180  # 30 -> 180s : tolere la contention avec l'indexation bge-m3
                )
                resp.raise_for_status()
                return resp.json()["embedding"]
            except Exception as _e:
                logger.warning(f"_embed_query fallback attempt {attempt+1} failed: {_e}")
                if attempt < MAX_RETRIES - 1:
                    _time.sleep(RETRY_DELAY)
        # Dernier recours : retourner vecteur nul (BM25 prendra le relais)
        logger.error("_embed_query: tous les tentatives ont echoue - fallback vecteur nul")
        return [0.0] * EMBEDDING_DIM

    def _vector_search(self, query: str, top_k: int) -> list[RetrievalResult]:
        """Vector search using cached numpy embeddings (fast) or ChromaDB fallback (safe)."""

        # --- Cas 1 : Cache numpy prêt → recherche rapide ---
        if self._embedding_matrix is not None and len(self._embedding_matrix) > 0:
            try:
                query_emb = np.array(self._embed_query(query))
                doc_norms = np.linalg.norm(self._embedding_matrix, axis=1)
                query_norm = np.linalg.norm(query_emb)
                similarities = np.dot(self._embedding_matrix, query_emb) / (doc_norms * query_norm + 1e-8)
                top_indices = np.argsort(similarities)[::-1][:top_k * 2]
                output = []
                for idx in top_indices:
                    score = float(similarities[idx])
                    if score <= 0:
                        continue
                    meta = self._bm25_corpus_metadatas[idx] if idx < len(self._bm25_corpus_metadatas) else {}
                    output.append(RetrievalResult(
                        content=self._bm25_corpus_texts[idx],
                        source=meta.get("source", "unknown"),
                        score=score,
                        chunk_id=self._bm25_corpus_ids[idx],
                        discipline=meta.get("discipline", ""),
                        metadata=meta
                    ))
                return output
            except Exception as e:
                logger.error(f"Vector search (numpy) failed: {e}")

        # --- Cas 2 : Cache en cours de construction → fallback ChromaDB direct ---
        if self._collection is not None:
            try:
                logger.info("Embedding cache not ready — using ChromaDB fallback for vector search")
                query_emb = self._embed_query(query)
                results = self._collection.query(
                    query_embeddings=[query_emb],
                    n_results=min(top_k * 2, self._collection.count()),
                    include=["documents", "metadatas", "distances"],
                )
                output = []
                docs = results.get("documents", [[]])[0]
                metas = results.get("metadatas", [[]])[0]
                dists = results.get("distances", [[]])[0]
                for doc, meta, dist in zip(docs, metas, dists):
                    score = max(0.0, 1.0 - dist)  # convertit distance → similarité
                    meta = meta or {}
                    output.append(RetrievalResult(
                        content=doc,
                        source=meta.get("source", "unknown"),
                        score=score,
                        chunk_id=meta.get("chunk_id", ""),
                        discipline=meta.get("discipline", ""),
                        metadata=meta
                    ))
                return output
            except Exception as e:
                logger.error(f"Vector search (ChromaDB fallback) failed: {e}")

        return []


    def _bm25_search(self, query: str, top_k: int) -> list[RetrievalResult]:
        if self._bm25_index is None:
            return []

        tokens = self._tokenize(query)
        if not tokens:
            return []

        scores = self._bm25_index.get_scores(tokens)
        top_indices = np.argsort(scores)[::-1][:top_k * 2]

        output = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue

            # Use cached metadata instead of querying ChromaDB each time
            chunk_id = self._bm25_corpus_ids[idx]
            meta = self._bm25_corpus_metadatas[idx] if idx < len(self._bm25_corpus_metadatas) else {}

            output.append(RetrievalResult(
                content=self._bm25_corpus_texts[idx],
                source=meta.get("source", "unknown"),
                score=float(scores[idx]),
                chunk_id=chunk_id,
                discipline=meta.get("discipline", ""),
                metadata=meta
            ))
        return output

    def _reciprocal_rank_fusion(
        self,
        vector_results: list[RetrievalResult],
        bm25_results: list[RetrievalResult],
        k: int = 60
    ) -> list[RetrievalResult]:
        """
        Reciprocal Rank Fusion (Cormack et al., 2009).
        RRF(d) = sum over all rankings R: 1 / (k + rank_R(d))

        This is mathematically proven superior to linear score combination because:
        - It is invariant to score scale differences between rankers
        - It handles the single-result normalization problem
        - It naturally weights highly-ranked documents from either source
        """
        fused_scores: dict[str, float] = {}
        doc_map: dict[str, RetrievalResult] = {}

        # Score from vector ranking
        for rank, result in enumerate(sorted(vector_results, key=lambda r: r.score, reverse=True)):
            rrf_score = 1.0 / (k + rank + 1)
            key = result.chunk_id or result.content[:100]
            fused_scores[key] = fused_scores.get(key, 0.0) + rrf_score
            doc_map[key] = result

        # Score from BM25 ranking
        for rank, result in enumerate(sorted(bm25_results, key=lambda r: r.score, reverse=True)):
            rrf_score = 1.0 / (k + rank + 1)
            key = result.chunk_id or result.content[:100]
            fused_scores[key] = fused_scores.get(key, 0.0) + rrf_score
            if key not in doc_map:
                doc_map[key] = result

        # Apply source weights from feedback
        if self._source_weights:
            for key in fused_scores:
                source = doc_map[key].source
                raw_weight = self._source_weights.get(source, 1.0)
                # Handle both formats: float or dict with "weight" key
                if isinstance(raw_weight, dict):
                    weight = float(raw_weight.get("weight", raw_weight.get("score", 1.0)))
                else:
                    weight = float(raw_weight)
                fused_scores[key] *= weight

        # Sort by fused score
        sorted_keys = sorted(fused_scores.keys(), key=lambda k: fused_scores[k], reverse=True)

        results = []
        for key in sorted_keys:
            result = doc_map[key]
            result.score = fused_scores[key]
            results.append(result)

        return results

    def retrieve(self, query: str, top_k: Optional[int] = None, discipline_filter: Optional[str] = None) -> list[RetrievalResult]:
        """
        Main retrieval entry point.

        Args:
            query: User question
            top_k: Number of results to return (default: config TOP_K)
            discipline_filter: Optional discipline to filter by

        Returns:
            List of RetrievalResult sorted by relevance
        """
        self._ensure_initialized()
        self._refresh_source_weights_if_needed()  # Hot-reload si source_weights.json a change
        top_k = top_k or TOP_K

        # Parallel retrieval from both engines
        vector_results = self._vector_search(query, top_k)
        try:
            from vocabulary import expand_query
            expanded_query = expand_query(query)
        except ImportError:
            expanded_query = query
        bm25_results = self._bm25_search(expanded_query, top_k)

        logger.info(f"Vector: {len(vector_results)} results, BM25: {len(bm25_results)} results")

        # Reciprocal Rank Fusion
        fused = self._reciprocal_rank_fusion(vector_results, bm25_results)

        # Optional discipline filter
        if discipline_filter:
            disc_lower = discipline_filter.lower()
            filtered = [r for r in fused if disc_lower in r.discipline.lower()]
            if not filtered:
                logger.warning(f"No results for discipline '{discipline_filter}', returning unfiltered results")
            fused = filtered if filtered else fused

        # Neural Reranking (Cross-Encoder)
        if RERANK_ENABLED:
            try:
                from neural_reranker import get_reranker
                reranker = get_reranker()
                # On passe le double de top_k au reranker pour qu'il puisse trier parmi un plus large spectre
                fused = reranker.rerank(query, fused[:top_k * 3], top_k=top_k)
            except Exception as e:
                logger.error(f"Neural reranking step failed, falling back to RRF: {e}")
                fused = fused[:top_k]
        else:
            fused = fused[:top_k]

        return fused

    def assess_context_sufficiency(self, query: str, results: list[RetrievalResult], threshold: float = 0.3) -> dict:
        """
        Assess whether retrieved context is sufficient to answer the query.
        Uses cached embedding similarity against top result (no extra Ollama call).
        """
        if not results:
            return {"sufficient": False, "confidence": 0.0, "reason": "Aucun document trouvé"}

        try:
            scores = [r.score for r in results]
            
            # Detect if scores are raw logits (which can be negative or positive, but typically not RRF)
            # RRF scores are always between 0 and 0.05
            is_reranked = any(s < 0 or s > 0.05 for s in scores)

            if is_reranked:
                # Normalize raw logits using sigmoid centered around -3.0
                normalized_scores = []
                for s in scores:
                    if 0.0 <= s <= 1.0:
                        normalized_scores.append(s)
                    else:
                        norm = 1.0 / (1.0 + math.exp(-(s + 3.0) / 1.5))
                        normalized_scores.append(norm)
                
                avg_score = sum(normalized_scores) / len(normalized_scores)
                max_score = max(normalized_scores)
                normalized_max = max_score
                avg_score_term = avg_score
            else:
                avg_score = sum(scores) / len(scores)
                max_score = max(scores)
                max_possible_rrf = 2.0 / (RRF_K + 1)
                normalized_max = min(max_score / max_possible_rrf, 1.0) if max_possible_rrf > 0 else 0.0
                avg_score_term = avg_score * 50

            coverage = min(len(results) / max(TOP_K, 1), 1.0)

            # Weighted confidence
            if is_reranked:
                confidence = 0.6 * normalized_max + 0.25 * avg_score_term + 0.15 * coverage
            else:
                confidence = 0.5 * normalized_max + 0.35 * avg_score_term + 0.15 * coverage

            confidence = max(0.0, min(1.0, confidence))
            sufficient = confidence >= threshold

            return {
                "sufficient": sufficient,
                "confidence": round(confidence, 3),
                "num_results": len(results),
                "max_score": round(max_score, 4),
                "reason": "Contexte suffisant" if sufficient else "Contexte insuffisant — pertinence faible",
            }
        except Exception as e:
            logger.warning(f"Context sufficiency assessment failed: {e}")
            return {
                "sufficient": len(results) > 0,
                "confidence": 0.3 if results else 0.0,
                "reason": "Évaluation par défaut (fallback)",
            }

    def build_context_string(self, results: list[RetrievalResult], max_tokens: int = None) -> str:
        """Build formatted context string for LLM prompt injection.
        
        Utilise MAX_CONTEXT_TOKENS depuis config (défaut 4000 tokens).
        Enrichit les headers avec discipline et score pour aider le LLM à prioriser.
        """
        if not results:
            return ""

        # Utiliser MAX_CONTEXT_TOKENS depuis config si non spécifié
        if max_tokens is None:
            try:
                from config import MAX_CONTEXT_TOKENS
            except ImportError:
                MAX_CONTEXT_TOKENS = 4000
            max_tokens = MAX_CONTEXT_TOKENS

        context_parts = []
        total_chars = 0
        char_limit = max_tokens * 4  # ~4 chars/token

        for i, r in enumerate(results, 1):
            src = getattr(r, "source", None) or (r.get("source", "unknown") if isinstance(r, dict) else "unknown")
            disc = getattr(r, "discipline", None) or (r.get("discipline", "") if isinstance(r, dict) else "")
            score = getattr(r, "score", 0.0) or (r.get("score", 0.0) if isinstance(r, dict) else 0.0)
            cont = getattr(r, "content", None) or getattr(r, "text", None) or (r.get("content", "") if isinstance(r, dict) else "") or (r.get("text", "") if isinstance(r, dict) else "")

            # Extraire seulement le nom de fichier (pas le chemin complet)
            src_display = src.split("\\")[-1].split("/")[-1] if src != "unknown" else "Inconnu"

            source_info = f"[{src_display}]" if src != "unknown" else ""
            discipline_info = f"[{disc.upper()}]" if disc else ""
            score_info = f"[score: {score:.3f}]" if score > 0 else ""
            header = f"--- Document {i} {source_info} {discipline_info} {score_info} ---"
            entry = f"{header}\n{cont}\n"

            if total_chars + len(entry) > char_limit:
                break

            context_parts.append(entry)
            total_chars += len(entry)

        return "\n".join(context_parts)

    def invalidate_cache(self):
        """Force rebuild of BM25 index, embeddings, and source weights."""
        self._initialized = False
        self._bm25_index = None
        self._embedding_matrix = None
        self._bm25_corpus_metadatas = []
        self._source_weights = {}
        logger.info("Retriever cache invalidated")


def top_k_default() -> int:
    return TOP_K


# Module-level convenience functions
_retriever_instance = None
_retriever_lock = __import__('threading').Lock()

def get_retriever() -> HybridRetriever:
    global _retriever_instance
    if _retriever_instance is None:
        with _retriever_lock:
            if _retriever_instance is None:
                _retriever_instance = HybridRetriever()
    return _retriever_instance

def hybrid_retrieve(query: str, top_k: int = None, discipline: str = None) -> list[RetrievalResult]:
    return get_retriever().retrieve(query, top_k, discipline)

def assess_context_sufficiency(query: str, results: list[RetrievalResult]) -> dict:
    return get_retriever().assess_context_sufficiency(query, results)

def build_context_string(results: list[RetrievalResult], max_tokens: int = 3000) -> str:
    return get_retriever().build_context_string(results, max_tokens)



# ── Fonctions module-level (aliases de la classe) ────────────
# Note: apply_source_weights() est géré nativement par HybridRetriever._reciprocal_rank_fusion()
# Le patch injecté par trainer_feedback.py est intentionnellement absent ici car
# il opère sur list[dict] et est incompatible avec list[RetrievalResult].
