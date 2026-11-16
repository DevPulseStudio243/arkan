import pytest
import re
import json
from pathlib import Path
import sys
import openpyxl
from io import BytesIO
from fastapi import UploadFile

# Ajouter le root workspace D:\DATA BASE IA à sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from dots.dcc_lifecycles import (
    PREDEFINED_LIFECYCLES,
    validate_codification,
    resolve_lifecycle_for_doc_type,
    get_step_info,
    calculate_weighted_project_progress
)
from routes.ocr_service import extract_document_text
import routes.workspace_indexer as ws_idx

def test_10_predefined_lifecycles_integrity():
    """Vérifie que les 10 cycles existent, totalisent 100% et ont des étapes valides."""
    assert len(PREDEFINED_LIFECYCLES) == 10, "Il doit y avoir exactement 10 cycles prédéfinis."
    
    for lc in PREDEFINED_LIFECYCLES:
        steps = lc["steps"]
        assert len(steps) >= 3, f"Le cycle {lc['code']} doit comporter au moins 3 étapes."
        
        sum_weights = sum(s["weight_percent"] for s in steps)
        assert abs(sum_weights - 100.0) < 0.01, f"La somme des poids du cycle {lc['code']} doit être égale à 100% (actuel: {sum_weights})"
        assert abs(steps[-1]["cumulative_percent"] - 100.0) < 0.01
        
        for s in steps:
            assert s["actor"] in ["ENGINEER", "DOC_CONTROL", "CLIENT"], f"Acteur invalide dans {lc['code']}: {s['actor']}"

def test_codification_validation_multi_standards():
    """Teste la validation selon IEC 82045, Sonatrach et Custom Regex."""
    # 1. IEC 82045
    ok_iec, _ = validate_codification("CPF-PIP-ISO-0001-A", "IEC_82045")
    assert ok_iec is True
    ko_iec, _ = validate_codification("DOCUMENT_SANS_DISCIPLINE", "IEC_82045")
    assert ko_iec is False

    # 2. Sonatrach Oil & Gas
    ok_sh, _ = validate_codification("SH-HBK-U10-PIP-ISO-0001-0", "SONATRACH")
    assert ok_sh is True
    ko_sh, _ = validate_codification("PRJ-PIP-001", "SONATRACH")
    assert ko_sh is False

    # 3. Custom Regex
    custom_rx = r'^TOTAL-[A-Z]{3}-\d{4}$'
    ok_cust, _ = validate_codification("TOTAL-EXP-1234", "CUSTOM", custom_rx)
    assert ok_cust is True
    ko_cust, _ = validate_codification("SH-EXP-1234", "CUSTOM", custom_rx)
    assert ko_cust is False

def test_resolve_lifecycle_for_doc_types():
    """Teste l'auto-mapping intelligent type de document -> cycle de vie."""
    lc_pid = resolve_lifecycle_for_doc_type("P&ID")
    assert lc_pid["code"] == "LC_01_PID_LONG"

    lc_mto = resolve_lifecycle_for_doc_type("MTO")
    assert lc_mto["code"] == "LC_02_QUANT_SHORT"

    lc_iso = resolve_lifecycle_for_doc_type("PLAN_ISO")
    assert lc_iso["code"] == "LC_06_ISO_PLANS"

    lc_calc = resolve_lifecycle_for_doc_type("NOTE_DE_CALCUL")
    assert lc_calc["code"] == "LC_07_CALC_NOTE"

    lc_plot = resolve_lifecycle_for_doc_type("PLOT_PLAN")
    assert lc_plot["code"] == "LC_10_PLOT_PLAN"

def test_step_progression_helper():
    """Teste la récupération des métadonnées d'étape et de l'étape suivante."""
    lc = PREDEFINED_LIFECYCLES[0] # LC_01_PID_LONG
    step_start = get_step_info(lc, "START")
    assert step_start is not None
    assert step_start["step_index"] == 0
    assert step_start["next_step_code"] == "IDC"
    assert step_start["is_last_step"] is False

    step_last = get_step_info(lc, "AS_BUILT")
    assert step_last is not None
    assert step_last["is_last_step"] is True
    assert step_last["next_step_code"] is None

