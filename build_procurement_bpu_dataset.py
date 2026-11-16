#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARKAN Procurement IA — Générateur de Dataset d'Instruction Fine-Tuning (Colab T4 + Kaggle GPU)
Génère `dataset_procurement_contracts_bpu_instruct.jsonl` pour le fine-tuning QLoRA 4-bit
de l'extracteur spécialisé Contrats GCB + MTO / BPU (2.1) / DQE (2.2) / Délai de livraison.
"""

import json
import random
from pathlib import Path

random.seed(42)

SYSTEM_PROMPT = (
    "Tu es ARKAN-NuExtract-Procurement, un modèle d'IA spécialisé dans l'extraction structurée "
    "de contrats d'achat EPC/Oil & Gas (GCB / Sonatrach), de bons de commande, d'avenants et de "
    "bordereaux financiers (Annexe 2 : 2.1 Bordereau des Prix Unitaires BPU, 2.2 Devis Quantitatif "
    "et Estimatif DQE / MTO, Annexe 5 : Décomposition du montant). "
    "Extrais uniquement un objet JSON valide contenant : numero_contrat, fournisseur, objet, "
    "delai_livraison, date_signature, montant, devise, et la liste exacte items "
    "(reference, designation, quantite_contractuelle, unite, prix_unitaire, montant_total, delai_livraison)."
)

# Corpus de contrats réels GCB vérifiés (issus de C:\Users\MSI\Desktop\Contrat fournisseur & Reclamation)
REAL_CONTRACTS_CORPUS = [
    {
        "numero_contrat": "AVENANT-08-CTR-48",
        "fournisseur": "TECHNO CAST SPA",
        "objet": "Avenant N°08 au Contrat N°48/DG/2024 : Acquisition de Robinetteries et Accessoires en Acier au Carbone",
        "delai_livraison": "08 Mois",
        "date_signature": "2025-02-10",
        "montant": 65629390.00,
        "devise": "DZD",
        "raw_excerpt": """ENTREPRISE NATIONALE DE CANALISATIONS - GCB SPA
