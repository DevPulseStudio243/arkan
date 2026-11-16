# ============================================================
#  DEERFLOW LITE - Feedback / Self-learning
#  Learns from user interactions to improve future answers.
# ============================================================

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

from config import FEEDBACK_DB_PATH

logger = logging.getLogger(__name__)

# Thread-safe lock for all feedback DB operations
_DB_LOCK = threading.Lock()


# -- Persistence -------------------------------------------

def _load_db():
    """Load the feedback database from disk. Caller should hold _DB_LOCK."""
    try:
        path = Path(FEEDBACK_DB_PATH)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        return []
    except Exception as exc:
        logger.error("Error loading feedback DB: %s", exc)
        return []


def _save_db(records):
    """Save feedback database atomically. Caller should hold _DB_LOCK."""
    try:
        with open(FEEDBACK_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.error("Error saving feedback DB: %s", exc)


# -- Token-based similarity --------------------------------

def _tokenize(text):
    """Simple whitespace + lowercase tokenizer for similarity checks."""
    import re
    tokens = re.split(r"[\s\.,;:!?()\[\]{}<>\"'`/\\|@#$%^&*+=~]+", text.lower())
    return set(t for t in tokens if len(t) >= 2)


def _token_overlap(text_a, text_b):
    """Return Jaccard similarity between two texts based on token overlap."""
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


# -- Public API --------------------------------------------

def save_feedback(question, answer, sources=None, rating="pending", metadata=None):
    """Save user feedback for a question/answer pair.

    Args:
        question: The user question.
        answer: The generated answer.
        sources: List of source document names.
        rating: One of 'good', 'bad', 'pending'.
        metadata: Optional dict with extra fields (query_type, confidence,
                  grounding_ratio, etc.).

    Returns:
        The ID of the saved feedback record.
    """
    with _DB_LOCK:
        records = _load_db()
        meta = metadata or {}
        
        # Sécurité : ne jamais auto-valider comme "good" une réponse qui contient l'avertissement de limite
        if rating == "good" and isinstance(answer, str) and ("limite de raisonnement" in answer or answer.startswith("⚠")):
            rating = "bad"
            
        record_id = uuid.uuid4().hex[:12]
        record = {
            "id": record_id,
            "question": question,
            "answer": answer,
            "sources": sources or [],
            "rating": rating,
            "timestamp": datetime.utcnow().isoformat(),
            "query_type": meta.get("query_type", ""),
            "confidence": meta.get("confidence", 0.0),
            "grounding_ratio": meta.get("grounding_ratio", 0.0),
        }
        records.append(record)
        _save_db(records)
        logger.info("Feedback saved: id=%s rating=%s", record_id, rating)
    return record_id


def get_similar_questions(question, threshold=0.5, max_results=5):
    """Find past questions similar to the current one.

    Uses simple token overlap (Jaccard similarity).

    Returns:
        A list of feedback records sorted by similarity (descending).
    """
    records = _load_db()
    scored = []
    for rec in records:
        sim = _token_overlap(question, rec.get("question", ""))
        if sim >= threshold:
            scored.append((sim, rec))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [rec for _, rec in scored[:max_results]]


def get_best_answer(question, threshold=0.85, max_age_days=30):
    """Return a cached answer if a very similar question was previously rated good.

    Args:
        question: The current question.
        threshold: Minimum Jaccard similarity to consider a match.
                   0.85 = quasi-identique requis (était 0.65, trop permissif).
                   Exemple: "pression K-101" et "débit V-201" → sim ≈ 0.1 → pas de hit.
        max_age_days: Maximum age in days for cached answers.

    Returns:
        The cached answer string, or None if no suitable match exists.
    """
    records = _load_db()
    best_sim = 0.0
    best_answer = None

    # Skip stale answers
    cutoff = (datetime.utcnow() - timedelta(days=max_age_days)).isoformat() if max_age_days else None

    for rec in records:
        if rec.get("rating") != "good":
            continue
        if cutoff and rec.get("timestamp", "") < cutoff:
            continue
        sim = _token_overlap(question, rec.get("question", ""))
        if sim >= threshold and sim > best_sim:
            best_sim = sim
            best_answer = rec.get("answer")

    if best_answer:
        logger.info("Feedback cache hit (similarity=%.2f)", best_sim)
    return best_answer



def get_retrieval_stats():
    """Aggregate statistics from the feedback database.

    Returns a dict with:
        - total: total feedback count
        - good / bad / pending counts
        - top_sources: most referenced source documents
        - query_type_breakdown: counts per query type
        - avg_confidence: average confidence across all records
    """
    records = _load_db()
    if not records:
        return {
            "total": 0,
            "good": 0,
            "bad": 0,
            "pending": 0,
            "top_sources": [],
            "query_type_breakdown": {},
            "avg_confidence": 0.0,
        }

    good = sum(1 for r in records if r.get("rating") == "good")
    bad = sum(1 for r in records if r.get("rating") == "bad")
    pending = sum(1 for r in records if r.get("rating") == "pending")

    source_counter = Counter()
    qt_counter = Counter()
    total_conf = 0.0

    for rec in records:
        for src in rec.get("sources", []):
            source_counter[src] += 1
        qt = rec.get("query_type", "unknown")
        if qt:
            qt_counter[qt] += 1
        total_conf += rec.get("confidence", 0.0)

    return {
        "total": len(records),
        "good": good,
        "bad": bad,
        "pending": pending,
        "top_sources": source_counter.most_common(10),
        "query_type_breakdown": dict(qt_counter),
        "avg_confidence": round(total_conf / len(records), 3) if records else 0.0,
    }


def learn_from_feedback():
    """Analyze feedback to produce learning insights.

    Returns a dict with:
        - preferred_sources: question pattern -> best source documents
        - failed_queries: queries that consistently fail (bad rating)
        - term_associations: pairs of terms that users search together
    """
    records = _load_db()

    # -- preferred_sources --
    preferred_sources = {}
    source_by_qt = {}
    for rec in records:
        if rec.get("rating") != "good":
            continue
        qt = rec.get("query_type", "general")
        source_by_qt.setdefault(qt, Counter())
        for src in rec.get("sources", []):
            source_by_qt[qt][src] += 1

    for qt, counter in source_by_qt.items():
        preferred_sources[qt] = [src for src, _ in counter.most_common(3)]

    # -- failed_queries --
    fail_counter = Counter()
    for rec in records:
        if rec.get("rating") == "bad":
            fail_counter[rec.get("question", "")] += 1
    failed_queries = [q for q, count in fail_counter.items() if count >= 1]

    # -- term_associations --
    term_pairs = Counter()
    for rec in records:
        tokens = sorted(_tokenize(rec.get("question", "")))
        for i, t1 in enumerate(tokens):
            for t2 in tokens[i + 1:]:
                term_pairs[(t1, t2)] += 1

    # Keep only pairs seen more than once
    term_associations = [
        {"terms": list(pair), "count": count}
        for pair, count in term_pairs.most_common(20)
        if count >= 2
    ]

    result = {
        "preferred_sources": preferred_sources,
        "failed_queries": failed_queries,
        "term_associations": term_associations,
    }
    logger.info(
        "Learning complete: %d preferred source groups, %d failed queries, "
        "%d term associations",
        len(preferred_sources), len(failed_queries), len(term_associations),
    )
    return result
