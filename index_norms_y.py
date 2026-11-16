# -*- coding: utf-8 -*-
"""
index_norms_y.py
================
Script d'indexation massive des Normes Algériennes (Y:\01-Normes Algériennes)
et Internationales (Y:\02-Normes Internationales) dans la base de données ARKAN
(ChromaDB + BM25 + Knowledge DB).
"""

import sys
import os
import time
import json
import logging
from pathlib import Path

sys.path.insert(0, "d:/DATA BASE IA")
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "false"

import fitz  # PyMuPDF
from config import (
    CHROMA_PATH,
    CHROMA_COLLECTION,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    EMBEDDING_MODEL,
    EMBEDDING_DIM
)
from indexer import adaptive_chunk, tokenize_for_bm25, get_embedding, _validate_embedding
import chromadb

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("IndexNormsY")

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx", ".rtf", ".html", ".htm"}


def extract_text_from_file(file_path: Path) -> str:
    """Extrait le texte d'un fichier (PDF via PyMuPDF, TXT/MD/RTF/HTML via IO)."""
    ext = file_path.suffix.lower()
    text = ""
    try:
        if ext == ".pdf":
            with fitz.open(file_path) as doc:
                pages_text = []
                for page in doc:
                    pages_text.append(page.get_text())
                text = "\n".join(pages_text)
        elif ext in (".txt", ".md", ".rtf", ".html", ".htm"):
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        elif ext == ".docx":
            try:
                import docx
                doc = docx.Document(file_path)
                text = "\n".join([p.text for p in doc.paragraphs])
            except Exception:
                text = ""
    except Exception as e:
        logger.warning(f"Erreur d'extraction sur {file_path.name}: {e}")
    return text.strip()


def run_norms_indexing(target_folders: list = None, max_files_per_category: int = None):
    start_time = time.time()
    logger.info("=== DÉMARRAGE DE L'INDEXATION DES NORMES Y:\\ ===")

    folders_to_scan = target_folders or [
        Path("Y:/01-Normes Algériennes"),
        Path("Y:/02-Normes Internationales")
    ]

    # Connexion ChromaDB
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = chroma_client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"}
    )

    total_files_scanned = 0
    total_chunks_added = 0
    errors = 0

    for folder in folders_to_scan:
        folder = Path(folder)
        if not folder.exists():
            logger.warning(f"Dossier non trouvé: {folder}")
            continue

        cat_name = folder.name
        logger.info(f"Analyse du répertoire : {cat_name}")

        files = [f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS]
        logger.info(f"  Total fichiers éligibles dans {cat_name} : {len(files)}")

        if max_files_per_category and len(files) > max_files_per_category:
            files = files[:max_files_per_category]
            logger.info(f"  Limité à {max_files_per_category} fichiers pour ce run.")

        batch_ids = []
        batch_documents = []
        batch_metadatas = []
        batch_embeddings = []

        for i, file_path in enumerate(files, 1):
            total_files_scanned += 1
            rel_path = str(file_path.relative_to(folder))
            doc_name = file_path.name

            text = extract_text_from_file(file_path)
            if not text or len(text) < 50:
                continue

            chunks = adaptive_chunk(text, base_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
            sub_folder = file_path.parent.name

            for chunk_idx, chunk in enumerate(chunks):
                if len(chunk.strip()) < 30:
                    continue

                emb = get_embedding(chunk)
                if not emb or len(emb) != 768:
                    continue

                doc_id = f"norm_{file_path.stem[:30]}_{chunk_idx}_{hash(chunk) & 0xffffffff:08x}"
                metadata = {
                    "source": str(file_path),
                    "file_name": doc_name,
                    "category": cat_name,
                    "subfolder": sub_folder,
                    "chunk_index": chunk_idx,
                    "total_chunks": len(chunks),
                    "is_norm": True
                }

                batch_ids.append(doc_id)
                batch_documents.append(chunk)
                batch_metadatas.append(metadata)
                batch_embeddings.append(emb)

                # Batch write tous les 100 chunks
                if len(batch_ids) >= 100:
                    try:
                        collection.upsert(
                            ids=batch_ids,
                            documents=batch_documents,
                            metadatas=batch_metadatas,
                            embeddings=batch_embeddings
                        )
                        total_chunks_added += len(batch_ids)
                    except Exception as e:
                        logger.error(f"Erreur d'insertion batch ChromaDB: {e}")
                        errors += 1
                    batch_ids, batch_documents, batch_metadatas, batch_embeddings = [], [], [], []

            time.sleep(0.02)
            if i % 25 == 0:
                logger.info(f"  Progression {cat_name}: {i}/{len(files)} fichiers traités ({total_chunks_added} chunks indexés)")

        # Flush restants
        if batch_ids:
            try:
                collection.upsert(
                    ids=batch_ids,
                    documents=batch_documents,
                    metadatas=batch_metadatas,
                    embeddings=batch_embeddings
                )
                total_chunks_added += len(batch_ids)
            except Exception as e:
                logger.error(f"Erreur d'insertion batch final ChromaDB: {e}")
                errors += 1

    elapsed = round((time.time() - start_time) / 60, 2)
    logger.info("=== INDEXATION DES NORMES TERMINÉE ===")
    logger.info(f"Fichiers scannés : {total_files_scanned}")
    logger.info(f"Chunks indexés   : {total_chunks_added}")
    logger.info(f"Temps écoulé     : {elapsed} min")

    return {
        "files_scanned": total_files_scanned,
        "chunks_indexed": total_chunks_added,
        "elapsed_min": elapsed,
        "errors": errors
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=str, default=None, help="Chemin du dossier spécifique à indexer (ex: Y:\\01-Normes Algériennes)")
    parser.add_argument("--limit", type=int, default=None, help="Limite le nombre de fichiers par dossier")
    args = parser.parse_args()

    targets = [Path(args.folder)] if args.folder else None
    res = run_norms_indexing(target_folders=targets, max_files_per_category=args.limit)
    print(json.dumps(res, indent=2))
