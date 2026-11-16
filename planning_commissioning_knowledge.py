"""
planning_commissioning_knowledge.py
====================================
Référentiel Expert Exhaustif des Phases de Travaux, Pré-Commissioning (Fiches A)
et Commissioning (Fiches B) pour TOUS les Équipements et Unités de Procédé Oil & Gas.

Standards & Normes Couverts :
  - ICAPS / OPERCOM (Standards internationaux TotalEnergies / Sonatrach / Eni)
  - API RP 14C / 14E / 14J (Sécurité et conception des installations de surface)
  - API 610 / 617 / 618 / 614 / 670 / 682 / 686 (Machines tournantes & auxiliaires)
  - ASME Section VIII Div 1 & 2 (Appareils sous pression)
  - ASME B31.3 / B31.4 / B31.8 (Tuyauteries d'usine et Canalisations de transport)
  - API 650 / 620 / 653 (Bacs de stockage atmosphériques et basse pression)
  - API 520 / 521 / 526 (Soupapes de sûreté PSV et réseaux de torche)
  - IEC 61508 / IEC 61511 (Systèmes Instrumentés de Sécurité - SIS / ESD / SIL)
  - IEC 60079 (Installations en atmosphères explosives ATEX / IECEx)
  - IEC 61439 / 62271 / 60076 (Distribution électrique HT / MT / BT)
  - Décrets exécutifs algériens 21-261, 21-314, 21-315, 24-278 et Procédure ARH P-CTE-1.
"""

from __future__ import annotations

import json
from typing import Dict, List, Any, Optional

# ══════════════════════════════════════════════════════════════════════════════
# ENCYCLOPÉDIE COMPLÈTE DES ÉQUIPEMENTS & PACKAGES PROCÉDÉ OIL & GAS
# ══════════════════════════════════════════════════════════════════════════════

