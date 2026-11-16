"""
test_pid_analyzer_dxf_integration.py
====================================
Test d'intégration certifié pour la fonction parse_dwg_file dans pid_analyzer.py,
validant l'ingestion vectorielle 2 étages (dxf_pid_parser + pid_equipment_blocks)
sur plan réel DXF.
"""

import os
import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

import pytest


def _pick_sample():
    """DXF de test : uploads/test_gtp.dxf s'il est present (non livre dans le bundle), sinon l'echantillon
    synthetique fourni. Skip explicite plutot qu'un echec si aucun fichier n'est disponible."""
    for cand in (PROJECT_ROOT / "uploads" / "test_gtp.dxf", PROJECT_ROOT / "samples" / "synthetic_pid.dxf"):
        if cand.exists():
            return cand
    pytest.skip("aucun DXF d'echantillon disponible")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pid_analyzer import parse_dwg_file


def test_parse_dwg_file_with_real_pid_dxf():
    """
    Vérifie l'intégration complète du pipeline vectoriel 2 étages sur uploads/test_gtp.dxf:
      - Étage 1 : Parsing DXF géométrique & sémantique brut
      - Étage 2 : Enrichissement des équipements, déduplication, détection des lignes et aperçu SVG
    """
    dxf_sample = _pick_sample()

    result = parse_dwg_file(str(dxf_sample), output_image_dir="generated_visuals", discipline="pid")

    # 1. Structure de données retournée
    required_keys = [
        "elements",
        "lines",
        "loops",
        "warnings",
        "equipment_candidates",
        "equipment",
        "valves",
        "instruments",
        "image_url",
        "svg_url",
        "schematic_svg_url",
        "equipment_preview_url",
        "document",
    ]
    for key in required_keys:
        assert key in result, f"La clé obligatoire '{key}' est absente du dictionnaire retourné"

    # 2. Présence et enrichissement des éléments
    elements = result["elements"]
    assert len(elements) > 0, "Aucun élément n'a été extrait du DXF"
    assert len(result["lines"]) > 0, "Les lignes de tuyauterie doivent être détectées"
    assert len(result["equipment_candidates"]) > 0, "Les équipements candidats doivent être extraits"

    # 3. Validation de l'enrichissement des équipements
    equipments = result["equipment"]
    assert len(equipments) > 0, "Au moins un équipement doit être identifié dans test_gtp.dxf"

    for eq in equipments:
        assert "tag" in eq and eq["tag"], "L'équipement doit posséder un tag"
        assert "candidate_id" in eq, f"L'équipement {eq['tag']} doit être relié à un candidat (candidate_id)"
        assert "bbox" in eq or "box" in eq, f"L'équipement {eq['tag']} doit posséder une bounding box"
        # un equipement non issu d'un bloc reste "a confirmer" tant qu'un humain ne l'a pas valide
        assert eq.get("review_status") in ("ok", "to_confirm", "human_confirmed"), eq["tag"]
        if eq.get("review_status") != "to_confirm":
            assert eq.get("confidence", 0) >= 0.85, f"La confiance de {eq['tag']} doit être >= 0.85"
        assert "proposed_block" in eq, f"L'équipement {eq['tag']} doit avoir un nom de bloc proposé"

    # 4. Validation du rendu vectoriel SVG
    image_url = result["image_url"]
    assert image_url is not None, "image_url ne doit pas être None"
    assert image_url.lower().endswith(".svg"), f"image_url doit pointer vers un fichier SVG (obtenu: {image_url})"
    assert Path(image_url).exists(), f"Le fichier image SVG {image_url} doit exister sur disque"
    assert Path(image_url).stat().st_size > 1000, f"Le fichier SVG {image_url} ne doit pas être vide"

    # 4.bis Validation du Schéma P&ID Simplifié (pid_schematic)
    schematic_svg_url = result["schematic_svg_url"]
    assert schematic_svg_url is not None, "schematic_svg_url ne doit pas être None"
    assert schematic_svg_url.lower().endswith(".svg"), f"schematic_svg_url doit pointer vers un SVG: {schematic_svg_url}"
    assert Path(schematic_svg_url).exists(), f"Le fichier schéma simplifié {schematic_svg_url} doit exister sur disque"
    assert Path(schematic_svg_url).stat().st_size > 1000, "Le fichier schéma simplifié SVG ne doit pas être vide"
    schematic_content = Path(schematic_svg_url).read_text(encoding="utf-8")
    assert 'class="pid-schematic-element' in schematic_content, "Le schéma doit contenir des éléments interactifs"
    assert 'class="eq-info-bubble"' in schematic_content, "Le schéma doit contenir les bulles d'informations normatives"
    assert 'data-lines=' in schematic_content, "Les équipements doivent posséder l'attribut data-lines"
    assert 'data-loops=' in schematic_content, "Les équipements doivent posséder l'attribut data-loops"
    assert '<g id="annotations-panel">' in schematic_content, "Le schéma doit inclure le panneau d'annotations"

    # 4.ter Validation de svg_url (garantie de la double génération systématique)
    svg_url = result.get("svg_url")
    assert svg_url is not None and len(svg_url) > 0, "svg_url ne doit pas être None ou vide"
    assert Path(svg_url).exists(), f"Le fichier SVG principal {svg_url} doit exister sur le disque"

    # 4.quater Validation de l'aperçu des équipements (equipment_preview.svg)
    equipment_preview_url = result["equipment_preview_url"]
    assert equipment_preview_url is not None, "equipment_preview_url ne doit pas être None"
    assert equipment_preview_url.lower().endswith(".svg"), f"equipment_preview_url doit être un SVG: {equipment_preview_url}"
    assert Path(equipment_preview_url).exists(), f"L'aperçu équipements {equipment_preview_url} doit exister sur disque"
    assert Path(equipment_preview_url).stat().st_size > 1000, "L'aperçu équipements SVG ne doit pas être vide"

    # 5. Validation des métadonnées du document
    doc = result["document"]
    assert isinstance(doc, dict), "document doit être un dictionnaire de métadonnées"


def test_parse_dwg_file_file_not_found():
    """Vérifie le comportement défensif quand le fichier n'existe pas."""
    res = parse_dwg_file("chemin_inexistant_bidon.dwg")
    assert res == {"elements": [], "width": 800, "height": 600, "image_url": None}


def test_parse_dwg_file_other_discipline():
    """Vérifie que pour d'autres disciplines (ex: civil), le fallback s'exécute sans régression."""
    dxf_sample = _pick_sample()
    res = parse_dwg_file(str(dxf_sample), discipline="civil")
    assert "elements" in res
    assert "width" in res
    assert "height" in res
