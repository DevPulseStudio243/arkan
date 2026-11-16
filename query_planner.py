"""
DeerFlow Lite - Query Planner v2.0
Semantic intent detection + multi-step query decomposition.
"""
import re
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


class QueryType(Enum):
    LOOKUP = "lookup"              # Simple fact retrieval
    COMPARISON = "comparison"      # Compare entities/specs
    CALCULATION = "calculation"    # Compute values
    PROCEDURE = "procedure"       # Step-by-step process
    DESIGN_CHECK = "design_check" # Norm/code verification
    TROUBLESHOOT = "troubleshoot" # Problem diagnosis
    EQUIPMENT = "equipment"       # Equipment-specific query
    PLANNING = "planning"         # Project planning query
    MULTI_HOP = "multi_hop"      # Requires chaining multiple facts
    UNKNOWN = "unknown"


@dataclass
class SubQuery:
    """A decomposed sub-question with routing metadata."""
    text: str
    query_type: QueryType
    discipline: str = ""
    equipment_tags: list[str] = field(default_factory=list)
    priority: int = 1


@dataclass
class RetrievalPlan:
    """Plan for executing a complex query."""
    original_query: str
    query_type: QueryType
    sub_queries: list[SubQuery]
    equipment_tags: list[str]
    disciplines: list[str]
    is_complex: bool = False
    requires_calculation: bool = False
    is_pid_query: bool = False   # True si la question concerne un P&ID/plan technique


# --- Intent patterns (scored, not just counted) ---
_INTENT_PATTERNS: dict[QueryType, list[tuple[str, float]]] = {
    QueryType.COMPARISON: [
        (r'\b(comparer|comparaison|compar[ée]|différence|versus|vs\.?|par rapport)\b', 2.0),
        (r'\b(plus|moins|meilleur|pire)\b.*\b(que)\b', 0.8),
        (r'\b(avantage|inconvénient)\b', 0.7),
    ],
    QueryType.CALCULATION: [
        (r'\b(calculer|calcul|dimensionner|dimensionnement|formule|équation)\b', 1.5),
        (r'\bcombien\b', 0.8),
        (r'\b(surface|volume|poids|masse|longueur|épaisseur|diamètre)\b.*\b(calcul|dimensionn|minimum|maximum)\b', 0.6),
        (r'\d+\s*[\+\-\*\/×÷]\s*\d+', 0.9),
    ],
    QueryType.PROCEDURE: [
        (r'\b(comment|procédure|étape|méthode|processus)\b', 1.0),
        (r'\b(installer|démonter|réparer|remplacer|inspecter|tester)\b', 0.9),
        (r'\b(mise en service|commissioning|démarrage|arrêt)\b', 0.8),
    ],
    QueryType.DESIGN_CHECK: [
        (r'\b(conforme|conformité|norme|standard|code|spécification)\b', 1.0),
        (r'\b(API|ASME|ISO|EN|NF|NFPA|IEC|ATEX)\s*\d', 1.0),
        (r'\b(exigence|critère|requis|obligatoire|interdit)\b', 0.7),
        (r'\b(vérif|valid|certif)\b', 0.8),
    ],
    QueryType.TROUBLESHOOT: [
        (r'\b(problème|panne|défaut|fuite|vibration|bruit|erreur)\b', 1.0),
        (r'\b(pourquoi|cause|origine|raison)\b', 0.8),
        (r'\b(diagnostic|dépannage|troubleshoot)\b', 1.0),
        (r'\b(ne\s+(?:fonctionne|marche|démarre)\s+(?:pas|plus))\b', 0.9),
    ],
    QueryType.EQUIPMENT: [
        (r'\b[A-Z]{1,3}-\d{2,4}[A-Z]?\b', 0.4),  # Equipment tags (low weight to not dominate intent)
        (r'\b(pompe|vanne|échangeur|compresseur|turbine|réacteur|colonne|ballon|séparateur)\b', 0.3),
        (r'\b(P&ID|PFD|datasheet|fiche technique)\b', 0.7),
        (r'\b(caractéristiques?|spécifications?|datasheet)\b', 0.8),
        (r'\b(équipements?|equipements?|matériels?|materiels?)\b', 1.0),
    ],
    QueryType.PLANNING: [
        (r'\b(planning|calendrier|délai|échéancier|jalons?)\b', 1.0),
        (r'\b(phase|lot|work\s*package|WBS)\b', 0.8),
        (r'\b(FEED|EPC|APD|APS|construction|fabrication)\b', 0.6),
    ],
}

