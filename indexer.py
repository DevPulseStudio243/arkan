# ============================================================
#  DEERFLOW LITE - Indexation ChromaDB + BM25
#  Chunking adaptatif avec stopword filtering amélioré
# ============================================================

import re
import logging
import hashlib
from typing import Optional

import httpx
import chromadb
from rank_bm25 import BM25Okapi

from config import (
    OLLAMA_BASE_URL,
    OLLAMA_EMBED_MODEL,
    CHROMA_PERSIST_DIR,
    CHROMA_COLLECTION,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    MIN_CHUNK_SIZE,
    MAX_CHUNK_SIZE,
    LLM_TIMEOUT,
    BM25_STOPWORDS,
)

logger = logging.getLogger(__name__)

# ── BM25 Tokenization améliorée ────────────────────────────

def tokenize_for_bm25(text: str) -> list:
    """
    Tokenisation améliorée pour BM25:
    - Lowercase
    - Suppression stopwords FR + EN
    - Filtrage tokens < 2 caractères
    - Conservation des tags techniques (P-101, etc.)
    """
    # Protéger les tags techniques avant le split
    # Remplacer les tirets dans les tags par un placeholder
    tag_pattern = r"\b([A-Z0-9]+-[A-Z0-9]+-?[A-Z0-9]*)\b"
    tags_found = re.findall(tag_pattern, text)
    protected = text
    tag_map = {}
    for i, tag in enumerate(tags_found):
        placeholder = f"TAGHOLDER{i}"
        tag_map[placeholder.lower()] = tag.lower()
        protected = protected.replace(tag, placeholder)

    # Tokeniser
    tokens_raw = re.split(r"[\s\.,;:!?\(\)\[\]{}<>\"'`/\\|@#$%^&*+=~]+", protected.lower())

    # Restaurer les tags et filtrer
    tokens = []
    for t in tokens_raw:
        if t in tag_map:
            tokens.append(tag_map[t])
        elif len(t) >= 2 and t not in BM25_STOPWORDS:
            tokens.append(t)

    return tokens


# ── Chunking helpers ──────────────────────────────────────

def _contains_table(text: str) -> bool:
    """Detect if text block contains a table structure."""
    lines = text.strip().split("\n")
    tab_lines = sum(1 for l in lines if "\t" in l or "|" in l)
    return tab_lines >= 3

def _get_semantic_overlap(previous_chunk: str, overlap_chars: int) -> str:
    """Get overlap at sentence boundary instead of raw character slicing."""
    if len(previous_chunk) <= overlap_chars:
        return previous_chunk
    tail = previous_chunk[-overlap_chars * 2:]
    sentences = re.split(r'(?<=[.!?])\s+', tail)
    overlap_text = ""
    for s in reversed(sentences):
        if len(overlap_text) + len(s) <= overlap_chars:
            overlap_text = s + " " + overlap_text
        else:
            break
    return overlap_text.strip() or previous_chunk[-overlap_chars:]

# ── Chunking adaptatif ──────────────────────────────────────

