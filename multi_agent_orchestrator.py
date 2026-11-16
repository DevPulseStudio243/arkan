"""
DeerFlow Lite — Multi-Agent Orchestrator v2.0
Architecture découpée autour de Qwen 14B pour éviter la surcharge cognitive.
Implémente le Native Tool Calling d'Ollama.

Chaque agent spécialisé reçoit UNIQUEMENT les outils de sa spécialité,
ce qui réduit la confusion du LLM et améliore la précision des réponses.

Architecture:
  [Question] → Router → [Agent Spécialisé + Outils] → Critic → [Réponse Finale]
"""

import json
import logging
import time
import re
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────
try:
    from config import OLLAMA_BASE_URL
except ImportError:
    OLLAMA_BASE_URL = "http://127.0.0.1:11434"

try:
    from config import LLM_MODEL as AGENT_MODEL
except ImportError:
    AGENT_MODEL = "deepseek-r1:latest"
AGENT_TIMEOUT = 300.0  # Qwen 14B peut être long au chargement initial


# ── Importation des outils depuis reasoning_agent ─────────────
from reasoning_agent import AGENT_TOOLS

# ── Structures de données ─────────────────────────────────────

class SwarmBlackboard:
    """Mémoire partagée temporaire (Blackboard Architecture) entre agents pendant l'exécution d'une requête."""
    def __init__(self):
        self.data: Dict[str, Any] = {}
        self.handoffs: List[Dict[str, Any]] = []

    def store(self, key: str, value: Any, agent: str):
        self.data[key] = value
        self.handoffs.append({"agent": agent, "key": key, "summary": str(value)[:300]})

    def get_summary(self) -> str:
        if not self.data:
            return ""
        lines = []
        for k, v in self.data.items():
            lines.append(f"- **{k}**: {v}")
        return "\n".join(lines)


@dataclass
class OrchestratorStep:
    """Une étape du pipeline multi-agent."""
    agent_name: str
    step_type: str     # "routing", "specialist", "tool_call", "critic", "handoff"
    content: str
    tool_name: str = ""
    duration_ms: float = 0.0


@dataclass
class OrchestratorResult:
    """Résultat complet du Multi-Agent Orchestrator."""
    answer: str
    steps: List[OrchestratorStep] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    total_time: float = 0.0
    iterations: int = 0
    model_used: str = ""
    selected_agent: str = ""
    secondary_agent: str = ""
    collaboration_chain: List[str] = field(default_factory=list)
    blackboard_summary: str = ""



# ── 1. CONVERSION OUTILS → FORMAT OLLAMA ─────────────────────

def convert_to_ollama_tools(tool_names: list) -> list:
    """Convertit une liste de noms d'outils du dictionnaire AGENT_TOOLS au format Ollama Native Tool Calling."""
    ollama_tools = []
    for name in tool_names:
        if name not in AGENT_TOOLS:
            continue
        info = AGENT_TOOLS[name]
        tool = {
            "type": "function",
            "function": {
                "name": name,
                "description": info["description"],
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": info["params"]
                }
            }
        }
        for param in info["params"]:
            tool["function"]["parameters"]["properties"][param] = {
                "type": "string",
                "description": f"Paramètre technique: {param}"
            }
        ollama_tools.append(tool)
    return ollama_tools


