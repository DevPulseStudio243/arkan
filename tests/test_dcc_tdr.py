import pytest
import sqlite3
import re
from datetime import datetime
from pathlib import Path

# Importer le validateur depuis dot_09
import sys
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "dots"))
from dot_09_doccontrol import DOT09, validate_iec82045_codification
import routes.workspace_indexer as ws_idx

def test_validate_iec82045_codification():
    # Codes valides selon IEC 82045 / EPC standard
    valid_codes = [
        "CPF-PIP-ISO-0001-A",
        "PRJ-PRO-PID-1020-0",
        "SH-CPF-PIP-ISO-1002-0",
        "TRN-ELE-SLD-5001-1",
        "CPF-PIP-ISO-0001",
        "PRJ-01-CIV-FND-0010-B"
    ]
    for code in valid_codes:
        assert validate_iec82045_codification(code) is True, f"Devrait être valide : {code}"

    # Codes non conformes
    invalid_codes = [
        "",
        "PLAN1",
        "test-iso",
        "12345",
        "A-B",
        "NOM_DE_FICHIER_QUELCONQUE_SANS_DISCIPLINE_NI_NUMERO"
    ]
    for code in invalid_codes:
        assert validate_iec82045_codification(code) is False, f"Devrait être invalide : {code}"

def test_dot09_business_logic():
    dot = DOT09()
    
    # 1. Cas conforme
    res_valid = dot._business_logic({
        "doc_number": "CPF-PIP-ISO-0001-0",
        "author": "Ingénieur Piping",
        "approver": "Lead DocControl",
        "status": "IFC"
    })
    assert res_valid["success"] is True
    assert res_valid["iec_82045_valid"] is True
    assert res_valid["metadata_complete"] is True

    # 2. Cas cartouche incomplet (manque approbateur)
    res_incomplete = dot._business_logic({
        "doc_number": "CPF-PIP-ISO-0001-0",
        "author": "Ingénieur Piping",
        "approver": "",
        "status": "IFR"
    })
    assert res_incomplete["success"] is False
    assert res_incomplete["metadata_complete"] is False

    # 3. Cas syntaxe invalide
    res_invalid_syntax = dot._business_logic({
        "doc_number": "CROQUIS_CHANTIER",
        "author": "Technicien",
        "approver": "Chef de chantier",
        "status": "IFR"
    })
    assert res_invalid_syntax["success"] is False
    assert res_invalid_syntax["iec_82045_valid"] is False

def test_dot09_batch_audit():
    dot = DOT09()
    docs = [
        {"doc_number": "CPF-PIP-ISO-0001-A"},
        {"doc_number": "CPF-PIP-ISO-0002-0"},
        {"doc_number": "PLAN_NON_CONFORME"}
    ]
    report = dot.batch_audit(docs)
    assert report["total_documents"] == 3
    assert report["compliant_count"] == 2
    assert report["non_compliant_count"] == 1
    assert report["compliance_rate_percent"] == 66.7

def test_transmittal_number_generation():
    # Tester l'endpoint fonctionnel get_next_transmittal_number
    # Utiliser un dossier fictif
    res = ws_idx.get_next_transmittal_number(folder_id=999999, prefix="TR")
    assert res["status"] == "success"
    assert "next_transmittal_no" in res
    assert res["next_transmittal_no"].startswith("TR-")
    assert re.search(r'\d{4}$', res["next_transmittal_no"]) is not None

def test_database_iec_column():
    # Vérifier que la colonne iec_82045_valid existe bien dans tdr_documents
    conn = sqlite3.connect(str(ws_idx.DB_PATH))
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(tdr_documents)")
    columns = [row[1] for row in cursor.fetchall()]
    conn.close()
    assert "iec_82045_valid" in columns, "La colonne iec_82045_valid doit exister dans tdr_documents"

@pytest.mark.anyio
async def test_audit_tdr_compliance_endpoint():
    # Tester l'audit de conformité sur un dossier existant ou vide
    res = await ws_idx.audit_tdr_compliance(folder_id=1)
    assert res["status"] == "success"
    assert "compliance_rate_percent" in res
    assert "compliant_count" in res
    assert "non_compliant_count" in res
