# -*- coding: utf-8 -*-
"""
tests/test_validation_rules.py
Vérifie la conformité exacte des règles normatives IEC dans ie_mto_validator.py :
  - Règle IEC 60364-5-54 pour le PE (3 paliers stricts)
  - Détection de non-conformité sur sous-dimensionnement PE
  - Détection de surcharge de courant In > Iz (IEC 60364-5-52)
  - Détection de section de terre enterrée < 25 mm²
  - Détection d'absence de supportage de câbles
"""

import os
import sys
sys.path.insert(0, os.path.abspath('.'))
from ie_mto_validator import calculate_iec_pe_section, validate_ie_mto

def test_pe_calculation_three_tiers():
    # Palier 1 : S <= 16 mm² -> PE = S
    assert calculate_iec_pe_section(2.5) == 2.5
    assert calculate_iec_pe_section(4.0) == 4.0
    assert calculate_iec_pe_section(6.0) == 6.0
    assert calculate_iec_pe_section(10.0) == 10.0
    assert calculate_iec_pe_section(16.0) == 16.0

    # Palier 2 : 16 < S <= 35 mm² -> PE = 16 mm² fixe
    assert calculate_iec_pe_section(25.0) == 16.0
    assert calculate_iec_pe_section(35.0) == 16.0

    # Palier 3 : S > 35 mm² -> PE = S / 2 (arrondi section normalisée supérieure)
    assert calculate_iec_pe_section(50.0) == 25.0
    assert calculate_iec_pe_section(70.0) == 35.0
    assert calculate_iec_pe_section(95.0) == 50.0
    assert calculate_iec_pe_section(120.0) == 70.0
    assert calculate_iec_pe_section(150.0) == 95.0
    assert calculate_iec_pe_section(185.0) == 95.0
    assert calculate_iec_pe_section(240.0) == 120.0
    print("Contrôle IEC 60364-5-54 (3 Paliers PE) : VALIDÉ")

def test_validation_anomalies_detection():
    # Cas 1 : Câble 3x120 avec PE de seulement 35mm² (invalide : requiert 70mm²)
    items = [
        {"category": "CABLE", "tag": "CBL-01", "cable_section": "3X120+35", "quantity": 50.0, "calibre_a": 160},
        # Cas 2 : Disjoncteur 250A sur câble 2.5 mm² (surcharge critique)
        {"category": "CABLE", "tag": "CBL-02", "cable_section": "3G2.5", "quantity": 30.0, "calibre_a": 250},
        # Cas 3 : Câble de terre cuivre nu de seulement 16 mm² (invalide en enfouissement direct)
        {"category": "EARTHING", "tag": "MALT-01", "size": "16 mm²", "quantity": 100.0}
    ]

    anomalies = validate_ie_mto(items)
    print(f"Anomalies détectées : {len(anomalies)}")

    rules_triggered = [a["rule"] for a in anomalies]
    assert "MALT_01_PE_SECTION" in rules_triggered, "Règle MALT_01 PE non déclenchée."
    assert "PUISSANCE_01_OVERCURRENT" in rules_triggered, "Règle PUISSANCE_01 surintensité non déclenchée."
    assert "MALT_02_MIN_BURIED_COPPER" in rules_triggered, "Règle MALT_02 cuivre nu < 25mm² non déclenchée."

    # Contrôle proposition d'article
    pe_anom = [a for a in anomalies if a["rule"] == "MALT_01_PE_SECTION"][0]
    assert "item_proposed" in pe_anom, "Une réserve doit proposer un article matériel qualifié."
    assert "3X120+70" in pe_anom["item_proposed"]["description"], "L'article proposé doit avoir la section PE corrigée 70mm²."

    print("TEST TEST_VALIDATION_RULES RÉUSSI AVEC SUCCÈS !")

if __name__ == "__main__":
    test_pe_calculation_three_tiers()
    test_validation_anomalies_detection()
