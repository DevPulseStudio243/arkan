"""
DEXPI ISO 15926 Proteus XML Exporter for Arkan EPC Intelligence.
Serializes plant engineering data (Equipment, PipingComponents, Instruments, PipingNetworkSegments)
into fully compliant DEXPI 1.3 Proteus XML format.
"""

import logging
import os
import xml.dom.minidom
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

logger = logging.getLogger("dexpi_exporter")


def create_dexpi_xml_tree(project_data: Dict[str, Any]) -> ET.Element:
    """
    Creates a strict DEXPI 1.3 / ISO 15926 Proteus XML ElementTree root.
    """
    project_name = project_data.get("name", "Arkan_Plant_Project")

    root = ET.Element("ProteusXML", {
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
        "SchemaVersion": "1.3",
        "ProductRelease": "DEXPI 1.3",
        "OriginatingSystem": "Arkan EPC Intelligence v4.0",
        "Date": project_data.get("date", "2026-07-19"),
        "Time": "00:00:00"
    })

    plant_model = ET.SubElement(root, "PlantModel", {
        "ID": "PLANT_MODEL_01",
        "PlantName": project_name
    })

    plant_item = ET.SubElement(plant_model, "Plant", {"ID": "PLANT_01", "TagName": "PLANT-01"})
    area_item = ET.SubElement(plant_item, "PlantArea", {"ID": "AREA_01", "TagName": "AREA-100"})

    # 1. Export Equipment
    equipment_list = project_data.get("equipment", [])
    for idx, eq in enumerate(equipment_list):
        tag = eq.get("tag", f"EQ-{idx+1}")
        etype = eq.get("type", "Equipment")
        eq_class = "Pump" if "pompe" in etype.lower() else "Vessel" if "ballon" in etype.lower() else "HeatExchanger" if "échangeur" in etype.lower() else "Equipment"
        
        eq_el = ET.SubElement(area_item, "Equipment", {
            "ID": f"EQ_{idx+1}",
            "TagName": tag,
            "ComponentClass": eq_class,
            "Capacity": str(eq.get("capacity", "N/A")),
            "Configuration": str(eq.get("configuration", "1(1+0)"))
        })

        # Add Bounding Box if available
        if "box" in eq:
            box = eq["box"]
            ET.SubElement(eq_el, "Extent", {
                "MinX": str(box[0]), "MinY": str(box[1]),
                "MaxX": str(box[2]), "MaxY": str(box[3])
            })

    # 2. Export Valves & Piping Components
    valves_list = project_data.get("valves", [])
    for idx, v in enumerate(valves_list):
        tag = v.get("tag", f"V-{idx+1}")
        vtype = v.get("type", "Valve")
        func = v.get("function", "isolement")
        vclass = "SafetyValve" if "sécurité" in func.lower() or "surpression" in func.lower() else "ControlValve" if "régulation" in func.lower() else "GateValve"

        v_el = ET.SubElement(area_item, "PipingComponent", {
            "ID": f"PIPE_COMP_{idx+1}",
            "TagName": tag,
            "ComponentClass": vclass,
            "NominalDiameter": f"DN{int(v.get('size_inch', 4) * 25)}",
            "NormalState": str(v.get("normal_state", "NO")),
            "Function": str(func)
        })

    # 3. Export Instrumentation Loops
    instruments_list = project_data.get("instruments", [])
    for idx, inst in enumerate(instruments_list):
        tag = inst.get("tag", f"INST-{idx+1}")
        isa_func = inst.get("isa_function", tag.split("-")[0] if "-" in tag else "PT")

        inst_el = ET.SubElement(area_item, "InstrumentationLoop", {
            "ID": f"INST_LOOP_{idx+1}",
            "TagName": tag,
            "ComponentClass": f"Instrument_{isa_func}",
            "LoopNumber": str(inst.get("loop_number", "100")),
            "IsaFunction": str(isa_func)
        })

    # 4. Export Piping Network Segments (Lines)
    lines_list = project_data.get("lines", project_data.get("pipelines", []))
    for idx, line in enumerate(lines_list):
        ltag = line.get("line_tag", line.get("line", f"LINE-{idx+1}"))
        from_node = line.get("from", line.get("from_equipment", "OPEN"))
        to_node = line.get("to", line.get("to_equipment", "OPEN"))

        line_el = ET.SubElement(area_item, "PipingNetworkSegment", {
            "ID": f"PIPE_SEG_{idx+1}",
            "TagName": ltag,
            "FromComponent": str(from_node),
            "ToComponent": str(to_node),
            "ServiceCode": str(line.get("service_code", "PR")),
            "SpecCode": str(line.get("spec_code", "A1"))
        })

        if "path_coords" in line:
            for c_idx, coords in enumerate(line["path_coords"]):
                ET.SubElement(line_el, "ConnectionPoint", {
                    "PointIndex": str(c_idx),
                    "X0": str(coords[0]), "Y0": str(coords[1]),
                    "X1": str(coords[2]), "Y1": str(coords[3])
                })

    return root


def export_project_to_dexpi_xml(project_data: Dict[str, Any], output_filepath: Optional[str] = None) -> str:
    """
    Exports project data to formatted DEXPI 1.3 XML string and optionally saves to file.
    """
    root = create_dexpi_xml_tree(project_data)
    xml_raw = ET.tostring(root, encoding="utf-8")
    
    # Pretty-print XML format
    dom = xml.dom.minidom.parseString(xml_raw)
    xml_pretty = dom.toprettyxml(indent="  ")

    if output_filepath:
        os.makedirs(os.path.dirname(os.path.abspath(output_filepath)), exist_ok=True)
        with open(output_filepath, "w", encoding="utf-8") as f:
            f.write(xml_pretty)
        logger.info("Successfully exported DEXPI XML to %s", output_filepath)

    return xml_pretty
