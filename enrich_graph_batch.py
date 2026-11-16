"""
Script de batch GraphRAG — Enrichissement LLM de tous les chunks ChromaDB existants.

Usage depuis Docker :
  docker exec deerflow-api python enrich_graph_batch.py

Options :
  --offset N    : Commencer à partir du Nième chunk (reprendre après interruption)
  --limit  N    : Nombre max de chunks à traiter (défaut: tous)
  --workers N   : Threads parallèles (défaut: 2, max recommandé: 4)
"""
import sys
import os
import time
import logging
import argparse
import threading
from queue import Queue

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/app/logs/graphrag_batch.log", encoding="utf-8")
        if os.path.isdir("/app/logs") else logging.StreamHandler()
    ]
)
logger = logging.getLogger("graphrag_batch")


def parse_args():
    parser = argparse.ArgumentParser(description="GraphRAG Batch Enricher")
    parser.add_argument("--offset",  type=int, default=0,    help="Chunk offset de départ")
    parser.add_argument("--limit",   type=int, default=0,    help="Nombre max de chunks (0=tous)")
    parser.add_argument("--workers", type=int, default=2,    help="Threads parallèles")
    parser.add_argument("--batch",   type=int, default=100,  help="Taille d'un batch ChromaDB")
    return parser.parse_args()


def worker(queue: Queue, kg, stats: dict, lock: threading.Lock):
    """Worker thread: consomme les items de la queue et enrichit Neo4j."""
    while True:
        item = queue.get()
        if item is None:
            break
        idx, source, text = item
        try:
            # Extraction LLM unique (évite le double appel dans enrichir_graphe_depuis_llm)
            data = kg.extraire_entites_llm(text[:4000])
            has_data = bool(
                data.get("equipments") or data.get("properties")
                or data.get("connections") or data.get("norms")
            )
            if has_data:
                result = kg.enrichir_graphe_depuis_llm(source, text, prefetched_data=data)
            else:
                result = False

            with lock:
                if result:
                    stats["success"] += 1
                elif has_data:
                    stats["errors"] += 1
                else:
                    stats["empty"] += 1
                stats["done"] += 1
                done  = stats["done"]
                total = stats["total"]
                pct   = done / total * 100 if total > 0 else 0
                if done % 10 == 0 or done == total:
                    elapsed   = time.time() - stats["start"]
                    rate      = done / elapsed * 60 if elapsed > 0 else 0
                    remaining = (total - done) / (rate / 60) if rate > 0 else 0
                    logger.info(
                        f"Progression: {done}/{total} ({pct:.1f}%)"
                        f" | Enrichis: {stats['success']} | Vides: {stats['empty']}"
                        f" | Erreurs: {stats['errors']}"
                        f" | {rate:.1f}/min | ETA: {remaining/60:.1f}h"
                    )
        except Exception as e:
            with lock:
                stats["errors"] += 1
                stats["done"]   += 1
            logger.error(f"Erreur chunk {idx} ({source}): {e}")
        finally:
            queue.task_done()



def main():
    args = parse_args()

    logger.info("=" * 60)
    logger.info("GraphRAG Batch — Démarrage")
    logger.info(f"  offset={args.offset} | limit={args.limit} | workers={args.workers}")
    logger.info("=" * 60)

    # Connexion Neo4j
    from knowledge_graph import get_neo4j_kg
    kg = get_neo4j_kg()
    if not kg.disponible():
        logger.error("Neo4j non disponible. Abandon.")
        sys.exit(1)

    # Connexion ChromaDB
    from indexer import get_collection
    try:
        collection = get_collection()
    except Exception as e:
        logger.error(f"ChromaDB inaccessible: {e}")
        sys.exit(1)

    # Récupérer les IDs de sources uniques pour éviter doublons
    logger.info("Comptage des chunks dans ChromaDB...")
    total_in_db = collection.count()
    logger.info(f"Total chunks dans ChromaDB: {total_in_db}")

    # Stats
    stats = {
        "start": time.time(),
        "total": 0,
        "done": 0,
        "success": 0,
        "empty": 0,
        "errors": 0,
    }
    lock = threading.Lock()

    # Charger les chunks par batch pour éviter de surcharger la RAM
    queue = Queue(maxsize=args.workers * 4)
    offset = args.offset
    limit  = args.limit
    batch  = args.batch
    processed = 0

    # Démarrer les workers
    threads = []
    for i in range(args.workers):
        t = threading.Thread(
            target=worker,
            args=(queue, kg, stats, lock),
            name=f"Worker-{i+1}",
            daemon=True
        )
        t.start()
        threads.append(t)

    # Compter d'abord le total
    effective_total = (total_in_db - offset)
    if limit > 0:
        effective_total = min(effective_total, limit)
    with lock:
        stats["total"] = max(effective_total, 0)

    logger.info(f"Chunks à enrichir: {stats['total']}")
    if stats["total"] == 0:
        logger.info("Rien à traiter. Fin.")
        for _ in threads:
            queue.put(None)
        return

    # Alimenter la queue par batch
    current_offset = offset
    while True:
        if limit > 0 and processed >= limit:
            break

        fetch_size = batch
        if limit > 0:
            fetch_size = min(batch, limit - processed)

        try:
            docs = collection.get(
                limit=fetch_size,
                offset=current_offset,
                include=["documents", "metadatas"]
            )
        except Exception as e:
            logger.error(f"Erreur lecture ChromaDB offset={current_offset}: {e}")
            break

        texts = docs.get("documents", [])
        metas = docs.get("metadatas", []) or [{}] * len(texts)

        if not texts:
            break

        for i, (text, meta) in enumerate(zip(texts, metas)):
            source = meta.get("source", f"chunk_{current_offset + i}")
            queue.put((current_offset + i, source, text))
            processed += 1

        current_offset += len(texts)

        # Si on a tout chargé, on sort
        if len(texts) < fetch_size:
            break

    # Signal de fin pour chaque worker
    for _ in threads:
        queue.put(None)

    # Attendre la fin
    for t in threads:
        t.join()

    elapsed = time.time() - stats["start"]
    logger.info("=" * 60)
    logger.info("GraphRAG Batch — TERMINÉ")
    logger.info(f"  Total traités : {stats['done']}")
    logger.info(f"  Enrichis OK   : {stats['success']}")
    logger.info(f"  Vides (no data): {stats['empty']}")
    logger.info(f"  Erreurs        : {stats['errors']}")
    logger.info(f"  Durée totale   : {elapsed/60:.1f} min")

    # Stats Neo4j finales
    neo_stats = kg.get_stats()
    logger.info(f"Neo4j — Nœuds finaux: {neo_stats}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
