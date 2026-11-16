"""
arh_actors_knowledge.py
=======================
Base de Connaissances des Acteurs Institutionnels et Règles Implicites de l'Écosystème ARH / Sonatrach / GCB.

Ce module encapsule l'expertise métier du secteur pétrolier et gazier algérien :
  1. Rôles et prérogatives des acteurs (ARH, ALGERAC, Sonatrach, GCB, TPI/Tiers Habilités).
  2. Organismes TPI accrédités et règles de délégation géographique/territoriale.
  3. Distinction sémantique entre une preuve d'acte (tampon d'inspection) et une simple mention de coordonnées.
  4. Règles d'exemption et d'obligation de légalisation consulaire (Part 2 P-CTE-1).
"""

from __future__ import annotations

import re
from typing import Dict, List, Any, Optional, Tuple

# ══════════════════════════════════════════════════════════════════════════════
# 1. CATALOGUE DES ACTEURS INSTITUTIONNELS
# ══════════════════════════════════════════════════════════════════════════════

INSTITUTIONAL_ACTORS: Dict[str, Dict[str, Any]] = {
    "ARH": {
        "name": "Autorité de Régulation des Hydrocarbures",
        "role": "Autorité de régulation et de délivrance de l'avis de conformité",
        "decree_ref": "Loi 19-13 / Décret exécutif n° 21-261 / Décret 21-314 / Décret 21-315",
        "key_powers": [
            "Délivrance de l'Avis de Conformité préalable à l'importation (Dossier Préliminaire)",
            "Délivrance de l'Avis de Conformité pour Mise en Service / Mise en Produit (Dossier Final)",
            "Mandatement et agrément des Organismes Tiers Habilités (TPI)"
        ]
    },
    "ALGERAC": {
        "name": "Organisme Algérien d'Accréditation",
        "role": "Accréditation nationale des laboratoires d'essais, d'étalonnage et organismes d'inspection",
        "standard": "ISO/IEC 17025 (Laboratoires) / ISO/IEC 17020 (Organismes d'inspection)",
        "relevance": "Tout certificat d'étalonnage ou essai destructif/non-destructif en Algérie doit émaner d'un organisme accrédité ALGERAC ou équivalent reconnu (EA, ILAC)."
    },
    "SONATRACH": {
        "name": "SONATRACH (Société Nationale pour la Recherche, la Production, le Transport, la Transformation et la Commercialisation des Hydrocarbures)",
        "role": "Maître d'Ouvrage / Client Final",
        "entities": ["EPM", "DP", "TRC", "RTI", "DPN", "DPE", "LQS"]
    },
    "GCB": {
        "name": "Société Nationale de Génie Civil et Bâtiment (GCB Spa - Filiale Sonatrach)",
        "role": "Contractant Général EPC / Constructeur Principal",
        "proc_ref": "Procédure Qualité P-CTE-1 / Système de Management Intégré"
    },
    "TPI_BODIES": {
        "BUREAU_VERITAS": {
            "name": "Bureau Veritas",
            "aliases": ["BV", "BUREAU VERITAS", "BUREAU VERITAS SA", "BUREAU VERITAS ALGERIE", "BUREAU VERITAS BENELUX"],
            "mandate_condition": "Le cachet doit être celui de l'agence mandatée territorialement sur le site de fabrication, avec signature de l'inspecteur délégué."
        },
        "TUV": {
            "name": "TÜV Rheinland / TÜV SÜD / TÜV NORD",
            "aliases": ["TUV", "TÜV", "TUV RHEINLAND", "TUV SUD", "TUV NORD"],
            "mandate_condition": "Le poinçon physique sur plaque signalétique et les rapports FAT doivent comporter le matricule de l'inspecteur TÜV délégué."
        },
        "SGS": {
            "name": "SGS (Société Générale de Surveillance)",
            "aliases": ["SGS", "SGS ALGERIE", "SGS INDUSTRIAL SERVICES"],
            "mandate_condition": "Rapports de surveillance FAT et poinçonnage d'usine."
        },
        "APAVE": {
            "name": "APAVE",
            "aliases": ["APAVE", "APAVE ALGERIE", "APAVE INTERNATIONAL"],
            "mandate_condition": "Inspection et requalification des ESP."
        }
    }
}