def test_weighted_project_progress_math():
    """Teste le calcul d'avancement S-Curve pondéré par poids contractuel."""
    docs = [
        {"contract_weight": 5.0, "progress_percent": 60.0},
        {"contract_weight": 3.0, "progress_percent": 100.0},
        {"contract_weight": 2.0, "progress_percent": 10.0}
    ]
    prog = calculate_weighted_project_progress(docs)
    assert prog == 62.0

def test_ocr_service_on_synthetic_pdf(tmp_path):
    """Teste l'extraction de texte vectoriel PyMuPDF sur un PDF généré dynamiquement."""
    import fitz
    test_pdf = tmp_path / "test_drawing.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "PROJET: CPF TOUAT GAZ - SONATRACH\nNUMERO: SH-TOU-PIP-ISO-001\nREVISION: A\nSTATUT: IFR")
    doc.save(str(test_pdf))
    doc.close()

    res = extract_document_text(str(test_pdf))
    assert res["success"] is True
    assert res["method"] == "PYMUPDF_VECTORIAL"
    assert "SH-TOU-PIP-ISO-001" in res["text"]
    assert res["cartouche_metadata"].get("detected_client") == "SONATRACH"
    assert res["cartouche_metadata"].get("detected_revision") == "A"
    assert res["cartouche_metadata"].get("detected_status") == "IFR"

@pytest.mark.anyio
async def test_api_get_lifecycle_templates():
    """Vérifie l'endpoint GET /tdr/lifecycles/templates."""
    res = await ws_idx.get_lifecycle_templates()
    assert res["status"] == "success"
    templates = res["templates"]
    assert len(templates) >= 10
    assert templates[0]["code"] == "LC_01_PID_LONG"
    assert len(templates[0]["steps"]) >= 3

