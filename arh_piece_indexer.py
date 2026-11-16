"""
arh_piece_indexer.py — v1.0
===========================
Moteur d'Indexation Granulaire & Recherche Hybride par Pièce ARH (ChromaDB + GraphRAG).
Permet le chunking sémantique par pièce réglementaire (DOC-01 à DOC-14) et la recherche
ciblée sans bruit de fond avec filtrage par discipline et métadonnées techniques.
"""

from __future__ import annotations
import os
import json
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Any, Optional

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")

# Mappage des disciplines par code pièce
DISCIPLINE_MAP = {
    "DOC-00": "ADMINISTRATIF",
    "DOC-01": "ADMINISTRATIF",
    "DOC-02": "JURIDIQUE",
    "DOC-03": "INSPECTION",
    "DOC-04": "CONFORMITE",
    "DOC-05": "PROCESS_MECANIQUE",
    "DOC-06": "CALCUL_STRUCTURE",
    "DOC-07": "DESSIN_PLAN",
    "DOC-08": "SOUDAGE_METALLURGIE",
    "DOC-09": "TRAITEMENT_THERMIQUE",
    "DOC-10": "INSPECTION_QUALITE",
    "DOC-11": "ESSAIS_EPREUVE",
    "DOC-12": "METALLURGIE_MATIERE",
    "DOC-13": "CND_CONTROLE",
    "DOC-14": "DIMENSIONNEL"
}

