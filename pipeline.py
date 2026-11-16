"""
DeerFlow Lite — pipeline.py v2.1
Orchestration RAG : Plan → Retrieve → Neo4j Enrichment → Generate → Guard.

MODIFICATIONS v2.1 :
- STEP 8 enrichi : après retrieval hybride, kg.build_context() injecte le
  sous-graphe Neo4j dans le prompt, balisé [KNOWLEDGE GRAPH] pour que
  le LLM le distingue du contexte ChromaDB.
- Timeout 2s sur la requête Neo4j pour ne pas bloquer le pipeline.
- Neo4j complémente ChromaDB (ne le remplace pas).
- Fallback automatique si Neo4j indisponible.
"""
import os
import json
import time
import logging
import threading
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

_kg_cache = None
_kg_mtime = 0.0
_kg_lock = threading.Lock()


@dataclass
class PipelineResponse:
    """Complete response from the pipeline."""
    answer: str
    sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    query_type: str = ""
    disciplines: list[str] = field(default_factory=list)
    equipment_tags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    context_sufficient: bool = True
    processing_time: float = 0.0
    num_documents_retrieved: int = 0
    reasoning_steps: list[dict] = field(default_factory=list)
    reasoning_model: str = ""
    reasoning_iterations: int = 0
    image_url: Optional[str] = None
    neo4j_enriched: bool = False   # indique si Neo4j a enrichi la réponse
    lightrag_enriched: bool = False  # indique si LightRAG a enrichi la réponse


# Types de requêtes routées vers l'Agent Raisonneur
_AGENT_QUERY_TYPES = {"multi_hop", "troubleshoot", "comparison", "design_check", "calculation"}


