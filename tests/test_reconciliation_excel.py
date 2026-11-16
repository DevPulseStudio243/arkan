# -*- coding: utf-8 -*-
"""
tests/test_reconciliation_excel.py
Vérifie la génération de la feuille RECONCILIATION_CROSS dans le classeur Excel maître.
"""
import openpyxl
import pytest
from mto_consolidator import generate_master_multidiscipline_excel


def test_reconciliation_cross_sheet_created(tmp_path):
    items = [
        {"category": "CABLE_TRAY", "tag": "CDC-100", "description": "Chemin de câbles 100x50", "quantity": 50, "unit": "m", "confidence_score": 0.95}
    ]
    cross_anomalies = [
        {
            "rule": "CROSS_01",
            "check_id": "CROSS_01",
            "severity": "CRITICAL",
            "status": "DETECTED",
            "tag": "300-P-101A",
            "title": "Moteur P&ID sans départ au SLD",
            "message": "Pompe 300-P-101A présente au P&ID mais absente du schéma unifilaire.",
            "norm_source": "CEI 60364 / ISA-5.1",
            "recommendation": "Vérifier si le départ est alimenté par un MCC déporté ou ajouter un départ réserve."
        },
        {
            "rule": "CROSS_02",
            "check_id": "CROSS_02",
            "severity": "INFO",
            "status": "NOT_EVALUATED",
            "tag": "-",
            "title": "Contrôle CROSS_02 non évalué",
            "message": "Données P&ID manquantes pour le contrôle inverse.",
            "norm_source": "CEI 60364",
            "recommendation": "Fournir la liste d'équipements P&ID."
        }
    ]

    out_xlsx = str(tmp_path / "test_mto_cross.xlsx")
    generate_master_multidiscipline_excel(items, metadata={"cross_anomalies": cross_anomalies}, anomalies=cross_anomalies, output_path=out_xlsx)

    wb = openpyxl.load_workbook(out_xlsx)
    assert "RECONCILIATION_CROSS" in wb.sheetnames

    ws = wb["RECONCILIATION_CROSS"]
    assert ws["A1"].value == "N°"
    assert ws["B1"].value == "CODE RÈGLE"
    assert ws["C1"].value == "SÉVÉRITÉ"

    # Row 2: CROSS_01
    assert ws["B2"].value == "CROSS_01"
    assert ws["C2"].value == "CRITICAL"
    assert ws["D2"].value == "DETECTED"
    assert ws["E2"].value == "300-P-101A"

    # Row 3: CROSS_02
    assert ws["B3"].value == "CROSS_02"
    assert ws["D3"].value == "NOT_EVALUATED"
