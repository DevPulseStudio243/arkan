"""
DeerFlow Lite - Multi-Discipline Agent System v2.1
Specialized Oil & Gas agents with orchestration.
Nouvel agent: PlanningCostAgent — Planification & Cost Control.
"""
import re
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional, Protocol
from enum import Enum

logger = logging.getLogger(__name__)


class Discipline(Enum):
    PIPING = "piping"
    PROCESS = "process"
    INSTRUMENTATION = "instrumentation"
    MECHANICAL = "mechanical"
    ELECTRICAL = "electrical"
    HSE = "hse"
    CIVIL = "civil"
    DIAGRAM = "diagram"
    PLANNING = "planning"   # ← NOUVEAU : Planification & Cost Control
    VERIFICATION_CONSISTENCY = "verification_consistency"
    VERIFICATION_COMPLIANCE = "verification_compliance"
    VERIFICATION_DRAWING = "verification_drawing"
    GENERAL = "general"


@dataclass
class AgentContext:
    """Context enrichment from a discipline agent."""
    discipline: Discipline
    enriched_query: str
    additional_keywords: list[str]
    relevant_norms: list[str]
    expected_units: list[str]
    confidence: float = 0.0
    notes: str = ""


@dataclass
class AgentResponse:
    """Response from a discipline agent after post-processing."""
    discipline: Discipline
    answer: str
    validation_passed: bool
    warnings: list[str] = field(default_factory=list)
    referenced_norms: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class AgentResult:
    """Consolidated result from the orchestrator."""
    primary_agent: str
    secondary_agents: list[str]
    enriched_context: str
    validation_rules: list[str]
    cross_references: list[str]
    understanding: dict


class DisciplineAgent:
    """
    Base class for discipline-specific agents.
    Each agent knows its domain's norms, vocabulary, units, and validation rules.
    """

    def __init__(self, discipline: Discipline):
        self.discipline = discipline
        self._norms: list[str] = []
        self._keywords: list[str] = []
        self._units: list[str] = []
        self._validation_patterns: list[tuple[str, str]] = []  # (pattern, warning_msg)

    def enrich_query(self, query: str, equipment_tags: list[str] = None) -> AgentContext:
        """Add discipline-specific context to a query before retrieval."""
        additional_kw = []
        relevant_norms = []

        query_lower = query.lower()

        # Find relevant norms mentioned or implied
        for norm in self._norms:
            norm_pattern = re.escape(norm.split()[0]) if norm else ""
            if norm_pattern and re.search(norm_pattern, query, re.IGNORECASE):
                relevant_norms.append(norm)

        # Add discipline-specific keywords for query expansion
        for kw in self._keywords:
            if kw.lower() in query_lower:
                additional_kw.extend(self._get_related_terms(kw))

        # Enrich query with discipline context
        enriched = query
        if equipment_tags:
            tag_context = " ".join(equipment_tags)
            if tag_context not in query:
                enriched = f"{query} [équipement: {tag_context}]"

        return AgentContext(
            discipline=self.discipline,
            enriched_query=enriched,
            additional_keywords=additional_kw,
            relevant_norms=relevant_norms,
            expected_units=self._units,
            confidence=self._compute_relevance(query),
        )

    def validate_answer(self, query: str, answer: str, context: str) -> AgentResponse:
        """Validate and post-process an answer with discipline-specific rules."""
        warnings = []
        referenced_norms = []

        # Check for norm references in answer
        for norm in self._norms:
            if norm.split()[0].lower() in answer.lower():
                referenced_norms.append(norm)

        # Run validation patterns
        for pattern, warning_msg in self._validation_patterns:
            if re.search(pattern, answer, re.IGNORECASE):
                warnings.append(warning_msg)

        # Check unit consistency
        self._check_units(answer, warnings)

        validation_passed = len(warnings) == 0

        return AgentResponse(
            discipline=self.discipline,
            answer=answer,
            validation_passed=validation_passed,
            warnings=warnings,
            referenced_norms=referenced_norms,
            confidence=self._compute_relevance(query)
        )

    def _compute_relevance(self, query: str) -> float:
        """How relevant is this discipline to the query? 0.0 to 1.0."""
        query_lower = query.lower()
        score = 0.0
        matches = 0

        for kw in self._keywords:
            if kw.lower() in query_lower:
                matches += 1

        if self._keywords:
            score = min(matches / max(len(self._keywords) * 0.1, 1), 1.0)

        return score

    def _get_related_terms(self, term: str) -> list[str]:
        """Override in subclass for discipline-specific synonym expansion."""
        return []

    def _check_units(self, answer: str, warnings: list[str]):
        """Check for expected measurement units in answer."""
        pass


