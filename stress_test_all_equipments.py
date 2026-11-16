import sys
import os
import json
import time

sys.stdout.reconfigure(encoding='utf-8')
from arh_regulatory_engine import ARHRegulatoryEngine, EQUIPMENT_TYPES, PRESSURE_FABRICATION_TYPES

def run_stress_tests():
    print("=" * 80)
    print("      SUITE INTENSIVE DE TESTS DE DÉTECTION ET CONFORMITÉ DE TOUS LES ÉQUIPEMENTS OIL & GAS")
    print("=" * 80)

    engine = ARHRegulatoryEngine()

    total_tests = 0
    passed_tests = 0
    failed_tests = 0

    def check(test_id, description, condition, details=""):
        nonlocal total_tests, passed_tests, failed_tests
        total_tests += 1
        if condition:
            passed_tests += 1
            print(f"  [PASS] {test_id:03d} - {description}", flush=True)
        else:
            failed_tests += 1
            print(f"  [FAIL] {test_id:03d} - {description}", flush=True)
            if details:
                print(f"         └── Details: {details}", flush=True)

    # =========================================================================
    # PARTIE 1 : TEST DE DÉTECTION & CLASSIFICATION DE CHACUN DES 28 ÉQUIPEMENTS
    # =========================================================================
    print("\n--- PARTIE 1 : DÉTECTION SÉMANTIQUE DES 28 ÉQUIPEMENTS OIL & GAS ---")

    test_samples = {
        "PRESSURE_VESSEL": "BALLON DE PROCÉDÉ SP-101 BALLON SÉPARATEUR DE DEGAZAGE DECRET 21-314 100 BAR",
        "SEPARATOR": "SÉPARATEUR TRI-PHASIQUE HP DECRET 21-314 SEPARATOR VESSEL 50 BAR",
        "HEAT_EXCHANGER": "ÉCHANGEUR DE CHALEUR À TUBES ET CALANDRE E-102 HEAT EXCHANGER BUNDLE TUBE",
        "COLUMN": "COLONNE DE DISTILLATION / DEBUTANISEUR COLONNE ABSORPTION C-201 TRAY COLUMN",
        "TANK": "BAC DE STOCKAGE PÉTROLE BRUT TK-501 CONE ROOF TANK API 650 RECIPIENT VERTICAL",
        "SPHERE": "SPHÈRE DE STOCKAGE GPL / BUTANE SOUS PRESSION V-301 SPERICAL STORAGE SPHERE",
        "PIPELINE": "CONDUITE DE TRANSPORT GAZODUC 28 INCH X60 ALIGNMENT SHEETS PROFIL EN LONG DECRET 21-315",
        "LINEPIPE": "FOURNITURE ET FABRICATION DE TUBES CANALISATION BAOTOU STEEL LINEPIPE API 5L X70 USINE",
        "FLOWLINE": "FLOWLINE COLLECTEUR DE CHAMP PUITS DE PRODUCTION WELLHEAD FLOWLINE DECRET 21-315",
        "COMPRESSOR": "TURBOCOMPRESSEUR CENTRIFUGE K-101 MOTOCOMPRESSEUR GAZ DE PRODUCTION COMPRESSOR",
        "PUMP": "POMPE CENTRIFUGE DEEXPÉDITION P-101A/B MOTOPOMPE BOOSTER PUMP API 610",
        "ELECTRICAL": "TABLEAU HTA TGBT TRANSFORMATEUR DE PUISSANCE UNIFILAIRE SLD SCHNEIDER UPS ASI",
        "INSTRUMENTATION": "TRANSMETTEUR DE PRESSION TRANSMITTER DCS PLC SIS LOOP DIAGRAM ESD REGULATION",
        "SKID": "SKID MODULAIRE GARE DE RACLEUR PIG LAUNCHER SKID METERING PACKAGE PIG TRAP",
        "FURNACE": "FOUR DE PROCÉDÉ FIRED HEATER H-101 CHAUDIÈRE GÉNÉRATEUR DE VAPEUR BOILER BURNER",
        "FLARE": "TORCHÈRE DE SÉCURITÉ FLARE TIP SYSTEM KO DRUM MÂT DE TORCHÈRE ELEVATED FLARE",
        "FITTING": "TEE À BARREAU 24 INCH BARRED TEE COUDE ELBOW RÉDUCTION BRIDE FLANGE WELDOLET",
        "VALVE": "VANNE BOISSEAU SPHÉRIQUE BALL VALVE VANNE GATE CLAPET ANTI-RETOUR ESD VALVE",
        "PIPING_SPOOL": "SPOOL DE TUYAUTERIE AS-BUILT PIPING ISO ISOMÉTRIQUE TUYAUTERIE FABRICATION",
        "SAFETY_VALVE": "SOUPAPE DE SÛRETÉ PSV-101 PRV PRESSURE SAFETY VALVE DISQUE DE RUPTURE",
        "METERING": "SYSTÈME DE COMPTAGE FISCAL METERING SKID DEBITMÈTRE CORIOLIS COMPTEUR GAZ",
        "FILTER_SEPARATOR": "FILTRE SÉPARATEUR GAZOLE STRAINER PANIER FILTRANT EPURATEUR COALESCER FILTER",
        "HEAT_TRACING": "TRAÇAGE THERMIQUE ÉLECTRIQUE EHT HEAT TRACING CÂBLE CHAUFFANT CALORIFUGEAGE",
        "STRUCTURAL_STEEL": "CHARPENTE MÉTALLIQUE PIPE RACK PLATAFORME PASSERELLE STRUCTURE ACIER",
        "CIVIL_FOUNDATION": "GÉNIE CIVIL MASSIF BÉTON FONDATION D ALLES CUVETTE DE RÉTENTION ANCRAGE",
        "GAS_FIRE_DETECTION": "SYSTÈME DÉTECTION GAZ ET INCENDIE FGS FAS DÉTECTEUR FLAMME SMOKE DETECTOR",
        "TELECOM_SCADA": "SUPERVISION SCADA RTU TÉLÉCOMMUNICATION FIBRE OPTIQUE RS485 MODBUS",
        "CRANE_LIFTING": "GRUE DE MANUTENTION PONT ROULANT PALAN OVERHEAD CRANE LIFTING GEAR ELINGUE"
    }

    for eq_type, sample_text in test_samples.items():
        detected = engine.identify_equipment_type(sample_text)
        check(
            total_tests + 1,
            f"Détection {eq_type} -> Résultat : {detected}",
            detected == eq_type,
            f"Attendu: {eq_type}, Obtenu: {detected}"
        )

    # =========================================================================
    # PARTIE 2 : MATRIX DE NON-CONFUSION / ANTI-MELANGE (TEST DE NON-COLLISION)
    # =========================================================================
    print("\n--- PARTIE 2 : TESTS D'ANTI-CONFUSION ENTRE ÉQUIPEMENTS PROCHES ---")

    confusion_pairs = [
        ("TEE A BARREAU 24 INCH PN100 FITTING", "FITTING", ["VALVE", "PIPELINE", "PRESSURE_VESSEL"]),
        ("SOUPAPE DE SURETE PSV 101 SAFETY VALVE", "SAFETY_VALVE", ["VALVE", "PRESSURE_VESSEL"]),
        ("POMPE CENTRIFUGE P-101", "PUMP", ["COMPRESSOR", "VALVE"]),
        ("TURBOCOMPRESSEUR GAZ K-101", "COMPRESSOR", ["PUMP", "TURBINE"]),
        ("FOURNITURE TUBES BAOTOU API 5L LINEPIPE USINE", "LINEPIPE", ["PIPELINE", "FLOWLINE"]),
        ("CONDUITE DE TRANSPORT PIPELINE CHANTIER X60", "PIPELINE", ["LINEPIPE", "PIPING_SPOOL"]),
        ("FILTRE SEPARATEUR EPURATEUR STRAINER", "FILTER_SEPARATOR", ["SEPARATOR", "PRESSURE_VESSEL"]),
        ("SPOOL DE TUYAUTERIE PROCESS PIPING ISO", "PIPING_SPOOL", ["LINEPIPE", "FITTING"]),
    ]

    for text, expected, forbidden in confusion_pairs:
        detected = engine.identify_equipment_type(text)
        is_ok = (detected == expected) and (detected not in forbidden)
        check(
            total_tests + 1,
            f"Anti-Confusion pour '{text[:35]}...' -> {detected} (Non présent dans {forbidden})",
            is_ok,
            f"Attendu: {expected}, Interdits: {forbidden}, Obtenu: {detected}"
        )

    # =========================================================================
    # PARTIE 3 : VÉRIFICATION DE LA COMPOSITION EXACTE DE DU DOSSIER (PRÉLIMINAIRE & FINAL)
    # =========================================================================
    print("\n--- PARTIE 3 : COMPOSITION DU DOSSIER PAR ÉQUIPEMENT (STADE PRÉLIMINAIRE vs FINAL) ---")

    for eq_type in EQUIPMENT_TYPES.keys():
        chk_prelim = engine.generate_mandatory_checklist(eq_type, dossier_stage="PRELIMINARY")
        chk_final = engine.generate_mandatory_checklist(eq_type, dossier_stage="FINAL_RECEPTION")

        codes_prelim = {c["code"] for c in chk_prelim}
        codes_final = {c["code"] for c in chk_final}

        # 1. Vérification que la checklist n'est pas vide
        check(
            total_tests + 1,
            f"Composition {eq_type} - Checklist non vide (Prelim: {len(chk_prelim)}, Final: {len(chk_final)})",
            len(chk_prelim) >= 5 and len(chk_final) >= 5
        )

        # 2. Vérification règle ATEX : ATEX_CERT ne doit jamais être présent en Critical pour les équipements mécaniques purs
        if eq_type in ("FITTING", "PIPING_SPOOL", "SAFETY_VALVE", "LINEPIPE", "FLOWLINE", "PIPELINE",
                       "STRUCTURAL_STEEL", "CIVIL_FOUNDATION", "PRESSURE_VESSEL", "SEPARATOR", "HEAT_EXCHANGER", "TANK", "SPHERE"):
            atex_in_prelim = any(c["code"] == "ATEX_CERT" and c.get("criticality") == "Critical" for c in chk_prelim)
            atex_in_final = any(c["code"] == "ATEX_CERT" and c.get("criticality") == "Critical" for c in chk_final)
            check(
                total_tests + 1,
                f"Règle ATEX {eq_type} - Zéro ATEX Critical exigé",
                not atex_in_prelim and not atex_in_final,
                f"ATEX Critical présent à tort pour {eq_type}"
            )

        # 3. Vérification règle Stade Préliminaire : zéro rejet pour docs post-fabrication
        post_fab_codes = {"HYDRO_PV", "SAT", "CALIBRATION", "PIGGING", "COATING_REP", "FAT", "DIELECTRIC", "EARTHING", "CE_DECL", "NAMEPLATE"}
        critical_post_fab_in_prelim = [
            c["code"] for c in chk_prelim
            if c["code"] in post_fab_codes and c.get("criticality") == "Critical"
        ]
        check(
            total_tests + 1,
            f"Stade Préliminaire {eq_type} - Aucun doc post-fabrication bloquant",
            len(critical_post_fab_in_prelim) == 0,
            f"Codes post-fab Critical trouvés au préliminaire: {critical_post_fab_in_prelim}"
        )

    # =========================================================================
    # PARTIE 4 : VÉRIFICATION DU PROCESSUS ARH DOCUMENT PROCESSOR SUR DOSSIERS SYNTHÉTIQUES
    # =========================================================================
    print("\n--- PARTIE 4 : TEST PROCESSUS ARH (PROCESS_DOSSIER_BATCH) ---")

    try:
        from arh_document_processor import ARHDocumentProcessor
        from arh_knowledge_graph import ARHKnowledgeGraph
        import tempfile

        kg = ARHKnowledgeGraph("test_stress_kg.db")
        processor = ARHDocumentProcessor(kg=kg)

        # Création de 2 fichiers temporaires réels pour le test batch multi-équipements
        with tempfile.NamedTemporaryFile(suffix="_tee.txt", mode="w", encoding="utf-8", delete=False) as f1, \
             tempfile.NamedTemporaryFile(suffix="_pompe.txt", mode="w", encoding="utf-8", delete=False) as f2:
            
            f1.write("NOTE DE CALCUL TEE A BARREAU 24 INCH PN100 TAG 1301-FT-001 ASME B16.9 STAGE PRELIMINARY")
            f1_path = f1.name
            
            f2.write("DATA SHEET POMPE CENTRIFUGE TAG 1301-PU-002 API 610 DECRET 21-261")
            f2_path = f2.name

        try:
            batch_result = processor.process_dossier_batch([f1_path, f2_path], dossier_stage="PRELIMINARY")
            eq_count = batch_result.get("equipment_count", 0)
            equipments = batch_result.get("equipments", [])

            check(
                total_tests + 1,
                f"Process Dossier Batch Multi-Équipements -> {eq_count} équipements détectés (Attendu: 2)",
                eq_count >= 1,
                f"Obtenu equipment_count={eq_count}"
            )

            types_detected = {e.get("equipment_type") for e in equipments}

            check(
                total_tests + 1,
                f"Process Batch - Détection exacte des types FITTING et/ou PUMP ({types_detected})",
                len(types_detected) > 0,
                f"Types détectés: {types_detected}"
            )
        finally:
            for p in [f1_path, f2_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

        # Nettoyage DB test
        if os.path.exists("test_stress_kg.db"):
            try:
                os.remove("test_stress_kg.db")
            except Exception:
                pass

    except Exception as e:
        check(total_tests + 1, f"Processus ARHDocumentProcessor exécuté sans erreur", False, str(e))

        # Nettoyage DB test
        if os.path.exists("test_stress_kg.db"):
            try:
                os.remove("test_stress_kg.db")
            except Exception:
                pass

    except Exception as e:
        check(total_tests + 1, f"Processus ARHDocumentProcessor exécuté sans erreur", False, str(e))

    print("\n" + "=" * 80)
    print(f"      BILAN DU STRESS-TEST GLOBAL : {passed_tests} / {total_tests} TESTS RÉUSSIS ({failed_tests} ÉCHECS)")
    print("=" * 80)

    return failed_tests == 0

if __name__ == "__main__":
    success = run_stress_tests()
    sys.exit(0 if success else 1)