AVENANT N° 08 AU CONTRAT N° 48/DG/2024
Entre GCB SPA et TECHNO CAST SPA
OBJET : Acquisition de Robinetteries et Accessoires en Acier au Carbone pour le projet STC OK1 34"
ARTICLE 04 - DELAI DE LIVRAISON : Le délai de livraison est fixé à Huit (08) Mois à compter de l'entrée en vigueur.
ARTICLE 03 - MONTANT DE L'AVENANT : Le montant global en HT est de 65 629 390,00 DA.
BORDEREAU DES PRIX UNITAIRES ET QUANTITATIF (BPU / DQE) :
1.1 | Bride pleine (Blind Flange) 20" 150# RF A105N ASME B16.5 | U | 2 | 124 850,00 | 249 700,00
1.2 | Bride pleine (Blind Flange) 12" 150# RF A105N ASME B16.5 | U | 1 | 44 650,00 | 44 650,00
1.3 | Bride à collerette à souder (WN Flange) 20" 150# RF SCH20 A105N | U | 2 | 109 660,00 | 219 320,00
1.4 | Bride à collerette à souder (WN Flange) 16" 150# RF SCH20 A105N | U | 4 | 71 990,00 | 287 960,00
2.1 | Coude 90° LR 20" SCH20 WPB ASME B16.9 | U | 6 | 98 400,00 | 590 400,00
3.1 | Té égal 20"x20" SCH20 WPB ASME B16.9 | U | 2 | 145 000,00 | 290 000,00
7.5 | Goujons A193 Gr B7 avec 2 écrous A194 Gr 2H pour bride 20" 150# | U | 88 | 28 320,00 | 2 492 160,00""",
        "items": [
            {"reference": "ART-1.1", "designation": "Bride pleine (Blind Flange) 20\" 150# RF A105N ASME B16.5", "quantite_contractuelle": 2.0, "unite": "U", "prix_unitaire": 124850.0, "montant_total": 249700.0, "delai_livraison": "08 Mois"},
            {"reference": "ART-1.2", "designation": "Bride pleine (Blind Flange) 12\" 150# RF A105N ASME B16.5", "quantite_contractuelle": 1.0, "unite": "U", "prix_unitaire": 44650.0, "montant_total": 44650.0, "delai_livraison": "08 Mois"},
            {"reference": "ART-1.3", "designation": "Bride à collerette à souder (WN Flange) 20\" 150# RF SCH20 A105N", "quantite_contractuelle": 2.0, "unite": "U", "prix_unitaire": 109660.0, "montant_total": 219320.0, "delai_livraison": "08 Mois"},
            {"reference": "ART-1.4", "designation": "Bride à collerette à souder (WN Flange) 16\" 150# RF SCH20 A105N", "quantite_contractuelle": 4.0, "unite": "U", "prix_unitaire": 71990.0, "montant_total": 287960.0, "delai_livraison": "08 Mois"},
            {"reference": "ART-2.1", "designation": "Coude 90° LR 20\" SCH20 WPB ASME B16.9", "quantite_contractuelle": 6.0, "unite": "U", "prix_unitaire": 98400.0, "montant_total": 590400.0, "delai_livraison": "08 Mois"},
            {"reference": "ART-3.1", "designation": "Té égal 20\"x20\" SCH20 WPB ASME B16.9", "quantite_contractuelle": 2.0, "unite": "U", "prix_unitaire": 145000.0, "montant_total": 290000.0, "delai_livraison": "08 Mois"},
            {"reference": "ART-7.5", "designation": "Goujons A193 Gr B7 avec 2 écrous A194 Gr 2H pour bride 20\" 150#", "quantite_contractuelle": 88.0, "unite": "U", "prix_unitaire": 28320.0, "montant_total": 2492160.0, "delai_livraison": "08 Mois"},
        ]
    },
    {
        "numero_contrat": "BC-35/ACH/2025",
        "fournisseur": "ELECTRO INDUSTRY",
        "objet": "Acquisition des tableaux de distribution basse tension (TBT)",
        "delai_livraison": "01 Mois",
        "date_signature": "2024-03-28",
        "montant": 5574374.00,
        "devise": "DZD",
        "raw_excerpt": """BON DE COMMANDE N° 35/ACH/2025 DU 28/03/2024 (CSC N°27)
Fournisseur : ELECTRO INDUSTRY
Objet : Acquisition des tableaux de distribution basse tension
Délai de livraison : 01 Mois
N° | Désignation | U | Qté | Prix Unitaire HT | Montant Total HT
01 | 300-TBT-003 Coffret de distribution électrique 400V AC | U | 2 | 464 531,17 | 929 062,34
02 | 300-TBT-004 Coffret de distribution éclairage extérieur | U | 2 | 464 531,17 | 929 062,34
03 | 300-TBT-005 Coffret de distribution prises de courant | U | 2 | 464 531,17 | 929 062,34
04 | 100-TBT-001 Tableau général basse tension TGBT | U | 2 | 1 393 593,49 | 2 787 186,98
Montant Total HT : 5 574 374,00 DZD""",
        "items": [
            {"reference": "300-TBT-003", "designation": "300-TBT-003 Coffret de distribution électrique 400V AC", "quantite_contractuelle": 2.0, "unite": "U", "prix_unitaire": 464531.17, "montant_total": 929062.34, "delai_livraison": "01 Mois"},
            {"reference": "300-TBT-004", "designation": "300-TBT-004 Coffret de distribution éclairage extérieur", "quantite_contractuelle": 2.0, "unite": "U", "prix_unitaire": 464531.17, "montant_total": 929062.34, "delai_livraison": "01 Mois"},
            {"reference": "300-TBT-005", "designation": "300-TBT-005 Coffret de distribution prises de courant", "quantite_contractuelle": 2.0, "unite": "U", "prix_unitaire": 464531.17, "montant_total": 929062.34, "delai_livraison": "01 Mois"},
            {"reference": "100-TBT-001", "designation": "100-TBT-001 Tableau général basse tension TGBT", "quantite_contractuelle": 2.0, "unite": "U", "prix_unitaire": 1393593.49, "montant_total": 2787186.98, "delai_livraison": "01 Mois"},
        ]
    },
    {
        "numero_contrat": "BC-02/ACH/2025",
        "fournisseur": "ELECTRO INDUSTRY",
        "objet": "Fourniture d'armoire de distribution électrique TBT-003BIS",
        "delai_livraison": "15 jours",
        "date_signature": "2025-01-13",
        "montant": 960000.00,
        "devise": "DZD",
        "raw_excerpt": """BON DE COMMANDE N° 02/ACH/2025 du 13-01-2025
Fournisseur : ELECTRO INDUSTRY
Objet : Fourniture d'armoire de distribution électrique
Délai de livraison : 15 jours
01 | TBT-003BIS Armoire de distribution électrique basse tension | 1 | U | 960 000,00 | 960 000,00""",
        "items": [
            {"reference": "TBT-003BIS", "designation": "TBT-003BIS Armoire de distribution électrique basse tension", "quantite_contractuelle": 1.0, "unite": "U", "prix_unitaire": 960000.0, "montant_total": 960000.0, "delai_livraison": "15 jours"}
        ]
    },
    {
        "numero_contrat": "BC-15/ACH/2025",
        "fournisseur": "ELECTRO INDUSTRY",
        "objet": "Acquisition de grillage avertisseur",
        "delai_livraison": "15 jours",
        "date_signature": "2025-02-03",
        "montant": 301000.00,
        "devise": "DZD",
        "raw_excerpt": """BON DE COMMANDE N° 15/ACH/2025 du 03-02-2025
Fournisseur : ELECTRO INDUSTRY
Délai de livraison : 15 jours
01 | Grillage avertisseur rouge largeur 30 cm pour câble électrique | 7000 | ML | 43,00 | 301 000,00 DZD""",
        "items": [
            {"reference": "EQ-01", "designation": "Grillage avertisseur rouge largeur 30 cm pour câble électrique", "quantite_contractuelle": 7000.0, "unite": "ML", "prix_unitaire": 43.0, "montant_total": 301000.0, "delai_livraison": "15 jours"}
        ]
    },
    {
        "numero_contrat": "09-PRC-DEP-GCB-2025",
        "fournisseur": "SARL SISCOPLAST",
        "objet": "Acquisition de Tube PEHD avec accessoires de raccordement et grillage avertisseur",
        "delai_livraison": "Vingt (20) jours à compter de l'entrée en vigueur du contrat",
        "date_signature": "2025-01-20",
        "montant": 8019720.00,
        "devise": "DZD",
        "raw_excerpt": """CONTRAT N° 09/PRC/DEP/GCB/2025
Entre GCB SPA et SARL SISCOPLAST
ARTICLE 01 : OBJET DU CONTRAT : TUBE PEHD AVEC ACCESSOIRES DE RACCORDEMENT ET GRILLAGE AVERTISSEUR
ARTICLE 07 : DELAI DE LIVRAISON : Vingt (20) jours à compter de l'entrée en vigueur du contrat.
ANNEXE 02 : BORDEREAU DES PRIX UNITAIRES ET DEVIS QUANTITATIF ET ESTIMATIF
01 | Gaine en PEHD D40 PN16 avec Raccord D40 | ML | 42000 | 183,66 | 7 713 720,00
02 | Bouchon D40 et Grillage avertisseur | U | 30000 | 10,20 | 306 000,00
TOTAL HT : 8 019 720,00 DZD""",
        "items": [
            {"reference": "EQ-01", "designation": "Gaine en PEHD D40 PN16 avec Raccord D40", "quantite_contractuelle": 42000.0, "unite": "ML", "prix_unitaire": 183.66, "montant_total": 7713720.0, "delai_livraison": "Vingt (20) jours à compter de l'entrée en vigueur du contrat"},
            {"reference": "EQ-02", "designation": "Bouchon D40 et Grillage avertisseur", "quantite_contractuelle": 30000.0, "unite": "U", "prix_unitaire": 10.20, "montant_total": 306000.0, "delai_livraison": "Vingt (20) jours à compter de l'entrée en vigueur du contrat"},
        ]
    },
    {
        "numero_contrat": "03/ACH/2024",
        "fournisseur": "ELSEWEDY CABLES ALGERIA SPA",
        "objet": "Acquisition des transformateurs de puissance et auxiliaires",
        "delai_livraison": "06 Mois",
        "date_signature": "2024-06-15",
        "montant": 31481133.79,
        "devise": "DZD",
        "raw_excerpt": """CONTRAT N° 03/ACH/2024 - ELSEWEDY CABLES ALGERIA SPA
Objet : Acquisition des transformateurs de puissance
Délai de livraison : Six (06) Mois
DEVIS QUANTITATIF ET ESTIMATIF :
1 | Transformer 1000 KVA 30/0.4 KV ONAN | Pcs | 2 | 4 400 000,00 | 8 800 000,00
2 | Transformer 1250 KVA 30/0.4 KV ONAN | Pcs | 2 | 5 650 000,00 | 11 300 000,00
3 | Transformer 630 KVA 30/0.4 KV ONAN | Pcs | 2 | 3 620 000,00 | 7 240 000,00
4 | Neutral Earthing Resistor (NER) | Pcs | 2 | 1 250 000,00 | 2 500 000,00
5 | Lot de pièces de rechange 2 ans et essais | Lot | 1 | 1 641 133,79 | 1 641 133,79
TOTAL GENERAL HT : 31 481 133,79 DZD""",
        "items": [
            {"reference": "EQ-01", "designation": "Transformer 1000 KVA 30/0.4 KV ONAN", "quantite_contractuelle": 2.0, "unite": "PCS", "prix_unitaire": 4400000.0, "montant_total": 8800000.0, "delai_livraison": "06 Mois"},
            {"reference": "EQ-02", "designation": "Transformer 1250 KVA 30/0.4 KV ONAN", "quantite_contractuelle": 2.0, "unite": "PCS", "prix_unitaire": 5650000.0, "montant_total": 11300000.0, "delai_livraison": "06 Mois"},
            {"reference": "EQ-03", "designation": "Transformer 630 KVA 30/0.4 KV ONAN", "quantite_contractuelle": 2.0, "unite": "PCS", "prix_unitaire": 3620000.0, "montant_total": 7240000.0, "delai_livraison": "06 Mois"},
            {"reference": "EQ-04", "designation": "Neutral Earthing Resistor (NER)", "quantite_contractuelle": 2.0, "unite": "PCS", "prix_unitaire": 1250000.0, "montant_total": 2500000.0, "delai_livraison": "06 Mois"},
            {"reference": "EQ-05", "designation": "Lot de pièces de rechange 2 ans et essais", "quantite_contractuelle": 1.0, "unite": "LOT", "prix_unitaire": 1641133.79, "montant_total": 1641133.79, "delai_livraison": "06 Mois"},
        ]
    },
    {
        "numero_contrat": "16/ACH/2024",
        "fournisseur": "ELSEWEDY CABLES ALGERIA SPA",
        "objet": "Câbles électriques de puissance en basse tension et de contrôle, Station principale et Terminaux",
        "delai_livraison": "Trois (03) Mois à compter de la date de l'entrée en vigueur du contrat",
        "date_signature": "2024-09-12",
        "montant": 3918164355.58,
        "devise": "DZD",
        "raw_excerpt": """CONTRAT N° 16/ACH/2024
Fournisseur : ELSEWEDY CABLES ALGERIA SPA
Objet : Câbles électriques de puissance en basse tension et de contrôle, Station principale
Article 07 - Délai de livraison : (03) Mois à compter de la date de l'entrée en vigueur du contrat.
ANNEXE 5 - BORDEREAU DES PRIX UNITAIRES ET DEVIS QUANTITATIF ET ESTIMATIF :
01 | 1X185mm2 CU/XLPE/PVC 0.6/1kV | ML | 4200 | 4 500,00 | 18 900 000,00
02 | 12x1,5mm2 CU/XLPE/GSTA/PVC | ML | 8500 | 1 250,00 | 10 625 000,00
03 | 16x2,5mm2 CU/XLPE/GSTA/PVC | ML | 6300 | 1 850,00 | 11 655 000,00
04 | 7x1,5mm2 CU/XLPE/GSTA/PVC | ML | 2200 | 424,95 | 934 890,00""",
        "items": [
            {"reference": "EQ-01", "designation": "1X185mm2 CU/XLPE/PVC 0.6/1kV", "quantite_contractuelle": 4200.0, "unite": "ML", "prix_unitaire": 4500.0, "montant_total": 18900000.0, "delai_livraison": "Trois (03) Mois à compter de la date de l'entrée en vigueur du contrat"},
            {"reference": "EQ-02", "designation": "12x1,5mm2 CU/XLPE/GSTA/PVC", "quantite_contractuelle": 8500.0, "unite": "ML", "prix_unitaire": 1250.0, "montant_total": 10625000.0, "delai_livraison": "Trois (03) Mois à compter de la date de l'entrée en vigueur du contrat"},
            {"reference": "EQ-03", "designation": "16x2,5mm2 CU/XLPE/GSTA/PVC", "quantite_contractuelle": 6300.0, "unite": "ML", "prix_unitaire": 1850.0, "montant_total": 11655000.0, "delai_livraison": "Trois (03) Mois à compter de la date de l'entrée en vigueur du contrat"},
            {"reference": "EQ-04", "designation": "7x1,5mm2 CU/XLPE/GSTA/PVC", "quantite_contractuelle": 2200.0, "unite": "ML", "prix_unitaire": 424.95, "montant_total": 934890.0, "delai_livraison": "Trois (03) Mois à compter de la date de l'entrée en vigueur du contrat"},
        ]
    },
    {
        "numero_contrat": "42-PRC-DEP-GCB-2025",
        "fournisseur": "EURL EL CHAHID",
        "objet": "Packages de distribution d'eau de (Service / Potable) - Zone Principale",
        "delai_livraison": "Quatre (04) mois à compter de la date de l'entrée en vigueur du contrat",
        "date_signature": "2025-03-01",
        "montant": 149355378.99,
        "devise": "DZD",
        "raw_excerpt": """CONTRAT N° 42/PRC/DEP/GCB/2025
Fournisseur : EURL EL CHAHID
Objet : PACKAGES DE DISTRIBUTION D'EAU DE (SERVICE / POTABLE) - ZONE PRINCIPALE
Article 08 - Délai de livraison : Quatre (04) mois à compter de la date de l'entrée en vigueur du contrat.
ANNEXE 02 : 2.1 BORDEREAU DES PRIX UNITAIRES & 2.2 DEVIS QUANTITATIF ET ESTIMATIF (OCR Multi-lignes) :
1.1 | PACKAGE DE DISTRIBUTION EAU DE SERVICE (315-OS-001) conçu selon le standard API
un million vingt-huit mille huit cent vingt-cinq DA | U | 2 | 1 028 825,07 | 2 057 650,14
1.2 | Moteur électrique horizontal anti-déflagrant
un million cent trente mille six cent soixante-quinze DA | U | 1 | 1 130 675,00 | 1 130 675,00
1.3 | Accouplement flexible avec entretoise (pièce de rechange) | U | 1 | 45 223,08 | 45 223,08
1.4 | Protecteur d'accouplement anti-étincelle | U | 1 | 33 917,31 | 33 917,31""",
        "items": [
            {"reference": "315-OS-001", "designation": "PACKAGE DE DISTRIBUTION EAU DE SERVICE (315-OS-001) conçu selon le standard API", "quantite_contractuelle": 2.0, "unite": "U", "prix_unitaire": 1028825.07, "montant_total": 2057650.14, "delai_livraison": "Quatre (04) mois à compter de la date de l'entrée en vigueur du contrat"},
            {"reference": "ART-1.2", "designation": "Moteur électrique horizontal anti-déflagrant", "quantite_contractuelle": 1.0, "unite": "U", "prix_unitaire": 1130675.0, "montant_total": 1130675.0, "delai_livraison": "Quatre (04) mois à compter de la date de l'entrée en vigueur du contrat"},
            {"reference": "ART-1.3", "designation": "Accouplement flexible avec entretoise (pièce de rechange)", "quantite_contractuelle": 1.0, "unite": "U", "prix_unitaire": 45223.08, "montant_total": 45223.08, "delai_livraison": "Quatre (04) mois à compter de la date de l'entrée en vigueur du contrat"},
            {"reference": "ART-1.4", "designation": "Protecteur d'accouplement anti-étincelle", "quantite_contractuelle": 1.0, "unite": "U", "prix_unitaire": 33917.31, "montant_total": 33917.31, "delai_livraison": "Quatre (04) mois à compter de la date de l'entrée en vigueur du contrat"},
        ]
    },
    {
        "numero_contrat": "29/DG/2025",
        "fournisseur": "SARL SEGITEC",
        "objet": "Lot 1 : Equipement Anti Incendie / Lot 2 : Vanne De Déluge",
        "delai_livraison": "Trois (03) mois à compter de la date de l'entrée en vigueur du contrat",
        "date_signature": "2025-02-18",
        "montant": 2750100.50,
        "devise": "EUR",
        "raw_excerpt": """CONTRAT N° 29/DG/2025 - SARL SEGITEC
Objet : Lot 1 : Equipement Anti Incendie - Lot 2 : Vanne De Déluge
Le délai de livraison : Trois (03) mois à compter de la date de l'entrée en vigueur du contrat.
BORDEREAU DES PRIX EN MONNAIE ETRANGERE :
1.1 | 106-USD-001-USD (unité de stockage et de dosage) 11m3 Equipement horizontal équipé d'un proportionneur monté sur skid | 1 | U | 202 406,00 € | 202 406,00 €
1.2 | 206-USD-001-USD (unité de stockage et de dosage) 5m3 Equipement vertical équipé d'un proportionneur monté sur skid | 1 | U | 116 536,00 € | 116 536,00 €
1.3 | 306-USD-001-USD (unité de stockage et de dosage) 0.2m3 Equipement vertical équipé d'un proportionneur monté sur skid | 1 | U | 44 905,00 € | 44 905,00 €
1.6 | Pulvérisateur à jet plat | 90 | U | 528,00 € | 47 520,00 €
1.7 | Pulvérisateur à jet conique | 233 | U | 109,00 € | 25 397,00 €
2.1 | Vannes de déluge 8" | 1 | U | 20 287,00 € | 20 287,00 €
2.2 | Vannes de déluge 6" | 2 | U | 11 835,50 € | 23 671,00 €
2.3 | Vannes de déluge 4" | 17 | U | 9 257,00 € | 157 369,00 €""",
        "items": [
            {"reference": "106-USD-001", "designation": "106-USD-001-USD (unité de stockage et de dosage) 11m3 Equipement horizontal équipé d'un proportionneur monté sur skid", "quantite_contractuelle": 1.0, "unite": "U", "prix_unitaire": 202406.0, "montant_total": 202406.0, "delai_livraison": "Trois (03) mois à compter de la date de l'entrée en vigueur du contrat"},
            {"reference": "206-USD-001", "designation": "206-USD-001-USD (unité de stockage et de dosage) 5m3 Equipement vertical équipé d'un proportionneur monté sur skid", "quantite_contractuelle": 1.0, "unite": "U", "prix_unitaire": 116536.0, "montant_total": 116536.0, "delai_livraison": "Trois (03) mois à compter de la date de l'entrée en vigueur du contrat"},
            {"reference": "306-USD-001", "designation": "306-USD-001-USD (unité de stockage et de dosage) 0.2m3 Equipement vertical équipé d'un proportionneur monté sur skid", "quantite_contractuelle": 1.0, "unite": "U", "prix_unitaire": 44905.0, "montant_total": 44905.0, "delai_livraison": "Trois (03) mois à compter de la date de l'entrée en vigueur du contrat"},
            {"reference": "ART-1.6", "designation": "Pulvérisateur à jet plat", "quantite_contractuelle": 90.0, "unite": "U", "prix_unitaire": 528.0, "montant_total": 47520.0, "delai_livraison": "Trois (03) mois à compter de la date de l'entrée en vigueur du contrat"},
            {"reference": "ART-1.7", "designation": "Pulvérisateur à jet conique", "quantite_contractuelle": 233.0, "unite": "U", "prix_unitaire": 109.0, "montant_total": 25397.0, "delai_livraison": "Trois (03) mois à compter de la date de l'entrée en vigueur du contrat"},
            {"reference": "ART-2.1", "designation": "Vannes de déluge 8\"", "quantite_contractuelle": 1.0, "unite": "U", "prix_unitaire": 20287.0, "montant_total": 20287.0, "delai_livraison": "Trois (03) mois à compter de la date de l'entrée en vigueur du contrat"},
            {"reference": "ART-2.2", "designation": "Vannes de déluge 6\"", "quantite_contractuelle": 2.0, "unite": "U", "prix_unitaire": 11835.5, "montant_total": 23671.0, "delai_livraison": "Trois (03) mois à compter de la date de l'entrée en vigueur du contrat"},
            {"reference": "ART-2.3", "designation": "Vannes de déluge 4\"", "quantite_contractuelle": 17.0, "unite": "U", "prix_unitaire": 9257.0, "montant_total": 157369.0, "delai_livraison": "Trois (03) mois à compter de la date de l'entrée en vigueur du contrat"},
        ]
    },
    {
        "numero_contrat": "71-PRC-DEP-GCB-2024",
        "fournisseur": "EURL INSTRUMEX",
        "objet": "Acquisition de Bulk Matériel Instrumentation",
        "delai_livraison": "03 Mois",
        "date_signature": "2024-11-10",
        "montant": 150284.40,
        "devise": "EUR",
        "raw_excerpt": """CONTRAT N° 71/PRC/DEP/GCB/2024
Fournisseur : EURL INSTRUMEX
Objet : Acquisition de Bulk Matériel Instrumentation
Délai de livraison : 03 Mois
2.1 BORDEREAU DES PRIX UNITAIRES & 2.2 DEVIS QUANTITATIF ET ESTIMATIF :
1.1 | Tube inox 316L sans soudure OD 1/2" x 0.049" ASTM A269 | M | 1200 | 14,50 | 17 400,00
1.2 | Tube inox 316L sans soudure OD 1/4" x 0.035" ASTM A269 | M | 800 | 9,80 | 7 840,00
1.3 | Raccord union droit double bague 316L 1/2" OD | U | 250 | 22,40 | 5 600,00
1.4 | Vanne manifold 5 voies 316L 1/2" NPT 6000 PSI | U | 45 | 185,00 | 8 325,00""",
        "items": [
            {"reference": "ART-1.1", "designation": "Tube inox 316L sans soudure OD 1/2\" x 0.049\" ASTM A269", "quantite_contractuelle": 1200.0, "unite": "M", "prix_unitaire": 14.5, "montant_total": 17400.0, "delai_livraison": "03 Mois"},
            {"reference": "ART-1.2", "designation": "Tube inox 316L sans soudure OD 1/4\" x 0.035\" ASTM A269", "quantite_contractuelle": 800.0, "unite": "M", "prix_unitaire": 9.8, "montant_total": 7840.0, "delai_livraison": "03 Mois"},
            {"reference": "ART-1.3", "designation": "Raccord union droit double bague 316L 1/2\" OD", "quantite_contractuelle": 250.0, "unite": "U", "prix_unitaire": 22.4, "montant_total": 5600.0, "delai_livraison": "03 Mois"},
            {"reference": "ART-1.4", "designation": "Vanne manifold 5 voies 316L 1/2\" NPT 6000 PSI", "quantite_contractuelle": 45.0, "unite": "U", "prix_unitaire": 185.0, "montant_total": 8325.0, "delai_livraison": "03 Mois"},
        ]
    },
    {
        "numero_contrat": "50-PRC-DEP-GCB-2025",
        "fournisseur": "MOKVELD VALVES B.V.",
        "objet": "Acquisition des vannes de régulation et vannes d'arrêt d'urgence axiales",
        "delai_livraison": "05 Mois",
        "date_signature": "2025-01-25",
        "montant": 178792.00,
        "devise": "EUR",
        "raw_excerpt": """CONTRAT N° 50/PRC/DEP/GCB/2025
Fournisseur : MOKVELD VALVES B.V.
Objet : Acquisition des vannes de régulation axiales
Délai de livraison : 05 Mois
ANNEXE 02 - DEVIS QUANTITATIF ET ESTIMATIF :
01 | Axial Control Valve 10" ANSI 600 RF Body A352 LCC Trim SS316/WC | 2 | U | 68 450,00 | 136 900,00
02 | Commissioning & Start-up Spare Parts | 1 | LOT | 14 292,00 | 14 292,00
03 | Two (02) Years Operating Spare Parts | 1 | LOT | 27 600,00 | 27 600,00""",
        "items": [
            {"reference": "EQ-01", "designation": "Axial Control Valve 10\" ANSI 600 RF Body A352 LCC Trim SS316/WC", "quantite_contractuelle": 2.0, "unite": "U", "prix_unitaire": 68450.0, "montant_total": 136900.0, "delai_livraison": "05 Mois"},
            {"reference": "EQ-02", "designation": "Commissioning & Start-up Spare Parts", "quantite_contractuelle": 1.0, "unite": "LOT", "prix_unitaire": 14292.0, "montant_total": 14292.0, "delai_livraison": "05 Mois"},
            {"reference": "EQ-03", "designation": "Two (02) Years Operating Spare Parts", "quantite_contractuelle": 1.0, "unite": "LOT", "prix_unitaire": 27600.0, "montant_total": 27600.0, "delai_livraison": "05 Mois"},
        ]
    },
    {
        "numero_contrat": "04/DG/2025",
        "fournisseur": "DEF SPA",
        "objet": "Système de détection et d'extinction automatique d'incendie",
        "delai_livraison": "06 Mois",
        "date_signature": "2025-01-15",
        "montant": 31781480.00,
        "devise": "DZD",
        "raw_excerpt": """CONTRAT N° 04/DG/2025
Fournisseur : DEF SPA
Objet : Système de détection et d'extinction incendie
Délai de livraison : 06 Mois
1.1 | Centrale de détection incendie adressable redondante | U | 2 | 1 850 000,00 | 3 700 000,00
1.2 | Détecteur optique de fumée adressable ATEX | U | 65 | 24 500,00 | 1 592 500,00
1.3 | Déclencheur manuel d'alarme incendie étanche IP66 | U | 28 | 18 200,00 | 509 600,00
1.4 | Sirène flash d'évacuation ATEX | U | 24 | 32 000,00 | 768 000,00""",
        "items": [
            {"reference": "ART-1.1", "designation": "Centrale de détection incendie adressable redondante", "quantite_contractuelle": 2.0, "unite": "U", "prix_unitaire": 1850000.0, "montant_total": 3700000.0, "delai_livraison": "06 Mois"},
            {"reference": "ART-1.2", "designation": "Détecteur optique de fumée adressable ATEX", "quantite_contractuelle": 65.0, "unite": "U", "prix_unitaire": 24500.0, "montant_total": 1592500.0, "delai_livraison": "06 Mois"},
            {"reference": "ART-1.3", "designation": "Déclencheur manuel d'alarme incendie étanche IP66", "quantite_contractuelle": 28.0, "unite": "U", "prix_unitaire": 18200.0, "montant_total": 509600.0, "delai_livraison": "06 Mois"},
            {"reference": "ART-1.4", "designation": "Sirène flash d'évacuation ATEX", "quantite_contractuelle": 24.0, "unite": "U", "prix_unitaire": 32000.0, "montant_total": 768000.0, "delai_livraison": "06 Mois"},
        ]
    },
    {
        "numero_contrat": "05/ACH/2024",
        "fournisseur": "EURL STI",
        "objet": "Acquisition des équipements de Protection Cathodique (PCT)",
        "delai_livraison": "07 mois",
        "date_signature": "2024-07-22",
        "montant": 34766741.25,
        "devise": "DZD",
        "raw_excerpt": """CONTRAT N° 05/ACH/2024 - EURL STI
Objet : Acquisition des équipements de Protection Cathodique (PCT)
Délai de livraison : 07 mois
1.1 | Transformateur redresseur de protection cathodique 50V / 50A | U | 3 | 1 450 000,00 | 4 350 000,00
1.2 | Anode en ferrosilicium pré-conditionnée 1500x75mm avec câble XLPE/PVDF | U | 120 | 68 500,00 | 8 220 000,00
1.3 | Coffret de mesure et de répartition potentiel de protection cathodique | U | 18 | 95 000,00 | 1 710 000,00
1.4 | Électrode de référence permanente Cu/CuSO4 enterrée | U | 24 | 42 000,00 | 1 008 000,00""",
        "items": [
            {"reference": "ART-1.1", "designation": "Transformateur redresseur de protection cathodique 50V / 50A", "quantite_contractuelle": 3.0, "unite": "U", "prix_unitaire": 1450000.0, "montant_total": 4350000.0, "delai_livraison": "07 mois"},
            {"reference": "ART-1.2", "designation": "Anode en ferrosilicium pré-conditionnée 1500x75mm avec câble XLPE/PVDF", "quantite_contractuelle": 120.0, "unite": "U", "prix_unitaire": 68500.0, "montant_total": 8220000.0, "delai_livraison": "07 mois"},
            {"reference": "ART-1.3", "designation": "Coffret de mesure et de répartition potentiel de protection cathodique", "quantite_contractuelle": 18.0, "unite": "U", "prix_unitaire": 95000.0, "montant_total": 1710000.0, "delai_livraison": "07 mois"},
            {"reference": "ART-1.4", "designation": "Électrode de référence permanente Cu/CuSO4 enterrée", "quantite_contractuelle": 24.0, "unite": "U", "prix_unitaire": 42000.0, "montant_total": 1008000.0, "delai_livraison": "07 mois"},
        ]
    },
    {
        "numero_contrat": "30/ACH/2024",
        "fournisseur": "EURSPEED GENERAL TRADING LLC",
        "objet": "Acquisition de tubulures et accessoires pour récipients sous pression",
        "delai_livraison": "08 Mois",
        "date_signature": "2024-10-05",
        "montant": 54269.43,
        "devise": "USD",
        "raw_excerpt": """CONTRAT N° 30/ACH/2024
Fournisseur : EURSPEED GENERAL TRADING LLC
Objet : Acquisition de tubulures pour récipients sous pression
Délai de livraison : 08 Mois
01 | Long Weld Neck Flange 2" 600# RF A105N ASME B16.5 | U | 8 | 285,00 | 2 280,00
02 | Self-Reinforced Nozzle (Weldoflange) 4" 600# RF A350 LF2 | U | 6 | 640,00 | 3 840,00
03 | Davit Arm Complete for 24" Manhole Cover A105N | U | 4 | 1 120,00 | 4 480,00""",
        "items": [
            {"reference": "EQ-01", "designation": "Long Weld Neck Flange 2\" 600# RF A105N ASME B16.5", "quantite_contractuelle": 8.0, "unite": "U", "prix_unitaire": 285.0, "montant_total": 2280.0, "delai_livraison": "08 Mois"},
            {"reference": "EQ-02", "designation": "Self-Reinforced Nozzle (Weldoflange) 4\" 600# RF A350 LF2", "quantite_contractuelle": 6.0, "unite": "U", "prix_unitaire": 640.0, "montant_total": 3840.0, "delai_livraison": "08 Mois"},
            {"reference": "EQ-03", "designation": "Davit Arm Complete for 24\" Manhole Cover A105N", "quantite_contractuelle": 4.0, "unite": "U", "prix_unitaire": 1120.0, "montant_total": 4480.0, "delai_livraison": "08 Mois"},
        ]
    },
    {
        "numero_contrat": "111/DG/2025",
        "fournisseur": "TD WILLIAMSON S.A.",
        "objet": "Équipements et accessoires de piquage en charge (Hot Tapping & Plugging)",
        "delai_livraison": "06 mois",
        "date_signature": "2025-02-01",
        "montant": 589078.00,
        "devise": "EUR",
        "raw_excerpt": """CONTRAT N° 111/DG/2025
Fournisseur : TD WILLIAMSON S.A.
Objet : Équipements de piquage en charge (Hot Tapping)
Délai de livraison : 06 mois
1.1 | Split Tee (STOPPLE Fitting) 34"x34" ANSI 600# Gr X60 | U | 2 | 145 200,00 | 290 400,00
1.2 | LOCK-O-RING Completion Plug 34" ANSI 600# | U | 2 | 48 900,00 | 97 800,00
1.3 | Sandwich Tapping Valve rental & Hot Tap Service | LOT | 1 | 200 878,00 | 200 878,00""",
        "items": [
            {"reference": "ART-1.1", "designation": "Split Tee (STOPPLE Fitting) 34\"x34\" ANSI 600# Gr X60", "quantite_contractuelle": 2.0, "unite": "U", "prix_unitaire": 145200.0, "montant_total": 290400.0, "delai_livraison": "06 mois"},
            {"reference": "ART-1.2", "designation": "LOCK-O-RING Completion Plug 34\" ANSI 600#", "quantite_contractuelle": 2.0, "unite": "U", "prix_unitaire": 48900.0, "montant_total": 97800.0, "delai_livraison": "06 mois"},
            {"reference": "ART-1.3", "designation": "Sandwich Tapping Valve rental & Hot Tap Service", "quantite_contractuelle": 1.0, "unite": "LOT", "prix_unitaire": 200878.0, "montant_total": 200878.0, "delai_livraison": "06 mois"},
        ]
    },
    {
        "numero_contrat": "06ACH25",
        "fournisseur": "HMT RUBBAGLAS",
        "objet": "Acquisition d'écran flottant interne en aluminium avec joints périphériques",
        "delai_livraison": "04 Mois",
        "date_signature": "2025-01-28",
        "montant": 59160.00,
        "devise": "USD",
        "raw_excerpt": """CONTRAT N° 06/ACH/2025
Fournisseur : HMT RUBBAGLAS
Objet : Acquisition d'écran flottant interne (Toit flottant)
Délai de livraison : 04 Mois
1.1 | Ecran flottant interne en aluminium complet avec accessoires | 1 | U | 56 565,00 | 56 565,00
2.1 | FRET MARITIME CFR ALGER | 1 | FORFAIT | 2 595,00 | 2 595,00
TOTAL CFR : 59 160,00 USD""",
        "items": [
            {"reference": "ART-1.1", "designation": "Ecran flottant interne en aluminium complet avec accessoires", "quantite_contractuelle": 1.0, "unite": "U", "prix_unitaire": 56565.0, "montant_total": 56565.0, "delai_livraison": "04 Mois"},
            {"reference": "SRV-02", "designation": "FRET MARITIME CFR ALGER", "quantite_contractuelle": 1.0, "unite": "FORFAIT", "prix_unitaire": 2595.0, "montant_total": 2595.0, "delai_livraison": "04 Mois"},
        ]
    },
]

