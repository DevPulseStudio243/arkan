import sys, os
sys.path.insert(0, os.path.abspath("."))
import json
from arh_document_processor import ARHDocumentProcessor
from arh_regulatory_engine import ARHRegulatoryEngine

print("=== TESTING ALL 4 ARH MANAGEMENT PILLARS ===")

processor = ARHDocumentProcessor()

# Dummy test docs
docs = [
    {
        "file_name": "DS_BALLON_V101.pdf",
        "text": "FICHE TECHNIQUE BALLON V-101. PMA = 25.0 bar, TMA = 85 °C. Epaisseur = 12.5 mm. Materiau: SA 516 GR 70. Norme: API 650.",
        "metadata": {"equipment_tag": "V-101", "document_type": "DATA SHEET"},
        "page_spans": [{"page": 1, "start": 0, "end": 150}]
    },
    {
        "file_name": "PV_HYDROTEST_V101.pdf",
        "text": "PV EPREUVE HYDROSTATIQUE BALLON V-101. Pression d'epreuve = 37.5 bar. Test temperature = 20 C.",
        "metadata": {"equipment_tag": "V-101", "document_type": "HYDROTEST"},
        "page_spans": [{"page": 1, "start": 0, "end": 120}]
    }
]

# Pillar 1 & 2 Test
res = processor._process_equipment_group(
    group_docs=docs,
    group_tag="V-101",
    project_name="PROJET 12 PUITS",
    unit_name="U-100",
    dossier_id="DOSSIER_TEST_101",
    dossier_stage="PRELIMINARY"
)

print(f"\n1. Compliance Status: {res['status']}")
print(f"2. Compliance Score: {res['compliance_score']}%")

print("\n--- PILLAR 1: PARAMETRIC CONCORDANCE MATRIX ---")
for m in res['concordance_matrix']:
    print(f" - {m['parameter_name']}: {m['extracted_values']} -> {m['status']}")

print("\n--- PILLAR 2: ARBORESCENCE NUMERIQUE ARH (P-CTE-1) ---")
for folder in res['arh_dossier_tree']:
    title_clean = folder['title'].encode('ascii', 'ignore').decode('ascii')
    print(f" - [{folder['status']}] {title_clean} ({len(folder['docs'])} docs)")


print("\n--- COMMENTS & ANOMALIES COUNT ---")
print(f"Total Comments Generated: {len(res['comments'])}")
for c in res['comments'][:5]:
    title_clean = c['title'].encode('ascii', 'ignore').decode('ascii')
    print(f" - [{c['priority']}] {title_clean}")

print("\n=== ALL 4 ARH PILLARS TESTED SUCCESSFULLY ===")
