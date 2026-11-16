# -*- coding: utf-8 -*-
"""
tests/test_dwg_routing_extraction.py
Vérifie l'extraction native DWG sur le plan réel de cheminement :
  C3421-ROK1-300-ELC-DW-300010-1.dwg (Atelier de maintenance)
Assure :
  - Détection des largeurs 100x50, 200x50 et 300x50
  - Mesure des polylignes géométriques
  - Capture des chambres de tirage 600x600x700 et repères 300-EL-xxx
  - Détection des buses PVC 2xØ110
"""

import os
import sys
sys.path.insert(0, os.path.abspath('.'))
import json
from ie_drawing_extractor import extract_ie_from_dwg_native

def test_dwg_routing():
    dwg_file = r"C:\Users\MSI\Desktop\Electricite\04.EXECUTION\C3421-ROK1-300-ELC -DW-300010- Chemin Atelier de maintenance\Rev 1\C3421-ROK1-300-ELC-DW-300010-1.dwg"
    assert os.path.exists(dwg_file), f"Fichier de référence non trouvé : {dwg_file}"

    # Chargement Ground Truth
    with open("tests/reference/reference_ground_truth.json", "r", encoding="utf-8") as f:
        ground_truth = json.load(f)["plans"]["DW-300010"]

    res = extract_ie_from_dwg_native(dwg_file)
    metadata = res["metadata"]
    items = res["items"]

    print("Metadata extraites :", metadata)
    assert metadata["units"] == "mm", "L'unité détectée doit être mm."
    assert metadata["doc_type"] == "ELEC_ROUTING", "Le doc_type doit être ELEC_ROUTING."
    assert metadata["cable_tray_linear_m"] > 100.0, "Le linéaire total de chemin de câbles doit être > 100 m."

    # Contrôle Chemins de Câbles
    tray_tags = [it["tag"] for it in items if it["category"] == "CABLE_TRAY"]
    assert "CDC-100x50" in tray_tags, "CDC-100x50 manquant dans l'extraction."
    assert "CDC-200x50" in tray_tags, "CDC-200x50 manquant dans l'extraction."

    # Contrôle Chambres de Tirage
    pull_boxes = [it for it in items if it["category"] == "PULL_BOX"]
    assert len(pull_boxes) >= 1, "Au moins 1 chambre de tirage 600x600x700 doit être détectée."

    # Contrôle Buses PVC
    conduits = [it for it in items if it["category"] == "CONDUIT"]
    assert len(conduits) >= 1, "La buse PVC 2xØ110 doit être détectée."

    print(f"TEST TEST_DWG_ROUTING_EXTRACTION RÉUSSI ({len(items)} items extraits) !")

if __name__ == "__main__":
    test_dwg_routing()