def adaptive_chunk(text: str, base_size: int = CHUNK_SIZE,
                   overlap: int = CHUNK_OVERLAP) -> list:
    """
    Semantic chunking: splits on structural boundaries (section headers,
    markdown headers, ALL-CAPS headers), keeps tables as atomic units,
    and uses sentence-boundary overlaps.
    """
    if not text or len(text.strip()) < MIN_CHUNK_SIZE:
        return [text.strip()] if text.strip() else []

    # Split on structural boundaries: numbered sections, markdown headers, ALL-CAPS headers, rules
    section_pattern = r"\n(?=(?:\d+\.\s|\#{1,3}\s|[A-Z][A-Z\s]{3,}:?\s*$|={3,}|-{3,}))"
    sections = re.split(section_pattern, text, flags=re.MULTILINE)

    chunks = []
    current_chunk = ""

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Keep tables as atomic units - never split them
        if _contains_table(section):
            if current_chunk and len(current_chunk) >= MIN_CHUNK_SIZE:
                chunks.append(current_chunk)
                current_chunk = ""
            # If the table section fits in a chunk, keep it whole
            if len(section) <= MAX_CHUNK_SIZE:
                chunks.append(section)
            else:
                # Table too large: add as-is (preserve atomicity)
                chunks.append(section)
            continue

        # If the section is larger than max_size, sub-split by paragraphs
        if len(section) > MAX_CHUNK_SIZE:
            paragraphs = section.split("\n\n")
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue

                if len(current_chunk) + len(para) + 1 <= base_size:
                    current_chunk = (current_chunk + "\n" + para).strip()
                else:
                    if current_chunk and len(current_chunk) >= MIN_CHUNK_SIZE:
                        chunks.append(current_chunk)
                    if len(para) > base_size:
                        sub_chunks = _split_long_text(para, base_size, overlap)
                        chunks.extend(sub_chunks[:-1])
                        current_chunk = sub_chunks[-1] if sub_chunks else ""
                    else:
                        if chunks and overlap > 0:
                            sem_overlap = _get_semantic_overlap(chunks[-1], overlap)
                            current_chunk = sem_overlap + "\n" + para
                        else:
                            current_chunk = para
        else:
            if len(current_chunk) + len(section) + 1 <= base_size:
                current_chunk = (current_chunk + "\n\n" + section).strip()
            else:
                if current_chunk and len(current_chunk) >= MIN_CHUNK_SIZE:
                    chunks.append(current_chunk)
                if chunks and overlap > 0:
                    sem_overlap = _get_semantic_overlap(chunks[-1], overlap)
                    current_chunk = sem_overlap + "\n\n" + section
                else:
                    current_chunk = section

    # Last chunk
    if current_chunk and len(current_chunk) >= MIN_CHUNK_SIZE:
        chunks.append(current_chunk)
    elif current_chunk and chunks:
        chunks[-1] = chunks[-1] + "\n" + current_chunk

    return chunks if chunks else [text.strip()]


def _validate_embedding(embedding, source: str = "") -> list | None:
    """
    Valide et normalise un embedding avant envoi à ChromaDB.

    ChromaDB exige : list[float] non vide, dimension cohérente.
    Retourne None si l'embedding est invalide (loggue l'erreur).
    """
    if embedding is None:
        logger.warning("Embedding None reçu pour %s", source)
        return None

    # Si dict retourné par erreur (ex: réponse Ollama mal parsée)
    if isinstance(embedding, dict):
        # Tenter d'extraire le vecteur du dict
        vec = embedding.get("embedding") or embedding.get("values") or embedding.get("data")
        if vec and isinstance(vec, list):
            logger.warning("Embedding reçu comme dict — extraction automatique pour %s", source)
            embedding = vec
        else:
            logger.error(
                "Embedding invalide (dict sans clé connue) pour %s : clés=%s",
                source, list(embedding.keys())[:5]
            )
            return None

    # Vérifier que c'est bien une liste de nombres
    if not isinstance(embedding, list) or len(embedding) == 0:
        logger.warning("Embedding vide ou non-list pour %s : type=%s", source, type(embedding))
        return None

    # S'assurer que tous les éléments sont des floats
    try:
        embedding = [float(x) for x in embedding]
    except (TypeError, ValueError) as e:
        logger.error("Embedding contient des valeurs non-numériques pour %s : %s", source, e)
        return None

    return embedding


