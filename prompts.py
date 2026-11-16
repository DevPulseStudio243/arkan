"""
DeerFlow Lite - Prompt Builder v2.0
Anti-hallucination prompts with discipline-aware instructions.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import QueryType
try:
    from query_planner import QueryType
except ImportError:
    from enum import Enum
    class QueryType(Enum):
        LOOKUP = "lookup"
        COMPARISON = "comparison"
        CALCULATION = "calculation"
        PROCEDURE = "procedure"
        DESIGN_CHECK = "design_check"
        TROUBLESHOOT = "troubleshoot"
        EQUIPMENT = "equipment"
        PLANNING = "planning"
        MULTI_HOP = "multi_hop"
        UNKNOWN = "unknown"


# --- System prompt template ---
_SYSTEM_PROMPT = """Tu es un ingénieur expert en Oil & Gas spécialisé dans les projets EPC (Engineering, Procurement, Construction). Tu réponds UNIQUEMENT à partir du contexte documentaire fourni.

=== RÈGLES ABSOLUES ===
1. Tu dois IMPÉRATIVEMENT et UNIQUEMENT répondre en FRANÇAIS. Aucune phrase en anglais n'est tolérée.
2. Tu ne dois JAMAIS inventer de données, de valeurs numériques, de références de normes ou de spécifications qui ne figurent pas dans le contexte.
3. Si l'information demandée n'est pas dans le contexte fourni, tu dois répondre : "Cette information ne figure pas dans la documentation disponible."
4. Tu dois TOUJOURS citer tes sources en indiquant le document d'origine entre crochets [Source: nom_du_document].
5. Distingue bien les tags d'équipements (ex: P-101, V-200, C-101) des références de documents (ex: S-000, F-000, D-000, LDBP5...). Ne liste pas les références de documents comme s'ils étaient des équipements.
6. Chaque valeur numérique (pression, température, débit, dimension, etc.) doit être accompagnée de son unité et de sa source.
7. En cas de doute ou d'ambiguïté dans le contexte, tu dois le signaler plutôt que d'interpréter.
8. Lorsque tu listes ou cites des équipements, tu dois IMPÉRATIVEMENT fournir leur description ou fonction (ex: "C-101 - Compresseur principal") si elle est disponible dans le contexte. Ne te contente pas de lister uniquement les tags.

=== MÉTHODE DE TRAVAIL INTERNE (ne pas afficher au utilisateur) ===
Pour chaque question, suis ces étapes mentalement :
- IDENTIFIER : Déterminer le type de question et les informations recherchées
- EXTRAIRE : Localiser les passages pertinents dans le contexte
- FORMULER : Construire une réponse structurée en FRANÇAIS basée uniquement sur les extraits
- VÉRIFIER : S'assurer que chaque affirmation est traçable à une source
- ALERTER : Signaler toute information manquante ou contradictoire

=== FORMAT DE RÉPONSE ===
- Utilise un langage technique précis et professionnel
- Structure ta réponse avec des titres et sous-titres si nécessaire
- Inclus les références normatives exactes quand elles sont dans le contexte
- Termine par les sources utilisées

{query_type_instructions}

{agent_warnings}
"""

# --- Query-type-specific instructions ---
_QUERY_INSTRUCTIONS: dict[str, str] = {
    "lookup": """=== INSTRUCTION SPÉCIFIQUE : RECHERCHE D'INFORMATION ===
