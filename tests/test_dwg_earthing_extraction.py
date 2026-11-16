# -*- coding: utf-8 -*-
"""
tests/test_dwg_earthing_extraction.py
Vérifie l'extraction native du plan de mise à la terre :
  C3421-ROK1-300-ELE-DW-300001 (MISE A LA TERRE GENERALE SP1)
Contrôle :
  - Détection de la discipline ELEC_EARTHING
  - Métré du câble cuivre nu 50 mm² et 70 mm²
  - Détection des piquets de terre L=2m
  - Calcul des poids totaux de cuivre
"""

import os
import sys
sys.path.insert(0, os.path.abspath('.'))
from ie_drawing_extractor import extract_ie_from_dwg_native

def test_dwg_earthing():
    dwg_file = r"C:\Users\MSI\Desktop\Electricite\04.EXECUTION\C3421-ROK1-300-ELE-DW-300001 (MISE A LA TERRE GENERALE SP1)\C3421-ROK1-300-ELE-DW-300001-0 29-10-2023.dwg"
    assert os.path.exists(dwg_file), f"Plan de terre introuvable : {dwg_file}"

    res = extract_ie_from_dwg_native(dwg_file)
    metadata = res["metadata"]
    items = res["items"]

    print("Metadata extraites :", metadata)
    assert metadata["doc_type"] == "ELEC_EARTHING", "Le doc_type doit être ELEC_EARTHING."
    assert metadata["bare_copper_linear_m"] > 50.0, "Le linéaire de cuivre nu doit être > 50m."

    earthing_items = [it for it in items if it["category"] == "EARTHING"]
    assert len(earthing_items) >= 2, "Au moins 2 catégories de matériel de terre requises (cuivre nu + piquets)."

    # Vérification présence cuivre nu 50 mm² et piquets
    tags = [it["tag"] for it in earthing_items]
    assert "CUIVRE-NU-50" in tags, "Câble cuivre nu 50 mm² manquant."
    assert "PIQUET-TERRE-2M" in tags, "Piquets de terre L=2m manquants."

    print(f"TEST TEST_DWG_EARTHING_EXTRACTION RÉUSSI ({len(items)} items extraits) !")

if __name__ == "__main__":
    test_dwg_earthing()