# Discipline detection patterns
_DISCIPLINE_PATTERNS: dict[str, list[str]] = {
    "piping": [r'\b(tuyauterie|piping|pipe|tuyau|raccord|bride|joint|isométrique|ISO\s*\d|spool)\b',
               r'\b(P&ID|PID)\b', r'\b(DN\s*\d|NPS\s*\d|schedule|Sch)\b'],
    "process": [r'\b(procédé|process|PFD|bilan|heat\s*balance|mass\s*balance)\b',
                r'\b(débit|pression|température|flow|pressure|temp)\b.*\b(design|opérat)\b'],
    "instrumentation": [r'\b(instrument|capteur|transmetteur|régulat|boucle|loop|DCS|PLC|SIS|ESD)\b',
                        r'\b(PT|TT|FT|LT|PDT|PIC|TIC|FIC|LIC)\s*[-]?\d', r'\b(4-20\s*mA|HART|Profibus)\b'],
    "mechanical": [r'\b(mécanique|mechanical|rotating|statique|static)\b',
                   r'\b(pompe|compresseur|turbine|ventilat|moteur|pump|compressor)\b'],
    "electrical": [r'\b(électri|electric|câble|cable|transfo|disjoncteur|MCC|switchgear)\b',
                   r'\b(HT|BT|MT|kV|kW|MW|ampère)\b'],
    "civil": [r'\b(génie civil|civil|béton|fondation|structure|charpente|bâtiment)\b',
              r'\b(ferraillage|coffrage|terrassement|remblai)\b'],
    "hse": [r'\b(HSE|sécurité|safety|environnement|HAZOP|SIL|ATEX|incendie|fire)\b',
            r'\b(risque|danger|protection|prévention|EPI|PPE)\b'],
}


def classify_query(query: str) -> QueryType:
    """
    Classify query intent using weighted pattern matching.
    Returns the QueryType with the highest accumulated score.
    """
    scores: dict[QueryType, float] = {}
    query_lower = query.lower()

    for qtype, patterns in _INTENT_PATTERNS.items():
        total_score = 0.0
        for pattern, weight in patterns:
            matches = re.findall(pattern, query_lower, re.IGNORECASE)
            if matches:
                total_score += weight * len(matches)
        if total_score > 0:
            scores[qtype] = total_score

    if not scores:
        # Default: LOOKUP for questions, UNKNOWN for statements
        if re.search(r'[?？]|^(quel|quelle|qu\'|comment|pourquoi|où|quand|combien)', query_lower):
            return QueryType.LOOKUP
        return QueryType.UNKNOWN

    return max(scores, key=scores.get)


def detect_disciplines(query: str) -> list[str]:
    """Detect relevant engineering disciplines from query content."""
    query_lower = query.lower()
    detected = []

    for discipline, patterns in _DISCIPLINE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, query_lower, re.IGNORECASE):
                detected.append(discipline)
                break

    return detected


def extract_equipment_tags(query: str) -> list[str]:
    """
    Extrait les tags techniques O&G depuis une question.
    
    Supporte :
    - Tags équipement : P-101, V-200A, E-301B, TK-1001
    - Tags instruments : FT-2301, PIC-100, LIC-3005A
    - Lignes tuyauterie : 2"-CS-150-P-101, 6"-SS-300-HC-001
    - Tags à lettres multiples : PSV-101, SDV-202, MOV-305
    """
    tags_found = set()

    # 1. Tags équipement classiques (P-101, V-200A, E-301, TK-1001, etc.)
    tags_found.update(re.findall(r'\b([A-Z]{1,4}-\d{2,5}[A-Z]?(?:-[A-Z0-9]+)?)\b', query.upper()))

    # 2. Tags instruments étendus (FIC-2301, PIC-100, LIC-3005A, PSHH-101)
    tags_found.update(re.findall(r'\b([A-Z]{2,5}-\d{3,5}[A-Z]?)\b', query.upper()))

    # 3. Numéros de ligne tuyauterie (ex: 2"-CS-150-P-101, 6"-SS-300-HC-001)
    tags_found.update(re.findall(r'\b(\d{1,4}"-[A-Z0-9]+-\d{3,4}-[A-Z0-9-]+)\b', query.upper()))

    # 4. Tags numériques seuls avec contexte (ex: "ligne 2052", "pompe P101")
    tags_found.update(re.findall(r'\b(?:pompe|vanne|ballon|échangeur|colonne|tank)\s+([A-Z0-9-]{3,10})\b', query.upper()))

    # Filtrer les tags trop courts ou non pertinents
    return [t for t in tags_found if len(t) >= 3 and not t.isdigit()]


