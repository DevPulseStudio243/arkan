import sys, os
sys.path.insert(0, os.path.abspath("."))
import json
from arh_regulatory_engine import ARHRegulatoryEngine
from arh_document_processor import ARHDocumentProcessor

print("=== TESTING ARH NORM SCOPE & HISTORICAL RETEX RESERVES MATCHING ===")

# Test 1: Inapplicable Norm Scope Detection
test_text = """
DOSSIER TECHNIQUE PRELIMINAIRE - BALLON SEPARATEUR V-101
Pression de calcul: 25 bar. Température de calcul: 85°C.
L'équipement est conçu selon la norme API 650 pour le calcul du réservoir et ASME B31.3 pour la virole.
"""

engine = ARHRegulatoryEngine()
norm_anomalies = engine.verify_norm_applicability("PRESSURE_VESSEL", test_text)

print(f"\n1. Norm Scope Anomalies Detected: {len(norm_anomalies)}")
for a in norm_anomalies:
    title_clean = a['title'].encode('ascii', 'ignore').decode('ascii')
    comment_clean = a['comment'].encode('ascii', 'ignore').decode('ascii')
    print(f" - [{a['priority']}] {title_clean}")
    print(f"   {comment_clean}\n")

# Test 2: Historical ARH Reserves Match
reserves_matches = engine.match_historical_arh_reserves("PRESSURE_VESSEL", test_text)
print(f"\n2. Historical ARH Reserves Matched: {len(reserves_matches)}")
for r in reserves_matches:
    title_clean = r['title'].encode('ascii', 'ignore').decode('ascii')
    comment_clean = r['comment'].encode('ascii', 'ignore').decode('ascii')
    print(f" - [{r['priority']}] {title_clean}")
    print(f"   {comment_clean[:150]}...\n")


print("=== TEST COMPLETED SUCCESSFULLY ===")