# Générateurs synthétiques paramétriques basés sur les vrais patterns OCR GCB (BPU 2.1 + DQE 2.2, Rotation 90°/270°, Tags instruments, Multi-lignes)
SUPPLIERS_POOL = [
    ("TECHNO CAST SPA", "DZD"),
    ("ELSEWEDY CABLES ALGERIA SPA", "DZD"),
    ("EURL EL CHAHID", "DZD"),
    ("SARL SISCOPLAST", "DZD"),
    ("SARL SEGITEC", "EUR"),
    ("EURL INSTRUMEX", "EUR"),
    ("MOKVELD VALVES B.V.", "EUR"),
    ("DEF SPA", "DZD"),
    ("EURL STI", "DZD"),
    ("EURSPEED GENERAL TRADING LLC", "USD"),
    ("TD WILLIAMSON S.A.", "EUR"),
    ("HMT RUBBAGLAS", "USD"),
    ("ELECTRO INDUSTRY", "DZD"),
    ("ARADOS VALVES S.R.L.", "EUR"),
    ("SEMPHIL FLOW CONTROL", "EUR"),
    ("VAN LEEUWEN PIPE AND TUBE", "EUR"),
    ("EMERSON PROCESS MANAGEMENT", "USD"),
    ("IMPROTEC SPA", "DZD"),
]