class PipingAgent(DisciplineAgent):
    def __init__(self):
        super().__init__(Discipline.PIPING)
        self._norms = [
            "ASME B31.3 Process Piping",
            "ASME B16.5 Pipe Flanges and Flanged Fittings",
            "ASME B16.9 Factory-Made Wrought Buttwelding Fittings",
            "ASME B16.47 Large Diameter Steel Flanges",
            "API 570 Piping Inspection Code",
            "API 574 Inspection Practices for Piping System Components",
            "ASTM A106 Seamless Carbon Steel Pipe",
            "ASTM A312 Seamless and Welded Austenitic Stainless Steel Pipes",
            "ASTM A333 Seamless and Welded Steel Pipe for Low-Temperature Service",
            "EN 13480 Metallic Industrial Piping",
            "PFI ES-7 Minimum Length and Spacing for Welded Nozzles",
        ]
        self._keywords = [
            "tuyauterie", "piping", "pipe", "tuyau", "raccord", "bride", "flange",
            "joint", "gasket", "isométrique", "spool", "support", "hanger",
            "dilatation", "expansion", "stress analysis", "flexibility",
            "soudure", "weld", "NPS", "DN", "schedule", "épaisseur", "wall thickness",
            "P&ID", "PID", "line list", "spec break", "pipe class",
            "valve", "vanne", "robinet", "clapet", "check valve",
        ]
        self._units = ["mm", "inch", "bar", "psi", "°C", "°F", "m/s", "kg/m"]
        self._validation_patterns = [
            (r'pression\s+(?:de\s+)?(\d+)\s*(?:bar|psi).*température\s+(?:de\s+)?(\d+)\s*°C',
             "Vérifier la cohérence pression-température selon les courbes P-T de la pipe class"),
            (r'vitesse\s+(?:de\s+)?(\d+)\s*m/s',
             "Vérifier que la vitesse d'écoulement est dans les limites (liquide <3m/s, gaz <20m/s)"),
        ]

    def _get_related_terms(self, term: str) -> list[str]:
        synonyms = {
            "bride": ["flange", "brides", "bride à collerette", "bride plate", "weld neck", "slip-on"],
            "vanne": ["valve", "robinet", "vanne à opercule", "gate valve", "ball valve", "globe valve"],
            "tuyauterie": ["piping", "pipe", "conduite", "ligne"],
            "soudure": ["weld", "soudage", "welding", "cordon de soudure"],
            "joint": ["gasket", "joint spiralé", "spiral wound", "ring joint", "RTJ"],
            "isométrique": ["isometric", "ISO drawing", "spool drawing"],
        }
        return synonyms.get(term.lower(), [])

    def _check_units(self, answer: str, warnings: list[str]):
        # Check for mixed unit systems
        has_metric = bool(re.search(r'\b(mm|bar|°C|m/s)\b', answer))
        has_imperial = bool(re.search(r'\b(inch|psi|°F|ft/s)\b', answer))
        if has_metric and has_imperial:
            warnings.append("Mélange d'unités métriques et impériales détecté - vérifier la cohérence")


class ProcessAgent(DisciplineAgent):
    def __init__(self):
        super().__init__(Discipline.PROCESS)
        self._norms = [
            "API 520 Sizing, Selection, and Installation of PRDs",
            "API 521 Pressure-Relieving and Depressuring Systems",
            "API 526 Flanged Steel PRVs",
            "API 2000 Venting Atmospheric and Low-Pressure Storage Tanks",
            "ASME Section VIII Pressure Vessels",
            "TEMA Standards for Heat Exchangers",
            "GPSA Engineering Data Book",
            "API 610 Centrifugal Pumps",
            "API 617 Axial and Centrifugal Compressors",
        ]
        self._keywords = [
            "procédé", "process", "PFD", "bilan", "balance", "heat balance", "mass balance",
            "débit", "flow rate", "pression", "pressure", "température", "temperature",
            "flash", "distillation", "séparation", "separation", "réaction", "reaction",
            "catalyseur", "catalyst", "rendement", "yield", "conversion",
            "HAZOP", "soupape", "relief valve", "PSV", "PRV",
            "échangeur", "heat exchanger", "condenseur", "reboiler",
        ]
        self._units = ["kg/h", "m³/h", "bar", "barg", "bara", "°C", "kW", "MW", "kcal/h"]
        self._validation_patterns = [
            (r'rendement\s+(?:de\s+)?(\d+)\s*%',
             "Vérifier que le rendement est réaliste pour le type de procédé"),
            (r'(?:pression|pressure)\s+(?:de\s+)?(\d+)\s*bar.*(?:design|conception)',
             "Vérifier la marge de design (typiquement +10% sur pression opératoire max)"),
        ]

    def _get_related_terms(self, term: str) -> list[str]:
        synonyms = {
            "débit": ["flow rate", "flowrate", "débit massique", "débit volumique"],
            "pression": ["pressure", "pression opératoire", "pression de design", "MAWP"],
            "échangeur": ["heat exchanger", "E-", "condenseur", "reboiler", "cooler", "heater"],
            "bilan": ["balance", "heat balance", "mass balance", "bilan matière", "bilan thermique"],
        }
        return synonyms.get(term.lower(), [])


