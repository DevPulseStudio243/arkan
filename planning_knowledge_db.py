"""
ARKAN — Intelligence EPC & Réglementaire Oil & Gas
Module: planning_knowledge_db.py
Gestionnaire de la base SQLite 'planning_knowledge.db' (mode WAL) pour :
1. Le référentiel universel des tâches EPC Oil & Gas (13 disciplines exhaustives)
2. Les rendements calibrés et équipes types
3. L'historique d'apprentissage et de correction continue
"""

import os
import json
import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("arkan.planning_db")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "planning_knowledge.db")

# ══════════════════════════════════════════════════════════════════════════════
# DÉFINITION DU SCHÉMA SQLITE (MODE WAL)
# ══════════════════════════════════════════════════════════════════════════════
SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS taches_referentiel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code_wbs TEXT UNIQUE,
    nom TEXT NOT NULL,
    discipline TEXT NOT NULL,
    unite_oeuvre TEXT NOT NULL,
    description TEXT,
    normes_associees TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rendements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tache_id INTEGER REFERENCES taches_referentiel(id) ON DELETE CASCADE,
    rendement_valeur REAL NOT NULL,
    rendement_unite TEXT NOT NULL,
    condition_site TEXT DEFAULT 'standard',
    source TEXT NOT NULL,
    niveau_confiance TEXT DEFAULT 'Moyenne',
    date_maj TEXT,
    nb_observations INTEGER DEFAULT 0,
    min_plausible REAL,
    max_plausible REAL
);

CREATE TABLE IF NOT EXISTS equipes_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tache_id INTEGER REFERENCES taches_referentiel(id) ON DELETE CASCADE,
    composition_json TEXT NOT NULL,
    ressources_json TEXT,
    source TEXT NOT NULL,
    niveau_confiance TEXT DEFAULT 'Moyenne'
);

CREATE TABLE IF NOT EXISTS historique_apprentissage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tache_id INTEGER REFERENCES taches_referentiel(id) ON DELETE SET NULL,
    rendement_estime REAL,
    rendement_reel REAL,
    ecart_pct REAL,
    projet_id TEXT,
    commentaire TEXT,
    date_validation TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_taches_discipline ON taches_referentiel(discipline);
