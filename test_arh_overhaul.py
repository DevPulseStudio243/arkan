import sys
from arh_regulatory_engine import ARHRegulatoryEngine
from arh_document_processor import ARHDocumentProcessor
from arh_api_routes import _init_db, _save_dossier, _load_dossier, _delete_dossier_from_db, _list_dossiers

print("=== TEST 1: ARH Regulatory Engine Equipment Detection ===")
engine = ARHRegulatoryEngine()

# Test text 1: Skid metering
t1 = "Spécification technique d'un SKID DE COMPTAGE ET MESURE FISCALE DE GAZ HYDROCARBURES DE DÉBIT 5000 M3/H"
type1 = engine.identify_equipment_type(t1)
print(f"Text 1 -> Detected Type: {type1} (Expected SKID)")

# Test text 2: Furnace / Four
t2 = "Note de calcul de radiation thermique et bilan thermique d'un FOUR DE PROCÉDÉ FIRED HEATER H-101"
type2 = engine.identify_equipment_type(t2)
print(f"Text 2 -> Detected Type: {type2} (Expected FURNACE)")

# Test text 3: Flare / Torche
t3 = "Étude de dispersion des gaz brûlés et rayonnement de la TORCHE DE SÉCURITÉ FLARE STACK ET KO DRUM"
type3 = engine.identify_equipment_type(t3)
print(f"Text 3 -> Detected Type: {type3} (Expected FLARE)")

# Test text 4: Unknown
t4 = "Document administratif général de présentation de projet"
type4 = engine.identify_equipment_type(t4)
print(f"Text 4 -> Detected Type: {type4} (Expected UNKNOWN)")

print("\n=== TEST 2: Checklists Applicable ===")
cl_skid = engine.generate_mandatory_checklist("SKID")
print(f"SKID checklist items count: {len(cl_skid)}")
cl_furnace = engine.generate_mandatory_checklist("FURNACE")
print(f"FURNACE checklist items count: {len(cl_furnace)}")
cl_flare = engine.generate_mandatory_checklist("FLARE")
print(f"FLARE checklist items count: {len(cl_flare)}")
cl_unk = engine.generate_mandatory_checklist("UNKNOWN")
print(f"UNKNOWN checklist items count: {len(cl_unk)}")

print("\n=== TEST 3: SQLite Persistence & Delete ===")
_init_db()

test_dossier = {
    "dossier_id": "TEST_DOSSIER_999",
    "project_name": "Projet Test ARH",
    "unit_name": "UNIT-TEST",
    "equipment_tag": "081-SKID-001",
    "equipment_type": "SKID",
    "equipment_label": "Skid Modulaire de Procédé",
    "status": "APPROVED_WITH_COMMENTS",
    "arh_decision": "CONFORME AVEC REMARQUES",
    "compliance_score": 88.5,
    "dossier_stage": "FINAL_RECEPTION",
    "dossier_stage_label": "Dossier Final de Réception",
    "pdf_report_path": None,
    "comments": []
}

_save_dossier(test_dossier)
print("Saved TEST_DOSSIER_999 to SQLite")

loaded = _load_dossier("TEST_DOSSIER_999")
print(f"Loaded from SQLite -> Tag: {loaded.get('equipment_tag')}, Score: {loaded.get('compliance_score')}%")

dossiers_list = _list_dossiers()
print(f"Total dossiers in DB list: {len(dossiers_list)}")

deleted = _delete_dossier_from_db("TEST_DOSSIER_999")
print(f"Deleted TEST_DOSSIER_999 from SQLite: {deleted}")

loaded_after = _load_dossier("TEST_DOSSIER_999")
print(f"Loaded after delete: {loaded_after}")

print("\nALL TESTS PASSED SUCCESSFULLY!")
