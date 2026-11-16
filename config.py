"""
ARKAN Lite - Configuration v3.2
Central configuration for all system components.

MODIFICATIONS v3.2:
- Migration vers ARKAN (priorité ARKAN_* dans .env)
- Ajout section Neo4j (URI, USER, PASSWORD, DATABASE, ENABLED)
- Ajout variables ChromaDB mode serveur Docker (CHROMA_MODE, CHROMA_HOST, CHROMA_PORT)
- Clarification dimension embeddings : nomic-embed-text=768 (défaut), bge-m3=1024
- Ajout OLLAMA_MODEL alias pour compatibilité Docker
"""
import os
from pathlib import Path

# --- Charger le .env AVANT tout (priorité aux variables définies dedans) ---
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

# --- Disable ChromaDB telemetry (supprime les erreurs PostHog dans les logs) ---
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY", "false")

# --- Base paths ---
base_env = os.environ.get("ARKAN_BASE_DIR", os.environ.get("DEERFLOW_BASE_DIR", "."))
if os.name == "nt" and base_env == "/app":
    BASE_DIR = Path(__file__).parent.resolve()
else:
    BASE_DIR = Path(base_env)
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = BASE_DIR / "models"
LEARNING_DIR = BASE_DIR / "learning_data"

# --- LLM Configuration ---
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", os.environ.get("ARKAN_LLM_MODEL", os.environ.get("DEERFLOW_LLM_MODEL", "qwen2.5:14b")))
LLM_MODEL = OLLAMA_MODEL
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_TEMPERATURE = float(os.environ.get("ARKAN_LLM_TEMP", os.environ.get("DEERFLOW_LLM_TEMP", "0.1")))
LLM_MAX_TOKENS = int(os.environ.get("ARKAN_LLM_MAX_TOKENS", os.environ.get("DEERFLOW_LLM_MAX_TOKENS", "2048")))

# LLM_NUM_CTX : taille de la fenêtre de contexte Ollama (en tokens).
# CRITIQUE pour le RAG : system (~600) + contexte RAG (~3000) + question (~100) = ~3700 tokens minimum.
# Si LLM_NUM_CTX < tokens_total → le contexte RAG est SILENCIEUSEMENT TRONQUÉ.
# qwen2.5:14b : 32768 max (recommandé 16384 sur 32GB RAM, CPU offload VRAM 4GB)
# llama3.1:8b : 16384 max (recommandé si qwen2.5 trop lent)
LLM_NUM_CTX = int(os.environ.get("LLM_NUM_CTX", "16384"))

# --- Embedding Configuration ---
# IMPORTANT : choisir le modèle correspondant à la ChromaDB indexée.
# nomic-embed-text → 768 dimensions (défaut)
# bge-m3           → 1024 dimensions (changer DEERFLOW_EMBEDDING_DIM=1024 dans .env)
EMBEDDING_MODEL = os.environ.get("ARKAN_EMBEDDING_MODEL", os.environ.get("DEERFLOW_EMBEDDING_MODEL", "nomic-embed-text"))
EMBEDDING_DIM = int(os.environ.get("ARKAN_EMBEDDING_DIM", os.environ.get("DEERFLOW_EMBEDDING_DIM", "768")))
# Alias pour Docker .env (OLLAMA_EMBED_MODEL=nomic-embed-text)
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", EMBEDDING_MODEL)

# --- ChromaDB Configuration ---
# Mode 'local' : PersistentClient (développement sans Docker)
# Mode 'server': HttpClient vers chromadb service Docker (production)
CHROMA_MODE = os.environ.get("CHROMA_MODE", "local")  # 'local' ou 'server'
CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))
CHROMA_PATH = str(BASE_DIR / os.environ.get("ARKAN_CHROMA_PATH", os.environ.get("DEERFLOW_CHROMA_PATH", "chroma_db")))
CHROMA_COLLECTION = os.environ.get("ARKAN_CHROMA_COLLECTION", os.environ.get("DEERFLOW_CHROMA_COLLECTION", "oil_gas_docs"))
# Alias pour compatibilité
CHROMA_PERSIST_DIR = CHROMA_PATH

# --- Neo4j Configuration ---
# URI bolt:// pour connexion locale ou Docker
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "deerflow_oilgas_2025")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
# Mettre NEO4J_ENABLED=false dans .env pour désactiver Neo4j (fallback JSON)
NEO4J_ENABLED = os.environ.get("NEO4J_ENABLED", "true").lower() == "true"