def _split_long_text(text: str, size: int, overlap: int) -> list:
    """Découpe un texte long en morceaux avec overlap."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        if end < len(text):
            space_pos = text.rfind(" ", start + size // 2, end)
            if space_pos > start:
                end = space_pos
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap if overlap > 0 else end
    return chunks


# ── Embeddings ────────────────────────────────────

_LOCAL_EMBED_MODEL = None
_LOCAL_EMBED_PATH = "models/embeddings_oil_gas"
_LOCAL_EMBED_LOCK = __import__('threading').Lock()
_LOCAL_EMBED_AVAILABLE: bool | None = None  # None = pas encore vérifié

# Cache LRU : évite les appels HTTP répétés pour le même texte
# 512 entrées couvrent toutes les requêtes d'une session normale
from functools import lru_cache as _lru_cache

@_lru_cache(maxsize=512)
def _cached_ollama_embedding(text: str) -> tuple:
    """
    Appelle Ollama et retourne l'embedding sous forme de tuple (hashable pour le cache).
    Ne jamais appeler directement — passer par get_embedding().
    """
    try:
        response = httpx.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
            timeout=LLM_TIMEOUT,
        )
        if response.status_code == 200:
            emb = response.json().get("embedding", [])
            return tuple(emb)
    except Exception as e:
        logger.error(f"Erreur embedding Ollama: {e}")
    return ()


def get_embedding(text: str) -> list:
    """
    Obtient l'embedding d'un texte.
    Priorité : modèle local fine-tuné O&G > Ollama nomic-embed-text (avec cache LRU).
    Les deux doivent produire des vecteurs de même dimension pour que
    ChromaDB reste cohérent — si le modèle local est chargé, il est
    utilisé exclusivement pour toute la session.
    """
    global _LOCAL_EMBED_MODEL, _LOCAL_EMBED_AVAILABLE

    # Tentative chargement modèle local (une seule fois)
    if _LOCAL_EMBED_AVAILABLE is None:
        with _LOCAL_EMBED_LOCK:
            if _LOCAL_EMBED_AVAILABLE is None:
                import os
                if os.path.exists(_LOCAL_EMBED_PATH):
                    try:
                        from sentence_transformers import SentenceTransformer
                        _LOCAL_EMBED_MODEL = SentenceTransformer(_LOCAL_EMBED_PATH)
                        _LOCAL_EMBED_AVAILABLE = True
                        logger.info("Embedding local O&G chargé: %s", _LOCAL_EMBED_PATH)
                    except Exception as e:
                        logger.warning("Modèle embedding local indisponible: %s", e)
                        _LOCAL_EMBED_AVAILABLE = False
                else:
                    _LOCAL_EMBED_AVAILABLE = False

    # Utiliser le modèle local si disponible (pas de cache nécessaire — déjà en mémoire)
    if _LOCAL_EMBED_AVAILABLE and _LOCAL_EMBED_MODEL is not None:
        try:
            vec = _LOCAL_EMBED_MODEL.encode(
                text[:512], normalize_embeddings=True, show_progress_bar=False
            )
            return vec.tolist()
        except Exception as e:
            logger.warning("Embedding local échoué, fallback Ollama: %s", e)

    # Fallback Ollama avec cache LRU (evite les appels HTTP répétés)
    # Tronquer à 1000 chars pour la clé de cache (les longs textes sont
    # souvent identiques dans leur début, ce qui donne de bons hits)
    cache_key = text[:1000]
    result = _cached_ollama_embedding(cache_key)
    return list(result) if result else []


def get_embeddings_batch(texts: list, max_workers: int = 8) -> list:
    """Obtain embeddings concurrently for better throughput."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        embeddings = list(executor.map(get_embedding, texts))
    return embeddings


# ── ChromaDB ────────────────────────────────────────────────

_chroma_client = None
_collection = None
_collection_lock = __import__('threading').Lock()