class InstrumentationAgent(DisciplineAgent):
    def __init__(self):
        super().__init__(Discipline.INSTRUMENTATION)
        self._norms = [
            "ISA 5.1 Instrumentation Symbols and Identification",
            "IEC 61511 Functional Safety - SIS for Process Industry",
            "IEC 61508 Functional Safety of E/E/PE Systems",
            "IEC 60079 Explosive Atmospheres (ATEX)",
            "ISA 84 Application of Safety Instrumented Systems",
            "API 554 Process Instrumentation and Control",
            "ISA 75 Control Valve Standards",
            "NAMUR NE Standards",
        ]
        self._keywords = [
            "instrument", "capteur", "sensor", "transmetteur", "transmitter",
            "régulation", "control", "boucle", "loop", "DCS", "PLC", "SIS", "ESD",
            "4-20 mA", "HART", "Profibus", "Foundation Fieldbus", "Modbus",
            "vanne de régulation", "control valve", "Cv", "Kv",
            "SIL", "SIF", "safety", "interlock", "trip",
            "PT", "TT", "FT", "LT", "AT", "PDT", "PIC", "TIC", "FIC", "LIC",
        ]
        self._units = ["mA", "V", "bar", "°C", "m³/h", "Hz", "ms"]
        self._validation_patterns = [
            (r'SIL\s*([1-4])',
             "Vérifier la cohérence du niveau SIL avec l'étude HAZOP/SIL"),
            (r'temps de réponse\s+(?:de\s+)?(\d+)\s*(?:ms|s)',
             "Vérifier que le temps de réponse est compatible avec les exigences du process safety time"),
        ]

    def _get_related_terms(self, term: str) -> list[str]:
        synonyms = {
            "capteur": ["sensor", "transmetteur", "transmitter", "détecteur"],
            "régulation": ["control", "contrôle", "asservissement", "PID"],
            "vanne de régulation": ["control valve", "CV", "vanne régulatrice"],
            "boucle": ["loop", "control loop", "boucle de régulation"],
        }
        return synonyms.get(term.lower(), [])


class MechanicalAgent(DisciplineAgent):
    def __init__(self):
        super().__init__(Discipline.MECHANICAL)
        self._norms = [
            "API 610 Centrifugal Pumps for Petroleum Industry",
            "API 617 Axial and Centrifugal Compressors",
            "API 618 Reciprocating Compressors",
            "API 674 Positive Displacement Pumps - Reciprocating",
            "API 675 Positive Displacement Pumps - Controlled Volume",
            "API 676 Positive Displacement Pumps - Rotary",
            "API 682 Pumps - Shaft Sealing Systems",
            "ASME Section VIII Pressure Vessels",
            "ASME Section II Materials",
            "API 660 Shell-and-Tube Heat Exchangers",
            "API 661 Air-Cooled Heat Exchangers",
            "API 650 Welded Tanks for Oil Storage",
        ]
        self._keywords = [
            "mécanique", "mechanical", "pompe", "pump", "compresseur", "compressor",
            "turbine", "moteur", "motor", "ventilateur", "fan", "blower",
            "roulement", "bearing", "palier", "arbre", "shaft", "garniture", "seal",
            "vibration", "alignement", "alignment", "lubrification", "lubrication",
            "NPSH", "rendement", "efficiency", "puissance", "power",
            "rotating equipment", "équipement tournant", "statique", "static",
        ]
        self._units = ["kW", "MW", "HP", "rpm", "tr/min", "mm/s", "g", "m³/h", "bar"]
        self._validation_patterns = [
            (r'NPSH\w*\s+(?:de\s+)?(\d+)',
             "Vérifier que NPSHa > NPSHr avec marge de sécurité (typiquement +1m)"),
            (r'vibration\s+(?:de\s+)?(\d+\.?\d*)\s*mm/s',
             "Vérifier les seuils de vibration selon ISO 10816 / API 670"),
        ]

    def _get_related_terms(self, term: str) -> list[str]:
        synonyms = {
            "pompe": ["pump", "pompe centrifuge", "pompe volumétrique", "P-"],
            "compresseur": ["compressor", "compresseur centrifuge", "compresseur alternatif", "K-"],
            "vibration": ["vibrations", "analyse vibratoire", "vibration analysis"],
            "garniture": ["seal", "mechanical seal", "garniture mécanique", "joint d'arbre"],
        }
        return synonyms.get(term.lower(), [])


