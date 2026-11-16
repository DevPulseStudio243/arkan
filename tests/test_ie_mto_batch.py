# -*- coding: utf-8 -*-
"""
tests/test_ie_mto_batch.py
Test unitaire et d'intégration pour le endpoint batch /ie-mto/calculate-batch.
Vérifie l'ingestion multi-fichiers, la correction d'échelle DXF, l'extraction du carnet de câbles et la triangulation.
"""
import os
import sys
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.ie_mto_router import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

DESKTOP_FOLDER = Path(r"C:\Users\MSI\Desktop\1")


def test_batch_calculate_with_desktop_folder():
    if not DESKTOP_FOLDER.exists():
        pytest.skip("Dossier C:\\Users\\MSI\\Desktop\\1 non présent sur cet environnement")

    response = client.post(
        "/ie-mto/calculate-batch",
        data={"folder_path": str(DESKTOP_FOLDER)}
    )

    assert response.status_code == 200, f"Erreur: {response.text}"
    data = response.json()
    assert data["status"] == "success"

    # Vérification du manifeste des fichiers
    manifest = data.get("batch_manifest", [])
    roles = {m["role"]: m for m in manifest}
    assert "CAD_ROUTING_PLAN" in roles or "CABLE_SCHEDULE" in roles

    # Vérification métrique quantitative DXF (196.6m et non 196km)
    kpis = data.get("kpis", {})
    tray_total = kpis.get("tray_total_m", 0.0)
    assert 150.0 < tray_total < 250.0, f"Métrage chemins anormal : {tray_total} m (attendu ~196.6 m)"

    # Vérification des câbles extraits (17 câbles du carnet)
    cable_total = kpis.get("cable_total_m", 0.0)
    assert cable_total > 500.0, f"Métrage câbles anormal : {cable_total} m (attendu ~750 m)"

    # Vérification des items et du fichier Excel généré
    items = data.get("items", [])
    assert len(items) >= 20, f"Nombre d'articles insuffisant : {len(items)}"
    assert data.get("excel_url") is not None

    # Vérification de la Triangulation
    triang = data.get("triangulation")
    assert triang is not None
    assert "summary" in triang
    assert "discrepancy_cards" in triang
    assert triang["summary"]["total_tags_triangulated"] >= 15
