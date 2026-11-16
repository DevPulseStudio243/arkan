# ============================================================
#  DEERFLOW LITE - Database Venv Cleanup Script
#  Prunes ChromaDB and BM25 indexes by removing .venv files.
# ============================================================

import sys
import os
from pathlib import Path

# Setup path and working directory
sys.path.insert(0, "d:/DATA BASE IA")
os.chdir("d:/DATA BASE IA")

# Configure logging
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("clean_database_venv")

try:
    from indexer import get_collection, _rebuild_bm25, flush_bm25
    from config import CHROMA_COLLECTION, CHROMA_MODE, CHROMA_HOST, CHROMA_PORT
except ImportError as e:
    logger.error("Could not import required modules. Make sure you run this script from the project root. Error: %s", e)
    sys.exit(1)

def main():
    logger.info("Connecting to ChromaDB collection '%s'...", CHROMA_COLLECTION)
    logger.info("ChromaDB Mode: %s (Host: %s, Port: %s)", CHROMA_MODE, CHROMA_HOST, CHROMA_PORT)
    
    collection = get_collection()
    if not collection:
        logger.error("Failed to connect to ChromaDB collection.")
        sys.exit(1)
        
    logger.info("Successfully connected to ChromaDB. Fetching all items...")
    
    # Fetch all items with their metadatas
    try:
        results = collection.get(include=["metadatas"])
    except Exception as e:
        logger.error("Error fetching items from ChromaDB: %s", e)
        sys.exit(1)
        
    metadatas = results.get("metadatas", [])
    ids = results.get("ids", [])
    
    if not ids:
        logger.info("No items found in ChromaDB.")
        return
        
    logger.info("Found %d total chunks in ChromaDB. Scanning for virtual environment files...", len(ids))
    
    ids_to_delete = []
    sources_to_delete = set()
    
    for i, meta in enumerate(metadatas):
        if not meta:
            continue
        source = meta.get("source", "")
        if not source:
            continue
            
        # Check if source path contains any virtual env indicators
        source_lower = str(source).lower()
        if any(indicator in source_lower for indicator in [".venv", "\\venv\\", "/venv/", "site-packages", "dist-info"]):
            ids_to_delete.append(ids[i])
            sources_to_delete.add(source)
            
    if not ids_to_delete:
        logger.info("Success! No virtual environment chunks found in ChromaDB. Clean database.")
        return
        
    logger.info("Identified %d chunks to delete, belonging to %d unique virtual environment files.", len(ids_to_delete), len(sources_to_delete))
    logger.info("Sample files to be deleted:")
    for s in sorted(list(sources_to_delete))[:10]:
        logger.info(" - %s", s)
        
    # Ask for dry-run or proceed (since this runs non-interactively, we proceed directly)
    logger.info("Proceeding to delete %d chunks from ChromaDB...", len(ids_to_delete))
    
    # Delete in batches of 100 to avoid request size limits or long locks
    batch_size = 100
    deleted_count = 0
    for idx in range(0, len(ids_to_delete), batch_size):
        batch_ids = ids_to_delete[idx:idx + batch_size]
        try:
            collection.delete(ids=batch_ids)
            deleted_count += len(batch_ids)
            logger.info("Deleted %d/%d chunks...", deleted_count, len(ids_to_delete))
        except Exception as e:
            logger.error("Error deleting batch starting at index %d: %s", idx, e)
            
    logger.info("ChromaDB deletion complete. %d chunks deleted.", deleted_count)
    
    # Rebuild BM25 index
    logger.info("Rebuilding BM25 index from remaining ChromaDB contents...")
    try:
        _rebuild_bm25()
        logger.info("BM25 index successfully rebuilt.")
    except Exception as e:
        logger.error("Error rebuilding BM25: %s", e)
        
    logger.info("Database prune complete! Remaining chunks in database: %d", len(collection.get(include=[])["ids"]))

if __name__ == "__main__":
    main()