# ── Définition des spécialités ────────────────────────────────
DOCUMENT_TOOL_NAMES = [
    "search_documents", "search_keywords", "query_knowledge_graph",
    "analyze_engineering_pdf", "analyze_image_vision",
    "calculate_pressure_drop", "calculate_pump_power", "convert_units", "check_asme_compliance"
]
GRAPH_TOOL_NAMES = [
    "query_knowledge_graph", "get_project_equipments", "analyze_impact_neo4j",
    "search_keywords", "search_documents"
]
PLANNING_TOOL_NAMES = [
    "compute_evm", "analyze_planning_risk", "generate_diagram",
    "get_project_equipments", "search_keywords"
]
PID_TOOL_NAMES = [
    "analyze_engineering_pdf", "search_keywords", "analyze_image_vision", "update_knowledge_graph"
]
AUDIT_TOOL_NAMES = [
    "cross_check_documents", "search_keywords", "query_knowledge_graph"
]
SCADA_TOOL_NAMES = [
    "get_scada_live_data", "analyze_impact_neo4j", "query_knowledge_graph", "analyze_scada_trend"
]
REPORT_TOOL_NAMES = [
    "generate_equipment_report", "query_knowledge_graph", "get_scada_live_data", "search_keywords"
]
TRENDING_TOOL_NAMES = [
    "analyze_scada_trend", "get_scada_live_data", "analyze_impact_neo4j"
]
IMPORT_TOOL_NAMES = [
    "import_equipment_list", "update_knowledge_graph"
]


# ── 2. PROMPTS SPECIALISES ───────────────────────────────────

ROUTER_PROMPT = """Tu es le Superviseur DeerFlow.
Ton rôle est d'analyser la question de l'utilisateur et de choisir le ou les Agents les plus qualifiés pour y répondre.
Tu DOIS répondre UNIQUEMENT avec un objet JSON strictement formaté. Aucun texte en dehors du JSON.

AGENTS :
- DOCUMENT_AGENT : Questions techniques, spécifications, normes (API, ASME, ISO), pression/température de calcul, fiches techniques (datasheets), manuels, recherche documentaire et calculs d'ingénierie (pertes de charge, puissance pompe, etc.).
- GRAPH_AGENT : Liste des équipements d'un projet, relations entre équipements, dépendances amont/aval, et analyse d'impact en cascade lors d'une panne ou modification.
- PLANNING_AGENT : Calculs EVM (BAC, BCWP, BCWS, ACWP, SPI, CPI), plannings, retards, gestion des coûts, risques projet, et création de diagrammes récapitulatifs.
- PID_AGENT : Lecture et analyse directe des schémas P&ID, tuyauteries (lignes), vannes et boucles d'instrumentation sur les plans.
- AUDIT_AGENT : Contrôle croisé et détection des incohérences entre plusieurs documents (ex: P&ID vs datasheet).
- SCADA_AGENT : Données opérationnelles en temps réel (mesures actuelles, températures/pressions instantanées, alarmes SCADA en cours).
- REPORT_AGENT : Demande explicite de génération de rapport technique complet (PDF, DOCX) sur un équipement.
- TRENDING_AGENT : Détection de dérives et historiques de tendances sur les capteurs SCADA.
- IMPORT_AGENT : Importation de fichiers d'équipements Excel ou CSV.
- DIRECT_ANSWER : Salutations sociales uniquement (Bonjour, Salut, Merci, Qui es-tu ?). NE PAS utiliser pour des questions techniques ou calculs.

Règles de décision impératives :
1. Toute question contenant des métriques financières/planning (BAC, BCWP, EVM, budget, retard, diagramme) DOIT être routée vers PLANNING_AGENT.
2. Toute question demandant la liste des équipements d'un projet ou l'impact d'une panne DOIT être routée vers GRAPH_AGENT.
3. Toute question sur une donnée de calcul/design (ex: pression de calcul, température de calcul) DOIT être routée vers DOCUMENT_AGENT (pas SCADA_AGENT).
4. Si une question nécessite 2 spécialités (ex: recherche documentaire + audit de cohérence, ou P&ID + rapport), indique un secondary_agent.
5. DIRECT_ANSWER ne doit être choisi QUE pour des salutations simples.

Format attendu :
{
    "reasoning": "Pourquoi je choisis cet/ces agent(s)",
    "selected_agent": "NOM_AGENT_PRINCIPAL",
    "secondary_agent": "NOM_AGENT_SECONDAIRE (ou '' si aucun)"
}"""


