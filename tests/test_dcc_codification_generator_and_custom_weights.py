import json
import uuid
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import pytest
import sqlite3
from dots.dcc_lifecycles import (
    generate_sequential_codification,
    validate_codification,
    EPC_DISCIPLINES,
    PREDEFINED_LIFECYCLES
)
import routes.workspace_indexer as ws_idx

DB_PATH = Path("d:/DATA BASE IA/arkan_workspace.db")


def test_epc_disciplines_taxonomy():
    assert "PRC" in EPC_DISCIPLINES
    assert "PIP" in EPC_DISCIPLINES
    assert "ELE" in EPC_DISCIPLINES
    assert "INS" in EPC_DISCIPLINES
    assert "CIV" in EPC_DISCIPLINES
    assert "STR" in EPC_DISCIPLINES
    assert "MEC" in EPC_DISCIPLINES
    assert "HSE" in EPC_DISCIPLINES
    assert "TEL" in EPC_DISCIPLINES
    assert "PM" in EPC_DISCIPLINES


def test_generate_sequential_codification_iec():
    raw_docs = [
        {"title": "Piping Isometric Line 10", "discipline": "Tuyauterie", "doc_type": "Isométrique"},
        {"title": "Piping Isometric Line 20", "discipline": "Piping", "doc_type": "ISO"},
        {"title": "Electrical SLD 400V", "discipline": "Electricite", "doc_type": "Single Line Diagram"},
        {"title": "Already Coded", "doc_number": "CPF-U10-PRC-PID-8888-0", "discipline": "Process", "doc_type": "PID"}
    ]
    coded, stats = generate_sequential_codification(
        deliverables=raw_docs,
        project_code="CPF",
        area_code="U10",
        standard="IEC_82045",
        padding_digits=4,
        step_increment=1,
        separator="-",
        initial_rev="0",
        counter_scope="DISCIPLINE_TYPE",
        overwrite_all=False
    )

    assert stats["total"] == 4
    assert stats["coded_now"] == 3
    assert stats["already_coded"] == 1

    # Verify line 1
    assert coded[0]["doc_number"] == "CPF-U10-PIP-ISO-0001-0"
    is_v, _ = validate_codification(coded[0]["doc_number"], "IEC_82045")
    assert is_v is True

    # Verify line 2 (incremented for PIP-ISO)
    assert coded[1]["doc_number"] == "CPF-U10-PIP-ISO-0002-0"
    is_v, _ = validate_codification(coded[1]["doc_number"], "IEC_82045")
    assert is_v is True

    # Verify line 3 (SLD starts at 0001)
    assert coded[2]["doc_number"] == "CPF-U10-ELE-SLD-0001-0"
    is_v, _ = validate_codification(coded[2]["doc_number"], "IEC_82045")
    assert is_v is True

    # Verify line 4 preserved
    assert coded[3]["doc_number"] == "CPF-U10-PRC-PID-8888-0"


def test_generate_sequential_codification_sonatrach():
    raw_docs = [
        {"title": "Datasheet Pompe", "discipline": "MEC", "doc_type": "DSH"},
        {"title": "Datasheet Compresseur", "discipline": "MEC", "doc_type": "DSH"}
    ]
    coded, stats = generate_sequential_codification(
        deliverables=raw_docs,
        project_code="HBK",
        area_code="U20",
        standard="SONATRACH",
        padding_digits=4,
        step_increment=1,
        separator="-",
        initial_rev="0"
    )

    assert coded[0]["doc_number"] == "SH-HBK-U20-MEC-DSH-0001-0"
    assert coded[1]["doc_number"] == "SH-HBK-U20-MEC-DSH-0002-0"
    is_v, _ = validate_codification(coded[0]["doc_number"], "SONATRACH")
    assert is_v is True