CREATE INDEX IF NOT EXISTS idx_rendements_tache ON rendements(tache_id);
CREATE INDEX IF NOT EXISTS idx_equipes_tache ON equipes_types(tache_id);
"""

# ══════════════════════════════════════════════════════════════════════════════
# JEU DE DONNÉES INITIAL EXHAUSTIF — 13 DISCIPLINES EPC OIL & GAS (ANNEXE A)
# ══════════════════════════════════════════════════════════════════════════════
INITIAL_EPC_SEED_DATA = [
    # ── 01. INGÉNIERIE & ÉTUDES ──
    {
        "code_wbs": "01.01",
        "nom": "Revue des études de base FEED & données de procédé",
        "discipline": "01_INGENIERIE_ETUDES",
        "unite_oeuvre": "document",
        "description": "Analyse et vérification des bilans matières/chaleur et PFD du FEED",
        "normes_associees": "API RP 14E / ISO 13702",
        "rendement_valeur": 0.5,
        "rendement_unite": "doc/jour/ingénieur",
        "min_plausible": 0.1,
        "max_plausible": 2.0,
        "source": "Standards Ingénierie EPC Sonatrach / TotalEnergies",
        "equipe": [{"role": "Ingénieur Procédé Senior", "effectif": 1}, {"role": "Ingénieur Projets", "effectif": 1}],
        "ressources": ["Logiciel HYSYS/UniSim", "Station CAO"]
    },
    {
        "code_wbs": "01.02",
        "nom": "Élaboration des P&ID détaillés (Process & Piping Diagrams)",
        "discipline": "01_INGENIERIE_ETUDES",
        "unite_oeuvre": "folio P&ID",
        "description": "Conception et finalisation des schémas P&ID avec vannes, instrumentation et tuyauterie",
        "normes_associees": "ISA 5.1 / ISO 10628",
        "rendement_valeur": 0.33,
        "rendement_unite": "folio/jour/ingénieur",
        "min_plausible": 0.1,
        "max_plausible": 1.0,
        "source": "Pratiques EPC Bechtel / Technip",
        "equipe": [{"role": "Ingénieur Procédé", "effectif": 1}, {"role": "Projeteur DAO Piping", "effectif": 1}],
        "ressources": ["AutoCAD Plant 3D / SmartPlant P&ID"]
    },
    {
        "code_wbs": "01.03",
        "nom": "Modélisation 3D Tuyauterie & Détection des Clashes",
        "discipline": "01_INGENIERIE_ETUDES",
        "unite_oeuvre": "zone / skid",
        "description": "Modélisation 3D sous PDMS/E3D et revue des interférences spatiales",
        "normes_associees": "ASME B31.3",
        "rendement_valeur": 0.1,
        "rendement_unite": "skid/jour/projeteur",
        "min_plausible": 0.02,
        "max_plausible": 0.5,
        "source": "Référentiel Méthodes Tuyauterie Industrielle",
        "equipe": [{"role": "Projeteur 3D Senior", "effectif": 1}, {"role": "Ingénieur Piping", "effectif": 1}],
        "ressources": ["Aveva E3D / Navisworks Manage"]
    },
    {
        "code_wbs": "01.04",
        "nom": "Calcul de flexibilité et contraintes tuyauterie (Stress Analysis)",
        "discipline": "01_INGENIERIE_ETUDES",
        "unite_oeuvre": "ligne critique",
        "description": "Calcul des contraintes thermiques, dynamiques et charges sur buses selon ASME B31.3",
        "normes_associees": "ASME B31.3 / API 610 / WRC 107/297",
        "rendement_valeur": 0.5,
        "rendement_unite": "ligne/jour/ingénieur",
        "min_plausible": 0.1,
        "max_plausible": 2.0,
        "source": "Norme ASME B31.3 Appendix P",
        "equipe": [{"role": "Ingénieur Calcul Contraintes Piping", "effectif": 1}],
        "ressources": ["Caesar II / AutoPIPE"]
    },
    {
        "code_wbs": "01.05",
        "nom": "Émission des plans isométriques pour fabrication (IFC)",
        "discipline": "01_INGENIERIE_ETUDES",
        "unite_oeuvre": "plan isométrique",
        "description": "Extraction et vérification des plans isométriques avec nomenclature BOM",
        "normes_associees": "ASME B31.3",
        "rendement_valeur": 3.0,
        "rendement_unite": "iso/jour/projeteur",
        "min_plausible": 1.0,
        "max_plausible": 10.0,
        "source": "Standards Bureaux d'Études EPC",
        "equipe": [{"role": "Projeteur Isométrique", "effectif": 1}, {"role": "Contrôleur Qualité Études", "effectif": 1}],
        "ressources": ["ISOGEN / AutoCAD"]
    },

    # ── 02. PROCUREMENT & MATÉRIAUX ──
    {
        "code_wbs": "02.01",
        "nom": "Réquisition technique & consultation fournisseurs (MR/RFQ)",
        "discipline": "02_PROCUREMENT_LOGISTIQUE",
        "unite_oeuvre": "lot matériel",
        "description": "Élaboration des Material Requisitions et sélection des fabricants certifiés",
        "normes_associees": "ISO 9001 / API Q1",
        "rendement_valeur": 0.2,
        "rendement_unite": "lot/jour/acheteur",
        "min_plausible": 0.05,
        "max_plausible": 1.0,
        "source": "Process Procurement EPC",
        "equipe": [{"role": "Ingénieur Matériel / Acheteur Technique", "effectif": 1}, {"role": "Ingénieur Discipline", "effectif": 1}],
        "ressources": ["Système ERP / Portail Achats"]
    },
    {
        "code_wbs": "02.02",
        "nom": "Audit et inspection usine de fabrication (FAT - Factory Acceptance Test)",
        "discipline": "02_PROCUREMENT_LOGISTIQUE",
        "unite_oeuvre": "équipement majeur",
        "description": "Inspection qualité, essais de pression et contrôle dimensionnel chez le constructeur",
        "normes_associees": "EN 10204 3.1/3.2 / API 598 / ASME VIII",
        "rendement_valeur": 0.5,
        "rendement_unite": "équipement/jour/inspecteur",
        "min_plausible": 0.1,
        "max_plausible": 1.0,
        "source": "Spécification TPI / Bureau Veritas",
        "equipe": [{"role": "Inspecteur QA/QC TPI Habilité", "effectif": 1}, {"role": "Représentant Client", "effectif": 1}],
        "ressources": ["Équipements de mesure calibrés", "Procédure FAT approuvée"]
    },
    {
        "code_wbs": "02.03",
        "nom": "Transport logistique & livraison sur site (Convois exceptionnels)",
        "discipline": "02_PROCUREMENT_LOGISTIQUE",
        "unite_oeuvre": "colis lourd / skid",
        "description": "Transport sous escorte, dédouanement et réception sur plate-forme de stockage chantier",
        "normes_associees": "Réglementation transport matières dangereuses / Code de la route",
        "rendement_valeur": 1.0,
        "rendement_unite": "colis/jour",
        "min_plausible": 0.2,
        "max_plausible": 3.0,
        "source": "Guide Logistique Projets Sahariens",
        "equipe": [{"role": "Coordinateur Logistique", "effectif": 1}, {"role": "Chauffeur Poids Lourd Spécialisé", "effectif": 2}, {"role": "Agent d'escorte", "effectif": 2}],
        "ressources": ["Remorque surbaissée multi-lignes", "Grue mobile de déchargement 100t"]
    },

    # ── 03. GÉNIE CIVIL & TERRASSEMENT ──
    {
        "code_wbs": "03.01",
        "nom": "Décapage de la terre végétale & nivellement de plate-forme",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "m²",
        "description": "Décapage mécanique sur 30 cm et nivellement préalable de la plate-forme",
        "normes_associees": "NF P94-500 / Eurocode 7",
        "rendement_valeur": 1200.0,
        "rendement_unite": "m²/jour/équipe",
        "min_plausible": 400.0,
        "max_plausible": 3000.0,
        "source": "Bordereau des Rendements Génie Civil EPC",
        "equipe": [{"role": "Chef de chantier TP", "effectif": 1}, {"role": "Conducteur de Bulldozer D8", "effectif": 1}, {"role": "Conducteur de Niveleuse", "effectif": 1}, {"role": "Manœuvre TP", "effectif": 2}],
        "ressources": ["Bulldozer CAT D8", "Niveleuse 140M", "Compacteur vibrant"]
    },
    {
        "code_wbs": "03.02",
        "nom": "Fouilles en déblais pour massifs de fondations et caniveaux",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "m³",
        "description": "Excavation mécanique et manuelle pour semelles de fondations d'équipements",
        "normes_associees": "Eurocode 7 / DTU 13.1",
        "rendement_valeur": 180.0,
        "rendement_unite": "m³/jour/équipe",
        "min_plausible": 50.0,
        "max_plausible": 450.0,
        "source": "Règles Professionnelles Terrassement",
        "equipe": [{"role": "Conducteur de Pelle 20t", "effectif": 1}, {"role": "Chauffeur Camion Benne 6x4", "effectif": 2}, {"role": "Manœuvre régleur", "effectif": 2}],
        "ressources": ["Pelle hydraulique 20 tonnes", "2 Camions bennes 15 m³"]
    },
    {
        "code_wbs": "03.03",
        "nom": "Ferraillage des radiers et massifs d'ancrage en béton armé",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "tonne acier (t)",
        "description": "Façonnage et pose des armatures en acier haute adhérence FeE500",
        "normes_associees": "BAEL 91 / Eurocode 2 / ACI 318",
        "rendement_valeur": 1.2,
        "rendement_unite": "t/jour/équipe",
        "min_plausible": 0.4,
        "max_plausible": 3.0,
        "source": "Fédération Nationale du Bâtiment & Travaux Publics",
        "equipe": [{"role": "Chef ferrailleur", "effectif": 1}, {"role": "Ferrailleurs qualifiés", "effectif": 4}, {"role": "Aide ferrailleur", "effectif": 2}],
        "ressources": ["Cintreuse électrique", "Coupe-boulons hydraulique", "Grue auxiliaire"]
    },
    {
        "code_wbs": "03.04",
        "nom": "Coffrage et coulage du béton armé pour massifs d'équipements lourds",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "m³ béton",
        "description": "Pose du coffrage métallique/bois, pose des tiges d'ancrage et coulage béton C30/37 vibré",
        "normes_associees": "Eurocode 2 / ACI 318 / NF EN 206",
        "rendement_valeur": 25.0,
        "rendement_unite": "m³/jour/équipe",
        "min_plausible": 8.0,
        "max_plausible": 60.0,
        "source": "Standards Génie Civil Oil & Gas",
        "equipe": [{"role": "Chef d'équipe béton", "effectif": 1}, {"role": "Coffreurs-boiseurs", "effectif": 3}, {"role": "Maçons vibrateurs", "effectif": 3}, {"role": "Topographe pour tiges d'ancrage", "effectif": 1}],
        "ressources": ["Camion toupie", "Pompe à béton 36m", "Aiguilles vibrantes haute fréquence"]
    },
    {
        "code_wbs": "03.05",
        "nom": "Construction de caniveaux techniques et cuvettes de rétention hydrocarbures",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "ml",
        "description": "Réalisation de caniveaux étanches avec enduit résistant aux hydrocarbures et caillebotis",
        "normes_associees": "NF P98-350 / Arrêté ministériel rétention",
        "rendement_valeur": 12.0,
        "rendement_unite": "ml/jour/équipe",
        "min_plausible": 4.0,
        "max_plausible": 25.0,
        "source": "Guide de Conception Sécurité Rétention Oil & Gas",
        "equipe": [{"role": "Chef d'équipe maçonnerie", "effectif": 1}, {"role": "Maçons qualifiés", "effectif": 3}, {"role": "Manœuvres", "effectif": 2}],
        "ressources": ["Bétonnière mobile", "Vibreur de surface", "Échafaudage de sécurité"]
    },

    # ── 04. STRUCTURES MÉTALLIQUES & CHARPENTE ──
    {
        "code_wbs": "04.01",
        "nom": "Préfabrication des profilés de charpente en atelier (Découpe, perçage, goussets)",
        "discipline": "04_STRUCTURE_CHARPENTE",
        "unite_oeuvre": "tonne acier (t)",
        "description": "Préfabrication des poteaux, poutres HEA/HEB/IPE et contreventements en atelier",
        "normes_associees": "EN 1090-2 EXC3 / AISC 360",
        "rendement_valeur": 1.5,
        "rendement_unite": "t/jour/équipe",
        "min_plausible": 0.5,
        "max_plausible": 4.0,
        "source": "Standards Construction Métallique Industrielle",
        "equipe": [{"role": "Chef d'atelier charpente", "effectif": 1}, {"role": "Chaudronniers métalliers", "effectif": 3}, {"role": "Soudeurs qualifiés EN ISO 9606-1", "effectif": 2}],
        "ressources": ["Banc d'oxycoupage CNC", "Perceuse magnétique", "Postes à souder MAG 400A"]
    },
    {
        "code_wbs": "04.02",
        "nom": "Montage et érection de la charpente métallique / Pipe-Rack sur site",
        "discipline": "04_STRUCTURE_CHARPENTE",
        "unite_oeuvre": "tonne acier (t)",
        "description": "Levage à la grue, positionnement, calage et boulonnage précontraint HR 8.8/10.9",
        "normes_associees": "EN 1090-2 / AISC 360",
        "rendement_valeur": 2.0,
        "rendement_unite": "t/jour/équipe",
        "min_plausible": 0.8,
        "max_plausible": 5.0,
        "source": "Guide de Montage Charpente Lourde EPC",
        "equipe": [{"role": "Chef monteur charpente", "effectif": 1}, {"role": "Monteurs-gréeurs (Riggers)", "effectif": 4}, {"role": "Grutier qualifié", "effectif": 1}, {"role": "Topographe alignement", "effectif": 1}],
        "ressources": ["Grue télescopique 50t", "Nacelle élévatrice 20m", "Clé dynamométrique étalonnée"]
    },
    {
        "code_wbs": "04.03",
        "nom": "Pose des planchers caillebotis, garde-corps et échelles à crinoline",
        "discipline": "04_STRUCTURE_CHARPENTE",
        "unite_oeuvre": "m²",
        "description": "Fixation des panneaux caillebotis galvanisés et installation des garde-corps de sécurité",
        "normes_associees": "ISO 14122-1 à 4 / OSHA 1910",
        "rendement_valeur": 35.0,
        "rendement_unite": "m²/jour/équipe",
        "min_plausible": 15.0,
        "max_plausible": 80.0,
        "source": "Référentiel Sécurité Accès Postes de Travail",
        "equipe": [{"role": "Monteur métallier", "effectif": 2}, {"role": "Aide monteur", "effectif": 2}],
        "ressources": ["Visseuses à chocs", "Crapauds de fixation galvanisés", "Harnais de sécurité"]
    },
    {
        "code_wbs": "04.04",
        "nom": "Application de la protection passive contre l'incendie (Fireproofing)",
        "discipline": "04_STRUCTURE_CHARPENTE",
        "unite_oeuvre": "m² surface profilé",
        "description": "Application d'enduit projeté ou peinture intumescente époxy pour résistance au feu 2h",
        "normes_associees": "UL 1709 / ISO 22899 (Feu d'hydrocarbures)",
        "rendement_valeur": 40.0,
        "rendement_unite": "m²/jour/équipe",
        "min_plausible": 15.0,
        "max_plausible": 90.0,
        "source": "Spécification Protection Incendie Sonatrach",
        "equipe": [{"role": "Applicateur qualifié Fireproofing", "effectif": 2}, {"role": "Manœuvre préparateur", "effectif": 2}],
        "ressources": ["Machine à projeter haute pression", "Échafaudage de confinement", "Jauge d'épaisseur film sec"]
    },

    # ── 05. TUYAUTERIE — PRÉFABRICATION EN ATELIER ──
    {
        "code_wbs": "05.01",
        "nom": "Découpe, traçage et chanfreinage des tubes acier carbone / inox",
        "discipline": "05_TUYAUTERIE_PREFABRICATION",
        "unite_oeuvre": "coupe/chanfrein",
        "description": "Découpe mécanique/plasma et préparation du chanfrein en V selon WPS",
        "normes_associees": "ASME B31.3 / ASME B16.25",
        "rendement_valeur": 18.0,
        "rendement_unite": "chanfreins/jour/équipe",
        "min_plausible": 6.0,
        "max_plausible": 40.0,
        "source": "Atelier Tuyauterie Industrielle GCB / Bonatti",
        "equipe": [{"role": "Tuyauteur qualifié", "effectif": 1}, {"role": "Aide tuyauteur", "effectif": 1}],
        "ressources": ["Chanfreineuse orbitale", "Scie à ruban industrielle", "Meuleuse pneumatique"]
    },
    {
        "code_wbs": "05.02",
        "nom": "Assemblage et pointage des spools de tuyauterie (Fit-up)",
        "discipline": "05_TUYAUTERIE_PREFABRICATION",
        "unite_oeuvre": "joint équivalent (DI)",
        "description": "Alignement, contrôle du jeu à la racine (gap) et pointage TIG selon plan isométrique",
        "normes_associees": "ASME B31.3 / ASME IX",
        "rendement_valeur": 30.0,
        "rendement_unite": "DI (Diamètre-Inch)/jour/équipe",
        "min_plausible": 10.0,
        "max_plausible": 70.0,
        "source": "Méthodes Tuyauterie EPC Oil & Gas (Métrique Diamètre-Pouce)",
        "equipe": [{"role": "Tuyauteur assembleur senior", "effectif": 1}, {"role": "Soudeur pointeur TIG", "effectif": 1}, {"role": "Aide tuyauteur", "effectif": 1}],
        "ressources": ["Positionneur rotatif de soudage", "Gabarits d'alignement externes/internes"]
    },
    {
        "code_wbs": "05.03",
        "nom": "Soudage de tuyauterie en atelier (Procédé TIG passe de racine + Remplissage SMAW/FCAW)",
        "discipline": "05_TUYAUTERIE_PREFABRICATION",
        "unite_oeuvre": "DI (Diamètre-Pouce soudé)",
        "description": "Soudage de bout en bout selon WPS qualifiée par soudeur homologué ASME IX",
        "normes_associees": "ASME IX / ASME B31.3 / API 1104",
        "rendement_valeur": 24.0,
        "rendement_unite": "DI/jour/soudeur",
        "min_plausible": 8.0,
        "max_plausible": 55.0,
        "source": "Guide de Rendement Soudage Oil & Gas (1 DI = 1 pouce de diamètre soudé en épaisseur standard)",
        "equipe": [{"role": "Soudeur qualifié ASME IX (6G)", "effectif": 1}, {"role": "Meuleur / Aide soudeur", "effectif": 1}],
        "ressources": ["Poste à souder TIG/MIG inverter", "Étuve à électrodes", "Pyromètre température préchauffage"]
    },
    {
        "code_wbs": "05.04",
        "nom": "Contrôle Non Destructif CND des soudures atelier (Radiographie RT / Ultrasons UT)",
        "discipline": "05_TUYAUTERIE_PREFABRICATION",
        "unite_oeuvre": "joint radiographié",
        "description": "Tir radio gammagraphie / rayons X ou contrôle TOFD/PAUT selon classe de tuyauterie",
        "normes_associees": "ASME V Art. 2 / ASME B31.3 Table 341.3.2 / ISO 17636",
        "rendement_valeur": 15.0,
        "rendement_unite": "joints/nuit/équipe CND",
        "min_plausible": 5.0,
        "max_plausible": 35.0,
        "source": "Procédures CND Organismes Habilités (ALGERAC / COFREND)",
        "equipe": [{"role": "Opérateur CND certifié Niveau II (RT/UT)", "effectif": 1}, {"role": "Agent de radioprotection", "effectif": 1}],
        "ressources": ["Source gammagraphie Se75/Ir192 / Appareil RX", "Bunker de tir ou balisage zone de nuit"]
    },
    {
        "code_wbs": "05.05",
        "nom": "Traitement thermique après soudage en atelier (PWHT)",
        "discipline": "05_TUYAUTERIE_PREFABRICATION",
        "unite_oeuvre": "joint traité",
        "description": "Préchauffage et détente thermique contrôlée par résistances électriques avec enregistreur",
        "normes_associees": "ASME B31.3 Table 331.1.1 / ASME VIII",
        "rendement_valeur": 4.0,
        "rendement_unite": "joints/jour/équipe",
        "min_plausible": 1.0,
        "max_plausible": 8.0,
        "source": "Spécification Métallurgique Soudage Tuyauteries Épaisses",
        "equipe": [{"role": "Technicien PWHT qualifié", "effectif": 1}, {"role": "Électricien d'intervention", "effectif": 1}],
        "ressources": ["Centrale de chauffe par résistance 6/12 voies", "Enregistreur graphique de température", "Thermocouples K"]
    },

    # ── 06. TUYAUTERIE — MONTAGE & ESSAIS SUR SITE ──
    {
        "code_wbs": "06.01",
        "nom": "Érection et pose des spools de tuyauterie sur pipe-rack / charpente",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "ml de tuyauterie",
        "description": "Levage, manutention et positionnement des spools préfabriqués sur leurs supports",
        "normes_associees": "ASME B31.3 / MSS SP-58",
        "rendement_valeur": 25.0,
        "rendement_unite": "ml/jour/équipe",
        "min_plausible": 8.0,
        "max_plausible": 60.0,
        "source": "Standards Chantier Montage Tuyauterie EPC",
        "equipe": [{"role": "Chef d'équipe tuyauteur site", "effectif": 1}, {"role": "Tuyauteurs monteurs", "effectif": 2}, {"role": "Gréeurs riggers", "effectif": 2}, {"role": "Grutier", "effectif": 1}],
        "ressources": ["Grue mobile 35t", "Palans à chaîne / Tirfor", "Échafaudage de montage"]
    },
    {
        "code_wbs": "06.02",
        "nom": "Soudage des joints de position sur site (Golden Welds / Tie-in)",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "DI (Diamètre-Pouce)",
        "description": "Soudage en position difficile 6G sur pipe-rack avec protection au vent",
        "normes_associees": "ASME IX / ASME B31.3 / API 1104",
        "rendement_valeur": 14.0,
        "rendement_unite": "DI/jour/soudeur",
        "min_plausible": 4.0,
        "max_plausible": 30.0,
        "source": "Rendements Chantier Site Pétrolier",
        "equipe": [{"role": "Soudeur haute qualification 6G", "effectif": 1}, {"role": "Aide tuyauteur / Meuleur", "effectif": 1}],
        "ressources": ["Poste de soudage autonome diesel 400A", "Tente de soudage coupe-vent", "Extracteur de fumées"]
    },
    {
        "code_wbs": "06.03",
        "nom": "Installation de la robinetterie industrielle (Vannes manuelles, clapets, filtres)",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "unité vanne (u)",
        "description": "Montage des vannes à brides avec joints spiralés et serrage au couple contrôlé",
        "normes_associees": "ASME B16.5 / ASME B16.34 / API 6D",
        "rendement_valeur": 6.0,
        "rendement_unite": "vannes/jour/équipe",
        "min_plausible": 2.0,
        "max_plausible": 15.0,
        "source": "Pratiques Mécaniques Robinetterie Oil & Gas",
        "equipe": [{"role": "Tuyauteur mécanicien", "effectif": 2}, {"role": "Aide monteur", "effectif": 1}],
        "ressources": ["Clé dynamométrique étalonnée", "Clé hydraulique pour gros diamètres > DN300", "Palans légers"]
    },
    {
        "code_wbs": "06.04",
        "nom": "Montage et réglage des supports de tuyauterie (Supports fixes, guides, boîtes à ressort)",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "support (u)",
        "description": "Installation des colliers, berceaux, patins téflon et déblocage des ressorts tarés",
        "normes_associees": "MSS SP-58 / MSS SP-69",
        "rendement_valeur": 8.0,
        "rendement_unite": "supports/jour/équipe",
        "min_plausible": 3.0,
        "max_plausible": 20.0,
        "source": "Référentiel Supportage Tuyauterie",
        "equipe": [{"role": "Tuyauteur supportiste", "effectif": 1}, {"role": "Soudeur charpente", "effectif": 1}, {"role": "Aide monteur", "effectif": 1}],
        "ressources": ["Poste à souder portatif", "Niveau optique de précision"]
    },
    {
        "code_wbs": "06.05",
        "nom": "Épreuve hydrostatique de tuyauterie sur site (Hydrotest à 1.5x PMA)",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "boucle / circuit hydrotest",
        "description": "Remplissage eau filtrée, mise en pression par paliers, maintien réglementaire et vidange",
        "normes_associees": "ASME B31.3 Para 345 / Décret 21-261 Art. 21 / P-CTE-1 ARH",
        "rendement_valeur": 0.5,
        "rendement_unite": "circuit/jour/équipe",
        "min_plausible": 0.2,
        "max_plausible": 1.0,
        "source": "Procédure Officielle d'Épreuve Hydrostatique ARH P-CTE-1",
        "equipe": [{"role": "Superviseur d'épreuve hydrostatique", "effectif": 1}, {"role": "Opérateurs de pompage haute pression", "effectif": 2}, {"role": "Inspecteur QA/QC TPI ARH", "effectif": 1}],
        "ressources": ["Pompe d'épreuve haute pression", "Enregistreur de pression/température étalonné (Barton)", "Manomètres certifiés avec certificat 3.1"]
    },
    {
        "code_wbs": "06.06",
        "nom": "Séchage de la tuyauterie à l'air sec déshuilé et inertage à l'azote N2",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "circuit de tuyauterie",
        "description": "Chasse à l'air sec, contrôle du point de rosée (<-40°C) et pressurisation à l'azote à 0.5 bar",
        "normes_associees": "Spécification Sonatrach Séchage & Inertage",
        "rendement_valeur": 1.0,
        "rendement_unite": "circuit/jour/équipe",
        "min_plausible": 0.3,
        "max_plausible": 2.0,
        "source": "Guide Précommissioning Lignes Gaz",
        "equipe": [{"role": "Technicien azote / séchage", "effectif": 1}, {"role": "Opérateur compresseur", "effectif": 1}],
        "ressources": ["Compresseur d'air 1500 m³/h avec sécheur adsorption", "Cadre de bouteilles azote / Cuve N2 liquide"]
    },

    # ── 07. ÉQUIPEMENTS STATIQUES ──
    {
        "code_wbs": "07.01",
        "nom": "Ripage, mise en place et ancrage de skids de procédé préfabriqués",
        "discipline": "07_EQUIPEMENTS_STATIQUES",
        "unite_oeuvre": "skid (u)",
        "description": "Déchargement lourd, ripage sur rouleurs, réglage altimétrique et serrage d'ancrage",
        "normes_associees": "API RP 686 / ASME VIII",
        "rendement_valeur": 0.5,
        "rendement_unite": "skid/jour/équipe",
        "min_plausible": 0.1,
        "max_plausible": 1.0,
        "source": "Standards Installation Skids Processus EPC",
        "equipe": [{"role": "Chef de manœuvre levage lourd", "effectif": 1}, {"role": "Mécaniciens monteurs", "effectif": 3}, {"role": "Gréeurs spécialisés", "effectif": 2}, {"role": "Conducteur de grue 150t", "effectif": 1}],
        "ressources": ["Grue mobile 150 tonnes", "Crics hydrauliques 50t & rouleurs de ripage", "Cales d'épaisseur en acier inox"]
    },
    {
        "code_wbs": "07.02",
        "nom": "Levage et érection de colonne verticale / séparateur de procédé",
        "discipline": "07_EQUIPEMENTS_STATIQUES",
        "unite_oeuvre": "colonne / ballon vertical",
        "description": "Levage tandem à deux grues, verticalisation, mise sur massif et scellement d'ancrage",
        "normes_associees": "ASME VIII Div. 1/2 / CODAP",
        "rendement_valeur": 0.33,
        "rendement_unite": "colonne/jour/équipe",
        "min_plausible": 0.1,
        "max_plausible": 0.5,
        "source": "Procédures Levage Lourd (Heavy Lift Protocol)",
        "equipe": [{"role": "Superviseur Heavy Lift", "effectif": 1}, {"role": "Grutier principal (Grue 250t)", "effectif": 1}, {"role": "Grutier de queue (Grue 100t)", "effectif": 1}, {"role": "Équipe de gréeurs qualifiés", "effectif": 4}],
        "ressources": ["Grue principale 250t", "Grue de retenue 100t", "Élingues câbles tressés haute résistance certifiées"]
    },
    {
        "code_wbs": "07.03",
        "nom": "Installation des internes de colonnes et séparateurs (Plateaux, dévésiculeurs, garnissage)",
        "discipline": "07_EQUIPEMENTS_STATIQUES",
        "unite_oeuvre": "plateau / étage d'internes",
        "description": "Montage soigné des plateaux à clapets, distributeurs de liquide et matelas dévésiculeurs inox",
        "normes_associees": "ASME VIII / Spécifications Fabricant Sulzer/Koch-Glitsch",
        "rendement_valeur": 2.0,
        "rendement_unite": "plateaux/jour/équipe",
        "min_plausible": 0.5,
        "max_plausible": 5.0,
        "source": "Manuels de Montage Internes Colonnes",
        "equipe": [{"role": "Mécanicien chaudronnier espace confiné", "effectif": 2}, {"role": "Surveillant trou d'homme sécurité", "effectif": 1}, {"role": "Aide monteur extérieur", "effectif": 1}],
        "ressources": ["Ventilateur extracteur ATEX", "Éclairage basse tension 24V sécurisé", "Clé dynamométrique calibrée"]
    },
    {
        "code_wbs": "07.04",
        "nom": "Préfabrication et soudage du fond et de la robe de bac de stockage pétrolier API 650",
        "discipline": "07_EQUIPEMENTS_STATIQUES",
        "unite_oeuvre": "tonne acier (t) ou virole",
        "description": "Roulage tôles, pose tôles de fond avec cordon d'angle, soudage viroles robe par arcs submergés SAW",
        "normes_associees": "API 650 / ASME IX",
        "rendement_valeur": 1.8,
        "rendement_unite": "t/jour/équipe bacs",
        "min_plausible": 0.6,
        "max_plausible": 4.5,
        "source": "Norme API Standard 650 (Welded Tanks for Oil Storage)",
        "equipe": [{"role": "Chef de chantier bacs", "effectif": 1}, {"role": "Chaudronniers monteurs de viroles", "effectif": 3}, {"role": "Soudeurs automatiques SAW / Manuels", "effectif": 3}, {"role": "Opérateur boîte à vide (Vacuum Box)", "effectif": 1}],
        "ressources": ["Chariot de soudage automatique circonférentiel SAW", "Tracteur de serrage viroles", "Boîte à vide d'étanchéité fond"]
    },
    {
        "code_wbs": "07.05",
        "nom": "Montage du toit flottant/fixe et accessoires de bac de stockage API 650",
        "discipline": "07_EQUIPEMENTS_STATIQUES",
        "unite_oeuvre": "toit de bac",
        "description": "Assemblage charpente de toit, pontons, joints d'étanchéité périphériques et escalier hélicoïdal",
        "normes_associees": "API 650 Appendix C/E",
        "rendement_valeur": 0.05,
        "rendement_unite": "toit/jour/équipe (20 jours par toit)",
        "min_plausible": 0.02,
        "max_plausible": 0.1,
        "source": "Guide de Construction Bacs Pétroliers",
        "equipe": [{"role": "Chef d'équipe charpente bacs", "effectif": 1}, {"role": "Chaudronniers monteurs", "effectif": 4}, {"role": "Soudeurs qualifiés", "effectif": 2}, {"role": "Grutier", "effectif": 1}],
        "ressources": ["Grue mobile 60t", "Poteaux d'étaiement provisoires de toit", "Postes à souder MAG"]
    },

    # ── 08. ÉQUIPEMENTS DYNAMIQUES (MACHINES TOURNANTES) ──
    {
        "code_wbs": "08.01",
        "nom": "Implantation, calage et scellement au mortier sans retrait de pompe centrifuge API 610",
        "discipline": "08_EQUIPEMENTS_DYNAMIQUES",
        "unite_oeuvre": "groupe motopompe (u)",
        "description": "Pose du socle skid, nivellement au comparateur, coulage coulis ciment/époxy sous châssis",
        "normes_associees": "API 610 / API RP 686 Chapter 5",
        "rendement_valeur": 0.5,
        "rendement_unite": "groupe/jour/équipe",
        "min_plausible": 0.2,
        "max_plausible": 1.0,
        "source": "Pratiques Recommandées API RP 686 (Machinery Installation)",
        "equipe": [{"role": "Mécanicien machines tournantes senior", "effectif": 1}, {"role": "Mécanicien ajusteur", "effectif": 1}, {"role": "Maçon scelleur", "effectif": 1}],
        "ressources": ["Mortier de scellement sans retrait haute résistance (SikaGrout)", "Comparateurs centésimaux", "Niveau de précision 0.02 mm/m"]
    },
    {
        "code_wbs": "08.02",
        "nom": "Lignage laser précis de l'accouplement moteur-pompe / compresseur (Cold Alignment)",
        "discipline": "08_EQUIPEMENTS_DYNAMIQUES",
        "unite_oeuvre": "accouplement (u)",
        "description": "Contrôle faux-rond, pied boiteux (soft foot) et alignement angulaire/parallèle au laser (<0.05 mm)",
        "normes_associees": "API RP 686 Chapter 7 / ISO 10816",
        "rendement_valeur": 1.5,
        "rendement_unite": "lignages/jour/spécialiste",
        "min_plausible": 0.5,
        "max_plausible": 3.0,
        "source": "Standards Lignage Laser Machines Tournantes",
        "equipe": [{"role": "Spécialiste vibration & lignage laser", "effectif": 1}, {"role": "Mécanicien ajusteur", "effectif": 1}],
        "ressources": ["Système de lignage laser optique (Prüftechnik Rotalign / Easy-Laser)", "Jeu de cales pré-découpées inox 316L"]
    },
    {
        "code_wbs": "08.03",
        "nom": "Raccordement des tuyauteries sur buses machines sans contrainte mécanique (Pipe Strain Check)",
        "discipline": "08_EQUIPEMENTS_DYNAMIQUES",
        "unite_oeuvre": "buse de raccordement",
        "description": "Vérification au comparateur qu'aucun effort de tuyauterie n'est transmis aux brides machine (<0.05 mm)",
        "normes_associees": "API RP 686 Chapter 6 / API 610",
        "rendement_valeur": 2.0,
        "rendement_unite": "buses/jour/équipe",
        "min_plausible": 0.5,
        "max_plausible": 4.0,
        "source": "Règles d'Installation Tuyauterie sur Machines Sensibles",
        "equipe": [{"role": "Tuyauteur haute précision", "effectif": 1}, {"role": "Mécanicien machines tournantes", "effectif": 1}],
        "ressources": ["Comparateurs à cadran magnétiques", "Clé dynamométrique"]
    },
    {
        "code_wbs": "08.04",
        "nom": "Flushing et nettoyage chimique du circuit d'huile de lubrification (Lube Oil Flushing)",
        "discipline": "08_EQUIPEMENTS_DYNAMIQUES",
        "unite_oeuvre": "circuit d'huile lubrification",
        "description": "Circulation d'huile avec chocs thermiques et contrôle de contamination selon ISO 4406 (Classe 14/12/9)",
        "normes_associees": "API 614 / ISO 4406 / ASTM D6439",
        "rendement_valeur": 0.25,
        "rendement_unite": "circuit/jour/équipe (4 jours par circuit)",
        "min_plausible": 0.1,
        "max_plausible": 0.5,
        "source": "Spécification Systèmes de Graissage API 614",
        "equipe": [{"role": "Spécialiste lubrification & filtration", "effectif": 1}, {"role": "Opérateur de rinçage", "effectif": 1}],
        "ressources": ["Groupe de flushing temporaire haut débit", "Filtres absolus 3 microns", "Compteur de particules laser portable"]
    },

    # ── 09. ÉLECTRICITÉ HT / BT ──
    {
        "code_wbs": "09.01",
        "nom": "Pose des chemins de câbles métalliques perforés / échelles à câbles",
        "discipline": "09_ELECTRICITE_HT_BT",
        "unite_oeuvre": "ml chemin de câbles",
        "description": "Fixation des supports, pose des tronçons d'échelles galvanisées et mise à la terre",
        "normes_associees": "IEC 61537 / NF C 15-100",
        "rendement_valeur": 30.0,
        "rendement_unite": "ml/jour/équipe",
        "min_plausible": 10.0,
        "max_plausible": 60.0,
        "source": "Rendements Entreprises Électricité Industrielle (Spie / Cegelec)",
        "equipe": [{"role": "Chef d'équipe électricien", "effectif": 1}, {"role": "Électriciens monteurs", "effectif": 2}, {"role": "Aide électricien", "effectif": 1}],
        "ressources": ["Perforateur burineur", "Pince coupe-câbles", "Échafaudage roulant"]
    },
    {
        "code_wbs": "09.02",
        "nom": "Tirage de câbles de puissance armés Basse Tension (BT 0.4 kV)",
        "discipline": "09_ELECTRICITE_HT_BT",
        "unite_oeuvre": "ml câble tiré",
        "description": "Déroulage, passage sur chemins de câbles et fixation par colliers Colson/treillis",
        "normes_associees": "IEC 60502-1 / NF C 15-100",
        "rendement_valeur": 120.0,
        "rendement_unite": "ml/jour/équipe",
        "min_plausible": 40.0,
        "max_plausible": 250.0,
        "source": "Guide de Pose Câblage Industriel",
        "equipe": [{"role": "Chef d'équipe tirage", "effectif": 1}, {"role": "Électriciens câbleurs", "effectif": 3}, {"role": "Manœuvres tireurs de câble", "effectif": 2}],
        "ressources": ["Dérouleur de touret hydraulique", "Tire-câble à cabestan", "Chaussettes de tirage"]
    },
    {
        "code_wbs": "09.03",
        "nom": "Tirage de câbles de puissance Moyenne / Haute Tension armés (HT 5.5 kV à 30 kV)",
        "discipline": "09_ELECTRICITE_HT_BT",
        "unite_oeuvre": "ml câble HT",
        "description": "Tirage soigné avec contrôle du rayon de courbure et lubrifiant de tirage",
        "normes_associees": "IEC 60502-2 / IEEE 576",
        "rendement_valeur": 60.0,
        "rendement_unite": "ml/jour/équipe",
        "min_plausible": 20.0,
        "max_plausible": 120.0,
        "source": "Spécification Câblage HT Réseaux Pétroliers",
        "equipe": [{"role": "Électricien spécialiste Habilitation H2V", "effectif": 1}, {"role": "Électriciens monteurs", "effectif": 3}, {"role": "Manœuvres de tirage", "effectif": 3}],
        "ressources": ["Treuil de tirage motorisé avec dynamomètre enregistreur de tension", "Rouleaux de guidage de virage"]
    },
    {
        "code_wbs": "09.04",
        "nom": "Confection des têtes de câbles HT et raccordement aux cellules 30 kV / Transformateurs",
        "discipline": "09_ELECTRICITE_HT_BT",
        "unite_oeuvre": "tête de câble / extrémité HT",
        "description": "Dénudage semi-conducteur, pose cône déflecteur rétractable à froid et cosse à serrage",
        "normes_associees": "IEC 60071 / IEEE 48",
        "rendement_valeur": 2.0,
        "rendement_unite": "extrémités/jour/spécialiste HT",
        "min_plausible": 1.0,
        "max_plausible": 4.0,
        "source": "Manuel de Montage Accessoires HT Raychem / 3M",
        "equipe": [{"role": "Monteur jointoyeur certifié HT", "effectif": 1}, {"role": "Aide électricien habilité", "effectif": 1}],
        "ressources": ["Kit d'outillage dénudage semi-conducteur", "Lampe à souder gaz / Chalumeau à air chaud", "Presse à sertir hydraulique 130 kN"]
    },
    {
        "code_wbs": "09.05",
        "nom": "Raccordement des armoires TGBT, tableaux de contrôle moteurs (MCC) et variateurs VFD",
        "discipline": "09_ELECTRICITE_HT_BT",
        "unite_oeuvre": "armoire / départ moteur",
        "description": "Fixation mécanique des armoires, raccordement puissance, repérage et serrage au couple",
        "normes_associees": "IEC 61439-1/2 / NF C 15-100",
        "rendement_valeur": 3.0,
        "rendement_unite": "départs/jour/équipe",
        "min_plausible": 1.0,
        "max_plausible": 6.0,
        "source": "Standards Tableaux Électriques Basse Tension",
        "equipe": [{"role": "Électricien tableautier qualifié", "effectif": 1}, {"role": "Câbleur armoire", "effectif": 1}],
        "ressources": ["Tournevis dynamométrique", "Pince à sertir embouts", "Multimètre / Testeur d'isolement"]
    },
    {
        "code_wbs": "09.06",
        "nom": "Installation du réseau général de mise à la terre et protection foudre (Earth Network)",
        "discipline": "09_ELECTRICITE_HT_BT",
        "unite_oeuvre": "ml conducteur cuivre nu ou piquet",
        "description": "Pose du câblette cuivre nu 75/95 mm², piquets de terre et soudures aluminothermiques Cadweld",
        "normes_associees": "IEEE 80 / NF C 17-102 (Paratonnerres) / Décret 21-257",
        "rendement_valeur": 40.0,
        "rendement_unite": "ml/jour/équipe",
        "min_plausible": 15.0,
        "max_plausible": 80.0,
        "source": "Guide Sécurité des Réseaux de Terre Postes HT",
        "equipe": [{"role": "Électricien spécialiste mise à la terre", "effectif": 1}, {"role": "Soudeur Cadweld", "effectif": 1}, {"role": "Manœuvre fouille", "effectif": 1}],
        "ressources": ["Moules de soudure aluminothermique Cadweld", "Poudre de soudage", "Telluromètre de mesure de résistance de terre (<4 Ohms)"]
    },

    # ── 10. INSTRUMENTATION & AUTOMATISME (DCS/ESD/F&G) ──
    {
        "code_wbs": "10.01",
        "nom": "Pose et fixation des instruments de terrain (Transmetteurs PT, TT, FT, LT)",
        "discipline": "10_INSTRUMENTATION_AUTOMATISME",
        "unite_oeuvre": "instrument (u)",
        "description": "Montage sur potence 2\" (stanchion), orientation cadran et protection parasoleil",
        "normes_associees": "ISA 5.1 / IEC 60079 (ATEX)",
        "rendement_valeur": 4.0,
        "rendement_unite": "instruments/jour/équipe",
        "min_plausible": 1.5,
        "max_plausible": 8.0,
        "source": "Standards Instrumentation Pétrolière",
        "equipe": [{"role": "Instrumentiste de chantier", "effectif": 1}, {"role": "Aide instrumentiste", "effectif": 1}],
        "ressources": ["Support stanchion 2\" galvanisé", "Niveau à bulle", "Clés mixtes"]
    },
    {
        "code_wbs": "10.02",
        "nom": "Façonnage et raccordement de tubing instrumentation en acier inox SS316 (Impulse Lines)",
        "discipline": "10_INSTRUMENTATION_AUTOMATISME",
        "unite_oeuvre": "ml de tubing ou piquage",
        "description": "Cintrage à froid de tubes 1/2\" et 1/4\" SS316, raccords double bague Swagelok et manifolds 5 voies",
        "normes_associees": "ASME B31.3 Chapter X / Spécifications Swagelok",
        "rendement_valeur": 12.0,
        "rendement_unite": "ml/jour/tubiste qualifié",
        "min_plausible": 4.0,
        "max_plausible": 25.0,
        "source": "Manuel de Tubing Haute Pression Swagelok / Parker",
        "equipe": [{"role": "Tubiste certifié Swagelok / Parker", "effectif": 1}, {"role": "Aide tubiste", "effectif": 1}],
        "ressources": ["Cintreuse manuelle de précision 1/2\"", "Coupe-tube spécial inox", "Jauge de contrôle de serrage double bague"]
    },
    {
        "code_wbs": "10.03",
        "nom": "Installation et raccordement des vannes automatiques de régulation et sécurité (SDV/ESDV/MOV)",
        "discipline": "10_INSTRUMENTATION_AUTOMATISME",
        "unite_oeuvre": "vanne motorisée / actionnée",
        "description": "Montage vanne avec actionneur pneumatique/électrique, positionneur numérique et fin de course",
        "normes_associees": "IEC 61508 / IEC 61511 (SIL 2/3) / API 6D",
        "rendement_valeur": 2.0,
        "rendement_unite": "vannes/jour/équipe",
        "min_plausible": 0.5,
        "max_plausible": 4.0,
        "source": "Guide Automatisation & Vannes d'Arrêt d'Urgence",
        "equipe": [{"role": "Instrumentiste régleur", "effectif": 1}, {"role": "Mécanicien robinetier", "effectif": 1}, {"role": "Électricien contrôle", "effectif": 1}],
        "ressources": ["Générateur de signal HART 4-20mA", "Alimentation d'air comprimé portable 6 bar", "Valise de communication Emerson Field Communicator"]
    },
    {
        "code_wbs": "10.04",
        "nom": "Tirage et raccordement de câbles signaux blindés & bus de terrain (Fieldbus / Modbus / Câbles IS)",
        "discipline": "10_INSTRUMENTATION_AUTOMATISME",
        "unite_oeuvre": "ml câble signal",
        "description": "Tirage sous fourreau ou goulotte séparée des câbles de puissance (ségrégation CEM / Sécurité Intrinsèque)",
        "normes_associees": "IEC 60079-14 / IEC 61158",
        "rendement_valeur": 150.0,
        "rendement_unite": "ml/jour/équipe",
        "min_plausible": 50.0,
        "max_plausible": 300.0,
        "source": "Règles d'Installation Sécurité Intrinsèque & CEM",
        "equipe": [{"role": "Instrumentiste câbleur", "effectif": 2}, {"role": "Aide câbleur", "effectif": 1}],
        "ressources": ["Aiguille de tirage fibre de verre", "Presse-étoupes certifiés ATEX Ex d / Ex e / Ex i", "Pince à dénuder de précision"]
    },
    {
        "code_wbs": "10.05",
        "nom": "Installation des détecteurs de Feu et Gaz (F&G - Détecteurs flamme IR3, gaz inflammable CH4, toxique H2S)",
        "discipline": "10_INSTRUMENTATION_AUTOMATISME",
        "unite_oeuvre": "détecteur (u)",
        "description": "Positionnement selon plan de couverture 3D, câblage résistant au feu et test avec lampe de calibration",
        "normes_associees": "NFPA 72 / EN 54 / IEC 60079-29-1",
        "rendement_valeur": 5.0,
        "rendement_unite": "détecteurs/jour/équipe",
        "min_plausible": 2.0,
        "max_plausible": 10.0,
        "source": "Spécification Détection Feu & Gaz Sonatrach",
        "equipe": [{"role": "Technicien F&G qualifié", "effectif": 1}, {"role": "Aide électricien", "effectif": 1}],
        "ressources": ["Lampe test flamme ATEX", "Bouteille de gaz étalon avec kit de calibrage", "Échafaudage roulant"]
    },

    # ── 11. ISOLATION, CALORIFUGE & PEINTURE ──
    {
        "code_wbs": "11.01",
        "nom": "Préparation de surface par sablage abrasif / grenaillage Sa 2.5 sur site",
        "discipline": "11_ISOLATION_CALORIFUGE_PEINTURE",
        "unite_oeuvre": "m²",
        "description": "Décapage à blanc Sa 2.5 au garnet/silice avec contrôle de rugosité de 50 à 75 microns",
        "normes_associees": "ISO 8501-1 / SSPC-SP 10 / NACE No. 2",
        "rendement_valeur": 60.0,
        "rendement_unite": "m²/jour/équipe (buse)",
        "min_plausible": 20.0,
        "max_plausible": 120.0,
        "source": "Standards Traitement de Surface ACQPA / FROSIO",
        "equipe": [{"role": "Sableur qualifié", "effectif": 1}, {"role": "Opérateur compresseur / chargeur abrasif", "effectif": 1}, {"role": "Contrôleur FROSIO Niveau II", "effectif": 1}],
        "ressources": ["Sableuse 200L avec buse venturi", "Compresseur d'air 12000 L/min avec déshuileur", "Casque de sablage avec adduction d'air purifié", "Jauge de rugosité Testex"]
    },
    {
        "code_wbs": "11.02",
        "nom": "Application du système de peinture anticorrosion 3 couches (Primaire Zinc + Époxy + Polyuréthane C5-M)",
        "discipline": "11_ISOLATION_CALORIFUGE_PEINTURE",
        "unite_oeuvre": "m²",
        "description": "Application airless avec respect des temps de recouvrement et contrôle d'épaisseur film sec (DFT ~280µm)",
        "normes_associees": "ISO 12944 C5-M / ACQPA",
        "rendement_valeur": 80.0,
        "rendement_unite": "m²/jour/équipe",
        "min_plausible": 30.0,
        "max_plausible": 150.0,
        "source": "Systèmes Peinture Offshore & Raffinerie",
        "equipe": [{"role": "Peintre pistolet airless", "effectif": 1}, {"role": "Aide peintre préparateur", "effectif": 1}],
        "ressources": ["Pompe de peinture airless 60:1", "Jauge d'épaisseur magnétique Elcometer", "Peigne d'épaisseur film humide"]
    },
    {
        "code_wbs": "11.03",
        "nom": "Pose du calorifugeage thermique chaud (Laine de roche + Revêtement tôle aluminium)",
        "discipline": "11_ISOLATION_CALORIFUGE_PEINTURE",
        "unite_oeuvre": "m² ou ml de tuyauterie",
        "description": "Pose coquilles laine de roche haute densité, barrière pare-vapeur et tôle alu 0.8 mm rivetée",
        "normes_associees": "CINI 2.2 / ASTM C547",
        "rendement_valeur": 15.0,
        "rendement_unite": "ml/jour/équipe",
        "min_plausible": 5.0,
        "max_plausible": 30.0,
        "source": "Normes CINI (Comité d'Isolation Industrielle)",
        "equipe": [{"role": "Calorifugeur tôlier qualifié", "effectif": 2}, {"role": "Aide calorifugeur", "effectif": 1}],
        "ressources": ["Bordeuse moulureuse", "Cisaille à tôle électrique", "Pince à riveter aveugle"]
    },
    {
        "code_wbs": "11.04",
        "nom": "Installation du système de traçage électrique chauffant (Heat Tracing)",
        "discipline": "11_ISOLATION_CALORIFUGE_PEINTURE",
        "unite_oeuvre": "ml de ruban chauffant",
        "description": "Pose du ruban autorégulant sur tuyauterie avec ruban adhésif aluminium et raccordement boîtes ATEX",
        "normes_associees": "IEEE 515 / IEC 60079-30-1",
        "rendement_valeur": 45.0,
        "rendement_unite": "ml/jour/équipe",
        "min_plausible": 15.0,
        "max_plausible": 90.0,
        "source": "Spécification Raychem / Bartec Heat Tracing",
        "equipe": [{"role": "Électricien spécialiste traçage", "effectif": 1}, {"role": "Aide monteur", "effectif": 1}],
        "ressources": ["Ruban adhésif alu haute température", "Mégohmmètre de contrôle d'isolement (2500V)"]
    },

    # ── 12. PRÉCOMMISSIONING & CONTRÔLES D'INTÉGRITÉ ──
    {
        "code_wbs": "12.01",
        "nom": "Rinçage, flushing hydraulique et dégraissage chimique des lignes de tuyauterie",
        "discipline": "12_PRECOMMISSIONING_TESTS",
        "unite_oeuvre": "circuit de rinçage",
        "description": "Circulation d'eau sous haute vitesse (>3 m/s) pour évacuation des scories et poussières de soudage",
        "normes_associees": "API RP 14G / Spécifications Précom Sonatrach",
        "rendement_valeur": 1.0,
        "rendement_unite": "circuit/jour/équipe",
        "min_plausible": 0.3,
        "max_plausible": 3.0,
        "source": "Guide Précommissioning Tuyauterie Process",
        "equipe": [{"role": "Superviseur Précommissioning", "effectif": 1}, {"role": "Opérateurs de pompage", "effectif": 2}],
        "ressources": ["Pompe de flushing gros débit", "Bacs de filtration décantation", "Cibles de contrôle de propreté"]
    },
    {
        "code_wbs": "12.02",
        "nom": "Soufflage des tuyauteries à l'air comprimé / à la vapeur vive (Air/Steam Blowing)",
        "discipline": "12_PRECOMMISSIONING_TESTS",
        "unite_oeuvre": "ligne / boucle de soufflage",
        "description": "Dépressurisation brutale avec plaque cible miroir (Mirror Target) pour vérification de l'absence d'impacts",
        "normes_associees": "ASME B31.3 / ISO 13703",
        "rendement_valeur": 1.0,
        "rendement_unite": "ligne/jour/équipe",
        "min_plausible": 0.2,
        "max_plausible": 2.0,
        "source": "Procédures de Nettoyage Dynamique des Tuyauteries",
        "equipe": [{"role": "Ingénieur Précom Tuyauterie", "effectif": 1}, {"role": "Opérateurs vanne de décompression", "effectif": 2}],
        "ressources": ["Compresseur d'air haute pression 30 bar", "Vanne de décompression rapide", "Cibles en aluminium poli"]
    },
    {
        "code_wbs": "12.03",
        "nom": "Contrôles diélectriques et tests d'isolement des câbles et moteurs électriques",
        "discipline": "12_PRECOMMISSIONING_TESTS",
        "unite_oeuvre": "câble / moteur (u)",
        "description": "Mesures de résistance d'isolement au mégohmmètre 1000V/5000V et indice de polarisation PI/DAR",
        "normes_associees": "IEEE 43 / IEC 60034-27",
        "rendement_valeur": 8.0,
        "rendement_unite": "moteurs/jour/électricien",
        "min_plausible": 3.0,
        "max_plausible": 15.0,
        "source": "Standards Essais Électriques Précom",
        "equipe": [{"role": "Technicien essais électriques Habilité H2V", "effectif": 1}, {"role": "Aide technicien", "effectif": 1}],
        "ressources": ["Mégohmmètre numérique 5kV (Megger)", "Micro-ohmmètre de contact (Ductor)"]
    },
    {
        "code_wbs": "12.04",
        "nom": "Test de boucles instrumentales de bout en bout (Loop Checks 100% terrain vers DCS)",
        "discipline": "12_PRECOMMISSIONING_TESTS",
        "unite_oeuvre": "boucle instrumentale (Loop)",
        "description": "Injection 4-20mA sur l'instrument de terrain, vérification de l'affichage en salle de contrôle DCS",
        "normes_associees": "ISA 5.4 / IEC 62381",
        "rendement_valeur": 12.0,
        "rendement_unite": "boucles/jour/binôme",
        "min_plausible": 4.0,
        "max_plausible": 25.0,
        "source": "Guide de Réception Usine & Site IEC 62381",
        "equipe": [{"role": "Instrumentiste terrain", "effectif": 1}, {"role": "Ingénieur automaticien en salle de contrôle (DCS)", "effectif": 1}],
        "ressources": ["Talkie-walkie ATEX", "Calibrateur de boucle 4-20mA/HART Fluke 789"]
    },
    {
        "code_wbs": "12.05",
        "nom": "Vérification des logiques de sécurité ESD (Emergency Shutdown Matrix Test)",
        "discipline": "12_PRECOMMISSIONING_TESTS",
        "unite_oeuvre": "matrice cause à effet / nœud",
        "description": "Test complet de simulation des déclenchements de sécurité et fermeture des vannes ESDV (<2 sec)",
        "normes_associees": "IEC 61511 / IEC 61508 / API RP 14C",
        "rendement_valeur": 10.0,
        "rendement_unite": "causes-effets/jour/équipe",
        "min_plausible": 3.0,
        "max_plausible": 20.0,
        "source": "Spécification Systèmes Instrumentés de Sécurité (SIS)",
        "equipe": [{"role": "Ingénieur Sécurité des Systèmes (SIS/ESD)", "effectif": 1}, {"role": "Inspecteur QA/QC TPI", "effectif": 1}, {"role": "Opérateur terrain", "effectif": 1}],
        "ressources": ["Console d'ingénierie automate Triconex / Yokogawa ProSafe", "Chronomètre étalonné"]
    },
    {
        "code_wbs": "12.06",
        "nom": "Délivrance de l'attestation d'achèvement mécanique (Mechanical Completion Certificate - RFSU)",
        "discipline": "12_PRECOMMISSIONING_TESTS",
        "unite_oeuvre": "système / sous-système",
        "description": "Levée de la liste des réserves (Punch List Catégorie A) et signature du PV d'achèvement mécanique",
        "normes_associees": "ISO 29001 / Directives ARH",
        "rendement_valeur": 0.5,
        "rendement_unite": "sous-système/jour",
        "min_plausible": 0.1,
        "max_plausible": 1.0,
        "source": "Processus Contractuel EPC Ready For Start-Up (RFSU)",
        "equipe": [{"role": "Commissioning Manager", "effectif": 1}, {"role": "Chef de Projet Client", "effectif": 1}, {"role": "Inspecteur ARH", "effectif": 1}],
        "ressources": ["Dossier des fiches de tests Précom (Check-sheets)", "Logiciel de gestion de Punch List"]
    },

    
    # ── PIPELINE & CANALISATIONS DE TRANSPORT (CROSS-COUNTRY) ──
    {
        "code_wbs": "03.10",
        "nom": "Piste et emprise pipeline (Right of Way / RoW) : Débroussaillage, nivellement et aménagement",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "ml",
        "description": "Terrassement, décapage et aménagement de la piste de travail de 20 à 30m de large",
        "normes_associees": "API RP 1109 / Spécifications Pipeline Sonatrach",
        "rendement_valeur": 800.0,
        "rendement_unite": "ml/jour/équipe RoW",
        "min_plausible": 300.0,
        "max_plausible": 2000.0,
        "source": "Standards Chantier Pipeline Sonatrach / Spiecapag",
        "equipe": [{"role": "Chef d'équipe terrassement piste", "effectif": 1}, {"role": "Conducteur de Bulldozer D8", "effectif": 2}, {"role": "Conducteur de Niveleuse 140M", "effectif": 1}, {"role": "Manœuvres régleurs", "effectif": 2}],
        "ressources": ["2 Bulldozers CAT D8T", "Niveleuse CAT 140M", "Compacteur 15t"]
    },
    {
        "code_wbs": "03.11",
        "nom": "Excavation de la tranchée pipeline (Trenching en terrain meuble/semi-rocheux)",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "ml",
        "description": "Fouille en rigole à profondeur réglementaire (couverture min 1.0m au-dessus de la génératrice)",
        "normes_associees": "ASME B31.8 / Décret 21-257",
        "rendement_valeur": 500.0,
        "rendement_unite": "ml/jour/équipe tranchée",
        "min_plausible": 150.0,
        "max_plausible": 1200.0,
        "source": "Guide Travaux Canalisations Enterrées",
        "equipe": [{"role": "Chef d'équipe tranchée", "effectif": 1}, {"role": "Conducteurs de pelles 25t", "effectif": 2}, {"role": "Manœuvres de fond de fouille", "effectif": 2}],
        "ressources": ["2 Pelles hydrauliques 25t avec godet tranchée", "Brise-roche hydraulique (BRH)", "Trancheuse de sol si terrain meuble"]
    },
    {
        "code_wbs": "06.10",
        "nom": "Bardage et distribution des tubes le long de la piste (Stringing)",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "ml",
        "description": "Déchargement des camions et alignement des tubes de 12m sur cales en bois le long de la piste",
        "normes_associees": "API 5L / API RP 5L1 (Transport ferroviaire/routier de tubes)",
        "rendement_valeur": 1000.0,
        "rendement_unite": "ml/jour/équipe bardage",
        "min_plausible": 400.0,
        "max_plausible": 2500.0,
        "source": "Méthodes Construction Pipeline Saipem / Cosider",
        "equipe": [{"role": "Chef de manœuvre bardage", "effectif": 1}, {"role": "Grutier / Conducteur Sideboom", "effectif": 1}, {"role": "Gréeurs spécialisés tubes", "effectif": 3}, {"role": "Chauffeurs semi-remorques plateau", "effectif": 3}],
        "ressources": ["Grue mobile tout-terrain 30t / Sideboom à pinces à tubes (Vacuum lifter)", "Semis porte-tubes", "Cales en bois d'empilage"]
    },
    {
        "code_wbs": "06.11",
        "nom": "Cintrage à froid des tubes sur piste (Cold Bending)",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "coude cintré (u)",
        "description": "Conformation géométrique des tubes selon le profil altimétrique et les changements de direction",
        "normes_associees": "ASME B31.8 Para 841 / ASME B31.4",
        "rendement_valeur": 20.0,
        "rendement_unite": "coudes/jour/machine",
        "min_plausible": 5.0,
        "max_plausible": 40.0,
        "source": "Standards Cintrage Chantier",
        "equipe": [{"role": "Opérateur cintreuse hydraulique certifié", "effectif": 1}, {"role": "Topographe traceur d'angles", "effectif": 1}, {"role": "Aides opérateurs", "effectif": 2}],
        "ressources": ["Machine à cintrer hydraulique de chantier 6 à 24 pouces (CRC-Evans)", "Mandrin de cintrage interne (Mandrel)"]
    },
    {
        "code_wbs": "06.12",
        "nom": "Soudage en ligne du pipeline (Mainline Welding - Passe de racine + Remplissage + Finition)",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "joint soudé ou DI",
        "description": "Alignement par clamp interne/externe et soudage circonférentiel en continu selon WPS qualifiée",
        "normes_associees": "API 1104 / ASME IX / Décret 21-257",
        "rendement_valeur": 40.0,
        "rendement_unite": "joints/jour/spread soudage",
        "min_plausible": 15.0,
        "max_plausible": 80.0,
        "source": "Cadences Soudage Pipeline Oil & Gas",
        "equipe": [{"role": "Chef de brigade soudage pipeline", "effectif": 1}, {"role": "Soudeurs passes de racine (Cellulosique 6010 / TIG)", "effectif": 4}, {"role": "Soudeurs remplissage/finition (7018 / Fil fourré FCAW)", "effectif": 6}, {"role": "Meuleurs de chanfreins", "effectif": 4}],
        "ressources": ["Centrale de soudage mobile sur tracteur (Tractor-Welder 4 postes)", "Clamp pneumatique d'alignement interne", "Tentes de soudage coupe-vent"]
    },
    {
        "code_wbs": "05.10",
        "nom": "Contrôle Non Destructif CND 100% des soudures pipeline (Radiographie interne / AUT)",
        "discipline": "05_TUYAUTERIE_PREFABRICATION",
        "unite_oeuvre": "joint contrôlé",
        "description": "Tir radio par crawler interne panoramique à rayons X ou ultrasons automatisés AUT (Phased Array)",
        "normes_associees": "API 1104 Section 9 / ISO 17636 / ASME V",
        "rendement_valeur": 50.0,
        "rendement_unite": "joints/jour/équipe CND",
        "min_plausible": 20.0,
        "max_plausible": 100.0,
        "source": "Procédures CND Pipeline",
        "equipe": [{"role": "Opérateur radiologue Niveau II COFREND/ALGERAC", "effectif": 1}, {"role": "Opérateur Crawler RX", "effectif": 1}, {"role": "Agent de radioprotection", "effectif": 1}],
        "ressources": ["Crawler radiographique interne automatisé RX", "Laboratoire mobile de développement numérique de films / DDA"]
    },
    {
        "code_wbs": "11.10",
        "nom": "Revêtement anticorrosion des joints soudés sur piste (Field Joint Coating - Manchons thermo)",
        "discipline": "11_ISOLATION_CALORIFUGE_PEINTURE",
        "unite_oeuvre": "joint revêtu",
        "description": "Sablage Sa 2.5 au pistolet à manche fermé, préchauffage par induction et pose de manchons thermo-rétractables 3 couches",
        "normes_associees": "ISO 21809-3 / NACE SP0169",
        "rendement_valeur": 50.0,
        "rendement_unite": "joints/jour/équipe FJC",
        "min_plausible": 20.0,
        "max_plausible": 90.0,
        "source": "Guide d'Application Canusa-CPS / Raychem",
        "equipe": [{"role": "Applicateur qualifié manchons", "effectif": 2}, {"role": "Opérateur induction / sablage", "effectif": 2}, {"role": "Contrôleur qualité FROSIO", "effectif": 1}],
        "ressources": ["Centrale de chauffage par induction moyenne fréquence", "Sableuse mobile de joint", "Chalumeau à gaz large buse pour rétreint"]
    },
    {
        "code_wbs": "11.11",
        "nom": "Contrôle d'isolement au balai électrique haute tension (Holiday Detection à 25 kV)",
        "discipline": "11_ISOLATION_CALORIFUGE_PEINTURE",
        "unite_oeuvre": "ml",
        "description": "Passage du balai circulaire haute tension pour détection du moindre micro-pore ou blessure de revêtement",
        "normes_associees": "NACE RP0274 / ISO 21809",
        "rendement_valeur": 1500.0,
        "rendement_unite": "ml/jour/équipe",
        "min_plausible": 500.0,
        "max_plausible": 3000.0,
        "source": "Spécifications Contrôle Diélectrique Revêtement Pipeline",
        "equipe": [{"role": "Inspecteur Holiday Test certifié", "effectif": 1}, {"role": "Aide technicien réparateur de défauts", "effectif": 1}],
        "ressources": ["Porosimètre haute tension portable Elcometer 25kV", "Balais à ressort torique adaptés au diamètre"]
    },
    {
        "code_wbs": "06.13",
        "nom": "Descente de la colonne soudée en tranchée (Lowering-in avec Sidebooms)",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "ml",
        "description": "Levage synchronisé de la colonne continue par une flotte de tracteurs pose-tubes et dépose soignée sur lit de pose",
        "normes_associees": "ASME B31.8 / API RP 1109",
        "rendement_valeur": 800.0,
        "rendement_unite": "ml/jour/flotte sidebooms",
        "min_plausible": 300.0,
        "max_plausible": 1800.0,
        "source": "Standards Manutention Lourde Pipeline",
        "equipe": [{"role": "Superviseur de pose", "effectif": 1}, {"role": "Conducteurs de pose-tubes Sidebooms", "effectif": 4}, {"role": "Gréeurs élingueurs berceaux à rouleaux", "effectif": 4}],
        "ressources": ["4 Pose-tubes CAT 583 / 572 (Sidebooms)", "Berceaux de descente à rouleaux polyuréthane (Roller cradles)"]
    },
    {
        "code_wbs": "03.12",
        "nom": "Remblaiement de la tranchée, lit de sable protecteur et pose du grillage avertisseur",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "ml",
        "description": "Pose du lit de sable 15cm autour du tube, remblai compacté par couches et pose du grillage avertisseur",
        "normes_associees": "NF P98-331 / ASME B31.8",
        "rendement_valeur": 800.0,
        "rendement_unite": "ml/jour/équipe remblai",
        "min_plausible": 300.0,
        "max_plausible": 1800.0,
        "source": "Règles de Pose de Réseaux Enterrés",
        "equipe": [{"role": "Chef d'équipe remblaiement", "effectif": 1}, {"role": "Conducteur de Bulldozer pousseur", "effectif": 1}, {"role": "Conducteur de Chargeuse", "effectif": 1}, {"role": "Manœuvres dérouleurs de grillage", "effectif": 2}],
        "ressources": ["Bulldozer d'angle (Angle-dozer)", "Chargeuse sur pneus", "Cribleuse-ensableuse de tranchée (Padding machine)", "Grillage avertisseur jaune polypropylène"]
    },
    {
        "code_wbs": "06.14",
        "nom": "Traversées spéciales (Routes, oueds et voies ferrées par forage dirigé HDD ou fonçage)",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "traversée (u)",
        "description": "Forage horizontal dirigé sous voirie ou pose de fourreaux acier par fonçage hydraulique",
        "normes_associees": "DCA Guidelines (Directional Crossing) / API RP 1102",
        "rendement_valeur": 0.2,
        "rendement_unite": "traversée/jour/équipe HDD (5j par traversée)",
        "min_plausible": 0.05,
        "max_plausible": 0.5,
        "source": "Spécification Forages Dirigés Pipeline",
        "equipe": [{"role": "Superviseur forage dirigé HDD", "effectif": 1}, {"role": "Opérateur machine HDD", "effectif": 1}, {"role": "Technicien boues bentonitiques", "effectif": 1}, {"role": "Opérateurs guidage", "effectif": 2}],
        "ressources": ["Unité de forage dirigé HDD 45 tonnes de poussée", "Centrale de mélange de bentonite", "Système de guidage électromagnétique DigiTrak"]
    },
    {
        "code_wbs": "09.10",
        "nom": "Installation du système de Protection Cathodique (Poste à courant imposé, déversoir et prises de potentiel)",
        "discipline": "09_ELECTRICITE_HT_BT",
        "unite_oeuvre": "poste de protection cathodique (u)",
        "description": "Forage du puits anodique profond, raccordement transformateur-redresseur et bornes de mesure test",
        "normes_associees": "NACE SP0169 / ISO 15589-1 / Décret 21-257",
        "rendement_valeur": 0.25,
        "rendement_unite": "poste/jour/équipe (4j par poste)",
        "min_plausible": 0.1,
        "max_plausible": 0.5,
        "source": "Norme Internationale de Protection Cathodique des Canalisations Enterrées",
        "equipe": [{"role": "Ingénieur spécialiste Protection Cathodique NACE Niveau 2/3", "effectif": 1}, {"role": "Électricien d'installation", "effectif": 2}],
        "ressources": ["Foreuse de puits anodique 50m", "Transformateur-redresseur régulé en potentiel", "Électrodes de référence Cu/CuSO4"]
    },
    {
        "code_wbs": "06.15",
        "nom": "Installation et raccordement des gares de racleurs Départ/Arrivée (Scraper Traps & Tie-in)",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "gare de racleur (u)",
        "description": "Montage des tubes de lancement/réception avec portes à ouverture rapide (Quick Opening Closures) et vannes motorisées MOV",
        "normes_associees": "ASME VIII / ASME B31.8 / API 6D",
        "rendement_valeur": 0.1,
        "rendement_unite": "gare/jour/équipe (10j par gare)",
        "min_plausible": 0.05,
        "max_plausible": 0.25,
        "source": "Standards Gares de Racleurs Pipeline",
        "equipe": [{"role": "Chef de chantier tuyauterie station", "effectif": 1}, {"role": "Tuyauteurs monteurs", "effectif": 3}, {"role": "Soudeurs haute qualification 6G", "effectif": 2}, {"role": "Grutier 50t", "effectif": 1}],
        "ressources": ["Grue mobile 50t", "Portes d'accès rapide certifiées ASME", "Vannes sphériques API 6D à passage intégral (Full Bore)"]
    },
    {
        "code_wbs": "12.10",
        "nom": "Nettoyage préliminaire, séchage et passage du racleur gabarit à plaque (Gauging Pig Run)",
        "discipline": "12_PRECOMMISSIONING_TESTS",
        "unite_oeuvre": "section pipeline",
        "description": "Lancement du racleur à coupelles polyuréthane muni d'une plaque d'aluminium calibrée à 95% du diamètre intérieur",
        "normes_associees": "ASME B31.8 Section 841.3 / API 1163",
        "rendement_valeur": 1.0,
        "rendement_unite": "section/jour/équipe",
        "min_plausible": 0.5,
        "max_plausible": 2.0,
        "source": "Guide d'Inspection par Racleur Instrumenté",
        "equipe": [{"role": "Superviseur de raclage pipeline", "effectif": 1}, {"role": "Opérateurs lancement/réception", "effectif": 2}],
        "ressources": ["Compresseur d'air haute pression gros débit", "Racleurs de nettoyage à brosses", "Plaque gabarit en alu 95% D.I."]
    },
    {
        "code_wbs": "12.11",
        "nom": "Épreuve hydrostatique de section pipeline (Hydrotest à 1.5x ou 1.25x PMA pendant 24h)",
        "discipline": "12_PRECOMMISSIONING_TESTS",
        "unite_oeuvre": "section d'épreuve (u)",
        "description": "Remplissage eau douce traitée biocide, montée en pression par paliers, stabilisation thermique et maintien officiel 24h",
        "normes_associees": "ASME B31.8 / API 1104 / Décret 21-261 Art. 21 / Spécifications ARH",
        "rendement_valeur": 0.15,
        "rendement_unite": "section/jour/équipe (7j par section 10km)",
        "min_plausible": 0.05,
        "max_plausible": 0.3,
        "source": "Procédure d'Épreuve Hydrostatique Pipeline ARH",
        "equipe": [{"role": "Chef de mission épreuve hydrostatique", "effectif": 1}, {"role": "Opérateurs de pompage haute pression", "effectif": 2}, {"role": "Inspecteurs ARH / TPI habilités", "effectif": 2}],
        "ressources": ["Pompe de remplissage gros débit", "Pompe de pressurisation haute pression", "Balance manométrique à poids morts (Dead Weight Tester)", "Sondes de température de sol et d'eau étalonnées"]
    },
    {
        "code_wbs": "12.12",
        "nom": "Déshydratation, séchage à l'air sec (-40°C point de rosée) et inertage à l'azote N2",
        "discipline": "12_PRECOMMISSIONING_TESTS",
        "unite_oeuvre": "section séchée",
        "description": "Évacuation de l'eau résiduelle par racleurs mousse (Foam Pigs), balayage à l'air déshuilé et pressurisation azote à 0.5 bar",
        "normes_associees": "Spécification Sonatrach Séchage Canalisations Gaz",
        "rendement_valeur": 0.25,
        "rendement_unite": "section/jour/équipe (4j par section 10km)",
        "min_plausible": 0.1,
        "max_plausible": 0.5,
        "source": "Guide Précommissioning Pipeline Gaz",
        "equipe": [{"role": "Technicien séchage et azote", "effectif": 1}, {"role": "Opérateurs compresseur", "effectif": 2}],
        "ressources": ["Sécheur d'air par adsorption haute capacité", "Hygromètre de mesure du point de rosée certifié", "Racleurs mousse haute densité"]
    },
    {
        "code_wbs": "03.13",
        "nom": "Remise en état des lieux (Clean-up), reprofilage du terrain naturel et pose des bornes PK",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "ml",
        "description": "Nettoyage complet de l'emprise, rétablissement des écoulements naturels et pose des bornes kilométriques et balises aériennes",
        "normes_associees": "Directives Environnementales / Décret 21-257",
        "rendement_valeur": 1000.0,
        "rendement_unite": "ml/jour/équipe",
        "min_plausible": 400.0,
        "max_plausible": 2500.0,
        "source": "Règles de Réhabilitation Environnementale",
        "equipe": [{"role": "Chef d'équipe nivellement", "effectif": 1}, {"role": "Conducteur de Niveleuse", "effectif": 1}, {"role": "Maçons poseurs de bornes", "effectif": 2}],
        "ressources": ["Niveleuse", "Bornes kilométriques en béton armé", "Balises de survol aérien"]
    },

    
    # ── GÉNIE CIVIL BÂTIMENT & HANGARS INDUSTRIELS ──
    {
        "code_wbs": "03.20",
        "nom": "Fondations par semelles isolées, filantes et longrines béton armé pour hangar/bâtiment",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "m³ béton",
        "description": "Fouilles, ferraillage FeE500, coffrage et coulage du béton C25/30 pour fondations de bâtiment",
        "normes_associees": "Eurocode 2 / DTU 13.1 / BAEL 91",
        "rendement_valeur": 30.0,
        "rendement_unite": "m³/jour/équipe",
        "min_plausible": 10.0,
        "max_plausible": 70.0,
        "source": "Bordereau Bâtiment Industriel",
        "equipe": [{"role": "Chef d'équipe GC", "effectif": 1}, {"role": "Ferrailleurs", "effectif": 3}, {"role": "Coffreurs", "effectif": 3}, {"role": "Maçons", "effectif": 2}],
        "ressources": ["Toupie béton", "Pompe à béton 28m", "Aiguilles vibrantes"]
    },
    {
        "code_wbs": "03.21",
        "nom": "Dallage industriel en béton armé avec chape d'usure quartzée anti-poussière (5t/m²)",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "m²",
        "description": "Pose du film polyane, treillis soudé ST25, coulage béton C30/37 et surfaçage à l'hélicoptère",
        "normes_associees": "DTU 13.3 / NF EN 206",
        "rendement_valeur": 150.0,
        "rendement_unite": "m²/jour/équipe",
        "min_plausible": 50.0,
        "max_plausible": 350.0,
        "source": "Guide Dallages Industriels Haute Résistance",
        "equipe": [{"role": "Chef d'équipe dalleur", "effectif": 1}, {"role": "Régleurs béton", "effectif": 3}, {"role": "Talocheurs hélicoptère", "effectif": 2}],
        "ressources": ["Truelles mécaniques rotatives (Hélicoptères)", "Règle vibrante laser", "Saupoudreuse de quartz"]
    },
    {
        "code_wbs": "04.10",
        "nom": "Érection de la charpente métallique du hangar/shelter industriel et pose des pannes",
        "discipline": "04_STRUCTURE_CHARPENTE",
        "unite_oeuvre": "tonne acier (t)",
        "description": "Levage des poteaux, fermes, pannes Z/C et contreventements avec boulonnage précontraint HR",
        "normes_associees": "EN 1090-2 EXC2 / AISC 360",
        "rendement_valeur": 2.5,
        "rendement_unite": "t/jour/équipe",
        "min_plausible": 0.8,
        "max_plausible": 6.0,
        "source": "Standards Montage Hangars Métalliques",
        "equipe": [{"role": "Chef monteur charpente", "effectif": 1}, {"role": "Monteurs charpentiers", "effectif": 4}, {"role": "Grutier", "effectif": 1}],
        "ressources": ["Grue mobile 50t", "2 Nacelles élévatrices 16m", "Clés dynamométriques étalonnées"]
    },
    {
        "code_wbs": "04.11",
        "nom": "Pose du bardage double peau isolé (Laine de roche 80mm) et couverture bac acier",
        "discipline": "04_STRUCTURE_CHARPENTE",
        "unite_oeuvre": "m²",
        "description": "Installation plateau intérieur, isolation laine de roche incombustible A1 et tôle de finition extérieure laquée",
        "normes_associees": "DTU 40.35 / DTU 43.3",
        "rendement_valeur": 80.0,
        "rendement_unite": "m²/jour/équipe",
        "min_plausible": 30.0,
        "max_plausible": 150.0,
        "source": "Règles Professionnelles Enveloppe Métallique",
        "equipe": [{"role": "Poseurs bardage qualifiés", "effectif": 3}, {"role": "Aides poseurs", "effectif": 2}],
        "ressources": ["Visseuses électriques de bardage", "Nacelle ciseaux", "Lève-panneau ventouse"]
    },
    {
        "code_wbs": "04.12",
        "nom": "Installation, câblage et essais en charge du pont roulant d'atelier (10t / 20t)",
        "discipline": "04_STRUCTURE_CHARPENTE",
        "unite_oeuvre": "pont roulant (u)",
        "description": "Pose des chemins de roulement, assemblage de la poutre caisson, treuil de levage et essais avec charges tarées",
        "normes_associees": "FEM 1.001 / ISO 4301 / Réglementation Levage",
        "rendement_valeur": 0.2,
        "rendement_unite": "pont/jour/équipe (5j par pont)",
        "min_plausible": 0.1,
        "max_plausible": 0.5,
        "source": "Spécification Ponts Roulants Industriels",
        "equipe": [{"role": "Électromécanicien ponts roulants", "effectif": 1}, {"role": "Monteurs mécaniciens", "effectif": 2}, {"role": "Inspecteur TPI habilité épreuves de charge", "effectif": 1}],
        "ressources": ["Grue télescopique 60t", "Masses de charge d'épreuve certifiées 125% CMU"]
    },
    {
        "code_wbs": "03.23",
        "nom": "Maçonnerie en blocs banchés, murs coupe-feu REI 120 / REI 240 et étanchéité terrasse",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "m²",
        "description": "Élévation des murs résistants au feu pour salle de contrôle/sous-station électrique et étanchéité bicouche élastomère",
        "normes_associees": "Eurocode 6 / Arrêté Sécurité Incendie ERP-IGH",
        "rendement_valeur": 25.0,
        "rendement_unite": "m²/jour/équipe",
        "min_plausible": 10.0,
        "max_plausible": 50.0,
        "source": "Guide Sécurité Passive Incendie",
        "equipe": [{"role": "Chef maçon", "effectif": 1}, {"role": "Maçons qualifiés", "effectif": 3}, {"role": "Étanchéistes", "effectif": 2}],
        "ressources": ["Bétonnière", "Chalumeau étanchéité", "Échafaudage de pied"]
    },
    {
        "code_wbs": "03.24",
        "nom": "Pose du plancher technique surélevé antistatique 600x600 pour salle DCS / Substation",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "m²",
        "description": "Pose des vérins réglables, traverses métalliques et dalles haute densité revêtues vinyle conducteur (<10^6 Ohms)",
        "normes_associees": "NF EN 12825 / NF C 15-100",
        "rendement_valeur": 60.0,
        "rendement_unite": "m²/jour/équipe",
        "min_plausible": 20.0,
        "max_plausible": 120.0,
        "source": "Standards Salles Informatiques & Contrôle Commande",
        "equipe": [{"role": "Poseur spécialisé faux-plancher", "effectif": 2}, {"role": "Aide poseur", "effectif": 1}],
        "ressources": ["Niveau laser rotatif", "Ventouses de levage de dalles"]
    },
    {
        "code_wbs": "09.20",
        "nom": "Installation du système HVAC de pressurisation et filtration d'air H2S / Poussière pour salle de contrôle",
        "discipline": "09_ELECTRICITE_HT_BT",
        "unite_oeuvre": "centrale HVAC (u)",
        "description": "Pose du groupe de traitement d'air avec filtres charbon actif H2S, gaines d'air étanches et régulateurs de surpression (+50 Pa)",
        "normes_associees": "NFPA 496 (Pressurized Enclosures) / ISO 15138",
        "rendement_valeur": 0.2,
        "rendement_unite": "centrale/jour/équipe (5j par système)",
        "min_plausible": 0.1,
        "max_plausible": 0.5,
        "source": "Spécification HVAC Pressurisation Bâtiments Pétroliers",
        "equipe": [{"role": "Frigoriste climaticien qualifié", "effectif": 1}, {"role": "Tuyauteur aéraulique", "effectif": 2}, {"role": "Électricien régulation", "effectif": 1}],
        "ressources": ["Manomètre différentiel de pression d'ambiance", "Machine de découpe gaines"]
    },

    # ── PUITS & INSTALLATIONS DE SURFACE (WELLHEADS) ──
    {
        "code_wbs": "03.30",
        "nom": "Excavation et coulage de la cave de puits en béton armé étanche (Wellhead Cellar 3x3x2.5m)",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "cave de puits (u)",
        "description": "Fouille, cuvelage béton hydrofuge C30/37, caniveaux d'égouttement et pose caillebotis galvanisé",
        "normes_associees": "API RP 54 / Spécifications Forage Sonatrach",
        "rendement_valeur": 0.2,
        "rendement_unite": "cave/jour/équipe (5j par cave)",
        "min_plausible": 0.1,
        "max_plausible": 0.5,
        "source": "Guide Génie Civil Plate-forme de Puits",
        "equipe": [{"role": "Chef d'équipe génie civil puits", "effectif": 1}, {"role": "Coffreurs ferrailleurs", "effectif": 3}, {"role": "Maçons vibrateurs", "effectif": 2}],
        "ressources": ["Pelle mécanique 15t", "Bétonnière mobile", "Vibreur haute fréquence"]
    },
    {
        "code_wbs": "07.20",
        "nom": "Installation, alignement et épreuve de la Tête d'éruption / Christmas Tree API 6A (5000 / 10000 psi)",
        "discipline": "07_EQUIPEMENTS_STATIQUES",
        "unite_oeuvre": "arbre de Noël / tête de puits (u)",
        "description": "Dudgeonnage bride de tête, montage vannes maîtresses (Master Valves), vanne de purge (Swab Valve) et tests d'étanchéité",
        "normes_associees": "API Spec 6A / ISO 10423 / Décret 21-257",
        "rendement_valeur": 0.5,
        "rendement_unite": "tête/jour/équipe (2j par puits)",
        "min_plausible": 0.2,
        "max_plausible": 1.0,
        "source": "Manuel de Montage Têtes de Puits Cameron / FMC / Schlumberger",
        "equipe": [{"role": "Spécialiste Wellhead certifié API 6A", "effectif": 1}, {"role": "Mécaniciens haute pression", "effectif": 2}, {"role": "Grutier 35t", "effectif": 1}],
        "ressources": ["Grue mobile 35t", "Pompe hydraulique d'épreuve 15000 psi", "Clés de serrage hydrauliques dynamométriques"]
    },
    {
        "code_wbs": "10.30",
        "nom": "Installation et raccordement du panneau de sécurité tête de puits (Wellhead Control Panel - WHCP)",
        "discipline": "10_INSTRUMENTATION_AUTOMATISME",
        "unite_oeuvre": "panneau WHCP (u)",
        "description": "Pose du skid WHCP autonome, raccordement tubing inox 1/2 pouce vers vanne de sécurité de fond SSSV et de surface SSV, boucle fusible",
        "normes_associees": "API RP 14C / API RP 14B / IEC 61508 (SIL 3)",
        "rendement_valeur": 0.5,
        "rendement_unite": "WHCP/jour/équipe (2j par puits)",
        "min_plausible": 0.2,
        "max_plausible": 1.0,
        "source": "Spécification Systèmes de Sécurité Têtes de Puits",
        "equipe": [{"role": "Instrumentiste spécialiste WHCP", "effectif": 1}, {"role": "Tubiste certifié Swagelok", "effectif": 1}],
        "ressources": ["Cintreuse de tubing inox", "Groupe hydraulique de charge des accumulateurs azote (3000 psi)"]
    },
    {
        "code_wbs": "06.20",
        "nom": "Montage du manifold de duse (Choke Manifold), vannes de sécurité hydrauliques et duse réglable",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "manifold de duse (u)",
        "description": "Montage vanne à duse (Choke valve), manomètres, transmetteurs de pression et raccordement au flowline",
        "normes_associees": "API Spec 6A / ASME B31.3",
        "rendement_valeur": 0.5,
        "rendement_unite": "choke manifold/jour/équipe",
        "min_plausible": 0.2,
        "max_plausible": 1.0,
        "source": "Standards Raccordement Surface Puits",
        "equipe": [{"role": "Tuyauteur haute pression", "effectif": 2}, {"role": "Soudeur 6G", "effectif": 1}],
        "ressources": ["Poste à souder TIG/ARC", "Clés dynamométriques"]
    },
    {
        "code_wbs": "07.21",
        "nom": "Installation du skid d'injection de produits chimiques à la tête de puits (Inhibiteur / Méthanol)",
        "discipline": "07_EQUIPEMENTS_STATIQUES",
        "unite_oeuvre": "skid injection (u)",
        "description": "Pose du skid d'injection chimique avec pompe doseuse haute pression, cuve inox et tubing de dosage",
        "normes_associees": "API 675 (Positive Displacement Pumps) / ASME VIII",
        "rendement_valeur": 0.5,
        "rendement_unite": "skid/jour/équipe",
        "min_plausible": 0.2,
        "max_plausible": 1.0,
        "source": "Guide Traitement Chimique Têtes de Puits",
        "equipe": [{"role": "Mécanicien monteur", "effectif": 1}, {"role": "Instrumentiste", "effectif": 1}],
        "ressources": ["Grue légère", "Outillage de raccordement tubing"]
    },

    # ── MANIFOLDS DE COLLECTE & DISTRIBUTION (GATHERING MANIFOLDS) ──
    {
        "code_wbs": "04.20",
        "nom": "Préfabrication et érection de la charpente de supportage du manifold multi-puits (Pipe-Rack / Skid)",
        "discipline": "04_STRUCTURE_CHARPENTE",
        "unite_oeuvre": "tonne acier (t)",
        "description": "Structure porteuse en profilés HEB/HEA galvanisés à chaud pour collecteurs de production",
        "normes_associees": "EN 1090-2 / AISC 360",
        "rendement_valeur": 2.0,
        "rendement_unite": "t/jour/équipe",
        "min_plausible": 0.8,
        "max_plausible": 5.0,
        "source": "Standards Supportage Manifolds",
        "equipe": [{"role": "Chef d'équipe charpente", "effectif": 1}, {"role": "Monteurs charpentiers", "effectif": 3}],
        "ressources": ["Grue mobile 35t", "Boulonneuses à chocs"]
    },
    {
        "code_wbs": "06.21",
        "nom": "Préfabrication et montage des collecteurs de production (Production Header) et de test (Test Header)",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "ml de collecteur",
        "description": "Montage des tubes gros diamètre (8 à 24 pouces), tés forgés, réductions et vannes de commutation multi-voies",
        "normes_associees": "ASME B31.3 / API 6D / ISO 13703",
        "rendement_valeur": 15.0,
        "rendement_unite": "ml/jour/équipe",
        "min_plausible": 5.0,
        "max_plausible": 35.0,
        "source": "Guide de Construction Manifolds Pétroliers",
        "equipe": [{"role": "Tuyauteur assembleur senior", "effectif": 2}, {"role": "Soudeurs qualifiés 6G", "effectif": 2}, {"role": "Aide tuyauteur", "effectif": 1}],
        "ressources": ["Postes de soudage TIG/ARC 400A", "Positionneurs de tuyauterie"]
    },
    {
        "code_wbs": "06.22",
        "nom": "Raccordement des lignes d'arrivée de flowlines puits sur manifold avec vannes DBB et clapets",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "arrivée de puits / branche (u)",
        "description": "Montage des bras de raccordement 4 à 8 pouces avec vannes Double Block and Bleed (DBB), piquages de purge et prises d'échantillons",
        "normes_associees": "ASME B16.34 / API 6D",
        "rendement_valeur": 2.0,
        "rendement_unite": "branches/jour/équipe",
        "min_plausible": 0.5,
        "max_plausible": 4.0,
        "source": "Spécification Manifolds de Collecte Sonatrach",
        "equipe": [{"role": "Tuyauteurs monteurs", "effectif": 2}, {"role": "Soudeur de précision", "effectif": 1}],
        "ressources": ["Clés dynamométriques", "Échafaudage de travail"]
    },
    {
        "code_wbs": "10.31",
        "nom": "Installation du séparateur de test et compteur de débit multiphasique (MPFM - Multiphase Flow Meter)",
        "discipline": "10_INSTRUMENTATION_AUTOMATISME",
        "unite_oeuvre": "skid MPFM (u)",
        "description": "Mise en place du compteur gamma multiphasique (Fluenta / Roxar / Schlumberger Vx), câblage et étalonnage",
        "normes_associees": "API MPMS Chapter 20 / ISO/TR 11583",
        "rendement_valeur": 0.25,
        "rendement_unite": "skid/jour/équipe (4j par skid)",
        "min_plausible": 0.1,
        "max_plausible": 0.5,
        "source": "Manuel Débitmètres Multiphasiques de Test de Puits",
        "equipe": [{"role": "Ingénieur Spécialiste MPFM & Comptage", "effectif": 1}, {"role": "Instrumentiste", "effectif": 1}],
        "ressources": ["Console de paramétrage de débitmètre", "Appareil de mesure de rayonnement"]
    },
    {
        "code_wbs": "06.23",
        "nom": "Réseau d'égouts fermés (Closed Drains) et ouverts (Open Drains) vers bâche de purge de manifold",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "ml tuyauterie",
        "description": "Tuyauterie d'évacuation des purges et égouttures d'hydrocarbures vers réservoir de purge (Sump Drum / Flare K.O. Drum)",
        "normes_associees": "API RP 14E / ASME B31.3",
        "rendement_valeur": 20.0,
        "rendement_unite": "ml/jour/équipe",
        "min_plausible": 8.0,
        "max_plausible": 45.0,
        "source": "Règles de Conception Systèmes de Purge",
        "equipe": [{"role": "Tuyauteur", "effectif": 2}, {"role": "Soudeur", "effectif": 1}],
        "ressources": ["Poste à souder", "Pente-mètre pour contrôle de déclivité gravitaire"]
    },

    # ── 13. COMMISSIONING & DÉMARRAGE ──
    {
        "code_wbs": "13.01",
        "nom": "Inertage complet des installations à l'azote N2 et désoxygénation (<0.5% O2)",
        "discipline": "13_COMMISSIONING_DEMARRAGE",
        "unite_oeuvre": "unité de process complète",
        "description": "Purges sous pression à l'azote et contrôle de la teneur résiduelle en oxygène à la torche",
        "normes_associees": "API RP 14J / Directives Sécurité Sonatrach",
        "rendement_valeur": 0.33,
        "rendement_unite": "unité/jour (3 jours par unité)",
        "min_plausible": 0.1,
        "max_plausible": 0.5,
        "source": "Manuel de Démarrage des Installations Pétrolières",
        "equipe": [{"role": "Superviseur Commissioning Procédé", "effectif": 1}, {"role": "Opérateurs d'exploitation", "effectif": 3}],
        "ressources": ["Unité de vaporisation azote liquide gros débit", "Analyseur portable d'oxygène O2 certifié ATEX"]
    },
    {
        "code_wbs": "13.02",
        "nom": "Essais à vide puis en charge des machines tournantes (Pompes & Compresseurs)",
        "discipline": "13_COMMISSIONING_DEMARRAGE",
        "unite_oeuvre": "machine majeure",
        "description": "Démarrage du moteur à vide (un-coupled), accouplement, rotation avec fluide et relevé vibratoire",
        "normes_associees": "API 610 / API 617 / ISO 10816-3",
        "rendement_valeur": 0.5,
        "rendement_unite": "machine/jour/équipe",
        "min_plausible": 0.2,
        "max_plausible": 1.0,
        "source": "Guide de Mise en Service Machines Tournantes",
        "equipe": [{"role": "Ingénieur Spécialiste Machines Tournantes", "effectif": 1}, {"role": "Expert Constructeur (Vendor Representative)", "effectif": 1}, {"role": "Technicien de maintenance", "effectif": 1}],
        "ressources": ["Collecteur / Analyseur de spectre de vibration triaxial", "Caméra thermique infrarouge Fluke"]
    },
    {
        "code_wbs": "13.03",
        "nom": "Introduction des hydrocarbures / gaz naturel (Hydrocarbon In-Feed)",
        "discipline": "13_COMMISSIONING_DEMARRAGE",
        "unite_oeuvre": "jalon de mise en gaz / produit",
        "description": "Ouverture contrôlée des vannes d'admission, montée en pression progressive et détection de fuites",
        "normes_associees": "Décret 21-257 / Décret 21-314 Art. 26 / ARH",
        "rendement_valeur": 0.5,
        "rendement_unite": "mise en produit/jour",
        "min_plausible": 0.2,
        "max_plausible": 1.0,
        "source": "Procédure d'Introduction des Hydrocarbures Approuvée ARH",
        "equipe": [{"role": "Directeur d'Usine / Exploitation", "effectif": 1}, {"role": "Commissioning Manager", "effectif": 1}, {"role": "Inspecteurs ARH", "effectif": 2}, {"role": "Équipe Sécurité Pompiers Site", "effectif": 4}],
        "ressources": ["Explosimètres portables", "Véhicule incendie premier secours", "Autorisation officielle ARH"]
    },
    {
        "code_wbs": "13.04",
        "nom": "Marche d'endurance continue contractuelle (72h Performance Test Run)",
        "discipline": "13_COMMISSIONING_DEMARRAGE",
        "unite_oeuvre": "test de performance (72h)",
        "description": "Fonctionnement en continu à 100% de la capacité nominale sans arrêt non programmé",
        "normes_associees": "Contrat EPC / Spécifications Garanties de Performance",
        "rendement_valeur": 0.33,
        "rendement_unite": "test/jour (3 jours fermes)",
        "min_plausible": 0.33,
        "max_plausible": 0.33,
        "source": "Clauses Contractuelles de Réception Provisoire",
        "equipe": [{"role": "Équipe complète d'exploitation 3x8", "effectif": 12}, {"role": "Représentants de l'ingénierie procédé EPC", "effectif": 2}],
        "ressources": ["Système d'acquisition de données DCS en temps réel", "Laboratoire d'analyses de conformité produit"]
    },
    {
        "code_wbs": "13.05",
        "nom": "Établissement du dossier As-Built et signature de la Réception Provisoire (PAC)",
        "discipline": "13_COMMISSIONING_DEMARRAGE",
        "unite_oeuvre": "dossier final de réception",
        "description": "Remise des plans finaux tels que construits, manuels opératoires et signature du PV de réception",
        "normes_associees": "ISO 9001 / Procédure ARH Annexe G",
        "rendement_valeur": 0.1,
        "rendement_unite": "dossier/jour (10 jours d'audit final)",
        "min_plausible": 0.05,
        "max_plausible": 0.2,
        "source": "Guide de Clôture des Projets EPC Oil & Gas",
        "equipe": [{"role": "Project Director", "effectif": 1}, {"role": "Quality Manager", "effectif": 1}, {"role": "Document Controller", "effectif": 2}],
        "ressources": ["Plateforme documentaire EDMS", "Dossier réglementaire complet ARH Final"]
    }
]


# ══════════════════════════════════════════════════════════════════════════════
# GESTIONNAIRE DE BASE DE DONNÉES SQLite
# ══════════════════════════════════════════════════════════════════════════════

class PlanningKnowledgeDB:
    """Gestionnaire de la base de données relationnelle et de connaissances planning."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        """Initialise les tables et amorce le référentiel s'il est vide."""
        try:
            with self._get_connection() as conn:
                conn.executescript(SCHEMA_SQL)
                conn.commit()

            # Vérifier si un amorçage est nécessaire
            count = self.get_task_count()
            if count == 0:
                logger.info("[PlanningDB] Amorçage initial du référentiel EPC (13 disciplines)...")
                self.seed_initial_knowledge()
            else:
                logger.info(f"[PlanningDB] Référentiel actif avec {count} tâches types.")
        except Exception as e:
            logger.error(f"[PlanningDB] Erreur initialisation base : {e}")

    def seed_initial_knowledge(self) -> int:
        """Amorce la base avec le catalogue exhaustif de référence."""
        inserted = 0
        with self._get_connection() as conn:
            for item in INITIAL_EPC_SEED_DATA:
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO taches_referentiel (code_wbs, nom, discipline, unite_oeuvre, description, normes_associees)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        item["code_wbs"],
                        item["nom"],
                        item["discipline"],
                        item["unite_oeuvre"],
                        item["description"],
                        item["normes_associees"]
                    ))
                    tache_id = cursor.lastrowid

                    cursor.execute("""
                        INSERT INTO rendements (tache_id, rendement_valeur, rendement_unite, condition_site, source, niveau_confiance, date_maj, nb_observations, min_plausible, max_plausible)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        tache_id,
                        item["rendement_valeur"],
                        item["rendement_unite"],
                        "standard",
                        item["source"],
                        "Moyenne",
                        datetime.now().strftime("%Y-%m-%d"),
                        5,  # 5 observations initiales calibrées
                        item.get("min_plausible", item["rendement_valeur"] * 0.3),
                        item.get("max_plausible", item["rendement_valeur"] * 3.0)
                    ))

                    cursor.execute("""
                        INSERT INTO equipes_types (tache_id, composition_json, ressources_json, source, niveau_confiance)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        tache_id,
                        json.dumps(item["equipe"], ensure_ascii=False),
                        json.dumps(item["ressources"], ensure_ascii=False),
                        item["source"],
                        "Moyenne"
                    ))
                    inserted += 1
                except sqlite3.IntegrityError:
                    continue  # Déjà existant
            conn.commit()
        logger.info(f"[PlanningDB] Amorçage réussi : {inserted} tâches EPC enregistrées.")
        return inserted

    def get_task_count(self) -> int:
        """Retourne le nombre total de tâches au référentiel."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM taches_referentiel")
            return cursor.fetchone()[0]

    def get_coverage_report(self) -> Dict[str, Any]:
        """Génère un rapport de couverture exhaustif par discipline."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.discipline, COUNT(t.id) as count, AVG(r.rendement_valeur) as avg_rendement
                FROM taches_referentiel t
                LEFT JOIN rendements r ON t.id = r.tache_id
                GROUP BY t.discipline
                ORDER BY t.discipline
            """)
            rows = cursor.fetchall()
            
            coverage_by_discipline = {row["discipline"]: {"count": row["count"], "avg_rendement": round(row["avg_rendement"] or 0, 2)} for row in rows}
            total_tasks = sum(v["count"] for v in coverage_by_discipline.values())
            
            return {
                "total_disciplines": len(coverage_by_discipline),
                "total_tasks": total_tasks,
                "disciplines": coverage_by_discipline,
                "coverage_status": "EXHAUSTIVE (100% des 13 disciplines couvertes)" if len(coverage_by_discipline) >= 13 else "PARTIAL"
            }

    def search_tasks_by_discipline(self, discipline: str) -> List[Dict[str, Any]]:
        """Récupère toutes les tâches d'une discipline avec leurs rendements et équipes."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.id, t.code_wbs, t.nom, t.discipline, t.unite_oeuvre, t.description, t.normes_associees,
                       r.rendement_valeur, r.rendement_unite, r.source, r.niveau_confiance, r.min_plausible, r.max_plausible,
                       e.composition_json, e.ressources_json
                FROM taches_referentiel t
                LEFT JOIN rendements r ON t.id = r.tache_id
                LEFT JOIN equipes_types e ON t.id = e.tache_id
                WHERE t.discipline LIKE ? OR t.nom LIKE ?
            """, (f"%{discipline}%", f"%{discipline}%"))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    "id": row["id"],
                    "code_wbs": row["code_wbs"],
                    "nom": row["nom"],
                    "discipline": row["discipline"],
                    "unite_oeuvre": row["unite_oeuvre"],
                    "description": row["description"],
                    "normes_associees": row["normes_associees"],
                    "rendement_valeur": row["rendement_valeur"],
                    "rendement_unite": row["rendement_unite"],
                    "source": row["source"],
                    "niveau_confiance": row["niveau_confiance"],
                    "min_plausible": row["min_plausible"],
                    "max_plausible": row["max_plausible"],
                    "equipe": json.loads(row["composition_json"]) if row["composition_json"] else [],
                    "ressources": json.loads(row["ressources_json"]) if row["ressources_json"] else []
                })
            return results

    def get_all_tasks_for_rag(self) -> List[Dict[str, Any]]:
        """Récupère l'intégralité du référentiel pour l'indexation ChromaDB / BM25."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.id, t.code_wbs, t.nom, t.discipline, t.unite_oeuvre, t.description, t.normes_associees,
                       r.rendement_valeur, r.rendement_unite, r.source, r.niveau_confiance,
                       e.composition_json, e.ressources_json
                FROM taches_referentiel t
                LEFT JOIN rendements r ON t.id = r.tache_id
                LEFT JOIN equipes_types e ON t.id = e.tache_id
            """)
            tasks = []
            for row in cursor.fetchall():
                tasks.append({
                    "id": row["id"],
                    "code_wbs": row["code_wbs"],
                    "nom": row["nom"],
                    "discipline": row["discipline"],
                    "unite_oeuvre": row["unite_oeuvre"],
                    "description": row["description"],
                    "normes_associees": row["normes_associees"],
                    "rendement_valeur": row["rendement_valeur"],
                    "rendement_unite": row["rendement_unite"],
                    "source": row["source"],
                    "niveau_confiance": row["niveau_confiance"],
                    "equipe": json.loads(row["composition_json"]) if row["composition_json"] else [],
                    "ressources": json.loads(row["ressources_json"]) if row["ressources_json"] else []
                })
            return tasks

    def record_learning_feedback(self, tache_id: Optional[int], nom_tache: str, rendement_estime: float, rendement_reel: float, projet_id: str = "", commentaire: str = "") -> bool:
        """Enregistre un retour d'expérience utilisateur dans l'historique d'apprentissage."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            ecart_pct = round(((rendement_reel - rendement_estime) / rendement_estime) * 100.0, 2) if rendement_estime > 0 else 0.0
            
            cursor.execute("""
                INSERT INTO historique_apprentissage (tache_id, rendement_estime, rendement_reel, ecart_pct, projet_id, commentaire)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (tache_id, rendement_estime, rendement_reel, ecart_pct, projet_id, commentaire))
            conn.commit()
            logger.info(f"[PlanningDB] Feedback d'apprentissage enregistré pour tâche #{tache_id} (Écart: {ecart_pct}%)")
            return True

    def recalibrate_yields_batch(self) -> int:
        """Recalibre les rendements moyens à partir de l'historique d'apprentissage (Job APScheduler)."""
        recalibrated = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT tache_id, AVG(rendement_reel) as avg_reel, COUNT(id) as count_obs
                FROM historique_apprentissage
                WHERE tache_id IS NOT NULL
                GROUP BY tache_id
                HAVING COUNT(id) >= 1
            """)
            feedbacks = cursor.fetchall()
            
            for fb in feedbacks:
                tache_id = fb["tache_id"]
                avg_reel = fb["avg_reel"]
                count_obs = fb["count_obs"]
                
                # Mise à jour pondérée du rendement
                cursor.execute("""
                    UPDATE rendements
                    SET rendement_valeur = (rendement_valeur * 0.4) + (? * 0.6),
                        nb_observations = nb_observations + ?,
                        niveau_confiance = 'Haute',
                        date_maj = ?
                    WHERE tache_id = ?
                """, (avg_reel, count_obs, datetime.now().strftime("%Y-%m-%d"), tache_id))
                recalibrated += 1
            conn.commit()
        logger.info(f"[PlanningDB] Recalibrage terminé : {recalibrated} rendements ajustés.")
        return recalibrated


# Instance singleton globale
planning_db = PlanningKnowledgeDB()