class OilGasPipeline:
    """
    Pipeline principal DeerFlow Lite v2.1.

    Étapes :
      1.  Query Planning (classification)
      2.  Query Expansion (vocabulaire)
      2b. Visual Generation (optionnel)
      3.  Multi-Agent Enrichment
      4.  Hybrid Retrieval (ChromaDB + BM25 + RRF)
      5.  Source Weight Application (learning)
      6.  Semantic Reranking
      7.  Context Sufficiency Check
      8.  Build Context ChromaDB
      8b. Neo4j Enrichment → contexte [KNOWLEDGE GRAPH] injecté
      9.  Prompt Construction
      10. LLM Generation
      11. Agent Validation + Anti-Hallucination (guardrails)
      12. Self-Learning Feedback
    """

    def __init__(self):
        self._initialized = False
        self._init_lock = threading.Lock()
        self._retriever = None
        self._orchestrator = None
        self._learning_engine = None
        self._neo4j_kg = None

    def _ensure_initialized(self):
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return

            try:
                from retriever import get_retriever
                self._retriever = get_retriever()
            except ImportError as e:
                logger.error(f"Retriever not available: {e}")

            try:
                from agents import get_orchestrator
                self._orchestrator = get_orchestrator()
            except ImportError as e:
                logger.error(f"Agent orchestrator not available: {e}")

            try:
                from learning import get_learning_engine
                self._learning_engine = get_learning_engine()
            except ImportError as e:
                logger.error(f"Learning engine not available: {e}")

            # Initialiser Neo4j (non bloquant)
            try:
                from knowledge_graph import get_neo4j_kg
                self._neo4j_kg = get_neo4j_kg()
                if self._neo4j_kg.disponible():
                    logger.info("Neo4j disponible pour enrichissement pipeline.")
                else:
                    logger.info("Neo4j indisponible — fallback JSON actif.")
            except Exception as e:
                logger.warning(f"Neo4j init failed (pipeline): {e}")
                self._neo4j_kg = None

            self._initialized = (self._retriever is not None)

    async def process_query(self, query: str, user_discipline: str = "", use_agent: bool = True) -> PipelineResponse:
        """
        Traite une question utilisateur à travers le pipeline complet.
        """
        start_time = time.time()
        self._ensure_initialized()

        response = PipelineResponse(answer="", query_type="unknown")

        # === PRE-CHECK: Route vers l'Agent Raisonneur si question complexe ===
        plan = None
        if use_agent:
            try:
                from query_planner import plan_retrieval
                plan = plan_retrieval(query)
                qtype = plan.query_type.value
                response.query_type = qtype
                response.equipment_tags = plan.equipment_tags
                response.disciplines = plan.disciplines or ([user_discipline] if user_discipline else [])

                if qtype in _AGENT_QUERY_TYPES:
                    logger.info(f"[Pipeline] Question complexe ({qtype}) → Agent Raisonneur")
                    return await self._process_with_agent(query, user_discipline, response, start_time)
            except Exception as e:
                logger.debug(f"Agent routing check failed, fallback to classic: {e}")
                plan = None

        try:
            # === STEP 1: Query Planning ===
            if plan is None:
                from query_planner import plan_retrieval
                plan = plan_retrieval(query)

            response.query_type = plan.query_type.value
            response.equipment_tags = plan.equipment_tags
            response.disciplines = plan.disciplines or ([user_discipline] if user_discipline else [])

            logger.info(f"Query plan: type={plan.query_type.value}, "
                       f"disciplines={response.disciplines}, tags={plan.equipment_tags}")

            # === STEP 2: Query Expansion ===
            from vocabulary import expand_query
            expanded_query = expand_query(query)

            # === STEP 2b: Visual Generation Check ===
            if any(w in query.lower() for w in ["schéma", "schema", "diagramme", "diagram", "visuel", "dessine"]):
                try:
                    from vision_generator import get_vision_generator
                    viz = get_vision_generator()
                    path = viz.generate_project_summary_card(query[:30], [{"title": "Analyse Visuelle", "points": [query]}])
                    if path:
                        response.image_url = f"/visuals/{os.path.basename(path)}"
                        logger.info(f"Visual triggered: {response.image_url}")
                except Exception as e:
                    logger.warning(f"Auto-visual generation failed: {e}")

            # === STEP 3: Multi-Agent Enrichment ===
            agent_contexts = []
            agent_keywords = []
            if self._orchestrator:
                agent_contexts = self._orchestrator.enrich_query(
                    query, plan.equipment_tags, response.disciplines
                )
                agent_keywords = self._orchestrator.merge_agent_keywords(agent_contexts)
                if agent_keywords:
                    expanded_query += " " + " ".join(agent_keywords[:5])

            # === STEP 4: Hybrid Retrieval ===
            if self._retriever is None:
                response.answer = "Erreur: le système de recherche n'est pas initialisé."
                response.confidence = 0.0
                return response

            # Adapter le TOP_K selon le type de requête
            # Les requêtes P&ID nécessitent plus de chunks (plans complexes, tags dispersés)
            retrieval_top_k = None  # utilise la valeur de config (TOP_K=20)
            if plan.is_pid_query:
                try:
                    from config import TOP_K as _BASE_TOP_K
                    retrieval_top_k = min(_BASE_TOP_K * 2, 40)  # max 40 pour les P&ID
                    logger.info("[Pipeline] Requête P&ID détectée → TOP_K doublé à %d", retrieval_top_k)
                except ImportError:
                    retrieval_top_k = 20

            results = self._retriever.retrieve(
                expanded_query,
                top_k=retrieval_top_k,
                discipline_filter=response.disciplines[0] if response.disciplines else None
            )

            # Boost des chunks P&ID/Instrumentation sur requête P&ID
            if plan.is_pid_query and results:
                PID_BOOST_TYPES = {"pid", "drawing", "instrumentation"}
                for r in results:
                    meta = getattr(r, "metadata", {}) or {}
                    doc_type = meta.get("document_type", "")
                    discipline = meta.get("discipline", "")
                    if doc_type in PID_BOOST_TYPES or discipline in PID_BOOST_TYPES:
                        r.score *= 1.3  # boost 30% pour les chunks pertinents P&ID
                # Retrier après boost
                results.sort(key=lambda x: x.score, reverse=True)
                logger.info("[Pipeline] Boost P&ID appliqué sur %d résultats", len(results))

            response.num_documents_retrieved = len(results)

            # === STEP 5: Source Weight Application ===
            try:
                from learning import get_learning_engine
                engine = get_learning_engine()
                if engine:
                    results = engine.apply_learned_weights_to_results(results)
            except Exception as e:
                logger.debug(f"Could not apply learned weights: {e}")

            # === STEP 6: Semantic Reranking ===
            try:
                from reranker import semantic_rerank
                results = semantic_rerank(query, results)
            except ImportError:
                logger.warning("Reranker not available, using retrieval order")

            # === STEP 7: Context Sufficiency ===
            sufficiency = self._retriever.assess_context_sufficiency(query, results)
            response.context_sufficient = sufficiency["sufficient"]
            response.confidence = sufficiency["confidence"]

            if not sufficiency["sufficient"] and sufficiency["confidence"] < 0.15:
                from prompts import build_insufficient_response
                response.answer = build_insufficient_response(query)
                response.sources = []
                response.processing_time = time.time() - start_time
                self._record_feedback(query, response)
                return response

            # === STEP 8: Build Context ChromaDB ===
            from retriever import build_context_string
            context = build_context_string(results)

            response.sources = list(set(
                r.source for r in results if r.source and r.source != "unknown"
            ))

            # === STEP 8b: Neo4j Enrichment ===
            # Injecter le sous-graphe Neo4j APRÈS le contexte ChromaDB.
            # Timeout 2s pour ne pas bloquer le pipeline.
            neo4j_context = self._get_neo4j_context(
                query, plan.equipment_tags, response.disciplines
            )
            if neo4j_context:
                context = context + "\n\n" + neo4j_context
                response.neo4j_enriched = True
                logger.info("Neo4j context injecté (%d chars)", len(neo4j_context))

            # === STEP 8c: LightRAG Enrichment ===
            # Injecter le contexte LightRAG si activé et disponible.
            import config
            if getattr(config, "LIGHTRAG_ENABLED", True):
                try:
                    from lightrag_integration import get_lightrag
                    lr = get_lightrag()
                    if lr.disponible():
                        # Déterminer le mode selon le type de requête
                        mode = "hybrid"
                        if plan.query_type in ('equipment', 'regulation'):
                            mode = "local"
                        elif plan.query_type in ('project_summary', 'impact_analysis'):
                            mode = "global"

                        logger.info("Interrogation LightRAG en mode '%s' pour la question...", mode)
                        lightrag_context = lr.query(query, mode=mode)
                        if lightrag_context:
                            context = context + "\n\n=== CONTEXTE GRAPH RAG (LightRAG) ===\n" + lightrag_context
                            response.lightrag_enriched = True
                            logger.info("Contexte LightRAG injecté (%d chars)", len(lightrag_context))
                except Exception as e:
                    logger.warning("Échec de l'enrichissement LightRAG: %s", e)

            # === STEP 9: Prompt Construction ===
            from prompts import build_prompt

            agent_warnings = ""
            if self._orchestrator and agent_contexts:
                norms = self._orchestrator.merge_agent_norms(agent_contexts)
                if norms:
                    agent_warnings = "Normes potentiellement applicables : " + ", ".join(norms)

            # Fallback legacy kb_context via JSON (si Neo4j indisponible)
            kb_context = "" if neo4j_context else self._get_kb_context(
                plan.equipment_tags, response.disciplines
            )

            prompt = build_prompt(
                query=query,
                context=context,
                query_type=plan.query_type,
                kb_context=kb_context,
                agent_warnings=agent_warnings,
                discipline=response.disciplines[0] if response.disciplines else "",
            )

            # === STEP 10: LLM Generation ===
            answer = await self._call_llm(prompt["system"], prompt["user"])

            # === STEP 11: Agent Validation + Guardrails ===
            if self._orchestrator:
                validations = self._orchestrator.validate_answer(
                    query, answer, context, response.disciplines
                )
                for v in validations:
                    response.warnings.extend(v.warnings)
                warning_text = self._orchestrator.format_warnings(validations)
                if warning_text:
                    answer += f"\n\n---\n**Alertes de vérification :**\n{warning_text}"

            try:
                from guardrails import get_guardrails
                guardrails = get_guardrails()
                if guardrails and context:
                    verification = guardrails.verify_answer(answer, context, query)
                    if not verification.get("grounded", True):
                        response.warnings.append(
                            f"Attention: seulement {verification.get('grounding_ratio', 0):.0%} "
                            "des affirmations sont vérifiées dans les sources"
                        )
                        answer = verification.get("sanitized_answer", answer)
            except Exception as e:
                logger.warning(f"Guardrails verification failed: {e}")

            response.answer = answer
            response.processing_time = time.time() - start_time

            # === STEP 12: Self-Learning ===
            self._record_feedback(query, response)

            return response

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            response.answer = "Une erreur interne s'est produite lors du traitement. Veuillez réessayer."
            response.confidence = 0.0
            response.processing_time = time.time() - start_time
            return response

    def _get_neo4j_context(self, query: str, equipment_tags: list, disciplines: list) -> str:
        """
        Interroge Neo4j avec timeout configurable (défaut 5s) + 1 retry.
        Retourne une chaîne balisée [KNOWLEDGE GRAPH] ou vide si Neo4j absent.
        """
        try:
            from config import NEO4J_TIMEOUT
        except ImportError:
            NEO4J_TIMEOUT = 5

        if self._neo4j_kg is None or not self._neo4j_kg.disponible():
            return ""

        import concurrent.futures
        import time as _time

        # Construire la requête avec les tags détectés ET la question complète
        search_query = query
        if equipment_tags:
            search_query = " ".join(equipment_tags) + " " + query

        MAX_ATTEMPTS = 2  # 1 tentative initiale + 1 retry
        for attempt in range(MAX_ATTEMPTS):
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(self._neo4j_kg._build_context_internal, search_query)
                    ctx = future.result(timeout=NEO4J_TIMEOUT)
                return ctx  # déjà balisé [KNOWLEDGE GRAPH] par build_context_internal
            except concurrent.futures.TimeoutError:
                if attempt < MAX_ATTEMPTS - 1:
                    logger.warning(
                        "[Neo4j] Timeout (%ss) — retry dans 1s (tentative %d/%d)",
                        NEO4J_TIMEOUT, attempt + 1, MAX_ATTEMPTS
                    )
                    _time.sleep(1)
                else:
                    logger.warning(
                        "[Neo4j] Timeout définitif après %d tentative(s) — pipeline continue sans Neo4j",
                        MAX_ATTEMPTS
                    )
                return ""
            except Exception as e:
                logger.debug("[Neo4j] Context failed : %s", e)
                return ""

    async def _process_with_agent(self, query: str, discipline: str,
                                   response: PipelineResponse, start_time: float) -> PipelineResponse:
        """Route la question vers l'Agent Raisonneur (Qwen 2.5 14B)."""
        try:
            from reasoning_agent import get_reasoning_agent
            import asyncio
            agent = get_reasoning_agent()
            
            # Executer agent.run de maniere non-bloquante dans un pool de threads
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: agent.run(query, discipline))

            response.answer = result.answer
            if response.answer and response.answer.startswith("⚠ L'agent a atteint la limite"):
                raise ValueError("Reasoning agent hit the iteration limit without a complete answer")
            response.sources = result.sources
            response.confidence = 0.85
            response.context_sufficient = True
            response.processing_time = time.time() - start_time
            response.reasoning_model = result.model_used
            response.reasoning_iterations = result.iterations
            response.num_documents_retrieved = sum(
                1 for s in result.steps if s.step_type == "observation"
            )
            response.reasoning_steps = [
                {
                    "type": step.step_type,
                    "content": step.content,
                    "tool": step.tool_name,
                    "tool_input": step.tool_input,
                    "duration_ms": round(step.duration_ms, 1),
                }
                for step in result.steps
            ]
            self._record_feedback(query, response)
            return response

        except Exception as e:
            logger.error(f"Agent Raisonneur failed, fallback to classic pipeline: {e}", exc_info=True)
            return await self.process_query(query, discipline, use_agent=False)

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Appel asynchrone Ollama pour la génération de réponse."""
        try:
            import httpx
            try:
                from config import LLM_MODEL, OLLAMA_BASE_URL, LLM_TIMEOUT, LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_NUM_CTX
            except ImportError:
                LLM_MODEL = "qwen2.5:14b"
                OLLAMA_BASE_URL = "http://localhost:11434"
                LLM_TIMEOUT = 300
                LLM_TEMPERATURE = 0.1
                LLM_MAX_TOKENS = 2048
                LLM_NUM_CTX = 16384

            # Diagnostic log
            total_chars = len(system_prompt) + len(user_prompt)
            estimated_tokens = total_chars // 4
            logger.info(
                "[Pipeline._call_llm] modèle=%s | num_ctx=%d | ~%d tokens estimés",
                LLM_MODEL, LLM_NUM_CTX, estimated_tokens,
            )
            if estimated_tokens > LLM_NUM_CTX * 0.85:
                logger.warning(
                    "[Pipeline._call_llm] ⚠️ TRONCATURE PROBABLE : %d tokens > 85%% de num_ctx=%d",
                    estimated_tokens, LLM_NUM_CTX,
                )

            async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
                resp = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": LLM_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user",   "content": user_prompt},
                        ],
                        "stream": False,
                        "options": {
                            "temperature": LLM_TEMPERATURE,
                            "top_p": 0.9,
                            "top_k": 40,
                            "repeat_penalty": 1.1,
                            "num_predict": LLM_MAX_TOKENS,
                            "num_ctx": LLM_NUM_CTX,
                        },
                    }
                )
                resp.raise_for_status()
                return resp.json()["message"]["content"]

        except httpx.ConnectError:
            return (
                "Erreur: Impossible de se connecter au serveur LLM (Ollama). "
                "Vérifiez que le service est démarré avec `ollama serve`."
            )
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return "Erreur lors de la génération de la réponse. Veuillez réessayer."

    def _get_kb_context(self, equipment_tags: list, disciplines: list) -> str:
        """Fallback : contexte depuis knowledge_graph.json (si Neo4j absent)."""
        global _kg_cache, _kg_mtime
        try:
            kg_path = Path("knowledge_graph.json")
            if not kg_path.exists():
                return ""
            with _kg_lock:
                current_mtime = kg_path.stat().st_mtime
                if _kg_cache is None or current_mtime != _kg_mtime:
                    with open(kg_path, 'r', encoding='utf-8') as f:
                        _kg_cache = json.load(f)
                    _kg_mtime = current_mtime
                kg = _kg_cache

            relevant = []
            entities_raw = kg.get("entities", {})
            if isinstance(entities_raw, dict):
                for key, entity in entities_raw.items():
                    name = entity.get("name", key)
                    etype = entity.get("type", "")
                    sources = entity.get("sources", [])
                    if any(tag.upper() in key for tag in equipment_tags):
                        src_str = f" [doc: {sources[0]}]" if sources else ""
                        relevant.append(f"- {name} ({etype}){src_str}")
                        for rel in kg.get("relationships", [])[:200]:
                            if rel.get("source") == key or rel.get("target") == key:
                                other = rel["target"] if rel["source"] == key else rel["source"]
                                relevant.append(f"  → {rel['relation']}: {other}")
                        continue
                    if etype.lower() in [d.lower() for d in disciplines]:
                        relevant.append(f"- {name} ({etype})")

            if relevant:
                return "Entités connues du Knowledge Graph :\n" + "\n".join(relevant[:25])
            return ""
        except Exception as e:
            logger.debug(f"KB context retrieval failed: {e}")
            return ""

    def _record_feedback(self, query: str, response: PipelineResponse):
        """Enregistre l'interaction pour le self-learning."""
        if self._learning_engine is None:
            return
        try:
            from learning import FeedbackEntry
            if response.confidence >= 0.7:
                rating = "partial"
            elif response.confidence >= 0.35:
                rating = "partial"
            else:
                rating = "bad"

            entry = FeedbackEntry(
                query=query,
                answer=response.answer[:500],
                sources=response.sources,
                rating=rating,
                confidence=response.confidence,
                discipline=response.disciplines[0] if response.disciplines else "",
            )
            self._learning_engine.process_feedback(entry)
        except Exception as e:
            logger.debug(f"Auto feedback recording failed: {e}")

    def submit_user_feedback(self, query: str, answer: str, rating: str,
                             correction: str = "", sources: list = None):
        """Soumet le feedback utilisateur explicite."""
        if self._learning_engine is None:
            logger.warning("Learning engine not available for feedback")
            return
        from learning import FeedbackEntry
        entry = FeedbackEntry(
            query=query,
            answer=answer,
            sources=sources or [],
            rating=rating,
            confidence=1.0 if rating == "good" else 0.0,
            correction=correction,
        )
        self._learning_engine.process_feedback(entry)
        logger.info(f"User feedback recorded: rating={rating}")

    def get_system_status(self) -> dict:
        """Retourne le statut du système incluant Neo4j."""
        status = {
            "pipeline": "ready" if self._initialized else "not_initialized",
            "retriever": "available" if self._retriever else "unavailable",
            "agents": "available" if self._orchestrator else "unavailable",
            "learning": "available" if self._learning_engine else "unavailable",
            "neo4j": "available" if (self._neo4j_kg and self._neo4j_kg.disponible()) else "unavailable",
        }
        if self._learning_engine:
            status["learning_stats"] = self._learning_engine.get_learning_stats()
        if self._neo4j_kg and self._neo4j_kg.disponible():
            status["neo4j_stats"] = self._neo4j_kg.get_stats()
        return status


# Module-level singleton
_pipeline = None
_pipeline_lock = threading.Lock()

def get_pipeline() -> OilGasPipeline:
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                _pipeline = OilGasPipeline()
    return _pipeline

async def ask(query: str, discipline: str = "") -> PipelineResponse:
    """Fonction de convenance pour poser une question."""
    return await get_pipeline().process_query(query, discipline)