# ══════════════════════════════════════════════════════════════════════════════
# 2. CLASSIFICATEUR SÉMANTIQUE : PREUVE D'ACTE VS SIMPLE MENTION
# ══════════════════════════════════════════════════════════════════════════════

class ARHActResolutionEngine:
    """
    Distingue sémantiquement les preuves réelles d'inspection/surveillance
    des simples mentions passives de coordonnées ou de réclamations défensives.
    """

    # Indicateurs d'acte réel avec valeur probante
    PROVEN_ACT_PATTERNS = [
        r'(?:test|épreuve|inspection|surveillance|épreuve\s+hydrostatique)\s+(?:réalisé|effectué|witnessed|conduit)\s+(?:en\s+présence|sous\s+la\s+surveillance|par|with)\s+(?:de\s+)?(?:bureau\s+veritas|tuv|sgs|apave|tpi|arh)',
        r'(?:witnessed|inspected|stamped|certified)\s+by\s+(?:bureau\s+veritas|tuv|tüv|sgs|apave|notified\s+body|authorized\s+inspector)',
        r'procès[- ]verbal\s+d[\'’]épreuve\s+visé\s+par\s+(?:bureau\s+veritas|tuv|sgs|tpi|arh)',
        r'poinçon\s+apposé\s+par\s+(?:l[\'’]inspecteur|tpi|tuv|bureau\s+veritas)',
        r'attestation\s+de\s+surveillance\s+d[\'’]épreuve\s+n°?\s*[:=]?\s*[A-Z0-9\-_/]+',
    ]

    # Indicateurs de mention passive ou défensive (NON probante)
    DEFENSIVE_OR_COORDINATE_PATTERNS = [
        r'(?:site\s+web|website|contact|email|tél|tel|adresse|headquarters|office\s+location)\s*[:=]?\s*[^\n]*(?:bureau\s+veritas|tuv|sgs)',
        r'(?:date\s+et\s+lieu\s+de\s+création|créé\s+en|fondé\s+en)\s+[^\n]*(?:bureau\s+veritas|tuv)',
        r'mentionnée\s+à\s+l[\'’]intérieur\s+du\s+cachet\s+c[\'’]est\s+la\s+date\s+de\s+création',
        r'clarification\s*:\s*[^\n]*(?:le\s+certificat\s+de\s+test|le\s+cachet)',
        r'https?://[^\s]*(?:bureauveritas|tuv|sgs)\.com',
    ]

    # Indicateurs de rejet ou contestation explicite par l'ARH
    ARH_REJECTION_PATTERNS = [
        r'(?:l[\'’]essai|l[\'’]épreuve)\s+n[\'’]a\s+pas\s+été\s+réalisé[e]?\s+en\s+présence\s+de\s+(?:bureau\s+veritas|tuv|tpi)',
        r'absence\s+(?:du\s+)?poinçon\s+de\s+l[\'’]organisme\s+tiers\s+habilité',
        r'décision\s+arh\s*:\s*non\s+conforme',
        r'plaques?\s+signalétiques?\s+utilisées?\s+en\s+étiquette',
    ]

    def classify_evidence(self, text: str, entity_name: str = "TPI") -> Dict[str, Any]:
        """
        Classifie un extrait textuel contenant le nom d'un organisme TPI.

        Returns:
            {
                "evidence_type": "DIRECT_PROOF" | "COORDINATES_MENTION" | "REJECTION_CONFIRMED" | "UNVERIFIED",
                "act_is_proven": bool,
                "confidence": float,
                "reasoning": str
            }
        """
        u_text = text.upper()
        l_text = text.lower()

        # 1. Vérifier d'abord si c'est un rejet explicite confirmé par l'ARH
        for pat in self.ARH_REJECTION_PATTERNS:
            if re.search(pat, l_text):
                return {
                    "evidence_type": "REJECTION_CONFIRMED",
                    "act_is_proven": False,
                    "confidence": 0.95,
                    "reasoning": "Texte identifié comme une réserve de rejet explicite de l'ARH (constat officiel de non-conformité)."
                }

        # 2. Vérifier si c'est une mention défensive / coordonnées
        for pat in self.DEFENSIVE_OR_COORDINATE_PATTERNS:
            if re.search(pat, l_text):
                return {
                    "evidence_type": "COORDINATES_MENTION",
                    "act_is_proven": False,
                    "confidence": 0.90,
                    "reasoning": "Simple mention d'adresse, de date de création institutionnelle ou de clarification défensive sans attestation de surveillance in-situ."
                }

        # 3. Vérifier si c'est un acte prouvé
        for pat in self.PROVEN_ACT_PATTERNS:
            if re.search(pat, l_text):
                return {
                    "evidence_type": "DIRECT_PROOF",
                    "act_is_proven": True,
                    "confidence": 0.92,
                    "reasoning": "Preuve directe d'acte d'inspection ou de surveillance sous mandat TPI/ARH documentée."
                }

        # 4. Présence du nom sans contexte probant
        has_entity = any(k in u_text for k in ["BUREAU VERITAS", "TUV", "TÜV", "SGS", "APAVE", "TPI"])
        if has_entity:
            return {
                "evidence_type": "UNVERIFIED",
                "act_is_proven": False,
                "confidence": 0.50,
                "reasoning": "Nom de l'organisme tiers mentionné sans description explicite de l'intervention ou du procès-verbal."
            }

        return {
            "evidence_type": "NONE",
            "act_is_proven": False,
            "confidence": 1.0,
            "reasoning": "Aucune mention de l'organisme TPI trouvée."
        }