class ElectricalAgent(DisciplineAgent):
    def __init__(self):
        super().__init__(Discipline.ELECTRICAL)
        self._norms = [
            "IEC 60364 Low-voltage Electrical Installations",
            "IEC 61439 Low-voltage Switchgear and Controlgear Assemblies",
            "IEC 60079 Equipment for Explosive Atmospheres",
            "IEC 60076 Power Transformers",
            "IEC 60034 Rotating Electrical Machines",
            "IEEE 141 Red Book - Electric Power Distribution",
            "IEEE 242 Buff Book - Protection and Coordination",
            "NF C 15-100 Installations électriques à basse tension",
            "API 500 Classification of Locations for Electrical Installations",
        ]
        self._keywords = [
            "électrique", "electrical", "câble", "cable", "transformateur", "transformer",
            "disjoncteur", "circuit breaker", "MCC", "switchgear", "TGBT",
            "HT", "BT", "MT", "haute tension", "basse tension", "moyenne tension",
            "kV", "kW", "MW", "ampère", "courant", "current",
            "court-circuit", "short circuit", "sélectivité", "selectivity",
            "mise à la terre", "earthing", "grounding", "ATEX", "zone",
            "moteur", "motor", "variateur", "VFD", "VSD",
            "éclairage", "lighting", "cheminement", "cable tray",
        ]
        self._units = ["V", "kV", "A", "kA", "kW", "MW", "kVA", "MVA", "Hz", "mm²", "Ω"]
        self._validation_patterns = [
            (r'section\s+(?:de\s+)?(\d+)\s*mm²',
             "Vérifier la section du câble par rapport au courant admissible et à la chute de tension"),
            (r'court[- ]circuit\s+(?:de\s+)?(\d+)\s*kA',
             "Vérifier le pouvoir de coupure des protections vs courant de court-circuit"),
        ]


class HSEAgent(DisciplineAgent):
    def __init__(self):
        super().__init__(Discipline.HSE)
        self._norms = [
            "API 752 Management of Hazards Associated with Location of Process Plant Buildings",
            "API 2218 Fireproofing Practices in Petroleum and Petrochemical Processing Plants",
            "NFPA 30 Flammable and Combustible Liquids Code",
            "NFPA 15 Standard for Water Spray Fixed Systems",
            "NFPA 69 Standard on Explosion Prevention Systems",
            "IEC 61511 Functional Safety",
            "ISO 14001 Environmental Management Systems",
            "ISO 45001 Occupational Health and Safety Management",
            "ATEX Directive 2014/34/EU",
            "Seveso III Directive 2012/18/EU",
        ]
        self._keywords = [
            "HSE", "sécurité", "safety", "environnement", "environment",
            "HAZOP", "HAZID", "LOPA", "SIL", "QRA", "SIMOPS",
            "incendie", "fire", "explosion", "fuite", "leak", "dispersion",
            "toxique", "toxic", "H2S", "LEL", "UEL", "flash point",
            "risque", "risk", "danger", "prévention", "prevention",
            "EPI", "PPE", "permis de travail", "work permit", "ATEX", "zone",
            "plan d'urgence", "emergency", "évacuation", "evacuation",
            "étude de dangers", "safety study",
        ]
        self._units = ["ppm", "mg/m³", "%LEL", "kW/m²", "mbar"]
        self._validation_patterns = [
            (r'(?:zone|ATEX)\s*([012])',
             "Vérifier la classification de zone avec le plan de zonage ATEX validé"),
            (r'(?:distance|rayon)\s+(?:de\s+)?(?:sécurité|safety)\s+(?:de\s+)?(\d+)\s*m',
             "Vérifier la distance de sécurité avec l'étude de dangers / QRA"),
        ]


class CivilAgent(DisciplineAgent):
    def __init__(self):
        super().__init__(Discipline.CIVIL)
        self._norms = [
            "Eurocode 0 EN 1990 Basis of Structural Design",
            "Eurocode 1 EN 1991 Actions on Structures",
            "Eurocode 2 EN 1992 Design of Concrete Structures",
            "Eurocode 3 EN 1993 Design of Steel Structures",
            "Eurocode 7 EN 1997 Geotechnical Design",
            "Eurocode 8 EN 1998 Design of Structures for Earthquake Resistance",
            "ACI 318 Building Code Requirements for Structural Concrete",
            "AISC 360 Specification for Structural Steel Buildings",
            "API 650 Welded Tanks for Oil Storage (foundations)",
        ]
        self._keywords = [
            "génie civil", "civil", "béton", "concrete", "fondation", "foundation",
            "structure", "charpente", "steel structure", "bâtiment", "building",
            "ferraillage", "reinforcement", "coffrage", "formwork",
            "terrassement", "earthwork", "remblai", "backfill",
            "charge", "load", "portance", "bearing capacity",
            "sismique", "seismic", "vent", "wind", "neige", "snow",
            "dalle", "slab", "poteau", "column", "poutre", "beam",
            "ancrage", "anchor bolt", "grout", "scellement",
        ]
        self._units = ["kN", "kN/m", "kN/m²", "MPa", "mm", "m", "m²", "m³", "t/m³"]