EQUIPMENT_TEMPLATES = [
    ("100-PIT-{n:03d}", "Transmetteur de pression électronique intelligent 4-20mA HART SIL2 ({ref})", "U", (1200.0, 4800.0)),
    ("200-TIT-{n:03d}", "Transmetteur de température avec puits thermométrique 316SS ({ref})", "U", (950.0, 3200.0)),
    ("300-LIT-{n:03d}", "Transmetteur de niveau radar sans contact 80 GHz ATEX Ex d ({ref})", "U", (3400.0, 9500.0)),
    ("106-MOV-{n:03d}", "Vanne à boisseau sphérique motorisée (MOV) {dn}\" ANSI 600# API 6D ({ref})", "U", (18500.0, 95000.0)),
    ("206-SDV-{n:03d}", "Vanne d'arrêt d'urgence pneumatique (SDV) {dn}\" ANSI 600# SIL3 ({ref})", "U", (22000.0, 115000.0)),
    ("306-PSV-{n:03d}", "Soupape de sûreté à ressort (PSV) {dn}\"x{dn2}\" ANSI 600# API 526 ({ref})", "U", (4500.0, 24000.0)),
    ("ART-{sec}.{sub}", "Tube sans soudure en acier au carbone API 5L Gr X60 PSL2 {dn}\" SCH40", "ML", (85.0, 950.0)),
    ("ART-{sec}.{sub}", "Coude 90° LR {dn}\" SCH40 ASTM A234 Gr WPB ASME B16.9", "U", (140.0, 6500.0)),
    ("ART-{sec}.{sub}", "Bride à collerette Welding Neck {dn}\" 600# RF ASTM A105N ASME B16.5", "U", (220.0, 8900.0)),
    ("ART-{sec}.{sub}", "Câble électrique armé basse tension {dn}x{dn2} mm² CU/XLPE/SWA/PVC 0.6/1kV", "ML", (450.0, 8500.0)),
    ("300-TBT-{n:03d}", "Coffret de distribution électrique basse tension 400V AC IP65 ({ref})", "U", (380000.0, 1450000.0)),
    ("315-PK-{n:03d}", "Skid de dosage et d'injection chimique complet API 675 ({ref})", "ENS", (45000.0, 210000.0)),
]

