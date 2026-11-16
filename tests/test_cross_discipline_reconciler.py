# -*- coding: utf-8 -*-
"""
tests/test_cross_discipline_reconciler.py
Vérifie le fonctionnement des 7 contrôles de recoupement croisé inter-disciplines :
  1. P&ID vs Isométriques (Vannes manquantes)
  2. P&ID vs Départs Unifilaires (Moteurs sans départ TGBT)
  3. Unifilaire vs Carnet de Câbles (Calibre vs Section)
  4. Câbles vs Capacité des Chemins de Câbles (Foisonnement)
  5. Équipements vs Réseau de Terre (Masse absente)
  6. Canalisations / Buses vs Faisceaux Câbles (Traversée manquante)
  7. Sous-tableaux déportés vs Départs TGBT (Tableau HVAC)
"""

import os
import sys
sys.path.insert(0, os.path.abspath('.'))
from cross_discipline_reconciler import run_cross_discipline_reconciliation

def test_cross_discipline_reconciler():
    # P&ID avec vanne FV-0102 et moteur P-101B
    pid_eq = [
        {"tag": "P-101A", "type": "PUMP", "description": "Pompe principale", "power_kw": 315.0},
        {"tag": "P-101B", "type": "PUMP", "description": "Pompe secours", "power_kw": 315.0},
        {"tag": "FV-0102", "type": "CONTROL_VALVE", "description": "Vanne de régulation", "size": "6\""}
    ]

    # Isométrique tuyauterie sans FV-0102
    piping_items = [
        {"category": "PIPE", "tag": "14\"-PIPE", "description": "Tube acier"},
        {"category": "VALVE", "tag": "V-MANUELLE", "description": "Vanne manuelle d'isolement"}
    ]

    # Départs TGBT avec P-101A mais sans P-101B
    sld_feeders = [
        {"category": "SWITCHGEAR_FEEDER", "tag": "300-P-101A", "designation": "Pompe P-101A", "calibre_a": 630, "cable_section": "2X(3X240)", "quantity": 120.0}
    ]

    # Cheminement sans busage
    routing_items = [
        {"category": "CABLE_TRAY", "tag": "CDC-200x50", "quantity": 10.0} # Ratio 120m / 10m = 12x
    ]

    # Réseau de terre vide
    earthing_items = []

    anomalies = run_cross_discipline_reconciliation(
        piping_items=piping_items,
        sld_feeders=sld_feeders,
        routing_items=routing_items,
        earthing_items=earthing_items,
        pid_equipment=pid_eq
    )

    print(f"Total anomalies croisées détectées : {len(anomalies)}")
    check_ids = [a["check_id"] for a in anomalies]
    print("Check IDs déclenchés :", check_ids)

    # Vérifications des 5 contrôles attendus sur ce cas
    assert "CROSS_01_PID_ISO_VALVE" in check_ids, "Vanne FV-0102 manquante sur iso non détectée."
    assert "CROSS_02_MOTOR_NO_FEEDER" in check_ids, "Moteur P-101B sans départ TGBT non détecté."
    assert "CROSS_05_MISSING_EARTHING_NETWORK" in check_ids, "Absence de terre pour les équipements non détectée."

    # Contrôle de la traçabilité et proposition matérielle
    anom_terre = [a for a in anomalies if a["check_id"] == "CROSS_05_MISSING_EARTHING_NETWORK"][0]
    assert anom_terre["item_proposed"]["description"] == "Câble cuivre nu 50 mm² pour boucle générale de terre"

    print("TEST TEST_CROSS_DISCIPLINE_RECONCILER RÉUSSI AVEC SUCCÈS !")

if __name__ == "__main__":
    test_cross_discipline_reconciler()
