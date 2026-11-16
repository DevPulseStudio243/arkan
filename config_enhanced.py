# ============================================================
#  DEERFLOW LITE - Enhanced Configuration
#  Pipeline RAG Oil & Gas avec anti-hallucination
#  + Agents, Training, Project Understanding, File Processing
# ============================================================

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

# ── Ollama ──────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", os.getenv("DEERFLOW_LLM_MODEL", "qwen2.5:14b"))
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "llava:7b")

# ── ChromaDB ────────────────────────────────────────────────
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "oil_gas_docs")

# ── Chunking ────────────────────────────────────────────────
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
MIN_CHUNK_SIZE = 100
MAX_CHUNK_SIZE = 2000

# ── Retrieval ───────────────────────────────────────────────
TOP_K = int(os.getenv("TOP_K", "20"))
BM25_WEIGHT = float(os.getenv("BM25_WEIGHT", "0.4"))
VECTOR_WEIGHT = float(os.getenv("VECTOR_WEIGHT", "0.6"))
RERANK_ENABLED = True
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "12"))
CONTEXT_MAX_CHARS = int(os.getenv("CONTEXT_MAX_CHARS", "15000"))

# ── Anti-Hallucination ──────────────────────────────────────
HALLUCINATION_THRESHOLD = float(os.getenv("HALLUCINATION_THRESHOLD", "0.3"))
GROUNDING_CHECK = os.getenv("GROUNDING_CHECK", "True").lower() == "true"
MAX_CLAIMS_UNGROUNDED = int(os.getenv("MAX_CLAIMS_UNGROUNDED", "0"))

CONFIDENCE_LEVELS = {
    "high":   {"min": 0.7, "label": "Confiance élevée",   "emoji": ""},
    "medium": {"min": 0.4, "label": "Confiance moyenne",  "emoji": ""},
    "low":    {"min": 0.3, "label": "Confiance faible",   "emoji": ""},
    "none":   {"min": 0.0, "label": "Insuffisant",        "emoji": ""},
}

# ── BM25 Stopwords (FR + EN) ───────────────────────────────
BM25_STOPWORDS = {
    # Français
    "le", "la", "les", "un", "une", "des", "du", "de", "et", "est",
    "en", "que", "qui", "dans", "pour", "pas", "ne", "sur", "au",
    "aux", "ce", "il", "elle", "se", "son", "sa", "ses", "nous",
    "vous", "ils", "elles", "leur", "leurs", "avec", "ou", "mais",
    "donc", "car", "ni", "par", "plus", "moins", "tout", "tous",
    "cette", "ces", "mon", "ton", "notre", "votre", "être", "avoir",
    "fait", "comme", "on", "été", "aussi", "peut", "sont", "vers",
    "quel", "quelle", "quels", "quelles", "dont",
    # English
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can",
    "need", "dare", "ought", "used", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between",
    "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all",
    "each", "every", "both", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "because", "but", "and", "if", "or",
    "what", "which", "who", "whom", "this", "that", "these", "those",
    "it", "its", "i", "me", "my", "we", "our", "you", "your",
    "he", "him", "his", "she", "her", "they", "them", "their",
}

# ── LLM ─────────────────────────────────────────────────────
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))

# ── Paths (original) ────────────────────────────────────────
KNOWLEDGE_DB_PATH = os.getenv("KNOWLEDGE_DB_PATH", "knowledge_db.json")
VISION_CACHE_PATH = os.getenv("VISION_CACHE_PATH", "vision_cache.db")

# ── Self-learning ─────────────────────────────────────────
DATA_PATH = os.getenv("RAG_DATA_PATH", os.path.join(os.getcwd(), "data"))
EXTENSIONS = {".pdf", ".txt", ".md", ".docx", ".xlsx", ".xls", ".pptx", ".csv"}
KNOWLEDGE_GRAPH_PATH = os.getenv("KNOWLEDGE_GRAPH_PATH", "knowledge_graph.json")
FEEDBACK_DB_PATH = os.getenv("FEEDBACK_DB_PATH", "feedback_db.json")
VOCABULARY_PATH = os.getenv("VOCABULARY_PATH", "vocabulary.json")
AUTO_INDEX_ENABLED = os.getenv("AUTO_INDEX_ENABLED", "True").lower() == "true"
AUTO_LEARN_ENABLED = os.getenv("AUTO_LEARN_ENABLED", "True").lower() == "true"

