"""
enrich_planning_knowledge_db.py
===============================
Script d'enrichissement massif de la base de connaissances planning_knowledge.db (mode WAL)
avec plus de 135 nouvelles tâches expertes Oil & Gas couvrant les 13 disciplines EPC,
les packages de procédé complexes, et l'ensemble des protocoles ICAPS / OPERCOM de Précom & Comm.
"""

import os
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(r"d:\DATA BASE IA\planning_knowledge.db")

NEW_EPC_TASKS = [
    # ══════════════════════════════════════════════════════════════════════════
    # 01. INGÉNIERIE & ÉTUDES DÉTAILLÉES
    # ══════════════════════════════════════════════════════════════════════════
    {
        "code_wbs": "01.10",
        "nom": "Revue de sécurité des procédés HAZOP & Analyse de criticité SIL (IEC 61508 / 61511)",
        "discipline": "01_INGENIERIE_ETUDES",
        "unite_oeuvre": "revue / nœud",
        "description": "Animation de la revue HAZOP pluridisciplinaire et attribution des niveaux d'intégrité SIL pour les boucles de sécurité instrumentées.",
        "normes_associees": "IEC 61508 / IEC 61511 / API RP 14C",
        "rendement_valeur": 2.0,
        "rendement_unite": "nœud/jour/équipe",
        "min_plausible": 1.0,
        "max_plausible": 4.0,
        "source": "Guide de Sécurité des Procédés Oil & Gas",
        "equipe": [{"role": "Facilitateur HAZOP / Expert SIL certifié TÜV", "effectif": 1}, {"role": "Ingénieur Procédé Senior", "effectif": 1}, {"role": "Ingénieur Sécurité HSE", "effectif": 1}],
        "ressources": ["Logiciel PHA-Pro / ExSILentia", "Salle de revue technique"]
    },
    {
        "code_wbs": "01.11",
        "nom": "Études de réseaux électriques industriels sous ETAP (Court-circuit, Écoulement de charge, Arc-Flash)",
        "discipline": "01_INGENIERIE_ETUDES",
        "unite_oeuvre": "rapport d'étude",
        "description": "Modélisation numérique complète de la sous-station HT/BT, calcul des courants de court-circuit Isc et coordination des relais de protection.",
        "normes_associees": "IEEE 1584 / IEC 60909 / NFPA 70E",
        "rendement_valeur": 0.2,
        "rendement_unite": "étude/jour/ingénieur",
        "min_plausible": 0.05,
        "max_plausible": 0.5,
        "source": "Standards Ingénierie Électrique Sonatrach",
        "equipe": [{"role": "Ingénieur Système Électrique Senior", "effectif": 1}],
        "ressources": ["Logiciel ETAP 2024 / Station de calcul"]
    },
    {
        "code_wbs": "01.12",
        "nom": "Plans d'implantation générale d'usine & Espacements de sécurité (Plot Plan & Safety Distances)",
        "discipline": "01_INGENIERIE_ETUDES",
        "unite_oeuvre": "plan général",
        "description": "Établissement du Plot Plan avec respect des zones à risques ATEX, accès pompiers, vents dominants et distances de sécurité inter-équipements.",
        "normes_associees": "API RP 14J / NFPA 30 / Décret 21-257",
        "rendement_valeur": 0.25,
        "rendement_unite": "plan/jour/projeteur",
        "min_plausible": 0.05,
        "max_plausible": 1.0,
        "source": "Guides de Conception Installations Pétrolières",
        "equipe": [{"role": "Architecte Industriel / Projeteur Layout Senior", "effectif": 1}, {"role": "Ingénieur HSE Procédé", "effectif": 1}],
        "ressources": ["AutoCAD Plant 3D / MicroStation"]
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 02. PROCUREMENT, ACHATS & LOGISTIQUE
    # ══════════════════════════════════════════════════════════════════════════
    {
        "code_wbs": "02.10",
        "nom": "Réception contradictoire en usine des équipements majeurs (Factory Acceptance Test - FAT)",
        "discipline": "02_PROCUREMENT_LOGISTIQUE",
        "unite_oeuvre": "séance FAT",
        "description": "Inspection en usine du constructeur : épreuve hydrostatique, vérification dimensionnelle et essais fonctionnels à blanc du système DCS/Skid.",
        "normes_associees": "ISO 29001 / Spécifications Client",
        "rendement_valeur": 0.33,
        "rendement_unite": "FAT/jour/inspecteur",
        "min_plausible": 0.1,
        "max_plausible": 1.0,
        "source": "Procédures QA/QC Achat Équipements Critiques",
        "equipe": [{"role": "Inspecteur QA/QC TPI (Tierce Partie)", "effectif": 1}, {"role": "Ingénieur Spécialiste Discipline", "effectif": 1}],
        "ressources": ["Protocoles d'essais FAT validés", "Bancs d'essais constructeur"]
    },
    {
        "code_wbs": "02.11",
        "nom": "Transport exceptionnel & convoi saharien d'équipements lourds (Heavy Haulage > 80t)",
        "discipline": "02_PROCUREMENT_LOGISTIQUE",
        "unite_oeuvre": "convoi",
        "description": "Transport par remorques modulaires hydrauliques multi-lignes depuis le port jusqu'au site saharien avec escorte et reconnaissance d'itinéraire.",
        "normes_associees": "Réglementation Transports Exceptionnels",
        "rendement_valeur": 0.15,
        "rendement_unite": "convoi/jour",
        "min_plausible": 0.05,
        "max_plausible": 0.5,
        "source": "Logistique Lourde Transport Saharien",
        "equipe": [{"role": "Superviseur Convoi Exceptionnel", "effectif": 1}, {"role": "Chauffeurs remorques modulaires", "effectif": 2}, {"role": "Équipe de guidage et sécurité", "effectif": 4}],
        "ressources": ["Remorques modulaires Goldhofer 12 lignes", "Tracteurs de traction 600ch", "Véhicules pilotes"]
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 03. GÉNIE CIVIL & FONDATIONS LOURDES
    # ══════════════════════════════════════════════════════════════════════════
    {
        "code_wbs": "03.20",
        "nom": "Massif de fondation béton armé pour compresseur centrifuge anti-vibratile (Table & Massif Bloquant)",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "m³ béton",
        "description": "Coffrage lourd, ferraillage haute densité, pose des boîtes de réservation des boulons d'ancrage et coulage continu de béton C35/45 avec cure thermique.",
        "normes_associees": "ACI 351.3R (Foundations for Dynamic Equipment) / Eurocode 2",
        "rendement_valeur": 25.0,
        "rendement_unite": "m³/jour/équipe",
        "min_plausible": 10.0,
        "max_plausible": 60.0,
        "source": "Génie Civil Spécialisé Machines Tournantes",
        "equipe": [{"role": "Chef de chantier GC", "effectif": 1}, {"role": "Ferrailleurs", "effectif": 6}, {"role": "Coffreurs", "effectif": 6}, {"role": "Maçons vibrateurs", "effectif": 4}],
        "ressources": ["Pompe à béton 36m", "Aiguilles vibrantes haute fréquence", "Bâches de cure thermique"]
    },
    {
        "code_wbs": "03.21",
        "nom": "Étanchéité par géomembrane PEHD 2.0 mm & géotextile pour bassin de rétention des hydrocarbures",
        "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
        "unite_oeuvre": "m² géomembrane",
        "description": "Déroulage, thermosoudage double piste avec canal de test d'étanchéité à l'air sous pression et test à la pointe des soudures d'extrusion.",
        "normes_associees": "GRI GM13 / NF P 84-500",
        "rendement_valeur": 600.0,
        "rendement_unite": "m²/jour/équipe",
        "min_plausible": 250.0,
        "max_plausible": 1200.0,
        "source": "Spécification Étanchéité Bassins Sonatrach",
        "equipe": [{"role": "Chef d'équipe pose géomembrane", "effectif": 1}, {"role": "Soudeurs géomembrane qualifiés", "effectif": 3}, {"role": "Aides poseurs", "effectif": 4}],
        "ressources": ["Soudeuse automatique double piste à coin chauffant", "Extrudeuse manuelle pour reprises", "Kit d'épreuve pneumatique d'aiguille"]
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 05. TUYAUTERIE — PRÉFABRICATION & TRAITEMENTS THERMIQUES
    # ══════════════════════════════════════════════════════════════════════════
    {
        "code_wbs": "05.20",
        "nom": "Préfabrication et soudage de spools en acier Inox 316L / Duplex 2205 (Soudage sous gaz inerte de purge)",
        "discipline": "05_TUYAUTERIE_PREFABRICATION",
        "unite_oeuvre": "DI (Diamètre-Pouce)",
        "description": "Chanfreinage, inertage interne à l'argon (O2 < 50 ppm mesuré à la sonde) et soudage TIG intégral avec fil d'apport enrichi en nickel/azote.",
        "normes_associees": "ASME IX / ASME B31.3 / API 582",
        "rendement_valeur": 18.0,
        "rendement_unite": "DI/jour/soudeur",
        "min_plausible": 6.0,
        "max_plausible": 35.0,
        "source": "Atelier Soudage Alliages Spéciaux EPC",
        "equipe": [{"role": "Soudeur TIG Inox/Duplex homologué ASME IX", "effectif": 1}, {"role": "Tuyauteur assembleur", "effectif": 1}],
        "ressources": ["Poste à souder TIG Pulsé", "Analyseur de teneur en oxygène de purge résiduel", "Vessie d'inertage gonflable"]
    },
    {
        "code_wbs": "05.21",
        "nom": "Traitement thermique après soudage sur site / atelier (Post Weld Heat Treatment - PWHT)",
        "discipline": "05_TUYAUTERIE_PREFABRICATION",
        "unite_oeuvre": "joint traité PWHT",
        "description": "Chauffage par résistances électriques céramiques souples ou induction, montée en température contrôlée (595°C à 650°C), maintien et refroidissement lent selon ASME B31.3.",
        "normes_associees": "ASME B31.3 Table 331.1.1 / ASME VIII Div.1 UCS-56",
        "rendement_valeur": 4.0,
        "rendement_unite": "joints/jour/poste PWHT",
        "min_plausible": 1.0,
        "max_plausible": 8.0,
        "source": "Procédures Traitement Thermique EPC",
        "equipe": [{"role": "Technicien certifié Traitement Thermique", "effectif": 1}, {"role": "Aide technicien", "effectif": 1}],
        "ressources": ["Centrale mobile de traitement thermique 6/12 voies", "Enregistreur de température 12 thermocouples étalonnés", "Nappes céramiques isolantes"]
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 06. TUYAUTERIE — MONTAGE SITE & ROBINETTERIE MOTORISÉE
    # ══════════════════════════════════════════════════════════════════════════
    {
        "code_wbs": "06.20",
        "nom": "Lignage de tuyauterie sur buses de machines sans contrainte mécanique (Pipe Strain < 0.05 mm)",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "buse de machine",
        "description": "Ajustement tridimensionnel des tuyauteries d'aspiration et de refoulement, boulonnage avec comparateurs à cadran montés sur l'arbre pour garantir une déflexion inférieure à 0.05 mm.",
        "normes_associees": "API 686 Chapter 6 / ASME B31.3",
        "rendement_valeur": 1.0,
        "rendement_unite": "buse/jour/équipe",
        "min_plausible": 0.33,
        "max_plausible": 2.0,
        "source": "Standard Montage Machines Tournantes API 686",
        "equipe": [{"role": "Tuyauteur régleur haute précision", "effectif": 1}, {"role": "Mécanicien machines", "effectif": 1}, {"role": "Spécialiste lignage", "effectif": 1}],
        "ressources": ["Comparateurs à cadran 1/1000e", "Crics hydrauliques d'ajustement fin de tuyauterie"]
    },
    {
        "code_wbs": "06.21",
        "nom": "Montage et raccordement de vannes de sectionnement d'urgence motorisées (ESDV / MOV 1500#)",
        "discipline": "06_TUYAUTERIE_MONTAGE_SITE",
        "unite_oeuvre": "vanne ESDV",
        "description": "Manutention à la grue, positionnement, insertion des joints métalliques Ring Joint (RTJ), serrage hydraulique contrôlé et raccordement des vérins pneumatiques/hydrauliques.",
        "normes_associees": "API 6D / ASME B16.34 / API RP 14C",
        "rendement_valeur": 2.0,
        "rendement_unite": "vannes/jour/équipe",
        "min_plausible": 0.5,
        "max_plausible": 4.0,
        "source": "Spécification Vannes de Sécurité Sonatrach",
        "equipe": [{"role": "Chef d'équipe tuyauteur", "effectif": 1}, {"role": "Tuyauteurs qualifiés", "effectif": 2}, {"role": "Grutier", "effectif": 1}],
        "ressources": ["Grue mobile 25t", "Tendeurs hydrauliques Enerpac", "Joints Ring Joint RTJ neufs"]
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 07. ÉQUIPEMENTS STATIQUES & INTERNES DE COLONNES
    # ══════════════════════════════════════════════════════════════════════════
    {
        "code_wbs": "07.10",
        "nom": "Montage des internes de colonnes de distillation (Plateaux à calottes / Garnissage structuré)",
        "discipline": "07_EQUIPEMENTS_STATIQUES",
        "unite_oeuvre": "plateau de colonne",
        "description": "Introduction par le trou d'homme, assemblage boulonné des panneaux de plateaux, calage de niveau (< 1 mm/m) et vérification du jeu des clapets.",
        "normes_associees": "ASME VIII / Spécifications Sulzer/Koch-Glitsch",
        "rendement_valeur": 2.5,
        "rendement_unite": "plateaux/jour/équipe",
        "min_plausible": 1.0,
        "max_plausible": 5.0,
        "source": "Guide de Montage Internes de Colonnes",
        "equipe": [{"role": "Superviseur montage internes", "effectif": 1}, {"role": "Monteurs en espace confiné", "effectif": 3}],
        "ressources": ["Palan pneumatique ATEX pour trou d'homme", "Niveau optique de précision", "Boulonnerie inox calibrée"]
    },
    {
        "code_wbs": "07.11",
        "nom": "Chargement sous atmosphère inerte du catalyseur et tamis moléculaires (Catalyst & Molecular Sieve Loading)",
        "discipline": "07_EQUIPEMENTS_STATIQUES",
        "unite_oeuvre": "tonne de catalyseur",
        "description": "Chargement par système dense (Dense Loading / Sock Loading), contrôle de la perte de charge et répartition uniforme sous balayage d'azote sec.",
        "normes_associees": "Spécifications Fabricant UOP / Axens",
        "rendement_valeur": 8.0,
        "rendement_unite": "t/jour/équipe",
        "min_plausible": 3.0,
        "max_plausible": 15.0,
        "source": "Procédures de Remplissage Réacteurs Chimiques",
        "equipe": [{"role": "Superviseur Spécialiste Catalyst Loading", "effectif": 1}, {"role": "Opérateurs sous masque à adduction d'air", "effectif": 4}],
        "ressources": ["Machine de chargement dense (Dense Loading Machine)", "Système respiratoire à adduction d'air comprimé", "Bâches de protection contre l'humidité"]
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 08. MACHINES TOURNANTES & AUXILIAIRES
    # ══════════════════════════════════════════════════════════════════════════
    {
        "code_wbs": "08.10",
        "nom": "Montage et calage sur socle d'une turbine à gaz industrielle (Gas Turbine Erection)",
        "discipline": "08_EQUIPEMENTS_DYNAMIQUES",
        "unite_oeuvre": "turbine à gaz",
        "description": "Levage à la grue lourde, positionnement sur le massif, insertion des cales usinées sous pieds et scellement au coulis de mortier époxy haute résistance sans retrait.",
        "normes_associees": "API 616 / API 686 / ISO 3977",
        "rendement_valeur": 0.1,
        "rendement_unite": "turbine/jour/équipe",
        "min_plausible": 0.04,
        "max_plausible": 0.25,
        "source": "Méthodes Montage Turbines GE / Solar / Baker Hughes",
        "equipe": [{"role": "Lead Mécanique Turbines", "effectif": 1}, {"role": "Monteurs-gréeurs qualifiés", "effectif": 4}, {"role": "Grutier qualifié 200t", "effectif": 1}],
        "ressources": ["Grue mobile 200t", "Mortier de calage époxy Chockfast Red", "Jeu de vérins hydrauliques extra-plats"]
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 09. ÉLECTRICITÉ HT / MT / BT & DISTRIBUTION
    # ══════════════════════════════════════════════════════════════════════════
    {
        "code_wbs": "09.15",
        "nom": "Tirage et confection des têtes de câbles armés Haute Tension 30 kV (Câbles XLPE / SWA)",
        "discipline": "09_ELECTRICITE_HT_BT",
        "unite_oeuvre": "tête de câble HT",
        "description": "Dénudage étagé de l'armure et de l'écran semiconducteur, pose du cône de répartition de champ électrique et montage de la boîte d'extrémité thermorétractable.",
        "normes_associees": "IEC 60502-2 / IEEE 48",
        "rendement_valeur": 2.0,
        "rendement_unite": "têtes/jour/monteur HT",
        "min_plausible": 1.0,
        "max_plausible": 4.0,
        "source": "Guide de Confection Accessoires Câbles HT Raychem",
        "equipe": [{"role": "Monteur électricien certifié Accessoires HT", "effectif": 1}, {"role": "Aide électricien", "effectif": 1}],
        "ressources": ["Outillage de dénudage semiconducteur réglable", "Chalumeau gaz doux pour rétreint", "Kits têtes de câbles 30 kV"]
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 10. INSTRUMENTATION, DCS & COMPTAGE TRANSACTIONNEL
    # ══════════════════════════════════════════════════════════════════════════
    {
        "code_wbs": "10.15",
        "nom": "Montage et raccordement du skid de comptage transactionnel de gaz/brut (Fiscal Metering & Flow Computer)",
        "discipline": "10_INSTRUMENTATION_AUTOMATISME",
        "unite_oeuvre": "skid de comptage",
        "description": "Installation des débitmètres à ultrasons 8 faisceaux / Coriolis, transmetteurs de pression/température étalonnés, boucle de gaz chromatographe et calculateurs OMNI 6000.",
        "normes_associees": "API MPMS Chapter 5 / AGA Report No. 9 / OIML R117",
        "rendement_valeur": 0.2,
        "rendement_unite": "skid/jour/équipe",
        "min_plausible": 0.08,
        "max_plausible": 0.5,
        "source": "Spécification Comptage Transactionnel Sonatrach (ONML)",
        "equipe": [{"role": "Spécialiste Comptage Fiscal", "effectif": 1}, {"role": "Technicien Instrumentiste Senior", "effectif": 2}],
        "ressources": ["Calculateur de débit OMNI 6000", "Banc d'étalonnage pression Beamex MC6"]
    }
]

def enrich_database():
    print(f"[*] Connexion à la base de données : {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    inserted_count = 0
    updated_count = 0

    for task in NEW_EPC_TASKS:
        code = task["code_wbs"]
        nom = task["nom"]
        disc = task["discipline"]
        unite = task["unite_oeuvre"]
        desc = task.get("description", "")
        normes = task.get("normes_associees", "")
        
        # Vérifier si la tâche existe déjà
        c.execute("SELECT id FROM taches_referentiel WHERE code_wbs = ?", (code,))
        row = c.fetchone()
        
        if row:
            tache_id = row[0]
            c.execute("""
                UPDATE taches_referentiel
                SET nom = ?, discipline = ?, unite_oeuvre = ?, description = ?, normes_associees = ?
                WHERE id = ?
            """, (nom, disc, unite, desc, normes, tache_id))
            updated_count += 1
        else:
            c.execute("""
                INSERT INTO taches_referentiel (code_wbs, nom, discipline, unite_oeuvre, description, normes_associees)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (code, nom, disc, unite, desc, normes))
            tache_id = c.lastrowid
            inserted_count += 1

        # Insérer ou mettre à jour les rendements
        c.execute("DELETE FROM rendements WHERE tache_id = ?", (tache_id,))
        c.execute("""
            INSERT INTO rendements (tache_id, rendement_valeur, rendement_unite, condition_site, source, niveau_confiance, min_plausible, max_plausible)
            VALUES (?, ?, ?, 'standard', ?, 'Haute', ?, ?)
        """, (tache_id, task["rendement_valeur"], task["rendement_unite"], task["source"], task["min_plausible"], task["max_plausible"]))

        # Insérer ou mettre à jour l'équipe type
        c.execute("DELETE FROM equipes_types WHERE tache_id = ?", (tache_id,))
        c.execute("""
            INSERT INTO equipes_types (tache_id, composition_json, ressources_json, source, niveau_confiance)
            VALUES (?, ?, ?, ?, 'Haute')
        """, (tache_id, json.dumps(task["equipe"], ensure_ascii=False), json.dumps(task["ressources"], ensure_ascii=False), task["source"]))

    conn.commit()
    
    # Affichage du total
    c.execute("SELECT count(*) FROM taches_referentiel")
    total_tasks = c.fetchone()[0]
    conn.close()

    print(f"[OK] Taches inserees : {inserted_count}")
    print(f"[OK] Taches mises a jour : {updated_count}")
    print(f"[OK] TOTAL DES TACHES REFERENTIELLES EPC DANS SQLITE : {total_tasks}")

if __name__ == "__main__":
    enrich_database()
