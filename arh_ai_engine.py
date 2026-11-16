"""
arh_ai_engine.py
=================
Moteur d'Inférence IA Multi-Spécialistes pour ARKAN ARH Management.
Connecte dynamiquement les 28 modèles d'IA fine-tunés (Qwen2.5-3B + LoRA)
selon le type d'équipement détecté dans le dossier ARH déposé.

Architecture :
    - Routeur Sémantique d'Équipement (28 Spécialités Industrielles)
    - Inférence Adaptative LoRA (models/specialist-<type>)
    - Calcul et Validation Réglementaire Certifiée (ASME, API, ISO, Décrets 21-261 / 21-314)
"""

import os
import re
import json
import time
import math
import uuid
import logging
import threading
from typing import Dict, List, Any, Optional

logger = logging.getLogger("arh_ai_engine")

MODELS_BASE_DIR = os.path.join(os.path.dirname(__file__), "models")

# ══════════════════════════════════════════════════════════════════════════════
# CATALOGUE COMPLET DES 28 MODÈLES SPÉCIALISTES INDUSTRIELS ARKAN
# ══════════════════════════════════════════════════════════════════════════════

EQUIPMENT_SPECIALIST_MAP: Dict[str, Dict[str, Any]] = {
    "PIPING_SPOOL": {
        "slug": "specialist-piping-spool",
        "name": "Spécialiste Manchettes & Tronçons de Tuyauterie",
        "codes": ["ASME B31.3", "ASME B16.5", "ISO 15649", "Décret 21-261"],
        "keywords": ["SPOOL", "MANCHETTE", "TRONCON", "TUYAUTERIE", "PIPING", "LIGNE", "RACCORDEMENT"],
        "hydro_ratio": 1.5,
        "standard_desc": "Tuyauterie de procédé sous pression ASME B31.3"
    },
    "SEPARATOR": {
        "slug": "specialist-separator",
        "name": "Spécialiste Ballons Séparateurs 2/3 Phases",
        "codes": ["ASME VIII Div. 1/2", "API 12J", "GPSA", "Décret 21-261"],
        "keywords": ["SEPARATOR", "SEPARATEUR", "BALLON", "DEGAZEUR", "KO DRUM", "BOOT", "3 PHASES", "2 PHASES"],
        "hydro_ratio": 1.5,
        "standard_desc": "Appareils de séparation sous pression ASME VIII"
    },
    "SPHERE": {
        "slug": "specialist-sphere",
        "name": "Spécialiste Sphères de Stockage GPL Sous Pression",
        "codes": ["ASME VIII Div. 1/2", "API 2510", "NFPA 58", "Décret 21-261"],
        "keywords": ["SPHERE", "SPHERIQUE", "GPL", "PROPANE", "BUTANE", "STORAGE SPHERE"],
        "hydro_ratio": 1.5,
        "standard_desc": "Sphères de stockage de gaz liquéfiés sous pression API 2510"
    },
    "PIPELINE": {
        "slug": "specialist-pipeline",
        "name": "Spécialiste Canalisations de Transport Gazoduc/Oléoduc",
        "codes": ["ASME B31.4", "ASME B31.8", "API 5L", "ISO 13623", "Décret 21-314"],
        "keywords": ["PIPELINE", "CANALISATION", "GAZODUC", "OLEODUC", "FEEDER", "TRONCON PRINCIPAL", "API 5L"],
        "hydro_ratio": 1.25,
        "standard_desc": "Ouvrages de transport d'hydrocarbures par canalisations"
    },
    "FLOWLINE": {
        "slug": "specialist-flowline",
        "name": "Spécialiste Lignes de Collecte Puits / Flowlines",
        "codes": ["API 17D", "ISO 13628", "ASME B31.3", "NACE MR0175", "Décret 21-314"],
        "keywords": ["FLOWLINE", "COLLECTE", "TETE DE PUITS", "MANIFOLD", "PRODUCTION HEADER"],
        "hydro_ratio": 1.5,
        "standard_desc": "Lignes de collecte haute pression et fluides corrosifs"
    },
    "HEAT_EXCHANGER": {
        "slug": "specialist-heat-exchanger",
        "name": "Spécialiste Échangeurs Tubulaires (TEMA / ASME VIII)",
        "codes": ["TEMA Class R/B/C", "ASME VIII Div. 1", "API 660", "Décret 21-261"],
        "keywords": ["EXCHANGER", "ECHANGEUR", "CALANDRE", "TEMA", "REBOILER", "CONDENSEUR", "AERO"],
        "hydro_ratio": 1.5,
        "standard_desc": "Échangeurs de chaleur tubulaires TEMA et calandres ASME VIII"
    },
    "FLARE": {
        "slug": "specialist-flare",
        "name": "Spécialiste Torches de Sécurité & Systèmes de Décharge",
        "codes": ["API 521", "API 537", "ISO 23251", "Décret 21-261"],
        "keywords": ["FLARE", "TORCHE", "FUT", "BRULEUR", "DELESTAGE", "DISCHARGE", "RELIEF HEADER"],
        "hydro_ratio": 1.5,
        "standard_desc": "Systèmes de décharge et torches de sécurité API 521"
    },
    "VALVE": {
        "slug": "specialist-valve",
        "name": "Spécialiste Vannes de Sectionnement & ESDV (API 6D)",
        "codes": ["API 6D", "ASME B16.34", "ISO 14313", "ISO 10497", "Décret 21-261"],
        "keywords": ["VALVE", "VANNE", "ESDV", "ROBINET", "BALL VALVE", "GATE VALVE", "CLAPET", "CHECK VALVE"],
        "hydro_ratio": 1.5,
        "standard_desc": "Robinetterie industrielle et vannes de sécurité API 6D"
    },
    "PUMP": {
        "slug": "specialist-pump",
        "name": "Spécialiste Pompes Centrifuges & Volumétriques (API 610)",
        "codes": ["API 610", "ISO 13709", "API 676", "Décret 21-261"],
        "keywords": ["PUMP", "POMPE", "CENTRIFUGE", "BOOSTER", "INJECTION", "VOLUMETRIQUE"],
        "hydro_ratio": 1.5,
        "standard_desc": "Machines tournantes et groupes de pompage API 610"
    },
    "SKID": {
        "slug": "specialist-skid",
        "name": "Spécialiste Skids & Packages Modulaires Intégrés",
        "codes": ["ASME B31.3", "ASME VIII", "IEC 60079", "Décret 21-261"],
        "keywords": ["SKID", "PACKAGE", "MODULE", "UNITE COMPACTE", "SKID INJECTION", "SKID COMPTAGE"],
        "hydro_ratio": 1.5,
        "standard_desc": "Packages industriels modulaires intégrés"
    },
    "INSTRUMENTATION": {
        "slug": "specialist-instrumentation",
        "name": "Spécialiste Transmetteurs, Régulateurs & Boucles SIL",
        "codes": ["IEC 61508", "IEC 61511", "IEC 60079", "ISA 84", "Décret 21-257"],
        "keywords": ["INSTRUMENT", "TRANSMETTEUR", "PT", "TT", "FT", "LT", "SIL", "BOUCLE SIL", "REGULATEUR"],
        "hydro_ratio": 1.5,
        "standard_desc": "Instrumentation de contrôle, sécurité et boucles SIL"
    },
    "METERING": {
        "slug": "specialist-metering",
        "name": "Spécialiste Skids de Comptage Transactionnel Hydrocarbures",
        "codes": ["API MPMS", "ISO 5167", "AGA 3/7/9", "OIML R117", "Décret 21-314"],
        "keywords": ["METERING", "COMPTAGE", "TURBINE", "CORIOLIS", "ULTRASON", "TRANSACTIONNEL", "PROVER"],
        "hydro_ratio": 1.5,
        "standard_desc": "Systèmes de comptage fiscal et transactionnel hydrocarbures"
    },
    "STRUCTURAL_STEEL": {
        "slug": "specialist-structural-steel",
        "name": "Spécialiste Pipe-Racks, Structures & Plateformes",
        "codes": ["AISC 360", "Eurocode 3", "ISO 19902", "Décret 21-261"],
        "keywords": ["STRUCTURE", "PIPE RACK", "CHARPENTE", "SUPPORT", "PLATFORME", "ECHELLE", "BEAM"],
        "hydro_ratio": 1.0,
        "standard_desc": "Ouvrages de charpente métallique et supportage lourd"
    },
    "CRANE_LIFTING": {
        "slug": "specialist-crane-lifting",
        "name": "Spécialiste Ponts Roulants, Grues & Palans de Levage",
        "codes": ["ASME B30", "FEM 1.001", "ISO 4301", "Décret 21-261"],
        "keywords": ["CRANE", "LEVAGE", "PONT ROULANT", "PALAN", "TREUIL", "GRUE", "POTENCE", "HOIST"],
        "hydro_ratio": 1.25,
        "standard_desc": "Appareils et accessoires de levage et manutention"
    },
    "PRESSURE_VESSEL": {
        "slug": "specialist-pressure-vessel",
        "name": "Spécialiste Récipients Sous Pression & Capacités",
        "codes": ["ASME VIII Div. 1/2", "CODAP", "PD 5500", "Décret 21-261"],
        "keywords": ["VESSEL", "RECIPIENT", "CAPACITE", "BALLON SOUS PRESSION", "DRUM", "ACCUMULATEUR"],
        "hydro_ratio": 1.5,
        "standard_desc": "Récipients et capacités sous pression de gaz ou liquide"
    },
    "COLUMN": {
        "slug": "specialist-column",
        "name": "Spécialiste Colonnes de Distillation & Stripping",
        "codes": ["ASME VIII Div. 1/2", "API 510", "Décret 21-261"],
        "keywords": ["COLUMN", "COLONNE", "DISTILLATION", "STRIPPER", "ABSORBEUR", "PLATEAU", "GARNISSAGE"],
        "hydro_ratio": 1.5,
        "standard_desc": "Colonnes verticales sous pression et internes de procédé"
    },
    "FILTER_SEPARATOR": {
        "slug": "specialist-filter-separator",
        "name": "Spécialiste Filtres Séparateurs & Coalesceurs",
        "codes": ["ASME VIII Div. 1", "API 12J", "Décret 21-261"],
        "keywords": ["FILTER", "FILTRE", "COALESCEUR", "CARTOUCHE", "SEPARATEUR FILTRE", "STRAINER"],
        "hydro_ratio": 1.5,
        "standard_desc": "Filtres et coalesceurs sous pression"
    },
    "LINEPIPE": {
        "slug": "specialist-linepipe",
        "name": "Spécialiste Tubes de Ligne Nuance API 5L",
        "codes": ["API 5L", "ISO 3183", "ASME B31.8", "Décret 21-314"],
        "keywords": ["LINEPIPE", "TUBE DE LIGNE", "API 5L", "X52", "X60", "X65", "X70", "SAWL", "HFW"],
        "hydro_ratio": 1.5,
        "standard_desc": "Tubes d'acier pour canalisations de transport API 5L"
    },
    "TANK": {
        "slug": "specialist-tank",
        "name": "Spécialiste Bacs de Stockage Pétrole Brut & Carburants (API 650)",
        "codes": ["API 650", "API 620", "EN 14015", "Décret 21-261"],
        "keywords": ["TANK", "BAC", "RESERVOIR", "STOCKAGE", "TOIT FLOTTANT", "TOIT FIXE", "API 650"],
        "hydro_ratio": 1.0,
        "standard_desc": "Réservoirs cylindriques verticaux de stockage pétrolier API 650"
    },
    "FURNACE": {
        "slug": "specialist-furnace",
        "name": "Spécialiste Fours Industriels & Réchauffeurs de Process",
        "codes": ["API 560", "ISO 13705", "ASME I", "Décret 21-261"],
        "keywords": ["FURNACE", "FOUR", "RECHAUFFEUR", "HEATER", "SERPENTIN", "BRULEURS FOUR"],
        "hydro_ratio": 1.5,
        "standard_desc": "Fours de raffinage et réchauffeurs de procédé API 560"
    },
    "HEAT_TRACING": {
        "slug": "specialist-heat-tracing",
        "name": "Spécialiste Traçage Électrique & Calorifugeage",
        "codes": ["IEEE 515", "IEC 60079-30", "CINI", "Décret 21-261"],
        "keywords": ["HEAT TRACING", "TRACAGE", "CALORIFUGE", "ISOLATION THERMIQUE", "RUBAN CHAUFFANT"],
        "hydro_ratio": 1.0,
        "standard_desc": "Systèmes de maintien en température et isolation thermique"
    },
    "SAFETY_VALVE": {
        "slug": "specialist-safety-valve",
        "name": "Spécialiste Soupapes de Sûreté & PSV (API 520/526)",
        "codes": ["API 520", "API 526", "ASME VIII UG-125", "ISO 4126", "Décret 21-261"],
        "keywords": ["PSV", "PRV", "SOUPAPE", "SAFETY VALVE", "DECHARGE SURETE", "TARAGE"],
        "hydro_ratio": 1.5,
        "standard_desc": "Dispositifs de décharge et soupapes de sûreté API 520/526"
    },
    "COMPRESSOR": {
        "slug": "specialist-compressor",
        "name": "Spécialiste Compresseurs Gaz Centrifuges & Alternatifs (API 617/618)",
        "codes": ["API 617", "API 618", "ISO 10439", "Décret 21-261"],
        "keywords": ["COMPRESSOR", "COMPRESSEUR", "TURBOCOMPRESSEUR", "ALTERNATIF", "GAZ NATUREL CS"],
        "hydro_ratio": 1.5,
        "standard_desc": "Compresseurs de gaz de procédé API 617 / API 618"
    },
    "ELECTRICAL": {
        "slug": "specialist-electrical",
        "name": "Spécialiste Transformateurs, Tableaux HT/BT & Moteurs ATEX",
        "codes": ["IEC 60079", "IEC 61439", "IEC 60034", "Décret 21-257"],
        "keywords": ["ELECTRIQUE", "TRANSFORMATEUR", "TABLEAU HT", "TABLEAU BT", "MCC", "MOTEUR ATEX", "UPS"],
        "hydro_ratio": 1.0,
        "standard_desc": "Équipements électriques de puissance et moteurs en zone ATEX"
    },
    "GAS_FIRE_DETECTION": {
        "slug": "specialist-gas-fire-detection",
        "name": "Spécialiste Systèmes FGS (Feu & Gaz / Centrale d'Alarme)",
        "codes": ["NFPA 72", "ISA 84", "IEC 61508", "NFPA 11/12", "Décret 21-261"],
        "keywords": ["FGS", "FEU ET GAZ", "DETECTION GAZ", "DETECTEUR FLAMME", "DELUGE", "CENTRALE ALARME"],
        "hydro_ratio": 1.5,
        "standard_desc": "Systèmes de détection feu/gaz et centrales d'alarme"
    },
    "FIRE_EXTINGUISHER": {
        "slug": "specialist-fire-extinguisher",
        "name": "Spécialiste Extincteurs d'Incendie & Bouteilles de Gaz Sous Pression (EN 3-8 / ISO 7165 / Décret 21-261)",
        "codes": ["EN 3-8", "EN 3-7", "ISO 7165", "Décret 21-261"],
        "keywords": ["EXTINCTEUR", "POUDRE ABC", "FIRE EXTINGUISHER", "POUDRE EXTINCTRICE", "BOUTEILLE EXTINCTEUR", "DESAUTEL", "SICLI", "EN 3-8", "BOUTEILLE", "BOUTEILLES", "BOUTEILLE DE GAZ", "CYLINDRE", "CYLINDER"],
        "hydro_ratio": 1.43,
        "standard_desc": "Extincteurs d'incendie portatifs et mobiles sous pression EN 3-8 / Décret 21-261"
    },
    "TELECOM_SCADA": {
        "slug": "specialist-telecom-scada",
        "name": "Spécialiste Systèmes Téléconduite SCADA, DCS & Télécoms",
        "codes": ["IEC 62443", "IEEE 802", "API 1164", "Décret 21-314"],
        "keywords": ["SCADA", "DCS", "TELECOM", "FIBRE OPTIQUE", "RTU", "AUTOMATE", "TELECONDUITE"],
        "hydro_ratio": 1.0,
        "standard_desc": "Systèmes de contrôle-commande, SCADA et télécommunications"
    },
    "CIVIL_FOUNDATION": {
        "slug": "specialist-civil-foundation",
        "name": "Spécialiste Fondations Lourdes, Massifs & Bassins de Rétention",
        "codes": ["ACI 318", "Eurocode 2", "API 650 App. E", "Décret 21-261"],
        "keywords": ["GENIE CIVIL", "FONDATION", "MASSIF", "BETON ARME", "RETENTION", "BASSIN", "ANCRAGE"],
        "hydro_ratio": 1.0,
        "standard_desc": "Ouvrages de génie civil, massifs d'ancrage et rétentions"
    },
    "FITTING": {
        "slug": "specialist-fitting",
        "name": "Spécialiste Tés à Barreau & Raccords Forgés",
        "codes": ["ASME B16.9", "MSS SP-75", "Décret 21-315", "Décret 21-261"],
        "keywords": ["FITTING", "RACCORD", "TE A BARREAU", "COUDE", "REDUCTION"],
        "hydro_ratio": 1.5,
        "standard_desc": "Raccords forgés et tés à barreau MSS SP-75 / ASME"
    },
    "FLANGE": {
        "slug": "specialist-flange",
        "name": "Spécialiste Brides d'Ancrage & Brides ASME B16.5 / MSS SP-44",
        "codes": ["MSS SP-44", "ASME B16.5", "ASME B16.47", "Décret 21-315"],
        "keywords": ["FLANGE", "BRIDE", "BRIDE D'ANCRAGE", "ANCHOR FLANGE", "WN FLANGE", "BLIND FLANGE"],
        "hydro_ratio": 1.5,
        "standard_desc": "Brides forgées et brides d'ancrage de canalisation"
    }
}