# ── Logging ─────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ============================================================
#  NEW SETTINGS — Agent System
# ============================================================

# ── Agent Timeout & Limits ───────────────────────────────
AGENT_TIMEOUT = int(os.getenv("AGENT_TIMEOUT", "300"))              # seconds per agent task
MAX_SECONDARY_AGENTS = int(os.getenv("MAX_SECONDARY_AGENTS", "5"))  # max concurrent sub-agents
AGENT_RETRY_LIMIT = int(os.getenv("AGENT_RETRY_LIMIT", "3"))       # retries on transient failure
AGENT_HEARTBEAT_INTERVAL = int(os.getenv("AGENT_HEARTBEAT_INTERVAL", "30"))  # seconds

# ── Agent Roles ─────────────────────────────────────────────
AGENT_ROLES = {
    "researcher":   {"description": "Searches & retrieves documents", "priority": 1},
    "analyst":      {"description": "Analyses data & generates insights", "priority": 2},
    "validator":    {"description": "Validates claims against sources", "priority": 3},
    "summarizer":   {"description": "Produces concise summaries", "priority": 4},
    "translator":   {"description": "Handles multilingual content", "priority": 5},
}

# ── Agent Communication ─────────────────────────────────────
AGENT_MESSAGE_QUEUE_SIZE = int(os.getenv("AGENT_MESSAGE_QUEUE_SIZE", "100"))
AGENT_COORDINATION_MODE = os.getenv("AGENT_COORDINATION_MODE", "sequential")  # sequential | parallel | hybrid

# ============================================================
#  NEW SETTINGS — Training Engine
# ============================================================

# ── Training Cycle ───────────────────────────────────────────
TRAINING_CYCLE_INTERVAL = int(os.getenv("TRAINING_CYCLE_INTERVAL", "3600"))   # seconds between auto-training cycles
MIN_FEEDBACK_FOR_TRAINING = int(os.getenv("MIN_FEEDBACK_FOR_TRAINING", "10")) # minimum feedback entries before triggering training
TRAINING_BATCH_SIZE = int(os.getenv("TRAINING_BATCH_SIZE", "32"))
TRAINING_EPOCHS = int(os.getenv("TRAINING_EPOCHS", "3"))
TRAINING_LEARNING_RATE = float(os.getenv("TRAINING_LEARNING_RATE", "2e-5"))

# ── Training Data ───────────────────────────────────────────
TRAINING_DATA_DIR = os.getenv("TRAINING_DATA_DIR", "./training_data")
TRAINING_EXPORT_DIR = os.getenv("TRAINING_EXPORT_DIR", "./training_exports")
TRAINING_LOG_PATH = os.getenv("TRAINING_LOG_PATH", "training_log.json")
AUTO_TRAINING_ENABLED = os.getenv("AUTO_TRAINING_ENABLED", "True").lower() == "true"

# ── Model Fine-tuning ──────────────────────────────────────
FINE_TUNE_BASE_MODEL = os.getenv("FINE_TUNE_BASE_MODEL", "nomic-ai/nomic-embed-text-v1.5")
FINE_TUNE_OUTPUT_DIR = os.getenv("FINE_TUNE_OUTPUT_DIR", "./fine_tuned_models")
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "768"))

# ============================================================
#  NEW SETTINGS — Project Model / Understanding
# ============================================================

