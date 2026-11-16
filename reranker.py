"""
DeerFlow Lite - Semantic Reranker v2.0
Cross-encoder based reranking with lexical fallback.
"""
import re
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Try to load cross-encoder
_cross_encoder = None
_cross_encoder_available = False

def _init_cross_encoder():
    global _cross_encoder, _cross_encoder_available
    try:
        from sentence_transformers import CrossEncoder
        import os

        # Prefer fine-tuned model, fallback to pretrained
        model_path = "models/reranker_oil_gas"
        if not os.path.exists(model_path):
            model_path = "cross-encoder/ms-marco-MiniLM-L-6-v2"

        _cross_encoder = CrossEncoder(model_path, max_length=512)
        _cross_encoder_available = True
        logger.info(f"Cross-encoder loaded: {model_path}")
    except Exception as e:
        logger.warning(f"Cross-encoder unavailable, using lexical fallback: {e}")
        _cross_encoder_available = False

# Lazy initialization
_init_attempted = False

def _ensure_cross_encoder():
    global _init_attempted
    if not _init_attempted:
        _init_attempted = True
        _init_cross_encoder()



# ── Reranker neuronal fine-tuné (ajout automatique) ──────────
_NEURAL_RERANKER = None
_NEURAL_RERANKER_PATH = r"D:\DATA BASE IA\models\reranker_oil_gas"

def get_neural_reranker():
    """Charge le cross-encoder fine-tuné sur données Oil & Gas."""
    global _NEURAL_RERANKER
    if _NEURAL_RERANKER is None:
        try:
            from sentence_transformers import CrossEncoder
            _NEURAL_RERANKER = CrossEncoder(_NEURAL_RERANKER_PATH, max_length=256)
            logger.info("Reranker neuronal chargé: %s", _NEURAL_RERANKER_PATH)
        except Exception as e:
            logger.warning("Reranker neuronal non disponible: %s", e)
    return _NEURAL_RERANKER

def neural_rerank(query: str, results: list, top_n: int = 8) -> list:
    """Reranking neuronal Oil & Gas (cross-encoder fine-tuné)."""
    if not results:
        return results
    model = get_neural_reranker()
    if model is None:
        return cross_rerank(query, results, top_n=top_n)  # fallback
    pairs = [(query, r.get("document", "")[:400]) for r in results]
    try:
        scores = model.predict(pairs)
        for i, r in enumerate(results):
            r["neural_score"] = float(scores[i])
        return sorted(results, key=lambda x: x.get("neural_score", 0), reverse=True)[:top_n]
    except Exception as e:
        logger.warning("Erreur reranker neuronal: %s", e)
        return cross_rerank(query, results, top_n=top_n)


def semantic_rerank(query: str, results: list, top_k: Optional[int] = None) -> list:
    """
    Rerank results using cross-encoder semantic similarity.
    Falls back to lexical reranking if cross-encoder unavailable.

    Args:
        query: User question
        results: List of RetrievalResult objects
        top_k: Number of results to return

    Returns:
        Reranked list of RetrievalResult
    """
    if not results:
        return results

    _ensure_cross_encoder()

    if _cross_encoder_available and _cross_encoder is not None:
        return _cross_encoder_rerank(query, results, top_k)
    else:
        return _lexical_rerank(query, results, top_k)


def _cross_encoder_rerank(query: str, results: list, top_k: Optional[int] = None) -> list:
    """Rerank using cross-encoder semantic similarity scores."""
    pairs = [(query, r.content[:2048]) for r in results]

    try:
        scores = _cross_encoder.predict(pairs)

        max_original = max((r.score for r in results), default=1.0) or 1.0
        for i, result in enumerate(results):
            ce_score = float(scores[i])
            normalized_original = result.score / max_original
            result.score = 0.6 * ce_score + 0.4 * normalized_original

        results.sort(key=lambda r: r.score, reverse=True)

        if top_k:
            results = results[:top_k]

        logger.debug(f"Cross-encoder reranking: top score={results[0].score:.4f}")
        return results

    except Exception as e:
        logger.error(f"Cross-encoder reranking failed: {e}")
        return _lexical_rerank(query, results, top_k)


def _lexical_rerank(query: str, results: list, top_k: Optional[int] = None) -> list:
    """
    Improved lexical fallback reranker.
    Uses TF-IDF-weighted keyword overlap instead of raw overlap.
    """
    query_tokens = set(_tokenize(query))

    if not query_tokens:
        return results[:top_k] if top_k else results

    for result in results:
        doc_tokens = set(_tokenize(result.content))

        if not doc_tokens:
            continue

        # Jaccard similarity (bounded, no arbitrary additive boost)
        intersection = query_tokens & doc_tokens
        query_coverage = len(intersection) / len(query_tokens) if query_tokens else 0.0

        # Entity tag matching (bounded boost)
        entity_boost = _entity_match_score(query, result.content)

        # Combined: 70% original retrieval score + 20% keyword relevance + 10% entity match
        original_score = result.score
        result.score = 0.7 * original_score + 0.2 * query_coverage + 0.1 * entity_boost

    results.sort(key=lambda r: r.score, reverse=True)

    if top_k:
        results = results[:top_k]

    return results


def _entity_match_score(query: str, content: str) -> float:
    """Score based on matching equipment tags and norm references."""
    # Equipment tags: P-101, V-200, E-301, etc.
    tag_pattern = r'\b(?:\d{1,3}-)?[A-Z]{1,4}-\d{2,5}[A-Z]?\b'
    query_tags = set(re.findall(tag_pattern, query.upper()))

    if not query_tags:
        return 0.0

    content_tags = set(re.findall(tag_pattern, content.upper()))

    if not content_tags:
        return 0.0

    matching = query_tags & content_tags
    return len(matching) / len(query_tags)


def _tokenize(text: str) -> list[str]:
    """Simple tokenization for lexical matching."""
    STOPWORDS = {"le", "la", "les", "de", "du", "des", "un", "une", "et", "en",
                 "est", "sont", "pour", "par", "sur", "dans", "avec", "qui", "que",
                 "the", "is", "are", "of", "and", "in", "to", "for", "with", "on"}
    tokens = re.findall(r'\b\w{2,}\b', text.lower())
    return [t for t in tokens if t not in STOPWORDS]


def cross_rerank(query: str, results: list, top_k: Optional[int] = None) -> list:
    """Backward-compatible alias for semantic_rerank."""
    return semantic_rerank(query, results, top_k)
