"""
DeerFlow Lite — Multi-Agent Reasoning System v2.0
Architecture découpée autour de Qwen 14B pour éviter la surcharge cognitive.
Implémente le Native Tool Calling d'Ollama.
"""

import json
import logging
import time
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://127.0.0.1:11434"

AGENT_MODEL = "qwen2.5:14b"
AGENT_TIMEOUT = 300.0  # Qwen 14B peut être long au chargement initial

# Importation des outils existants
from reasoning_agent import (
    tool_search_documents, tool_search_keywords, tool_analyze_engineering_pdf, tool_analyze_image_vision,
    tool_query_knowledge_graph, tool_get_project_equipments, tool_analyze_impact_neo4j,
    tool_compute_evm, tool_analyze_planning_risk, tool_generate_diagram
)
from reasoning_agent import AGENT_TOOLS

# ── 1. OUTILS DYNAMIQUES ET CONVERSION JSON SCHEMA ────────────

def convert_to_ollama_tools(tool_names: list[str]) -> list[dict]:
    """Convertit une liste de noms d'outils du dictionnaire AGENT_TOOLS au format Ollama."""
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

# Définition des spécialités
DOCUMENT_TOOL_NAMES = ["search_documents", "search_keywords", "analyze_engineering_pdf", "analyze_image_vision"]
GRAPH_TOOL_NAMES = ["query_knowledge_graph", "get_project_equipments", "analyze_impact_neo4j"]
PLANNING_TOOL_NAMES = ["compute_evm", "analyze_planning_risk", "generate_diagram"]

# ── 2. PROMPTS SPECIALISES ────────────────────────────────────

ROUTER_PROMPT = """Tu es le Superviseur DeerFlow.
Ton rôle est d'analyser la question de l'utilisateur et de choisir le meilleur Agent pour y répondre.
Tu DOIS répondre avec un objet JSON strictement formaté. N'ajoute AUCUN texte hors du JSON.

AGENTS :
- DOCUMENT_AGENT : Recherche textes, normes, manuels, PDF, mots-clés.
- GRAPH_AGENT : Relations équipements (impact, liste de matériels, P&ID).
- PLANNING_AGENT : Coûts, planning, risques, diagrammes.
- DIRECT_ANSWER : Salutations ou questions simples.

Format attendu :
{
    "reasoning": "Pourquoi je choisis cet agent",
    "selected_agent": "NOM_AGENT"
}"""

DOCUMENT_AGENT_PROMPT = """Tu es l'Agent Documentaire DeerFlow.
Ta spécialité : Trouver l'information exacte dans la base vectorielle et BM25.
Utilise tes outils. Cite toujours tes sources avec [Source: xyz].
Réponds en français, de manière précise et technique. Ne conclus rien sans appeler un outil."""

GRAPH_AGENT_PROMPT = """Tu es l'Agent Architecte Neo4j DeerFlow.
Ta spécialité : Naviguer dans le Knowledge Graph.
Trouve les impacts ou liste les équipements avec tes outils.
Réponds en français. Ne fais pas de suppositions sans appeler un outil."""

PLANNING_AGENT_PROMPT = """Tu es l'Agent Planning & Coûts DeerFlow.
Ta spécialité : Calculs EVM, risques et diagrammes.
Réponds en français. Fais les calculs avec précision."""

CRITIC_PROMPT = """Tu es l'Agent Évaluateur Final (Critic) de DeerFlow.
On va te donner la question initiale et la réponse technique générée par un agent spécialiste.
Vérifie :
1. Que la réponse répond bien à la question.
2. Qu'il n'y a pas d'invention.
Rédige la réponse finale en Markdown propre (en français)."""

# ── 3. CLASSE BASE AGENT AVEC TOOL CALLING NATIVE ─────────────

class BaseQwenAgent:
    """Agent utilisant l'API Chat d'Ollama avec Native Tool Calling."""
    
    def __init__(self, system_prompt: str, allowed_tool_names: list[str] = None):
        self.system_prompt = system_prompt
        self.allowed_tool_names = allowed_tool_names or []
        self.ollama_tools = convert_to_ollama_tools(self.allowed_tool_names)
        self.client = httpx.Client(timeout=AGENT_TIMEOUT)

    def _execute_tool(self, tool_name: str, arguments: dict) -> str:
        """Exécute physiquement la fonction Python associée."""
        if tool_name not in AGENT_TOOLS:
            return f"Error: Tool {tool_name} not found."
        
        try:
            fn = AGENT_TOOLS[tool_name]["fn"]
            return fn(**arguments)
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return f"Error executing tool {tool_name}: {str(e)}"

    def call_llm(self, user_query: str, response_format=None) -> str:
        """Appelle le LLM. Gère automatiquement la boucle des appels d'outils."""
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
            
        MAX_TOOL_ITERATIONS = 4
        iterations = 0
        
        while iterations < MAX_TOOL_ITERATIONS:
            iterations += 1
            payload["messages"] = messages
            
            try:
                print(f"Requesting URL: {OLLAMA_BASE_URL}/api/chat")
                resp = self.client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Ollama API Error: {e}")
                return "{}" if response_format == "json" else f"Erreur LLM: {e}"
                
            message = data.get("message", {})
            messages.append(message)
            
            # Si le modèle veut appeler un outil
            if "tool_calls" in message and message["tool_calls"]:
                for tool_call in message["tool_calls"]:
                    fn_name = tool_call["function"]["name"]
                    fn_args = tool_call["function"]["arguments"]
                    
                    print(f"  [Native Tool] LLM appelle '{fn_name}' avec {fn_args}")
                    result = self._execute_tool(fn_name, fn_args)
                    
                    # On ajoute le résultat au contexte
                    messages.append({
                        "role": "tool",
                        "content": str(result),
                        "name": fn_name
                    })
                # On boucle : le LLM va lire les rôles "tool" et répondre
            else:
                # S'il n'y a pas d'outil appelé, on retourne le texte final
                return message.get("content", "")
                
        return "Erreur: Nombre maximum d'appels d'outils dépassé."