def get_collection():
    """
    Obtient ou crée la collection ChromaDB (thread-safe).

    ChromaDB 1.5.8 deserialise l'EmbeddingFunction stockee sur disque
    sous forme de dict (au lieu d'objet). Quand upsert() tente ensuite
    d'acceder a dict.dimensionality → AttributeError.

    Fix : apres avoir charge la collection, on force
    _collection._embedding_function = None.
    ChromaDB saute alors toute validation de dimensionalite, et comme
    on passe toujours embeddings= explicitement dans upsert(), ca marche.
    """
    global _chroma_client, _collection
    if _collection is not None:
        return _collection
    with _collection_lock:
        if _collection is not None:  # Double-checked locking
            return _collection
        try:
            from config import CHROMA_MODE, CHROMA_HOST, CHROMA_PORT
        except ImportError:
            import os
            CHROMA_MODE = os.environ.get("CHROMA_MODE", "local")
            CHROMA_HOST = os.environ.get("CHROMA_HOST", "chromadb")
            CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8000"))

        if CHROMA_MODE == "server":
            _chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=int(CHROMA_PORT))
        else:
            _chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)

        try:
            _collection = _chroma_client.get_or_create_collection(
                name=CHROMA_COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            logger.warning("get_or_create_collection echoue (%s) — tentative get seule", e)
            try:
                _collection = _chroma_client.get_collection(name=CHROMA_COLLECTION)
                logger.info("Collection recuperee sans recreation")
            except Exception as e2:
                logger.error("Impossible d'acceder a la collection ChromaDB : %s", e2)
                raise

        # FIX ChromaDB 1.5.8+ : force une DummyEF pour éviter 'dict object has no attribute dimensionality'
        try:
            from config import EMBEDDING_DIM
            class DummyEF:
                def __init__(self, dim=EMBEDDING_DIM): self.dimensionality = dim
                def __call__(self, texts): return []
            
            dummy = DummyEF()
            _collection._embedding_function = dummy
            # Tenter aussi sans l'underscore pour la compatibilité
            if hasattr(_collection, "embedding_function"):
                _collection.embedding_function = dummy
            logger.info("Collection ChromaDB prete : %s (EF patchée)", CHROMA_COLLECTION)
        except Exception as e:
            logger.warning("Echec du patch EF : %s", e)
            logger.info("Collection ChromaDB prete : %s", CHROMA_COLLECTION)

    return _collection



# ── BM25 Index ──────────────────────────────────────────────

_bm25_index = None
_bm25_docs = []
_bm25_ids = []
_bm25_metadatas = []


def build_bm25_index(documents: list, doc_ids: list, metadatas: list = None):
    """Construit l'index BM25 avec tokenisation améliorée."""
    global _bm25_index, _bm25_docs, _bm25_ids, _bm25_metadatas
    _bm25_docs = documents
    _bm25_ids = doc_ids
    _bm25_metadatas = metadatas or [{} for _ in documents]

    tokenized = [tokenize_for_bm25(doc) for doc in documents]
    _bm25_index = BM25Okapi(tokenized)
    logger.info(f"Index BM25 construit: {len(documents)} documents")


def get_bm25_index():
    """Retourne l'index BM25 courant."""
    return _bm25_index, _bm25_docs, _bm25_ids, _bm25_metadatas


# ── Indexation complète ─────────────────────────────────────

def index_document(text: str, metadata: dict, source: str):
    """
    Indexe un document: chunking + ChromaDB + BM25.
    """
    chunks = adaptive_chunk(text)
    if not chunks:
        logger.warning(f"Aucun chunk généré pour {source}")
        return 0

    collection = get_collection()
    
    ids = []
    embeddings = []
    documents = []
    metadatas = []

    for i, chunk in enumerate(chunks):
        # Générer un ID unique
        chunk_id = hashlib.md5(f"{source}:{hashlib.md5(chunk.encode()).hexdigest()}".encode()).hexdigest()

        # Obtenir et valider l'embedding
        embedding = get_embedding(chunk)
        embedding = _validate_embedding(embedding, source=f"{source}:chunk{i}")
        if embedding is None:
            continue

        # ── Enrichissement automatique des métadonnées ──────────────────
        # Détecte discipline, type de document et tags techniques dans le chunk.
        # Ces métadonnées permettent le filtrage par discipline dans retriever.py.
        _discipline_detected = ""
        _doc_type_detected = ""
        _tags_in_chunk = []

        try:
            import re as _re

            # Détection de discipline (mapping simplifié depuis query_planner)
            _DISC_QUICK = {
                "piping":          [r'\b(tuyauterie|piping|pipe|tuyau|raccord|bride|P&ID|PID|isométrique|spool|DN\s*\d|NPS\s*\d)\b'],
                "process":         [r'\b(procédé|process|PFD|débit|pression|température|flow|pressure|heat balance)\b'],
                "instrumentation": [r'\b(instrument|capteur|transmetteur|boucle|DCS|PLC|SIS|ESD|4-20\s*mA|HART)\b',
                                    r'\b(FT|PT|TT|LT|PDT|PIC|TIC|FIC|LIC)\s*[-]?\d'],
                "mechanical":      [r'\b(mécanique|mechanical|pompe|compresseur|turbine|ventilat|moteur|pump)\b'],
                "electrical":      [r'\b(électri|electric|câble|cable|transfo|disjoncteur|MCC|switchgear|kV|kW|MW)\b'],
                "civil":           [r'\b(génie civil|civil|béton|fondation|structure|charpente|ferraillage)\b'],
                "hse":             [r'\b(HSE|sécurité|safety|environnement|HAZOP|SIL|ATEX|incendie|risque)\b'],
            }
            chunk_lower = chunk.lower()
            for _disc, _patterns in _DISC_QUICK.items():
                if any(_re.search(p, chunk_lower, _re.IGNORECASE) for p in _patterns):
                    _discipline_detected = _disc
                    break

            # Détection du type de document
            _DOC_TYPES = {
                "pid":       [r'\b(P&ID|PID|tuyauterie-instrumentation)\b'],
                "pfd":       [r'\b(PFD|procédé|diagramme de flux)\b'],
                "procedure": [r'\b(procédure|mode opératoire|étape|step\s+\d)\b'],
                "spec":      [r'\b(spécification|specification|datasheet|fiche technique)\b'],
                "drawing":   [r'\b(drawing|plan|isométrique|isometric|schéma|schematic)\b'],
                "report":    [r'\b(rapport|report|compte-rendu|revue|review)\b'],
                "standard":  [r'\b(API|ASME|ISO|EN\s*\d|NF|NFPA|IEC|ATEX)\s*\d'],
                "calculation": [r'\b(calcul|calculation|note de calcul|dimensionnement)\b'],
            }
            for _dtype, _patterns in _DOC_TYPES.items():
                if any(_re.search(p, chunk, _re.IGNORECASE) for p in _patterns):
                    _doc_type_detected = _dtype
                    break

            # Extraction des tags techniques (équipements, instruments, lignes)
            _TAG_PATTERNS = [
                r'\b([A-Z]{1,3}-\d{2,5}[A-Z]?)\b',              # P-101, V-200A, E-301
                r'\b(FT|PT|TT|LT|PDT|PIC|TIC|FIC|LIC)-\d{3,}\b', # instruments
                r'\b(\d{1,4}"-[A-Z0-9]+-\d{4})\b',              # lignes tuyauterie
            ]
            _tags_found = set()
            for _tp in _TAG_PATTERNS:
                _tags_found.update(_re.findall(_tp, chunk))
            _tags_in_chunk = list(_tags_found)[:20]  # max 20 tags par chunk

        except Exception:
            pass  # Ne jamais bloquer l'indexation sur enrichissement

        # Metadata du chunk (enrichie)
        chunk_meta = {
            "source": str(source),
            "chunk_index": i,
            "total_chunks": len(chunks),
            "char_count": len(chunk),
            "discipline": _discipline_detected,
            "document_type": _doc_type_detected,
            "equipment_tags": ",".join(_tags_in_chunk) if _tags_in_chunk else "",
            **{k: str(v) for k, v in metadata.items()},
        }

        ids.append(chunk_id)
        embeddings.append(embedding)
        documents.append(chunk)
        metadatas.append(chunk_meta)

    # Ajouter à ChromaDB par lots (upsert)
    if ids:
        try:
            collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )
        except Exception as e:
            logger.error(f"Erreur indexation batch pour {source}: {e}")
            return 0

    logger.info(f"Indexé {len(ids)}/{len(chunks)} chunks pour {source}")

    # === Double-indexation dans LightRAG ===
    try:
        import config
        if getattr(config, "LIGHTRAG_ENABLED", True):
            from lightrag_integration import get_lightrag
            lr = get_lightrag()
            if lr.disponible():
                logger.info(f"Insertion du document dans LightRAG pour: {source}")
                lr.insert_document(text)
    except Exception as e:
        logger.warning(f"Échec double-indexation LightRAG pour {source}: {e}")

    # Marquer BM25 comme à reconstruire (différé — évite O(n²) sur batch)
    # Appeler flush_bm25() après un batch d'indexation pour déclencher la reconstruction.
    if len(ids) > 0:
        global _bm25_rebuild_pending
        with _bm25_rebuild_lock:
            _bm25_rebuild_pending = True

    return len(ids)


