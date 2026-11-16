# -*- coding: utf-8 -*-
"""
tests/run_all_tests.py
Suite complète de tests automatisés ARKAN v3 - Lot Électricité Multi-Disciplines.
Exécute les 8 bancs de test et produit un rapport de synthèse d'ingénierie.
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath('.'))

TEST_MODULES = [
    ("test_tag_normalizer", "Normalisation & Alias des TAGs techniques (P-101A vs 300-P-101A)"),
    ("test_validation_rules", "Règles normatives IEC 60364-5-54 (PE 3 paliers, Iz, remplissage)"),
    ("test_cross_discipline_reconciler", "Moteur de Recoupement Croisé Inter-Disciplines (7 contrôles triangulaires)"),
    ("test_master_excel_9tabs", "Consolidateur Universel Excel (Classeur Maître 9 onglets & marges)"),
    ("test_procurement_gateway", "Passerelle Procurement & Suivi BoQ (Injection quantités avec marge)"),
    ("test_dwg_routing_extraction", "Extracteur DWG Natif Cheminement (DW-300010 : polylignes, 100x50, buses)"),
    ("test_sld_matrix_extraction", "Extracteur PDF Tabulaire Unifilaire (DN-300004 : TGBT 19 pages, départs)"),
    ("test_dwg_earthing_extraction", "Extracteur DWG Natif Réseau de Terre (ELE-DW-300001 : 818m cuivre nu)")
]

def run_suite():
    print("=" * 80)
    print("  ARKAN v3 : EXÉCUTION DU BANC DE TESTS MULTI-DISCIPLINES LOT ÉLECTRICITÉ")
    print("=" * 80)
    
    passed = 0
    failed = 0
    results = []

    for mod_name, desc in TEST_MODULES:
        t0 = time.time()
        print(f"\n[RUNNING] {mod_name} : {desc}...")
        try:
            mod = __import__(f"tests.{mod_name}", fromlist=["*"])
            # Run the main function in the module
            run_func = None
            for attr in dir(mod):
                if attr.startswith("test_") and callable(getattr(mod, attr)):
                    run_func = getattr(mod, attr)
                    run_func()
                    break
            
            elapsed = time.time() - t0
            passed += 1
            results.append((mod_name, "PASS", f"{elapsed:.2f}s"))
            print(f"  --> [PASS] en {elapsed:.2f}s")
        except Exception as e:
            elapsed = time.time() - t0
            failed += 1
            results.append((mod_name, f"FAIL: {e}", f"{elapsed:.2f}s"))
            print(f"  --> [FAIL] en {elapsed:.2f}s : {e}")

    print("\n" + "=" * 80)
    print(f"  RÉSUMÉ DU BANC DE TESTS : {passed}/{len(TEST_MODULES)} TESTS RÉUSSIS")
    print("=" * 80)
    for mod_name, status, dur in results:
        stat_label = "[OK]  " if status == "PASS" else "[FAIL]"
        print(f"  {stat_label:7} {mod_name:35} {dur:8} ({status})")
    print("=" * 80)

    if failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    run_suite()
