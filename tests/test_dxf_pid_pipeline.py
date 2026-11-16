"""
test_pipeline_pid.py
====================
Test de validation unitaire et intégration pour le pipeline P&ID :
dxf_pid_parser.py et pid_equipment_blocks.py.
"""

import json
import math
import shutil
import sys
from pathlib import Path

# Assurer que la racine du projet est sur sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 1. Imports des 2 modules
import ezdxf
import dxf_pid_parser
import pid_equipment_blocks


def test_layer_roles():
    print("\n--- Test 1: Détection des rôles de calques ---")
    cfg = dxf_pid_parser.load_config(None)
    test_cases = [
        ("EQT", "equipment"),
        ("EQP1", "equipment"),
        ("EQUIPMENT", "equipment"),
        ("PIPE", "piping"),
        ("PIPE2", "piping"),
        ("PROCESS", "piping"),
        ("INST", "instrumentation"),
        ("05. INSTRUMENTATION", "instrumentation"),
        ("TEXT", "text"),
        ("06. TEXT", "text"),
        ("CARTOUCHE", "titleblock"),
        ("BORDER", "titleblock"),
        ("DEFPOINTS", "ignore"),
        ("REVCLOUD", "ignore"),
        ("UNKNOWN_LAYER", "other"),
    ]
    for layer_name, expected in test_cases:
        actual = dxf_pid_parser.layer_role(layer_name, cfg)
        assert actual == expected, f"Erreur layer_role: '{layer_name}' -> '{actual}' (attendu: '{expected}')"
    print("  [OK] Tous les rôles de calques sont correctement détectés.")


def test_synthetic_pid_pipeline():
    print("\n--- Test 2: Pipeline complet sur P&ID synthétique (Pression / Pompes / Inline Strainer) ---")
    test_dir = Path("cad_cache/test_pipeline_pid")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True, exist_ok=True)

    dxf_path = test_dir / "synthetic_pid.dxf"

    # Création d'un DXF représentatif avec ezdxf
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # 1. Pompe 1 (Calque EQT : forme libre de 10 traits/cercles)
    # 201-PP-001/A
    msp.add_circle((100, 100), radius=15, dxfattribs={"layer": "EQT"})
    msp.add_line((85, 100), (115, 100), dxfattribs={"layer": "EQT"})
    msp.add_line((100, 85), (100, 115), dxfattribs={"layer": "EQT"})
    for i in range(7):
        msp.add_line((90 + i * 2, 90), (90 + i * 2, 110), dxfattribs={"layer": "EQT"})
    msp.add_text("201-PP-001/A", dxfattribs={"insert": (100, 125), "height": 3.0, "layer": "TEXT"})

    # 2. Pompe 2 (Calque EQT : forme identique pour tester déduplication MD5)
    # 201-PP-001/B
    msp.add_circle((200, 100), radius=15, dxfattribs={"layer": "EQT"})
    msp.add_line((185, 100), (215, 100), dxfattribs={"layer": "EQT"})
    msp.add_line((200, 85), (200, 115), dxfattribs={"layer": "EQT"})
    for i in range(7):
        msp.add_line((190 + i * 2, 90), (190 + i * 2, 110), dxfattribs={"layer": "EQT"})
    msp.add_text("201-PP-001/B", dxfattribs={"insert": (200, 125), "height": 3.0, "layer": "TEXT"})

    # 3. Équipement en ligne : Crépine / Filtre 201-ST-001 sur calque PIPE (Correction 3)
    # Géométrie sur calque PIPE / PROCESS, pas sur EQT !
    msp.add_line((50, 100), (70, 100), dxfattribs={"layer": "PIPE"})
    msp.add_line((55, 95), (65, 105), dxfattribs={"layer": "PIPE"})
    msp.add_line((55, 105), (65, 95), dxfattribs={"layer": "PIPE"})
    msp.add_text("201-ST-001", dxfattribs={"insert": (60, 110), "height": 2.5, "layer": "TEXT"})

    # 4. Vanne 201-HV-001
    msp.add_line((130, 95), (140, 105), dxfattribs={"layer": "PIPE"})
    msp.add_line((140, 95), (130, 105), dxfattribs={"layer": "PIPE"})
    msp.add_text("201-HV-001", dxfattribs={"insert": (135, 110), "height": 2.5, "layer": "TEXT"})

    # 5. Ligne de tuyauterie 4"-P-101-CS
    msp.add_line((0, 100), (300, 100), dxfattribs={"layer": "PIPE"})
    msp.add_text('4"-P-101-CS-101', dxfattribs={"insert": (150, 105), "height": 3.0, "layer": "TEXT"})

    doc.saveas(str(dxf_path))
    print(f"  [OK] DXF synthétique généré : {dxf_path}")

    # Étape 1 : Exécution dxf_pid_parser
    parser_out = test_dir / "stage1_parser"
    raw_res, sem_res = dxf_pid_parser.parse_dxf_to_raw_and_semantic(dxf_path, out_folder=parser_out)

    assert (parser_out / "raw.json").exists(), "raw.json non généré"
    assert (parser_out / "semantic.json").exists(), "semantic.json non généré"
    assert len(raw_res["entities"]) > 0, "Aucune entité extraite dans raw"
    assert len(sem_res["elements"]) >= 3, "Éléments sémantiques manquants (attendu au moins 3 : 2 pompes + strainer)"
    print(f"  [OK] Étage 1 validé : {len(raw_res['entities'])} entités brutes, {len(sem_res['elements'])} éléments sémantiques")

    # Étape 2 : Exécution pid_equipment_blocks
    blocks_out = test_dir / "stage2_blocks"
    rep = pid_equipment_blocks.run_equipment_blocks(parser_out, blocks_out)

    assert (blocks_out / "equipment_candidates.json").exists(), "equipment_candidates.json manquant"
    assert (blocks_out / "semantic_with_equipment.json").exists(), "semantic_with_equipment.json manquant"
    assert (blocks_out / "equipment_preview.svg").exists(), "equipment_preview.svg vectoriel manquant"

    svg_content = (blocks_out / "equipment_preview.svg").read_text("utf-8")
    assert "<svg" in svg_content and "</svg>" in svg_content, "Contenu SVG invalide"
    print("  [OK] Étage 2 validé : Rendu SVG natif généré sans erreur CairoSVG")

    # Vérification Correction 3 : Inline Equipment
    cands = rep["candidates"]
    inline_cands = [c for c in cands if c.get("kind") == "inline_equipment"]
    print(f"  [OK] Candidats détectés : {len(cands)}")
    for c in cands:
        print(f"       -> {c['id']}: tags={c['tags']}, kind={c['kind']}, status={c['status']}")

    assert len(inline_cands) >= 1, "Correction 3 en échec : L'équipement en ligne 201-ST-001 n'a pas été détecté"
    st_cand = inline_cands[0]
    assert "201-ST-001" in st_cand["tags"], f"Tag inattendu pour inline: {st_cand['tags']}"
    assert st_cand["status"] == "inline_symbol_to_confirm", "Statut attendu inline_symbol_to_confirm"
    assert st_cand["user_decision"] is None, "Un symbole en ligne ne doit jamais etre auto-confirme"
    print("  [OK] Correction 3 validée : 201-ST-001 capturé comme inline_equipment (à confirmer par l'humain) !")

    # Vérification déduplication MD5 de forme identique
    shape_groups = rep["shape_groups"]
    print(f"  [OK] Groupes de forme identique : {shape_groups}")
    assert len(shape_groups) >= 1, "Déduplication de forme identique manquante pour les 2 pompes"
    pump_group = next(iter(shape_groups.values()))
    assert len(pump_group) == 2, f"Attendu 2 pompes dans le groupe identique, reçu {pump_group}"
    print(f"  [OK] Déduplication validée : Les 2 pompes 201-PP-001/A et B partagent le même shape_group ({pump_group})")


