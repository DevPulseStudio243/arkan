"""
tests/test_pid_api_integration.py
==================================
Tests d'intégration de l'API FastAPI (api_enhanced.py) pour les modules P&ID :
  - Génération schématique orthogonale ISA-5.1
  - Jumeau numérique sémantique (pid_topology.json)
  - Endpoints /api/pid/process-dxf et /api/pid/topology-json/{session_id}
"""

import json
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api_enhanced import app

SAMPLE_DXF = PROJECT_ROOT / "samples" / "synthetic_pid.dxf"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_process_dxf_via_multipart_upload(client):
    """Vérifie l'endpoint /api/pid/process-dxf avec un envoi multipart de fichier DXF."""
    assert SAMPLE_DXF.exists(), f"Sample DXF manquant : {SAMPLE_DXF}"

    with open(SAMPLE_DXF, "rb") as f:
        response = client.post(
            "/api/pid/process-dxf",
            files={"file": ("synthetic_pid.dxf", f, "application/dxf")},
        )

    assert response.status_code == 200, f"Erreur {response.status_code}: {response.text}"
    data = response.json()
    assert data["status"] == "success"
    assert "schematic_svg_url" in data and data["schematic_svg_url"]
    assert "topology_json_url" in data and data["topology_json_url"]
    assert data["schematic_svg_url"].endswith("pid_schematic_plan.svg")
    assert data["topology_json_url"].endswith("pid_topology.json")
    assert "topology" in data
    assert "topology_summary" in data["topology"] or "summary" in data


def test_process_dxf_via_json_payload(client):
    """Vérifie l'endpoint /api/pid/process-dxf avec un payload JSON contenant le chemin du DXF."""
    response = client.post(
        "/api/pid/process-dxf",
        json={"dxf_path": str(SAMPLE_DXF)},
    )
    assert response.status_code == 200, f"Erreur {response.status_code}: {response.text}"
    data = response.json()
    assert data["status"] == "success"
    assert "schematic_svg_url" in data
    assert "topology_json_url" in data


def test_get_topology_json_success(client):
    """Vérifie le téléchargement en 1 clic du JSON topologique sémantique."""
    stem = SAMPLE_DXF.stem
    response = client.get(f"/api/pid/topology-json/{stem}")
    assert response.status_code == 200, f"Erreur {response.status_code}: {response.text}"
    assert response.headers["content-type"].startswith("application/json")
    data = response.json()
    assert "equipments" in data or "piping_circuits" in data or "metadata" in data


def test_get_topology_json_alias_route(client):
    """Vérifie que l'alias /pid/topology-json/{session_id} fonctionne également."""
    stem = SAMPLE_DXF.stem
    response = client.get(f"/pid/topology-json/{stem}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_get_topology_json_not_found_returns_404(client):
    """Vérifie qu'un session_id inconnu renvoie une erreur 404 propre."""
    response = client.get("/api/pid/topology-json/non_existent_file_xyz_999")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