class DiagramAgent(DisciplineAgent):
    """
    Agent spécialisé dans la génération de schémas explicatifs (Mermaid.js).
    Transforme du texte technique en représentations visuelles.
    """
    def __init__(self):
        super().__init__(Discipline.DIAGRAM)
        self._keywords = [
            "schéma", "diagramme", "schema", "diagram", "mermaid", "flux", "flowchart",
            "architecture", "séquence", "sequence", "graphique", "visuel", "explication",
            "processus", "étapes", "workflow", "interaction", "hiérarchie"
        ]

    def generate_mermaid(self, context: str, query: str) -> str:
        """
        Génère les instructions système pour que le LLM produise un bloc Mermaid.
        """
        return (
            "En tant qu'Agent Diagramme, ta mission est d'extraire la structure logique "
            "du contexte fourni et de la transformer en un schéma explicatif au format Mermaid.js.\n"
            "Règles :\n"
            "1. Utilise graph TD pour les flux de processus, sequenceDiagram pour les interactions.\n"
            "2. Sois concis dans les labels des nœuds.\n"
            "3. Ajoute des sous-graphes si nécessaire pour grouper les équipements.\n"
            "4. Termine toujours par une brève explication du schéma généré.\n"
        )

    def _compute_relevance(self, query: str) -> float:
        # Boost relevance if diagram-related words are present
        score = super()._compute_relevance(query)
        if any(w in query.lower() for w in ["schéma", "diagramme", "visuel", "dessine", "trace"]):
            score = max(score, 0.85)
        return score


# ============================================================
#  NOUVEL AGENT v2.1 : PlanningCostAgent
#  Expert en planification de projet, contrôle des coûts,
#  EVM, gestion des contrats et management des risques.
# ============================================================

