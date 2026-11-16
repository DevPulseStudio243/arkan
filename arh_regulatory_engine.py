"""
arh_regulatory_engine.py
========================
Moteur Réglementaire Officiel ARH (Autorité de Régulation des Hydrocarbures - Algérie)

Fournit la base réglementaire officielle, la classification automatique des équipements,
la génération dynamique de checklists documentaires et les vérifications techniques
conformément aux décrets exécutifs :
  • Décret exécutif n° 21-261 (ESP et Équipements Électriques)
  • Décret exécutif n° 21-314 (Contrôle & Suivi Canalisations de Transport)
  • Décret exécutif n° 21-315 (Exigences Conception, Fabrication, Construction Canalisations & Stockage)
  • Décret exécutif n° 17-62 & Arrêté du 29/03/2017 (Marquage de conformité 'ج م' et Niveaux A-E)
  • Décret exécutif n° 21-257 (Autorisation de Mise en Produit & Mise sous Tension)
  • Décret exécutif n° 24-278 (Bureaux d'Expertise Agréés et Préqualifiés ARH)

v2.0 — Détection Sémantique LLM : L'IA comprend le sens du texte, plus le simple keyword matching.
"""

from __future__ import annotations
import json
import logging
import math
import os
import re
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# DÉFINITION DES RÉGLEMENTATIONS ET DÉCRETS OFFICIELS
# ══════════════════════════════════════════════════════════════════════════════

DECREES_CATALOG = {
    "DE_21_261": {
        "title": "Décret exécutif n° 21-261 du 13 juin 2021",
        "description": "Réglementation des équipements sous pression (ESP) et des équipements électriques destinés à être intégrés aux installations du secteur des hydrocarbures.",
        "articles": {
            "Art_3": "Champ d'application ESP non soumis à la flamme (PMA >= 4 bars et PMA*V > 50).",
            "Art_6": "Obligation de conception conforme aux normes et sollicitations de fonctionnement.",
            "Art_15": "Dossier préliminaire ESP transmis à l'ARH avant fabrication (Notes de calcul, ITP, soudage).",
            "Art_27": "Pression minimale d'épreuve hydrostatique ESP = 150% de la PMA.",
            "Art_38": "Périodicité maximale des inspections réglementaires : 36 mois (récipients), 24 mois (générateurs vapeur).",
            "Art_43": "Requalification périodique ESP tous les 10 ans (fixe) ou 5 ans (mobile).",
            "Art_50": "Équipements électriques de tension >= 5500V ou installés en zones explosives (ATEX).",
            "Art_61": "Dossier préliminaire fabrication électrique (notes de court-circuit, ITP, schémas, ATEX).",
            "Art_77": "Autorisation obligatoire de mise sous tension délivrée par l'ARH."
        }
    },
    "DE_21_314": {
        "title": "Décret exécutif n° 21-314 du 14 août 2021",
        "description": "Fixant les procédures de contrôle et de suivi de la construction et d'exploitation d'un système de transport par canalisation des hydrocarbures.",
        "articles": {
            "Art_4": "Classification des emplacements en 4 zones A (forte densité), B (intermédiaire), C (faible), D (désertique).",
            "Art_6": "Emploi obligatoire de la radiographie pour les soudures de raccordement et raboutage.",
            "Art_7": "Examen visuel 100% de tous les joints de soudure.",
            "Art_8": "CND par radiographie à 100% pour canalisations Gaz Naturel et GPL.",
            "Art_9": "Étendue des CND radiographiques hydrocarbures liquides : Zone A (75%), Zone B (40%), Zone C (15%), Zone D (10%).",
            "Art_12": "Profondeur d'enfouissement minimale = 1,0 mètre à partir de la génératrice supérieure.",
            "Art_20": "Épreuve de résistance et d'étanchéité préalable sous supervision des représentants ARH.",
            "Art_21": "Pression minimale d'épreuve hydrostatique : 150% PMA (Zones A et B), 125% PMA (Zones C et D).",
            "Art_26": "Dossier final de construction obligatoire à transmettre à l'ARH (Carnet soudage, PV CND, PV d'épreuve)."
        }
    },
    "DE_21_315": {
        "title": "Décret exécutif n° 21-315 du 14 août 2021",
        "description": "Fixant les exigences de conception, fabrication, construction et exploitation des canalisations et installations de stockage d'hydrocarbures.",
        "articles": {
            "Art_5": "Facteurs de conception canalisation : Zone A (0.40), Zone B (0.50), Zone C (0.60), Zone D (0.72).",
            "Art_7": "Formule de calcul d'épaisseur minimale tube : e = (P * D) / (2 * R_t0.5 * F * Z).",
            "Art_14": "Dossier préliminaire fabrication tubes et accessoires transmis à l'ARH pour approbation.",
            "Art_21": "Épreuve hydrostatique des tubes en usine obligatoire avec de l'eau (sans dépasser 90% R_t0.5).",
            "Art_28": "Conception des bacs de stockage selon les codes et normes industrielles (API 650/620).",
            "Art_39": "Dossier préliminaire fabrication composants de stockage transmis à l'ARH.",
            "Art_59": "Contrôle 100% par radiographie des soudures bout à bout des installations de stockage.",
            "Art_63": "Épreuve hydrostatique obligatoire de l'installation de stockage sous supervision ARH."
        }
    },
    "DE_17_62": {
        "title": "Décret exécutif n° 17-62 du 7 février 2017 & Arrêté du 29/03/2017",
        "description": "Conditions d'apposition du marquage de conformité 'ج م' et procédures de certification de conformité.",
        "articles": {
            "Art_2": "Niveaux d'évaluation de la conformité : Niveau A (Contrôle interne), B (Examen de type), C (Vérification sur produits), D (Vérification à l'unité), E (Assurance qualité complète).",
            "Art_10": "Seuls les organismes habilités par le ministère compétent ou ALGERAC délivrent les certificats de conformité.",
            "Art_12": "Marquage obligatoire 'ج م' (Conformité Algérienne)."
        }
    },
    "DE_21_257": {
        "title": "Décret exécutif n° 21-257 du 13 juin 2021",
        "description": "Modalités et procédure d'autorisation de mise en produit et de mise sous tension des installations et ouvrages hydrocarbures.",
        "articles": {
            "Art_4": "Dossier de demande d'autorisation comprenant les PV d'épreuves, le dossier de construction, le dossier HSE et l'avis du bureau préqualifié.",
            "Art_8": "Inspection sur site par la commission ARH préalable à la délivrance de l'autorisation de mise en produit."
        }
    },
    "DE_24_278": {
        "title": "Décret exécutif n° 24-278 & Directives ARH",
        "description": "Agréments et préqualification des organismes tiers habilités et bureaux d'expertise technique.",
        "articles": {
            "Art_2": "Obligation d'accréditation ALGERAC ou équivalent reconnu pour l'intervention des bureaux tiers sur site."
        }
    }
}

# ══════════════════════════════════════════════════════════════════════════════
# CLASSIFICATION AUTOMATIQUE DES ÉQUIPEMENTS
# ══════════════════════════════════════════════════════════════════════════════

EQUIPMENT_TYPES = {
    "PRESSURE_VESSEL": {
        "label": "Pressure Vessel / Récipient Sous Pression",
        "keywords": ["PRESSURE VESSEL", "APPAREIL SOUS PRESSION", "RECIPIENT SOUS PRESSION", "ESP", "BALLON", "VESSEL", "DRUM", "ACCUMULATOR", "SCRUBBER", "FILTER VESSEL", "BOOT"],
        "decrees": ["DE_21_261", "DE_17_62", "DE_21_257", "DE_24_278"],
        "esp_type": "Fixed_ESP"
    },
    "SEPARATOR": {
        "label": "Separator / Séparateur de Procédé",
        "keywords": ["SEPARATOR", "SEPARATEUR", "3-PHASE SEPARATOR", "2-PHASE SEPARATOR", "PRODUCTION SEPARATEUR", "TEST SEPARATEUR"],
        "decrees": ["DE_21_261", "DE_17_62", "DE_21_257", "DE_24_278"],
        "esp_type": "Fixed_ESP"
    },
    "HEAT_EXCHANGER": {
        "label": "Heat Exchanger / Échangeur de Chaleur",
        "keywords": ["HEAT EXCHANGER", "ECHANGEUR", "REBOILER", "CONDENSER", "COOLER", "AEROTHERME", "HEATER"],
        "decrees": ["DE_21_261", "DE_17_62", "DE_21_257", "DE_24_278"],
        "esp_type": "Fixed_ESP"
    },
    "COLUMN": {
        "label": "Column / Colonne de Distillation / Stripper",
        "keywords": ["COLUMN", "COLONNE", "STRIPPER", "ABSORBER", "STABILIZER", "FRACTIONATOR"],
        "decrees": ["DE_21_261", "DE_17_62", "DE_21_257", "DE_24_278"],
        "esp_type": "Fixed_ESP"
    },
    "TANK": {
        "label": "Storage Tank / Bac de Stockage Hydrocarbures",
        "keywords": ["TANK", "BAC", "RESERVOIR", "STORAGE TANK", "FIXED ROOF TANK", "FLOATING ROOF TANK", "BAC DE STOCKAGE"],
        "decrees": ["DE_21_315", "DE_17_62", "DE_21_257", "DE_24_278"],
        "esp_type": "Storage"
    },
    "SPHERE": {
        "label": "Sphere / Sphère de Stockage Sous Pression",
        "keywords": ["SPHERE", "SPHERE GPL", "BUTANE SPHERE", "PROPANE SPHERE", "PRESSURE SPHERE"],
        "decrees": ["DE_21_261", "DE_21_315", "DE_17_62", "DE_21_257", "DE_24_278"],
        "esp_type": "Fixed_ESP"
    },
    "PIPELINE": {
        "label": "Pipeline Construction / Pose Canalisation de Transport",
        "keywords": ["PIPELINE", "CANALISATION", "GAZODUC", "OLEODUC", "POSE CANALISATION", "GAZODUC CHANTIER", "OLEODUC CHANTIER", "POSE TRONCON", "TRAVAUX CANALISATION", "PCT", "POSTE DE COUPURE", "POSTE DE SECTIONNEMENT"],
        "decrees": ["DE_21_314", "DE_21_315", "DE_21_257", "DE_24_278"],
        "esp_type": "Pipeline"
    },
    "LINEPIPE": {
        "label": "Linepipe & Tubes / Fourniture & Fabrication Tubes de Canalisation en Usine (Décret 21-315 Art. 14)",
        "keywords": ["LINEPIPE", "TUBES CANALISATION", "TUBE CANALISATION", "API 5L", "ISO 3183", "ASTM A106", "ASTM A333", "ASTM A312", "FOURNITURE TUBE", "FABRICATION TUBE", "STEEL PIPE SUPPLY", "SEAMLESS LINE PIPE", "SAW LINE PIPE", "ERW LINE PIPE", "LINE PIPE SPECIFICATION"],  # Universal normative standards
        "decrees": ["DE_21_315", "DE_17_62", "DE_24_278"],
        "esp_type": "Pipeline_Supply"
    },
    "FLOWLINE": {
        "label": "Flowline / Conduite d'Écoulement de Puits",
        "keywords": ["FLOWLINE", "COLLECTEUR", "MANIFOLD LINK", "WELLHEAD LINE"],
        "decrees": ["DE_21_314", "DE_21_315", "DE_21_257", "DE_24_278"],
        "esp_type": "Pipeline"
    },
    "COMPRESSOR": {
        "label": "Compressor Package / Groupe Compresseur",
        "keywords": ["COMPRESSOR", "COMPRESSEUR", "TURBOCOMPRESSEUR", "RECIPROCATING COMPRESSOR", "GAS COMPRESSOR"],
        "decrees": ["DE_21_261", "DE_21_257", "DE_24_278"],
        "esp_type": "Rotating_Machinery"
    },
    "PUMP": {
        "label": "Pump Package / Groupe Motopompe",
        "keywords": ["PUMP", "POMPE", "MOTOPOMPE", "CRUDE PUMP", "BOOSTER PUMP", "WATER INJECTION PUMP"],
        "decrees": ["DE_21_261", "DE_21_257", "DE_24_278"],
        "esp_type": "Rotating_Machinery"
    },
    "ELECTRICAL": {
        "label": "Electrical Installation / Installation Électrique & UPS/ASI",
        "keywords": [
            "UPS", "ASI", "UNINTERRUPTIBLE POWER SUPPLY", "ALIMENTATION SANS INTERRUPTION",
            "ELECTRICAL", "TRANSFORMER", "TRANSFORMATEUR", "SWITCHGEAR", "CELLULE 30KV",
            "POSTE ELECTRIQUE", "ATEX", "PROTECTION CATHODIQUE", "BATTERY", "BATTERIE",
            "ONDULEUR", "INVERTER", "REDRESSEUR", "RECTIFIER", "CHARGEUR", "CHARGER",
            "TGBT", "MCC", "POSTE HTA", "POSTE BT"
        ],
        "decrees": ["DE_21_261", "DE_17_62", "DE_21_257", "DE_24_278"],
        "esp_type": "Electrical"
    },
    "INSTRUMENTATION": {
        "label": "Instrumentation & Automation / Système DCS/ESD",
        "keywords": ["INSTRUMENT", "INSTRUMENTATION", "DCS", "ESD", "PLC", "TRANSMITTER", "VALVE ACTUATOR"],
        "decrees": ["DE_21_261", "DE_17_62", "DE_21_257"],
        "esp_type": "Instrumentation"
    },
    "SKID": {
        "label": "Skid Package / Unité Modulaire de Procédé",
        "keywords": ["SKID", "METERING SKID", "DOSING SKID", "INJECTION SKID", "PIG LAUNCHER SKID",
                     "SKID COMPTAGE", "FISCAL METERING", "PIG TRAP", "GARE DE RACLEUR", "UNIT MODULAIRE"],
        "decrees": ["DE_21_261", "DE_21_315", "DE_21_257", "DE_24_278"],
        "esp_type": "Package"
    },
    "FURNACE": {
        "label": "Fired Heater / Four de Procédé & Chaudière",
        "keywords": ["FURNACE", "FOUR", "FIRED HEATER", "BOILER", "CHAUDIERE", "GENERATEUR DE VAPEUR",
                     "STEAM GENERATOR", "THERMAL OXIDISER", "INCINERATEUR"],
        "decrees": ["DE_21_261", "DE_17_62", "DE_21_257"],
        "esp_type": "Fired_Heater"
    },
    "FLARE": {
        "label": "Flare System / Torche de Sécurité & Système de Gestion des Gaz Brûlés",
        "keywords": ["FLARE", "TORCHE", "FLARE STACK", "KNOCKOUT DRUM", "FLARE TIP",
                     "FLARE HEADER", "BLOWDOWN", "RELIEF HEADER", "KO DRUM"],
        "decrees": ["DE_21_261", "DE_21_314", "DE_21_257"],
        "esp_type": "Safety_System"
    },
    # ══════════════════════════════════════════════════════════════════════════
    # NOUVEAUX TYPES v3.0 — Accessoires, Robinetterie, Tuyauterie, Sécurité,
    # Mesurage, Filtration, Traçage, Génie Civil, Levage, SCADA, Détection
    # ══════════════════════════════════════════════════════════════════════════
    "BARRED_TEE": {
        "label": "Tés à Barreaux (Barred Tees / Scraper Tees pour Racleurs)",
        "keywords": [
            "BARRED TEE", "TEE A BARREAU", "TEE A BARREAUX", "TE A BARREAUX", "BARRED REDUCING TEE",
            "SCRAPER TEE", "PIGGABLE TEE", "GUIDE BARS TEE", "TE BARRE", "TÉ BARRÉ"
        ],
        "decrees": ["DE_21_315", "DE_21_261", "DE_17_62", "DE_24_278"],
        "esp_type": "Pressure_Fitting"
    },
    "FITTING": {
        "label": "Raccords & Accessoires de Canalisation Sous Pression (Tee à Barreau, Coudes, Réductions, Brides, Manchons)",
        "keywords": [
            "TEE A BARREAU", "BARRED TEE", "BARRED REDUCING TEE", "RACCORD", "FITTING",
            "COUDE", "ELBOW", "REDUCTION", "REDUCER", "MANCHON", "COUPLING", "SLEEVE",
            "CROIX", "CROSS FITTING", "CAP", "EMBOUT", "STUB END",
            "ACCESSOIRE CANALISATION", "PIPE FITTING", "FORGED FITTING", "WELD FITTING",
            "EQUAL TEE", "REDUCING TEE", "CONCENTRIC REDUCER", "ECCENTRIC REDUCER",
            "WELDOLET", "SOCKOLET", "THREADOLET", "LATROLET", "ELBOWLET",
            "SWEEPOLET", "INSERT FITTING", "PIGGABLE TEE", "SCRAPER TEE"
        ],
        "decrees": ["DE_21_315", "DE_21_261", "DE_17_62", "DE_24_278"],
        "esp_type": "Pressure_Fitting"
    },
    "FLANGE": {
        "label": "Brides Industrielles & Brides d'Ancrage (MSS SP-44, ASME B16.5, ASME B16.47)",
        "keywords": [
            "BRIDE D'ANCRAGE", "ANCHOR FLANGE", "BRIDE D'ENCRAGE", "BRIDES", "BRIDE",
            "FLANGES", "FLANGE", "WELDING NECK FLANGE", "WN FLANGE", "BLIND FLANGE",
            "SLIP ON FLANGE", "RTJ FLANGE", "RF FLANGE", "MSS SP-44", "ASME B16.5", "B16.47"
        ],
        "decrees": ["DE_21_315", "DE_21_261", "DE_17_62", "DE_24_278"],
        "esp_type": "Flange"
    },
    "VALVE": {
        "label": "Robinetterie Industrielle (Vannes, Clapets, Soupapes) — Toutes Catégories",
        "keywords": [
            "VANNE", "VANNES", "VALVE", "VALVES", "ROBINETTERIE", "ROBINETTERIES", "CLAPET", "CLAPETS", "CHECK VALVE", "CLAPET ANTI-RETOUR",
            "VANNE MANUELLE", "VANNES MANUELLES", "MANUAL VALVE", "MANUAL VALVES",
            "VANNE A BOISSEAU", "VANNES A BOISSEAU", "BALL VALVE", "BALL VALVES", "VANNE PAPILLON", "BUTTERFLY VALVE",
            "VANNE A OPERCULE", "GATE VALVE", "VANNE GLOBE", "GLOBE VALVE",
            "VANNE POINTEAU", "NEEDLE VALVE", "VANNE DIAPHRAGME", "DIAPHRAGM VALVE",
            "VANNE DE REGULATION", "CONTROL VALVE", "VANNES OBTURATEURS",
            "VANNE AUTOMATIQUE", "VANNE ATOMATIQUE", "AUTOMATIC VALVE", "VANNE MOTORISEE",
            "VANNE ESD", "ESD VALVE", "VANNE SDV", "SDV", "VANNE SDV/SOV", "SOV",
            "VANNE TRUNNION", "TRUNNION BALL VALVE", "VANNE FLOTTANTE", "FLOATING BALL VALVE",
            "VANNE TRIPLE OFFSET", "TRIPLE OFFSET VALVE", "SOUPAPE", "SOUPAPES", "SAFETY VALVE",
            "RELIEF VALVE", "VANNE DE DECHARGE", "VANNE PISTON", "PISTON VALVE",
            "VANNE GUILLOTINE", "PLUG VALVE"
        ],
        "decrees": ["DE_21_261", "DE_21_315", "DE_17_62", "DE_24_278"],
        "esp_type": "Valve"
    },
    "PIPING_SPOOL": {
        "label": "Tuyauteries Process & Spools d'Assemblage (Isométriques, Fabrication & Pose)",
        "keywords": [
            "SPOOL", "TUYAUTERIE", "PIPING", "PIPE SPOOL", "ASSEMBLAGE TUYAUTERIE",
            "ISOMETRIQUE", "ISOMETRIC DRAWING", "PREFAB", "PREFABRICATION",
            "TUYAUTERIE PROCEDE", "PROCESS PIPING", "SERVICE PIPING", "UTILITY PIPING",
            "TUYAUTERIE HP", "HIGH PRESSURE PIPING", "TUYAUTERIE VAPEUR", "STEAM PIPING",
            "PIPING CLASS", "CLASSE DE TUYAUTERIE", "PIPING SPECIFICATION", "PIPING STRESS",
            "STRESS ANALYSIS", "ANALYSE FLEXIBILITE", "FLEXIBILITY ANALYSIS",
            "TUYAUTERIE OFFSHORE", "SUBSEA PIPING", "BURIED PIPING", "TUYAUTERIE ENTERREE"
        ],
        "decrees": ["DE_21_261", "DE_21_315", "DE_17_62", "DE_24_278"],
        "esp_type": "Pressure_Piping"
    },
    "SAFETY_VALVE": {
        "label": "Organes de Protection & Sécurité Sous Pression (PSV/PRV, Disques de Rupture, Limiteurs de Débit)",
        "keywords": [
            "SOUPAPE DE SURETE", "SOUPAPE DE SECURITE", "SAFETY VALVE", "RELIEF VALVE",
            "PSV", "PRV", "PRESSURE SAFETY VALVE", "PRESSURE RELIEF VALVE",
            "DISQUE DE RUPTURE", "RUPTURE DISK", "BURSTING DISC", "BURST DISK",
            "LIMITEUR DE DEBIT", "FLOW RESTRICTOR", "EXCESS FLOW VALVE",
            "SOUPAPE PILOTEE", "PILOT OPERATED SAFETY VALVE", "POSV",
            "BACK PRESSURE VALVE", "SOUPAPE CONTREPRESSION",
            "ORGANE DE PROTECTION", "SAFETY DEVICE", "DISPOSITIF DE SECURITE"
        ],
        "decrees": ["DE_21_261", "DE_17_62", "DE_24_278"],
        "esp_type": "Safety_Device"
    },
    "FIRE_EXTINGUISHER": {
        "label": "Extincteurs d'Incendie & Bouteilles de Gaz Sous Pression (Décret 21-261 / EN 3-7 / EN 3-8 / ISO 7165)",
        "keywords": [
            "EXTINCTEUR", "FIRE EXTINGUISHER", "EXTINCTEURS", "POUDRE ABC", "POUDRE EXTINCTRICE",
            "EXTINCTEUR PORTATIF", "EXTINCTEUR MOBILE", "EXTINCTEUR CO2", "EXTINCTEUR EAU",
            "CORPS D'EXTINCTEUR", "BOUTEILLE D'EXTINCTEUR", "RESERVOIR EXTINCTEUR", "DESAUTEL",
            "SICLI", "EUROFEU", "ROT", "EN 3-7", "EN 3-8", "EN3-8", "EN3-7", "ISO 7165",
            "BOUTEILLE", "BOUTEILLES", "BOUTEILLE DE GAZ", "BOUTEILLES DE GAZ", "CYLINDRE", "CYLINDER", "GAS CYLINDER"
        ],
        "decrees": ["DE_21_261", "DE_17_62", "DE_24_278"],
        "esp_type": "Pressure_Receptacle"
    },
    "METERING": {
        "label": "Systèmes de Mesurage Fiscal & Comptage Gaz / Liquides Hydrocarbures",
        "keywords": [
            "METERING", "COMPTAGE", "MESURAGE", "MESURAGE FISCAL", "FISCAL METERING",
            "COMPTEUR DE GAZ", "GAS METER", "DEBITMETRIE", "DEBITmetre", "FLOW METER",
            "TURBINE METER", "CORIOLIS", "ULTRASONIC METER", "VORTEX METER",
            "ORIFICE PLATE", "PLAQUE D'ORIFICE", "VENTURI", "NOZZLE METER",
            "METERING STATION", "STATION DE MESURAGE", "STATION DE COMPTAGE",
            "POSTE DE MESURAGE", "ALLOCATION METERING", "CUSTODY TRANSFER",
            "TRANSFERT DE PROPRIETE", "UNITÉ DE COMPTAGE", "RECALIBRATION"
        ],
        "decrees": ["DE_21_315", "DE_21_257", "DE_24_278"],
        "esp_type": "Metering_System"
    },
    "FILTER_SEPARATOR": {
        "label": "Filtres, Epurateurs & Séparateurs Filtrants Sous Pression",
        "keywords": [
            "FILTRE", "FILTER", "EPURATEUR", "SEPARATOR FILTRE", "FILTER SEPARATOR",
            "FILTRE A GAZ", "GAS FILTER", "FILTRE A PANIER", "BASKET FILTER",
            "FILTRE EN Y", "Y-STRAINER", "FILTRE DUPLEX", "DUPLEX FILTER",
            "FILTRE COALESCER", "COALESCER FILTER", "FILTRE A CARTOUCHE", "CARTRIDGE FILTER",
            "FILTRE AUTOMATIQUE", "SELF-CLEANING FILTER", "STRAINER", "CREPINE",
            "FILTRE DESSICATEUR", "DESICCANT FILTER", "MOLECULAR SIEVE", "TAMIS MOLECULAIRE",
            "FILTRE PIPELINE", "INLINE FILTER", "FILTRE GRAVELEUX", "SAND FILTER"
        ],
        "decrees": ["DE_21_261", "DE_17_62", "DE_21_257", "DE_24_278"],
        "esp_type": "Fixed_ESP"
    },
    "HEAT_TRACING": {
        "label": "Traçage Thermique Électrique/Vapeur & Calorifugeage des Tuyauteries et Équipements",
        "keywords": [
            "TRACAGE THERMIQUE", "HEAT TRACING", "ELECTRICAL HEAT TRACING", "EHT",
            "TRACAGE VAPEUR", "STEAM TRACING", "TRACAGE ELECTRIQUE",
            "CALORIFUGEAGE", "INSULATION", "ISOLATION THERMIQUE", "THERMAL INSULATION",
            "MAINTIEN EN TEMPERATURE", "TEMPERATURE MAINTENANCE", "ANTI-GEL", "ANTI-FREEZE",
            "SKIN EFFECT HEATING", "IMPEDANCE HEATING", "MINERAL INSULATED CABLE"
        ],
        "decrees": ["DE_21_261", "DE_24_278"],
        "esp_type": "Utility_System"
    },
    "STRUCTURAL_STEEL": {
        "label": "Structures Métalliques, Charpentes, Racks de Tuyauterie & Supports",
        "keywords": [
            "STRUCTURE METALLIQUE", "STRUCTURAL STEEL", "CHARPENTE", "CHARPENTE METALLIQUE",
            "RACK DE TUYAUTERIE", "PIPE RACK", "PORTIQUE", "GANTRY", "FRAME",
            "PLATEFORME", "PLATFORM", "PASSERELLE", "WALKWAY", "MEZZANINE",
            "SUPPORT TUYAUTERIE", "PIPE SUPPORT", "HANGAR", "ABRI", "SHELTER",
            "GARDE-CORPS", "HANDRAIL", "ECHELLE", "LADDER", "ACCES", "STAIRCASE",
            "POUTRE", "BEAM", "COLONNE ACIER", "STEEL COLUMN", "CONTREVENTEMENT",
            "BRACING", "TREILLIS", "TRUSS", "OSSATURE ACIER", "STEEL STRUCTURE"
        ],
        "decrees": ["DE_21_261", "DE_24_278"],
        "esp_type": "Civil_Structural"
    },
    "CIVIL_FOUNDATION": {
        "label": "Génie Civil & Fondations (Massifs, Traversées, Ancrages, Rétentions)",
        "keywords": [
            "FONDATION", "FOUNDATION", "MASSIF", "BETON", "CONCRETE", "GENIE CIVIL",
            "CIVIL WORKS", "TRAVERSE DE ROUTE", "ROAD CROSSING", "CROSSING",
            "ANCRAGE", "ANCHORING", "SOCLE", "PEDESTAL", "DALLE", "SLAB",
            "RETENTION", "BUND WALL", "MUR DE RETENTION", "BASSIN DE RETENTION",
            "CUVETTE", "DRIP TRAY", "PIEU", "PILE", "MICROPIEU", "MICROPILE",
            "REMBLAI", "EARTHWORK", "TERRASSEMENT", "EXCAVATION", "FOUILLE",
            "ETANCHEITE", "WATERPROOFING", "BITUME", "GEOMEMBRANE"
        ],
        "decrees": ["DE_21_315", "DE_24_278"],
        "esp_type": "Civil_Works"
    },
    "GAS_FIRE_DETECTION": {
        "label": "Systèmes de Détection Gaz & Incendie (FGS/FAS/ESD — Zones ATEX)",
        "keywords": [
            "DETECTION GAZ", "GAS DETECTION", "DETECTEUR GAZ", "GAS DETECTOR",
            "DETECTION INCENDIE", "FIRE DETECTION", "DETECTEUR INCENDIE", "FIRE DETECTOR",
            "FGS", "FAS", "FIRE AND GAS SYSTEM", "SYSTEME DETECTION",
            "POINT CHAUD", "HEAT DETECTOR", "FLAMME", "FLAME DETECTOR",
            "CENTRALE D'ALARME", "FIRE PANEL", "ANNEAU DE GAZ", "GAS RING MAIN",
            "SPRINKLER", "MOUSSE", "FOAM SYSTEM", "DELUGE", "HALON",
            "DETECTION POINT FIXE", "DETECTION PORTATIVE", "DETECTEUR CATALYTIQUE",
            "INFRAROUGE", "ULTRAVIOLET", "UV IR DETECTOR", "CCTV DETECTION"
        ],
        "decrees": ["DE_21_261", "DE_17_62", "DE_21_257", "DE_24_278"],
        "esp_type": "Safety_System"
    },
    "TELECOM_SCADA": {
        "label": "Systèmes de Télécommunication, SCADA & Contrôle à Distance",
        "keywords": [
            "TELECOM", "TELECOMMUNICATION", "SCADA", "DCS", "SUPERVISION",
            "RTU", "REMOTE TERMINAL UNIT", "PLC SCADA", "AUTOMATE SCADA",
            "FIBRE OPTIQUE", "OPTICAL FIBER", "RADIO VHF", "RADIO UHF",
            "LIAISON HERTZIENNE", "MICROWAVE LINK", "SATELLITE", "VSAT",
            "SYSTEME DE CONTROLE", "CONTROL SYSTEM", "HMI", "IHM",
            "SERVEUR SCADA", "HISTORIEN", "HISTORIAN", "OPC", "MODBUS",
            "RESEAU INDUSTRIEL", "INDUSTRIAL NETWORK", "ETHERNET INDUSTRIEL",
            "PROTOCOLE", "PROTOCOL", "ALARME", "MONITORING", "TELECONTROLE"
        ],
        "decrees": ["DE_21_261", "DE_21_257", "DE_24_278"],
        "esp_type": "Telecom_System"
    },
    "CRANE_LIFTING": {
        "label": "Engins de Levage, Manutention & Appareils de Levage (Grues, Palans, Chariots)",
        "keywords": [
            "GRUE", "CRANE", "LEVAGE", "LIFTING", "APPAREIL DE LEVAGE", "LIFTING EQUIPMENT",
            "PALAN", "HOIST", "PONT ROULANT", "OVERHEAD CRANE", "PORTIQUE GRUE", "GANTRY CRANE",
            "CHARIOT ELEVATEUR", "FORKLIFT", "NACELLE", "MAN BASKET", "CHERRY PICKER",
            "TREUIL", "WINCH", "MOUFLE", "BLOCK AND TACKLE", "ELINGUE", "SLING",
            "PALONNIER", "SPREADER BAR", "CROCHET", "HOOK", "SHACKLE", "MANILLE",
            "VERIFICATION ANNUELLE LEVAGE", "PERIODIC INSPECTION CRANE", "LOAD TEST",
            "ESSAI DE CHARGE", "CERTIFICAT LEVAGE", "LIFTING CERTIFICATE"
        ],
        "decrees": ["DE_21_261", "DE_24_278"],
        "esp_type": "Lifting_Equipment"
    }
}