DOCUMENT_AGENT_PROMPT = """Tu es l'Agent Documentaire DeerFlow.
Ta spécialité : Trouver l'information exacte dans la base vectorielle et BM25.
Utilise tes outils pour chercher l'information. Cite toujours tes sources avec [Source: xyz].
Réponds en français, de manière précise et technique.
Ne conclus rien sans avoir d'abord appelé un outil de recherche.
Si un premier outil ne donne pas de résultat suffisant, essaie un autre outil."""

GRAPH_AGENT_PROMPT = """Tu es l'Agent Architecte Neo4j DeerFlow.
Ta spécialité : Naviguer dans le Knowledge Graph pour trouver les relations entre équipements.
Utilise tes outils pour chercher les impacts, les dépendances ou lister les équipements.
Réponds en français. Ne fais pas de suppositions sans appeler un outil.
Pour une question sur un projet, utilise get_project_equipments.
Pour un impact, utilise analyze_impact_neo4j."""

PLANNING_AGENT_PROMPT = """Tu es l'Agent Planning & Coûts DeerFlow.
Ta spécialité : Calculs EVM, analyses de risques planning, et diagrammes visuels.
Réponds en français. Fais les calculs avec précision.
Si l'utilisateur fournit des données chiffrées, utilise compute_evm.
Si un retard ou dépassement est mentionné, utilise analyze_planning_risk.
Si un résumé visuel est demandé, utilise generate_diagram."""

PID_AGENT_PROMPT = """Tu es l'Agent P&ID DeerFlow.
Ta spécialité : Analyser en profondeur les plans et schémas techniques (PDF ou images).
Utilise tes outils pour lire les P&ID, extraire les tags d'équipements, vannes, boucles, et tuyauteries.
Réponds en français, avec précision, en citant les tags trouvés et leur contexte."""

AUDIT_AGENT_PROMPT = """Tu es l'Agent Auditeur DeerFlow.
Ta spécialité : Vérifier la cohérence technique entre différentes sources (Data sheets, P&ID, normes).
Utilise l'outil cross_check_documents pour repérer d'éventuelles anomalies.
Réponds en signalant clairement les contradictions trouvées et propose des recommandations."""

SCADA_AGENT_PROMPT = """Tu es l'Agent SCADA DeerFlow.
Ta spécialité : Monitorer les équipements en temps réel (via get_scada_live_data).
Vérifie les alarmes (WARNING) et utilise analyze_impact_neo4j si un équipement est en défaut pour voir les conséquences.
Réponds en listant les données temps réel et en analysant le risque de l'alarme."""

REPORT_AGENT_PROMPT = """Tu es l'Agent Rapports DeerFlow.
Ta spécialité : Générer des rapports techniques complets et structurés sur les équipements.
Utilise generate_equipment_report avec le tag demandé et le format désiré (text ou docx).
Réponds en présentant le rapport complet, récapitulant les données P&ID, SCADA et documentation."""

TRENDING_AGENT_PROMPT = """Tu es l'Agent Trending DeerFlow.
Ta spécialité : Détecter les dérives et tendances sur les métriques SCADA (vibrations, pression, température).
Utilise analyze_scada_trend pour analyser les métriques demandées.
Si une dérive est détectée, utilise analyze_impact_neo4j pour évaluer le risque.
Réponds avec une interprétation technique claire et des recommandations concrètes."""

IMPORT_AGENT_PROMPT = """Tu es l'Agent Import DeerFlow.
Ta spécialité : Importer des listes d'équipements depuis des fichiers Excel ou CSV.
Utilise import_equipment_list avec le chemin du fichier fourni par l'utilisateur.
Réponds en confirmant le nombre d'équipements importés et les éventuelles erreurs."""

CRITIC_PROMPT = """Tu es l'Agent Évaluateur Final (Critic) de DeerFlow.
On va te donner la question initiale et la réponse technique générée par un agent spécialiste.

Ton travail :
1. Vérifie que la réponse répond BIEN à la question posée.
2. Vérifie qu'il n'y a pas d'invention de données (hallucination).
3. Si des sources sont citées, garde-les.
4. Reformule la réponse de manière claire et structurée en Markdown propre (en français).
5. Si la réponse du spécialiste est insuffisante ou hors-sujet, dis-le clairement.

Rédige la réponse finale directement, sans préambule comme "Voici la réponse validée"."""