@pytest.mark.anyio
async def test_api_upload_mdr_file_and_confirm_setup(tmp_path):
    """Teste le flux complet : upload MDR Excel -> configuration projet -> avancée étape -> dashboard KPIs."""
    # 1. Génération d'un fichier Excel MDR synthétique avec 10 colonnes
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MDR_Livrables"
    headers = [
        "N° Document", "Titre du Document", "Discipline", "Type",
        "Révision Initiale", "Date Prévue", "Priorité", "Format",
        "Responsable", "Poids Contractuel"
    ]
    ws.append(headers)

    test_rows = [
        ["SH-TOU-U10-PRO-PID-0001-0", "Schéma P&ID Unité 10 Séparation", "PROCESS", "P&ID", "0", "2026-12-01", "HIGH", "PDF", "Lead Process", 5.0],
        ["SH-TOU-U10-PIP-ISO-1001-A", "Isométrique Tuyauterie Ligne 4-P-101", "PIPING", "PLAN_ISO", "A", "2026-11-20", "MEDIUM", "PDF", "Ingénieur Piping", 2.0],
        ["SH-TOU-U10-ELE-SLD-2001-0", "Schéma Unifilaire Tableau BT", "ELECTRICAL", "SLD", "0", "2026-12-15", "MEDIUM", "DWG", "Lead Elec", 3.0]
    ]
    for r in test_rows:
        ws.append(r)

    mdr_file = tmp_path / "MDR_Projet_Touat.xlsx"
    wb.save(mdr_file)
    wb.close()

    # 2. Test upload MDR
    with open(mdr_file, "rb") as f:
        file_bytes = f.read()
    
    upload_file_obj = UploadFile(filename="MDR_Projet_Touat.xlsx", file=BytesIO(file_bytes))
    parsed_res = await ws_idx.upload_mdr_file(file=upload_file_obj)

    assert parsed_res["status"] == "success"
    assert parsed_res["total_documents_detected"] == 3
    deliverables = parsed_res["deliverables"]
    assert len(deliverables) == 3
    assert deliverables[0]["suggested_lifecycle_code"] == "LC_01_PID_LONG"
    assert deliverables[1]["suggested_lifecycle_code"] == "LC_06_ISO_PLANS"
    assert deliverables[2]["suggested_lifecycle_code"] == "LC_04_DRAWING_SLD"

    # 3. Test confirm project setup (avec code unique pour idempotence)
    import uuid
    unique_suffix = f"{uuid.uuid4().hex[:8]}"
    setup_res = await ws_idx.confirm_project_setup(
        project_name=f"PROJET_TEST_MDR_TOUAT_{unique_suffix}",
        project_code=f"PRJ-TOUAT-{unique_suffix}",
        codification_standard="SONATRACH",
        custom_regex=None,
        client_sla_days=21,
        engineer_sla_days=14,
        deliverables_json=json.dumps(deliverables)
    )

    assert setup_res["status"] == "success"
    folder_id = setup_res["folder_id"]
    assert folder_id > 0
    assert setup_res["total_documents"] == 3

    # 4. Test advance step sur le premier document (P&ID: START -> IDC)
    # Récupérer l'id du doc P&ID
    import sqlite3
    conn = sqlite3.connect(str(ws_idx.DB_PATH))
    c = conn.cursor()
    c.execute("SELECT id, current_step, progress_percent FROM tdr_documents WHERE folder_id = ? AND doc_number = ?",
              (folder_id, "SH-TOU-U10-PRO-PID-0001-0"))
    p_id, p_step, p_prog = c.fetchone()
    assert p_step == "START"
    assert p_prog == 10.0
    conn.close()

    advance_res = await ws_idx.advance_document_step(
        doc_id=p_id,
        target_step_code="IDC",
        transmittal_no=None,
        remarks="Validation étape START achevée"
    )

    assert advance_res["status"] == "success"
    assert advance_res["new_step"] == "IDC"
    assert advance_res["new_progress_percent"] == 30.0

    # 5. Test dashboard analytics
    analytics_res = await ws_idx.get_tdr_dashboard_analytics(folder_id=folder_id)
    assert analytics_res["status"] == "success"
    assert analytics_res["total_documents"] == 3
    # P&ID (poids 5, prog 30%) = 150 ; ISO (poids 2, prog 10%) = 20 ; SLD (poids 3, prog 10%) = 30 -> Total = 200 / 10 = 20.0%
    assert analytics_res["global_progress_percent"] == 20.0
    assert "s_curve_points" in analytics_res
    assert len(analytics_res["s_curve_points"]) == 6
    assert "top_delayed_documents" in analytics_res
    assert "discipline_distribution" in analytics_res
    assert "PROCESS" in analytics_res["discipline_distribution"]

@pytest.mark.anyio
async def test_confirm_project_setup_empty_deliverables():
    """Vérifie la création d'un projet configuré avec 0 livrable initial (mode 'Démarrer sans fichier Excel')."""
    import uuid
    import sqlite3
    unique_suffix = uuid.uuid4().hex[:8]
    setup_res = await ws_idx.confirm_project_setup(
        project_name=f"PROJET_VIERGE_{unique_suffix}",
        project_code=f"PRJ-EMPTY-{unique_suffix}",
        codification_standard="SONATRACH",
        custom_regex=None,
        client_sla_days=25,
        engineer_sla_days=10,
        deliverables_json="[]"
    )

    assert setup_res["status"] == "success"
    folder_id = setup_res["folder_id"]
    assert folder_id > 0
    assert setup_res["total_documents"] == 0

    # Vérification en base de données que les SLAs et le standard sont bien enregistrés
    conn = sqlite3.connect(str(ws_idx.DB_PATH))
    c = conn.cursor()
    c.execute("SELECT codification_standard, client_sla_days, engineer_sla_days FROM folders WHERE id = ?", (folder_id,))
    row = c.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "SONATRACH"
    assert row[1] == 25
    assert row[2] == 10