# ── 4. ORCHESTRATEUR PRINCIPAL ────────────────────────────────

class MasterOrchestrator:
    """Gère le routage et délègue aux sous-agents."""
    
    def __init__(self):
        self.router = BaseQwenAgent(system_prompt=ROUTER_PROMPT)
        self.specialists = {
            "DOCUMENT_AGENT": BaseQwenAgent(DOCUMENT_AGENT_PROMPT, DOCUMENT_TOOL_NAMES),
            "GRAPH_AGENT": BaseQwenAgent(GRAPH_AGENT_PROMPT, GRAPH_TOOL_NAMES),
            "PLANNING_AGENT": BaseQwenAgent(PLANNING_AGENT_PROMPT, PLANNING_TOOL_NAMES),
        }
        self.critic = BaseQwenAgent(system_prompt=CRITIC_PROMPT)

    def run(self, query: str) -> dict:
        start_time = time.time()
        print(f"\n[ORCHESTRATOR] Question : {query}")
        
        # 1. ROUTING
        print("[ROUTER] Analyse de l'intention...")
        router_response = self.router.call_llm(query, response_format="json")
        
        try:
            route_data = json.loads(router_response)
            selected_agent = route_data.get("selected_agent", "DOCUMENT_AGENT")
            reasoning = route_data.get("reasoning", "")
        except:
            selected_agent = "DOCUMENT_AGENT"
            reasoning = "Fallback par défaut."
            
        print(f"[ROUTER] Décision : {selected_agent} (Raison : {reasoning})")
        
        if selected_agent == "DIRECT_ANSWER":
            return {
                "answer": "Bonjour ! Comment puis-je vous aider avec vos données d'ingénierie ?",
                "model_used": AGENT_MODEL,
                "total_time": round(time.time() - start_time, 2)
            }
            
        if selected_agent not in self.specialists:
            selected_agent = "DOCUMENT_AGENT"

        # 2. EXECUTION DU SPECIALISTE
        agent = self.specialists[selected_agent]
        print(f"[{selected_agent}] Début de la réflexion avec outils...")
        specialist_draft = agent.call_llm(query)
        print(f"[{selected_agent}] Brouillon généré.")
        
        # 3. EVALUATION DU CRITIC
        print("[CRITIC] Vérification de la réponse...")
        critic_query = f"Question initiale: {query}\n\nRéponse du spécialiste:\n{specialist_draft}\n\nAméliore et valide cette réponse."
        final_answer = self.critic.call_llm(critic_query)
        
        return {
            "answer": final_answer,
            "model_used": AGENT_MODEL,
            "iterations": 1,
            "sources": [],  # Extraction à faire dans la réponse
            "total_time": round(time.time() - start_time, 2),
            "steps": []     # Log simplifié pour l'interface
        }

# Mock de ReasoningAgent pour remplacer l'ancienne classe
class ReasoningAgent:
    def __init__(self, model: str = None, max_iterations: int = 6):
        self.orchestrator = MasterOrchestrator()
        
    def run(self, query: str, discipline: str = ""):
        # Compatibility with old interface
        # Returns an object that has `.answer` at least.
        # En production, on devrait retourner un vrai AgentResult
        from dataclasses import dataclass
        @dataclass
        class AgentResult:
            answer: str
            total_time: float
            model_used: str
            sources: list
            steps: list
        
        res = self.orchestrator.run(query)
        return AgentResult(
            answer=res["answer"],
            total_time=res["total_time"],
            model_used=res["model_used"],
            sources=[],
            steps=[]
        )

if __name__ == "__main__":
    print("--- TEST ORCHESTRATOR ---")
    orc = MasterOrchestrator()
    res = orc.run("Quel est l'impact de la pompe P-101 ?")
    print("\n--- FINAL ANSWER ---")
    print(res["answer"])
    print(f"Time: {res['total_time']}s")