# --- Retrieval Configuration ---
TOP_K = int(os.environ.get("ARKAN_TOP_K", os.environ.get("DEERFLOW_TOP_K", "20")))  # augmenté 10→20 pour les docs complexes P&ID
VECTOR_WEIGHT = float(os.environ.get("ARKAN_VECTOR_WEIGHT", os.environ.get("DEERFLOW_VECTOR_WEIGHT", "0.6")))
BM25_WEIGHT = float(os.environ.get("ARKAN_BM25_WEIGHT", os.environ.get("DEERFLOW_BM25_WEIGHT", "0.4")))
RRF_K = int(os.environ.get("ARKAN_RRF_K", os.environ.get("DEERFLOW_RRF_K", "60")))
RERANK_ENABLED = os.environ.get("ARKAN_RERANK_ENABLED", os.environ.get("DEERFLOW_RERANK_ENABLED", "true")).lower() == "true"
HALLUCINATION_THRESHOLD = float(os.environ.get("ARKAN_HALLUCINATION_THRESHOLD", os.environ.get("DEERFLOW_HALLUCINATION_THRESHOLD", "0.4")))

# --- Learning Configuration ---
FEEDBACK_DB_PATH = str(BASE_DIR / "feedback_db.json")
SOURCE_WEIGHTS_PATH = str(BASE_DIR / "source_weights.json")
VOCABULARY_PATH = str(BASE_DIR / "vocabulary.json")
KNOWLEDGE_GRAPH_PATH = str(BASE_DIR / "knowledge_graph.json")
AUTO_INDEX_ENABLED = os.environ.get("ARKAN_AUTO_INDEX", os.environ.get("DEERFLOW_AUTO_INDEX", "true")).lower() == "true"
AUTO_LEARN_ENABLED = os.environ.get("ARKAN_AUTO_LEARN", os.environ.get("DEERFLOW_AUTO_LEARN", "true")).lower() == "true"

# --- Chunking Configuration ---
CHUNK_SIZE = int(os.environ.get("ARKAN_CHUNK_SIZE", os.environ.get("DEERFLOW_CHUNK_SIZE", "1000")))
CHUNK_OVERLAP = int(os.environ.get("ARKAN_CHUNK_OVERLAP", os.environ.get("DEERFLOW_CHUNK_OVERLAP", "200")))

# --- BM25 Configuration ---
BM25_STOPWORDS = {"le", "la", "les", "de", "du", "des", "un", "une", "et", "en",
                  "est", "sont", "pour", "par", "sur", "dans", "avec", "qui", "que",
                  "ce", "cette", "ces", "au", "aux", "ne", "pas", "ou", "se", "sa",
                  "son", "ses", "il", "elle", "ils", "nous", "vous", "ont", "être",
                  "avoir", "fait", "mais", "donc", "car", "ni", "si",
                  "the", "is", "are", "of", "and", "in", "to", "for", "with", "on"}

# --- Context limits ---
MAX_CONTEXT_TOKENS = int(os.environ.get("ARKAN_MAX_CONTEXT_TOKENS", os.environ.get("DEERFLOW_MAX_CONTEXT_TOKENS", "4000")))  # augmenté 3000→4000 : profite de LLM_NUM_CTX=16384
MIN_CONFIDENCE_THRESHOLD = float(os.environ.get("ARKAN_MIN_CONFIDENCE", os.environ.get("DEERFLOW_MIN_CONFIDENCE", "0.3")))

# --- Logging ---
LOG_LEVEL = os.environ.get("ARKAN_LOG_LEVEL", os.environ.get("DEERFLOW_LOG_LEVEL", "INFO"))
LOG_FILE = os.environ.get("ARKAN_LOG_FILE", os.environ.get("DEERFLOW_LOG_FILE", "deerflow.log"))

# --- Ensure directories exist ---
for d in [DATA_DIR, MODELS_DIR, LEARNING_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# --- Vision / OCR ---
OLLAMA_VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "llava:7b")
VISION_CACHE_PATH = os.environ.get("VISION_CACHE_PATH", str(BASE_DIR / "vision_cache.db"))

# --- Timeouts ---
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "300"))
NEO4J_TIMEOUT = int(os.environ.get("NEO4J_TIMEOUT", "5"))  # timeout requête Neo4j dans le pipeline (5s + 1 retry)

# --- Knowledge DB ---
KNOWLEDGE_DB_PATH = BASE_DIR / os.environ.get("ARKAN_KNOWLEDGE_DB", os.environ.get("DEERFLOW_KNOWLEDGE_DB", "knowledge_db.json"))

# --- LightRAG & Docling Configuration ---
LIGHTRAG_ENABLED = os.environ.get("LIGHTRAG_ENABLED", "true").lower() == "true"
LIGHTRAG_WORKING_DIR = str(BASE_DIR / "lightrag_data")
DOCLING_ENABLED = os.environ.get("DOCLING_ENABLED", "false").lower() == "true"

# --- Aliases for compatibility with modules that import these names ---
MIN_CHUNK_SIZE = 100
MAX_CHUNK_SIZE = 2000
DATA_PATH = str(DATA_DIR)
EXTENSIONS = {".pdf", ".txt", ".md", ".docx", ".xlsx", ".xls", ".pptx", ".csv", ".html", ".htm", ".dwg", ".dxf"}

# --- API ---
API_PORT = int(os.environ.get("API_PORT", "8000"))
API_KEY = os.environ.get("API_KEY", "deerflow_api_key_change_me")
