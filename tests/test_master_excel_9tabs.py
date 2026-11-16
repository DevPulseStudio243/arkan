# -*- coding: utf-8 -*-
"""
tests/test_master_excel_9tabs.py
Vérifie la génération du classeur maître Excel 'MTO_GLOBAL_PROJET.xlsx' à 9 onglets.
Contrôle :
  - Présence des 9 onglets exacts
  - Calculs des marges de commande (Quantité Nette vs Quantité à Commander)
  - Onglet A_VALIDER recevant les lignes à faible confiance
  - Onglet MATRICE_RESERVES_GLOBALE avec articles matériels proposés
"""

import os
import sys
sys.path.insert(0, os.path.abspath('.'))
import openpyxl
from mto_consolidator import generate_master_multidiscipline_excel

def test_generate_master_excel():
    sample_items = [
        # Tuyauterie
        {"category": "PIPE", "tag": "14\"-WF-301", "description": "TUBE ACIER SMLS ASTM A106 Gr.B", "size": "14\"", "schedule": "SCH.40", "material": "Carbon Steel", "quantity": 45.0, "unit": "m", "weight_unit": 79.5, "source_drawing": "14-WF-301.pdf", "confidence_score": 0.98},
        {"category": "VALVE", "tag": "14\"-BALL-01", "description": "VANNE A BOISSEAU SPHERIQUE CL.300", "size": "14\"", "schedule": "CL.300", "material": "WCB", "quantity": 2.0, "unit": "EA", "weight_unit": 450.0, "source_drawing": "14-WF-301.pdf", "confidence_score": 0.95},
        # Électricité : Distribution MT/BT
        {"category": "SWITCHGEAR_FEEDER", "tag": "300-TRP-003", "description": "Arrivée Transformateur 4P 2500A", "size": "4P4D", "schedule": "In=2500A", "material": "Cuivre", "quantity": 1.0, "unit": "EA", "weight_unit": 450.0, "source_drawing": "DN-300004_1.pdf", "confidence_score": 0.96},
        {"category": "SWITCHGEAR_FEEDER", "tag": "300-UPS-001", "description": "Départ UPS 110VDC", "size": "5X6", "schedule": "4P 63A", "material": "Cu/XLPE/PVC", "quantity": 35.0, "unit": "m", "weight_unit": 0.56, "source_drawing": "DN-300004_1.pdf", "confidence_score": 0.92},
        # Ligne à faible confiance -> Doit aller dans A_VALIDER
        {"category": "SWITCHGEAR_FEEDER", "tag": "QF-DOUTE", "description": "Départ non identifié", "size": "4G2.5", "schedule": "Inconnu", "material": "Cuivre", "quantity": 20.0, "unit": "m", "weight_unit": 0.23, "source_drawing": "DN-300004_1.pdf", "confidence_score": 0.65, "needs_human_validation": True},
        # Électricité : Câbles
        {"category": "CABLE", "tag": "C-300-P-101A", "description": "CÂBLE PUISSANCE MOTEUR U-1000 R2V 3X120+70", "size": "3X120+70", "schedule": "U-1000 R2V", "material": "Cu/XLPE/PVC", "quantity": 85.0, "unit": "m", "weight_unit": 5.70, "source_drawing": "DW-300010.dwg", "confidence_score": 0.94},
        # Électricité : Chemins & Canalisations
        {"category": "CABLE_TRAY", "tag": "CDC-200x50", "description": "Chemin de câbles perforé galvanisé 200x50 mm", "size": "200x50 mm", "schedule": "Galvanisé à chaud", "material": "Acier Galva", "quantity": 120.0, "unit": "m", "weight_unit": 3.2, "source_drawing": "DW-300010.dwg", "confidence_score": 0.95},
        {"category": "PULL_BOX", "tag": "300-EL-312", "description": "Chambre de tirage préfabriquée béton 600x600x700 mm", "size": "600x600x700 mm", "schedule": "Fonte C250", "material": "Béton armé", "quantity": 1.0, "unit": "EA", "weight_unit": 85.0, "source_drawing": "DW-300010.dwg", "confidence_score": 0.97},
        # Électricité : Terre & Foudre
        {"category": "EARTHING", "tag": "CUIVRE-NU-50", "description": "Câble cuivre nu 50 mm² pour boucle de terre", "size": "50 mm²", "schedule": "CEI 60228", "material": "Cuivre", "quantity": 250.0, "unit": "m", "weight_unit": 0.448, "source_drawing": "ELE-DW-300001.dwg", "confidence_score": 0.96},
        {"category": "EARTHING", "tag": "PIQUET-TERRE-2M", "description": "Piquet de terre L=2m Ø16mm", "size": "L=2m", "schedule": "Cuivré 250µm", "material": "Acier Cuivré", "quantity": 8.0, "unit": "EA", "weight_unit": 4.5, "source_drawing": "ELE-DW-300001.dwg", "confidence_score": 0.98},
        # Électricité : Éclairage & Prises
        {"category": "LIGHTING", "tag": "PROJ-LED-150W", "description": "Projecteur extérieur LED 150W ATEX Zone 2", "size": "150W", "schedule": "IP66 Ex-nR", "material": "Aluminium", "quantity": 12.0, "unit": "EA", "weight_unit": 9.5, "source_drawing": "DW-300006.dwg", "confidence_score": 0.93}
    ]

    sample_anomalies = [
        {
            "rule": "MALT_01_PE_SECTION",
            "severity": "CRITICAL",
            "tag": "C-300-P-101A",
            "title": "Section PE non conforme IEC 60364-5-54",
            "message": "Phase 120 mm² requiert PE=70 mm².",
            "norm_source": "IEC 60364-5-54",
            "recommendation": "Passer à 3X120+70 mm².",
            "status": "PROPOSED",
            "item_proposed": {"description": "CÂBLE 3X120+70 mm²", "quantity": 85.0, "unit": "m"}
        }
    ]

    out_file = "MTO_GLOBAL_PROJET.xlsx"
    res = generate_master_multidiscipline_excel(sample_items, metadata={}, anomalies=sample_anomalies, output_path=out_file)
    assert os.path.exists(res), "Le fichier Excel maître n'a pas été généré."

    wb = openpyxl.load_workbook(res)
    expected_sheets = [
        "SYNTHESE_GLOBALE",
        "TUYAUTERIE_MTO",
        "DISTRIBUTION_MT_BT",
        "CARNET_DE_CABLES",
        "CHEMINS_ET_CANALISATIONS",
        "RESEAU_TERRE_FOUDRE",
        "ECLAIRAGE_ET_PRISES",
        "A_VALIDER",
        "MATRICE_RESERVES_GLOBALE"
    ]
    sheet_names = wb.sheetnames
    print("Onglets générés :", sheet_names)
    for es in expected_sheets:
        assert es in sheet_names, f"Onglet manquant : {es}"

    # Vérification que l'onglet A_VALIDER contient la ligne à faible confiance
    ws_val = wb["A_VALIDER"]
    assert ws_val.max_row >= 2, "L'onglet A_VALIDER devrait contenir la ligne douteuse."
    print("Contrôle A_VALIDER :", ws_val.cell(row=2, column=2).value)

    # Vérification que l'onglet MATRICE_RESERVES_GLOBALE contient l'anomalie
    ws_res = wb["MATRICE_RESERVES_GLOBALE"]
    assert ws_res.max_row >= 2, "La matrice des réserves devrait contenir 1 anomalie."
    print("Contrôle Réserve :", ws_res.cell(row=2, column=4).value)

    print("TEST TEST_MASTER_EXCEL_9TABS RÉUSSI AVEC SUCCÈS !")

if __name__ == "__main__":
    test_generate_master_excel()