# ── 3. CLASSE BASE AGENT AVEC TOOL CALLING NATIVE ────────────

class BaseQwenAgent:
    """Agent utilisant l'API Chat d'Ollama avec Native Tool Calling."""

    def __init__(self, system_prompt: str, allowed_tool_names: list = None):
        self.system_prompt = system_prompt
        self.allowed_tool_names = allowed_tool_names or []
        self.ollama_tools = convert_to_ollama_tools(self.allowed_tool_names)
        self.client = httpx.Client(timeout=AGENT_TIMEOUT)
        self._tool_call_log: List[Dict] = []

    def _execute_tool(self, tool_name: str, arguments: Any) -> str:
        """Exécute physiquement la fonction Python associée."""
        if tool_name not in AGENT_TOOLS:
            return f"Error: Tool {tool_name} not found."

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except Exception:
                arguments = {"query": arguments}
        elif not isinstance(arguments, dict):
            arguments = {}

        try:
            fn = AGENT_TOOLS[tool_name]["fn"]
            # Filtrer les paramètres valides
            valid_params = AGENT_TOOLS[tool_name]["params"]
            filtered_args = {k: v for k, v in arguments.items() if k in valid_params}
            result = fn(**filtered_args)
            return str(result)[:4000]  # Limiter la taille pour le contexte
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return f"Error executing tool {tool_name}: {str(e)}"


    def call_llm(self, user_query: str, response_format=None) -> str:
        """Appelle le LLM. Gère automatiquement la boucle des appels d'outils."""
        self._tool_call_log = []

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_query}
        ]

        payload = {
            "model": AGENT_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 2048}
        }

        if response_format == "json":
            payload["format"] = "json"
        elif self.ollama_tools:
            payload["tools"] = self.ollama_tools

        MAX_TOOL_ITERATIONS = 5
        iterations = 0

        while iterations < MAX_TOOL_ITERATIONS:
            iterations += 1
            payload["messages"] = messages

            try:
                logger.info(f"[Agent] Appel Ollama ({AGENT_MODEL})...")
                resp = self.client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
            except httpx.ConnectError:
                logger.error(f"Ollama non accessible sur {OLLAMA_BASE_URL}")
                return "{}" if response_format == "json" else "Erreur: Ollama non accessible. Vérifiez que le service est démarré."
            except Exception as e:
                logger.error(f"Ollama API Error: {e}")
                return "{}" if response_format == "json" else f"Erreur LLM: {e}"

            message = data.get("message", {})
            messages.append(message)

            # Si le modèle veut appeler un outil (Native Tool Calling)
            if "tool_calls" in message and message["tool_calls"]:
                for tool_call in message["tool_calls"]:
                    fn_name = tool_call["function"]["name"]
                    fn_args = tool_call["function"].get("arguments", {})

                    logger.info(f"  [Native Tool] LLM appelle '{fn_name}' avec {fn_args}")
                    self._tool_call_log.append({"tool": fn_name, "args": fn_args})

                    result = self._execute_tool(fn_name, fn_args)

                    # On ajoute le résultat au contexte
                    messages.append({
                        "role": "tool",
                        "content": result,
                    })
                # On boucle : le LLM va lire les résultats d'outils et répondre
            else:
                # Pas d'outil appelé → retourner le texte final
                return message.get("content", "")

        return "Erreur: Nombre maximum d'appels d'outils dépassé."


# ── 4. ORCHESTRATEUR PRINCIPAL ───────────────────────────────

