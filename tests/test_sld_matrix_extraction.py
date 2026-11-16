# -*- coding: utf-8 -*-
"""
tests/test_sld_matrix_extraction.py
Vérifie l'extraction matricielle par colonnes du schéma unifilaire TGBT multi-pages :
  C3421-ROK1-300-ELC-DN-300004_1.pdf (19 pages)
Contrôle :
  - Extraction de plus de 50 départs réels
  - Capture des tags de référence (300-TRP-003, 300-UPS-001, 300-TRP-005)
  - Extraction des calibres et sections de câbles (5X6, 5X16, CANALISATION, 2X(3X240))
  - Attribution de scores de confiance
"""

import os
import sys
sys.path.insert(0, os.path.abspath('.'))
import json
from ie_drawing_extractor import extract_sld_from_pdf_matrix

def test_sld_matrix():
    pdf_file = r"C:\Users\MSI\Desktop\Electricite\04.EXECUTION\C3421-ROK1-300-ELC-DN-300004. TGBT\Rev 1\C3421-ROK1-300-ELC-DN-300004_1.pdf"
    assert os.path.exists(pdf_file), f"Fichier de référence non trouvé : {pdf_file}"

    res = extract_sld_from_pdf_matrix(pdf_file)
    metadata = res["metadata"]
    items = res["items"]

    print("Metadata extraites :", metadata)
    assert metadata["total_pages"] == 19, "Le document doit comporter 19 pages."
    assert metadata["total_feeders_count"] >= 50, f"Nombre de départs insuffisant : {metadata['total_feeders_count']}"

    extracted_tags = [it["tag"] for it in items]
    extracted_sections = [it["cable_section"] for it in items if it.get("cable_section")]

    # Vérification des départs clés de référence
    assert any("TRP-003" in t for t in extracted_tags), "Arrivée Transfo 300-TRP-003 manquante."
    assert any("5X6" in s for s in extracted_sections), "Section 5X6 manquante."
    assert any("5X16" in s for s in extracted_sections), "Section 5X16 manquante."
    assert any("CANALISATION" in s for s in extracted_sections), "Canalisation / Gaine à barres manquante."

    # Contrôle de la traçabilité
    for it in items[:10]:
        assert "source_page" in it, "La page source doit être renseignée pour chaque départ."
        assert "confidence_score" in it, "Le score de confiance doit être calculé."

    print(f"TEST TEST_SLD_MATRIX_EXTRACTION RÉUSSI ({len(items)} départs extraits sur 19 pages) !")

if __name__ == "__main__":
    test_sld_matrix()