class ARHPieceIndexer:
    def __init__(self, chroma_path: Optional[str] = None):
        base_dir = Path(__file__).parent
        self.chroma_path = chroma_path or str(base_dir / "chroma_db")
        self.collection_name = "arh_pieces_knowledge"
        
        # Initialisation du client ChromaDB persistant
        self.client = chromadb.PersistentClient(path=self.chroma_path)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "Index vectoriel granulaire des pièces réglementaires ARH"}
        )

    def _get_embedding(self, text: str) -> List[float]:
        """Génère l'embedding via le client Ollama unifié (nomic-embed-text) avec fallback déterministe."""
        try:
            from arh_ollama_client import get_ollama_client
            emb = get_ollama_client().embed(EMBEDDING_MODEL, text[:1500])
            if emb:
                return emb
        except Exception:
            pass

        # Fallback pseudo-embedding déterministe
        import hashlib, math
        h = hashlib.sha256(text.encode('utf-8', errors='ignore')).digest()
        raw = [float(b) / 255.0 for b in h] * 24
        norm = math.sqrt(sum(x*x for x in raw)) or 1.0
        return [x / norm for x in raw[:768]]

    def _batch_get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Calcule les embeddings en parallèle avec un pool de threads."""
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as executor:
            return list(executor.map(self._get_embedding, texts))

    def index_dossier_pieces(self, dossier_id: str) -> Dict[str, Any]:
        """
        Indexe toutes les pièces découpées d'un dossier dans ChromaDB.
        Génère des chunks sémantiques ciblés par pièce pour une recherche ultra-rapide.
        """
        from arh_document_slicer import arh_slicer
        pieces = arh_slicer.get_sliced_pieces(dossier_id)
        if not pieces:
            pieces = arh_slicer.slice_dossier(dossier_id)

        try:
            self.collection.delete(where={"dossier_id": dossier_id})
        except Exception:
            pass

        ids = []
        documents = []
        metadatas = []

        import fitz

        for piece in pieces:
            p_code = piece["piece_code"]
            p_name = piece["piece_name"]
            p_file = piece["file_path"]
            disc = DISCIPLINE_MAP.get(p_code, "GENERAL")
            dec_ref = piece.get("regulatory_ref", "P-CTE-1")

            # 1. Chunk résumé du contrat Pydantic (Haute valeur sémantique)
            fields = piece.get("extracted_fields", {})
            contract_summary = (
                f"PIÈCE ARH {p_code} : {p_name} ({dec_ref}). Discipline: {disc}. "
                f"Plage: Pages {piece['page_start']} à {piece['page_end']}. "
            )
            if fields:
                contract_summary += "Données vérifiées: " + " | ".join(f"{k}: {v}" for k, v in fields.items())

            c_id = f"{dossier_id}_{p_code}_contract"
            ids.append(c_id)
            documents.append(contract_summary)
            metadatas.append({
                "dossier_id": dossier_id,
                "piece_code": p_code,
                "piece_name": p_name,
                "discipline": disc,
                "regulatory_ref": dec_ref,
                "page": piece["page_start"],
                "page_start": piece["page_start"],
                "page_end": piece["page_end"],
                "file_name": piece["file_name"]
            })

            # 2. Chunks de texte physique du sous-PDF
            if os.path.exists(p_file):
                try:
                    with fitz.open(p_file) as p_doc:
                        # Extraire le texte agrégé de la pièce
                        for p_idx, page in enumerate(p_doc):
                            p_txt = page.get_text().strip()
                            if len(p_txt) > 40:
                                real_page = piece["page_start"] + p_idx
                                c_id = f"{dossier_id}_{p_code}_p{real_page}"
                                ids.append(c_id)
                                documents.append(p_txt[:1200])  # Premier bloc représentatif de la page
                                metadatas.append({
                                    "dossier_id": dossier_id,
                                    "piece_code": p_code,
                                    "piece_name": p_name,
                                    "discipline": disc,
                                    "regulatory_ref": dec_ref,
                                    "page": real_page,
                                    "page_start": piece["page_start"],
                                    "page_end": piece["page_end"],
                                    "file_name": piece["file_name"]
                                })
                except Exception as e:
                    logger.error("[ARH-INDEXER] Erreur lecture sub-pdf %s: %s", p_file, e)

        # Calcul parallèle de tous les embeddings
        embeddings = self._batch_get_embeddings(documents)

        if ids:
            self.collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings
            )

        logger.info("[ARH-INDEXER] Dossier %s indexé avec succès (%d chunks, %d pièces).", dossier_id, len(ids), len(pieces))
        return {
            "status": "SUCCESS",
            "dossier_id": dossier_id,
            "pieces_indexed": len(pieces),
            "chunks_count": len(ids)
        }


    def search_pieces(self, dossier_id: str, query: str, piece_code: Optional[str] = None, discipline: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Recherche sémantique ciblée dans les pièces d'un dossier.
        Permet le filtrage strict par pièce (ex: DOC-06) ou par discipline (ex: CALCUL_STRUCTURE).
        """
        filters = [{"dossier_id": dossier_id}]
        if piece_code:
            filters.append({"piece_code": piece_code.strip().upper()})
        elif discipline:
            filters.append({"discipline": discipline.strip().upper()})

        where_filter = filters[0] if len(filters) == 1 else {"$and": filters}
        q_emb = self._get_embedding(query)
        
        try:
            results = self.collection.query(
                query_embeddings=[q_emb],
                n_results=top_k,
                where=where_filter
            )
        except Exception as e:
            logger.error("[ARH-INDEXER] Erreur query ChromaDB: %s", e)
            return []

        hits = []
        if results and results.get("ids") and len(results["ids"][0]) > 0:
            for idx in range(len(results["ids"][0])):
                doc_text = results["documents"][0][idx]
                meta = results["metadatas"][0][idx]
                dist = results["distances"][0][idx] if results.get("distances") else 0.0
                sim_score = max(0.0, round(1.0 - (dist / 2.0), 3)) if dist is not None else 1.0

                hits.append({
                    "chunk_id": results["ids"][0][idx],
                    "piece_code": meta.get("piece_code"),
                    "piece_name": meta.get("piece_name"),
                    "discipline": meta.get("discipline"),
                    "page": meta.get("page"),
                    "page_start": meta.get("page_start"),
                    "page_end": meta.get("page_end"),
                    "file_name": meta.get("file_name"),
                    "regulatory_ref": meta.get("regulatory_ref"),
                    "relevance_score": sim_score,
                    "text_snippet": doc_text
                })

        return hits

# Instance singleton
arh_indexer = ARHPieceIndexer()
