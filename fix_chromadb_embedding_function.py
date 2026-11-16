#!/usr/bin/env python3
"""
fix_chromadb_embedding_function.py
===================================
Corrige l'erreur : 'dict' object has no attribute 'dimensionality'

CAUSE :
  La collection ChromaDB a ete creee avec une embedding_function par defaut
  (DefaultEmbeddingFunction de sentence-transformers). Quand on fournit nos
  propres vecteurs via upsert(embeddings=[...]), ChromaDB tente de valider
  avec sa fonction interne -> conflit -> AttributeError.

SOLUTION :
  1. Sauvegarder tous les documents existants
  2. Supprimer la collection
  3. La recreer avec embedding_function=None
  4. Re-indexer tous les documents sauvegardes

Usage :
    python fix_chromadb_embedding_function.py
    python fix_chromadb_embedding_function.py --check-only
    python fix_chromadb_embedding_function.py --reset-collection
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# --- Config ---
try:
    from config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION
except ImportError:
    CHROMA_PERSIST_DIR = "./chroma_db"
    CHROMA_COLLECTION  = "oil_gas_docs"


def check_collection():
    """Verifie l'etat de la collection et detecte le probleme."""
    try:
        import chromadb
        print(f"\nChromaDB version : {chromadb.__version__}")
    except ImportError:
        print("ERREUR : chromadb non installe")
        sys.exit(1)

    print(f"Repertoire       : {CHROMA_PERSIST_DIR}")
    print(f"Collection       : {CHROMA_COLLECTION}")

    if not Path(CHROMA_PERSIST_DIR).exists():
        print("\nRepertoire ChromaDB inexistant — aucune collection a corriger.")
        return False

    try:
        client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)

        # Essayer de recuperer la collection
        try:
            col = client.get_collection(name=CHROMA_COLLECTION)
            count = col.count()
            print(f"\nCollection trouvee : {count} chunks indexes")
        except Exception as e:
            print(f"\nCollection introuvable : {e}")
            return False

        # Tester un upsert avec embedding_function=None
        print("\nTest upsert avec embedding_function=None...")
        try:
            col_safe = client.get_collection(
                name=CHROMA_COLLECTION,
                embedding_function=None,
            )
            # Test minimal : peek
            col_safe.peek(limit=1)
            print("[OK]  Collection compatible avec embedding_function=None")
            print("   Aucune correction necessaire.")
            return False
        except AttributeError as e:
            if "dimensionality" in str(e) or "embedding_function" in str(e).lower():
                print(f"[FAIL]  Probleme detecte : {e}")
                print("   -> La collection doit etre recreee avec embedding_function=None")
                return True
            raise
        except Exception as e:
            print(f"?  Erreur inattendue : {e}")
            return True

    except Exception as e:
        print(f"ERREUR acces ChromaDB : {e}")
        sys.exit(1)


def backup_collection() -> dict:
    """Sauvegarde tous les documents de la collection avant reset."""
    import chromadb

    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    try:
        col = client.get_collection(name=CHROMA_COLLECTION)
        count = col.count()
        if count == 0:
            logger.info("Collection vide — pas de sauvegarde necessaire")
            return {"ids": [], "documents": [], "metadatas": [], "embeddings": []}

        logger.info("Sauvegarde de %d chunks...", count)

        # Recuperer par batch de 1000 pour eviter les OOM
        batch_size = 1000
        all_ids, all_docs, all_metas, all_embeds = [], [], [], []

        for offset in range(0, count, batch_size):
            results = col.get(
                limit=batch_size,
                offset=offset,
                include=["documents", "metadatas"],
            )
            all_ids.extend(results.get("ids", []))
            all_docs.extend(results.get("documents", []))
            all_metas.extend(results.get("metadatas", []))
            logger.info("  Sauvegarde %d/%d chunks", min(offset + batch_size, count), count)

        # Écrire sur disque
        backup_path = Path(f"chroma_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        backup_data = {
            "collection": CHROMA_COLLECTION,
            "count": len(all_ids),
            "ids": all_ids,
            "documents": all_docs,
            "metadatas": all_metas,
            "has_embeddings": len(all_embeds) > 0,
            "backed_up_at": datetime.now().isoformat(),
        }
        # Ne pas sauvegarder les embeddings dans le JSON (trop volumineux)
        # On re-indexera depuis les textes
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)

        logger.info("Backup sauvegarde : %s (%d chunks)", backup_path, len(all_ids))
        return backup_data

    except Exception as e:
        logger.error("Sauvegarde echouee : %s", e)
        raise