# Verrou et flag pour le rebuild BM25 différé
import threading as _threading
_bm25_rebuild_pending: bool = False
_bm25_rebuild_lock = _threading.Lock()


def flush_bm25():
    """
    Reconstruit l'index BM25 une seule fois après un batch d'indexation.
    À appeler après scan_all() ou après une série d'appels à index_document().
    Évite le O(n²) de rebuilder après chaque document.
    """
    global _bm25_rebuild_pending
    with _bm25_rebuild_lock:
        if _bm25_rebuild_pending:
            _rebuild_bm25()
            _bm25_rebuild_pending = False
            logger.info("BM25 flush : index reconstruit")


def _rebuild_bm25():
    """Reconstruit l'index BM25 depuis ChromaDB avec métadonnées."""
    try:
        collection = get_collection()
        all_docs = collection.get(include=["documents", "metadatas"])
        if all_docs and all_docs.get("documents"):
            build_bm25_index(
                all_docs["documents"],
                all_docs["ids"],
                all_docs.get("metadatas", []),
            )
    except Exception as e:
        logger.error(f"Erreur reconstruction BM25: {e}")


def ensure_bm25_loaded():
    """S'assure que l'index BM25 est chargé."""
    global _bm25_index
    if _bm25_index is None:
        _rebuild_bm25()