def test_generate_sequential_codification_overwrite_all():
    raw_docs = [
        {"title": "Doc 1", "doc_number": "OLD-001", "discipline": "CIV", "doc_type": "PLN"}
    ]
    coded, stats = generate_sequential_codification(
        deliverables=raw_docs,
        project_code="PRJ",
        area_code="U10",
        overwrite_all=True
    )
    assert coded[0]["doc_number"] == "PRJ-U10-CIV-PLN-0001-0"
    assert stats["coded_now"] == 1


@pytest.mark.anyio
async def test_api_auto_generate_codification():
    docs = [
        {"title": "Doc auto", "discipline": "Tuyauterie", "doc_type": "ISO"}
    ]
    res = await ws_idx.api_auto_generate_codification(
        deliverables_json=json.dumps(docs),
        project_code="TESTPRJ",
        area_code="U10",
        standard="IEC_82045",
        padding_digits=4,
        step_increment=1,
        separator="-",
        initial_rev="0",
        counter_scope="DISCIPLINE_TYPE",
        overwrite_all=False
    )
    assert res["status"] == "success"
    assert len(res["deliverables"]) == 1
    assert res["deliverables"][0]["doc_number"] == "TESTPRJ-U10-PIP-ISO-0001-0"
    assert res["preview"][0]["is_valid"] is True


@pytest.mark.anyio
async def test_custom_lifecycles_persistence_and_advance():
    p_code = f"CUST_{uuid.uuid4().hex[:6].upper()}"
    p_name = f"Projet Custom Weights {p_code}"

    # Custom steps for lifecycle ID 1 with custom weights: START 15%, IDC 35%, IFC 50%
    custom_steps = [
        {"code": "START", "label": "Start Custom", "weight_percent": 15.0, "cumulative_percent": 15.0, "actor": "ENGINEER"},
        {"code": "IDC", "label": "IDC Custom", "weight_percent": 35.0, "cumulative_percent": 50.0, "actor": "ENGINEER"},
        {"code": "IFC", "label": "IFC Custom", "weight_percent": 50.0, "cumulative_percent": 100.0, "actor": "DOC_CONTROL"}
    ]
    custom_lc_map = {
        "1": {
            "code": "LC_01_PID_LONG",
            "name": "Cycle Custom 1",
            "steps": custom_steps
        }
    }

    docs = [
        {
            "doc_number": f"{p_code}-U10-PRC-PID-0001-0",
            "title": "P&ID Custom Steps",
            "discipline": "PRC",
            "doc_type": "PID",
            "lifecycle_id": 1,
            "contract_weight": 2.0
        }
    ]

    # Confirm setup with custom_lifecycles_json
    res_setup = await ws_idx.confirm_project_setup(
        project_name=p_name,
        project_code=p_code,
        codification_standard="IEC_82045",
        custom_regex=None,
        client_sla_days=21,
        engineer_sla_days=14,
        deliverables_json=json.dumps(docs),
        custom_lifecycles_json=json.dumps(custom_lc_map)
    )
    assert res_setup["status"] == "success"
    folder_id = res_setup["folder_id"]

    # Check DB folders table contains custom_lifecycles_json
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT custom_lifecycles_json FROM folders WHERE id = ?", (folder_id,))
    f_row = c.fetchone()
    assert f_row is not None
    saved_custom = json.loads(f_row[0])
    assert "1" in saved_custom
    assert saved_custom["1"]["steps"][0]["weight_percent"] == 15.0

    # Check document was inserted with custom start_progress (15.0%)
    c.execute("SELECT id, progress_percent, current_step FROM tdr_documents WHERE folder_id = ?", (folder_id,))
    doc_row = c.fetchone()
    assert doc_row is not None
    doc_id, progress, curr_step = doc_row
    assert curr_step == "START"
    assert progress == 15.0
    conn.close()

    # Advance step: from START to IDC -> cumulative should become 50.0%
    res_adv = await ws_idx.advance_document_step(
        doc_id=doc_id,
        target_step_code="IDC"
    )
    assert res_adv["status"] == "success"
    assert res_adv["new_step"] == "IDC"
    assert res_adv["new_progress_percent"] == 50.0