class PlanningCostAgent(DisciplineAgent):
    """
    Agent spécialisé en Planification de Projet & Cost Control.
    Maîtrise tous les domaines du management de la planification:
    - Planification & Ordonnancement (CPM, PERT, Primavera P6, MS Project)
    - Contrôle des Coûts & Estimation (AACE, CAPEX/OPEX, WBS, CBS)
    - Earned Value Management (EVM : CPI, SPI, EAC, ETC, BAC)
    - Gestion des Ressources (Manpower, équipements, matériaux)
    - Gestion des Risques Planning & Coûts (Monte Carlo, risk register)
    - Contrats & Approvisionnement (EPC, EPCM, lump sum, régie)
    - Gestion des Avenants & Changements (Change Orders, Variations)
    - Reporting & KPIs Projet (Progress reports, S-Curves, Dashboards)
    """

    def __init__(self):
        super().__init__(Discipline.PLANNING)
        self.name = "Agent Planificateur & Cost Control"
        self._norms = [
            # AACE International (référence mondiale du Cost Engineering)
            "AACE 18R-97 Cost Estimate Classification System",
            "AACE 29R-03 Forensic Schedule Analysis",
            "AACE 45R-08 Escalation & Cost Trending",
            "AACE 58R-10 Integrated Cost and Schedule Risk Analysis",
            "AACE 96R-18 Total Cost Management Framework",
            "AACE 74R-13 Progress Measurement for Engineering",
            "AACE 81R-13 Earned Value Management - Applications in Engineering",
            # PMI / PMBOK
            "PMI PMBOK Guide 7th Edition - Project Management Body of Knowledge",
            "PMI Practice Standard for Scheduling",
            "PMI Practice Standard for Earned Value Management",
            "PMI Practice Standard for Work Breakdown Structures",
            # ISO
            "ISO 21500:2021 Project, Programme and Portfolio Management",
            "ISO 21502:2020 Project Management - Guidance on Project Management",
            "ISO 31000:2018 Risk Management",
            # Normes Oil & Gas spécifiques
            "API RP 17N Subsea Production Systems Reliability and Technical Risk",
            "NORSOK Z-013 Risk and Emergency Preparedness Management",
            "Shell DEP 31.22.05.10 Project Controls Manual",
            "IPA (Independent Project Analysis) Best Practices",
        ]
        self._keywords = [
            # Planification & Ordonnancement
            "planning", "planification", "schedule", "calendrier",
            "Gantt", "PERT", "CPM", "chemin critique", "critical path",
            "Primavera", "P6", "MS Project", "WBS", "OBS", "RBS",
            "jalon", "milestone", "délai", "durée", "séquencement", "float",
            "décalage", "lag", "avance", "lead", "dépendance", "précédence",
            "ressource", "resource", "charge", "loading", "lissage", "leveling",
            "baseline", "ligne de base", "replanification", "recovery plan",
            "look-ahead", "rolling wave", "sprint", "étape", "phase",
            # Cost Control & Estimation
            "coût", "cost", "budget", "budgét", "estimation", "estimate",
            "CAPEX", "OPEX", "TOTEX", "AFC", "AFE", "contingency",
            "réserve", "reserve", "provision", "escalade", "escalation",
            "CBS", "cost breakdown structure", "code analytique", "cost code",
            "variance", "déviation", "dérive", "drift", "forecast",
            "EAC", "ETC", "VAC", "Estimate at Completion", "Estimate to Complete",
            "dépenses engagées", "committed", "actuals", "réalisé",
            # Earned Value Management
            "EVM", "Earned Value", "valeur acquise", "valeur gagnée",
            "CPI", "SPI", "BCWP", "BCWS", "ACWP", "BAC",
            "Cost Performance Index", "Schedule Performance Index",
            "TCPI", "To-Complete Performance Index",
            "S-curve", "courbe en S", "courbe d’avancement",
            # Contrats & Approvisionnement
            "contrat", "contract", "EPC", "EPCM", "FEED", "PMC",
            "forfait", "lump sum", "régie", "reimbursable", "unit rate",
            "appel d’offres", "tender", "ITB", "RFQ", "RFP",
            "avenant", "amendment", "variation order", "change order", "VO", "CO",
            "sous-traitant", "subcontractor", "fournisseur", "vendor",
            "procurement", "approvisionnement", "commande", "purchase order", "PO",
            "inspection", "FAT", "SAT", "reception", "punch list",
            # Gestion des risques Planning
            "risque", "risk", "opportunité", "opportunity", "mitigation",
            "registre des risques", "risk register", "contingency plan",
            "analyse Monte Carlo", "simulation", "P50", "P80", "probabilité",
            "impact", "probabilité d’occurrence", "risk score",
            # Reporting & KPIs
            "avancement", "progress", "reporting", "rapport", "KPI",
            "tableau de bord", "dashboard", "indicateur", "performance",
            "revue", "review", "gate", "phase gate", "PMR", "MOM",
            "lesson learned", "retour d’expérience", "REX",
            "commissioning", "mechanical completion", "MC", "RFC", "RFSU",
        ]
        self._units = [
            "MUSD", "MDA", "k$", "M$", "EUR", "heures", "jours", "semaines",
            "mois", "%", "homme-heure", "man-hour", "MH", "k-MH", "t", "m³",
        ]
        self._validation_patterns = [
            # CPI et SPI
            (r'CPI\s*[=:>]?\s*([0-9\.]+)',
             "Vérifier le CPI: <0.9 = dérive coût critique, 0.9-1.0 = attention, >1.0 = bonne performance"),
            (r'SPI\s*[=:>]?\s*([0-9\.]+)',
             "Vérifier le SPI: <0.9 = retard significatif, >1.0 = en avance sur planning"),
            # Contingency
            (r'contingency\s+(?:de\s+)?(\d+)\s*%',
             "Vérifier la contingency: AACE classe 5=15-20%, classe 3=10%, classe 1=5-3%"),
            # Change Order
            (r'(?:avenant|change order|variation)\s+(?:de\s+)?(\d+)',
             "Vérifier l’impact de l’avenant sur le budget total et le planning - mettre à jour le forecast"),
            # Monte Carlo
            (r'P(50|80|90)',
             "P50=valeur médiane, P80=80% de chances de ne pas dépasser. Utiliser P80 pour les budgets de réserve"),
        ]

    def _get_related_terms(self, term: str) -> list[str]:
        synonyms = {
            "planning": ["schedule", "calendrier", "programme", "planification", "ordonnancement"],
            "coût": ["cost", "budget", "dépense", "débours", "décaissement"],
            "avenant": ["change order", "CO", "variation order", "VO", "amendment"],
            "EVM": ["earned value", "valeur acquise", "méthode de la valeur acquise"],
            "CAPEX": ["capital expenditure", "investissement", "dépenses d’investissement"],
            "contrat": ["contract", "marché", "accord", "convention"],
            "WBS": ["work breakdown structure", "organigramme des tâches", "OTP"],
            "risque": ["risk", "aléa", "incertitude", "menace"],
            "ressource": ["resource", "main-d’œuvre", "manpower", "effectif", "workforce"],
            "jalon": ["milestone", "jalonnement", "etape cle", "decision"],
        }
        return synonyms.get(term.lower(), [])

    def _compute_relevance(self, query: str) -> float:
        score = super()._compute_relevance(query)
        # Boost fort sur les termes clés métier planning
        planning_triggers = [
            "planning", "schedule", "coût", "cost", "budget", "evm", "cpi", "spi",
            "avenant", "change order", "contrat", "contract", "forecast", "capex",
            "wbs", "primavera", "risque", "risk", "milestone", "jalon", "reporting",
            "avancement", "progress", "s-curve", "estimation", "estimate",
        ]
        query_lower = query.lower()
        for trigger in planning_triggers:
            if trigger in query_lower:
                score = max(score + 0.25, 0.7)
                break
        return min(score, 1.0)

    def compute_evm_metrics(self, BAC: float, BCWP: float, BCWS: float, ACWP: float) -> dict:
        """Calcule les métriques EVM clés à partir des données de base.
        Args:
            BAC: Budget At Completion (budget total)
            BCWP: Budgeted Cost of Work Performed (valeur acquise / EV)
            BCWS: Budgeted Cost of Work Scheduled (valeur planifiée / PV)
            ACWP: Actual Cost of Work Performed (coût réel / AC)
        Returns:
            Dict avec CPI, SPI, EAC, ETC, VAC, TCPI, CV, SV
        """
        cv = BCWP - ACWP         # Cost Variance
        sv = BCWP - BCWS         # Schedule Variance
        cpi = BCWP / ACWP if ACWP != 0 else 0.0    # Cost Performance Index
        spi = BCWP / BCWS if BCWS != 0 else 0.0    # Schedule Performance Index
        eac = BAC / cpi if cpi != 0 else BAC        # Estimate at Completion
        etc = eac - ACWP                            # Estimate to Complete
        vac = BAC - eac                             # Variance at Completion
        tcpi = (BAC - BCWP) / (BAC - ACWP) if (BAC - ACWP) != 0 else 0.0  # To-Complete PI
        pct_complete = (BCWP / BAC * 100) if BAC != 0 else 0.0
        return {
            "BAC": round(BAC, 2),
            "EV_BCWP": round(BCWP, 2),
            "PV_BCWS": round(BCWS, 2),
            "AC_ACWP": round(ACWP, 2),
            "CV": round(cv, 2),
            "SV": round(sv, 2),
            "CPI": round(cpi, 3),
            "SPI": round(spi, 3),
            "EAC": round(eac, 2),
            "ETC": round(etc, 2),
            "VAC": round(vac, 2),
            "TCPI": round(tcpi, 3),
            "pct_complete": round(pct_complete, 1),
            "statut_cout": "Dérive" if cpi < 0.9 else ("Attention" if cpi < 1.0 else "OK"),
            "statut_planning": "Retard" if spi < 0.9 else ("Attention" if spi < 1.0 else "OK"),
        }

    def get_planning_context_prompt(self, query: str) -> str:
        """Génère le contexte système spécialisé pour les questions planning."""
        return (
            "\n=== CONTEXTE PLANNING & COST CONTROL ===\n"
            "Tu es un expert certifié en planification de projet Oil & Gas et contrôle des coûts.\n"
            "Références obligatoires: AACE International, PMI PMBOK, ISO 21500.\n"
            "Outils maîtrisés: Primavera P6, MS Project, Excel (EVM), SAP PS.\n"
            "\nPour chaque réponse planning tu DOIS:\n"
            "1. Identifier le domaine: planification / coûts / contrats / risques / reporting\n"
            "2. Citer les normes AACE ou PMI applicables\n"
            "3. Si données numériques: calculer CPI/SPI/EAC/ETC si pertinent\n"
            "4. Signaler tout écart significatif (CPI<0.9, SPI<0.9, contingency dépassée)\n"
            "5. Proposer des actions correctives concrètes\n"
        )


