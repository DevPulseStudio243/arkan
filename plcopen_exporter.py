"""
PLCopen XML (IEC 61131-3) Exporter for Arkan EPC Intelligence.
Generates standardized PLCopen XML for control logic diagrams, interlocks, and automation loops
suitable for importing into PLCs (Siemens TIA Portal, Schneider EcoStruxure, CODESYS, Rockwell).
"""

import logging
import os
import xml.dom.minidom
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

logger = logging.getLogger("plcopen_exporter")


def create_plcopen_xml_tree(logic_data: Dict[str, Any]) -> ET.Element:
    """
    Creates a strict PLCopen XML (IEC 61131-3) ElementTree root.
    """
    app_name = logic_data.get("name", "Arkan_Control_Logic")

    root = ET.Element("project", {
        "xmlns": "http://www.plcopen.org/xml/tc6_0201",
        "xmlns:xhtml": "http://www.w3.org/1999/xhtml",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": "http://www.plcopen.org/xml/tc6_0201 tc6_0201.xsd"
    })

    file_header = ET.SubElement(root, "fileHeader", {
        "companyName": "Arkan EPC Intelligence v4.0",
        "productName": "Arkan Logic Diagram Converter",
        "productVersion": "4.0",
        "creationDateTime": "2026-07-19T00:00:00"
    })

    content_header = ET.SubElement(root, "contentHeader", {
        "name": app_name,
        "modificationDateTime": "2026-07-19T00:00:00"
    })

    types_el = ET.SubElement(root, "types")
    data_types = ET.SubElement(types_el, "dataTypes")
    pous_el = ET.SubElement(types_el, "pous")

    # Create Program Organization Unit (POU)
    pou_el = ET.SubElement(pous_el, "pou", {
        "name": f"POU_{app_name}",
        "pouType": "program"
    })

    interface_el = ET.SubElement(pou_el, "interface")
    input_vars = ET.SubElement(interface_el, "inputVars")
    output_vars = ET.SubElement(interface_el, "outputVars")

    # Add ESD/Hand Switches as Inputs
    inputs_list = logic_data.get("inputs", logic_data.get("safety", {}).get("hand_switches", []))
    for idx, inp in enumerate(inputs_list):
        itag = inp.get("tag", f"IN_{idx+1}") if isinstance(inp, dict) else str(inp)
        var_el = ET.SubElement(input_vars, "variable", {"name": itag})
        ET.SubElement(var_el, "type", {"name": "BOOL"})

    # Add Actuators / Shutdown Points as Outputs
    outputs_list = logic_data.get("outputs", logic_data.get("safety", {}).get("esd_points", []))
    for idx, outp in enumerate(outputs_list):
        otag = outp.get("tag", f"OUT_{idx+1}") if isinstance(outp, dict) else str(outp)
        var_el = ET.SubElement(output_vars, "variable", {"name": otag})
        ET.SubElement(var_el, "type", {"name": "BOOL"})

    # Create FBD (Function Block Diagram) Body
    body_el = ET.SubElement(pou_el, "body")
    fbd_el = ET.SubElement(body_el, "FBD")

    # Add Logic Gate (e.g. AND / OR interlock)
    gate_el = ET.SubElement(fbd_el, "block", {
        "localId": "1",
        "typeName": logic_data.get("gate_type", "AND"),
        "instanceName": "ESD_Interlock_Gate"
    })
    ET.SubElement(gate_el, "position", {"x": "100", "y": "100"})

    # Instances
    instances_el = ET.SubElement(root, "instances")
    configurations_el = ET.SubElement(instances_el, "configurations")
    config_el = ET.SubElement(configurations_el, "configuration", {"name": "Arkan_PLC_Config"})
    resource_el = ET.SubElement(config_el, "resource", {"name": "CPU_Resource"})
    task_el = ET.SubElement(resource_el, "task", {"name": "MainTask", "interval": "PT0.01S", "priority": "1"})
    ET.SubElement(task_el, "pouInstance", {"name": f"POU_{app_name}", "typeName": f"POU_{app_name}"})

    return root


def export_logic_to_plcopen_xml(logic_data: Dict[str, Any], output_filepath: Optional[str] = None) -> str:
    """
    Exports control logic diagram data to formatted PLCopen XML string and optionally saves to file.
    """
    root = create_plcopen_xml_tree(logic_data)
    xml_raw = ET.tostring(root, encoding="utf-8")

    dom = xml.dom.minidom.parseString(xml_raw)
    xml_pretty = dom.toprettyxml(indent="  ")

    if output_filepath:
        os.makedirs(os.path.dirname(os.path.abspath(output_filepath)), exist_ok=True)
        with open(output_filepath, "w", encoding="utf-8") as f:
            f.write(xml_pretty)
        logger.info("Successfully exported PLCopen XML to %s", output_filepath)

    return xml_pretty