COMMISSIONING_EQUIPMENT_DATABASE: Dict[str, Dict[str, Any]] = {

    # ──────────────────────────────────────────────────────────────────────────
    # 1. ÉQUIPEMENTS STATIQUES SOUS PRESSION & SÉPARATION
    # ──────────────────────────────────────────────────────────────────────────
    "PRESSURE_VESSEL_SEPARATOR": {
        "category": "STATIC_EQUIPMENT",
        "label": "Ballon Séparateur Triphasique / Séparateur de Production HP-BP",
        "codes_standards": ["ASME VIII Div.1", "API 12J", "NACE MR0175", "Décret 21-261"],
        "precommissioning": [
            {
                "code": "PC-ST-01",
                "name": "Inspection visuelle interne & propreté (Internal Cleanliness & Box-up)",
                "description": "Contrôle de l'absence de corps étrangers, vérification du montage des internes (débrumisateur demister, déversoirs, coalesseurs, vortex breaker) et PV de fermeture d'homme (Box-up Certificate).",
                "unite": "u (appareil)",
                "duree_jours": 1.0,
                "checksheet_type": "A-SHEET (Mécanique)",
                "equipe": [{"role": "Inspecteur QA/QC Mécanique", "effectif": 1}, {"role": "Monteur mécanique", "effectif": 2}],
                "ressources": ["Lampe d'inspection ATEX", "Miroir d'inspection", "Joints d'étanchéité neufs homologués"]
            },
            {
                "code": "PC-ST-02",
                "name": "Épreuve hydrostatique / pneumatique & calage de surpression",
                "description": "Pose des disques pleins temporaires (Spades/Blinds), mise en eau déminéralisée avec inhibiteur de corrosion, montée en pression à 150% PMA, maintien 2h et dépressurisation contrôlée.",
                "unite": "u (épreuve)",
                "duree_jours": 2.0,
                "checksheet_type": "A-SHEET (Pression)",
                "equipe": [{"role": "Superviseur Épreuve Hydro", "effectif": 1}, {"role": "Opérateurs pompage HP", "effectif": 2}, {"role": "Inspecteur TPI / ARH", "effectif": 1}],
                "ressources": ["Pompe d'épreuve hydrostatique HP", "Enregistreur de pression/température Barton étalonné", "Manomètres étalonnés classe 0.5"]
            },
            {
                "code": "PC-ST-03",
                "name": "Séchage à l'air sec déshuilé (Drying to Dew Point < -20°C)",
                "description": "Soufflage d'air chaud et sec ou balayage sous vide jusqu'à obtention d'un point de rosée inférieur à -20°C pour éviter la formation d'hydrates lors du démarrage.",
                "unite": "u (capacité)",
                "duree_jours": 1.5,
                "checksheet_type": "A-SHEET (Procédé)",
                "equipe": [{"role": "Opérateur séchage", "effectif": 2}],
                "ressources": ["Compresseur d'air sec mobile avec sécheur par adsorption (Dew Point -40°C)", "Hygromètre capacitif étalonné"]
            },
            {
                "code": "PC-ST-04",
                "name": "Serrage contrôlé au couple / tensionnage hydraulique des brides",
                "description": "Vérification des couples de serrage au couplemètre ou tendeur hydraulique selon la spécification de classe de tuyauterie, marquage témoin au feutre indélébile.",
                "unite": "bride",
                "duree_jours": 1.0,
                "checksheet_type": "A-SHEET (Tuyauterie)",
                "equipe": [{"role": "Tuyauteur spécialisé serrage", "effectif": 2}],
                "ressources": ["Centrale hydraulique de serrage Plarad / Enerpac", "Douilles à chocs adaptées"]
            }
        ],
        "commissioning": [
            {
                "code": "COM-ST-01",
                "name": "Test d'étanchéité sensible Hélium-Azote (He/N2 Gross & Sensitive Leak Test)",
                "description": "Mise sous pression à 95% de la pression de service avec un mélange 95% N2 / 5% Hélium, reniflage des brides et presse-étoupes au spectromètre de masse (critère de fuite < 0.01 kg/an).",
                "unite": "système",
                "duree_jours": 2.0,
                "checksheet_type": "B-SHEET (Étanchéité)",
                "equipe": [{"role": "Ingénieur Spécialiste Leak Testing", "effectif": 1}, {"role": "Technicien spectrométrie", "effectif": 2}],
                "ressources": ["Spectromètre de masse hélium portatif", "Bouteilles d'Hélium et Azote liquide haute pureté"]
            },
            {
                "code": "COM-ST-02",
                "name": "Inertage à l'azote gazeux jusqu'à O2 < 0.5% (Oxygen Freeing)",
                "description": "Purge continue à l'azote jusqu'à ce que la teneur en oxygène résiduel soit inférieure à 0.5% vol pour éliminer tout risque d'atmosphère explosive avant introduction d'hydrocarbures.",
                "unite": "u (capacité)",
                "duree_jours": 1.0,
                "checksheet_type": "B-SHEET (Sécurité Gaz)",
                "equipe": [{"role": "Opérateur inertage", "effectif": 2}, {"role": "Agent HSE contrôleur gaz", "effectif": 1}],
                "ressources": ["Analyseur d'oxygène O2 portable certifié ATEX", "Tuyaux de purge cryogéniques"]
            },
            {
                "code": "COM-ST-03",
                "name": "Introduction progressive des hydrocarbures (Live Hydrocarbon In-feed & First Oil/Gas)",
                "description": "Ouverture contrôlée des vannes d'admission de brut/gaz, montée en pression graduelle, contrôle des niveaux et surveillance des étanchéités en direct (Ready For Start-Up validé).",
                "unite": "jalon procédé",
                "duree_jours": 1.0,
                "checksheet_type": "B-SHEET (Démarrage)",
                "equipe": [{"role": "Commissioning Manager", "effectif": 1}, {"role": "Chef de Quart Exploitation", "effectif": 1}, {"role": "Opérateurs console DCS", "effectif": 2}],
                "ressources": ["Console DCS / SCADA active", "Radios VHF ATEX"]
            },
            {
                "code": "COM-ST-04",
                "name": "Marche de performance continue 72h (Performance Guarantee Run - PGR)",
                "description": "Fonctionnement à 100% de la charge nominale pendant 72h continues, vérification de la pureté du gaz de tête, teneur en eau (BS&W < 0.5%) et rejet d'huile dans l'eau produite.",
                "unite": "test 72h",
                "duree_jours": 3.0,
                "checksheet_type": "B-SHEET (Performance)",
                "equipe": [{"role": "Ingénieur Procédé", "effectif": 2}, {"role": "Chimiste de laboratoire site", "effectif": 2}],
                "ressources": ["Laboratoire mobile d'analyse d'hydrocarbures", "Centrifugeuse BS&W", "Titreur Karl Fischer"]
            }
        ]
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 2. UNITÉ DE DÉSHYDRATATION DU GAZ AU GLYCOL (TEG)
    # ──────────────────────────────────────────────────────────────────────────
    "GLYCOL_DEHYDRATION_TEG": {
        "category": "PROCESS_PACKAGE",
        "label": "Unité de Déshydratation du Gaz au Triéthylène Glycol (TEG Contactor & Regenerator)",
        "codes_standards": ["GPSA Section 20", "ASME VIII", "API 12G", "ISO 13628"],
        "precommissioning": [
            {
                "code": "PC-TEG-01",
                "name": "Inspection des plateaux à calottes et garnissage de la colonne de contact (Trays & Structured Packing)",
                "description": "Contrôle d'horizontalité des plateaux de barbotage, propreté de la zone de débrumisation supérieure, serrage des brides internes.",
                "unite": "colonne TEG",
                "duree_jours": 2.0,
                "checksheet_type": "A-SHEET (Internes)",
                "equipe": [{"role": "Inspecteur QA/QC Colonnes", "effectif": 1}, {"role": "Monteur mécanique", "effectif": 2}],
                "ressources": ["Niveau optique de précision", "Clé dynamométrique étalonnée"]
            },
            {
                "code": "PC-TEG-02",
                "name": "Rinçage chimique et dégraissage du circuit TEG (Degreasing & Hot Water Flushing)",
                "description": "Circulation d'eau chaude avec surfactant biodégradable pour éliminer les huiles de protection des tubes et du rebouilleur, suivi d'un rinçage à l'eau déminéralisée.",
                "unite": "boucle glycol",
                "duree_jours": 2.5,
                "checksheet_type": "A-SHEET (Nettoyage)",
                "equipe": [{"role": "Opérateur de rinçage chimique", "effectif": 2}],
                "ressources": ["Groupe de pompage temporaire", "Kit de test pH et conductivité"]
            },
            {
                "code": "PC-TEG-03",
                "name": "Test d'allumage à blanc du brûleur du rebouilleur TEG (Reboiler Burner BMS Cold Test)",
                "description": "Test complet de la séquence d'allumage du Burner Management System (BMS), vérification du balayage d'air (purge time > 30s) et coupure gaz pilote par cellule UV.",
                "unite": "rebouilleur",
                "duree_jours": 1.5,
                "checksheet_type": "A-SHEET (Sécurité BMS)",
                "equipe": [{"role": "Spécialiste Brûleurs & Fours", "effectif": 1}, {"role": "Instrumentiste BMS", "effectif": 1}],
                "ressources": ["Simulateur de flamme UV ATEX", "Chronomètre étalonné"]
            }
        ],
        "commissioning": [
            {
                "code": "COM-TEG-01",
                "name": "Chargement du TEG pur et établissement de la circulation à chaud (TEG Loading & Circulation)",
                "description": "Chargement sous vide du triéthylène glycol (pureté > 99.5%), démarrage des pompes de circulation haute pression (Kimray / Milton Roy) et montée en température du rebouilleur à 204°C.",
                "unite": "unité TEG",
                "duree_jours": 2.0,
                "checksheet_type": "B-SHEET (Fluides)",
                "equipe": [{"role": "Opérateur procédé TEG", "effectif": 2}, {"role": "Chimiste de site", "effectif": 1}],
                "ressources": ["Réfractomètre numérique BRIX/Glycol", "Fûts de TEG vierge grade pétrolier"]
            },
            {
                "code": "COM-TEG-02",
                "name": "Admission de gaz humide & mesure du point de rosée eau (Dew Point < -15°C à 70 bar)",
                "description": "Mise en service du gaz de stripping d'azote, admission progressive du gaz naturel humide et mesure continue du point de rosée eau par hygromètre à miroir refroidi.",
                "unite": "test gaz",
                "duree_jours": 2.0,
                "checksheet_type": "B-SHEET (Performance Procédé)",
                "equipe": [{"role": "Ingénieur Traitement de Gaz", "effectif": 1}, {"role": "Opérateur console DCS", "effectif": 1}],
                "ressources": ["Hygromètre Chilled Mirror Michell Instruments", "Chromatographe en ligne"]
            }
        ]
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 3. UNITÉ DE TRAITEMENT DU GAZ AUX AMINES (MDEA / DÉACIDIFICATION)
    # ──────────────────────────────────────────────────────────────────────────
    "AMINE_SWEETENING_UNIT": {
        "category": "PROCESS_PACKAGE",
        "label": "Unité de Traitement des Gaz Acides aux Amines (MDEA / Décarbonatation & Désulfuration)",
        "codes_standards": ["GPSA Section 21", "NACE MR0175 / ISO 15156", "ASME VIII Div.1"],
        "precommissioning": [
            {
                "code": "PC-AM-01",
                "name": "Passivation chimique et dégraissage des colonnes et échangeurs (Alkaline Boil-out & Passivation)",
                "description": "Traitement chimique alcalin pour éliminer la calamine et former une couche protectrice de magnétite (Fe3O4) sur les aciers carbone pour résister à la corrosion par l'amine.",
                "unite": "unité amine",
                "duree_jours": 3.0,
                "checksheet_type": "A-SHEET (Chimie)",
                "equipe": [{"role": "Ingénieur Chimiste Spécialiste Amines", "effectif": 1}, {"role": "Opérateurs traitement", "effectif": 3}],
                "ressources": ["Centrale mobile de traitement chimique", "Cuves de neutralisation des effluents"]
            },
            {
                "code": "PC-AM-02",
                "name": "Épreuve hydrostatique et étanchéité de l'absorbeur HP et régénérateur LP",
                "description": "Épreuve hydraulique à l'eau traitée avec inhibiteur, contrôle des étanchéités de calandre des échangeurs Amine Riche / Amine Pauvre.",
                "unite": "colonnes & échangeurs",
                "duree_jours": 2.5,
                "checksheet_type": "A-SHEET (Pression)",
                "equipe": [{"role": "Superviseur Épreuve", "effectif": 1}, {"role": "Inspecteur ARH", "effectif": 1}],
                "ressources": ["Pompe d'épreuve HP", "Manomètres étalonnés classe 0.5"]
            }
        ],
        "commissioning": [
            {
                "code": "COM-AM-01",
                "name": "Chargement de la solution MDEA activée et test de moussage (Amine Loading & Anti-Foam Test)",
                "description": "Remplissage en MDEA formulée (45% massique), mise en circulation à chaud, injection du produit antimousse et réglage des filtres à charbon actif.",
                "unite": "boucle MDEA",
                "duree_jours": 2.0,
                "checksheet_type": "B-SHEET (Mise en Solution)",
                "equipe": [{"role": "Spécialiste Fournisseur Amine (BASF / Dow / TotalEnergies)", "effectif": 1}, {"role": "Opérateur procédé", "effectif": 2}],
                "ressources": ["Appareil de mesure de moussage (Foam Test Kit)", "Titreur acido-basique de concentration MDEA"]
            },
            {
                "code": "COM-AM-02",
                "name": "Admission du gaz acide et vérification de la spécification H2S < 4 ppm & CO2 < 2%",
                "description": "Introduction progressive du gaz brut contenant H2S et CO2, équilibrage thermique du rebouilleur et analyse continue des teneurs en gaz acide dans le gaz traité de tête.",
                "unite": "test performance gaz",
                "duree_jours": 3.0,
                "checksheet_type": "B-SHEET (Spécification Export)",
                "equipe": [{"role": "Ingénieur Procédé Senior", "effectif": 1}, {"role": "Technicien Laboratoire Chromatographie", "effectif": 2}],
                "ressources": ["Analyseur H2S par UV / Ruban acétate de plomb", "Chromatographe de gaz naturel en ligne"]
            }
        ]
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 4. COMPRESSEURS CENTRIFUGES & TURBINES À GAZ
    # ──────────────────────────────────────────────────────────────────────────
    "CENTRIFUGAL_COMPRESSOR_TRAIN": {
        "category": "ROTATING_EQUIPMENT",
        "label": "Train de Compression Centrifuge de Gaz (Turbine à Gaz / Moteur Électrique + Compresseur)",
        "codes_standards": ["API 617", "API 614", "API 670", "ISO 10438", "Décret 21-261"],
        "precommissioning": [
            {
                "code": "PC-CMP-01",
                "name": "Rinçage chimique et huilage du circuit d'huile de lubrification (Lube Oil Flushing - ISO 4406)",
                "description": "Circulation continue de l'huile de lubrification à chaud avec chocs thermiques, filtration jusqu'à obtention de la classe de propreté ISO 4406 (15/13/10) validée sur tamis 100 mesh.",
                "unite": "circuit d'huile",
                "duree_jours": 4.0,
                "checksheet_type": "A-SHEET (Mécanique)",
                "equipe": [{"role": "Superviseur Machines Tournantes", "effectif": 1}, {"role": "Mécaniciens régleurs", "effectif": 3}],
                "ressources": ["Groupe de filtration d'huile 3 microns externe", "Compteur de particules laser portable", "Béchers de prélèvement d'huile"]
            },
            {
                "code": "PC-CMP-02",
                "name": "Alignement laser à froid & vérification des contraintes tuyauteries (Cold Alignment & Pipe Strain)",
                "description": "Alignement précis au comparateur laser entre turbine, multiplicateur et compresseur, mesure du Soft Foot (< 0.05 mm) et test de contrainte de tuyauterie aux brides d'aspiration/refoulement (< 0.05 mm de déflexion).",
                "unite": "train complet",
                "duree_jours": 2.0,
                "checksheet_type": "A-SHEET (Mécanique)",
                "equipe": [{"role": "Spécialiste Alignement Laser", "effectif": 1}, {"role": "Mécanicien ajusteur", "effectif": 2}],
                "ressources": ["Appareil d'alignement laser Prüftechnik / Easy-Laser", "Comparateurs à cadran 1/100e"]
            },
            {
                "code": "PC-CMP-03",
                "name": "Calibration et test de la chaîne de protection vibratoire API 670 (Bentley Nevada Probes)",
                "description": "Vérification des sondes de proximité à courants de Foucault (déplacement radial, position axiale, Keyphasor, température paliers Pt100) et simulation des seuils d'alarme et déclenchement (Trip).",
                "unite": "système API 670",
                "duree_jours": 2.0,
                "checksheet_type": "A-SHEET (Instrumentation)",
                "equipe": [{"role": "Ingénieur Vibratoire / Instrumentation", "effectif": 1}, {"role": "Technicien instruments", "effectif": 2}],
                "ressources": ["Générateur de signaux TK-3 Bentley Nevada", "Valise de calibration de sondes de déplacement"]
            },
            {
                "code": "PC-CMP-04",
                "name": "Essai de rotation à vide du moteur d'entraînement (Uncoupled Motor Solo Run 4h)",
                "description": "Essai de rotation découplé du moteur pendant 4h continues avec relevé toutes les 15 min des vibrations, température des enroulements et équilibre des courants des 3 phases.",
                "unite": "moteur",
                "duree_jours": 1.0,
                "checksheet_type": "A-SHEET (Électricité)",
                "equipe": [{"role": "Ingénieur Électrique", "effectif": 1}, {"role": "Électricien haute tension", "effectif": 2}],
                "ressources": ["Analyseur de spectre vibratoire FFT", "Caméra thermique infrarouge Fluke"]
            }
        ],
        "commissioning": [
            {
                "code": "COM-CMP-01",
                "name": "Mise en service du système de garnitures mécaniques à gaz sec (Dry Gas Seal - DGS Conditioning)",
                "description": "Alimentation en azote/gaz propre filtré, contrôle des débits de fuite primaire et secondaire, vérification des pressions différentielles de barrière et des clapets anti-retour.",
                "unite": "système DGS",
                "duree_jours": 2.0,
                "checksheet_type": "B-SHEET (Procédé/Mécanique)",
                "equipe": [{"role": "Représentant Constructeur (John Crane / EagleBurgmann)", "effectif": 1}, {"role": "Technicien machines", "effectif": 2}],
                "ressources": ["Panneau de contrôle DGS calibré", "Débitmètres massiques de fuite gaz"]
            },
            {
                "code": "COM-CMP-02",
                "name": "Validation dynamique de la boucle de régulation anti-pompage (Anti-Surge Dynamic Tuning)",
                "description": "Test de réponse rapide de la vanne de recyclage anti-pompage (temps d'ouverture < 1.0 sec), tracé de la courbe limite de pompage et paramétrage du contrôleur CCC / Yokogawa.",
                "unite": "boucle anti-pompage",
                "duree_jours": 2.0,
                "checksheet_type": "B-SHEET (Automatisme)",
                "equipe": [{"role": "Expert Anti-Surge CCC (Compressor Controls Corp)", "effectif": 1}, {"role": "Ingénieur DCS", "effectif": 1}],
                "ressources": ["Enregistreur de transitoires haute fréquence", "Logiciel de diagnostic compresseur"]
            },
            {
                "code": "COM-CMP-03",
                "name": "Premier démarrage en charge de gaz & montée en vitesse (First Start on Gas & Speed Ramp-up)",
                "description": "Pressurisation lente du compresseur au gaz procédé, lancement de la séquence de démarrage automatique, passage des vitesses critiques sans résonance et mise en charge à 50% puis 100%.",
                "unite": "train de compression",
                "duree_jours": 2.0,
                "checksheet_type": "B-SHEET (Démarrage)",
                "equipe": [{"role": "Commissioning Lead", "effectif": 1}, {"role": "Spécialiste Constructeur Baker Hughes / Solar", "effectif": 1}, {"role": "Opérateur console", "effectif": 2}],
                "ressources": ["Système de supervision DCS en temps réel", "Équipements de protection auditive et EPI ATEX"]
            },
            {
                "code": "COM-CMP-04",
                "name": "Marche de garantie de performance thermodynamique 72h (Polytropic Head & Efficiency Test)",
                "description": "Vérification continue du taux de compression, du rendement polytropique, de la puissance absorbée et de la stabilité des paliers selon ASME PTC 10.",
                "unite": "test 72h",
                "duree_jours": 3.0,
                "checksheet_type": "B-SHEET (Performance ASME PTC 10)",
                "equipe": [{"role": "Ingénieur Thermodynamique Procédé", "effectif": 1}, {"role": "Inspecteur ARH", "effectif": 1}],
                "ressources": ["Chromatographe en phase gazeuse en ligne (Composition MW, Z-factor)", "Capteurs de pression/température haute précision étalonnés"]
            }
        ]
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 5. COMPRESSEURS ALTERNATIFS À PISTONS (RECIPROCATING API 618)
    # ──────────────────────────────────────────────────────────────────────────
    "RECIPROCATING_COMPRESSOR_API618": {
        "category": "ROTATING_EQUIPMENT",
        "label": "Compresseur Alternatif à Pistons Haute Pression (Gaz Lift / Injection API 618)",
        "codes_standards": ["API 618", "API 688 (Pulsations)", "NACE MR0175"],
        "precommissioning": [
            {
                "code": "PC-REC-01",
                "name": "Contrôle du jeu de bielle, alignement vilebrequin et flèche de tige (Piston Rod Drop & Web Deflection)",
                "description": "Mesure des déflexions des bras de manivelle du vilebrequin aux comparateurs à cadran, contrôle du jeu aux segments et montage des bouteilles anti-pulsatoires.",
                "unite": "compresseur",
                "duree_jours": 2.5,
                "checksheet_type": "A-SHEET (Mécanique Lourd)",
                "equipe": [{"role": "Spécialiste Compresseurs Alternatifs Dresser/Ariel", "effectif": 1}, {"role": "Mécanicien", "effectif": 2}],
                "ressources": ["Jauge de déflexion vilebrequin (Crankshaft Deflection Gauge)", "Capteurs de Rod Drop inductifs étalonnés"]
            },
            {
                "code": "PC-REC-02",
                "name": "Rinçage et purge des cylindres et circuits de lubrification forcée (Force Feed Lubrication)",
                "description": "Contrôle du débit goutte-à-goutte des pompes doseuses de lubrification des garnitures de tige et clapets d'aspiration/refoulement.",
                "unite": "système lubrification",
                "duree_jours": 1.5,
                "checksheet_type": "A-SHEET (Lubrification)",
                "equipe": [{"role": "Mécanicien régleur", "effectif": 2}],
                "ressources": ["Débitmètre de micro-injection d'huile", "Huile synthétique haute viscosité"]
            }
        ],
        "commissioning": [
            {
                "code": "COM-REC-01",
                "name": "Démarrage à vide sous azote avec déchargeurs de clapets ouverts (Unloaded Run on N2)",
                "description": "Rotation 2h sous azote à vide avec clapets déchargés par vérins pneumatiques (Finger unloader), vérification de la montée en température des cylindres et de l'absence de chocs.",
                "unite": "essai à vide",
                "duree_jours": 1.5,
                "checksheet_type": "B-SHEET (Essai à vide)",
                "equipe": [{"role": "Superviseur Commissioning", "effectif": 1}, {"role": "Opérateur terrain", "effectif": 2}],
                "ressources": ["Thermomètre infrarouge de contact", "Stéthoscope acoustique de mécanicien"]
            },
            {
                "code": "COM-REC-02",
                "name": "Mise en charge progressive au gaz et analyse acoustique des pulsations de pression",
                "description": "Fermeture séquentielle des déchargeurs de clapets (25%, 50%, 75%, 100% de charge), mesure des niveaux de vibrations sur tuyauteries selon API 688.",
                "unite": "essai en charge",
                "duree_jours": 2.0,
                "checksheet_type": "B-SHEET (Pulsations API 688)",
                "equipe": [{"role": "Expert Vibratoire et Pulsations Acoustiques", "effectif": 1}, {"role": "Opérateur console", "effectif": 1}],
                "ressources": ["Capteurs de pression dynamique piézo-électriques Kistler", "Analyseur FFT multi-voies"]
            }
        ]
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 6. BACS DE STOCKAGE PÉTROLE BRUT & CONDENSATS API 650
    # ──────────────────────────────────────────────────────────────────────────
    "STORAGE_TANK_API650": {
        "category": "STATIC_EQUIPMENT",
        "label": "Bac de Stockage Pétrole Brut / Condensat (Toit Flottant / Toit Fixe API 650)",
        "codes_standards": ["API 650", "API 653", "Décret 21-315", "NFPA 11"],
        "precommissioning": [
            {
                "code": "PC-TK-01",
                "name": "Contrôle d'étanchéité du fond par boîte à vide (Vacuum Box Test des soudures)",
                "description": "Contrôle à 100% des cordons de soudure du fond de bac à la boîte à vide savonneuse sous dépression de -500 mbar.",
                "unite": "ml de soudure",
                "duree_jours": 3.0,
                "checksheet_type": "A-SHEET (CND Fond)",
                "equipe": [{"role": "Contrôleur CND Niveau II", "effectif": 2}],
                "ressources": ["Boîte à vide rectangulaire et d'angle", "Compresseur d'air comprimé", "Solution moussante certifiée"]
            },
            {
                "code": "PC-TK-02",
                "name": "Épreuve hydrostatique complète & mesure des tassements différentiels (Hydrotest & Settlement)",
                "description": "Remplissage progressif du bac en 4 paliers (25%, 50%, 75%, 100%), relevé topographique des tassements sur chaque repère de virole et maintien en charge 48h.",
                "unite": "bac",
                "duree_jours": 7.0,
                "checksheet_type": "A-SHEET (Hydrotest Bac)",
                "equipe": [{"role": "Superviseur Épreuve", "effectif": 1}, {"role": "Topographe géomètre", "effectif": 2}, {"role": "Inspecteur ARH", "effectif": 1}],
                "ressources": ["Pompe de remplissage gros débit (500 m³/h)", "Niveau optique de haute précision / Station totale", "Capteurs de tassement"]
            },
            {
                "code": "PC-TK-03",
                "name": "Essai de flottabilité et joint d'étanchéité du toit flottant (Floating Roof & Seal Test)",
                "description": "Vérification de la liberté de mouvement du toit lors de la montée/descente d'eau, contrôle du jeu annulaire (rim space) et inspection du joint primaire/secondaire.",
                "unite": "toit",
                "duree_jours": 2.0,
                "checksheet_type": "A-SHEET (Mécanique)",
                "equipe": [{"role": "Monteur mécanique bacs", "effectif": 3}, {"role": "Inspecteur QA/QC", "effectif": 1}],
                "ressources": ["Piges de mesure d'intervalle annulaire", "Harnais de sécurité pour toiture"]
            },
            {
                "code": "PC-TK-04",
                "name": "Essai des couronnes d'arrosage et injection de mousse anti-incendie (Deluge & Foam System Test)",
                "description": "Essai de débit réel de la couronne de refroidissement de robe et des déversoirs de mousse bas foisonnement.",
                "unite": "système incendie",
                "duree_jours": 1.5,
                "checksheet_type": "A-SHEET (Sécurité Incendie)",
                "equipe": [{"role": "Ingénieur Sécurité Incendie", "effectif": 1}, {"role": "Pompier industriel / Technicien réseau", "effectif": 3}],
                "ressources": ["Manomètres d'extrémité de couronne", "Débitmètre à ultrasons portable", "Bac de récupération d'émulseur"]
            }
        ],
        "commissioning": [
            {
                "code": "COM-TK-01",
                "name": "Étalonnage du système de jaugeage haute précision (Radar Tank Gauge & Servo Proving)",
                "description": "Vérification de la chaîne de mesure de niveau radar / servo-jaugeur, étalonnage du tableau de barémage officiel (Strapping Table) avec visa de l'ONML.",
                "unite": "bac",
                "duree_jours": 2.0,
                "checksheet_type": "B-SHEET (Instrumentation)",
                "equipe": [{"role": "Spécialiste Comptage Transactionnel", "effectif": 1}, {"role": "Inspecteur Métrologie Légale (ONML)", "effectif": 1}],
                "ressources": ["Ruban de jaugeage étalonné avec plomb", "Thermomètre électronique de fond", "Table de barémage certifiée"]
            },
            {
                "code": "COM-TK-02",
                "name": "Mise en service du système de protection cathodique du fond (Impressed Current CP)",
                "description": "Mesure des potentiels de polarisation ON/OFF sur les coupons témoins et réglage du transformateur-redresseur de courant imposé.",
                "unite": "bac",
                "duree_jours": 1.0,
                "checksheet_type": "B-SHEET (Électricité/Corrosion)",
                "equipe": [{"role": "Ingénieur Protection Cathodique (NACE CP Level 3)", "effectif": 1}],
                "ressources": ["Électrode de référence Cu/CuSO4 saturée", "Multimètre haute impédance étalonné"]
            },
            {
                "code": "COM-TK-03",
                "name": "Premier remplissage en hydrocarbures (Initial Oil-in & Flange Sniffing)",
                "description": "Introduction du brut à vitesse réduite (< 1 m/s pour limiter l'électricité statique) jusqu'au décollement complet du toit flottant, surveillance continue de l'étanchéité.",
                "unite": "bac",
                "duree_jours": 2.0,
                "checksheet_type": "B-SHEET (Démarrage)",
                "equipe": [{"role": "Chef d'exploitation stockage", "effectif": 1}, {"role": "Opérateurs de pomperie", "effectif": 3}],
                "ressources": ["Explosimètre portable certifié ATEX", "Liaison équipotentielle de mise à la terre vérifiée (< 5 Ohms)"]
            }
        ]
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 7. SYSTÈME TORCHE, BRÛLEURS & BALLON KNOCK-OUT DRUM
    # ──────────────────────────────────────────────────────────────────────────
    "FLARE_SYSTEM_AND_IGNITION": {
        "category": "SAFETY_UTILITIES",
        "label": "Système de Torche HP/BP, Brûleurs sans fumée & Ballon de Torche (Knock-Out Drum)",
        "codes_standards": ["API 521", "API 537", "ISO 23251", "Décret 21-261"],
        "precommissioning": [
            {
                "code": "PC-FLR-01",
                "name": "Épreuve hydrostatique et propreté interne du ballon d'abattage de torche (KO Drum Hydro & Cleanliness)",
                "description": "Contrôle du débrumisateur inox interne, épreuve hydrostatique du KO Drum et de la ligne de décharge vers les pompes de reprise de condensats.",
                "unite": "KO Drum",
                "duree_jours": 1.5,
                "checksheet_type": "A-SHEET (Pression)",
                "equipe": [{"role": "Superviseur Épreuve", "effectif": 1}, {"role": "Monteur", "effectif": 2}],
                "ressources": ["Pompe hydro", "Manomètres 0.5"]
            },
            {
                "code": "PC-FLR-02",
                "name": "Contrôle à froid du système d'allumage des veilleuses (Pilot Gas & High Energy Spark Igniters)",
                "description": "Vérification des lignes de gaz combustible de veilleuses, étincelles des allumeurs haute énergie (High Energy Igniters) et détection de flamme par thermocouple et ionisation.",
                "unite": "nez de torche",
                "duree_jours": 2.0,
                "checksheet_type": "A-SHEET (Instrumentation/Torche)",
                "equipe": [{"role": "Spécialiste Torches (Zeeco / John Zink)", "effectif": 1}, {"role": "Instrumentiste", "effectif": 1}],
                "ressources": ["Console d'allumage torche", "Générateur d'étincelles de test"]
            }
        ],
        "commissioning": [
            {
                "code": "COM-FLR-01",
                "name": "Mise en service du gaz de balayage (Purge Gas & Velocity Seal) pour éliminer les retours d'air",
                "description": "Injection continue de gaz combustible ou d'azote de balayage à débit régulé pour maintenir une vitesse positive dans le fût de torche et empêcher les retours de flamme.",
                "unite": "torche",
                "duree_jours": 1.0,
                "checksheet_type": "B-SHEET (Sécurité Torche)",
                "equipe": [{"role": "Opérateur utilités", "effectif": 2}],
                "ressources": ["Débitmètre massique de purge", "Analyseur O2 en tête"]
            },
            {
                "code": "COM-FLR-02",
                "name": "Allumage réel des pilotes et test de décharge sous torche (Flare Ignition & Blowdown Live Test)",
                "description": "Allumage continu des 3 pilotes, vérification du retour d'état flamme au DCS et premier test d'ouverture d'une vanne de dépressurisation d'urgence (BDV).",
                "unite": "système complet torche",
                "duree_jours": 1.5,
                "checksheet_type": "B-SHEET (Démarrage)",
                "equipe": [{"role": "Commissioning Lead", "effectif": 1}, {"role": "Pompier industriel HSE", "effectif": 2}, {"role": "Opérateur DCS", "effectif": 1}],
                "ressources": ["Caméra thermique infrarouge longue portée", "Radios VHF sécurisées"]
            }
        ]
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 8. GROUPES ÉLECTRO-POMPES CENTRIFUGES INDUSTRIELLES API 610
    # ──────────────────────────────────────────────────────────────────────────
    "CENTRIFUGAL_PUMP_PACKAGE": {
        "category": "ROTATING_EQUIPMENT",
        "label": "Groupe Électro-Pompe Centrifuge (Brut / Eau d'injection / Produits chimiques)",
        "codes_standards": ["API 610 (OH2 / BB2 / BB3 / VS4)", "API 682 (Garnitures)", "ISO 5199"],
        "precommissioning": [
            {
                "code": "PC-PMP-01",
                "name": "Vérification mécanique & alignement laser pompe/moteur",
                "description": "Contrôle du jeu axial/radial, vérification du plan de garniture (API Plan 11/52/53), alignement laser à froid (< 0.05 mm d'écart angulaire et parallèle).",
                "unite": "groupe pompe",
                "duree_jours": 1.0,
                "checksheet_type": "A-SHEET (Mécanique)",
                "equipe": [{"role": "Mécanicien ajusteur qualifié", "effectif": 2}],
                "ressources": ["Laser d'alignement", "Jeu de cales d'épaisseur inox calibrées"]
            },
            {
                "code": "PC-PMP-02",
                "name": "Essai de rotation à vide du moteur électrique (Motor Solo Run 2h)",
                "description": "Contrôle du sens de rotation (Phase rotation check), mesure des courants à vide, des vibrations aux paliers et de la température.",
                "unite": "moteur",
                "duree_jours": 0.5,
                "checksheet_type": "A-SHEET (Électricité)",
                "equipe": [{"role": "Électricien industriel", "effectif": 2}],
                "ressources": ["Pince ampèremétrique TRMS", "Vibromètre portable"]
            },
            {
                "code": "PC-PMP-03",
                "name": "Rinçage de la tuyauterie d'aspiration & contrôle du filtre temporaire (Suction Strainer Check)",
                "description": "Rinçage de la ligne d'aspiration, démontage et nettoyage du filtre à cône temporaire (100 mesh) jusqu'à propreté parfaite avant accouplement définitif.",
                "unite": "ligne d'aspiration",
                "duree_jours": 1.0,
                "checksheet_type": "A-SHEET (Tuyauterie)",
                "equipe": [{"role": "Tuyauteur", "effectif": 2}],
                "ressources": ["Filtre à chapeau chinois temporaire inox", "Manomètre différentiel"]
            }
        ],
        "commissioning": [
            {
                "code": "COM-PMP-01",
                "name": "Amorçage, mise sous fluide & essai couplé à l'eau ou au produit (Coupled Run 4h)",
                "description": "Purge d'air de la volute, ouverture de l'aspiration, démarrage vanne de refoulement fermée puis ouverture progressive, mesure du débit, pression différentielle (HMT) et puissance consommée.",
                "unite": "pompe",
                "duree_jours": 1.0,
                "checksheet_type": "B-SHEET (Fonctionnel)",
                "equipe": [{"role": "Opérateur de pomperie", "effectif": 2}, {"role": "Inspecteur QA/QC", "effectif": 1}],
                "ressources": ["Débitmètre portable à ultrasons", "Thermo-caméra infrarouge"]
            },
            {
                "code": "COM-PMP-02",
                "name": "Test de basculement automatique de la pompe de secours (Auto-Standby Changeover Test)",
                "description": "Simulation de la panne de la pompe principale (déclenchement électrique ou baisse de pression de refoulement) et vérification du démarrage automatique de la pompe de secours en moins de 3 secondes.",
                "unite": "duo de pompes (1+1)",
                "duree_jours": 0.5,
                "checksheet_type": "B-SHEET (Automatisme/ESD)",
                "equipe": [{"role": "Technicien DCS / Automatisme", "effectif": 1}, {"role": "Opérateur console", "effectif": 1}],
                "ressources": ["Console DCS", "Chronomètre numérique étalonné"]
            }
        ]
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 9. CONTRÔLE-COMMANDE DCS, AUTOMATE ESD/SIS & DÉTECTION FEU ET GAZ
    # ──────────────────────────────────────────────────────────────────────────
    "INSTRUMENTATION_DCS_SIS": {
        "category": "AUTOMATION_SAFETY",
        "label": "Système de Contrôle-Commande DCS, Automate de Sécurité ESD/SIS & Système Feu et Gaz (F&G)",
        "codes_standards": ["IEC 61511", "IEC 61508", "ISA 84", "API RP 14C", "NFPA 72"],
        "precommissioning": [
            {
                "code": "PC-INS-01",
                "name": "Étalonnage 5 points en atelier des transmetteurs de pression, niveau, débit et température",
                "description": "Calibration sur banc d'étalonnage à 0%, 25%, 50%, 75% et 100% de l'échelle (montée et descente), réglage du zéro et de la sensibilité HART / Fieldbus.",
                "unite": "transmetteur",
                "duree_jours": 0.2,
                "checksheet_type": "A-SHEET (Étalonnage)",
                "equipe": [{"role": "Technicien Instrumentiste de laboratoire", "effectif": 1}],
                "ressources": ["Générateur de pression étalon Fluke 754 / Beamex MC6", "Bain d'étalonnage de température à puits sec (-25°C à +150°C)"]
            },
            {
                "code": "PC-INS-02",
                "name": "Test de boucle à froid (Cold Loop Checking complet Terrain -> JB -> DCS/ESD)",
                "description": "Injection d'un signal analogique 4-20mA au transmetteur de terrain, vérification de la continuité, de la polarité, de l'adresse de la carte d'E/S et de l'affichage exact sur la vue synoptique du DCS.",
                "unite": "boucle de contrôle",
                "duree_jours": 0.3,
                "checksheet_type": "A-SHEET (Boucle)",
                "equipe": [{"role": "Instrumentiste terrain", "effectif": 1}, {"role": "Opérateur console DCS", "effectif": 1}],
                "ressources": ["Calibrateur de boucle 4-20mA / HART Communicator 475", "Radios VHF ATEX"]
            },
            {
                "code": "PC-INS-03",
                "name": "Contrôle de course et étalonnage du positionneur des vannes de régulation & ESDV",
                "description": "Vérification des courses d'ouverture/fermeture (0-100%), temps de manœuvre de sécurité (< 2 sec pour ESDV), étalonnage du positionneur intelligent et test d'étanchéité de la garniture.",
                "unite": "vanne motorisée / pneumatique",
                "duree_jours": 0.5,
                "checksheet_type": "A-SHEET (Robinetterie Instrumentée)",
                "equipe": [{"role": "Spécialiste Vannes de régulation (Fisher / Masoneilan)", "effectif": 1}],
                "ressources": ["Banc de test de positionneur Fieldvue / ValVue", "Chronomètre numérique étalonné"]
            },
            {
                "code": "PC-INS-04",
                "name": "Étalonnage et test au gaz étalon des détecteurs Feu & Gaz (F&G Detectors Calibration)",
                "description": "Test des détecteurs de flamme optiques UV/IR avec lampe test d'étincelle, étalonnage des détecteurs de gaz toxique H2S et explosif LEL au mélange de gaz étalon certifié.",
                "unite": "détecteur F&G",
                "duree_jours": 0.25,
                "checksheet_type": "A-SHEET (Sécurité F&G)",
                "equipe": [{"role": "Technicien certifié F&G", "effectif": 2}],
                "ressources": ["Bouteilles de gaz étalon calibrées (Méthane 50% LEL, H2S 20 ppm)", "Lampe d'épreuve de flamme certifiée ATEX"]
            }
        ],
        "commissioning": [
            {
                "code": "COM-INS-01",
                "name": "Test fonctionnel de la matrice Causes et Effets & déclenchement ESD complet (Live C&E Testing)",
                "description": "Simulation réelle de chaque condition de cause (niveau très haut LAHH, pression très haute PAHH, détection feu confirmée) et validation des effets (fermeture ESDV, arrêt compresseurs, déclenchement déluge).",
                "unite": "système ESD/SIS complet",
                "duree_jours": 3.0,
                "checksheet_type": "B-SHEET (Sécurité Fonctionnelle)",
                "equipe": [{"role": "Lead Commissioning Automatisme", "effectif": 1}, {"role": "Ingénieur Sécurité SIS / SIL", "effectif": 1}, {"role": "Inspecteur TPI / ARH", "effectif": 1}],
                "ressources": ["Console d'ingénierie automate Triconex / HIMA / Yokogawa ProSafe", "Journal d'événements SOE (Sequence of Events à la milliseconde)"]
            },
            {
                "code": "COM-INS-02",
                "name": "Tuning dynamique des boucles PID en conditions réelles de procédé (Dynamic PID Loop Tuning)",
                "description": "Optimisation des paramètres P (Proportionnel), I (Intégral) et D (Dérivé) sur les régulations de pression, niveau de séparateur, température de four et débit de recycle pour éviter les oscillations.",
                "unite": "boucle PID",
                "duree_jours": 0.5,
                "checksheet_type": "B-SHEET (Régulation)",
                "equipe": [{"role": "Ingénieur Régulation Avancée APC", "effectif": 1}],
                "ressources": ["Outil d'analyse et de modélisation de boucle Expertune / PlantTriage"]
            },
            {
                "code": "COM-INS-03",
                "name": "Délivrance de l'attestation Ready For Start-Up (RFSU) & levée des réserves Catégorie A",
                "description": "Revue finale de conformité avec la commission ARH et le client, vérification de la levée à 100% des réserves bloquantes Catégorie A et signature du PV officiel de mise en service.",
                "unite": "jalon contractuel",
                "duree_jours": 1.0,
                "checksheet_type": "B-SHEET (Visa Officiel ARH)",
                "equipe": [{"role": "Commissioning Manager", "effectif": 1}, {"role": "Directeur de Projet EPC", "effectif": 1}, {"role": "Chef de Département ARH", "effectif": 1}],
                "ressources": ["Dossier complet des Check-Sheets et Test-Sheets ICAPS signés"]
            }
        ]
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 10. SOUS-STATIONS ÉLECTRIQUES, TRANSFORMATEURS & SWITCHGEAR HT/BT
    # ──────────────────────────────────────────────────────────────────────────
    "ELECTRICAL_SUBSTATION_SWITCHGEAR": {
        "category": "ELECTRICAL_DISTRIBUTION",
        "label": "Sous-Station Électrique HT/BT, Tableaux Switchgear, Transformateurs & Onduleurs UPS",
        "codes_standards": ["IEC 61439", "IEC 62271", "IEC 60076", "IEEE 519", "Décret 21-257"],
        "precommissioning": [
            {
                "code": "PC-ELE-01",
                "name": "Mesure de résistance d'isolement (Mégohmmètre) & test diélectrique VLF Hipot des câbles HT/BT",
                "description": "Test d'isolement à 5 kV DC pour câbles HT et 1 kV DC pour câbles BT, injection haute tension très basse fréquence (VLF à 0.1 Hz) pour validation de la tenue diélectrique.",
                "unite": "départ câble",
                "duree_jours": 0.5,
                "checksheet_type": "A-SHEET (Électrique)",
                "equipe": [{"role": "Électricien haute tension certifié", "effectif": 2}],
                "ressources": ["Générateur d'essai diélectrique VLF 60 kV Megger / Baur", "Mégohmmètre numérique 5kV Chauvin Arnoux"]
            },
            {
                "code": "PC-ELE-02",
                "name": "Contrôle de rigidité diélectrique de l'huile & rapport de transformation des transformateurs HT/BT",
                "description": "Prélèvement et claquage d'huile du transformateur (Breakdown Voltage > 60 kV), mesure du rapport de transformation, de la résistance des enroulements et test d'isolement du circuit magnétique.",
                "unite": "transformateur",
                "duree_jours": 1.0,
                "checksheet_type": "A-SHEET (Transformateur)",
                "equipe": [{"role": "Spécialiste Transformateurs de puissance", "effectif": 2}],
                "ressources": ["Spintermètre d'huile portable 80kV", "Micro-ohmmètre de précision 100A", "Ratiomètre automatique"]
            },
            {
                "code": "PC-ELE-03",
                "name": "Injection secondaire et étalonnage des relais de protection numériques (Omicron Relay Testing)",
                "description": "Test de déclenchement des protections maximum de courant (50/51), différentielles (87T/87M), à minimum de tension (27) et de défaut à la terre (50N/51N) par injection de courant secondaire.",
                "unite": "relais de protection",
                "duree_jours": 0.5,
                "checksheet_type": "A-SHEET (Protection)",
                "equipe": [{"role": "Ingénieur Protection Électrique certifié", "effectif": 1}],
                "ressources": ["Valise d'injection triphasée numérique Omicron CMC 356", "Logiciel de test Test Universe"]
            },
            {
                "code": "PC-ELE-04",
                "name": "Mesure de la résistance de terre du réseau général de masse (Earth Grid Resistance < 1 Ohm)",
                "description": "Mesure de la résistance de la boucle de terre par la méthode des 3 piquets (chute de potentiel), contrôle de la continuité des liaisons équipotentielles sur tous les skids.",
                "unite": "réseau de terre",
                "duree_jours": 1.0,
                "checksheet_type": "A-SHEET (Terre)",
                "equipe": [{"role": "Électricien mesureur", "effectif": 2}],
                "ressources": ["Telluromètre numérique Chauvin Arnoux CA 6470", "Piquets de test et bobines de câble 100m"]
            }
        ],
        "commissioning": [
            {
                "code": "COM-ELE-01",
                "name": "Première mise sous tension des jeux de barres HT & vérification du concordancement de phases",
                "description": "Consignation des départs, fermeture du disjoncteur d'arrivée générale sous protocole de verrouillage LOTO, contrôle du concordancement des phases à la perche de phase.",
                "unite": "tableau switchgear",
                "duree_jours": 1.0,
                "checksheet_type": "B-SHEET (Mise sous tension)",
                "equipe": [{"role": "Chargé de Manœuvre HT habilité H2V/HC", "effectif": 1}, {"role": "Inspecteur Sécurité Électrique", "effectif": 1}],
                "ressources": ["Perche de concordancement de phase HT", "EPI complet de protection contre les arcs électriques (Arc Flash 40 cal/cm²)"]
            },
            {
                "code": "COM-ELE-02",
                "name": "Test de décharge en charge réelle du banc de batteries et de l'onduleur UPS (8h Discharge Test)",
                "description": "Coupure de l'alimentation secteur normale, maintien de la charge critique d'instrumentation et de sécurité sur batteries pendant 8h continues, contrôle des tensions d'éléments.",
                "unite": "baie UPS / Batteries",
                "duree_jours": 1.5,
                "checksheet_type": "B-SHEET (Autonomie Secourue)",
                "equipe": [{"role": "Spécialiste UPS / Batteries de traction", "effectif": 2}],
                "ressources": ["Banc de charge résistif 50 kW", "Enregistreur de tension multi-voies pour éléments de batterie"]
            },
            {
                "code": "COM-ELE-03",
                "name": "Essai de démarrage automatique en noir du groupe électrogène de secours (Black-Start Auto Transfer)",
                "description": "Simulation d'une perte totale de l'alimentation électrique normale (Black-Out), vérification du démarrage automatique du groupe Diesel en moins de 10 secondes et de la prise en charge des auxiliaires.",
                "unite": "générateur de secours",
                "duree_jours": 1.0,
                "checksheet_type": "B-SHEET (Secours Vital)",
                "equipe": [{"role": "Électricien diéséliste", "effectif": 2}],
                "ressources": ["Inverseur de source automatique (ATS)", "Chronomètre certifié"]
            }
        ]
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 11. PIPELINES DE TRANSPORT & CANALISATIONS CROSS-COUNTRY
    # ──────────────────────────────────────────────────────────────────────────
    "CROSS_COUNTRY_PIPELINE": {
        "category": "PIPELINE_TRANSPORT",
        "label": "Pipeline de Transport d'Hydrocarbures (Gazoduc / Oléoduc / Condensatduc)",
        "codes_standards": ["ASME B31.8", "ASME B31.4", "API 1104", "Décret 21-314", "P-CTE-1 Part 4 & 5"],
        "precommissioning": [
            {
                "code": "PC-PL-01",
                "name": "Raclages de nettoyage mécanique & calibrage au disque aluminium (Cleaning & Gauging Pigging)",
                "description": "Lancement d'un piston racleur mousse puis racleur à brosses métalliques et d'un racleur de calibrage équipé d'une plaque d'aluminium à 95% du diamètre intérieur pour détecter les ovalisations.",
                "unite": "section de pipeline",
                "duree_jours": 3.0,
                "checksheet_type": "A-SHEET (Nettoyage Pipeline)",
                "equipe": [{"role": "Superviseur Raclage Pipeline", "effectif": 1}, {"role": "Opérateurs gares de racleurs", "effectif": 4}],
                "ressources": ["Gare de départ / réception de racleurs", "Pistons racleurs à brosses et à disques", "Compresseurs gros débit (25 m³/min)"]
            },
            {
                "code": "PC-PL-02",
                "name": "Épreuve hydrostatique réglementaire de 24h avec calcul du diagramme Volume/Pression (PV Plot)",
                "description": "Remplissage en eau inhibée, mise en pression continue avec tracé du diagramme Pression-Volume (PV Plot) jusqu'à la pression d'épreuve (125% à 150% de la PMA selon la classe d'emplacement) et maintien 24h sans chute de pression.",
                "unite": "tronçon d'épreuve",
                "duree_jours": 4.0,
                "checksheet_type": "A-SHEET (Hydrotest 24h)",
                "equipe": [{"role": "Ingénieur Épreuve Pipeline", "effectif": 1}, {"role": "Inspecteurs ARH / TPI", "effectif": 2}, {"role": "Opérateurs pompage", "effectif": 4}],
                "ressources": ["Pompe de pressurisation triplex haute pression", "Balance manométrique à poids morts (Deadweight tester)", "Sondes de température enterrées"]
            },
            {
                "code": "PC-PL-03",
                "name": "Séchage final par soufflage d'air sec et contrôle du point de rosée < -40°C (Drying to -40°C)",
                "description": "Passage de trains de racleurs mousse sous air ultra-sec jusqu'à ce que le point de rosée mesuré à l'extrémité soit stable à moins de -40°C pendant 24h.",
                "unite": "section de pipeline",
                "duree_jours": 4.0,
                "checksheet_type": "A-SHEET (Séchage Gaz)",
                "equipe": [{"role": "Technicien séchage pipeline", "effectif": 3}],
                "ressources": ["Centrale de production d'air sec mobile avec sécheur à dessiccant -70°C", "Hygromètre de précision à miroir refroidi (Chilled Mirror)"]
            }
        ],
        "commissioning": [
            {
                "code": "COM-PL-01",
                "name": "Purge et conditionnement à l'azote gazeux (Nitrogen Packing / Inerting)",
                "description": "Remplissage de la canalisation sous une pression positive d'azote (0.5 à 1.0 bar) pour éviter toute rentrée d'air avant le raccordement définitif aux stations.",
                "unite": "section",
                "duree_jours": 2.0,
                "checksheet_type": "B-SHEET (Inertage)",
                "equipe": [{"role": "Opérateur azote cryogénique", "effectif": 3}],
                "ressources": ["Semi-remorque citerne d'azote liquide avec évaporateur flamme directe"]
            },
            {
                "code": "COM-PL-02",
                "name": "Mise en gaz / mise en huile sous pistonnage continu (Line Fill & Gas-in)",
                "description": "Introduction du gaz naturel ou brut derrière un piston de séparation sous vitesse contrôlée (1 à 2 m/s), évacuation de l'azote à la torche et mise en pression nominale du réseau.",
                "unite": "pipeline complet",
                "duree_jours": 3.0,
                "checksheet_type": "B-SHEET (Démarrage)",
                "equipe": [{"role": "Directeur des Opérations Pipeline", "effectif": 1}, {"role": "Superviseurs Dispatching Gaz", "effectif": 2}, {"role": "Équipes de ligne réparties aux postes de sectionnement", "effectif": 6}],
                "ressources": ["Système SCADA télémétrique", "Véhicules 4x4 d'intervention rapide le long de la piste"]
            },
            {
                "code": "COM-PL-03",
                "name": "Inspection par racleur instrumenté intelligent (Intelligent / Smart In-Line Inspection MFL)",
                "description": "Passage d'un racleur magnétique MFL (Magnetic Flux Leakage) pour établir l'empreinte zéro (Baseline Survey) de la géométrie, des épaisseurs et de l'état de surface interne.",
                "unite": "pipeline",
                "duree_jours": 5.0,
                "checksheet_type": "B-SHEET (Intégrité)",
                "equipe": [{"role": "Spécialiste Inspection Intelligente (Rosen / Baker Hughes)", "effectif": 2}],
                "ressources": ["Racleur intelligent haute résolution MFL / Caliper", "Balises acoustiques et électromagnétiques de tracking de racleur"]
            }
        ]
    }
}


# ══════════════════════════════════════════════════════════════════════════════
# MOTEUR DE GÉNÉRATION DES PHASES PRECOM & COMM DANS LE PLANNING
# ══════════════════════════════════════════════════════════════════════════════

class CommissioningPlanningEngine:
    """
    Moteur expert qui génère automatiquement les activités ordonnancées
    de Pré-Commissioning et Commissioning adaptées à la liste d'équipements du projet.
    """

    def get_all_equipment_types(self) -> List[Dict[str, Any]]:
        """Retourne la liste des types d'équipements disponibles avec leur description."""
        res = []
        for eq_key, eq_data in COMMISSIONING_EQUIPMENT_DATABASE.items():
            res.append({
                "code": eq_key,
                "category": eq_data["category"],
                "label": eq_data["label"],
                "standards": eq_data["codes_standards"],
                "precomm_tasks_count": len(eq_data["precommissioning"]),
                "comm_tasks_count": len(eq_data["commissioning"])
            })
        return res

    def get_equipment_matrix(self, equipment_code: str) -> Optional[Dict[str, Any]]:
        """Retourne la matrice technique détaillée complète pour un équipement donné."""
        return COMMISSIONING_EQUIPMENT_DATABASE.get(equipment_code.upper())

    def generate_commissioning_activities(
        self,
        equipment_types: List[str],
        project_name: str = "PROJET_COURANT",
        start_day_offset: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Génère la liste complète des tâches ordonnancées WBS (Précom + Comm)
        avec durées, rendements, équipes types, prédécesseurs et livrables.
        """
        activities = []
        task_counter = 1
        previous_task_id = None

        # ── 1. PHASES DE PRÉ-COMMISSIONING (Discipline 12_PRECOMMISSIONING_TESTS) ──
        for eq_code in equipment_types:
            eq_data = COMMISSIONING_EQUIPMENT_DATABASE.get(eq_code.upper())
            if not eq_data:
                continue

            for pc_task in eq_data["precommissioning"]:
                t_id = f"WBS-12.{task_counter:03d}"
                preds = [previous_task_id] if previous_task_id else []
                
                act = {
                    "id_tache": t_id,
                    "nom": f"[PRÉCOM] {eq_data['label'][:35]} - {pc_task['name']}",
                    "description": pc_task["description"],
                    "phase": "Pré-Commissioning (Essais à froid & Achèvement mécanique)",
                    "discipline": "12_PRECOMMISSIONING_TESTS",
                    "unite_oeuvre": pc_task["unite"],
                    "quantite_estimee": 1.0,
                    "rendement": {
                        "valeur": 1.0 / max(0.1, pc_task["duree_jours"]),
                        "unite": f"{pc_task['unite']}/jour/équipe"
                    },
                    "duree_jours": pc_task["duree_jours"],
                    "equipe_type": pc_task["equipe"],
                    "ressources_materielles": pc_task["ressources"],
                    "predecesseurs": preds,
                    "successeurs": [],
                    "jalon": False,
                    "niveau_confiance": "Haute",
                    "sources": eq_data["codes_standards"] + [pc_task["checksheet_type"]],
                    "metadata_pcc": {
                        "equipment_type": eq_code,
                        "checksheet_type": pc_task["checksheet_type"],
                        "code_precom": pc_task["code"]
                    }
                }
                activities.append(act)
                previous_task_id = t_id
                task_counter += 1

        # ── JALON INTERMÉDIAIRE : MECHANICAL COMPLETION / RFSU ──
        jalon_rfsu_id = "WBS-12.999"
        activities.append({
            "id_tache": jalon_rfsu_id,
            "nom": "[JALON] Mechanical Completion Certificate & Ready For Start-Up (RFSU)",
            "description": "Validation de 100% des Check-Sheets Catégorie A, levée des réserves bloquantes et visa officiel ARH / Commissioning Manager.",
            "phase": "Jalon Réglementaire",
            "discipline": "12_PRECOMMISSIONING_TESTS",
            "unite_oeuvre": "jalon",
            "quantite_estimee": 1.0,
            "rendement": {"valeur": 1.0, "unite": "jalon"},
            "duree_jours": 0.0,
            "equipe_type": [{"role": "Commissioning Manager & ARH Lead", "effectif": 2}],
            "ressources_materielles": ["Dossier ICAPS complet"],
            "predecesseurs": [previous_task_id] if previous_task_id else [],
            "successeurs": [],
            "jalon": True,
            "niveau_confiance": "Haute",
            "sources": ["Procédure ARH P-CTE-1", "ISO 29001 / ICAPS"]
        })
        previous_task_id = jalon_rfsu_id

        # ── 2. PHASES DE COMMISSIONING & DÉMARRAGE (Discipline 13_COMMISSIONING_STARTUP) ──
        comm_counter = 1
        for eq_code in equipment_types:
            eq_data = COMMISSIONING_EQUIPMENT_DATABASE.get(eq_code.upper())
            if not eq_data:
                continue

            for c_task in eq_data["commissioning"]:
                t_id = f"WBS-13.{comm_counter:03d}"
                preds = [previous_task_id] if previous_task_id else []

                act = {
                    "id_tache": t_id,
                    "nom": f"[COMM] {eq_data['label'][:35]} - {c_task['name']}",
                    "description": c_task["description"],
                    "phase": "Commissioning & Mise en service (Essais à chaud & Démarrage)",
                    "discipline": "13_COMMISSIONING_STARTUP",
                    "unite_oeuvre": c_task["unite"],
                    "quantite_estimee": 1.0,
                    "rendement": {
                        "valeur": 1.0 / max(0.1, c_task["duree_jours"]),
                        "unite": f"{c_task['unite']}/jour/équipe"
                    },
                    "duree_jours": c_task["duree_jours"],
                    "equipe_type": c_task["equipe"],
                    "ressources_materielles": c_task["ressources"],
                    "predecesseurs": preds,
                    "successeurs": [],
                    "jalon": False,
                    "niveau_confiance": "Haute",
                    "sources": eq_data["codes_standards"] + [c_task["checksheet_type"]],
                    "metadata_pcc": {
                        "equipment_type": eq_code,
                        "checksheet_type": c_task["checksheet_type"],
                        "code_comm": c_task["code"]
                    }
                }
                activities.append(act)
                previous_task_id = t_id
                comm_counter += 1

        # ── JALON FINAL : READY FOR OPERATION / FINAL HANDOVER ──
        jalon_rfo_id = "WBS-13.999"
        activities.append({
            "id_tache": jalon_rfo_id,
            "nom": "[JALON FINAL] Ready For Operation (RFO) & Transfert Definitif aux Operations",
            "description": "Validation continue de la marche de performance 72h, levée de 100% des réserves Catégorie B, livraison des dossiers As-Built et signature du PV de réception provisoire (FAC).",
            "phase": "Jalon Final",
            "discipline": "13_COMMISSIONING_STARTUP",
            "unite_oeuvre": "jalon",
            "quantite_estimee": 1.0,
            "rendement": {"valeur": 1.0, "unite": "jalon"},
            "duree_jours": 0.0,
            "equipe_type": [{"role": "Chef de Projet EPC & Directeur Exploitation Client", "effectif": 2}],
            "ressources_materielles": ["Dossier As-Built", "Certificats de garantie"],
            "predecesseurs": [previous_task_id] if previous_task_id else [],
            "successeurs": [],
            "jalon": True,
            "niveau_confiance": "Haute",
            "sources": ["Contrat EPC Clé en Main", "Procédure ARH Exploitation"]
        })

        return activities


# Instance Singleton
commissioning_engine = CommissioningPlanningEngine()