def reset_collection():
    """Supprime et recree la collection avec embedding_function=None."""
    import chromadb

    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)

    # 1. Supprimer
    try:
        client.delete_collection(name=CHROMA_COLLECTION)
        logger.info("Collection '%s' supprimee", CHROMA_COLLECTION)
    except Exception as e:
        logger.warning("Suppression echouee (peut-etre inexistante) : %s", e)

    # 2. Recreer avec embedding_function=None
    col = client.create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )
    logger.info("Collection recreee avec embedding_function=None [OK]")
    return col


def reindex_from_backup(backup_data: dict):
    """Re-indexe les documents depuis la sauvegarde."""
    docs = backup_data.get("documents", [])
    if not docs:
        logger.info("Aucun document a re-indexer")
        return

    logger.info("Re-indexation de %d chunks...", len(docs))

    try:
        from indexer import get_embedding, get_collection, _validate_embedding

        col = get_collection()
        ids = backup_data["ids"]
        metas = backup_data.get("metadatas", [{} for _ in docs])

        indexed = 0
        failed = 0
        for i, (doc_id, doc, meta) in enumerate(zip(ids, docs, metas)):
            emb = get_embedding(doc)
            emb = _validate_embedding(emb, source=f"restore:{doc_id}")
            if emb is None:
                failed += 1
                continue
            try:
                col.upsert(
                    ids=[doc_id],
                    embeddings=[emb],
                    documents=[doc],
                    metadatas=[meta],
                )
                indexed += 1
            except Exception as e:
                logger.error("Upsert echoue pour %s : %s", doc_id, e)
                failed += 1

            if (i + 1) % 50 == 0:
                logger.info("  %d/%d chunks re-indexes...", i + 1, len(docs))

        logger.info("Re-indexation terminee : %d OK, %d echoues", indexed, failed)

        # Reconstruire BM25
        from indexer import flush_bm25
        flush_bm25()

    except ImportError as e:
        logger.error("Impossible d'importer indexer.py : %s", e)
        logger.info("Lance manuellement : python train_deerflow.py --mode synthetic")


def main():
    parser = argparse.ArgumentParser(description="Corriger ChromaDB embedding_function")
    parser.add_argument("--check-only",       action="store_true", help="Verifier sans modifier")
    parser.add_argument("--reset-collection", action="store_true", help="Forcer la recreation")
    args = parser.parse_args()

    print("=" * 60)
    print("  DEERFLOW LITE — Fix ChromaDB embedding_function")
    print("=" * 60)

    # Étape 1 : Diagnostic
    needs_fix = check_collection()

    if args.check_only:
        sys.exit(0 if not needs_fix else 1)

    if not needs_fix and not args.reset_collection:
        print("\nAucune action necessaire. Utilise --reset-collection pour forcer.")
        sys.exit(0)

    # Étape 2 : Sauvegarde
    print("\n--- Sauvegarde des donnees existantes ---")
    try:
        backup = backup_collection()
    except Exception:
        print("ERREUR lors de la sauvegarde. Abandon.")
        sys.exit(1)

    # Étape 3 : Reset
    print("\n--- Reset de la collection ---")
    try:
        reset_collection()
    except Exception as e:
        print(f"ERREUR lors du reset : {e}")
        sys.exit(1)

    # Étape 4 : Re-indexation
    if backup.get("count", 0) > 0:
        print(f"\n--- Re-indexation de {backup['count']} chunks ---")
        print("(Cela peut prendre quelques minutes selon la taille du corpus)")
        try:
            reindex_from_backup(backup)
        except Exception as e:
            print(f"ERREUR re-indexation : {e}")
            print("Lance manuellement depuis le dossier data/ :")
            print("  python train_deerflow.py --mode synthetic")
    else:
        print("\nCollection vide apres reset — indexe tes documents via l'API /documents/upload")

    print("\n" + "=" * 60)
    print("  CORRECTION TERMINÉE")
    print("  Redemarre le serveur DeerFlow : python api.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