class MasterOrchestrator:
    """Gère le routage et délègue aux sous-agents spécialisés."""

    def __init__(self):
        self.router = BaseQwenAgent(system_prompt=ROUTER_PROMPT)
        self.specialists = {
            "DOCUMENT_AGENT": BaseQwenAgent(DOCUMENT_AGENT_PROMPT, DOCUMENT_TOOL_NAMES),
            "GRAPH_AGENT": BaseQwenAgent(GRAPH_AGENT_PROMPT, GRAPH_TOOL_NAMES),
            "PLANNING_AGENT": BaseQwenAgent(PLANNING_AGENT_PROMPT, PLANNING_TOOL_NAMES),
            "PID_AGENT": BaseQwenAgent(PID_AGENT_PROMPT, PID_TOOL_NAMES),
            "AUDIT_AGENT": BaseQwenAgent(AUDIT_AGENT_PROMPT, AUDIT_TOOL_NAMES),
            "SCADA_AGENT": BaseQwenAgent(SCADA_AGENT_PROMPT, SCADA_TOOL_NAMES),
            "REPORT_AGENT": BaseQwenAgent(REPORT_AGENT_PROMPT, REPORT_TOOL_NAMES),
            "TRENDING_AGENT": BaseQwenAgent(TRENDING_AGENT_PROMPT, TRENDING_TOOL_NAMES),
            "IMPORT_AGENT": BaseQwenAgent(IMPORT_AGENT_PROMPT, IMPORT_TOOL_NAMES),
        }
        self.critic = BaseQwenAgent(system_prompt=CRITIC_PROMPT)
        logger.info("[Orchestrator] Initialisé avec %d agents spécialisés", len(self.specialists))

    def run(self, query: str, discipline: str = "") -> OrchestratorResult:
        """Exécute le pipeline complet avec Blackboard et collaboration multi-agents : Router → Agent 1 [→ Agent 2] → Critic."""
        start_time = time.time()
        steps: List[OrchestratorStep] = []
        all_sources: List[str] = []
        blackboard = SwarmBlackboard()
        collaboration_chain: List[str] = ["ROUTER"]

        logger.info(f"\n[ORCHESTRATOR] Question : {query}")

        # ── 1. ROUTING ──────────────────────────────────────
        t0 = time.time()
        logger.info("[ROUTER] Analyse de l'intention et de la chaîne de collaboration...")
        router_response = self.router.call_llm(query, response_format="json")

        try:
            route_data = json.loads(router_response)
            selected_agent = route_data.get("selected_agent") or route_data.get("primary_agent") or "DOCUMENT_AGENT"
            secondary_agent = route_data.get("secondary_agent", "").strip()
            reasoning = route_data.get("reasoning", "")
        except (json.JSONDecodeError, Exception):
            selected_agent = "DOCUMENT_AGENT"
            secondary_agent = ""
            reasoning = "Fallback par défaut (parsing JSON échoué)."

        collaboration_chain.append(selected_agent)
        if secondary_agent and secondary_agent in self.specialists and secondary_agent != selected_agent:
            collaboration_chain.append(secondary_agent)
        else:
            secondary_agent = ""

        collaboration_chain.append("CRITIC")

        steps.append(OrchestratorStep(
            agent_name="ROUTER",
            step_type="routing",
            content=f"Agent principal: {selected_agent}" + (f", Agent secondaire: {secondary_agent}" if secondary_agent else "") + f". Raison: {reasoning}",
            duration_ms=(time.time() - t0) * 1000
        ))

        logger.info(f"[ROUTER] Chaîne de collaboration : {' ➔ '.join(collaboration_chain)} (Raison : {reasoning})")

        # ── Réponse directe (salutations ou conversation simple) ─────────────
        if selected_agent == "DIRECT_ANSWER":
            greeting_keywords = ["bonjour", "salut", "hello", "coucou", "qui es-tu", "presentation", "présentation"]
            is_pure_greeting = any(kw in query.lower() for kw in greeting_keywords) and len(query.split()) <= 6

            if is_pure_greeting:
                direct_ans = "Bonjour ! Je suis DeerFlow, votre assistant IA spécialisé en ingénierie Oil & Gas. Comment puis-je vous aider ?"
            else:
                direct_agent = BaseQwenAgent(
                    system_prompt="Tu es DeerFlow, l'assistant IA spécialisé en ingénierie Oil & Gas. Réponds à la question de l'utilisateur de manière claire, exacte et technique."
                )
                direct_ans = direct_agent.call_llm(query)

            return OrchestratorResult(
                answer=direct_ans,
                steps=steps,
                model_used=AGENT_MODEL,
                total_time=round(time.time() - start_time, 2),
                selected_agent="DIRECT_ANSWER",
                collaboration_chain=["ROUTER", "DIRECT_ANSWER"]
            )

        if selected_agent not in self.specialists:
            selected_agent = "DOCUMENT_AGENT"

        # ── 2. EXECUTION DU SPÉCIALISTE PRINCIPAL ─────────────────────
        t1 = time.time()
        agent1 = self.specialists[selected_agent]
        logger.info(f"[{selected_agent}] Début de la réflexion principale...")
        specialist_draft = agent1.call_llm(query)

        for tc in agent1._tool_call_log:
            steps.append(OrchestratorStep(
                agent_name=selected_agent,
                step_type="tool_call",
                content=f"Outil: {tc['tool']} — Args: {json.dumps(tc['args'], ensure_ascii=False)}",
                tool_name=tc['tool'],
            ))

        blackboard.store("Primary_Agent_Output", specialist_draft, selected_agent)

        steps.append(OrchestratorStep(
            agent_name=selected_agent,
            step_type="specialist",
            content=specialist_draft[:500] + ("..." if len(specialist_draft) > 500 else ""),
            duration_ms=(time.time() - t1) * 1000
        ))

        # ── 3. EXECUTION DU SPÉCIALISTE SECONDAIRE (SI PRÉSENT) ────────
        secondary_draft = ""
        if secondary_agent:
            t_sec = time.time()
            logger.info(f"[{secondary_agent}] Handoff de données partagées (Blackboard)...")
            steps.append(OrchestratorStep(
                agent_name=selected_agent,
                step_type="handoff",
                content=f"Transfert du contexte et des découvertes vers {secondary_agent}",
            ))

            agent2 = self.specialists[secondary_agent]
            sec_query = (
                f"Question de l'utilisateur: {query}\n\n"
                f"Découvertes et données de {selected_agent}:\n{specialist_draft}\n\n"
                f"Complète l'analyse avec tes compétences spécialisées ({secondary_agent})."
            )
            secondary_draft = agent2.call_llm(sec_query)

            for tc in agent2._tool_call_log:
                steps.append(OrchestratorStep(
                    agent_name=secondary_agent,
                    step_type="tool_call",
                    content=f"Outil: {tc['tool']} — Args: {json.dumps(tc['args'], ensure_ascii=False)}",
                    tool_name=tc['tool'],
                ))

            blackboard.store("Secondary_Agent_Output", secondary_draft, secondary_agent)

            steps.append(OrchestratorStep(
                agent_name=secondary_agent,
                step_type="specialist",
                content=secondary_draft[:500] + ("..." if len(secondary_draft) > 500 else ""),
                duration_ms=(time.time() - t_sec) * 1000
            ))

        # Extraire les sources
        combined_text = specialist_draft + "\n" + secondary_draft
        for match in re.finditer(r'\[Source:\s*([^\]]+)\]', combined_text):
            src = match.group(1).strip()
            if src not in all_sources:
                all_sources.append(src)

        # ── 4. EVALUATION DU CRITIC ─────────────────────────
        t2 = time.time()
        logger.info("[CRITIC] Synthèse et vérification de la chaîne d'agents...")
        if secondary_draft:
            critic_query = (
                f"Question initiale de l'utilisateur: {query}\n\n"
                f"Analyse de l'Agent 1 ({selected_agent}):\n{specialist_draft}\n\n"
                f"Analyse complémentaire de l'Agent 2 ({secondary_agent}):\n{secondary_draft}\n\n"
                f"Synthétise et valide ces 2 analyses en une réponse unifiée et structurée en Markdown (en français)."
            )
        else:
            critic_query = (
                f"Question initiale de l'utilisateur: {query}\n\n"
                f"Réponse du spécialiste ({selected_agent}):\n{specialist_draft}\n\n"
                f"Vérifie et améliore cette réponse."
            )

        final_answer = self.critic.call_llm(critic_query)

        steps.append(OrchestratorStep(
            agent_name="CRITIC",
            step_type="critic",
            content="Réponse synthétisée et validée.",
            duration_ms=(time.time() - t2) * 1000
        ))

        return OrchestratorResult(
            answer=final_answer,
            steps=steps,
            sources=all_sources,
            total_time=round(time.time() - start_time, 2),
            model_used=AGENT_MODEL,
            selected_agent=selected_agent,
            secondary_agent=secondary_agent,
            collaboration_chain=collaboration_chain,
            blackboard_summary=blackboard.get_summary()
        )


        # Extraire aussi les sources du critic
        for match in re.finditer(r'\[Source:\s*([^\]]+)\]', final_answer):
            src = match.group(1).strip()
            if src not in all_sources:
                all_sources.append(src)

        total_time = round(time.time() - start_time, 2)
        logger.info(f"[ORCHESTRATOR] Pipeline terminé en {total_time}s")

        return OrchestratorResult(
            answer=final_answer,
            steps=steps,
            sources=all_sources,
            total_time=total_time,
            iterations=1,
            model_used=AGENT_MODEL,
            selected_agent=selected_agent,
        )


