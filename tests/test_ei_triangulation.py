"""
tests/test_ei_triangulation.py
==============================
Banc de test unitaire et d'intégration pour la Triangulation Totale E&I
(Plan CAD vs Carnet de Câbles vs Note de Calcul Caneco/ETAP vs MTO ARKAN).
"""

import csv
import json
import pytest
from pathlib import Path
import openpyxl
from fastapi.testclient import TestClient

from api_enhanced import app
from calculation_note_parser import CalculationNoteParser
from cable_schedule_parser import CableScheduleParser
from ei_triangulation_engine import EITriangulationEngine, _get_next_standard_section


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def tmp_excel_calc_note(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Calculs_BT"
    ws.append(["Repère Circuit", "Amont", "Aval", "Section Retenue", "Longueur (m)", "Chute de Tension (%)", "Ib (A)", "In (A)", "Type Câble"])
    ws.append(["300-P-101A", "TGBT-300", "Pompe P-101A", "4G16", 45.0, 1.8, 48.0, 63.0, "U-1000 R2V"])
    ws.append(["300-P-101B", "TGBT-300", "Pompe P-101B", "4G16", 45.0, 1.8, 48.0, 63.0, "U-1000 R2V"])
    ws.append(["300-TRP-001", "TGBT-300", "Transfo TRP-001", "3x120+70", 30.0, 0.9, 180.0, 250.0, "XLPE/PVC"])
    ws.append(["300-FAN-005", "TGBT-300", "Ventilateur", "4G4", 25.0, 2.2, 12.0, 20.0, "U-1000 R2V"])
    file_path = tmp_path / "note_caneco_bt.xlsx"
    wb.save(file_path)
    return file_path


@pytest.fixture
def tmp_csv_calc_note(tmp_path):
    file_path = tmp_path / "note_etap.csv"
    with open(file_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Circuit", "From", "To", "Section", "Length_m", "Delta_U_%", "Ib", "In", "Cable_Type"])
        writer.writerow(["300-P-101A", "TGBT", "P-101A", "4G16", "45", "1.8", "48", "63", "U-1000 R2V"])
        writer.writerow(["300-M-201", "MCC-1", "Moteur", "3x70+35", "80", "3.2", "110", "160", "XLPE"])
    return file_path


@pytest.fixture
def tmp_excel_cable_schedule(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cable_Schedule"
    ws.append(["Tag Câble", "Description", "Tenant", "Aboutissant", "Section Déclarée", "Longueur Prévue (m)", "Spécification"])
    # 300-P-101A présent mais longueur sous-estimée (35m vs 85m réel)
    ws.append(["300-P-101A", "Alim Pompe A", "TGBT-300", "300-P-101A", "4G16", 35.0, "U-1000 R2V"])
    # 300-P-101B omis dans le carnet !
    # 300-TRP-001 présent avec divergence de section
    ws.append(["300-TRP-001", "Alim Transfo", "TGBT-300", "TRP-001", "3x95+50", 30.0, "XLPE/PVC"])
    # 300-ORPHAN présent uniquement dans le carnet
    ws.append(["300-ORPHAN-01", "Câble Orphelin", "TGBT-300", "Inconnu", "3G2.5", 15.0, "PVC"])
    file_path = tmp_path / "carnet_de_cables.xlsx"
    wb.save(file_path)
    return file_path


def test_calculation_note_parser_excel(tmp_excel_calc_note):
    items = CalculationNoteParser.parse_file(tmp_excel_calc_note)
    assert len(items) == 4
    tag_map = {it["tag"]: it for it in items}
    assert "P-101A" in tag_map
    p101 = tag_map["P-101A"]
    assert p101["raw_tag"] == "300-P-101A"
    assert p101["calc_section"] == "4G16"
    assert p101["calc_length_m"] == 45.0
    assert p101["calc_du_pct"] == 1.8
    assert p101["ib_a"] == 48.0


def test_calculation_note_parser_csv(tmp_csv_calc_note):
    items = CalculationNoteParser.parse_file(tmp_csv_calc_note)
    assert len(items) == 2
    tag_map = {it["tag"]: it for it in items}
    assert "M-201" in tag_map
    m201 = tag_map["M-201"]
    assert m201["raw_tag"] == "300-M-201"
    assert m201["calc_section"] == "3x70+35"
    assert m201["calc_length_m"] == 80.0


def test_cable_schedule_parser(tmp_excel_cable_schedule):
    items = CableScheduleParser.parse_file(tmp_excel_cable_schedule)
    assert len(items) == 3
    tags = [it["tag"] for it in items]
    assert "P-101A" in tags
    assert "TRP-001" in tags
    assert "ORPHAN-01" in tags


def test_triangulation_axis_1_omission():
    """Axe 1: Détection d'un câble présent sur CAD et Note mais omis du Carnet."""
    cad_feeders = [
        {"tag": "300-P-101B", "length_m": 50.0, "cable_section": "4G16", "status": "ROUTED"}
    ]
    cs_items = []  # Oublié dans le carnet !
    cn_items = [
        {"tag": "300-P-101B", "calc_section": "4G16", "calc_length_m": 45.0, "calc_du_pct": 1.8}
    ]

    engine = EITriangulationEngine()
    res = engine.triangulate(cad_feeders, cs_items, cn_items)

    assert res["summary"]["discrepancies_count"] == 1
    assert res["summary"]["critical_count"] == 1
    card = res["discrepancy_cards"][0]
    assert card["category"] == "OMISSION"
    assert card["severity"] == "CRITICAL"
    assert "omis dans le Carnet" in card["title"]
    assert card["item_proposed"]["quantity"] == 50.0
    assert card["item_proposed"]["source"] == "TRIANGULATION_VALIDEE"


def test_triangulation_axis_2_length_mismatch():
    """Axe 2: Détection d'une sous-estimation de longueur de plus de 10% dans le Carnet."""
    cad_feeders = [
        {"tag": "300-P-101A", "length_m": 85.0, "cable_section": "4G16", "status": "ROUTED"}
    ]
    cs_items = [
        {"tag": "300-P-101A", "declared_length_m": 35.0, "declared_section": "4G16"}
    ]
    cn_items = [
        {"tag": "300-P-101A", "calc_section": "4G16", "calc_length_m": 40.0, "calc_du_pct": 1.5}
    ]

    engine = EITriangulationEngine()
    res = engine.triangulate(cad_feeders, cs_items, cn_items)

    cards = [c for c in res["discrepancy_cards"] if c["tag"] in ("P-101A", "300-P-101A")]
    assert len(cards) >= 1
    c = cards[0]
    assert c["category"] in ("LENGTH_MISMATCH", "VOLTAGE_DROP_EXCEEDED")
    # L_cad = 85.0 vs L_cs = 35.0 -> Écart > 100%
    assert c["severity"] == "CRITICAL"


def test_triangulation_axis_3_voltage_drop_recalculation():
    """Axe 3: Chute de tension dépassée sur tracé réel CAD imposant un surdimensionnement."""
    # L_cn = 30m avec DU = 2.5% sur 4G16.
    # L_cad = 90m -> DU_reel = 2.5 * (90/30) = 7.5% > 5.0% !
    cad_feeders = [
        {"tag": "300-P-202", "length_m": 90.0, "cable_section": "4G16", "status": "ROUTED"}
    ]
    cs_items = [
        {"tag": "300-P-202", "declared_length_m": 85.0, "declared_section": "4G16"}
    ]
    cn_items = [
        {"tag": "300-P-202", "calc_section": "4G16", "calc_length_m": 30.0, "calc_du_pct": 2.5}
    ]

    engine = EITriangulationEngine()
    res = engine.triangulate(cad_feeders, cs_items, cn_items)

    cards = [c for c in res["discrepancy_cards"] if c["category"] == "VOLTAGE_DROP_EXCEEDED"]
    assert len(cards) == 1
    card = cards[0]
    assert card["severity"] == "CRITICAL"
    assert "Chute de tension inadmissible" in card["title"]
    # La section proposée doit être surdimensionnée (16 -> 25)
    assert "25" in card["proposed_resolution"]["section"]
    assert card["item_proposed"]["cable_section"] == card["proposed_resolution"]["section"]


def test_triangulation_axis_4_section_and_spec_mismatch():
    """Axe 4: Divergence de section ou de spécification isolant/armure."""
    cad_feeders = [
        {"tag": "300-TRP-001", "length_m": 30.0, "cable_section": "3x120+70", "status": "ROUTED"}
    ]
    cs_items = [
        {"tag": "300-TRP-001", "declared_length_m": 30.0, "declared_section": "3x95+50", "cable_type": "PVC"}
    ]
    cn_items = [
        {"tag": "300-TRP-001", "calc_length_m": 30.0, "calc_section": "3x120+70", "calc_du_pct": 0.9, "cable_type": "XLPE"}
    ]

    engine = EITriangulationEngine()
    res = engine.triangulate(cad_feeders, cs_items, cn_items)

    cards = res["discrepancy_cards"]
    assert any(c["category"] == "SPEC_MISMATCH" for c in cards)


def test_api_triangulation_and_action_flow(client, tmp_excel_calc_note, tmp_excel_cable_schedule):
    """Test du flux API complet : /ie-mto/triangulate puis /ie-mto/triangulation/action."""
    # 1. Appel /ie-mto/triangulate avec fichiers
    with open(tmp_excel_calc_note, "rb") as f_cn, open(tmp_excel_cable_schedule, "rb") as f_cs:
        resp = client.post(
            "/ie-mto/triangulate",
            files={
                "calc_note_file": ("calc_note.xlsx", f_cn, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "cable_schedule_file": ("schedule.xlsx", f_cs, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            }
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    cards = data["discrepancy_cards"]
    assert len(cards) > 0

    target_card = cards[0]
    disc_id = target_card["discrepancy_id"]

    # 2. Action Expert : Valider & Injecter
    resp_action = client.post(
        "/ie-mto/triangulation/action",
        json={
            "discrepancy_id": disc_id,
            "action": "validate_inject",
            "expert_note": "Validé conforme au dimensionnement Caneco",
            "item_proposed": target_card["item_proposed"]
        }
    )
    assert resp_action.status_code == 200
    act_data = resp_action.json()
    assert act_data["status"] == "success"
    assert act_data["action"] == "validate_inject"
    assert act_data["injected_item"]["source"] == "TRIANGULATION_VALIDEE"

    # 3. Action Expert : Ignorer
    resp_ignore = client.post(
        "/ie-mto/triangulation/action",
        json={
            "discrepancy_id": disc_id,
            "action": "ignore"
        }
    )
    assert resp_ignore.status_code == 200
    assert resp_ignore.json()["action"] == "ignore"

    # 4. Action Expert : Ajouter Note
    resp_note = client.post(
        "/ie-mto/triangulation/action",
        json={
            "discrepancy_id": disc_id,
            "action": "add_note",
            "expert_note": "Attente retour fournisseur sur la tolérance"
        }
    )
    assert resp_note.status_code == 200
    assert resp_note.json()["action"] == "add_note"