# ══════════════════════════════════════════════════════════════════════════════
# 3. VÉRIFICATEUR DES EXIGENCES DE LÉGALISATION CONSULAIRE (PART 2 P-CTE-1)
# ══════════════════════════════════════════════════════════════════════════════

class ARHConsularLegalizationValidator:
    """
    Règles d'exigibilité de la légalisation consulaire :
      - Fabricant algérien (local) → Pas de visa consulaire requis (Chambre de Commerce / Registre Commerce algérien suffisant).
      - Fabricant étranger → Visa Consulaire OBLIGATOIRE sur le certificat des signatures (Part 2 P-CTE-1).
    """

    FOREIGN_COUNTRY_KEYWORDS = [
        "ITALY", "ITALIE", "GERMANY", "ALLEMAGNE", "FRANCE", "CHINA", "CHINE",
        "INDIA", "INDE", "USA", "UNITED STATES", "SWEDEN", "SUÈDE", "SUEDE",
        "SWITZERLAND", "SUISSE", "TURKEY", "TURQUIE", "JAPAN", "JAPON",
        "SOUTH KOREA", "CORÉE", "COREE", "UK", "UNITED KINGDOM", "SPAIN", "ESPAGNE",
        "UAE", "EMIRATS", "CANADA", "AUSTRIA", "AUTRICHE"
    ]

    LOCAL_COUNTRY_KEYWORDS = [
        "ALGERIA", "ALGÉRIE", "ALGERIE", "ALGER", "HASSI MESSAOUD", "ORAN",
        "SKIKDA", "ANNABA", "CONSTANTINE", "ROUIBA", "OUARGLA", "ARZEW"
    ]

    def is_foreign_manufacturer(self, text: str) -> bool:
        """Détermine si le fabricant est étranger à partir du texte du document."""
        u_text = text.upper()
        # Si un pays étranger est explicitement mentionné dans l'adresse du fabricant
        has_foreign = any(k in u_text for k in self.FOREIGN_COUNTRY_KEYWORDS)
        has_local = any(k in u_text for k in ["FABRIQUÉ EN ALGÉRIE", "MADE IN ALGERIA", "SARL SCET", "GCB SPA", "ENTP", "ENAFOR", "SONATRACH"])
        if has_local and not has_foreign:
            return False
        return True  # (has_foreign ou défaut) Par défaut dans l'Oil & Gas, la quasi-totalité des équipements majeurs sont importés


# Instance singleton
arh_act_resolver = ARHActResolutionEngine()
arh_consular_validator = ARHConsularLegalizationValidator()