# ── Project Model ───────────────────────────────────────────
PROJECT_MODEL_PATH = os.getenv("PROJECT_MODEL_PATH", "project_model.json")
AUTO_PROJECT_ANALYSIS = os.getenv("AUTO_PROJECT_ANALYSIS", "True").lower() == "true"
PROJECT_SUMMARY_MAX_CHARS = int(os.getenv("PROJECT_SUMMARY_MAX_CHARS", "5000"))

# ── Project Understanding ──────────────────────────────────
PROJECT_CONTEXT_WINDOW = int(os.getenv("PROJECT_CONTEXT_WINDOW", "8192"))   # tokens for project context
PROJECT_TAXONOMY_PATH = os.getenv("PROJECT_TAXONOMY_PATH", "project_taxonomy.json")
PROJECT_ENTITIES_PATH = os.getenv("PROJECT_ENTITIES_PATH", "project_entities.json")
PROJECT_RELATIONS_PATH = os.getenv("PROJECT_RELATIONS_PATH", "project_relations.json")
PROJECT_ANALYSIS_DEPTH = os.getenv("PROJECT_ANALYSIS_DEPTH", "standard")  # light | standard | deep

# ============================================================
#  NEW SETTINGS — File Processor
# ============================================================

# ── File Size & Types ───────────────────────────────────────
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(100 * 1024 * 1024)))  # 100 MB default
SUPPORTED_EXTENSIONS = {
    ".pdf", ".txt", ".md", ".docx", ".xlsx", ".xls",
    ".pptx", ".csv", ".json", ".yaml", ".yml",
    ".html", ".htm", ".xml", ".rtf",
    ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif",
}

# ── OCR ─────────────────────────────────────────────────────
OCR_ENABLED = os.getenv("OCR_ENABLED", "True").lower() == "true"
OCR_LANGUAGE = os.getenv("OCR_LANGUAGE", "fra+eng")           # Tesseract language codes
OCR_DPI = int(os.getenv("OCR_DPI", "300"))
OCR_CONFIDENCE_THRESHOLD = float(os.getenv("OCR_CONFIDENCE_THRESHOLD", "0.6"))

# ── Encoding Detection ─────────────────────────────────────
ENCODING_DETECTION_ENABLED = os.getenv("ENCODING_DETECTION_ENABLED", "True").lower() == "true"
DEFAULT_ENCODING = os.getenv("DEFAULT_ENCODING", "utf-8")

# ============================================================
#  NEW SETTINGS — Persistence Paths (JSON)
# ============================================================

# All JSON persistence files in one place for easy discovery
AGENT_STATE_PATH = os.getenv("AGENT_STATE_PATH", "agent_state.json")
AGENT_HISTORY_PATH = os.getenv("AGENT_HISTORY_PATH", "agent_history.json")
CONVERSATION_MEMORY_PATH = os.getenv("CONVERSATION_MEMORY_PATH", "conversation_memory.json")
TASK_QUEUE_PATH = os.getenv("TASK_QUEUE_PATH", "task_queue.json")
METRICS_PATH = os.getenv("METRICS_PATH", "metrics.json")
CACHE_INDEX_PATH = os.getenv("CACHE_INDEX_PATH", "cache_index.json")
ERROR_LOG_PATH = os.getenv("ERROR_LOG_PATH", "error_log.json")

# ── Convenience: collect all persistence paths ──────────────
ALL_PERSISTENCE_PATHS = [
    KNOWLEDGE_DB_PATH,
    VISION_CACHE_PATH,
    KNOWLEDGE_GRAPH_PATH,
    FEEDBACK_DB_PATH,
    VOCABULARY_PATH,
    TRAINING_LOG_PATH,
    PROJECT_MODEL_PATH,
    PROJECT_TAXONOMY_PATH,
    PROJECT_ENTITIES_PATH,
    PROJECT_RELATIONS_PATH,
    AGENT_STATE_PATH,
    AGENT_HISTORY_PATH,
    CONVERSATION_MEMORY_PATH,
    TASK_QUEUE_PATH,
    METRICS_PATH,
    CACHE_INDEX_PATH,
    ERROR_LOG_PATH,
]