class ConsistencyVerificationAgent(DisciplineAgent):
    def __init__(self):
        super().__init__(Discipline.VERIFICATION_CONSISTENCY)
        self._norms = []
        self._keywords = ["cohérence", "incohérence", "différence", "conflit", "divergence", "attribut", "valeur", "contrôle", "données"]
        self._units = []

class ComplianceVerificationAgent(DisciplineAgent):
    def __init__(self):
        super().__init__(Discipline.VERIFICATION_COMPLIANCE)
        self._norms = ["ISO 15156", "ASME VIII", "API 520", "API 521", "ASME B31.3"]
        self._keywords = ["conformité", "norme", "réglementaire", "dépassement", "limite", "pression", "température", "h2s", "acide"]
        self._units = []

class PlanDrawingVerificationAgent(DisciplineAgent):
    def __init__(self):
        super().__init__(Discipline.VERIFICATION_DRAWING)
        self._keywords = ["plan", "dessin", "p&id", "pfd", "tag absent", "missing tag", "schéma"]
        self._units = []


class AgentOrchestrator:
    """
    Orchestrates multi-discipline agent collaboration.
    Routes queries, coordinates agents, and merges responses.
    """

    def __init__(self):
        self.agents: dict[Discipline, DisciplineAgent] = {
            Discipline.PIPING: PipingAgent(),
            Discipline.PROCESS: ProcessAgent(),
            Discipline.INSTRUMENTATION: InstrumentationAgent(),
            Discipline.MECHANICAL: MechanicalAgent(),
            Discipline.ELECTRICAL: ElectricalAgent(),
            Discipline.HSE: HSEAgent(),
            Discipline.CIVIL: CivilAgent(),
            Discipline.DIAGRAM: DiagramAgent(),
            Discipline.PLANNING: PlanningCostAgent(),
            Discipline.VERIFICATION_CONSISTENCY: ConsistencyVerificationAgent(),
            Discipline.VERIFICATION_COMPLIANCE: ComplianceVerificationAgent(),
            Discipline.VERIFICATION_DRAWING: PlanDrawingVerificationAgent(),
            Discipline.GENERAL: DisciplineAgent(Discipline.GENERAL),  # Fallback — évite KeyError sur discipline inconnue
        }
        logger.info(f"Agent orchestrator initialized with {len(self.agents)} discipline agents")

    def execute(self, query: str, documents: list, knowledge_graph_context: str,
                entities_context: str, query_type: str) -> AgentResult:
        """
        Main entry point for multi-agent analysis.
        """
        agents = self.route_query(query)
        primary = agents[0]
        secondary = agents[1:] if len(agents) > 1 else []

        enriched_context = ""
        validation_rules = []
        
        # Collect context from all relevant agents
        for agent in agents:
            ctx = agent.enrich_query(query)
            if ctx.relevant_norms:
                enriched_context += f"\nNormes {agent.discipline.value.upper()} : " + ", ".join(ctx.relevant_norms)

            # Special logic for DiagramAgent
            if isinstance(agent, DiagramAgent):
                enriched_context += "\n" + agent.generate_mermaid("", query)

            # Special logic for PlanningCostAgent
            if isinstance(agent, PlanningCostAgent):
                enriched_context += agent.get_planning_context_prompt(query)

        # Basic understanding dict
        understanding = {
            "intent": query_type,
            "primary_discipline": primary.discipline.value,
            "confidence": primary._compute_relevance(query)
        }

        return AgentResult(
            primary_agent=primary.discipline.value,
            secondary_agents=[a.discipline.value for a in secondary],
            enriched_context=enriched_context,
            validation_rules=validation_rules,
            cross_references=[],
            understanding=understanding
        )

    def route_query(self, query: str, detected_disciplines: list[str] = None) -> list[DisciplineAgent]:
        """
        Route a query to the most relevant agent(s).
        Returns agents sorted by relevance.
        """
        if detected_disciplines:
            # Use pre-detected disciplines
            agents = []
            for disc_name in detected_disciplines:
                try:
                    disc = Discipline(disc_name.lower())
                    if disc in self.agents:
                        agents.append(self.agents[disc])
                except ValueError:
                    continue
            if agents:
                return agents

        # Auto-detect by scoring all agents
        scored = []
        for discipline, agent in self.agents.items():
            relevance = agent._compute_relevance(query)
            if relevance > 0:
                scored.append((relevance, agent))

        if not scored:
            # No specific discipline detected, return general-purpose agents
            # Process + Piping are the most common in Oil & Gas
            return [self.agents[Discipline.PROCESS], self.agents[Discipline.PIPING]]

        scored.sort(key=lambda x: x[0], reverse=True)

        # Return top agents (those with relevance > 0.1 or top 2)
        top_agents = [agent for score, agent in scored if score > 0.1]
        if not top_agents:
            top_agents = [scored[0][1]]

        return top_agents[:3]  # Max 3 agents per query

    def enrich_query(self, query: str, equipment_tags: list[str] = None,
                     detected_disciplines: list[str] = None) -> list[AgentContext]:
        """
        Get enrichment from all relevant agents.
        Returns list of AgentContext objects.
        """
        agents = self.route_query(query, detected_disciplines)
        contexts = []

        for agent in agents:
            ctx = agent.enrich_query(query, equipment_tags)
            contexts.append(ctx)
            logger.debug(f"Agent {agent.discipline.value}: relevance={ctx.confidence:.2f}, "
                        f"norms={len(ctx.relevant_norms)}, keywords={len(ctx.additional_keywords)}")

        return contexts

    def validate_answer(self, query: str, answer: str, context: str,
                        detected_disciplines: list[str] = None) -> list[AgentResponse]:
        """
        Validate answer through relevant discipline agents.
        Each agent checks for discipline-specific issues.
        """
        agents = self.route_query(query, detected_disciplines)
        responses = []

        for agent in agents:
            response = agent.validate_answer(query, answer, context)
            responses.append(response)

            if response.warnings:
                logger.warning(f"Agent {agent.discipline.value} warnings: {response.warnings}")

        return responses

    def merge_agent_keywords(self, contexts: list[AgentContext]) -> list[str]:
        """Merge and deduplicate keywords from multiple agents."""
        all_keywords = []
        seen = set()

        for ctx in contexts:
            for kw in ctx.additional_keywords:
                kw_lower = kw.lower()
                if kw_lower not in seen:
                    seen.add(kw_lower)
                    all_keywords.append(kw)

        return all_keywords

    def merge_agent_norms(self, contexts: list[AgentContext]) -> list[str]:
        """Merge norms from multiple agents."""
        all_norms = []
        seen = set()

        for ctx in contexts:
            for norm in ctx.relevant_norms:
                if norm not in seen:
                    seen.add(norm)
                    all_norms.append(norm)

        return all_norms

    def format_warnings(self, responses: list[AgentResponse]) -> str:
        """Format all agent warnings into a user-readable string."""
        all_warnings = []

        for resp in responses:
            if resp.warnings:
                disc_name = resp.discipline.value.upper()
                for w in resp.warnings:
                    all_warnings.append(f"⚠ [{disc_name}] {w}")

        if not all_warnings:
            return ""

        return "\n".join(all_warnings)

    def get_agent(self, discipline: str) -> Optional[DisciplineAgent]:
        """Get a specific discipline agent by name."""
        try:
            disc = Discipline(discipline.lower())
            return self.agents.get(disc)
        except ValueError:
            return None


# Module-level singleton
_orchestrator = None
_orchestrator_lock = threading.Lock()

def get_orchestrator() -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        with _orchestrator_lock:
            if _orchestrator is None:
                _orchestrator = AgentOrchestrator()
    return _orchestrator