# ── 5. COMPATIBILITÉ AVEC L'INTERFACE EXISTANTE ─────────────

class MultiAgentReasoningAgent:
    """Wrapper compatible avec l'ancienne interface ReasoningAgent.
    
    Permet de remplacer ReasoningAgent dans api_enhanced.py
    sans modifier les appelants.
    """

    def __init__(self, model: str = None, max_iterations: int = 6):
        self.orchestrator = MasterOrchestrator()
        self.tools = AGENT_TOOLS  # Pour compatibilité avec api_enhanced.py qui vérifie len(self.tools)
        self.model = model or AGENT_MODEL
        self.max_iterations = max_iterations

    def run(self, query: str, discipline: str = ""):
        """Interface compatible avec ReasoningAgent.run()."""
        from reasoning_agent import AgentResult, AgentStep
        
        res = self.orchestrator.run(query, discipline)
        
        # Convertir OrchestratorStep → AgentStep pour compatibilité
        agent_steps = []
        for s in res.steps:
            agent_steps.append(AgentStep(
                step_type=s.step_type,
                content=s.content,
                tool_name=s.tool_name,
                duration_ms=s.duration_ms,
            ))

        return AgentResult(
            answer=res.answer,
            steps=agent_steps,
            sources=res.sources,
            total_time=res.total_time,
            iterations=res.iterations,
            model_used=res.model_used,
            selected_agent=res.selected_agent,
        )


_multi_agent_instance = None
_multi_agent_lock = __import__("threading").Lock()

def get_reasoning_agent() -> MultiAgentReasoningAgent:
    """Retourne une instance singleton de MultiAgentReasoningAgent."""
    global _multi_agent_instance
    if _multi_agent_instance is None:
        with _multi_agent_lock:
            if _multi_agent_instance is None:
                _multi_agent_instance = MultiAgentReasoningAgent()
    return _multi_agent_instance



# ── TEST STANDALONE ──────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    
    print("=" * 60)
    print("  TEST MULTI-AGENT ORCHESTRATOR v2.0")
    print("=" * 60)
    
    orc = MasterOrchestrator()
    
    # Test 1: Question documentaire
    print("\n--- TEST 1: Question documentaire ---")
    res = orc.run("Quelle est la pression de design de la pompe P-101 ?")
    print(f"Agent: {res.selected_agent}")
    print(f"Réponse: {res.answer[:300]}...")
    print(f"Sources: {res.sources}")
    print(f"Temps: {res.total_time}s")
    
    print("\n" + "=" * 60)
    print("  TEST TERMINÉ")
    print("=" * 60)
