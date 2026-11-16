"""
COLIBRI Fast Sub-second Local RAG Engine v1.0
Moteur de Recherche Sémantique et Contextuelle Ultra-Rapide (< 80ms) pour ARKAN.
Exécution 100% Locale et Hors-Ligne (Offline).
"""

import os
import sys
import time
import json
import re
import math
import logging
from typing import List, Dict, Any

logger = logging.getLogger("colibri_rag")
logging.basicConfig(level=logging.INFO)

class ColibriFastRAG:
    def __init__(self, data_dir: str = "d:/DATA BASE IA/data"):
        self.data_dir = data_dir
        self.documents = []
        self.vocabulary = {}
        self.idf = {}
        self.indexed = False
        self.build_index()

    def _tokenize(self, text: str) -> List[str]:
        text_clean = re.sub(r"[^\w\s\-\.]", " ", text.lower())
        tokens = [t for t in text_clean.split() if len(t) > 2]
        return tokens

    def build_index(self):
        start_time = time.time()
        docs = []
        doc_id = 0

        # Scan root markdown/txt files
        base_dir = "d:/DATA BASE IA"
        for fname in os.listdir(base_dir):
            if fname.endswith((".md", ".txt", ".json")) and not fname.startswith("."):
                fpath = os.path.join(base_dir, fname)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        if len(content) > 50:
                            chunks = self._chunk_text(content, fname)
                            for c in chunks:
                                docs.append({
                                    "id": doc_id,
                                    "source": fname,
                                    "path": fpath,
                                    "text": c,
                                    "tokens": self._tokenize(c)
                                })
                                doc_id += 1
                    except Exception as e:
                        pass

        # Scan data/ directory
        if os.path.exists(self.data_dir):
            for root, dirs, files in os.walk(self.data_dir):
                for fname in files:
                    if fname.endswith((".md", ".txt", ".json", ".pdf", ".dwg", ".xer")) and not fname.startswith("."):
                        fpath = os.path.join(root, fname)
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                            if len(content) > 50:
                                chunks = self._chunk_text(content, fname)
                                for c in chunks:
                                    docs.append({
                                        "id": doc_id,
                                        "source": fname,
                                        "path": fpath,
                                        "text": c,
                                        "tokens": self._tokenize(c)
                                    })
                                    doc_id += 1
                        except Exception:
                            pass

        self.documents = docs
        total_docs = len(self.documents)

        # Build IDF
        doc_freq = {}
        for doc in self.documents:
            unique_tokens = set(doc["tokens"])
            for t in unique_tokens:
                doc_freq[t] = doc_freq.get(t, 0) + 1

        for t, freq in doc_freq.items():
            self.idf[t] = math.log((total_docs + 1) / (freq + 1)) + 1

        self.indexed = True
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"⚡ [COLIBRI RAG] Indexation de {total_docs} fragments documentaires terminée en {elapsed_ms:.1f} ms !")

    def _chunk_text(self, text: str, source: str, chunk_size: int = 600) -> List[str]:
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = ""

        for p in paragraphs:
            p_strip = p.strip()
            if not p_strip:
                continue
            if len(current_chunk) + len(p_strip) < chunk_size:
                current_chunk += "\n\n" + p_strip if current_chunk else p_strip
            else:
                if current_chunk:
                    chunks.append(f"[{source}] " + current_chunk)
                current_chunk = p_strip

        if current_chunk:
            chunks.append(f"[{source}] " + current_chunk)

        return chunks if chunks else [f"[{source}] " + text[:chunk_size]]

    def search(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        start_time = time.time()
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return {"results": [], "query": query, "latency_ms": 0.0}

        scores = []
        for doc in self.documents:
            score = 0.0
            doc_tokens = doc["tokens"]
            doc_len = len(doc_tokens)
            if doc_len == 0:
                continue

            for qt in query_tokens:
                count = doc_tokens.count(qt)
                if count > 0:
                    tf = count / doc_len
                    idf_val = self.idf.get(qt, 1.0)
                    score += tf * idf_val * 2.5

            # Bonus for exact keyword match in title / source
            if any(qt in doc["source"].lower() for qt in query_tokens):
                score += 1.5

            if score > 0:
                scores.append((score, doc))

        scores.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, doc in scores[:top_k]:
            results.append({
                "source": doc["source"],
                "path": doc["path"],
                "score": round(score, 4),
                "text": doc["text"][:400] + "..." if len(doc["text"]) > 400 else doc["text"]
            })

        latency_ms = (time.time() - start_time) * 1000
        logger.info(f"⚡ [COLIBRI RAG] Recherche '{query}' effectuée en {latency_ms:.2f} ms ({len(results)} résultats)")

        return {
            "query": query,
            "latency_ms": round(latency_ms, 2),
            "engine": "COLIBRI Sub-second RAG 100% Local",
            "results": results
        }


# Singleton Global Instance
_colibri_instance = None

def get_colibri_engine():
    global _colibri_instance
    if _colibri_instance is None:
        _colibri_instance = ColibriFastRAG()
    return _colibri_instance

if __name__ == "__main__":
    colibri = get_colibri_engine()
    res = colibri.search("Audit DCMA Lags et marges", top_k=3)
    print(json.dumps(res, indent=2, ensure_ascii=False))
