# ============================================================
#  DEERFLOW LITE - Script de Migration ChromaDB → LightRAG
#  Optimisation : Regroupement par document source pour
#  éviter l'indexation redondante par chunk.
# ============================================================

import os
import sys
import logging
from collections import defaultdict

# Configurer le logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("deerflow.migration")

# Ajouter le répertoire de travail
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from retriever import get_retriever
from lightrag_integration import get_lightrag

def run_migration(limit: int = 10, dry_run: bool = False):
    """
    Regroupe les chunks ChromaDB par document source et les indexe dans LightRAG.
    """
    logger.info("Connexion à ChromaDB...")
    retriever = get_retriever()
    retriever._init_chroma()
    collection = retriever._collection

    logger.info("Récupération de tous les chunks depuis ChromaDB...")
    try:
        # Charger tous les chunks (limite haute pour tout récupérer)
        data = collection.get(include=["documents", "metadatas"])
    except Exception as e:
        logger.error(f"Impossible de lire ChromaDB : {e}")
        return

    ids = data.get("ids", [])
    documents = data.get("documents", [])
    metadatas = data.get("metadatas", [])

    logger.info(f"Trouvé {len(ids)} chunks au total.")

    # Regrouper les chunks par source
    sources_chunks = defaultdict(list)
    for doc, meta in zip(documents, metadatas):
        if not meta:
            continue
        source = meta.get("source")
        if not source:
            continue
        
        # Ignorer les fichiers de l'environnement virtuel, git ou temporaires
        source_lower = source.lower()
        if any(x in source_lower for x in ("venv", ".git", ".pytest_cache", ".gemini", "node_modules", "license.txt")):
            continue
            
        chunk_index = int(meta.get("chunk_index", 0))
        sources_chunks[source].append((chunk_index, doc))

    logger.info(f"Trouvé {len(sources_chunks)} documents uniques après filtrage.")

    # Initialiser LightRAG
    lr = get_lightrag()
    if not lr.disponible():
        logger.error("LightRAG + Neo4j n'est pas disponible. Démarrer Neo4j d'abord.")
        return

    # Ordonner et reconstituer les documents
    sorted_sources = sorted(list(sources_chunks.keys()))
    
    count = 0
    for source in sorted_sources:
        if count >= limit:
            logger.info(f"Limite de {limit} documents atteinte. Fin de cette passe.")
            break

        # Trier les chunks par index pour reconstituer le texte dans l'ordre d'origine
        chunks_list = sorted(sources_chunks[source], key=lambda x: x[0])
        full_text = "\n\n".join(chunk_text for _, chunk_text in chunks_list)

        logger.info(f"[{count+1}/{limit}] Document : {os.path.basename(source)} ({len(chunks_list)} chunks, {len(full_text)} caractères)")

        if not dry_run:
            try:
                success = lr.insert_document(full_text)
                if success:
                    logger.info(f"✓ Indexation réussie dans LightRAG")
                else:
                    logger.warning(f"✗ Échec d'indexation dans LightRAG")
            except Exception as e:
                logger.error(f"Erreur d'insertion LightRAG pour {source} : {e}")
        else:
            logger.info("  [Mode DRY-RUN] Aucune insertion effectuée.")

        count += 1

    logger.info(f"Migration terminée. {count} documents traités.")

if __name__ == "__main__":
    # Paramètres par défaut : dry-run pour que l'utilisateur valide, limite 5 documents
    limit = 5
    dry_run = False
    
    # Lire les arguments
    if len(sys.argv) > 1:
        if sys.argv[1].lower() == "--dry-run":
            dry_run = True
        elif sys.argv[1].isdigit():
            limit = int(sys.argv[1])
            
    if len(sys.argv) > 2:
        if sys.argv[2].lower() == "--dry-run":
            dry_run = True
        elif sys.argv[2].isdigit():
            limit = int(sys.argv[2])

    logger.info(f"Lancement de la migration | Limite={limit} documents | Dry-Run={dry_run}")
    run_migration(limit=limit, dry_run=dry_run)