def decompose_query(query: str) -> list[SubQuery]:
    """
    Decompose a complex query into sub-queries.
    Preserves shared context across sub-queries.
    """
    # Detect shared context (equipment tags, discipline references)
    shared_tags = extract_equipment_tags(query)
    shared_disciplines = detect_disciplines(query)
    shared_context = ""
    if shared_tags:
        shared_context = f" (équipement: {', '.join(shared_tags)})"

    # Split on conjunctions and semicolons, preserving context
    # Pattern: split on "et", "ainsi que", "également", ";", "," (in list context)
    parts = re.split(r'\s*(?:;|\bet\b|\bainsi que\b|\bégalement\b)\s*', query)

    # If only one part or very short parts, don't decompose
    if len(parts) <= 1 or all(len(p.split()) < 3 for p in parts[1:]):
        sub = SubQuery(
            text=query,
            query_type=classify_query(query),
            discipline=shared_disciplines[0] if shared_disciplines else "",
            equipment_tags=shared_tags
        )
        return [sub]

    sub_queries = []
    for i, part in enumerate(parts):
        part = part.strip()
        if not part or len(part) < 5:
            continue

        # Add shared context if missing from this sub-part
        enriched = part
        for tag in shared_tags:
            if tag not in part.upper():
                enriched += shared_context
                break

        sub = SubQuery(
            text=enriched,
            query_type=classify_query(enriched),
            discipline=detect_disciplines(enriched)[0] if detect_disciplines(enriched) else (shared_disciplines[0] if shared_disciplines else ""),
            equipment_tags=extract_equipment_tags(enriched) or shared_tags,
            priority=1 if i == 0 else 2
        )
        sub_queries.append(sub)

    return sub_queries


def plan_retrieval(query: str) -> RetrievalPlan:
    """
    Create a full retrieval plan for a user query.

    This is the main entry point for the query planner. It:
    1. Classifies the query intent
    2. Extracts equipment tags and disciplines
    3. Decomposes complex queries
    4. Détecte si la question concerne un P&ID/plan technique (is_pid_query)
    5. Returns a plan with routing metadata
    """
    query_type = classify_query(query)
    equipment_tags = extract_equipment_tags(query)
    disciplines = detect_disciplines(query)
    sub_queries = decompose_query(query)

    is_complex = len(sub_queries) > 1
    requires_calc = query_type == QueryType.CALCULATION

    # ── Détection P&ID / plan technique ──────────────────────────────
    # is_pid_query = True si la question porte sur un plan, un schéma ou un tag instrument/équipement
    _PID_KEYWORDS = re.compile(
        r'\b(P&ID|PID|PFD|isométrique|isometric|drawing|plan\s+de\s+tuyau|'
        r'ligne\s+de\s+tuyau|line\s+number|tag\s+instrument|boucle\s+de\s+contrôle|'
        r'loop|FT|PT|TT|LT|FIC|PIC|TIC|SDV|MOV|PSV|PRV|PSHH)\b',
        re.IGNORECASE
    )
    is_pid = bool(_PID_KEYWORDS.search(query))
    # Aussi P&ID si on a des tags instruments (FT-xxx, PIC-xxx) ou des tags équipements
    if not is_pid and equipment_tags:
        _INSTR_PAT = re.compile(r'^(FT|PT|TT|LT|PDT|FIC|PIC|TIC|LIC|FY|PY|TY|SDV|MOV|PSV|PRV|PSHH)-\d+', re.IGNORECASE)
        is_pid = any(_INSTR_PAT.match(t) for t in equipment_tags)
    # Ou si discipline piping/instrumentation détectée
    if not is_pid:
        is_pid = any(d in ("piping", "instrumentation") for d in disciplines)

    plan = RetrievalPlan(
        original_query=query,
        query_type=query_type,
        sub_queries=sub_queries,
        equipment_tags=equipment_tags,
        disciplines=disciplines,
        is_complex=is_complex,
        requires_calculation=requires_calc,
        is_pid_query=is_pid,
    )

    logger.info(
        "Query plan: type=%s, disciplines=%s, tags=%s, sub_queries=%d, is_pid=%s",
        query_type.value, disciplines, equipment_tags, len(sub_queries), is_pid
    )

    return plan