def test_real_project_dxf():
    print("\n--- Test 3: Test sur plan DXF réel du projet ---")
    real_dxfs = [
        Path("uploads/test_gtp.dxf"),
        Path("uploads/C3421-ROK1-081-PRC-DM-300001_2_test.dxf"),
        Path("uploads/21008-TRHT-DC-PR-18-OO-101_1_accore.dxf")
    ]
    target_dxf = None
    for r in real_dxfs:
        if r.exists():
            target_dxf = r
            break

    if not target_dxf:
        print("  [SKIP] Aucun DXF réel trouvé dans uploads/ pour le test 3")
        return

    print(f"  Test sur DXF réel : {target_dxf} ({target_dxf.stat().st_size / 1024:.1f} KB)")
    out_dir = Path(f"cad_cache/real_test_{target_dxf.stem}")
    raw_res, sem_res = dxf_pid_parser.parse_dxf_to_raw_and_semantic(target_dxf, out_dir / "parser")
    print(f"  -> Raw entities: {len(raw_res['entities'])}, Semantic elements: {len(sem_res['elements'])}, Lines: {len(sem_res['lines'])}")

    rep = pid_equipment_blocks.run_equipment_blocks(out_dir / "parser", out_dir / "blocks")
    print(f"  -> Equipment candidates: {len(rep['candidates'])}, Shape groups: {len(rep['shape_groups'])}")
    assert (out_dir / "blocks" / "equipment_preview.svg").exists()
    print(f"  [OK] Plan réel traité avec succès. Aperçu généré : {out_dir / 'blocks' / 'equipment_preview.svg'}")


if __name__ == "__main__":
    test_layer_roles()
    test_synthetic_pid_pipeline()
    test_real_project_dxf()
    print("\n==========================================")
    print(" TOUS LES TESTS SONT PASSÉS AVEC SUCCÈS !")
    print("==========================================")
