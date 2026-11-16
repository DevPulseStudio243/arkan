# ============================================================
#  DEERFLOW LITE - Auto Indexer
#  Watches the data folder and auto-indexes new/modified files.
# ============================================================

import os
import time
import logging
import threading
from pathlib import Path

from config import DATA_PATH, EXTENSIONS

logger = logging.getLogger(__name__)

# Directories to always skip during scanning
_EXCLUDED_DIRS = {
    ".venv", "venv", "__pycache__", ".git", "node_modules",
    ".tox", ".mypy_cache", ".pytest_cache", "env", ".env",
    "site-packages", "dist-info", "procurement_contracts",
}


# -- Debounce helper ---------------------------------------

class _Debouncer:
    """Simple debounce mechanism: delays action until *delay* seconds
    after the last call for a given key."""

    def __init__(self):
        self._timers = {}
        self._lock = threading.Lock()

    def call(self, key, func, delay=3.0):
        """Schedule *func* to run after *delay* seconds.
        Resets the timer if called again for the same *key* before firing."""
        with self._lock:
            existing = self._timers.get(key)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(delay, func)
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def cancel_all(self):
        """Cancel all pending timers."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()


# -- Event handler (watchdog) ------------------------------

def _make_handler(auto_indexer):
    """Create a watchdog FileSystemEventHandler bound to *auto_indexer*.

    We import watchdog lazily so the module can be imported even when
    watchdog is not installed (tests can still run partially).
    """
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        """Watchdog handler that delegates to AutoIndexer methods."""

        def on_created(self, event):
            """Handle file creation events."""
            if not event.is_directory:
                auto_indexer.on_file_created(event.src_path)

        def on_modified(self, event):
            """Handle file modification events."""
            if not event.is_directory:
                auto_indexer.on_file_modified(event.src_path)

        def on_deleted(self, event):
            """Handle file deletion events."""
            if not event.is_directory:
                auto_indexer.on_file_deleted(event.src_path)

    return _Handler()


# -- AutoIndexer class -------------------------------------

class AutoIndexer:
    """Watches a data directory and auto-indexes new or modified files.

    Integrates with the indexer and knowledge_graph modules so that
    every indexed document is also added to the graph.
    """

    def __init__(self, data_path=None, extensions=None):
        """Initialise the auto-indexer.

        Args:
            data_path: Directory to watch.  Defaults to config DATA_PATH.
            extensions: Set of file extensions to index.
                        Defaults to config EXTENSIONS.
        """
        self.data_path = data_path or DATA_PATH
        self.extensions = extensions or EXTENSIONS
        self._observer = None
        self._debouncer = _Debouncer()
        self._stats = {
            "indexed": 0,
            "re_indexed": 0,
            "deleted": 0,
            "errors": 0,
            "total_files_found": 0,
            "last_event": None,
        }
        self._stats_lock = threading.Lock()
        self._indexed_files = {}  # path -> mtime
        self._start_time_turbo = time.time()
        self._indexed_count_turbo = 0
        self._speed_docs_per_min = 0.0

    # -- Lifecycle -----------------------------------------

    def start(self):
        """Start the filesystem watcher."""
        try:
            from watchdog.observers import Observer
        except ImportError:
            logger.error(
                "watchdog is not installed -- auto-indexing disabled. "
                "Install with: pip install watchdog"
            )
            return

        if self._observer is not None:
            logger.warning("AutoIndexer already running")
            return

        path = Path(self.data_path)
        if not path.exists():
            logger.warning("Data path does not exist: %s", self.data_path)
            return

        handler = _make_handler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(path), recursive=True)
        self._observer.daemon = True
        self._observer.start()
        logger.info("AutoIndexer started -- watching %s", self.data_path)

    def stop(self):
        """Stop the filesystem watcher."""
        self._debouncer.cancel_all()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            logger.info("AutoIndexer stopped")

    # -- File event handlers -------------------------------

    def _is_supported(self, path):
        """Check whether *path* has a supported extension and is not in an excluded directory."""
        p = Path(path)
        ext = p.suffix.lower()
        if ext not in self.extensions:
            return False
        # Skip files inside excluded directories
        parts = p.parts
        for part in parts:
            if part.lower() in _EXCLUDED_DIRS:
                return False
        return True

    def on_file_created(self, path):
        """Handle a newly created file.  Debounced to avoid rapid re-fires."""
        if not self._is_supported(path):
            return
        logger.info("File created: %s", path)
        self._debouncer.call(path, lambda: self._index_file(path, is_new=True))

    def on_file_modified(self, path):
        """Handle a modified file.  Debounced."""
        if not self._is_supported(path):
            return
        logger.info("File modified: %s", path)
        self._debouncer.call(path, lambda: self._index_file(path, is_new=False))

    def on_file_deleted(self, path):
        """Handle a deleted file.  Removes chunks from the index."""
        if not self._is_supported(path):
            return
        logger.info("File deleted: %s", path)
        self._remove_from_index(path)
        with self._stats_lock:
            self._stats["deleted"] += 1
            self._stats["last_event"] = "deleted: %s" % path
        self._indexed_files.pop(os.path.abspath(path).lower(), None)
        self._indexed_files.pop(path, None)

    def _remove_from_index(self, path):
        """Remove all chunks for a deleted source from the index."""
        try:
            from indexer import get_collection, _rebuild_bm25
            collection = get_collection()
            if collection:
                source_name = str(path)
                results = collection.get(where={"source": source_name}, include=[])
                if results and results.get("ids"):
                    collection.delete(ids=results["ids"])
                    logger.info("Deleted %d chunks for %s from index", len(results["ids"]), path)
                    try:
                        _rebuild_bm25()
                    except Exception:
                        pass
        except Exception as e:
            logger.error("Error removing %s from index: %s", path, e)

    # -- Indexing logic ------------------------------------

    def _index_file(self, path, is_new=True):
        """Index a single file and add it to the knowledge graph."""
        try:
            from extractors import extract_file
            from indexer import index_document, get_collection
            from classifier import classify_document_ml, classify_document
            from entities import extract_entities, save_to_kb
            from knowledge_graph import add_document_to_graph

            # For modified files, remove old chunks first
            if not is_new:
                try:
                    collection = get_collection()
                    if collection:
                        old = collection.get(where={"source": str(path)}, include=[])
                        if old and old.get("ids"):
                            collection.delete(ids=old["ids"])
                            logger.info("Removed %d old chunks for %s before re-indexing", len(old["ids"]), path)
                except Exception as e:
                    logger.warning("Could not remove old chunks for %s: %s", path, e)

            extraction = extract_file(path)
            text = extraction.get("text", "")
            if not text.strip():
                logger.warning("No text extracted from %s", path)
                return

            filename = Path(path).name

            try:
                classification = classify_document_ml(text, filename=filename)
            except Exception as _e:
                logger.warning("Classifieur ML indisponible, fallback règles: %s", _e)
                classification = classify_document(text, filename=filename)
            entities = extract_entities(text)
            save_to_kb(entities, source_file=filename, context_snippet=text[:500])

            metadata = {
                "discipline": classification["discipline"],
                "confidence": classification["confidence"],
                "format": extraction.get("format", "unknown"),
                "pages": extraction.get("pages", 0),
            }
            chunks = index_document(text, metadata, source=path)

            # ──────────────────────────────────────────────────────────────
            # Enrichissement Knowledge Graph
            #   1. Extraction rapide par Regex (tags, normes) — toujours
            #   2. Extraction intelligente par LLM (GraphRAG) — si Neo4j dispo
            # ──────────────────────────────────────────────────────────────
            try:
                from verification_extractors import resolve_project_for_file
                proj_info = resolve_project_for_file(Path(path))
                p_id = proj_info.get("project_id", "general")
            except Exception:
                p_id = "general"
            add_document_to_graph(filename, text, project_id=p_id)

            try:
                from knowledge_graph import get_neo4j_kg
                kg = get_neo4j_kg()
                if kg.disponible():
                    # N'appeler le LLM que sur les 4000 premiers caractères
                    # pour limiter la latence (le reste est capturé par le Regex)
                    kg.enrichir_graphe_depuis_llm(str(path), text[:4000])
            except Exception as _eg:
                logger.warning("GraphRAG LLM enrichment skipped for %s: %s", filename, _eg)

            if is_new:
                with self._stats_lock:
                    self._stats["indexed"] += 1
            else:
                with self._stats_lock:
                    self._stats["re_indexed"] += 1

            with self._stats_lock:
                self._stats["last_event"] = "indexed: %s (%d chunks)" % (filename, chunks)
            self._indexed_files[os.path.abspath(path).lower()] = os.path.getmtime(path)
            self._indexed_count_turbo += 1
            
            # Calculer la vitesse moyenne (docs/min)
            elapsed = (time.time() - self._start_time_turbo) / 60.0
            if elapsed > 0.01: # Eviter division par zéro
                self._speed_docs_per_min = self._indexed_count_turbo / elapsed
            
            logger.info("Indexed %s: %d chunks (Speed: %.1f docs/min)", filename, chunks, self._speed_docs_per_min)

            # Invalider le cache embedding du retriever (nouveaux docs disponibles)
            try:
                from retriever import get_retriever
                retriever = get_retriever()
                if retriever._initialized:
                    retriever.invalidate_cache()
            except Exception:
                pass

            # Déclencher l'auto-apprentissage si ce n'est pas un scan en lot (scan_all s'en charge à la fin)
            if not getattr(self, "in_scan_all", False):
                self.trigger_synonym_learning()

        except Exception as exc:
            with self._stats_lock:
                self._stats["errors"] += 1
                self._stats["last_event"] = "error: %s -- %s" % (path, exc)
            logger.error("Error indexing %s: %s", path, exc)

    # -- Full scan -----------------------------------------

    def scan_all(self, force=False):
        """Scan the entire data_path and index any un-indexed files.

        Args:
            force: If True, re-index all files regardless of mtime.
        """
        data_dir = Path(self.data_path)
        if not data_dir.exists():
            logger.warning("Data path does not exist: %s", self.data_path)
            return

        if not self._indexed_files:
            try:
                from indexer import get_collection
                col = get_collection()
                if col:
                    res = col.get(include=["metadatas"])
                    metas = res.get("metadatas", []) or []
                    for meta in metas:
                        src = meta.get("source")
                        if src and os.path.exists(src):
                            norm_src = os.path.abspath(src).lower()
                            try:
                                self._indexed_files[norm_src] = os.path.getmtime(src)
                            except OSError:
                                self._indexed_files[norm_src] = 1.0
                    logger.info("Loaded %d indexed files from ChromaDB metadata", len(self._indexed_files))
            except Exception as e:
                logger.warning("Could not load indexed files from ChromaDB: %s", e)

        files_to_index = []
        for root, dirs, files in os.walk(str(data_dir)):
            dirs[:] = [d for d in dirs if d.lower() not in _EXCLUDED_DIRS]
            for fname in files:
                fpath = os.path.join(root, fname)
                if not self._is_supported(fpath):
                    continue
                try:
                    mtime = os.path.getmtime(fpath)
                except OSError:
                    continue
                prev_mtime = self._indexed_files.get(os.path.abspath(fpath).lower(), 0)
                if force or mtime > prev_mtime:
                    files_to_index.append((fpath, prev_mtime == 0))

        with self._stats_lock:
            self._stats["total_files_found"] = len(files_to_index) + len(self._indexed_files)

        if not files_to_index:
            logger.info("Full scan complete: no new files to index.")
            return 0

        logger.info("Full scan: %d files to index (sequential to protect ChromaDB)", len(files_to_index))
        
        self.in_scan_all = True
        count = 0
        try:
            import concurrent.futures
            from knowledge_graph import batch_mode
            with batch_mode():
                # max_workers=1: ChromaDB PersistentClient is NOT thread-safe for concurrent writes
                # (causes SIGSEGV / 0xC0000005 on Windows). Serialize all indexing operations.
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future_to_file = {
                        executor.submit(self._index_file, fpath, is_new): fpath 
                        for fpath, is_new in files_to_index
                    }
                    for future in concurrent.futures.as_completed(future_to_file):
                        try:
                            future.result()
                            count += 1
                        except Exception as e:
                            fpath = future_to_file[future]
                            logger.error(f"Failed to index {fpath} during scan: {e}")
        finally:
            self.in_scan_all = False

        logger.info("Full scan complete: %d files processed", count)

        # Reconstruire BM25 UNE SEULE FOIS après le scan complet (évite O(n²))
        if count > 0:
            try:
                from indexer import flush_bm25
                flush_bm25()
            except Exception as e:
                logger.warning("flush_bm25 après scan_all échoué: %s", e)

            # Déclencher la découverte automatique de synonymes sur le corpus complet
            self.trigger_synonym_learning()

        return count

    def trigger_synonym_learning(self):
        """Récupère tous les documents de ChromaDB et déclenche la découverte automatique de synonymes."""
        try:
            from indexer import get_collection
            from vocabulary import learn_synonyms_from_corpus
            col = get_collection()
            if col:
                res = col.get(include=["documents"])
                documents = res.get("documents", []) or []
                # Filtrer les textes valides
                valid_docs = [doc for doc in documents if doc and len(doc.strip()) > 50]
                if valid_docs:
                    logger.info("Déclenchement de l'apprentissage automatique de synonymes sur %d textes...", len(valid_docs))
                    learn_synonyms_from_corpus(valid_docs, min_cooccurrence=2)
                else:
                    logger.debug("Aucun document valide trouvé pour l'apprentissage de synonymes.")
        except Exception as e:
            logger.error("Échec de l'auto-apprentissage de synonymes : %s", e)

    # -- Status --------------------------------------------

    def get_status(self):
        """Return indexing statistics.

        Returns:
            A dict with indexed, re_indexed, deleted, errors counts and
            the last event description.
        """
        return {
            "running": self._observer is not None,
            "data_path": self.data_path,
            "extensions": sorted(self.extensions),
            "tracked_files": len(self._indexed_files),
            "speed_docs_per_min": round(self._speed_docs_per_min, 2),
            **self._stats,
        }
