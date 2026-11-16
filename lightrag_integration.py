# ============================================================
#  DEERFLOW LITE - LightRAG Integration Module
#  Graph RAG double-niveau (local/global) avec Neo4j + Ollama
# ============================================================

import os
import sys
import logging
import asyncio
import threading
import concurrent.futures
from pathlib import Path

# Importer la configuration de DeerFlow
import config

logger = logging.getLogger("deerflow.lightrag")

# Singleton global thread-safe
_lightrag_instance = None
_init_lock = threading.Lock()

def run_async(coro):
    """
    Exécute un coroutine asynchrone de manière synchrone.
    Gère correctement les cas où un event loop est déjà actif.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Exécuter dans un thread séparé pour éviter "This event loop is already running"
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: asyncio.run(coro))
            return future.result()
    else:
        return asyncio.run(coro)


class DeerFlowLightRAG:
    """Wrapper pour LightRAG s'intégrant au pipeline de DeerFlow Lite."""

    def __init__(self):
        self._rag = None
        self._initialized = False
        self._disponible = False

    def _ensure_initialized(self):
        """Initialisation paresseuse et thread-safe de LightRAG + Neo4j."""
        if self._initialized:
            return

        with _init_lock:
            if self._initialized:
                return

            try:
                # 1. Configurer les variables d'environnement Neo4j exigées par LightRAG
                os.environ["NEO4J_URI"] = config.NEO4J_URI
                os.environ["NEO4J_USERNAME"] = config.NEO4J_USER
                os.environ["NEO4J_PASSWORD"] = config.NEO4J_PASSWORD
                os.environ["NEO4J_DATABASE"] = config.NEO4J_DATABASE

                # 2. Configurer le répertoire de travail
                working_dir = getattr(config, "LIGHTRAG_WORKING_DIR", str(config.BASE_DIR / "lightrag_data"))
                os.makedirs(working_dir, exist_ok=True)

                # 3. Importer LightRAG dynamiquement
                from lightrag import LightRAG
                from lightrag.llm.ollama import ollama_model_complete, ollama_embed
                from lightrag.utils import EmbeddingFunc

                # 4. Déterminer le modèle LLM à utiliser pour LightRAG.
                # Nous préférons qwen2.5:14b car les modèles de raisonnement (comme deepseek-r1)
                # sont lents et instables pour la phase d'extraction structurée de LightRAG.
                # On utilise LIGHTRAG_LLM_MODEL si configuré, sinon config.LLM_MODEL s'il n'est pas deepseek,
                # sinon on fallback sur qwen2.5:14b.
                llm_model = os.environ.get("LIGHTRAG_LLM_MODEL")
                if not llm_model:
                    cfg_model = getattr(config, "LLM_MODEL", "qwen2.5:14b")
                    if "deepseek-r1" in cfg_model:
                        llm_model = "qwen2.5:14b"
                    else:
                        llm_model = cfg_model

                logger.info(f"Initialisation de LightRAG | LLM={llm_model} | Embeddings={config.EMBEDDING_MODEL} | Workspace=deerflow")

                # 5. Instancier LightRAG avec workspace deerflow pour isoler les labels dans Neo4j
                self._rag = LightRAG(
                    working_dir=working_dir,
                    workspace="deerflow",
                    llm_model_func=ollama_model_complete,
                    llm_model_name=llm_model,
                    embedding_func=EmbeddingFunc(
                        embedding_dim=config.EMBEDDING_DIM,
                        max_token_size=8192,
                        # Utiliser .func pour court-circuiter le décorateur 1024 dimensions d'ollama_embed
                        func=lambda texts: ollama_embed.func(
                            texts,
                            embed_model=config.EMBEDDING_MODEL
                        )
                    ),
                    graph_storage="Neo4JStorage"
                )

                # 6. Initialiser les storages (exécuté de manière synchrone via run_async)
                run_async(self._rag.initialize_storages())
                
                self._disponible = True
                logger.info("LightRAG + Neo4j initialisé avec succès !")

            except Exception as e:
                logger.error(f"Échec de l'initialisation de LightRAG: {e}", exc_info=True)
                self._rag = None
                self._disponible = False
            
            self._initialized = True

    def disponible(self) -> bool:
        """Vérifie si LightRAG est actif et utilisable."""
        if not getattr(config, "LIGHTRAG_ENABLED", True):
            return False
        
        # S'assurer que l'initialisation a été tentée
        if not self._initialized:
            self._ensure_initialized()
            
        return self._disponible

    async def ainsert_document(self, text: str) -> bool:
        """Insertion asynchrone d'un document ou chunk dans le graphe."""
        if not self.disponible():
            return False
        try:
            await self._rag.ainsert(text)
            return True
        except Exception as e:
            logger.error(f"Erreur lors de l'insertion asynchrone dans LightRAG: {e}")
            return False

    def insert_document(self, text: str) -> bool:
        """Insertion synchrone d'un document ou chunk dans le graphe (thread-safe)."""
        if not self.disponible():
            return False
        return run_async(self.ainsert_document(text))

    async def aquery(self, question: str, mode: str = "hybrid") -> str:
        """Requête asynchrone sur le graphe (modes: local/global/hybrid)."""
        if not self.disponible():
            return ""
        try:
            from lightrag import QueryParam
            res = await self._rag.aquery(question, param=QueryParam(mode=mode))
            return res if isinstance(res, str) else str(res)
        except Exception as e:
            logger.error(f"Erreur lors de la requête asynchrone sur LightRAG: {e}")
            return ""

    def query(self, question: str, mode: str = "hybrid") -> str:
        """Requête synchrone sur le graphe (modes: local/global/hybrid)."""
        if not self.disponible():
            return ""
        return run_async(self.aquery(question, mode=mode))


def get_lightrag() -> DeerFlowLightRAG:
    """Retourne l'instance singleton de DeerFlowLightRAG."""
    global _lightrag_instance
    if _lightrag_instance is None:
        with _init_lock:
            if _lightrag_instance is None:
                _lightrag_instance = DeerFlowLightRAG()
    return _lightrag_instance