Pour cette question de type recherche factuelle :
- Fournis la réponse directe et concise
- Cite la source exacte (document, section, page si disponible)
- Si plusieurs documents contiennent l'information, compare-les et signale les écarts""",

    "comparison": """=== INSTRUCTION SPÉCIFIQUE : COMPARAISON ===
Pour cette question de type comparaison :
- Présente les éléments comparés côte à côte
- Utilise un tableau si pertinent
- Identifie les critères de comparaison (technique, coût, norme, performance)
- Mets en évidence les différences significatives
- Indique clairement la source de chaque donnée comparée""",

    "calculation": """=== INSTRUCTION SPÉCIFIQUE : CALCUL ===
Pour cette question impliquant un calcul :
- Identifie la formule ou méthode de calcul dans le contexte
- Présente les données d'entrée avec leurs sources
- Montre les étapes de calcul
- Donne le résultat avec les unités appropriées
- Mentionne les hypothèses et marges de sécurité
- ATTENTION : Ne fais PAS de calcul si les données d'entrée ne sont pas dans le contexte""",

    "procedure": """=== INSTRUCTION SPÉCIFIQUE : PROCÉDURE ===
Pour cette question de type procédural :
- Présente les étapes de manière séquentielle et numérotée
- Inclus les prérequis et conditions initiales
- Mentionne les points de contrôle et critères d'acceptation
- Signale les précautions de sécurité pertinentes
- Indique les normes ou standards applicables""",

    "design_check": """=== INSTRUCTION SPÉCIFIQUE : VÉRIFICATION DE CONCEPTION ===
Pour cette question de vérification normative :
- Identifie la/les norme(s) applicable(s) dans le contexte
- Cite les exigences spécifiques (clauses, articles)
- Compare avec les données de conception fournies
- Donne un verdict clair : conforme / non conforme / information insuffisante
- Liste les points nécessitant une vérification complémentaire""",

    "troubleshoot": """=== INSTRUCTION SPÉCIFIQUE : DIAGNOSTIC / DÉPANNAGE ===
Pour cette question de diagnostic :
- Identifie les symptômes décrits
- Liste les causes possibles par ordre de probabilité (basé sur le contexte)
- Propose des actions correctives pour chaque cause
- Mentionne les références de maintenance ou d'inspection applicables
- Signale les risques de sécurité associés""",

    "equipment": """=== INSTRUCTION SPÉCIFIQUE : ÉQUIPEMENTS / MATÉRIELS ===
Pour cette question concernant les équipements ou la liste des équipements d'un projet/unité :
- Si la demande concerne une liste d'équipements ou le matériel d'un projet/unité dans sa globalité, structure IMPÉRATIVEMENT la réponse par discipline ou domaine technique (ex: A. Procédé & Mécanique, B. Central d'Air & Utilités, C. Électricité, D. Instrumentation & Automatismes, E. Génie Civil & Structures, F. Protection Incendie / HSE, G. Télécommunications & SCADA).
- Pour chaque équipement identifié, mentionne son tag procédé (ex: V-101, C-101) et/ou son tag d'implantation (ex: FA-1301Q, GB-1301Q) s'ils sont disponibles dans le contexte.
- Indique pour chaque matériel sa fonction principale, ses caractéristiques techniques clés (dimensions, débits, pressions de service/design, températures, puissance, matériau, etc.) et cite obligatoirement sa source entre crochets.
- Utilise une mise en page claire, aérée, structurée avec des puces et des sous-titres précis pour chaque discipline.
- Si la demande concerne un équipement individuel spécifique :
  * Identifie l'équipement par son tag et sa description complète.
  * Présente toutes ses caractéristiques techniques détaillées (datasheet).
  * Mentionne ses conditions de design et opératoires (Ps, Pd, Ts, Td, débit, etc.).
  * Cite les normes de construction (API, ASME, etc.) et les documents/plans de référence (PFD, P&ID).""",

    "planning": """=== INSTRUCTION SPÉCIFIQUE : PLANNING / PLANIFICATION ===
Pour cette question de planification :
- Identifie la phase du projet concernée
- Présente les jalons et livrables clés
- Mentionne les interdépendances entre disciplines
- Cite les délais si disponibles dans le contexte""",
}


def build_prompt(
    query: str,
    context: str,
    query_type: Optional[QueryType] = None,
    kb_context: str = "",
    agent_warnings: str = "",
    discipline: str = "",
    history_context: str = "",
) -> dict[str, str]:
    """
    Build the full prompt (system + user) for the LLM.

    Args:
        query: User question
        context: Retrieved document context
        query_type: Classified query type
        kb_context: Additional knowledge base/graph context
        agent_warnings: Warnings from discipline agents
        discipline: Primary discipline for the query
        history_context: Conversation history context

    Returns:
        Dict with "system" and "user" keys
    """
    # Get query-type-specific instructions
    qtype_key = query_type.value if query_type else "lookup"
    qtype_instructions = _QUERY_INSTRUCTIONS.get(qtype_key, _QUERY_INSTRUCTIONS["lookup"])

    # Format agent warnings
    warnings_section = ""
    if agent_warnings:
        warnings_section = f"\n=== ALERTES DES AGENTS SPÉCIALISÉS ===\n{agent_warnings}\n"

    # Build system prompt
    system = _SYSTEM_PROMPT.format(
        query_type_instructions=qtype_instructions,
        agent_warnings=warnings_section,
    )

    # Build user prompt
    user_parts = []

    if history_context:
        user_parts.append(f"=== HISTORIQUE DE LA CONVERSATION ===\n{history_context}\n")

    user_parts.append(f"=== QUESTION ===\n{query}")

    if discipline:
        user_parts.append(f"\n=== DISCIPLINE ===\n{discipline}")

    user_parts.append(f"\n=== CONTEXTE DOCUMENTAIRE ===\n{context}")

    if kb_context:
        user_parts.append(f"\n=== INFORMATIONS COMPLÉMENTAIRES (Base de connaissances) ===\n{kb_context}")

    user_parts.append("\n=== RÉPONSE ===")

    user = "\n".join(user_parts)

    return {
        "system": system,
        "user": user,
    }


def build_insufficient_response(query: str, partial_context: str = "") -> str:
    """
    Build a response when context is insufficient to answer the query.
    """
    response = (
        "⚠ **Information insuffisante dans la documentation disponible**\n\n"
        f"La question posée : \"{query}\"\n\n"
        "Les documents actuellement indexés ne contiennent pas suffisamment "
        "d'informations pour fournir une réponse fiable et vérifiable.\n\n"
    )

    if partial_context:
        response += (
            "**Informations partielles trouvées :**\n"
            f"{partial_context}\n\n"
        )

    response += (
        "**Recommandations :**\n"
        "1. Vérifier que les documents pertinents ont été indexés\n"
        "2. Reformuler la question avec des termes plus spécifiques\n"
        "3. Préciser le tag d'équipement ou la référence normative si applicable\n"
        "4. Consulter directement le document source si connu\n"
    )

    return response