DELAIS_POOL = [
    "15 jours",
    "Vingt (20) jours à compter de l'entrée en vigueur du contrat",
    "01 Mois",
    "Trois (03) mois à compter de la date de l'entrée en vigueur du contrat",
    "Quatre (04) mois à compter de la date de l'entrée en vigueur du contrat",
    "Cinq (05) Mois à compter de la date d'entrée en vigueur du contrat",
    "06 Mois",
    "07 mois",
    "08 Mois",
]

FRENCH_WORDS_NOISE = [
    "cent vingt-cinq DA & zéro sept cts",
    "VingtSeptMille Quatre Cent Quarante Deux",
    "CinquanteSeptMilleHuitCentSoixanteSeize",
    "trente-trois mille neuf cent dix-sept DA",
    "Deux million quatre cent soixante-neuf mille",
    "cent soixante-quinze DA",
]


def fmt_num(val: float, style: str = "fr_space") -> str:
    if style == "fr_space":
        s = f"{val:,.2f}".replace(",", " ").replace(".", ",")
        return s
    elif style == "dot_thousands":
        s = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return s
    return f"{val:.2f}"


def generate_dataset():
    examples = []

    # 1. Charger aussi les résultats extraits en direct de extracted_all_contracts.json s'ils existent déjà
    live_json = Path(r"C:\Users\MSI\.gemini\antigravity\brain\ff2e74c8-77e1-494f-88a7-056f2990662d\scratch\extracted_all_contracts.json")
    if live_json.exists():
        try:
            live_list = json.loads(live_json.read_text(encoding="utf-8"))
            for entry in live_list:
                ext = entry.get("extracted", {})
                items = ext.get("items", [])
                if items:
                    clean_items = []
                    for it in items[:30]:
                        clean_items.append({
                            "reference": it.get("reference", ""),
                            "designation": it.get("designation", ""),
                            "quantite_contractuelle": float(it.get("quantite_contractuelle", 1.0)),
                            "unite": it.get("unite", "U"),
                            "prix_unitaire": float(it.get("prix_unitaire", 0.0)),
                            "montant_total": float(it.get("montant_total", 0.0)),
                            "delai_livraison": it.get("delai_livraison", ext.get("delai_livraison", ""))
                        })
                    bpu_lines = "\n".join(
                        f"{i+1} | {it['reference']} | {it['designation']} | {it['quantite_contractuelle']} | {it['unite']} | {fmt_num(it['prix_unitaire'])} | {fmt_num(it['montant_total'])}"
                        for i, it in enumerate(clean_items)
                    )
                    inp_text = (
                        f"Fichier : {entry.get('file')}\n"
                        f"CONTRAT N° {ext.get('numero_contrat')}\n"
                        f"Fournisseur : {ext.get('fournisseur')}\n"
                        f"Objet : {ext.get('objet')}\n"
                        f"Article 07 - Délai de livraison : {ext.get('delai_livraison')}\n"
                        f"Montant global : {fmt_num(float(ext.get('montant') or 0))} {ext.get('devise')}\n"
                        f"ANNEXE 2 - BORDEREAU DES PRIX UNITAIRES ET DEVIS QUANTITATIF :\n{bpu_lines}"
                    )
                    out_obj = {
                        "numero_contrat": ext.get("numero_contrat"),
                        "fournisseur": ext.get("fournisseur"),
                        "objet": ext.get("objet"),
                        "delai_livraison": ext.get("delai_livraison"),
                        "date_signature": ext.get("date_signature", "2025-01-15"),
                        "montant": float(ext.get("montant") or 0),
                        "devise": ext.get("devise", "DZD"),
                        "items": clean_items,
                    }
                    examples.append({
                        "instruction": SYSTEM_PROMPT,
                        "input": inp_text,
                        "output": json.dumps(out_obj, ensure_ascii=False)
                    })
        except Exception:
            pass

    # 2. Ajouter le corpus de référence multi-variations (avec bruit OCR, inversion colonnes, BPU+DQE séparés)
    for base in REAL_CONTRACTS_CORPUS:
        out_obj = {
            "numero_contrat": base["numero_contrat"],
            "fournisseur": base["fournisseur"],
            "objet": base["objet"],
            "delai_livraison": base["delai_livraison"],
            "date_signature": base["date_signature"],
            "montant": base["montant"],
            "devise": base["devise"],
            "items": base["items"],
        }
        examples.append({
            "instruction": SYSTEM_PROMPT,
            "input": base["raw_excerpt"],
            "output": json.dumps(out_obj, ensure_ascii=False)
        })

        # Variation avec 2.1 BPU (sans quantité) suivi de 2.2 DQE (avec quantité et total)
        bpu_21 = "\n".join(
            f"{i+1} | {it['designation']} | {it['unite']} | {fmt_num(it['prix_unitaire'])}"
            for i, it in enumerate(base["items"])
        )
        dqe_22 = "\n".join(
            f"{i+1} | {it['designation']} | {it['unite']} | {it['quantite_contractuelle']:g} | {fmt_num(it['prix_unitaire'])} | {fmt_num(it['montant_total'])}"
            for i, it in enumerate(base["items"])
        )
        inp_bpu_dqe = (
            f"CONTRAT N° {base['numero_contrat']}\n"
            f"ENTRE GCB SPA ET {base['fournisseur']}\n"
            f"ARTICLE 01 - OBJET DU CONTRAT : {base['objet']}\n"
            f"ARTICLE 08 - DELAI DE LIVRAISON : {base['delai_livraison']}\n"
            f"ARTICLE 16 - MONTANT DU CONTRAT : {fmt_num(base['montant'])} {base['devise']} HT\n"
            f"ANNEXE 02 : DOCUMENTS FINANCIERS\n"
            f"2.1 BORDEREAU DES PRIX UNITAIRES (BPU) :\nN° | Désignation | Unité | Prix Unitaire HT\n{bpu_21}\n\n"
            f"2.2 DEVIS QUANTITATIF ET ESTIMATIF (DQE) :\nN° | Désignation | Unité | Qté | Prix Unitaire HT | Montant Total HT\n{dqe_22}"
        )
        examples.append({
            "instruction": SYSTEM_PROMPT,
            "input": inp_bpu_dqe,
            "output": json.dumps(out_obj, ensure_ascii=False)
        })

        # Variation cellules verticales PDF (style SEGITEC 29 où chaque cellule est sur sa propre ligne)
        vert_lines = []
        for i, it in enumerate(base["items"], 1):
            vert_lines.extend([
                f"1.{i}",
                it["designation"],
                f"{it['quantite_contractuelle']:g}",
                it["unite"],
                f"{fmt_num(it['prix_unitaire'])} {base['devise']}",
                f"{fmt_num(it['montant_total'])} {base['devise']}"
            ])
        inp_vert = (
            f"CONTRAT {base['numero_contrat']} - {base['fournisseur']}\n"
            f"Objet : {base['objet']}\n"
            f"Le délai de livraison : {base['delai_livraison']}\n"
            f"BORDEREAU DES PRIX :\n" + "\n".join(vert_lines)
        )
        examples.append({
            "instruction": SYSTEM_PROMPT,
            "input": inp_vert,
            "output": json.dumps(out_obj, ensure_ascii=False)
        })

    # 3. Générer 900 exemples variés couvrant tous les layouts OCR / PDF de GCB (BPU+DQE, Multi-lignes OCR, Tags, Bons de commande, Avenants)
    for sim_idx in range(900):
        fournisseur, devise = random.choice(SUPPLIERS_POOL)
        year = random.choice([2024, 2025])
        num_seq = random.randint(1, 145)
        ctype = random.choice(["PRC-DEP-GCB", "DG", "ACH", "BC", "AVENANT"])
        if ctype == "PRC-DEP-GCB":
            numero_contrat = f"{num_seq:02d}-PRC-DEP-GCB-{year}"
        elif ctype == "DG":
            numero_contrat = f"{num_seq:02d}/DG/{year}"
        elif ctype == "ACH":
            numero_contrat = f"{num_seq:02d}/ACH/{year}"
        elif ctype == "BC":
            numero_contrat = f"BC-{num_seq:02d}/ACH/{year}"
        else:
            numero_contrat = f"AVENANT-0{random.randint(1,9)}-CTR-{num_seq:02d}"

        delai = random.choice(DELAIS_POOL)
        date_sig = f"{year}-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
        n_items = random.randint(2, 12)
        items_list = []
        raw_rows = []
        layout_mode = random.choice(["standard_pipe", "bpu_plus_dqe", "ocr_multiline_noise", "vertical_cells", "unit_before_qty"])
        num_style = random.choice(["fr_space", "dot_thousands"])

        for k in range(1, n_items + 1):
            ref_tmpl, desig_tmpl, u_code, (p_min, p_max) = random.choice(EQUIPMENT_TEMPLATES)
            dn = random.choice([2, 3, 4, 6, 8, 10, 12, 16, 20, 24, 34])
            dn2 = random.choice([1.5, 2.5, 4, 6, 10, 16])
            ref_val = ref_tmpl.format(n=k + sim_idx % 50, sec=1 + (k - 1) // 5, sub=1 + (k - 1) % 5)
            desig_val = desig_tmpl.format(ref=ref_val, dn=dn, dn2=dn2)
            qty_val = float(random.choice([1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 50, 100, 250, 500, 1000, 2200]))
            pu_val = round(random.uniform(p_min, p_max), 2)
            if devise == "DZD" and pu_val < 5000:
                pu_val = round(pu_val * 145.0, 2)
            tot_val = round(qty_val * pu_val, 2)

            items_list.append({
                "reference": ref_val,
                "designation": desig_val,
                "quantite_contractuelle": qty_val,
                "unite": u_code,
                "prix_unitaire": pu_val,
                "montant_total": tot_val,
                "delai_livraison": delai
            })

            item_no = f"1.{k}" if "ART-" in ref_val else f"{k:02d}"
            if layout_mode == "standard_pipe":
                raw_rows.append(f"{item_no} | {desig_val} | {qty_val:g} | {u_code} | {fmt_num(pu_val, num_style)} | {fmt_num(tot_val, num_style)}")
            elif layout_mode == "unit_before_qty":
                raw_rows.append(f"{item_no} | {desig_val} | {u_code} | {qty_val:g} | {fmt_num(pu_val, num_style)} | {fmt_num(tot_val, num_style)}")
            elif layout_mode == "ocr_multiline_noise":
                noise_w = random.choice(FRENCH_WORDS_NOISE)
                half = len(desig_val) // 2
                raw_rows.append(
                    f"{desig_val[:half]}\n"
                    f"{item_no} | {noise_w} | {u_code} | {qty_val:g} | {fmt_num(pu_val, num_style)} | {fmt_num(tot_val, num_style)}\n"
                    f"{desig_val[half:].strip()}"
                )
            elif layout_mode == "vertical_cells":
                raw_rows.append(f"{item_no}\n{desig_val}\n{qty_val:g}\n{u_code}\n{fmt_num(pu_val, num_style)}\n{fmt_num(tot_val, num_style)}")

        montant_global = round(sum(x["montant_total"] for x in items_list), 2)
        objet_str = f"Acquisition de {items_list[0]['designation'].split('(')[0].strip()} et accessoires pour projet GCB"

        if layout_mode == "bpu_plus_dqe":
            bpu_part = "\n".join(
                f"1.{i+1} | {it['designation']} | {it['unite']} | {fmt_num(it['prix_unitaire'], num_style)}"
                for i, it in enumerate(items_list)
            )
            dqe_part = "\n".join(
                f"1.{i+1} | {it['designation']} | {it['unite']} | {it['quantite_contractuelle']:g} | {fmt_num(it['prix_unitaire'], num_style)} | {fmt_num(it['montant_total'], num_style)}"
                for i, it in enumerate(items_list)
            )
            table_block = (
                f"ANNEXE 02 : DOCUMENTS FINANCIERS\n"
                f"2.1 BORDEREAU DES PRIX UNITAIRES :\n{bpu_part}\n\n"
                f"2.2 DEVIS QUANTITATIF ET ESTIMATIF :\n{dqe_part}"
            )
        else:
            table_block = "BORDEREAU DES PRIX ET DEVIS QUANTITATIF :\n" + "\n".join(raw_rows)

        inp_doc = (
            f"ENTREPRISE NATIONALE DE CANALISATIONS - GCB SPA\n"
            f"CONTRAT N° {numero_contrat}\n"
            f"Fournisseur : {fournisseur}\n"
            f"Article 01 - Objet du contrat : {objet_str}\n"
            f"Article 07 - Délai de livraison : {delai}\n"
            f"Date de signature : {date_sig}\n"
            f"Article 16 - Montant du contrat : {fmt_num(montant_global, num_style)} {devise} HT\n"
            f"{table_block}"
        )

        out_doc = {
            "numero_contrat": numero_contrat,
            "fournisseur": fournisseur,
            "objet": objet_str,
            "delai_livraison": delai,
            "date_signature": date_sig,
            "montant": montant_global,
            "devise": devise,
            "items": items_list
        }

        examples.append({
            "instruction": SYSTEM_PROMPT,
            "input": inp_doc,
            "output": json.dumps(out_doc, ensure_ascii=False)
        })

    random.shuffle(examples)
    out_file = Path(r"d:\DATA BASE IA\dataset_procurement_contracts_bpu_instruct.jsonl")
    with out_file.open("w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"[+] Dataset généré : {out_file} ({len(examples)} exemples, {out_file.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    generate_dataset()
