"""
test_dxf_to_pid_json.py
=======================
Tests unitaires et de validation du convertisseur DXF vers JSON Sémantique Topologique
(Module 1 - Architecture Option A).
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from dxf_to_pid_json import (
    CONVERTER_VERSION,
    SCHEMA_VERSION,
    DxfToPidJsonConverter,
    convert_dxf_to_json,
)

SAMPLE_DXF = Path(__file__).resolve().parent.parent / "samples" / "synthetic_pid.dxf"


@pytest.fixture
def synthetic_dxf_path():
    """Vérifie et retourne le chemin vers synthetic_pid.dxf."""
    assert SAMPLE_DXF.exists(), f"Fichier test introuvable: {SAMPLE_DXF}"
    return SAMPLE_DXF


@pytest.fixture
def converted_data(synthetic_dxf_path):
    """Exécute la conversion de synthetic_pid.dxf et fournit le dictionnaire JSON."""
    return convert_dxf_to_json(synthetic_dxf_path)


class TestDxfToPidJsonConverter:
    """Suite de tests pour la classe DxfToPidJsonConverter et son API."""

    def test_instantiation_default_and_custom(self):
        """Vérifie l'instanciation avec config par défaut ou surchargée."""
        conv_default = DxfToPidJsonConverter()
        assert conv_default.cfg is not None
        assert "snap_tol" in conv_default.cfg

        custom_cfg = {"snap_tol": 12.0, "equip_attach_tol": 30.0}
        conv_custom = DxfToPidJsonConverter(config=custom_cfg)
        assert conv_custom.cfg["snap_tol"] == 12.0
        assert conv_custom.cfg["equip_attach_tol"] == 30.0

    def test_file_not_found_raises(self, tmp_path):
        """Vérifie qu'un chemin inexistant lève FileNotFoundError."""
        converter = DxfToPidJsonConverter()
        missing = tmp_path / "inexistant.dxf"
        with pytest.raises(FileNotFoundError):
            converter.convert(missing)

    def test_root_structure_keys(self, converted_data):
        """Vérifie la présence de toutes les clés maîtresses du Jumeau Numérique."""
        required_keys = {
            "metadata",
            "equipments",
            "piping_circuits",
            "valves",
            "instruments",
            "loops",
            "instrument_loops",
            "topology_summary",
        }
        assert required_keys.issubset(converted_data.keys())
        assert converted_data["loops"] == converted_data["instrument_loops"]

    def test_metadata_fields(self, converted_data):
        """Vérifie la validité des métadonnées du dessin."""
        meta = converted_data["metadata"]
        assert meta["schema_version"] == SCHEMA_VERSION
        assert meta["converter_version"] == CONVERTER_VERSION
        assert meta["source_file"] == "synthetic_pid.dxf"
        assert "generated_at" in meta
        assert "units" in meta

    def test_equipments_and_nozzles(self, converted_data):
        """Vérifie l'extraction des équipements, géométrie et détection des piquages."""
        equipments = converted_data["equipments"]
        assert len(equipments) == 3

        eq_map = {eq["tag"]: eq for eq in equipments}
        expected_tags = {"201-PP-001/A", "201-PP-001/B", "201-ST-001"}
        assert set(eq_map.keys()) == expected_tags

        # Vérification pompe 201-PP-001/A
        pump_a = eq_map["201-PP-001/A"]
        assert pump_a["type"] == "PUMP"
        assert pump_a["prefix"] == "PP"
        assert len(pump_a["bbox"]) == 4
        assert len(pump_a["cad_anchor"]) == 2
        assert len(pump_a["connected_circuits"]) >= 2

        # Vérification des piquages/nozzles
        nozzles_a = pump_a["nozzles"]
        assert len(nozzles_a) >= 2
        inlet_nozzles = [n for n in nozzles_a if n["direction"] == "INLET"]
        outlet_nozzles = [n for n in nozzles_a if n["direction"] == "OUTLET"]
        assert len(inlet_nozzles) >= 1
        assert len(outlet_nozzles) >= 1

        # Vérification des orientations (N/S/E/W)
        for n in nozzles_a:
            assert n["orientation"] in {"N", "S", "E", "W"}
            assert len(n["coords"]) == 2
            assert len(n["connected_circuits"]) > 0

        # Pompe A : aspiration à l'ouest (W), refoulement à l'est (E)
        assert inlet_nozzles[0]["orientation"] == "W"
        assert outlet_nozzles[0]["orientation"] == "E"

        # Vérification crépine 201-ST-001
        strainer = eq_map["201-ST-001"]
        assert strainer["type"] == "FILTER_STRAINER"
        assert strainer["prefix"] == "ST"
        assert len(strainer["nozzles"]) >= 2

    def test_piping_circuits_and_inline_components(self, converted_data):
        """Vérifie la continuité des circuits, orientations et composants en ligne."""
        circuits = converted_data["piping_circuits"]
        assert len(circuits) == 4

        circ_map = {c["line_id"]: c for c in circuits}
        assert set(circ_map.keys()) == {"CIRC-001", "CIRC-002", "CIRC-003", "CIRC-004"}

        # Circuit CIRC-001: Header ouvert -> Crépine
        c1 = circ_map["CIRC-001"]
        assert c1["from_node"]["node_type"] == "OPEN_HEADER"
        assert c1["to_node"]["equipment_tag"] == "201-ST-001"
        assert c1["to_node"]["node_type"] == "EQUIPMENT"
        assert c1["length"] > 0

        # Circuit CIRC-002: Crépine -> Pompe A
        c2 = circ_map["CIRC-002"]
        assert c2["from_node"]["equipment_tag"] == "201-ST-001"
        assert c2["to_node"]["equipment_tag"] == "201-PP-001/A"

        # Circuit CIRC-003: Pompe A -> Pompe B avec vanne en ligne 201-HV-001
        c3 = circ_map["CIRC-003"]
        assert c3["from_node"]["equipment_tag"] == "201-PP-001/A"
        assert c3["to_node"]["equipment_tag"] == "201-PP-001/B"
        assert len(c3["in_line_components"]) == 1

        inline_comp = c3["in_line_components"][0]
        assert inline_comp["tag"] == "201-HV-001"
        assert inline_comp["type"] == "VALVE"
        assert 0.0 <= inline_comp["position_ratio"] <= 1.0

        # Circuit CIRC-004: Pompe B -> Header ouvert
        c4 = circ_map["CIRC-004"]
        assert c4["from_node"]["equipment_tag"] == "201-PP-001/B"
        assert c4["to_node"]["node_type"] == "OPEN_HEADER"

    def test_valves(self, converted_data):
        """Vérifie la détection et les attributs des vannes."""
        valves = converted_data["valves"]
        assert len(valves) == 1

        v = valves[0]
        assert v["tag"] == "201-HV-001"
        assert v["valve_type"] == "MANUAL_VALVE"
        assert v["sub_type"] == "HV"
        assert v["circuit_id"] == "CIRC-003"
        assert v["line_tag"] == '4"-P-101-CS-101'
        assert 0.0 <= v["position_ratio"] <= 1.0
        assert v["lock_status"] == "NONE"
        assert v["has_tag"] is True

    def test_topology_summary(self, converted_data):
        """Vérifie le résumé statistique et le taux de connectivité."""
        summary = converted_data["topology_summary"]
        assert summary["total_equipments"] == 3
        assert summary["connected_equipments"] == 3
        assert summary["isolated_equipments"] == 0
        assert summary["total_circuits"] == 4
        assert summary["complete_circuits"] == 2  # CIRC-002 et CIRC-003 sont entre équipements
        assert summary["open_circuits"] == 2      # CIRC-001 et CIRC-004 ont une extrémité ouverte
        assert summary["total_valves"] == 1
        assert summary["valves_with_tag"] == 1
        assert summary["connectivity_ratio"] == 1.0

    def test_json_file_export(self, synthetic_dxf_path, tmp_path):
        """Vérifie l'écriture physique dans un fichier JSON et sa relecture."""
        out_json = tmp_path / "output_pid_test.json"
        data = convert_dxf_to_json(synthetic_dxf_path, output_json_path=out_json, pretty=True)

        assert out_json.exists()
        reloaded = json.loads(out_json.read_text(encoding="utf-8"))
        assert reloaded["metadata"]["source_file"] == data["metadata"]["source_file"]
        assert len(reloaded["equipments"]) == len(data["equipments"])
        assert len(reloaded["piping_circuits"]) == len(data["piping_circuits"])

    def test_instrument_and_loops_isa_5_1(self):
        """Vérifie la conformité de l'extraction des instruments et boucles ISA-5.1."""
        conv = DxfToPidJsonConverter()
        raw_data = {"entities": []}
        semantic_data = {
            "elements": [
                {
                    "kind": "instrument",
                    "tag": "PT-101",
                    "position": [100.0, 100.0],
                    "parts": {"var": "P", "fn": "T", "loop": "101"},
                    "confidence": 0.95,
                },
                {
                    "kind": "instrument",
                    "tag": "PIC-101",
                    "position": [110.0, 100.0],
                    "parts": {"var": "P", "fn": "IC", "loop": "101"},
                    "confidence": 0.95,
                },
            ]
        }
        valves = [
            {
                "id": "VALV-001",
                "tag": "PV-101",
                "valve_type": "CONTROL_VALVE",
                "sub_type": "PV",
                "circuit_id": "CIRC-001",
            }
        ]
        circuits = []
        instruments, loops = conv._build_instruments_and_loops(raw_data, semantic_data, circuits, valves)

        assert len(instruments) == 2
        assert instruments[0]["tag"] == "PT-101"
        assert instruments[0]["variable"] == "P"
        assert instruments[0]["variable_desc"] == "Pressure / Vacuum"

        assert len(loops) == 1
        lp = loops[0]
        assert lp["loop_tag"] == "P-101"
        assert lp["transmitter"] == "PT-101"
        assert lp["controller"] == "PIC-101"
        assert lp["final_element"] == "PV-101"
        assert lp["is_complete"] is True
