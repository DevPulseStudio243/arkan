# -*- coding: utf-8 -*-
"""
tests/test_router_cable_routing.py
Test de l'endpoint /ie-mto/route-cables sur le routeur FastAPI.
"""
import pytest
import ezdxf
from fastapi.testclient import TestClient
from fastapi import FastAPI
from routes.ie_mto_router import router
import config_loader as cl

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_route_cables_endpoint_success(tmp_path, monkeypatch):
    # Configurer allowed_roots pour pointer vers tmp_path
    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text(f"""
project_metadata: {{project_name: "Test"}}
paths:
  allowed_roots: ["{str(tmp_path).replace(chr(92), '/')}"]
""", encoding="utf-8")
    monkeypatch.setenv(cl.ENV_PATH, str(cfg_file))
    cl._CACHE.clear()

    # Créer un plan DXF avec un réseau et deux équipements
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6  # mètres
    msp = doc.modelspace()
    msp.add_line((0, 0), (50, 0), dxfattribs={"layer": "CABLETRAY"})
    msp.add_line((50, 0), (50, 30), dxfattribs={"layer": "CABLETRAY"})

    msp.add_text("TGBT-01", dxfattribs={"layer": "EQUIPMENT", "insert": (0, 2)})
    msp.add_text("300-P-101A", dxfattribs={"layer": "EQUIPMENT", "insert": (50, 32)})

    dxf_path = tmp_path / "routing_plan.dxf"
    doc.saveas(str(dxf_path))

    payload = {
        "file_path": str(dxf_path),
        "origin_tag": "TGBT-01",
        "feeders": [
            {"tag": "300-P-101A", "calibre_a": 63, "cable_section": "5X6"},
            {"tag": "300-P-UNKNOWN", "calibre_a": 32, "cable_section": "3G4"}
        ]
    }

    resp = client.post("/ie-mto/route-cables", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["routed_count"] == 1
    assert data["unrouted_count"] == 1

    f1 = data["feeders"][0]
    assert f1["tag"] == "300-P-101A"
    assert f1["length_source"] == "DIJKSTRA_ROUTED"
    assert f1["quantity"] is not None
    assert f1["quantity"] > 80.0  # 50 + 30 + drops + elevations + loops

    f2 = data["feeders"][1]
    assert f2["tag"] == "300-P-UNKNOWN"
    assert f2["length_source"] == "UNKNOWN"
    assert f2["quantity"] is None