# ══════════════════════════════════════════════════════════════════════════════
# LISTES DOCUMENTAIRES EXIGÉES PAR TYPE D'ÉQUIPEMENT (CHECKLISTS DYNAMIQUES)
# ══════════════════════════════════════════════════════════════════════════════

MANDATORY_DOCUMENTS_MASTER = {
    "PRESSURE_VESSEL": [
        {"code": "DS", "name": "Spécification Technique & Fiche de Données (Equipment Data Sheet)", "criticality": "Critical", "aliases": ["DATA SHEET", "DATASHEET", "FICHE TECHNIQUE", "SPECIFICATION TECHNIQUE"]},
        {"code": "CALC", "name": "Note de Calcul d'Épaisseur & Résistance Mécanique (ASME VIII / EN 13445)", "criticality": "Critical", "aliases": ["CALCUL", "CALCULATION", "NOTE DE CALCUL", "STRESS", "ASME VIII", "EN 13445"]},
        {"code": "GA_DWG", "name": "Plan d'Ensemble GA & Coupes de Fabrication (General Arrangement Drawing)", "criticality": "Major", "aliases": ["GENERAL ARRANGEMENT", "PLAN D'ENSEMBLE", "PLAN GA", "DRAWING GA", "PLAN COUPE"]},
        {"code": "FAB_DWG", "name": "Plans de Détails & Assemblage de Fabrication", "criticality": "Major", "aliases": ["FABRICATION DRAWING", "PLAN FABRICATION", "PLAN ASSEMBLAGE", "DETAILED DRAWING"]},
        {"code": "WELD_BOOK", "name": "Cahier de Soudage Officiel (WPS, PQR, WPQ, Cartographie Soudures)", "criticality": "Critical", "aliases": ["CAHIER DE SOUDAGE", "WELDING BOOK", "WPS", "PQR", "WPQ", "WELDING PROCEDURE", "QUALIFICATION SOUDAGE"]},
        {"code": "NDT_REP", "name": "Procès-Verbaux de Contrôles Non Destructifs CND (RT / UT / MT / PT)", "criticality": "Critical", "aliases": ["RAPPORT CND", "NDT REPORT", "RADIOGRAPHIE", "ULTRASONS", "CONTROLE NON DESTRUCTIF", "RT REPORT", "UT REPORT"]},
        {"code": "PWHT_REP", "name": "Diagrammes & Procès-Verbaux de Traitement Thermique (PWHT)", "criticality": "Major", "aliases": ["PWHT", "TRAITEMENT THERMIQUE", "HEAT TREATMENT", "DIAGRAMME PWHT"]},
        {"code": "MAT_CERT", "name": "Certificats de Réception Matière EN 10204 3.1 / 3.2 (Heat Numbers)", "criticality": "Critical", "aliases": ["CERTIFICAT MATIERE", "MILL CERTIFICATE", "EN 10204", "HEAT NUMBER", "MATERIAL CERTIFICATE", "CERT MATIERE"]},
        {"code": "HYDRO_PV", "name": "Procès-Verbal d'Épreuve Hydrostatique usine & Diagramme d'Enregistrement (150% PMA)", "criticality": "Critical", "aliases": ["PV HYDROSTATIQUE", "HYDROTEST REPORT", "EPREUVE HYDROSTATIQUE", "TEST PRESSURE", "PRESSURE TEST CHART"]},
        {"code": "INSP_REP", "name": "Certificat de Réception & Rapport de l'Organisme Tiers Habilité (Bureau ARH Agrée)", "criticality": "Critical", "aliases": ["RAPPORT ORGANISME TIERS", "THIRD PARTY INSPECTION", "ORGANISME HABILITE", "ALGERAC", "BUREAU D'INSPECTION", "RAPPORT DE RECEPTION"]},
        {"code": "PAINT_REP", "name": "Rapport d'Inspection de Préparation de Surface & Peinture / Revêtement", "criticality": "Minor", "aliases": ["RAPPORT PEINTURE", "COATING INSPECTION", "SURFACE PREPARATION", "PAINT REPORT", "REVETEMENT ANTICORROSION"]},
        {"code": "NAMEPLATE", "name": "Dessin & Photo de la Plaque Signalétique Poinçonnée ARH", "criticality": "Major", "aliases": ["PLAQUE SIGNALETIQUE", "NAMEPLATE DRAWING", "PLAQUE CONSTRUCTEUR", "TAG PLAQUE"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage Officiel ج م (Décret 17-62, Art. 12)", "criticality": "Critical", "aliases": ["DECLARATION DE CONFORMITE", "MARQUAGE CONFORMITE", "MARQUE JIM", "MARQUAGE DZ", "CERTIFICAT DE CONFORMITE"]},
        {"code": "SAFETY_CALC", "name": "Note de Dimensionnement & Certificat de Tarage des Soupapes de Sécurité (PSV/PRV)", "criticality": "Critical", "aliases": ["NOTE SOUPAPE", "SAFETY VALVE SIZING", "PSV DATASHEET", "PRV SIZING", "TARAGE SOUPAPE", "VALVE SIZING CALCULATION"]},
        {"code": "ITP", "name": "Plan d'Inspection et d'Essais (PIE / ITP) Approuvé par Bureau ARH", "criticality": "Critical", "aliases": ["PLAN D'INSPECTION", "INSPECTION TEST PLAN", "PIE", "ITP APPROUVE", "PLAN QUALITE INSPECTION"]},
        {"code": "FAT", "name": "Procès-Verbal des Essais de Réception en Usine (FAT)", "criticality": "Major", "aliases": ["FACTORY ACCEPTANCE TEST", "PV RECEPTION USINE", "ESSAIS USINE FAT", "FAT REPORT"]}
    ],
    "TANK": [
        {"code": "DS", "name": "Fiche de Données du Bac de Stockage (API 650 / API 620)", "criticality": "Critical", "aliases": ["DATA SHEET BAC", "DATASHEET TANK", "FICHE TECHNIQUE BAC", "TANK SPECIFICATION"]},
        {"code": "CALC", "name": "Note de Calcul de Robe, Fond & Toit (API 650 / 620) avec Analyse Sismique", "criticality": "Critical", "aliases": ["CALCUL BAC", "TANK CALCULATION", "API 650 CALCULATION", "SHELL DESIGN", "NOTE DE CALCUL BAC"]},
        {"code": "GA_DWG", "name": "Plan d'Ensemble du Bac & Table de Jaugeage / Baremage Officiel", "criticality": "Major", "aliases": ["PLAN D'ENSEMBLE BAC", "GENERAL ARRANGEMENT TANK", "TABLE DE JAUGEAGE", "STRAPPING TABLE"]},
        {"code": "WELD_BOOK", "name": "Qualifications de Soudage WPS/PQR & Procédures de Soudage Robe/Fond", "criticality": "Critical", "aliases": ["CAHIER SOUDAGE BAC", "WELDING PROCEDURE TANK", "WPS PQR BAC", "QUALIFICATION SOUDEUR BAC"]},
        {"code": "NDT_REP", "name": "PV de Contrôle CND Radiographie 100% des Soudures de Robe (Art. 59 Décret 21-315)", "criticality": "Critical", "aliases": ["RAPPORT CND BAC", "NDT TANK", "RADIOGRAPHIE ROBE", "RT 100% SHELL"]},
        {"code": "VACUUM_TEST", "name": "Rapport d'Essai Boîte à Vide des Soudures de Fond (Vacuum Box Test)", "criticality": "Critical", "aliases": ["BOITE A VIDE", "VACUUM BOX TEST", "FOND TEST ETANCHEITE", "BOTTOM WELD TEST"]},
        {"code": "MAT_CERT", "name": "Certificats de Réception des Tôles de Robe, Fond & Toit (EN 10204 3.1)", "criticality": "Critical", "aliases": ["CERTIFICAT TOLES", "PLATE MILL CERTIFICATE", "EN 10204 BAC", "MATERIAL CERT TANK"]},
        {"code": "HYDRO_PV", "name": "PV d'Épreuve d'Eau (Water Fill Test) & Contrôle du Tassement sous Supervision ARH", "criticality": "Critical", "aliases": ["EPREUVE D'EAU", "WATER FILL TEST", "TEST TASSEMENT", "SETTLEMENT MONITORING", "PV EPREUVE BAC"]},
        {"code": "CATHODIC", "name": "Rapport d'Étude & Contrôle de la Protection Cathodique (Fond du Bac)", "criticality": "Major", "aliases": ["PROTECTION CATHODIQUE BAC", "CATHODIC PROTECTION TANK", "ANODE FOND", "CATHODIC STUDY"]},
        {"code": "CALIBRATION", "name": "Certificat Officiel de Jaugeage/Baremage & Barème Volumétrique Légal", "criticality": "Critical", "aliases": ["CERTIFICAT JAUGEAGE", "BAREMAGE OFFICIEL", "STRAPPING CERTIFICATE", "VOLUMETRIC TABLE", "CALIBRATION REPORT"]},
        {"code": "INSP_REP", "name": "Visa de Libération & Rapport Final de l'Organisme Tiers Habilité ARH", "criticality": "Critical", "aliases": ["RAPPORT TIERS BAC", "THIRD PARTY TANK", "ORGANISME HABILITE BAC", "RAPPORT LIBERATION"]}
    ],
    "LINEPIPE": [
        {"code": "DS", "name": "Spécification Technique & Fiche de Données Tubes en Usine (API 5L / ISO 3183)", "criticality": "Critical", "aliases": ["DATA SHEET TUBE", "LINEPIPE SPECIFICATION", "SPECIFICATION TUBE", "API 5L", "ISO 3183", "TECHNICAL SPECIFICATION", "FOURNITURE DE TUBES"]},  # Bug5 fix: alias "DOSSIER ARH" retire (trop generique, faux positifs)
        {"code": "PIPE_CALC", "name": "Note de Calcul d'Épaisseur Nominale & Pression de Design Tube (Décret 21-315 Art. 7)", "criticality": "Critical", "aliases": ["NOTE DE CALCUL", "CALCUL EPAISSEUR", "THICKNESS CALCULATION", "WALL THICKNESS", "DESIGN PRESSURE CALC", "CALCULATION NOTE", "STRESS CALCULATION", "MARGE EN EPAISSEUR", "EPAISSEUR DE CALCUL", "CALCUL D'EPAISSEUR"]},
        {"code": "MILL_WELD", "name": "Qualifications de Procédure de Fabrication Usine & Soudage Longitudinal/Hélicoïdal (WPS/PQR Usine)", "criticality": "Critical", "aliases": ["MILL WELDING", "WPS USINE", "PQR USINE", "FABRICATION PROCEDURE", "MILL WPS", "PROCEDURE DE FABRICATION", "SOUDAGE EN USINE", "WELDING PROCEDURE"]},
        {"code": "MAT_CERT", "name": "Certificats de Réception Matière EN 10204 3.1 / 3.2 (Analyse Chimique & Essais Mécaniques)", "criticality": "Critical", "aliases": ["CERTIFICAT MATIERE", "MILL CERTIFICATE", "EN 10204", "HEAT NUMBER", "3.1", "3.2", "CHEMICAL ANALYSIS", "MECHANICAL TEST", "CERTIFICAT DE RECEPTION", "COMPOSITION CHIMIQUE", "ESSAI DE TRACTION"]},
        {"code": "NDT_REP", "name": "PV de Contrôles Non Destructifs Usine (Ultrasons / Radiographie Soudures Usine)", "criticality": "Critical", "aliases": ["NDT MILL", "CND USINE", "ULTRASONS USINE", "RADIOGRAPHIE USINE", "UT REPORT", "RT REPORT", "AUTOMATIC UT", "CONTROLE NON DESTRUCTIF", "CND EN USINE"]},
        {"code": "HYDRO_PV", "name": "Procès-Verbal d'Épreuve Hydrostatique en Usine (Décret 21-315 Art. 21 - Hydrotest usine)", "criticality": "Critical", "aliases": ["HYDROTEST USINE", "MILL HYDROTEST", "EPREUVE USINE", "HYDROSTATIC TEST CERTIFICATE", "PRESSURE TEST MILL", "PV EPREUVE HYDROSTATIQUE USINE"]},
        {"code": "MILL_COATING", "name": "Rapport d'Inspection du Revêtement Externe/Interne Usine (3LPE / 3LPP / FBE)", "criticality": "Major", "aliases": ["COATING MILL", "REVETEMENT USINE", "3LPE", "3LPP", "FBE", "COATING CERTIFICATE", "INSPECTION DU REVETEMENT"]},
        {"code": "INSP_REP", "name": "Visa de Réception & Rapport Final de l'Organisme Tiers Habilité ARH (Bureau d'Inspection Usine)", "criticality": "Critical", "aliases": ["RAPPORT TIERS USINE", "THIRD PARTY MILL", "ORGANISME HABILITE ARH", "INSPECTION CERTIFICATE", "ALGERAC", "BUREAU VERITAS", "SGS", "TUV", "VERITAL", "LLOYDS", "LR", "RELEASE NOTE", "IRN", "INSPECTION RELEASE", "VISA", "VISA TIERS", "VISA D'INSPECTION", "VISA D'APPROBATION", "TAMPON D'INSPECTION", "STAMP", "INSPECTEUR", "RAPPORT D'INSPECTION", "INSPECTION REPORT", "CERTIFICAT DE LIBERATION", "CERTIFICAT DE CONFORMITE", "PV D'INSPECTION", "RECEPTION TIERS", "APPROVED BY", "INSPECTED BY", "CERTIFICAT DE RECEPTION"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage Officiel ج م (Décret 17-62)", "criticality": "Critical", "aliases": ["DECLARATION CONFORMITE", "MARQUAGE JIM", "CERTIFICAT CONFORMITE", "CONFORMITE ARH"]}
    ],
    "PIPELINE": [
        {"code": "ALIGN_DWG", "name": "Plans de Tracé en Plan & Profil en Long (Alignment Sheets)", "criticality": "Critical", "aliases": ["ALIGNMENT SHEET", "PROFIL EN LONG", "PLAN DE TRACE", "ROUTE SURVEY"]},
        {"code": "ISO_DWG", "name": "Isométriques des Gares de Racleurs, Postes de Vannes & Manifolds", "criticality": "Major", "aliases": ["ISOMETRIQUE PIPELINE", "ISO DRAWING PIPELINE", "GARE DE RACLEUR", "PIG TRAP ISOMETRIC"]},
        {"code": "PIPE_CALC", "name": "Note de Calcul d'Épaisseur Tube selon Décret 21-315 Art.7 & Analyse de Flexibilité", "criticality": "Critical", "aliases": ["CALCUL EPAISSEUR TUBE", "PIPE THICKNESS CALCULATION", "DECRET 21-315 ART 7", "WALL THICKNESS NOTE"]},
        {"code": "WELD_BOOK", "name": "Carnet de Soudage de Ligne, QMOS/QS & Cartographie Complète des Soudures", "criticality": "Critical", "aliases": ["CARNET DE SOUDAGE PIPELINE", "LINE WELDING BOOK", "WELD MAP PIPELINE", "QMOS QS PIPELINE"]},
        {"code": "NDT_REP", "name": "PV de Contrôle Radiographique/UT selon Zones A-D (Art. 8/9 Décret 21-314)", "criticality": "Critical", "aliases": ["RAPPORT CND PIPELINE", "NDT PIPELINE REPORT", "RADIOGRAPHIE SOUDURE LIGNE", "RT UT PIPELINE"]},
        {"code": "HYDRO_PV", "name": "PV d'Épreuve Hydrostatique de Tronçon (150% PMA A/B — 125% C/D, Art.21)", "criticality": "Critical", "aliases": ["PV HYDROSTATIQUE PIPELINE", "HYDROTEST LINE REPORT", "EPREUVE TRONCON", "LINE PRESSURE TEST"]},
        {"code": "COATING_REP", "name": "Rapport d'Inspection du Revêtement Externe & Test Balai Étincelle (Holiday Test)", "criticality": "Major", "aliases": ["RAPPORT REVETEMENT", "COATING INSPECTION PIPELINE", "HOLIDAY TEST REPORT", "BALAI ETINCELLE"]},
        {"code": "CATHODIC", "name": "Rapport d'Étude & Mise en Service Protection Cathodique (Décret 21-315)", "criticality": "Critical", "aliases": ["PROTECTION CATHODIQUE PIPELINE", "CATHODIC PIPELINE", "CATHODIC COMMISSIONING", "CP REPORT"]},
        {"code": "PIGGING", "name": "Rapports de Passage du Piston Gabarit, Nettoyage & Raclage de Mise en Service", "criticality": "Major", "aliases": ["PISTON GABARIT", "GAUGING PIG RUN", "PIGGING REPORT", "NETTOYAGE PIPELINE"]},
        {"code": "ARH_APPROVAL", "name": "Dossier Préliminaire Approuvé ARH & Autorisation de Mise en Produit (Décret 21-257)", "criticality": "Critical", "aliases": ["AUTORISATION MISE EN PRODUIT", "ARH APPROVAL PIPELINE", "DECRET 21-257 PIPELINE"]}
    ],
    "ELECTRICAL": [
        {"code": "DS", "name": "Spécification Technique & Schéma Unifilaire Principal (Single Line Diagram)", "criticality": "Critical", "aliases": ["DATA SHEET ELECTRIQUE", "UNIFILAIRE", "SINGLE LINE DIAGRAM", "SLD", "SCHEMA PRINCIPAL"]},
        {"code": "SHORT_CIRCUIT", "name": "Note de Calcul de Court-Circuit & Coordination des Protections Électriques", "criticality": "Critical", "aliases": ["CALCUL COURT-CIRCUIT", "SHORT CIRCUIT CALCULATION", "COORDINATION PROTECTION", "POWER SYSTEM STUDY"]},
        {"code": "ATEX_CERT", "name": "Certificats de Conformité ATEX / IECEx des Matériels en Zones Explosives", "criticality": "Critical", "aliases": ["CERTIFICAT ATEX", "IECEX CERTIFICATE", "EXPLOSION PROOF CERT", "ZONE ATEX CERTIFICATE"]},
        {"code": "BATTERY_AUTONOMY", "name": "Note de Calcul de Capacité Batteries & Autonomie ASI/UPS (en heures)", "criticality": "Critical", "aliases": ["CALCUL BATTERIE", "BATTERY AUTONOMY CALCULATION", "UPS SIZING", "ASI DIMENSIONNEMENT"]},
        {"code": "EARTHING", "name": "PV de Mesure de Résistance de Mise à la Terre & Continuité des Masses", "criticality": "Critical", "aliases": ["MESURE TERRE", "EARTHING TEST", "GROUND RESISTANCE", "CONTINUITE MASSE", "PV TERRE"]},
        {"code": "DIELECTRIC", "name": "PV d'Essais Diélectriques & Rigidité d'Isolement (High Voltage Test)", "criticality": "Critical", "aliases": ["ESSAI DIELECTRIQUE", "HV TEST REPORT", "INSULATION TEST", "RIGIDITE ELECTRIQUE", "DIELECTRIC TEST"]},
        {"code": "FAT", "name": "PV des Essais de Réception en Usine (FAT) de l'Armoire/Tableau Électrique", "criticality": "Major", "aliases": ["FAT ELECTRIQUE", "FACTORY TEST TABLEAU", "ESSAIS USINE TABLEAU", "FAT SWITCHBOARD"]},
        {"code": "SAT", "name": "PV des Essais sur Site (SAT) & Autorisation de Mise sous Tension ARH (Art. 77)", "criticality": "Critical", "aliases": ["SAT ELECTRIQUE", "SITE ACCEPTANCE TEST", "MISE SOUS TENSION", "ARH MISE SOUS TENSION"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage Officiel ج م (Décret 17-62)", "criticality": "Critical", "aliases": ["DECLARATION CONFORMITE ELECTRIQUE", "MARQUAGE JIM", "CERT CONFORMITE ELECTRIQUE"]}
    ],
    "ROTATING_MACHINERY": [
        {"code": "DS", "name": "Spécification Technique & Fiche de Données Compresseur/Pompe", "criticality": "Critical", "aliases": ["DATA SHEET POMPE", "DATASHEET COMPRESSEUR", "PUMP SPECIFICATION", "COMPRESSOR DATASHEET"]},
        {"code": "GA_DWG", "name": "Plan d'Ensemble GA & Empreinte du Skid/Châssis", "criticality": "Major", "aliases": ["PLAN D'ENSEMBLE POMPE", "GENERAL ARRANGEMENT PUMP", "SKID LAYOUT", "CHASSIS DRAWING"]},
        {"code": "PERF_CURVE", "name": "Courbes de Performance & Rendement Hydraulique/Aéraulique Garanties", "criticality": "Critical", "aliases": ["COURBE PERFORMANCE", "PERFORMANCE CURVE", "PUMP CURVE", "COMPRESSOR CURVE", "RENDEMENT HYDRAULIQUE"]},
        {"code": "MOTOR_ATEX", "name": "Certificat ATEX / IECEx du Moteur Électrique d'Entraînement", "criticality": "Critical", "aliases": ["CERTIFICAT ATEX MOTEUR", "MOTOR ATEX CERTIFICATE", "IECEX MOTOR", "MOTEUR ZONE ATEX"]},
        {"code": "VIB_REP", "name": "Procès-Verbal des Essais de Vibrations & Équilibrage Dynamique (ISO 10816)", "criticality": "Major", "aliases": ["RAPPORT VIBRATION", "VIBRATION TEST REPORT", "BALANCING CERTIFICATE", "EQUILIBRAGE DYNAMIQUE"]},
        {"code": "SEAL_CERT", "name": "Fiche & Plan de la Garniture Mécanique / Plan de Rinçage (API 682)", "criticality": "Major", "aliases": ["FICHE GARNITURE", "SEAL PLAN", "API 682", "MECHANICAL SEAL DATASHEET", "FLUSHING PLAN"]},
        {"code": "FAT", "name": "PV des Essais de Performance & Réception Usine (FAT / Performance Test)", "criticality": "Critical", "aliases": ["FAT POMPE", "FACTORY ACCEPTANCE PUMP", "PERFORMANCE TEST REPORT", "FAT COMPRESSEUR"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage Officiel ج م (Décret 17-62)", "criticality": "Critical", "aliases": ["DECLARATION CONFORMITE POMPE", "MARQUAGE JIM POMPE", "CERT CONFORMITE COMPRESSEUR"]}
    ],
    "INSTRUMENTATION": [
        {"code": "DS", "name": "Fiche de Données Instrument / Transmetteur / Vanne de Régulation", "criticality": "Critical", "aliases": ["DATA SHEET INSTRUMENT", "INSTRUMENT DATASHEET", "TRANSMITTER DATASHEET", "CONTROL VALVE DATASHEET"]},
        {"code": "LOOP_DWG", "name": "Schéma de Câblage & Diagramme de Boucle de Régulation (Loop Diagram)", "criticality": "Major", "aliases": ["LOOP DIAGRAM", "BOUCLE DE REGULATION", "CABLAGE INSTRUMENT", "LOOP DRAWING"]},
        {"code": "ATEX_CERT", "name": "Certificat ATEX / IECEx Sécurité Intrinsèque (Ex i / Ex d / Ex e)", "criticality": "Critical", "aliases": ["CERTIFICAT ATEX INSTRUMENT", "IECEX INSTRUMENT", "SECURITE INTRINSEQUE", "EX I CERT", "EX D CERT"]},
        {"code": "CALIBRATION", "name": "PV d'Étalonnage & Certificat de Calibration Usine (Traçabilité Métrologique)", "criticality": "Critical", "aliases": ["PV ETALONNAGE", "CALIBRATION CERTIFICATE", "INSTRUMENT CALIBRATION", "METROLOGIE INSTRUMENT"]},
        {"code": "SIL_CERT", "name": "Certificat SIL / Sécurité Fonctionnelle IEC 61508 / IEC 61511 (ESD/SIS)", "criticality": "Major", "aliases": ["SIL CERTIFICATE", "SAFETY INTEGRITY LEVEL", "IEC 61511 CERT", "SIS CERTIFICATION", "FUNCTIONAL SAFETY"]},
        {"code": "SAT", "name": "PV de Test de Boucle & Mise en Service sur Site (Loop Test / SAT / Pre-Commissioning)", "criticality": "Critical", "aliases": ["LOOP TEST", "SAT INSTRUMENT", "PRE-COMMISSIONING", "COMMISSIONING TEST", "BOUCLE TEST SITE"]}
    ],
    # ── SKID ──────────────────────────────────────────────────────────────────────
    "SKID": [
        {"code": "DS", "name": "Spécification Technique Générale du Skid / Datasheet Package", "criticality": "Critical", "aliases": ["DATA SHEET SKID", "SKID SPECIFICATION", "PACKAGE DATASHEET", "FICHE TECHNIQUE SKID"]},
        {"code": "PFD_PID", "name": "Schéma de Procédé (PFD) & Schéma de Tuyauterie et Instrumentation (P&ID) du Skid", "criticality": "Critical", "aliases": ["PFD SKID", "PID SKID", "PROCESS DIAGRAM SKID", "TUYAUTERIE INSTRUMENTATION SKID"]},
        {"code": "GA_DWG", "name": "Plan d'Ensemble du Skid, Implantation & Général Arrangement", "criticality": "Major", "aliases": ["PLAN IMPLANTATION SKID", "GA SKID", "GENERAL ARRANGEMENT SKID", "LAYOUT SKID"]},
        {"code": "INTEGRATION_NOTE", "name": "Note d'Intégration ATEX & Analyse des Risques de Zone Explosive du Skid", "criticality": "Critical", "aliases": ["NOTE INTEGRATION ATEX", "ZONE ANALYSIS SKID", "ATEX ZONE SKID", "HAZARDOUS AREA CLASSIFICATION"]},
        {"code": "WELD_BOOK", "name": "Qualification de Soudage WPS/PQR & Carnet de Soudage Tubulures du Skid", "criticality": "Critical", "aliases": ["SOUDAGE SKID", "WPS PQR SKID", "WELDING SKID", "QUALIFICATION SOUDURE SKID"]},
        {"code": "NDT_REP", "name": "PV de CND des Soudures de Pression du Skid (RT / UT)", "criticality": "Critical", "aliases": ["NDT SKID", "CND SKID", "RT UT SKID", "RADIOGRAPHIE SKID"]},
        {"code": "MAT_CERT", "name": "Certificats Matière EN 10204 3.1 des Composants Sous Pression du Skid", "criticality": "Critical", "aliases": ["CERTIFICAT MATIERE SKID", "MILL CERT SKID", "MATERIAL CERT SKID"]},
        {"code": "WEIGHT_CERT", "name": "Certificat de Pesée Officiel & Rapport de Centre de Gravité du Skid", "criticality": "Major", "aliases": ["CERTIFICAT PESEE", "WEIGHT CERTIFICATE", "CENTRE DE GRAVITE", "LIFTING CERT"]},
        {"code": "HYDRO_PV", "name": "PV d'Épreuve Hydrostatique des Circuits Sous Pression du Skid (150% PMA)", "criticality": "Critical", "aliases": ["HYDROTEST SKID", "PV EPREUVE SKID", "PRESSURE TEST SKID"]},
        {"code": "FAT", "name": "Procès-Verbal de Réception & Essais Usine (FAT) du Skid Complet", "criticality": "Critical", "aliases": ["FAT SKID", "FACTORY ACCEPTANCE SKID", "RECEPTION USINE SKID", "PV FAT SKID"]},
        {"code": "INSP_REP", "name": "Rapport Final de l'Organisme Tiers Habilité ARH & Visa de Libération", "criticality": "Critical", "aliases": ["RAPPORT TIERS SKID", "THIRD PARTY SKID", "ORGANISME HABILITE SKID"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage ج م (Décret 17-62)", "criticality": "Critical", "aliases": ["DECLARATION CONFORMITE SKID", "MARQUAGE JIM SKID"]}
    ],
    # ── FURNACE ───────────────────────────────────────────────────────────────────
    "FURNACE": [
        {"code": "DS", "name": "Fiche de Données du Four / Chaudière & Spécification Thermique", "criticality": "Critical", "aliases": ["DATA SHEET FOUR", "FURNACE DATASHEET", "BOILER SPECIFICATION", "THERMAL SPECIFICATION"]},
        {"code": "THERMAL_NOTE", "name": "Note de Calcul de Radiation Thermique & Bilan Thermique (Heat & Material Balance)", "criticality": "Critical", "aliases": ["NOTE RADIATION THERMIQUE", "THERMAL RADIATION NOTE", "HEAT BALANCE", "BILAN THERMIQUE FOUR"]},
        {"code": "DRAFT_CALC", "name": "Note de Calcul de Tirage (Calcul de Cheminée & Perte de Charge Fumées)", "criticality": "Critical", "aliases": ["CALCUL TIRAGE", "DRAFT CALCULATION", "CHIMNEY SIZING", "FLUE GAS CALC"]},
        {"code": "BMS_CERT", "name": "Documentation & Certificat du Système de Gestion des Brûleurs (BMS/BPCS)", "criticality": "Critical", "aliases": ["BMS CERTIFICATE", "BURNER MANAGEMENT SYSTEM", "BPCS", "BRULEURS CERTIFICATION", "FLAME SAFETY"]},
        {"code": "BURNER_CERT", "name": "Certificat de Type & Fiche de Données des Brûleurs (EU / ARH Approved)", "criticality": "Critical", "aliases": ["CERTIFICAT BRULEUR", "BURNER DATASHEET", "BURNER TYPE CERT", "BURNER APPROVAL"]},
        {"code": "REFRACTORY", "name": "Rapport d'Inspection du Revêtement Réfractaire & PV de Séchage", "criticality": "Major", "aliases": ["REFRACTAIRE", "REFRACTORY INSPECTION", "CURING REPORT", "SECHAGE REFRACTAIRE"]},
        {"code": "WELD_BOOK", "name": "Cahier de Soudage WPS/PQR des Circuits Sous Pression (Tubes, Collecteurs)", "criticality": "Critical", "aliases": ["SOUDAGE FOUR", "WELDING FURNACE", "WPS PQR FOUR", "TUBE WELDING"]},
        {"code": "NDT_REP", "name": "PV de CND (RT / UT / TOFD) des Soudures des Circuits de Chauffe", "criticality": "Critical", "aliases": ["NDT FOUR", "CND FOUR", "RADIOGRAPHIE TUBES FOUR", "TOFD FURNACE"]},
        {"code": "MAT_CERT", "name": "Certificats Matière EN 10204 3.1 des Tubes de Radiation & Convection", "criticality": "Critical", "aliases": ["CERTIFICAT MATERIAU FOUR", "TUBE MATERIAL CERT", "HIGH TEMP ALLOY CERT"]},
        {"code": "STACK_CERT", "name": "Rapport d'Inspection & Calcul de Stabilité Structurale de la Cheminée", "criticality": "Major", "aliases": ["RAPPORT CHEMINEE", "STACK INSPECTION", "CHIMNEY STABILITY", "CHEMINEE CALCUL"]},
        {"code": "EMISSION_REP", "name": "Rapport de Mesure des Émissions Atmosphériques (NOx / CO / SO2 / Opacité)", "criticality": "Major", "aliases": ["RAPPORT EMISSION", "EMISSION MEASUREMENT", "NOX CO MEASUREMENT", "ATMOSPHERIC EMISSION"]},
        {"code": "FAT", "name": "PV de Réception en Usine (FAT) & Essais de Performance Thermique", "criticality": "Critical", "aliases": ["FAT FOUR", "FURNACE FAT", "THERMAL PERFORMANCE TEST", "RECEPTION FOUR"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage ج م (Décret 17-62)", "criticality": "Critical", "aliases": ["DECLARATION CONFORMITE FOUR", "MARQUAGE JIM FOUR"]}
    ],
    # ── FLARE ─────────────────────────────────────────────────────────────────────
    "FLARE": [
        {"code": "DS", "name": "Spécification Technique du Système Torche & Fiche de Données KO Drum", "criticality": "Critical", "aliases": ["DATA SHEET TORCHE", "FLARE SPECIFICATION", "KO DRUM DATASHEET", "FLARE SYSTEM SPEC"]},
        {"code": "DISPERSION_NOTE", "name": "Étude de Dispersion des Gaz Brûlés & Rayonnement Thermique (API 521)", "criticality": "Critical", "aliases": ["ETUDE DISPERSION", "DISPERSION STUDY", "THERMAL RADIATION FLARE", "API 521 STUDY", "RAYONNEMENT TORCHE"]},
        {"code": "SONIC_CALC", "name": "Calcul Hydraulique Sonique & Dimensionnement de l'Entête (Relief Header Sizing)", "criticality": "Critical", "aliases": ["CALCUL SONIQUE", "SONIC VELOCITY CALC", "HEADER SIZING", "RELIEF HEADER HYDRAULIC"]},
        {"code": "FLARE_TIP", "name": "Fiche de Données & Certificat du Brûleur Torche (Flare Tip) & Allumeur", "criticality": "Critical", "aliases": ["FLARE TIP DATASHEET", "BRULEUR TORCHE", "IGNITION SYSTEM", "PILOT BURNER CERT"]},
        {"code": "KO_DRUM_CALC", "name": "Note de Calcul du Ballon Séparateur de Liquides (Knock-Out Drum)", "criticality": "Critical", "aliases": ["CALCUL KO DRUM", "KNOCKOUT DRUM SIZING", "LIQUID KNOCKOUT CALC", "KO DRUM DESIGN NOTE"]},
        {"code": "SEAL_POT", "name": "Fiche de Données du Pot de Joint Hydraulique (Liquid Seal Pot)", "criticality": "Major", "aliases": ["SEAL POT DATASHEET", "LIQUID SEAL", "POT DE JOINT", "WATER SEAL DRUM"]},
        {"code": "BLOCK_VALVE", "name": "PV d'Essais & Certificat de la Vanne de Blocage Torche (Manual / ESD Actuated)", "criticality": "Critical", "aliases": ["VANNE BLOCAGE TORCHE", "FLARE BLOCK VALVE", "ESD VALVE FLARE", "VALVE CERT FLARE"]},
        {"code": "WELD_BOOK", "name": "Qualification de Soudage WPS/PQR de la Structure & des Circuits Sous Pression", "criticality": "Critical", "aliases": ["SOUDAGE TORCHE", "WELDING FLARE", "WPS PQR FLARE", "FLARE STRUCTURE WELD"]},
        {"code": "NDT_REP", "name": "PV de CND des Soudures (KO Drum, Tête de Torche, Entête)", "criticality": "Critical", "aliases": ["NDT FLARE", "CND TORCHE", "RADIOGRAPHIE TORCHE"]},
        {"code": "MAT_CERT", "name": "Certificats Matière des Composants Sous Pression (KO Drum, Piping)", "criticality": "Critical", "aliases": ["CERTIFICAT MATIERE TORCHE", "FLARE MATERIAL CERT"]},
        {"code": "HYDRO_PV", "name": "PV d'Épreuve Hydrostatique du KO Drum & du Système de Tuyauterie (150% PMA)", "criticality": "Critical", "aliases": ["HYDROTEST TORCHE", "PV EPREUVE FLARE", "PRESSURE TEST FLARE"]},
        {"code": "INSP_REP", "name": "Rapport de l'Organisme Tiers Habilité ARH & Visa de Libération du Système Torche", "criticality": "Critical", "aliases": ["TIERS TORCHE", "THIRD PARTY FLARE", "ORGANISME HABILITE TORCHE"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage ج م (Décret 17-62)", "criticality": "Critical", "aliases": ["DECLARATION CONFORMITE TORCHE", "MARQUAGE JIM TORCHE"]}
    ],
    # ── FITTING ───────────────────────────────────────────────────────────────────
    "FITTING": [
        {"code": "DS", "name": "Spécification Technique & Fiche de Données (Type, Classe de Pression, DN, Matière, Norme)", "criticality": "Critical",
         "aliases": ["DATA SHEET RACCORD", "FITTING DATASHEET", "SPECIFICATION RACCORD", "PIPING CLASS", "FICHE TECHNIQUE FITTING", "BARRED TEE SPECIFICATION", "TEE A BARREAU"]},
        {"code": "CALC", "name": "Note de Calcul de Résistance & Vérification de la Classe de Pression (ASME B16.9 / MSS SP-75)", "criticality": "Critical",
         "aliases": ["CALCUL RACCORD", "FITTING CALCULATION", "PRESSURE CLASS VERIFICATION", "ASME B16.9", "MSS SP-75", "VERIFICATION CLASSE PRESSION"]},
        {"code": "MAT_CERT", "name": "Certificats de Réception Matière EN 10204 3.1 / 3.2 (Analyse Chimique + Essais Mécaniques)", "criticality": "Critical",
         "aliases": ["CERTIFICAT MATIERE RACCORD", "MILL CERT FITTING", "EN 10204 FITTING", "MATERIAL CERTIFICATE FITTING"]},
        {"code": "DIM_CERT", "name": "Rapport de Contrôle Dimensionnel & Tolérances de Fabrication (Procès-Verbal de Contrôle)", "criticality": "Critical",
         "aliases": ["CONTROLE DIMENSIONNEL", "DIMENSIONAL INSPECTION REPORT", "DIM CHECK", "PV DIMENSIONNEL", "INSPECTION DIMENSIONNELLE"]},
        {"code": "NDT_REP", "name": "Rapports de Contrôles Non Destructifs (UT/MT/PT/RT selon DN et Classe de Pression)", "criticality": "Critical",
         "aliases": ["NDT FITTING", "CND RACCORD", "UT FITTING", "MT FITTING", "PT FITTING"]},
        {"code": "HYDRO_PV", "name": "Procès-Verbal d'Épreuve Hydrostatique Usine (150% PMA selon ASME B16.9 / MSS SP-75)", "criticality": "Critical",
         "aliases": ["HYDROTEST FITTING", "PV EPREUVE RACCORD", "SHELL TEST FITTING", "PRESSURE TEST FITTING"]},
        {"code": "WELD_CERT", "name": "Qualification de Soudage WPS/PQR Applicables si Fitting Soudé en Usine", "criticality": "Major",
         "aliases": ["WPS FITTING", "PQR FITTING", "WELDING QUALIFICATION FITTING", "SOUDAGE RACCORD"]},
        {"code": "INSP_REP", "name": "Certificat de Réception & Visa de l'Organisme Tiers Habilité ARH", "criticality": "Critical",
         "aliases": ["RAPPORT TIERS RACCORD", "THIRD PARTY FITTING", "ORGANISME HABILITE FITTING", "RELEASE NOTE FITTING"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage Officiel ج م (Décret 17-62)", "criticality": "Critical",
         "aliases": ["DECLARATION CONFORMITE RACCORD", "MARQUAGE JIM FITTING"]}
    ],
    # ── VALVE ─────────────────────────────────────────────────────────────────────
    "VALVE": [
        {"code": "DS", "name": "Fiche de Données Vanne/Clapet (Type, DN, Classe, Matière Corps/Obturateur/Garniture, Actionneur)", "criticality": "Critical",
         "aliases": ["DATA SHEET VANNE", "VALVE DATASHEET", "DATASHEET ROBINETTERIE", "VALVE SPECIFICATION", "CLAPET DATASHEET"]},
        {"code": "CALC", "name": "Note de Calcul de Dimensionnement & Facteur Cv/Kv (Vannes de Régulation) ou Calcul de Résistance (Vannes HP)", "criticality": "Critical",
         "aliases": ["CALCUL VANNE", "VALVE SIZING", "CV CALCULATION", "KV CALCULATION", "VALVE CALCULATION NOTE"]},
        {"code": "MAT_CERT", "name": "Certificats Matière EN 10204 3.1 Corps, Chapeau, Obturateur (Forged/Cast)", "criticality": "Critical",
         "aliases": ["CERTIFICAT MATIERE VANNE", "VALVE MATERIAL CERT", "BODY MATERIAL CERT", "FORGING CERT VANNE"]},
        {"code": "SHELL_TEST", "name": "Procès-Verbal d'Épreuve de Corps (Shell Test) à 150% PMA selon API 598 / EN 12266", "criticality": "Critical",
         "aliases": ["SHELL TEST VALVE", "CORPS TEST VANNE", "API 598 TEST", "EN 12266 TEST", "PV EPREUVE CORPS"]},
        {"code": "SEAT_TEST", "name": "Procès-Verbal d'Essai d'Étanchéité Siège (Seat Leakage Test) selon API 598 / EN 12266", "criticality": "Critical",
         "aliases": ["SEAT TEST VALVE", "LEAKAGE TEST VANNE", "ETANCHEITE SIEGE", "PV ETANCHEITE VANNE"]},
        {"code": "TORQUE_TEST", "name": "Procès-Verbal d'Essai de Couple de Manœuvre & Temps d'Actionnement (pour Vannes à Actionneur)", "criticality": "Conditional",
         "aliases": ["TORQUE TEST VALVE", "ESSAI COUPLE VANNE", "ACTUATOR TEST", "PV ACTIONNEUR", "TEMPS OUVERTURE FERMETURE"]},
        {"code": "ATEX_CERT", "name": "Certificat ATEX / IECEx de l'Actionneur & Accessoires Électriques (Uniquement si Vanne Motorisée)", "criticality": "Conditional",
         "aliases": ["ATEX ACTIONNEUR", "ATEX VANNE", "IECEX ACTUATOR", "EXPLOSION PROOF VALVE"]},
        {"code": "FAT", "name": "Procès-Verbal de Réception en Usine (FAT) — Vannes Instrumentées & ESD", "criticality": "Conditional",
         "aliases": ["FAT VANNE", "FAT VALVE", "FACTORY TEST VALVE", "RECEPTION USINE VANNE"]},
        {"code": "INSP_REP", "name": "Certificat de Réception & Visa de l'Organisme Tiers Habilité ARH", "criticality": "Critical",
         "aliases": ["RAPPORT TIERS VANNE", "THIRD PARTY VALVE", "ORGANISME HABILITE VALVE", "RELEASE NOTE VALVE"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage Officiel ج م (Décret 17-62)", "criticality": "Critical",
         "aliases": ["DECLARATION CONFORMITE VANNE", "MARQUAGE JIM VALVE"]}
    ],
    # ── PIPING_SPOOL ──────────────────────────────────────────────────────────────
    "PIPING_SPOOL": [
        {"code": "ISO_DWG", "name": "Isométriques de Tuyauterie avec Nomenclature (Bill of Material — BOM) et Repères de Soudure", "criticality": "Critical",
         "aliases": ["ISOMETRIQUE TUYAUTERIE", "ISOMETRIC DRAWING", "ISO SPOOL", "PIPE SPOOL ISOMETRIC", "BOM TUYAUTERIE"]},
        {"code": "PIPING_CLASS", "name": "Spécification de Classe de Tuyauterie (Piping Class / Piping Spec) applicable", "criticality": "Critical",
         "aliases": ["PIPING SPECIFICATION", "CLASSE DE TUYAUTERIE", "PIPE CLASS", "PIPING SPEC", "SPECIFICATION TUYAUTERIE"]},
        {"code": "STRESS_NOTE", "name": "Note d'Analyse de Flexibilité & Contraintes de Tuyauterie (CAESAR II / AUTOPIPE ou équivalent)", "criticality": "Critical",
         "aliases": ["STRESS ANALYSIS", "ANALYSE FLEXIBILITE", "FLEXIBILITY ANALYSIS", "CAESAR II", "PIPE STRESS REPORT", "NOTE FLEXIBILITE"]},
        {"code": "WELD_BOOK", "name": "Cahier de Soudage WPS/PQR & Cartographie Complète des Soudures du Spool", "criticality": "Critical",
         "aliases": ["CAHIER SOUDAGE SPOOL", "WPS PQR TUYAUTERIE", "WELD MAP SPOOL", "SOUDAGE TUYAUTERIE"]},
        {"code": "MAT_CERT", "name": "Certificats Matière EN 10204 3.1 des Tubes, Raccords, Brides & Composants du Spool", "criticality": "Critical",
         "aliases": ["CERTIFICAT MATIERE SPOOL", "MATERIAL CERT PIPING", "EN 10204 TUYAUTERIE"]},
        {"code": "NDT_REP", "name": "PV de CND des Soudures de Tuyauterie (RT / UT / MT / PT selon Classe)", "criticality": "Critical",
         "aliases": ["NDT SPOOL", "CND TUYAUTERIE", "RADIOGRAPHIE SOUDURES SPOOL", "RT UT PIPING"]},
        {"code": "HYDRO_PV", "name": "PV d'Épreuve Hydrostatique / Pneumatique du Spool (selon ASME B31.3 / EN 13480)", "criticality": "Critical",
         "aliases": ["HYDROTEST SPOOL", "PRESSURE TEST PIPING", "PV EPREUVE SPOOL", "PNEUMATIC TEST PIPING"]},
        {"code": "INSP_REP", "name": "Certificat de Réception & Visa de l'Organisme Tiers Habilité ARH", "criticality": "Critical",
         "aliases": ["RAPPORT TIERS SPOOL", "THIRD PARTY PIPING", "ORGANISME HABILITE SPOOL"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage Officiel ج م (Décret 17-62)", "criticality": "Critical",
         "aliases": ["DECLARATION CONFORMITE SPOOL", "MARQUAGE JIM TUYAUTERIE"]}
    ],
    # ── SAFETY_VALVE ──────────────────────────────────────────────────────────────
    "SAFETY_VALVE": [
        {"code": "DS", "name": "Fiche de Données PSV/PRV/Disque de Rupture (Pression de Tarage, Débit, Fluide, Température)", "criticality": "Critical",
         "aliases": ["DATA SHEET PSV", "DATA SHEET PRV", "SOUPAPE DATASHEET", "SAFETY VALVE DATASHEET", "RUPTURE DISK DATASHEET", "PSV SPECIFICATION"]},
        {"code": "SIZING_NOTE", "name": "Note de Dimensionnement de la Soupape (Calcul de Débit d'Évacuation, API 520/521)", "criticality": "Critical",
         "aliases": ["CALCUL SOUPAPE", "SIZING NOTE PSV", "API 520", "API 521", "RELIEF LOAD CALCULATION", "DEBIMETRIE SOUPAPE", "CAPACITE SOUPAPE"]},
        {"code": "TARAGE_CERT", "name": "Certificat de Tarage & Essai de Pop (Pression de levée confirmée en banc d'essai)", "criticality": "Critical",
         "aliases": ["CERTIFICAT DE TARAGE", "TARAGE PSV", "SET PRESSURE TEST", "POP TEST", "BENCH TEST CERTIFICATE", "PV TARAGE"]},
        {"code": "MAT_CERT", "name": "Certificats Matière EN 10204 3.1 du Corps, Siège & Obturateur", "criticality": "Critical",
         "aliases": ["CERTIFICAT MATIERE PSV", "MATERIAL CERT SOUPAPE", "BODY MATERIAL SAFETY VALVE"]},
        {"code": "NDT_REP", "name": "Procès-Verbal de CND du Corps (si soudé) selon Classe de Pression", "criticality": "Major",
         "aliases": ["NDT PSV", "CND SOUPAPE", "UT SOUPAPE", "MT SOUPAPE"]},
        {"code": "INSP_REP", "name": "Certificat de Réception & Visa de l'Organisme Tiers Habilité ARH", "criticality": "Critical",
         "aliases": ["RAPPORT TIERS PSV", "THIRD PARTY SAFETY VALVE", "ORGANISME HABILITE PSV"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage Officiel ج م (Décret 17-62)", "criticality": "Critical",
         "aliases": ["DECLARATION CONFORMITE PSV", "MARQUAGE JIM SOUPAPE"]}
    ],
    # ── FIRE_EXTINGUISHER ─────────────────────────────────────────────────────────
    "FIRE_EXTINGUISHER": [
        {"code": "REQ_LETTER", "name": "Lettre Officielle de Demande d'Avis sur la Conformité du Dossier Préliminaire", "criticality": "Major",
         "aliases": ["LETTRE DE DEMANDE", "LETTRE D'AVIS", "DOCUMENT NO 1", "DEMANDE D'AVIS", "LETTRE ARH", "LETTRE OFFICIELLE", "LETTRE D'APPROBATION"]},
        {"code": "LEGAL_VISA", "name": "Légalisation des Signatures du Fabricant (Chambre de Commerce / Consulat)", "criticality": "Major",
         "aliases": ["LEGALISATION DES SIGNATURES", "DOCUMENT NO 2", "SIGNATURES DU FABRICANT", "CHAMBRE DE COMMERCE", "VISA CONSULAIRE", "LEGALISATION"]},
        {"code": "COC_INSPECTION", "name": "Certificat de Conformité et Visite Interne/Externe Usine", "criticality": "Major",
         "aliases": ["CERTIFICAT DE CONFORMITE ET DE VISITE", "DOCUMENT NO 3", "VISITE INTERNE ET EXTERNE", "CERTIFICAT DE CONFORMITE", "CERTIFICAT DE VISITE"]},
        {"code": "ORIGIN_COC", "name": "Certificat Attestant la Construction Conforme pour Utilisation dans le Pays d'Origine", "criticality": "Major",
         "aliases": ["PAYS D'ORIGINE", "DOCUMENT NO 4", "UTILISATION DANS SON PAYS D'ORIGINE", "CONSTRUCTION CONFORME", "DANS SON PAYS D'ORIGINE"]},
        {"code": "ANNEXE_E", "name": "État Descriptif du Réservoir / Bouteille Sous Pression (Annexe E / EN 3-8 / Décret 21-261)", "criticality": "Critical",
         "aliases": ["ETAT DESCRIPTIF", "DOCUMENT NO 5", "ANNEXE E", "DESCRIPTIVE STATEMENT", "ETAT DESCRIPTIF POUR APPAREILS A PRESSION", "ETAT DESCRIPTIF DU RESERVOIR"]},
        {"code": "CALC", "name": "Notes de Calcul de Dimensionnement et Résistance sous Pression (EN 3-8 / CODAP / EN 13445)", "criticality": "Critical",
         "aliases": ["NOTES DE CALCUL", "NOTE DE CALCUL", "DOCUMENT NO 6", "CALCULATION NOTE", "BASE DU CALCUL", "NOTE CALCUL"]},
        {"code": "PLANS", "name": "Index des Plans et Plans de Fabrication du Corps d'Extincteur", "criticality": "Major",
         "aliases": ["INDEX DES PLANS", "DOCUMENT NO 7", "PLANS DE FABRICATION", "PLAN DE FABRICATION", "PLANS JOINTS", "DRAWING", "PLAN"]},
        {"code": "WPS_PQR", "name": "Spécifications des Procédures de Soudage (DMOS / QMOS / WPS / PQR)", "criticality": "Critical",
         "aliases": ["SPECIFICATIONS DES PROCEDURES DE SOUDAGE", "PROCEDURES DE SOUDAGE", "DOCUMENT NO 8", "DMOS", "QMOS", "WPS", "PQR", "PROCES-VERBAL DE QUALIFICATION DE MODE OPERATOIRE DE SOUDAGE", "MODE OPERATOIRE DE SOUDAGE"]},
        {"code": "PWHT_SPEC", "name": "Spécification du Traitement Thermique (si applicable / dérogation)", "criticality": "Minor",
         "aliases": ["TRAITEMENT THERMIQUE", "DOCUMENT NO 9", "SPECIFICATION DU TRAITEMENT THERMIQUE", "SANS TRAITEMENT THERMIQUE", "PWHT"]},
        {"code": "ITP", "name": "Plan de Contrôle Qualité / ITP Applicable à l'Équipement", "criticality": "Major",
         "aliases": ["PLAN DE CONTROLE QUALITE", "DOCUMENT NO 10", "PLAN DE CONTROLE", "ITP", "QCP", "QUALITY CONTROL PLAN"]},
        {"code": "SCHEDULE", "name": "Planning Général de Fabrication Usine", "criticality": "Minor",
         "aliases": ["PLANNING GENERAL DE FABRICATION", "DOCUMENT NO 11", "PLANNING DE FABRICATION", "MANUFACTURING SCHEDULE", "PLANNING"]}
    ],
    # ── METERING ──────────────────────────────────────────────────────────────────
    "METERING": [
        {"code": "DS", "name": "Fiche de Données du Système de Comptage (Type, Fluide, Débit Min/Max, Précision, Pression)", "criticality": "Critical",
         "aliases": ["DATA SHEET COMPTAGE", "METERING SYSTEM DATASHEET", "FLOW METER DATASHEET", "SPECIFICATION COMPTAGE"]},
        {"code": "METER_SIZING", "name": "Note de Dimensionnement & Calcul d'Incertitude de Mesure du Compteur (ISO 17089 / AGA)", "criticality": "Critical",
         "aliases": ["CALCUL COMPTEUR", "METER SIZING", "UNCERTAINTY CALCULATION", "CALCUL INCERTITUDE", "ISO 17089", "AGA 9", "AGA 3"]},
        {"code": "CALIBRATION", "name": "Rapport de Calibration Officiel & Certificat d'Étalonnage (Traçabilité Métrologique ALGERAC/ONML)", "criticality": "Critical",
         "aliases": ["CERTIFICAT ETALONNAGE", "CALIBRATION CERTIFICATE", "PV ETALONNAGE COMPTEUR", "FLOW METER CALIBRATION", "METROLOGIE COMPTEUR"]},
        {"code": "FLOW_COMPUTER", "name": "Fiche Technique & Certification du Calculateur de Débit (Flow Computer)", "criticality": "Critical",
         "aliases": ["FLOW COMPUTER DATASHEET", "CALCULATEUR DE DEBIT", "FLOW COMPUTER CERTIFICATE", "CALCULATEUR COMPTAGE"]},
        {"code": "ATEX_CERT", "name": "Certificat ATEX / IECEx de Tous les Composants Électriques en Zone Explosive", "criticality": "Critical",
         "aliases": ["ATEX COMPTEUR", "IECEX METERING", "ATEX FLOW METER", "ZONE ATEX METERING"]},
        {"code": "FAT", "name": "Procès-Verbal de Réception en Usine (FAT) du Skid de Comptage Complet", "criticality": "Critical",
         "aliases": ["FAT METERING", "FAT COMPTAGE", "FACTORY TEST METERING SKID", "PV RECEPTION METERING"]},
        {"code": "PROVING", "name": "Rapport de Provage (Prover Run) & Certificat de Facteur de Correction du Compteur", "criticality": "Critical",
         "aliases": ["PROVER RUN", "PROVING REPORT", "METER FACTOR", "FACTEUR COMPTEUR", "METER PROVING CERTIFICATE"]},
        {"code": "INSP_REP", "name": "Visa de Libération & Rapport de l'Organisme Tiers Habilité ARH", "criticality": "Critical",
         "aliases": ["RAPPORT TIERS METERING", "THIRD PARTY METERING", "ORGANISME HABILITE COMPTAGE"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage Officiel ج م (Décret 17-62)", "criticality": "Critical",
         "aliases": ["DECLARATION CONFORMITE METERING", "MARQUAGE JIM COMPTAGE"]}
    ],
    # ── FILTER_SEPARATOR ─────────────────────────────────────────────────────────
    "FILTER_SEPARATOR": [
        {"code": "DS", "name": "Fiche de Données du Filtre/Épurateur (Type, Fluide, Pression, Température, Débit, Micronage)", "criticality": "Critical",
         "aliases": ["DATA SHEET FILTRE", "FILTER DATASHEET", "EPURATEUR DATASHEET", "FILTER SPECIFICATION", "STRAINER DATASHEET"]},
        {"code": "CALC", "name": "Note de Calcul de la Perte de Charge & Dimensionnement du Filtre (Propre & Colmaté)", "criticality": "Critical",
         "aliases": ["CALCUL FILTRE", "FILTER SIZING", "PRESSURE DROP CALCULATION", "PERTE DE CHARGE FILTRE"]},
        {"code": "GA_DWG", "name": "Plan d'Ensemble GA du Filtre avec Connexions, Piquages & Purges", "criticality": "Major",
         "aliases": ["PLAN FILTRE", "FILTER GA DRAWING", "GENERAL ARRANGEMENT FILTRE"]},
        {"code": "MAT_CERT", "name": "Certificats Matière EN 10204 3.1 du Corps, Panier/Cartouche Filtrante & Éléments Sous Pression", "criticality": "Critical",
         "aliases": ["CERTIFICAT MATIERE FILTRE", "MATERIAL CERT FILTER", "BASKET MATERIAL CERT", "FILTER ELEMENT CERT"]},
        {"code": "NDT_REP", "name": "PV de CND des Soudures du Corps Sous Pression (RT/UT/MT/PT)", "criticality": "Critical",
         "aliases": ["NDT FILTRE", "CND FILTRE", "RT UT FILTER"]},
        {"code": "HYDRO_PV", "name": "PV d'Épreuve Hydrostatique (150% PMA selon ASME VIII / EN 13445)", "criticality": "Critical",
         "aliases": ["HYDROTEST FILTRE", "PV EPREUVE FILTRE", "PRESSURE TEST FILTER"]},
        {"code": "INSP_REP", "name": "Certificat de Réception & Visa de l'Organisme Tiers Habilité ARH", "criticality": "Critical",
         "aliases": ["RAPPORT TIERS FILTRE", "THIRD PARTY FILTER", "ORGANISME HABILITE FILTRE"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage Officiel ج م (Décret 17-62)", "criticality": "Critical",
         "aliases": ["DECLARATION CONFORMITE FILTRE", "MARQUAGE JIM FILTRE"]}
    ],
    # ── HEAT_TRACING ─────────────────────────────────────────────────────────────
    "HEAT_TRACING": [
        {"code": "DS", "name": "Spécification Technique du Système de Traçage (Type EHT/Vapeur, Puissance, Longueur, Fluide)", "criticality": "Critical",
         "aliases": ["SPECIFICATION TRACAGE", "HEAT TRACING SPEC", "EHT DATASHEET", "STEAM TRACING SPEC"]},
        {"code": "DESIGN_NOTE", "name": "Note de Conception du Traçage Thermique (Calcul de Puissance, Pertes Thermiques, Maintien en T°)", "criticality": "Critical",
         "aliases": ["CALCUL TRACAGE", "HEAT TRACING DESIGN", "HEAT LOSS CALCULATION", "NOTE CONCEPTION EHT"]},
        {"code": "ATEX_CERT", "name": "Certificat ATEX / IECEx du Câble Chauffant & Thermostat de Régulation en Zone Explosive", "criticality": "Critical",
         "aliases": ["ATEX EHT", "ATEX CABLE CHAUFFANT", "IECEX HEAT TRACING", "ZONE ATEX EHT"]},
        {"code": "CALORIFUGE_SPEC", "name": "Spécification de Calorifugeage (Type Isolant, Épaisseur, Finition, Norme EN ISO 12241)", "criticality": "Major",
         "aliases": ["CALORIFUGE SPECIFICATION", "INSULATION SPEC", "ISOLATION THERMIQUE SPEC", "LAGGING SPECIFICATION"]},
        {"code": "INSTALL_CERT", "name": "Rapport de Contrôle d'Installation & Tests de Continuité du Traçage (Mégohmètre)", "criticality": "Critical",
         "aliases": ["TEST CONTINUITE EHT", "INSULATION RESISTANCE TEST", "MEGOHMMETRE", "HEAT TRACING TEST REPORT"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité du Câble Chauffant & Thermostat (Décret 17-62 / ATEX)", "criticality": "Critical",
         "aliases": ["DECLARATION CONFORMITE EHT", "MARQUAGE JIM TRACAGE"]}
    ],
    # ── STRUCTURAL_STEEL ──────────────────────────────────────────────────────────
    "STRUCTURAL_STEEL": [
        {"code": "STRUCT_CALC", "name": "Note de Calcul de Structure (Charges Mortes, Charges d'Exploitation, Charges Sismiques & Vent — EC3 / AISC)", "criticality": "Critical",
         "aliases": ["CALCUL STRUCTURE", "STRUCTURAL CALCULATION", "EC3 CALCULATION", "AISC DESIGN", "SEISMIC ANALYSIS", "NOTE STRUCTURE"]},
        {"code": "STRUCT_DWG", "name": "Plans de Structure Détaillés (Assemblages, Connexions Boulonnées/Soudées, Cotation Complète)", "criticality": "Critical",
         "aliases": ["PLANS STRUCTURE", "STRUCTURAL DRAWINGS", "ASSEMBLY DRAWINGS", "CONNECTION DETAILS", "PLAN CHARPENTE"]},
        {"code": "MAT_CERT", "name": "Certificats Matière EN 10204 3.1 des Profilés, Tôles & Éléments Structuraux", "criticality": "Critical",
         "aliases": ["CERTIFICAT MATIERE STRUCTURE", "STEEL MATERIAL CERT", "PROFILE MATERIAL CERT", "MILL CERT STRUCTURE"]},
        {"code": "WELD_BOOK", "name": "Qualifications de Soudage WPS/PQR & Rapports de CND des Soudures Portantes", "criticality": "Critical",
         "aliases": ["SOUDAGE STRUCTURE", "WPS PQR STRUCTURE", "STRUCTURAL WELD QUALIFICATION", "CND SOUDURES STRUCTURE"]},
        {"code": "COATING_REP", "name": "Rapport d'Inspection de la Protection Anticorrosion (Sablage, Primaire, Finition — ISO 8501)", "criticality": "Major",
         "aliases": ["PROTECTION ANTICORROSION", "COATING INSPECTION STRUCTURE", "ISO 8501", "BLASTING REPORT", "PAINTING STRUCTURE"]},
        {"code": "LOAD_TEST", "name": "Rapport d'Essai de Charge Statique & Dynamique (si applicable — racks, plateformes)", "criticality": "Major",
         "aliases": ["ESSAI DE CHARGE STRUCTURE", "LOAD TEST STRUCTURE", "STATIC LOAD TEST", "DYNAMIC TEST"]},
        {"code": "INSP_REP", "name": "Rapport Final de Réception de la Structure (Organisme Tiers ou Ingénieur Certifié)", "criticality": "Critical",
         "aliases": ["RAPPORT RECEPTION STRUCTURE", "STRUCTURAL INSPECTION REPORT", "FINAL INSPECTION STRUCTURE"]}
    ],
    # ── CIVIL_FOUNDATION ─────────────────────────────────────────────────────────
    "CIVIL_FOUNDATION": [
        {"code": "GEOTECH_REP", "name": "Rapport Géotechnique de Reconnaissance du Sol (Essais SPT, Pressiomètre, Carottes)", "criticality": "Critical",
         "aliases": ["RAPPORT GEOTECHNIQUE", "GEOTECHNICAL REPORT", "SOIL INVESTIGATION", "ETUDE SOL", "RAPPORT DE SOL", "SPT REPORT"]},
        {"code": "CIVIL_CALC", "name": "Note de Calcul de Fondation (Capacité Portante, Tassements, Analyse Sismique — RPA99)", "criticality": "Critical",
         "aliases": ["CALCUL FONDATION", "FOUNDATION DESIGN", "BEARING CAPACITY CALCULATION", "RPA99", "CALCUL GENIE CIVIL", "SETTLEMENT CALCULATION"]},
        {"code": "CIVIL_DWG", "name": "Plans d'Exécution Génie Civil (Ferraillage, Coffrages, Détails Joints & Ancrages)", "criticality": "Critical",
         "aliases": ["PLANS BETON", "REINFORCEMENT DRAWINGS", "FERRAILLAGE", "SHUTTERING PLAN", "ANCHOR BOLT PLAN", "PLAN EXECUTION CIVIL"]},
        {"code": "CONCRETE_CERT", "name": "Rapports d'Essais sur le Béton Frais & Durci (Affaissement, Résistance fc28, Carotte)", "criticality": "Critical",
         "aliases": ["ESSAI BETON", "CONCRETE TEST REPORT", "CUBE TEST", "COMPRESSION TEST CONCRETE", "FC28", "AFFAISSEMENT BETON"]},
        {"code": "REBAR_CERT", "name": "Certificats Matière des Aciers de Renforcement (Armatures HA selon NF A35-080 / ENOR)", "criticality": "Critical",
         "aliases": ["CERTIFICAT ACIER BETON", "REBAR CERTIFICATE", "ARMATURE CERTIFICATE", "HA STEEL CERT", "NF A35-080"]},
        {"code": "BUND_CERT", "name": "Rapport de Contrôle d'Étanchéité des Rétentions & Cuvettes (pour bacs/sphères)", "criticality": "Major",
         "aliases": ["CONTROLE ETANCHEITE RETENTION", "BUND LEAK TEST", "CUVETTE TEST", "RETENTION INTEGRITY TEST"]},
        {"code": "INSP_REP", "name": "Rapport de Réception du Génie Civil par l'Ingénieur Vérificateur ou Bureau de Contrôle", "criticality": "Critical",
         "aliases": ["RAPPORT RECEPTION CIVIL", "BUREAU DE CONTROLE", "VERIFICATION GENIE CIVIL", "CIVIL INSPECTION REPORT"]}
    ],
    # ── GAS_FIRE_DETECTION ────────────────────────────────────────────────────────
    "GAS_FIRE_DETECTION": [
        {"code": "DS", "name": "Fiche de Données des Détecteurs (Type Gaz/Flamme/Chaleur, Principe, Zone ATEX, Plage de Détection)", "criticality": "Critical",
         "aliases": ["DATA SHEET DETECTEUR", "GAS DETECTOR DATASHEET", "FIRE DETECTOR DATASHEET", "FGS SPECIFICATION", "DETECTOR SPEC"]},
        {"code": "FGS_DESIGN", "name": "Note de Conception du Système FGS/FAS (Logique de Détection, Vote 1oo2/2oo3, Cause & Effect)", "criticality": "Critical",
         "aliases": ["CAUSE AND EFFECT", "DETECTION LOGIC", "FGS DESIGN NOTE", "FIRE AND GAS PHILOSOPHY", "VOTING LOGIC"]},
        {"code": "ATEX_CERT", "name": "Certificats ATEX / IECEx de Tous les Détecteurs & Composants Électroniques en Zone Explosive", "criticality": "Critical",
         "aliases": ["ATEX DETECTEUR", "IECEX DETECTOR", "ATEX FGS", "ZONE ATEX DETECTION", "EXPLOSION PROOF DETECTOR"]},
        {"code": "SIL_CERT", "name": "Certificat SIL & Rapport de Calcul PFD (Probability of Failure on Demand) — IEC 61508", "criticality": "Critical",
         "aliases": ["SIL CERTIFICATE FGS", "PFD CALCULATION", "IEC 61508 FGS", "FUNCTIONAL SAFETY FGS"]},
        {"code": "FAT", "name": "Procès-Verbal de Réception en Usine (FAT) du Système de Détection Complet", "criticality": "Critical",
         "aliases": ["FAT FGS", "FACTORY TEST DETECTION", "PV RECEPTION FGS", "FAT FIRE AND GAS"]},
        {"code": "SAT", "name": "PV de Tests sur Site (SAT) & Rapport de Mise en Service du Système FGS/FAS", "criticality": "Critical",
         "aliases": ["SAT FGS", "SITE ACCEPTANCE TEST DETECTION", "COMMISSIONING FGS", "PV MISE EN SERVICE DETECTION"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage ATEX / ج م des Équipements de Détection (Décret 17-62)", "criticality": "Critical",
         "aliases": ["DECLARATION CONFORMITE FGS", "MARQUAGE ATEX DETECTION", "MARQUAGE JIM FGS"]}
    ],
    # ── TELECOM_SCADA ─────────────────────────────────────────────────────────────
    "TELECOM_SCADA": [
        {"code": "DS", "name": "Fiche de Données & Architecture du Système SCADA/DCS (Redondance, Protocoles, Bande Passante)", "criticality": "Critical",
         "aliases": ["SCADA ARCHITECTURE", "DCS DATASHEET", "SYSTEM ARCHITECTURE", "ARCHITECTURE SCADA", "TELECOM SPEC"]},
        {"code": "TELECOM_DESIGN", "name": "Note de Conception Télécom (Bilan de Liaison Radio, Calcul Fibre Optique, Plan d'Adressage)", "criticality": "Critical",
         "aliases": ["LINK BUDGET", "BILAN DE LIAISON", "OPTICAL LINK CALCULATION", "RADIO DESIGN", "NOTE CONCEPTION TELECOM"]},
        {"code": "CYBER_SEC", "name": "Rapport d'Évaluation de la Cybersécurité des Systèmes de Contrôle (IEC 62443 / NIST)", "criticality": "Critical",
         "aliases": ["CYBERSECURITY ASSESSMENT", "IEC 62443", "NIST CYBERSECURITY", "OT SECURITY REPORT", "SECURITE SYSTEME CONTROLE"]},
        {"code": "FAT", "name": "Procès-Verbal de Réception en Usine (FAT) du Système SCADA/DCS/RTU Complet", "criticality": "Critical",
         "aliases": ["FAT SCADA", "FAT DCS", "FAT RTU", "FACTORY ACCEPTANCE TEST SCADA", "PV RECEPTION SCADA"]},
        {"code": "SAT", "name": "PV de Tests sur Site (SAT) & Mise en Service du Système de Contrôle-Commande", "criticality": "Critical",
         "aliases": ["SAT SCADA", "SITE TEST SCADA", "COMMISSIONING DCS", "PV MISE EN SERVICE SCADA"]},
        {"code": "INTEGRATION_TEST", "name": "Rapport de Test d'Intégration Système (SIT — Interfaces DCS/ESD/FGS/METERING)", "criticality": "Critical",
         "aliases": ["SIT SCADA", "SYSTEM INTEGRATION TEST", "INTERFACE TEST", "DCS ESD INTEGRATION"]},
        {"code": "CE_DECL", "name": "Déclaration de Conformité & Marquage ج م des Équipements Électroniques (Décret 17-62)", "criticality": "Critical",
         "aliases": ["DECLARATION CONFORMITE SCADA", "MARQUAGE JIM TELECOM"]}
    ],
    # ── CRANE_LIFTING ──────────────────────────────────────────────────────────────
    "CRANE_LIFTING": [
        {"code": "DS", "name": "Fiche de Données Engin de Levage (Type, Capacité CMU, Portée, Hauteur de Levage, Classe)", "criticality": "Critical",
         "aliases": ["DATA SHEET GRUE", "CRANE DATASHEET", "LIFTING EQUIPMENT SPEC", "CMU", "SAFE WORKING LOAD", "SWL"]},
        {"code": "STRUCT_CALC", "name": "Note de Calcul Structurale de la Grue/Palan (selon FEM 1.001 / EN 13001 / ASME B30)", "criticality": "Critical",
         "aliases": ["CALCUL GRUE", "CRANE CALCULATION", "FEM 1.001", "EN 13001", "ASME B30", "STRUCTURAL DESIGN CRANE"]},
        {"code": "LOAD_TEST", "name": "Procès-Verbal d'Essai de Charge Dynamique & Statique (125% CMU Statique, 110% CMU Dynamique)", "criticality": "Critical",
         "aliases": ["ESSAI DE CHARGE GRUE", "LOAD TEST CERTIFICATE", "DYNAMIC LOAD TEST", "STATIC LOAD TEST CRANE", "PV ESSAI CHARGE"]},
        {"code": "PERIODIC_INSP", "name": "Rapport de Vérification Générale Périodique (VGP) par Organisme Agréé", "criticality": "Critical",
         "aliases": ["VERIFICATION PERIODIQUE", "VGP RAPPORT", "PERIODIC INSPECTION CRANE", "ANNUAL INSPECTION REPORT", "RAPPORT VERIFICATION ANNUELLE"]},
        {"code": "MAT_CERT", "name": "Certificats Matière des Crochets, Élingues, Manilles, Câbles & Chaînes de Levage", "criticality": "Critical",
         "aliases": ["CERTIFICAT MATERIAU LEVAGE", "SLING CERTIFICATE", "HOOK CERTIFICATE", "SHACKLE CERTIFICATE", "CABLE LEVAGE CERT"]},
        {"code": "OPERATOR_CERT", "name": "Certificat de Formation & Habilitation des Opérateurs de Levage (CACES ou équivalent)", "criticality": "Critical",
         "aliases": ["HABILITATION OPERATEUR GRUE", "CACES GRUE", "CRANE OPERATOR CERTIFICATE", "LIFTING OPERATOR TRAINING"]},
        {"code": "LIFT_PLAN", "name": "Plan de Levage Critique (pour opérations > 75% CMU ou levages avec 2 grues)", "criticality": "Major",
         "aliases": ["CRITICAL LIFT PLAN", "PLAN LEVAGE CRITIQUE", "TANDEM LIFT PLAN", "RIGGING PLAN"]},
        {"code": "INSP_REP", "name": "Rapport Final de Réception & Visa de l'Organisme Tiers Habilité", "criticality": "Critical",
         "aliases": ["RAPPORT TIERS GRUE", "THIRD PARTY LIFTING", "ORGANISME HABILITE LEVAGE", "RELEASE NOTE CRANE"]}
    ]
}

# Default fallback checklist for unknown equipment — 6 items génériques
DEFAULT_CHECKLIST = [
    {"code": "DS", "name": "Spécification Technique & Fiche de Données Équipement", "criticality": "Critical",
     "aliases": ["DATA SHEET", "DATASHEET", "FICHE TECHNIQUE", "SPECIFICATION"]},
    {"code": "GA_DWG", "name": "Plan d'Ensemble & Disposition Générale (General Arrangement)", "criticality": "Major",
     "aliases": ["GENERAL ARRANGEMENT", "PLAN D'ENSEMBLE", "LAYOUT DRAWING", "GA DRAWING"]},
    {"code": "CALC", "name": "Note de Calcul de Conception & Dimensionnement", "criticality": "Critical",
     "aliases": ["CALCULATION NOTE", "DESIGN CALCULATION", "NOTE DE CALCUL", "CALCUL DIMENSIONNEMENT"]},
    {"code": "MAT_CERT", "name": "Certificats de Réception Matière (EN 10204 3.1 ou équivalent)", "criticality": "Major",
     "aliases": ["MATERIAL CERTIFICATE", "MILL CERT", "CERTIFICAT MATIERE", "EN 10204"]},
    {"code": "TEST_PV", "name": "Procès-Verbaux d'Essais Usine & Site (FAT / SAT)", "criticality": "Critical",
     "aliases": ["FAT REPORT", "SAT REPORT", "ESSAIS USINE", "SITE TEST"]},
    {"code": "QA_ITP", "name": "Plan Qualité / Plan d'Inspection & d'Essais Approuvé (ITP / PIE)", "criticality": "Major",
     "aliases": ["ITP", "PIE", "PLAN QUALITE", "INSPECTION TEST PLAN", "QUALITY PLAN"]}
]

# ═══════════════════════════════════════════════════════════════════════════
# CHECKLIST PROCÉDURALE UNIVERSELLE — P-CTE-1 (Procédure ARH N°01/CTE/ARH/2015
# du 26 Mars 2015, Annexe A "Composition du dossier préliminaire" et Annexe G
# "Composition du Dossier final"). Ces pièces sont exigées par la PROCÉDURE
# elle-même, en plus des exigences techniques spécifiques par équipement
# (MANDATORY_DOCUMENTS_MASTER). Elles sont fusionnées dans
# generate_mandatory_checklist() pour toute demande ARH.
# ═══════════════════════════════════════════════════════════════════════════

# Types d'équipements concernés par la fabrication sous pression soudée
# (contrôles destructifs, traitement thermique, visites int/ext, qualif.
# soudeurs) — non applicable tel quel aux équipements purement électriques /
# rotatifs / instrumentation qui suivent d'autres modalités.
PRESSURE_FABRICATION_TYPES = (
    "PRESSURE_VESSEL", "TANK", "LINEPIPE", "PIPELINE", "SEPARATOR",
    "HEAT_EXCHANGER", "COLUMN", "SPHERE", "FLOWLINE", "FURNACE", "FLARE", "SKID",
    # Nouveaux types v3.0 sous pression soudée
    "FITTING", "VALVE", "PIPING_SPOOL", "SAFETY_VALVE", "FILTER_SEPARATOR"
)

# ── Annexe A : Composition du dossier PRÉLIMINAIRE (P-CTE-1, page 15) ──
PCTE1_PRELIMINARY_UNIVERSAL = [
    {"code": "LETTRE_DEMANDE_AVIS", "name": "Lettre de Demande d'Avis sur la Conformité (Annexe B P-CTE-1)",
     "criticality": "Critical", "aliases": [
         "DEMANDE D'AVIS", "DEMANDE AVIS CONFORMITE", "LETTRE DE DEMANDE", "DEMANDE D'APPROBATION",
         "LETTRE DE DEMANDE D'APPROBATION", "DEMANDE D'AVIS SUR LA CONFORMITE", "DOSSIER D'ETUDE PRELIMINAIRE",
         "DOSSIER D'ÉTUDE PRÉLIMINAIRE", "SOUMETTRE POUR APPROBATION", "LETTRE ARH", "TRANSMISSION ARH",
         "MONSIEUR LE PRESIDENT", "MONSIEUR LE DIRECTEUR", "AUTORITE DE REGULATION DES HYDROCARBURES"
     ],
     "decree_reference": "P-CTE-1 Annexe A/B"},
    {"code": "CERT_SIGNATURES_FABRICANT", "name": "Certification des Signatures du Fabricant par la Chambre de Commerce + Visa du Consulat d'Algérie (Annexe C)",
     "criticality": "Critical", "aliases": ["CERTIFICATION DES SIGNATURES", "CHAMBRE DE COMMERCE", "VISA CONSULAT"],
     "decree_reference": "P-CTE-1 Annexe C"},
    {"code": "CERT_VISITE_INT_EXT", "name": "Certificats de Conformité et de Visites Intérieures et Extérieures de l'Équipement, visés par le Consulat d'Algérie (Annexe D)",
     "criticality": "Critical", "aliases": ["CERTIFICAT DE VISITE", "VISITE INTERIEURE", "VISITE EXTERIEURE", "CERTIFICAT DE CONFORMITE ET DE VISITE"],
     "decree_reference": "P-CTE-1 Annexe D"},
    {"code": "ETAT_DESCRIPTIF", "name": "État Descriptif de l'Équipement (Annexe E)",
     "criticality": "Critical", "aliases": ["ETAT DESCRIPTIF", "DESCRIPTIVE STATEMENT"],
     "decree_reference": "P-CTE-1 Annexe E"},
    {"code": "PLANS_DETAILLES_INDEX", "name": "Plans Détaillés avec Index, en Format A3 Lisible",
     "criticality": "Critical", "aliases": ["PLANS DETAILLES", "DETAILED DRAWINGS", "PLAN AVEC INDEX", "FORMAT A3"],
     "decree_reference": "P-CTE-1 §VI.2"},
    {"code": "TRAIT_THERMIQUE_SPEC", "name": "Spécification de Traitement Thermique (si applicable)",
     "criticality": "Major", "aliases": ["SPECIFICATION TRAITEMENT THERMIQUE", "HEAT TREATMENT SPECIFICATION", "PWHT SPECIFICATION"],
     "decree_reference": "P-CTE-1 Annexe A", "conditional": True},
    {"code": "CERT_PAYS_ORIGINE", "name": "Certificat de Conformité attestant que l'Équipement est de Construction Conforme pour Utilisation dans le Pays d'Origine (Annexe F)",
     "criticality": "Critical", "aliases": ["CERTIFICAT PAYS D'ORIGINE", "CONFORME PAYS D'ORIGINE", "CONSTRUCTION CONFORME"],
     "decree_reference": "P-CTE-1 Annexe F"},
]

# ── Annexe G : Composition du Dossier FINAL (P-CTE-1, page 21) ──
PCTE1_FINAL_UNIVERSAL = [
    {"code": "DOSSIER_PRELIM_JOINT", "name": "Dossier d'Étude Préliminaire Complet (joint au dossier final)",
     "criticality": "Critical", "aliases": ["DOSSIER PRELIMINAIRE", "DOSSIER D'ETUDE PRELIMINAIRE"],
     "decree_reference": "P-CTE-1 Annexe G point 1"},
    {"code": "LETTRE_AVIS_ARH_PRELIM", "name": "Lettre relative à l'Avis sur la Conformité du Dossier Préliminaire émise par l'ARH",
     "criticality": "Critical", "aliases": ["AVIS DE CONFORMITE ARH", "LETTRE AVIS ARH", "AVIS SUR LA CONFORMITE"],
     "decree_reference": "P-CTE-1 Annexe G point 2"},
    {"code": "LETTRE_INVITATION_INSPECTEUR", "name": "Lettre ou Télécopie émise par le Maître de l'Ouvrage demandant la Présence de l'Inspecteur pour les Épreuves et Contrôles en Usine (Annexe H)",
     "criticality": "Major", "aliases": ["INVITATION INSPECTEUR", "DEMANDE PRESENCE INSPECTEUR"],
     "decree_reference": "P-CTE-1 Annexe H"},
    {"code": "REPONSE_ARH_PRESENCE", "name": "Réponse Écrite de l'ARH Confirmant (ou non) la Présence de son Représentant/Délégué",
     "criticality": "Major", "aliases": ["REPONSE ARH", "CONFIRMATION PRESENCE", "CONFIRMATION REPRESENTANT"],
     "decree_reference": "P-CTE-1 Annexe G point 4"},
    {"code": "QUALIF_SOUDEURS", "name": "Attestation de Qualification des Soudeurs et des Opérateurs de Soudage, Validée à la Date des Opérations",
     "criticality": "Critical", "aliases": ["QUALIFICATION SOUDEURS", "WELDER QUALIFICATION", "WPQ", "CERTIFICAT SOUDEUR"],
     "decree_reference": "P-CTE-1 Annexe G point 5"},
    {"code": "DESTRUCTIVE_TEST_REP", "name": "Rapports des Contrôles DESTRUCTIFS effectués lors de la Fabrication (essais de traction, pliage, résilience sur coupons de soudure)",
     "criticality": "Critical", "aliases": ["CONTROLE DESTRUCTIF", "DESTRUCTIVE TEST", "ESSAI DE TRACTION", "ESSAI DE PLIAGE", "ESSAI DE RESILIENCE", "COUPON DE SOUDURE"],
     "decree_reference": "P-CTE-1 Annexe G point 8"},
    {"code": "DIAG_TRAIT_THERMIQUE", "name": "Diagramme des Traitements Thermiques Réellement Effectués",
     "criticality": "Major", "aliases": ["DIAGRAMME TRAITEMENT THERMIQUE", "HEAT TREATMENT CHART", "PWHT CHART"],
     "decree_reference": "P-CTE-1 Annexe G point 9", "conditional": True},
    {"code": "CERT_INSP_VISITE_FINAL", "name": "Certificat d'Inspection de Visites Intérieure et Extérieure (Réception Finale)",
     "criticality": "Critical", "aliases": ["CERTIFICAT D'INSPECTION VISITE", "FINAL VISUAL INSPECTION CERTIFICATE"],
     "decree_reference": "P-CTE-1 Annexe G point 10"},
]

# Prompt LLM pour la détection sémantique d'équipement
_LLM_DETECT_PROMPT = """Tu es un expert en équipements industriels pétroliers et gaziers (Oil & Gas).
Analyse le texte suivant extrait d'un dossier technique ARH (Algérie) et identifie le TYPE D'ÉQUIPEMENT principal décrit.

TYPES POSSIBLES (réponds EXACTEMENT avec l'un de ces codes) :
- PRESSURE_VESSEL : Récipient sous pression, ballon, sécheur, accumulateur, scrubber
- SEPARATOR : Séparateur de procédé (2 ou 3 phases), test separator
- HEAT_EXCHANGER : Échangeur de chaleur, aéroréfrigérant, condenseur, refroidisseur, TEMA
- COLUMN : Colonne de distillation, stripper, absorbeur, stabilisateur, fractionateur
- TANK : Bac de stockage, réservoir atmosphérique (API 650/620), bac à toit fixe/flottant
- SPHERE : Sphère de stockage GPL/butane/propane sous pression
- PIPELINE : Travaux de pose & construction de canalisation sur chantier (gazoduc, oléoduc)
- LINEPIPE : Fourniture et fabrication de tubes/canalisations en usine (Décret 21-315 Art. 14, Baotou Steel, pipes usine)
- FLOWLINE : Conduite d'écoulement puits, collecteur de champ, flowline, wellhead line
- COMPRESSOR : Compresseur, turbocompresseur, moto-compresseur, compresseur à piston
- PUMP : Pompe centrifuge, motopompe, pompe d'injection, booster pump
- ELECTRICAL : Installation électrique, UPS, ASI, transformateur, TGBT, MCC, tableau HTA/BT, batterie, onduleur
- INSTRUMENTATION : Instrument, transmetteur, DCS, ESD, PLC, boucle de régulation, SIS
- SKID : Skid modulaire, gare de racleur, metering skid, pig launcher, package industriel
- FURNACE : Four de procédé, chaudière, générateur de vapeur, fired heater, incinerateur
- FLARE : Torche de sécurité, système flare, KO drum, entête de torche, flare tip
- FITTING : Raccord de canalisation, tee à barreau, barred tee, coude, réduction, manchon, bride, croix, weldolet, olet
- VALVE : Vanne, robinetterie, clapet anti-retour, vanne boisseau sphérique, vanne papillon, vanne gate, vanne ESD, vanne de régulation
- PIPING_SPOOL : Spool de tuyauterie, assemblage tuyauterie, isométrique, tuyauterie procédé, piping
- SAFETY_VALVE : Soupape de sûreté, PSV, PRV, disque de rupture, limiteur de débit, safety valve
- METERING : Système de comptage, mesurage fiscal, compteur de gaz, débitmétre, orifice, turbine, Coriolis
- FILTER_SEPARATOR : Filtre industriel, épurateur, strainer, panier filtrant, filtre coalescer
- HEAT_TRACING : Traçage thermique, calorifugeage, EHT, heat tracing, isolation thermique
- STRUCTURAL_STEEL : Structure métallique, charpente, rack de tuyauterie, portique, plateforme, passerelle
- CIVIL_FOUNDATION : Fondation, génie civil, massif béton, traversée, ancrage, dalle, rétention, cuvette
- GAS_FIRE_DETECTION : Détection gaz, détection incendie, FGS, FAS, détecteur gaz/flamme/chaleur
- FIRE_EXTINGUISHER : Extincteurs d'incendie, bouteilles de gaz sous pression, extincteur poudre ABC/CO2/eau, EN 3-8, bouteille extincteur
- TELECOM_SCADA : SCADA, DCS, RTU, télécommunication, fibre optique, supervision, contrôle à distance
- CRANE_LIFTING : Grue, pont roulant, palan, engin de levage, chariot élévateur, élingue, manutention
- UNKNOWN : Type non identifiable avec certitude

Réponds UNIQUEMENT avec le code (ex: PRESSURE_VESSEL) sans explication.

TEXTE À ANALYSER (extrait) :
{text_sample}
"""


class ARHRegulatoryEngine:
    """
    Moteur de règles d'audit réglementaire ARH.
    v2.0 — Détection sémantique LLM avec fallback keyword.
    """

    _OLLAMA_CHECKED = False
    _OLLAMA_ONLINE = False

    @staticmethod
    def _detect_via_llm(text_sample: str) -> str:
        """
        Détection sémantique du type d'équipement via le client unifié ARHOllamaClient.
        Retourne None immédiatement si Ollama n'est pas actif (circuit-breaker mémoire).
        """
        if os.getenv("ARH_DISABLE_LLM") == "1":
            return None

        try:
            from arh_ollama_client import get_ollama_client, TIMEOUT_PROBE
            client = get_ollama_client()
            if not client.is_available():
                return None

            try:
                from config import AGENT_MODEL
            except ImportError:
                AGENT_MODEL = os.getenv("ARH_LLM_MODEL", "llama3.1:8b")

            sample = text_sample[:3000] if len(text_sample) > 3000 else text_sample
            prompt = _LLM_DETECT_PROMPT.format(text_sample=sample)

            raw_out = client.generate(
                model=AGENT_MODEL,
                prompt=prompt,
                options={"temperature": 0.0, "num_predict": 32},
                timeout=TIMEOUT_PROBE
            )
            if raw_out:
                raw = raw_out.strip().upper()
                valid_types = set(EQUIPMENT_TYPES.keys()) | {"UNKNOWN"}
                first_token = re.split(r'[^A-Z_]+', raw)[0] if raw else ""
                if first_token in valid_types:
                    return first_token
                for eq_type in list(EQUIPMENT_TYPES.keys()) + ["UNKNOWN"]:
                    if re.search(rf'\b{eq_type}\b', raw):
                        return eq_type
        except Exception as e:
            logger.debug(f"[ARH] LLM detect indisponible (fallback keyword): {e}")
        return None

    @staticmethod
    def identify_equipment_type(text_content: str, metadata: Dict[str, Any] = None) -> str:
        """
        Identifie le type d'équipement par analyse sémantique en 2 étapes :
        
        ÉTAPE 0 — Priorités absolues (Tee à barreau / Fittings, Linepipe)
        ÉTAPE 1 — Détection LLM (compréhension contextuelle du sens)
        ÉTAPE 2 — Fallback scoring pondéré par fréquence de mots-clés
        ÉTAPE 3 — UNKNOWN si rien n'est identifié
        """
        search_blob = (text_content + " " + str(metadata or {})).upper()

        # ── Étape 0 : Analyse du Nom de Fichier & Titre de la Page de Garde ───────────
        fname_blob = ""
        unit_blob = ""
        if metadata and isinstance(metadata, dict):
            f_list = metadata.get("filenames") or metadata.get("file_name") or metadata.get("file_names") or []
            if isinstance(f_list, str):
                f_list = [f_list]
            fname_blob = " ".join(f_list).upper()
            unit_blob = f"{metadata.get('unit_name', '')} {metadata.get('project_name', '')}".upper()
        
        # ── Étape 0.0 : Détection Ultra-Prioritaire par Nom de Fichier et Titre/Unité ──
        target_eval_blob = fname_blob + " " + unit_blob
        if target_eval_blob.strip():
            import unicodedata
            fu = ''.join(c for c in unicodedata.normalize('NFD', target_eval_blob) if unicodedata.category(c) != 'Mn').upper()
            if any(k in fu for k in ['EXTINCTEUR', 'EXTINGUISHER', 'POUDRE ABC', 'POUDRE EXTINCTRICE', 'BOUTEILLE', 'BOUTEILLES', 'CYLINDRE', 'CYLINDER']):
                logger.info(f"[ARH] Équipement identifié par nom/unité : FIRE_EXTINGUISHER ({target_eval_blob[:60]})")
                return "FIRE_EXTINGUISHER"
            if any(k in fu for k in ['BATTERIE', 'BATTERY', 'PHOTOVOLTAIQUE', 'SOLAIRE', 'ONDULEUR', 'TRANSFORMATEUR', 'HTA', 'CABLE', 'UPS', 'ASI', 'ELECTRIQUE', 'ELECTRICAL']):
                logger.info(f"[ARH] Équipement identifié par nom/unité : ELECTRICAL ({target_eval_blob[:60]})")
                return "ELECTRICAL"
            if any(k in fu for k in ['CHOCK', 'CHOKE', 'BLOWDOWN', 'VALVE', 'SJV', 'ESDV', 'API 6D', 'API 600', 'ASME B16.34']):
                logger.info(f"[ARH] Équipement identifié par nom/unité : VALVE ({target_eval_blob[:60]})")
                return "VALVE"
            if any(k in fu for k in ['CS PIPES', 'SS PIPES', 'LINEPIPE', 'API 5L', 'ISO 3183', 'ASTM A106', 'ASTM A333']):
                logger.info(f"[ARH] Équipement identifié par nom/unité : LINEPIPE ({target_eval_blob[:60]})")
                return "LINEPIPE"
            if any(k in fu for k in ['FLANGES', 'BRIDE', 'ANCHOR FLANGE', 'ASME B16.5', 'ASME B16.47', 'MSS SP-44']):
                logger.info(f"[ARH] Équipement identifié par nom/unité : FLANGE ({target_eval_blob[:60]})")
                return "FLANGE"
            if any(k in fu for k in ['BARRED TEE', 'TEE A BARREAU', 'TEE A BAREAU', 'TE A BARREAUX']):
                logger.info(f"[ARH] Équipement identifié par nom/unité : BARRED_TEE ({target_eval_blob[:60]})")
                return "BARRED_TEE"
            if any(k in fu for k in ['FITTINGS', 'FITTING', 'RACCORD', 'JOINT ISOLANT', 'ASME B16.9', 'MSS SP-75', 'INSULATING JOINT']):
                logger.info(f"[ARH] Équipement identifié par nom/unité : FITTING ({target_eval_blob[:60]})")
                return "FITTING"
            if any(k in fu for k in ['SOUPAPE', 'PSV', 'PRV', 'SAFETY VALVE']):
                logger.info(f"[ARH] Équipement identifié par nom/unité : SAFETY_VALVE ({target_eval_blob[:60]})")
                return "SAFETY_VALVE"
            if any(k in fu for k in ['GARE RACLEUR', 'SCRAPER', 'PIG TRAP']):
                logger.info(f"[ARH] Équipement identifié par nom/unité : SCRAPER_TRAP ({target_eval_blob[:60]})")
                return "SCRAPER_TRAP"

        full_header_blob = (fname_blob + " " + unit_blob + " " + text_content[:2000]).upper()

        # 0.05 EXTINCTEURS D'INCENDIE & BOUTEILLES DE GAZ (FIRE_EXTINGUISHER)
        extinguisher_kws = ["EXTINCTEUR", "FIRE EXTINGUISHER", "POUDRE ABC", "POUDRE EXTINCTRICE", "CORPS D'EXTINCTEUR", "EXTINCTEUR PORTATIF", "EXTINCTEUR MOBILE", "EN 3-8", "EN 3-7", "BOUTEILLE", "BOUTEILLES", "CYLINDRE", "CYLINDER", "BOUTEILLE DE GAZ", "GAS CYLINDER"]
        if any(kw in full_header_blob for kw in extinguisher_kws):
            logger.info("[ARH] Dossier Extincteur / Bouteille d'incendie détecté -> Classification FIRE_EXTINGUISHER")
            return "FIRE_EXTINGUISHER"

        # 0.1 SOUPAPES DE SÛRETÉ & DISQUES DE RUPTURE (SAFETY_VALVE)
        safety_valve_kws = ["SOUPAPE DE SURETE", "SOUPAPE DE SÛRETÉ", "PRESSURE SAFETY VALVE", "SAFETY VALVE", "PSV-", "PRV-", "DISQUE DE RUPTURE", "RUPTURE DISK"]
        if any(kw in full_header_blob for kw in safety_valve_kws):
            logger.info("[ARH] Soupape de sécurité / PSV détectée -> Classification SAFETY_VALVE")
            return "SAFETY_VALVE"

        # 0.2 VANNES / ROBINETTERIE (VALVE)
        if any(kw in full_header_blob for kw in ["CHOCK", "CHOKE", "BLOWDOWN", "VALVES", "VALVE", "ROBINETTERIE", "VANNE AUTOMATIQUE", "VANNE MANUELLE", "CLAPET", "BALL VALVE", "GATE VALVE", "CHECK VALVE", "VANNE A SPHERE", "ROBINET", "SJV", "ESDV", "SDVC", "API 6D", "API 600", "ASME B16.34"]):
            logger.info("[ARH] Dossier Vanne/Robinetterie détecté -> Classification VALVE")
            return "VALVE"

        # 0.3 BRIDES & BRIDES D'ANCRAGE (FLANGE)
        flange_kws = ["BRIDE D'ANCRAGE", "BRIDE D'ENCRAGE", "ANCHOR FLANGE", "FLANGES", "BRIDES", "BRIDE", "FLANGE", "MSS SP-44", "ASME B16.5", "ASME B16.47", "EN 1092-1"]
        if any(kw in full_header_blob for kw in flange_kws) and not any(kw in full_header_blob for kw in ["TEE A BARREAU", "BARRED TEE"]):
            logger.info("[ARH] Dossier Bride / Flange détecté -> Classification FLANGE")
            return "FLANGE"

        # 0.4 TÉS À BARREAU, RACCORDS & JOINTS ISOLANTS (FITTING)
        fitting_priority_kws = ["TEE A BARREAU", "TEE À BARREAU", "BARRED TEE", "BARRED REDUCING TEE",
                                "PIGGABLE TEE", "SCRAPER TEE", "WELDOLET", "SWEEPOLET", "SOCKOLET",
                                "THREADOLET", "ELBOW 90", "ELBOW 45", "REDUCING TEE", "CONCENTRIC REDUCER",
                                "JOINT ISOLANT", "INSULATING JOINT", "MONOLITHIC ISOLATION",
                                "FITTINGS", "FITTING", "RACCORD", "COUDE", "ASME B16.9", "MSS SP-75", "MSS SP-97"]
        if any(kw in full_header_blob for kw in fitting_priority_kws):
            logger.info("[ARH] Dossier de raccordement / Raccord / Té / Joint Isolant détecté -> Classification FITTING")
            return "FITTING"

        # 0.5 TUBES DE LIGNE & PIPELINE (LINEPIPE)
        linepipe_kws = ["LINEPIPE", "FOURNITURE TUBE", "FOURNITURE DE TUBES",
                        "FABRICATION TUBE", "FABRICATION DE TUBES", "TUBE CANALISATION", "TUBES CANALISATION",
                        "CS PIPES", "SS PIPES", "PIPES", "PIPING", "API 5L", "ISO 3183", "ASTM A106", "ASTM A333", "ASTM A312",
                        "TUBES DE LIGNE", "TUBE DE LIGNE", "TUBES", "TUBE", "X60", "X52", "X65", "X70"]
        if any(re.search(r'\b' + re.escape(kw) + r'\b', full_header_blob) for kw in linepipe_kws):
            logger.info("[ARH] Dossier de fourniture/fabrication tubes en usine détecté -> Classification LINEPIPE")
            return "LINEPIPE"

        # 0.6 POMPES (PUMP)
        if any(kw in full_header_blob for kw in ["MOTOPOMPE", "POMPE CENTRIFUGE", "PUMP PACKAGE", "POMPES", "PUMP"]):
            logger.info("[ARH] Dossier Pompe/Motopompe détecté -> Classification PUMP")
            return "PUMP"

        # 0.7 COMPRESSEURS (COMPRESSOR)
        if any(kw in full_header_blob for kw in ["TURBOCOMPRESSEUR", "COMPRESSEUR", "COMPRESSOR PACKAGE", "GAS COMPRESSOR"]):
            logger.info("[ARH] Dossier Compresseur détecté -> Classification COMPRESSOR")
            return "COMPRESSOR"

        # 0.8 BACS & CITERNES (TANK vs PRESSURE_VESSEL)
        if any(kw in full_header_blob for kw in ["CITERNE", "BAC DE STOCKAGE", "RESERVOIR DE STOCKAGE", "STORAGE TANK", "FIXED ROOF TANK", "FLOATING ROOF TANK"]):
            if any(p_kw in full_header_blob for p_kw in ["ASME VIII", "ASME 8", "PRESSURE VESSEL", "APPAREIL A PRESSION", "APPAREIL À PRESSION", "SOUS PRESSION", "ESP", "PURGE"]):
                logger.info("[ARH] Citerne sous pression / ASME VIII détectée -> Classification PRESSURE_VESSEL")
                return "PRESSURE_VESSEL"
            logger.info("[ARH] Dossier Bac/Citerne de stockage atmosphérique détecté -> Classification TANK")
            return "TANK"

        # 0.9 FILTRE SÉPARATEUR (FILTER_SEPARATOR)
        filter_sep_kws = ["FILTRE SEPARATEUR", "FILTRE SÉPARATEUR", "FILTER SEPARATOR", "EPURATEUR", "STRAINER PANIER", "FILTRE COALESCER", "COALESCER FILTER"]
        if any(kw in full_header_blob for kw in filter_sep_kws):
            logger.info("[ARH] Filtre Séparateur / Épurateur détecté -> Classification FILTER_SEPARATOR")
            return "FILTER_SEPARATOR"

        # 0.10 SÉPARATEUR DE PROCÉDÉ (SEPARATOR)
        separator_kws = ["SEPARATEUR TRI-PHASIQUE", "SÉPARATEUR TRI-PHASIQUE", "SEPARATEUR DIPHASIQUE", "SÉPARATEUR DIPHASIQUE", "3-PHASE SEPARATOR", "2-PHASE SEPARATOR", "PRODUCTION SEPARATEUR", "TEST SEPARATEUR", "SÉPARATEUR DE PRODUCTION", "SÉPARATEUR D'ESSAI"]
        if any(kw in full_header_blob for kw in separator_kws):
            logger.info("[ARH] Séparateur de procédé détecté -> Classification SEPARATOR")
            return "SEPARATOR"

        # 0.11 SYSTÈME DE COMPTAGE FISCAL (METERING)
        metering_kws = ["COMPTAGE FISCAL", "FISCAL METERING", "METERING SKID", "SKID DE COMPTAGE", "SKID COMPTAGE", "DEBITMETRE CORIOLIS", "DÉBITMÈTRE CORIOLIS", "DÉBITMÈTRE FISCAL", "DEBITMETRE FISCAL", "METERING RUN"]
        if any(kw in full_header_blob for kw in metering_kws):
            logger.info("[ARH] Système de comptage fiscal détecté -> Classification METERING")
            return "METERING"

        # 0.12 ÉLECTRIQUE & INSTRUMENTATION (ELECTRICAL / INSTRUMENTATION)
        electrical_kws = ["BATTERIE", "BATTERY", "PHOTOVOLTAIQUE", "PHOTOVOLTAÏQUE", "SOLAR", "SOLAIRE", "UPS", "ASI", "TRANSFORMATEUR", "ONDULEUR", "HTA", "TABLEAU HTA", "POSTE ELECTRIQUE", "NEUTRE DU TRANSFORMATEUR", "CABLE MT", "CABLES MT"]
        if any(kw in full_header_blob for kw in electrical_kws):
            logger.info("[ARH] Équipement Électrique / Batterie / Solaire détecté -> Classification ELECTRICAL")
            return "ELECTRICAL"

        # ── Étape 1 : Appel LLM sémantique ───────────────────────────────────────
        llm_result = ARHRegulatoryEngine._detect_via_llm(text_content[:3000])
        if llm_result and llm_result != "UNKNOWN" and llm_result in EQUIPMENT_TYPES:
            logger.info(f"[ARH] Type équipement détecté par LLM : {llm_result}")
            return llm_result

        # ── Étape 2 : Scoring keyword pondéré (fallback) ─────────────────────────
        scores = {}
        for eq_type, info in EQUIPMENT_TYPES.items():
            score = 0
            for kw in info["keywords"]:
                matches = len(re.findall(r'\b' + re.escape(kw) + r'\b', search_blob))
                # Pondération : les mots-clés plus longs / spécifiques reçoivent un poids nettement supérieur
                weight = len(kw.split()) * 5 if len(kw.split()) > 1 else 2
                score += matches * weight
            if score > 0:
                scores[eq_type] = score

        if not scores:
            logger.warning("[ARH] Aucun type d'équipement identifié — retour UNKNOWN")
            return "UNKNOWN"

        best_type = max(scores, key=scores.get)
        logger.info(f"[ARH] Type équipement (keyword fallback) : {best_type} (score={scores[best_type]})")
        return best_type

    @staticmethod
    def get_applicable_decrees(equipment_type: str) -> List[Dict[str, str]]:
        """
        Détermine la liste des décrets et réglementations applicables.
        Pour un type UNKNOWN, retourne la liste minimale commune.
        """
        if equipment_type == "UNKNOWN":
            decree_keys = ["DE_21_261", "DE_21_257", "DE_24_278"]
        else:
            eq_info = EQUIPMENT_TYPES.get(equipment_type, EQUIPMENT_TYPES["PRESSURE_VESSEL"])
            decree_keys = eq_info.get("decrees", ["DE_21_261", "DE_21_257"])

        results = []
        for d_key in decree_keys:
            if d_key in DECREES_CATALOG:
                results.append({
                    "key": d_key,
                    "title": DECREES_CATALOG[d_key]["title"],
                    "description": DECREES_CATALOG[d_key]["description"]
                })
        return results

    @staticmethod
    def has_electrical_scope(equipment_type: str, text: str = "") -> bool:
        """
        Détermine si l'équipement relève légitimement du domaine électrique/instrumentation/ATEX.
        Pour les équipements purement mécaniques (VALVE manuelle, SAFETY_VALVE, FITTING, LINEPIPE,
        PIPING_SPOOL, PRESSURE_VESSEL, STORAGE_TANK, HEAT_EXCHANGER), retourne False SAUF si une motorisation
        ou instrumentation active (MOV, actionneur électrique, électrovanne, transmetteur) est explicitement détectée.
        """
        tu = text.upper() if text else ""
        eq = (equipment_type or "PRESSURE_VESSEL").upper()
        
        # 1. Équipements nativement électriques ou instrumentés
        if eq in ("ELECTRICAL", "INSTRUMENTATION", "METERING", "MOTOR_OPERATED_VALVE", "ACTUATED_VALVE"):
            return True
            
        # 2. Équipements tournants avec moteur électrique
        if eq in ("PUMP", "COMPRESSOR") and any(k in tu for k in ["MOTOR", "MOTEUR", "ELECTRIQUE", "ÉLECTRIQUE", "KW", "HP", "VOLT", "400V", "690V", "6.6KV", "10KV"]):
            return True
            
        # 3. Vannes : uniquement si motorisées (MOV / Actuator / Solenoid)
        if eq in ("VALVE", "SAFETY_VALVE"):
            has_motor_actuator = any(k in tu for k in [
                "MOTOR OPERATED", "ELECTRIC ACTUATOR", "ACTIONNEUR ELECTRIQUE", "ACTIONNEUR ÉLECTRIQUE",
                "ELECTROVANNE", "SOLENOID VALVE", "LIMIT SWITCH", "FIN DE COURSE ELECTRIQUE",
                "SMART POSITIONER", "POSITIONNEUR ELECTRIQUE", "POSITIONNEUR INTELLIGENT",
                "VANNE MOTORISEE", "VANNE MOTORISÉE"
            ])
            return has_motor_actuator
            
        # 4. Équipements statiques sous pression : uniquement si réchauffeur électrique ou instrumentation
        if eq in ("PRESSURE_VESSEL", "SEPARATOR", "FILTER_SEPARATOR", "SKID"):
            has_elec_package = any(k in tu for k in [
                "ELECTRIC HEATER", "RECHAUFFEUR ELECTRIQUE", "RÉCHAUFFEUR ÉLECTRIQUE",
                "CONTROL PANEL", "ARMOIRE ELECTRIQUE", "JUNCTION BOX", "BOITE DE JONCTION"
            ])
            return has_elec_package
            
        # 5. Raccords, Tubes, Tuyauteries, Extincteurs : False sauf si boîte de jonction ou composant ATEX détecté
        if eq in ("FITTING", "LINEPIPE", "PIPING_SPOOL", "BARRED_TEE", "FIRE_EXTINGUISHER"):
            if any(k in tu for k in ["JUNCTION BOX", "BOITE DE JONCTION", "BOÎTE DE JONCTION", "COFFRET ELECTRIQUE", "ENCLOSURE EX"]):
                return True
            return False
            
        return False

    @staticmethod
    def detect_dossier_stage(text_content: str, filenames: List[str] = None) -> str:
        """
        Détecte automatiquement si le dossier est un Dossier Préliminaire (Conception/Études/Fabrication)
        ou un Dossier Final (Construction/Réception & Demande de Mise en Produit/Tension).

        Priorités de détection (décroissantes) :
        1. Nom de répertoire ou chemin (ex: '02 DOSSIER PRELIMINAIRE' vs '03 DOSSIER FINAL')
        2. Titre explicite dans le nom de fichier ('PRELIMINAIRE', 'NOTE DE CALCUL', 'ETAT DESCRIPTIF' vs 'FINAL', 'AS-BUILT')
        3. Titre explicite dans les 2500 premiers caractères (page de garde / bordereau / lettre)
        4. Score pondéré sur tout le texte
        """
        filenames = filenames or []

        # PRIORITÉ 1 : Chemin et noms de fichiers (signal absolu)
        import unicodedata
        def _norm_s(s: str) -> str:
            return "".join(c for c in unicodedata.normalize('NFKD', str(s).upper()) if not unicodedata.combining(c))

        file_blob = _norm_s(" ".join(filenames).replace("\\", "/").replace("_", " "))
        if any(k in file_blob for k in [
            "/02 ", " 02-", "02-DOSSIER", "DOSSIER PRELIMINAIRE",
            "PRELIMINARY", "PRELIM", "ETAT DESCRIPTIF", "NOTE DE CALCUL",
            "CALCULATION NOTE", "CONCEPTION", "DRAFT"
        ]):
            return "PRELIMINARY"
        if any(k in file_blob for k in [
            "/03 ", "/04 ", " 03-", " 04-", "03-DOSSIER", "04-DOSSIER", "DOSSIER FINAL",
            "DOSSIER DE CONSTRUCTION", "AS-BUILT", "AS BUILT", "RECEPTION FINALE", "FINAL DOSSIER", "FINAL"
        ]):
            return "FINAL_RECEPTION"

        # PRIORITÉ 2 : Page de garde (2500 premiers caractères = lettre de transmission / couverture)
        header_text = text_content[:2500].upper()
        prelim_header = [
            "DOSSIER PRELIMINAIRE", "DOSSIER PRÉLIMINAIRE", "PRELIMINARY DOSSIER",
            "DOSSIER DE FABRICATION", "STADE PRELIMINAIRE", "DEMANDE D'APPROBATION",
            "APPROBATION DU DOSSIER TECHNIQUE", "DOSSIER TECHNIQUE PRELIMINAIRE",
            "DEMANDE D'AVIS SUR LA CONFORMITE", "ETUDE PRELIMINAIRE", "ÉTUDE PRÉLIMINAIRE",
            "ANNEXE A", "P-CTE-1 ANNEXE A"
        ]
        final_header = [
            "DOSSIER FINAL DE CONSTRUCTION", "DOSSIER FINAL", "DOSSIER DE CONSTRUCTION",
            "RECEPTION FINALE", "DEMANDE DE MISE EN PRODUIT", "MISE SOUS TENSION",
            "DOSSIER AS-BUILT", "ANNEXE G", "P-CTE-1 ANNEXE G", "DOSSIER CONSTRUCTEUR"
        ]
        if any(k in header_text for k in prelim_header):
            return "PRELIMINARY"
        if any(k in header_text for k in final_header):
            return "FINAL_RECEPTION"

        # PRIORITÉ 3 : Score pondéré sur tout le texte
        preliminary_scored = [
            (4, "DOSSIER PRELIMINAIRE"), (4, "DOSSIER PRÉLIMINAIRE"), (3, "PRELIMINARY"),
            (3, "APPROBATION PRELIMINAIRE"), (3, "AVIS SUR LA CONFORMITE"),
            (2, "DOSSIER TECHNIQUE DU CONSTRUCTEUR"), (2, "FABRICATION"),
            (2, "CONCEPTION"), (2, "DESIGN DOSSIER"), (2, "ETAT DESCRIPTIF"),
            (1, "DECRET 21-261 ART 15"), (1, "DECRET 21-315 ART 14"),
        ]
        final_scored = [
            (5, "DOSSIER FINAL DE CONSTRUCTION"), (5, "DEMANDE DE MISE EN PRODUIT"),
            (4, "MISE SOUS TENSION"), (4, "DOSSIER AS-BUILT"), (3, "AS-BUILT"), (3, "AS BUILT"),
            (3, "DOSSIER CONSTRUCTEUR"), (2, "DECRET 21-257"), (2, "DECRET 21-314 ART 26"),
            (1, "RECEPTION FINALE"), (1, "CVI")
        ]

        blob = text_content.upper()
        score_prelim = sum(w for w, kw in preliminary_scored if kw in blob)
        score_final = sum(w for w, kw in final_scored if kw in blob)

        if score_final > score_prelim + 3:
            return "FINAL_RECEPTION"
        elif score_prelim > 0:
            return "PRELIMINARY"
        else:
            # Par défaut : PRELIMINARY (le cas le plus soumis à l'ARH avant fabrication)
            return "PRELIMINARY"

    @staticmethod
    def generate_mandatory_checklist(equipment_type: str, dossier_stage: str = "FINAL_RECEPTION") -> List[Dict[str, Any]]:
        """
        Génère la checklist documentaire dynamique obligatoire adaptée :
        - Au TYPE D'ÉQUIPEMENT identifié (SKID, FURNACE, FLARE, FITTING, VALVE, etc.)
        - Au STADE du dossier ARH (Préliminaire vs Final de Réception)
        
        Pour le stade PRÉLIMINAIRE :
        - Les pièces post-fabrication (MTC 3.1 réels, WPQ ouvriers, PV hydro final, CND de chantier, CVI, etc.)
          sont explicitement qualifiées de "Stage_Optional" avec la mention :
          'Non exigible au stade préliminaire (différé au dossier final selon P-CTE-1). Aucune pénalité Arkan.'
        """
        base_checklist = []

        if equipment_type == "UNKNOWN":
            base_checklist = list(DEFAULT_CHECKLIST)
            base_checklist.insert(0, {
                "code": "IDENTIFICATION",
                "name": "⚠️ TYPE D'ÉQUIPEMENT NON IDENTIFIÉ — Fournir une description explicite du type d'équipement pour obtenir la checklist complète applicable",
                "criticality": "Critical",
                "aliases": []
            })
        elif equipment_type in MANDATORY_DOCUMENTS_MASTER:
            base_checklist = list(MANDATORY_DOCUMENTS_MASTER[equipment_type])
        elif equipment_type in ("SEPARATOR", "HEAT_EXCHANGER", "COLUMN", "SPHERE"):
            base_checklist = list(MANDATORY_DOCUMENTS_MASTER["PRESSURE_VESSEL"])
        elif equipment_type == "FLOWLINE":
            base_checklist = list(MANDATORY_DOCUMENTS_MASTER["PIPELINE"])
        elif equipment_type in ("COMPRESSOR", "PUMP"):
            base_checklist = list(MANDATORY_DOCUMENTS_MASTER["ROTATING_MACHINERY"])
        elif equipment_type in ("FITTING", "VALVE", "PIPING_SPOOL", "SAFETY_VALVE",
                                "METERING", "FILTER_SEPARATOR", "HEAT_TRACING",
                                "STRUCTURAL_STEEL", "CIVIL_FOUNDATION",
                                "GAS_FIRE_DETECTION", "TELECOM_SCADA", "CRANE_LIFTING"):
            base_checklist = list(MANDATORY_DOCUMENTS_MASTER[equipment_type])
        else:
            base_checklist = list(DEFAULT_CHECKLIST)

        # ═══════════════════════════════════════════════════════════════════
        # FUSION avec la checklist procédurale universelle P-CTE-1 (Annexe A
        # pour le préliminaire, Annexe G pour le final)
        # ═══════════════════════════════════════════════════════════════════
        existing_codes = {d["code"] for d in base_checklist}

        universal_source = PCTE1_PRELIMINARY_UNIVERSAL if dossier_stage == "PRELIMINARY" else PCTE1_FINAL_UNIVERSAL
        for univ_doc in universal_source:
            code = univ_doc["code"]
            if code in existing_codes:
                continue

            pressure_only_codes = {
                "CERT_VISITE_INT_EXT", "TRAIT_THERMIQUE_SPEC", "QUALIF_SOUDEURS",
                "DESTRUCTIVE_TEST_REP", "DIAG_TRAIT_THERMIQUE", "CERT_INSP_VISITE_FINAL"
            }
            if code in pressure_only_codes and equipment_type not in PRESSURE_FABRICATION_TYPES:
                continue

            base_checklist.append(univ_doc)
            existing_codes.add(code)

        # Adaptation stricte selon le stade du dossier ARH
        adapted_checklist = []
        for doc in base_checklist:
            d_copy = dict(doc)
            code = d_copy["code"]

            # Exclure ATEX_CERT pour les équipements mécaniques purs sans composant électrique
            if code == "ATEX_CERT":
                if equipment_type in ("FITTING", "PIPING_SPOOL", "SAFETY_VALVE", "LINEPIPE", "FLOWLINE",
                                      "PIPELINE", "STRUCTURAL_STEEL", "CIVIL_FOUNDATION",
                                      "PRESSURE_VESSEL", "SEPARATOR", "HEAT_EXCHANGER", "TANK", "SPHERE", "FILTER_SEPARATOR"):
                    continue

            if dossier_stage == "PRELIMINARY":
                # Pièces post-fabrication NON OBLIGATOIRES au stade préliminaire
                if code in ("HYDRO_PV", "SAT", "CALIBRATION", "PIGGING", "COATING_REP",
                            "EMISSION_REP", "VACUUM_TEST", "WEIGHT_CERT", "TARAGE_CERT",
                            "NDT_REP", "INSP_REP", "MILL_COATING", "FAT",
                            "DIELECTRIC", "EARTHING", "VIB_REP", "STACK_CERT",
                            "REFRACTORY", "BLOCK_VALVE", "ARH_APPROVAL", "MAT_CERT",
                            "ATEX_CERT", "CE_DECL", "NAMEPLATE", "SHELL_TEST", "SEAT_TEST",
                            "TORQUE_TEST", "DIM_CERT", "QUALIF_SOUDEURS", "DESTRUCTIVE_TEST_REP",
                            "DIAG_TRAIT_THERMIQUE", "CERT_INSP_VISITE_FINAL", "DOSSIER_PRELIM_JOINT",
                            "LETTRE_AVIS_ARH_PRELIM", "LETTRE_INVITATION_INSPECTEUR", "REPONSE_ARH_PRESENCE"):
                    d_copy["criticality"] = "Stage_Optional"
                    d_copy["is_stage_optional"] = True
                    d_copy["stage_note"] = "Pièce post-fabrication non exigible au préliminaire (différée au dossier final selon P-CTE-1). Aucune pénalité Arkan."
                else:
                    d_copy["is_stage_optional"] = False

            elif dossier_stage == "FINAL_RECEPTION":
                # Au stade final, les pièces préliminaires d'origine sont incluses via DOSSIER_PRELIM_JOINT
                d_copy["is_stage_optional"] = False

            adapted_checklist.append(d_copy)

        return adapted_checklist

        return adapted_checklist

    @staticmethod
    def verify_ndt_extent(zone: str, actual_percent: float, fluid_type: str = "LIQUID") -> Tuple[bool, float, str]:
        """
        Vérifie la conformité de l'étendue des CND par radiographie selon le Décret 21-314 (Art 8 et 9).
        """
        zone = zone.upper().strip()
        fluid_type = fluid_type.upper().strip()

        if "GAS" in fluid_type or "GPL" in fluid_type or "LPG" in fluid_type:
            required = 100.0
            rule_ref = "Décret 21-314 Art. 8 (100% pour Gaz/GPL)"
        else:
            req_map = {"ZONE A": 75.0, "ZONE B": 40.0, "ZONE C": 15.0, "ZONE D": 10.0}
            required = req_map.get(zone, 100.0)
            rule_ref = f"Décret 21-314 Art. 9 ({required}% pour {zone})"

        is_ok = actual_percent >= required
        return is_ok, required, rule_ref

    @staticmethod
    def verify_hydrotest_pressure(
        pma_bar: float,
        pms_bar: float,
        actual_test_bar: float,
        equipment_type: str,
        zone: str = "ZONE A",
        max_test_bar: Optional[float] = None
    ) -> Tuple[bool, float, str]:
        """
        Vérifie la valeur de la pression d'épreuve hydrostatique minimale réglementaire.
        Si `max_test_bar` est fourni (ex. 90 % R_t0.5 pour les tubes, Décret 21-315 Art. 21, ou limite
        UG-99 de l'équipement), une surpression d'épreuve est aussi signalée.
        """
        eq_type = equipment_type.upper()
        zone = zone.upper()

        if "PIPELINE" in eq_type or "CANALISATION" in eq_type or "FLOWLINE" in eq_type:
            if "ZONE C" in zone or "ZONE D" in zone:
                mult = 1.25
                rule_ref = "Décret 21-314 Art. 21 (125% PMA pour Zone C/D)"
            else:
                mult = 1.50
                rule_ref = "Décret 21-314 Art. 21 (150% PMA pour Zone A/B)"
            required_p = round(pma_bar * mult, 2)
        else:
            # Équipements Sous Pression (ESP) Décret 21-261 Art. 27
            mult = 1.50
            required_p = round(pma_bar * mult, 2)
            rule_ref = "Décret 21-261 Art. 27 (150% PMA pour ESP)"

        is_ok = actual_test_bar >= required_p
        if max_test_bar is not None and actual_test_bar > max_test_bar:
            is_ok = False
            rule_ref += f" | SURPRESSION d'épreuve : {actual_test_bar} bar > maximum admissible {max_test_bar} bar"
        return is_ok, required_p, rule_ref

    @staticmethod
    def calculate_min_pipe_thickness(
        p_bar: float,
        d_mm: float,
        r_t05_bar: float,
        f_factor: float,
        z_coef: float = 1.0
    ) -> float:
        """
        Calcule l'épaisseur minimale réglementaire de tube selon le Décret 21-315 Art 7:
        e = (P * D) / (2 * R_t0.5 * F * Z)
        """
        if (r_t05_bar * f_factor * z_coef) == 0:
            return 0.0
        e_mm = (p_bar * d_mm) / (2.0 * r_t05_bar * f_factor * z_coef)
        return round(e_mm, 3)

    @staticmethod
    def calculate_asme_required_wall_thickness(
        p_bar: float,
        d_mm: float,
        grade_astm: str = "A105",
        corrosion_allowance_mm: float = 3.0,
        joint_efficiency: float = 1.0,
        y_coefficient: float = 0.4
    ) -> Dict[str, Any]:
        """
        Calculateur de tuyauterie ASME B31.3 (Pillar 4) : t = P*D / (2*(S*E + P*Y)) + c.
        ATTENTION : cette formule est celle de la TUYAUTERIE (B31.3), pas celle des enveloppes d'appareils
        ASME VIII-1 UG-27 (voir arh_code_harness.calculate_minimum_wall_thickness_asme / arh_deterministic_calcs).
        Les contraintes ci-dessous sont des valeurs de référence indicatives à température ambiante ; un grade
        absent de la table renvoie `grade_known=False` (la valeur par défaut n'est PAS fiable).
        """
        ALLOWABLE_STRESSES_MPA = {
            "A105": 138.0,
            "A694 F60": 286.0,
            "A234 WPB": 138.0,
            "A234 WPC": 150.0,
            "A350 LF2": 138.0,
            "A350 LF3": 150.0,
            "A420 WPL6": 138.0,
            "SA-516 GR 70": 138.0,
            "SA-516 GR 60": 118.0,
            "A516 GR 70": 138.0,
            "A516 GR 60": 118.0,
            "A106 GR B": 118.0,
            "A333 GR 6": 118.0,
            "X52": 250.0,
            "X60": 286.0,
            "X65": 310.0,
            "X70": 335.0,
            "304": 115.0,
            "304L": 105.0,
            "316": 115.0,
            "316L": 105.0
        }
        grade_known = grade_astm.upper() in ALLOWABLE_STRESSES_MPA
        s_mpa = ALLOWABLE_STRESSES_MPA.get(grade_astm.upper(), 138.0)
        s_bar = s_mpa * 10.0

        denom = 2.0 * (s_bar * joint_efficiency + p_bar * y_coefficient)
        if denom == 0:
            t_min = 0.0
        else:
            t_min = ((p_bar * d_mm) / denom) + corrosion_allowance_mm

        return {
            "t_required_mm": round(t_min, 2),
            "pressure_bar": p_bar,
            "diameter_mm": d_mm,
            "allowable_stress_mpa": s_mpa,
            "corrosion_allowance_mm": corrosion_allowance_mm,
            "grade_astm": grade_astm,
            "formula_used": "ASME B31.3 t = (P*D)/(2*(S*E + P*Y)) + c",
            "grade_known": grade_known,
            "warnings": [] if grade_known else [f"Grade '{grade_astm}' absent de la table : S=138 MPa par défaut, résultat non fiable"]
        }


    # ══════════════════════════════════════════════════════════════════════════════
    # VÉRIFICATION DE LA PORTÉE DES NORMES ET MATCHING DES RÉSERVES HISTORIQUES ARH
    # ══════════════════════════════════════════════════════════════════════════════

    NORMS_SCOPES = {
        "PRESSURE_VESSEL": {
            "valid": ["ASME VIII", "ASME SEC VIII", "CODAP", "EN 13445", "API 620", "BS 5500", "PD 5500"],
            "incompatible": {
                "API 650": "Réservé exclusivement aux bacs et réservoirs de stockage atmosphériques (API 650)",
                "ASME B31.3": "Réservé exclusivement aux tuyauteries de procédé (Process Piping)",
                "API 610": "Réservé aux pompes centrifuges",
                "API 617": "Réservé aux compresseurs axiaux et centrifuges",
            }
        },
        "TANK": {
            "valid": ["API 650", "API 620", "EN 14015", "NFPA 30", "CODRES"],
            "incompatible": {
                "ASME VIII": "Réservé aux récipients sous pression (PMA >= 0.5 bar)",
                "ASME B31.3": "Réservé aux tuyauteries de procédé",
            }
        },
        "PIPELINE": {
            "valid": ["ASME B31.4", "ASME B31.8", "API 5L", "ISO 13623", "DNV-ST-F101"],
            "incompatible": {
                "ASME VIII": "Réservé aux récipients sous pression",
                "API 650": "Réservé aux réservoirs de stockage",
                "API 610": "Réservé aux pompes centrifuges"
            }
        },
        "PIPING_SPOOL": {
            "valid": ["ASME B31.3", "ASME B31.1", "EN 13480", "ASME B16.5", "ASME B16.9"],
            "incompatible": {
                "API 650": "Réservé aux bacs de stockage",
                "API 610": "Réservé aux pompes centrifuges",
                "ASME VIII": "Réservé aux appareils sous pression"
            }
        },
        "PUMP": {
            "valid": ["API 610", "ISO 13709", "ISO 5199", "ANSI B73.1"],
            "incompatible": {
                "API 650": "Réservé aux bacs de stockage",
                "API 617": "Réservé aux compresseurs",
                "API 520": "Réservé aux soupapes de sûreté"
            }
        },
        "COMPRESSOR": {
            "valid": ["API 617", "API 618", "API 619", "ISO 10439", "ISO 13631"],
            "incompatible": {
                "API 650": "Réservé aux bacs de stockage",
                "API 610": "Réservé aux pompes centrifuges",
                "API 520": "Réservé aux soupapes de sûreté"
            }
        },
        "SAFETY_VALVE": {
            "valid": ["API 520", "API 521", "API 526", "ASME VIII", "ISO 4126"],
            "incompatible": {
                "API 650": "Réservé aux bacs de stockage",
                "API 610": "Réservé aux pompes centrifuges",
                "API 617": "Réservé aux compresseurs",
                "ASME B31.3": "Réservé aux tuyauteries de procédé"
            }
        },
        "FITTING": {
            "valid": ["ASME B16.9", "ASME B16.11", "MSS SP-75", "MSS SP-97", "EN 10253"],
            "incompatible": {
                "API 650": "Réservé aux bacs de stockage",
                "API 610": "Réservé aux pompes centrifuges",
                "API 617": "Réservé aux compresseurs"
            }
        }
    }

    @staticmethod
    def verify_norm_applicability(equipment_type: str, text_content: str) -> List[Dict[str, Any]]:
        """
        Vérifie si les normes citées dans le document sont applicables à l'équipement.
        Détecte les erreurs de portée de norme (ex: API 650 cité sur un ESP ou un Fitting).
        """
        anomalies = []
        eq_type = equipment_type.upper()
        
        # Résoudre les alias
        if eq_type in ("SEPARATOR", "HEAT_EXCHANGER", "COLUMN", "SPHERE", "FILTER_SEPARATOR"):
            eq_type = "PRESSURE_VESSEL"
        elif eq_type in ("LINEPIPE", "FLOWLINE"):
            eq_type = "PIPELINE"

        scope_info = ARHRegulatoryEngine.NORMS_SCOPES.get(eq_type)
        if not scope_info:
            return anomalies

        incompatibles = scope_info.get("incompatible", {})
        blob_upper = text_content.upper()

        for norm_code, reason in incompatibles.items():
            pattern = r'\b' + re.escape(norm_code.upper()) + r'\b'
            if re.search(pattern, blob_upper):
                anomalies.append({
                    "priority": "CRITICAL",
                    "code": "INVALID_NORM_SCOPE",
                    "title": f"❌ NORME INAPPLICABLE DÉTECTÉE : {norm_code}",
                    "comment": f"La norme '{norm_code}' est mentionnée dans le dossier mais N'EST PAS APPLICABLE à un équipement de type '{equipment_type}'. ({reason}). Normes applicables attendues : {', '.join(scope_info['valid'])}.",
                    "reference": f"P-CTE-1 / Normative Scope ({norm_code})"
                })

        return anomalies

    @staticmethod
    def match_historical_arh_reserves(equipment_type: str, text_content: str) -> List[Dict[str, Any]]:
        """
        [STRICTEMENT DÉSACTIVÉ - ISOLATION TOTALE PAR DOSSIER]
        Interdiction absolue d'injecter des réserves ou archives de projets antérieurs.
        L'audit ARH doit être strictement ancré et confiné aux documents soumis.
        """
        return []