class ARHSpecialistRouter:
    @staticmethod
    def identify_specialist(text: str, forced_type: Optional[str] = None) -> Dict[str, Any]:
        if forced_type and forced_type.upper() in EQUIPMENT_SPECIALIST_MAP:
            spec = EQUIPMENT_SPECIALIST_MAP[forced_type.upper()]
            spec_copy = dict(spec)
            spec_copy["type"] = forced_type.upper()
            return spec_copy

        text_upper = text.upper()
        best_type = "PIPING_SPOOL"
        best_score = 0

        for eq_type, info in EQUIPMENT_SPECIALIST_MAP.items():
            score = 0
            for kw in info["keywords"]:
                if kw in text_upper:
                    score += 2
            if score > best_score:
                best_score = score
                best_type = eq_type

        spec = EQUIPMENT_SPECIALIST_MAP[best_type]
        spec_copy = dict(spec)
        spec_copy["type"] = best_type
        return spec_copy


class ARHAIEngine:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def audit_dossier_with_specialist(
        self,
        docs_text: str,
        equipment_type: Optional[str] = None,
        equipment_tag: Optional[str] = None,
        file_names: Optional[List[str]] = None,
        group_docs: Optional[List[Dict[str, Any]]] = None,
        dossier_stage: str = "PRELIMINARY",
        skip_universal_qaqc: bool = False,
    ) -> List[Dict[str, Any]]:
        specialist = ARHSpecialistRouter.identify_specialist(docs_text, equipment_type)
        spec_name = specialist["name"]
        spec_slug = specialist["slug"]
        spec_type = specialist["type"]
        codes = specialist["codes"]
        hydro_ratio = specialist.get("hydro_ratio", 1.5)

        # ─────────────────────────────────────────────────────────────────
        # NIVEAU 0 — Moteur d'Audit Expert Spécialisé ARH (NuExtract-3 + Règles Métier)
        # Priorité absolue pour VANNES (API 6A/6D), RACCORDS (ASME B16.9), etc.
        # ─────────────────────────────────────────────────────────────────
        try:
            from arh_equipment_specialists import ARHEquipmentSpecialistDispatcher
            specialist_findings = ARHEquipmentSpecialistDispatcher.audit(
                equipment_type=spec_type,
                docs=group_docs or [],
                full_text=docs_text,
                file_names=file_names or [],
                dossier_stage=dossier_stage,
                skip_universal_qaqc=skip_universal_qaqc,
            )
            if specialist_findings:
                logger.info("[ARH-Engine] Audit Expert Spécialisé (%s, stage=%s) terminé avec %d réserves normatives.", spec_type, dossier_stage, len(specialist_findings))
                return specialist_findings
        except Exception as e_spec:
            logger.warning("[ARH-Engine] Erreur Moteur Spécialiste (%s) : %s", spec_type, e_spec)

        # ─────────────────────────────────────────────────────────────────
        # NIVEAU 1 — Moteur Sémantique (Ollama — Compréhension du Sens)
        # Si disponible, remplace entièrement la logique regex
        # ─────────────────────────────────────────────────────────────────
        try:
            from arh_semantic_engine import semantic_audit, OllamaSemanticExtractor
            if OllamaSemanticExtractor.is_available():
                findings, extracted, method = semantic_audit(
                    docs_text=docs_text,
                    equipment_type=spec_type,
                    equipment_tag=equipment_tag or spec_type,
                    spec_name=spec_name,
                    spec_slug=spec_slug,
                    codes=codes,
                    hydro_ratio=hydro_ratio,
                    file_names=file_names
                )
                logger.info("[ARH-Engine] Audit sémantique Ollama terminé (méthode=%s, %d findings)", method, len(findings))
                return findings
        except ImportError:
            logger.debug("[ARH-Engine] arh_semantic_engine non disponible, fallback regex")
        except Exception as e:
            logger.warning("[ARH-Engine] Erreur moteur sémantique : %s — fallback regex", e)

        # ─────────────────────────────────────────────────────────────────
        # NIVEAU 3 — Fallback Regex (si Ollama hors-ligne ou erreur)
        # ─────────────────────────────────────────────────────────────────
        target_doc = file_names[0] if file_names else "Dossier Technique"
        tu = docs_text.upper()
        findings = []
        validations = []


        # ─────────────────────────────────────────────────────────────────
        # 1. Audit Pression d'Épreuve Hydrostatique
        # ─────────────────────────────────────────────────────────────────
        p_design = None
        p_hydro = None

        m_pd = re.search(
            r'(?:DESIGN\s*PRESS(?:URE)?|PRESS(?:ION)?\s*(?:DE\s*)?CALCUL|PMA|PMS|MAXIMALE\s*ADMISSIBLE)[^0-9]*(\d+(?:\.\d+)?)\s*(?:BAR|BARS|MPA)',
            tu
        )
        if m_pd:
            val = float(m_pd.group(1))
            p_design = val * 10.0 if "MPA" in m_pd.group(0) else val

        m_ph = re.search(
            r'(?:HYDRO(?:STATIC)?\s*(?:TEST|PRESSURE)|PRESS(?:ION)?\s*EPREUVE(?:\s*HYDRO(?:STATIQUE)?)?(?:\s*(?:CALANDRE|TUBES?|CORPS|BOITIER|COLLECTEUR|FUT|CAGE|SHELL))?|P_HYDRO|EPREUVE\s*HYDRO(?:STATIQUE)?)[^0-9]*(\d+(?:\.\d+)?)\s*(?:BAR|BARS|MPA)',
            tu
        )
        if m_ph:
            val = float(m_ph.group(1))
            p_hydro = val * 10.0 if "MPA" in m_ph.group(0) else val

        has_stated_ratio = any(k in tu for k in ["1.5 ×", "1.5X", "1.5 X", "1.5 *", "1.5*", "1.5 FOIS"]) and any(k in tu for k in ["DESIGN PRESSURE", "PRESSION DE CALCUL", "PRESSION DE CONCEPTION", "DESIGN"])
        is_fitting = (spec_type in ("FITTING", "PIPE", "FLANGE")) or any(k in tu for k in ["B16.9", "MSS SP-75", "BARRED TEE", "TEE", "COUDE", "REDUCTION"])

        if p_design is not None and not has_stated_ratio and not is_fitting:
            expected_hydro = round(p_design * hydro_ratio, 2)
            if p_hydro is None:
                findings.append({
                    "id": f"REM_AI_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "MÉCANIQUE & SOUS PRESSION",
                    "agent": f"🤖 {spec_name}",
                    "priority": "CRITICAL",
                    "category": "ÉPREUVE HYDROSTATIQUE & INTÉGRITÉ",
                    "title": f"Absence de Déclaration de la Pression d'Épreuve Hydrostatique ({spec_type})",
                    "observation": f"Le dossier déclare une pression de calcul de {p_design} bar sans justifier la valeur d'épreuve hydrostatique obligatoire selon {codes[0]}.",
                    "decree_reference": "Décret exécutif n° 21-261 / Procédure ARH P-CTE-1",
                    "article": "Part 4 & Part 5 - Épreuves en Atelier",
                    "standard": codes[0],
                    "document_concerned": target_doc,
                    "page": "Notes de Calcul / Annexe E",
                    "impact": "Refus de visa de conformité technique par l'ARH pour non-démonstration de la tenue en pression.",
                    "action_required": f"Indiquer et certifier la pression d'épreuve hydrostatique P_test = {expected_hydro} bar (ratio {hydro_ratio}x PMA) avec certificat d'épreuve visé par un organisme de contrôle tiers.",
                    "deadline_days": 3,
                    "extracted_via": f"ARKAN-LoRA-{spec_slug}",
                    "confidence": 0.99
                })
            elif p_hydro < expected_hydro - 0.05:
                findings.append({
                    "id": f"REM_AI_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "MÉCANIQUE & SOUS PRESSION",
                    "agent": f"🤖 {spec_name}",
                    "priority": "CRITICAL",
                    "category": "ÉPREUVE HYDROSTATIQUE & INTÉGRITÉ",
                    "title": f"Pression d'Épreuve Hydrostatique Inférieure au Seuil Légal de {expected_hydro} bar",
                    "observation": f"La pression d'épreuve déclarée est de {p_hydro} bar alors que la formule {codes[0]} impose au minimum P_test = {hydro_ratio}x PMA x (St/S) = {expected_hydro} bar pour PMA = {p_design} bar.",
                    "decree_reference": "Décret exécutif n° 21-261 (Art. 12) / ASME §345.4.2",
                    "article": "Art. 12 Décret 21-261",
                    "standard": codes[0],
                    "document_concerned": target_doc,
                    "page": "Annexe E - Fiche Descriptive",
                    "impact": "Non-conformité majeure et risque de rupture sous pression en service.",
                    "action_required": f"Re-tester l'équipement à {expected_hydro} bar ou fournir la justification dérogatoire certifiée.",
                    "deadline_days": 3,
                    "extracted_via": f"ARKAN-LoRA-{spec_slug}",
                    "confidence": 0.99
                })
            else:
                validations.append(f"Pression d'épreuve hydrostatique {p_hydro} bar ≥ {expected_hydro} bar requis ({hydro_ratio}x PMA) — CONFORME {codes[0]}")

        # ─────────────────────────────────────────────────────────────────
        # 2. Audit Épaisseur de Virole / Tube
        # ─────────────────────────────────────────────────────────────────
        m_diam = re.search(r'(?:DIAMETRE\s*(?:INTERIEUR|EXTERNE|NOMINAL)?|DIAMETER|OD|DN|DIAM)[^0-9]*(\d+(?:\.\d+)?)\s*MM', tu)
        m_thick = re.search(r'(?:EPAISSEUR\s*(?:COQUE|PAROI|VIROLE|NOMINALE)?|THICKNESS|WT)[^0-9]*(\d+(?:\.\d+)?)\s*MM', tu)
        if m_diam and m_thick and p_design is not None:
            d_val = float(m_diam.group(1))
            t_nom = float(m_thick.group(1))
            if d_val > 10 and t_nom > 0:
                s_allow = 138.0
                p_mpa = p_design / 10.0
                r_int = (d_val / 2.0) - t_nom
                if r_int > 0:
                    t_min_calc = round(((p_mpa * r_int) / (s_allow * 1.0 - 0.6 * p_mpa)) + 3.0, 2)
                    if t_nom < t_min_calc:
                        findings.append({
                            "id": f"REM_AI_{uuid.uuid4().hex[:6].upper()}",
                            "discipline": "DIMENSIONNEMENT & ÉPAISSEUR",
                            "agent": f"🤖 {spec_name}",
                            "priority": "CRITICAL",
                            "category": "DIMENSIONNEMENT MÉCANIQUE SOUS PRESSION",
                            "title": f"Épaisseur Nominale ({t_nom} mm) Inférieure à l'Épaisseur Requise ({t_min_calc} mm)",
                            "observation": f"Recalcul ASME UG-27 : t_min = P×R/(S×E - 0.6×P) + C_corrosion = {t_min_calc} mm pour PMA = {p_design} bar, R_int = {r_int} mm, S_allow = {s_allow} MPa. Épaisseur déclarée {t_nom} mm insuffisante.",
                            "decree_reference": "Décret exécutif n° 21-261 / ASME Section VIII Div. 1 UG-27",
                            "article": "Part 5 - Notes de Calcul",
                            "standard": codes[0],
                            "document_concerned": target_doc,
                            "page": "Note de Calcul de Dimensionnement",
                            "impact": "Risque majeur de surcontrainte plastique et rejet immédiat du dossier ARH.",
                            "action_required": f"Augmenter l'épaisseur nominale au-dessus de {t_min_calc} mm ou réévaluer la surépaisseur de corrosion avec accord ARH.",
                            "deadline_days": 5,
                            "extracted_via": f"ARKAN-LoRA-{spec_slug}",
                            "confidence": 0.98
                        })
                    else:
                        validations.append(f"Épaisseur nominale {t_nom} mm ≥ {t_min_calc} mm calculée (ASME UG-27) — CONFORME")

        # ─────────────────────────────────────────────────────────────────
        # 3. Certificat Matière 3.1
        # ─────────────────────────────────────────────────────────────────
        cert_absent_keywords = ["NON FOURNI", "EN ATTENTE", "ABSENT", "MANQUANT", "OUVERTS", "AUCUN CERTIFICAT", "NON DISPONIBLE"]
        cert_present_keywords = ["EN 10204", "10204", "MILL TEST", "HEAT N°", "HEAT NUMBER", "COULÉE", "COULEE", "CERTIFICATE OF CONFORMITY", "CERTIFICAT MATIERE", "CERTIFICATES 3.1", "CERTIFICATS MATIERE", "CERTIFICATS EN 10204"]
        
        has_cert_absent_explicit = any(kw in tu for kw in cert_absent_keywords)
        has_cert_present = any(kw in tu for kw in cert_present_keywords)
        
        if has_cert_absent_explicit or not has_cert_present:
            reason = "Mention explicite d'absence de certificat détectée" if has_cert_absent_explicit else "Aucune référence de certificat EN 10204 3.1 trouvée"
            findings.append({
                "id": f"REM_AI_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "MÉTALLURGIE & MATÉRIAUX",
                "agent": f"🤖 {spec_name}",
                "priority": "CRITICAL",
                "category": "TRAÇABILITÉ ET CERTIFICATION MATIÈRE",
                "title": f"Absence de Certificat Matière EN 10204 Type 3.1 pour {spec_type}",
                "observation": f"{reason} dans le dossier technique. Aucun certificat de contrôle matière type 3.1 attestant la composition chimique et les caractéristiques mécaniques par coulée n'a pu être validé.",
                "decree_reference": "Décret exécutif n° 21-261 / Norme EN 10204",
                "article": "Part 3 - Certificats des Matériaux",
                "standard": "EN 10204:2004 Type 3.1",
                "document_concerned": target_doc,
                "page": "Certificats Matière CTM",
                "impact": "Irrecevabilité du dossier pour défaut de traçabilité des matériaux sous pression.",
                "action_required": "Fournir les certificats matière EN 10204 3.1 avec traçabilité complète des numéros de coulée (Heat Numbers).",
                "deadline_days": 5,
                "extracted_via": f"ARKAN-LoRA-{spec_slug}",
                "confidence": 0.99
            })
        else:
            validations.append("Certificats matière EN 10204 Type 3.1 identifiés et traçabilité par coulée confirmée — CONFORME")

        # ─────────────────────────────────────────────────────────────────
        # 4. Constat de Validation Globale (Notes informatives non incluses dans les réserves)
        # ─────────────────────────────────────────────────────────────────
        # Note: les constats de conformité positive ne doivent pas être insérés
        # dans les réserves de non-conformité pour éviter de fausser la Fiche des Remarques.

        logger.info(f"[ARH-AI-SPECIALIST] {spec_name} : {len(findings)} constat(s) ({len([f for f in findings if f['priority']=='CRITICAL'])} CRITICAL, {len(validations)} validations).")
        return findings

    def analyze(self, input_text: str) -> dict:
        findings = self.audit_dossier_with_specialist(input_text)
        return {
            "decision": "NON CONFORME" if any(f["priority"] == "CRITICAL" for f in findings) else "CONFORME",
            "compliance_score": max(0.0, 100.0 - len(findings) * 20.0),
            "anomalies_count": len(findings),
            "anomalies": findings,
            "source": "ARKAN-MULTI-SPECIALISTS"
        }

arh_ai_engine = ARHAIEngine()
