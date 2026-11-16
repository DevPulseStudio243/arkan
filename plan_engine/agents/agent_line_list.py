"""
Agent Logique 2 : Extraction Line List Structurée
Génère le tableau maître de tuyauterie (Line Number, Service, Diamètre, Spec, Matériau, Design P/T, From/To).
"""
from typing import List, Dict, Any

class LineListAgent:
    """Compile les lignes tracées et les symboles pour générer la Line List conforme ASME B31.3."""

    SERVICE_SPECS = {
        "HC": ("Hydrocarbures", "ASTM A106 Gr.B", "0.0 mm", "10% RT", 25, 60),
        "FG": ("Fuel Gas", "API 5L Gr.B", "0.0 mm", "20% RT", 40, 80),
        "PG": ("Process Gas", "ASTM A333 Gr.6", "Cold Insulation", "100% RT", 85, 120),
        "PW": ("Produced Water", "Inconel 625 / 316L", "None", "10% RT", 15, 50),
        "IA": ("Instrument Air", "Galvanized Carbon Steel", "None", "Visual", 8, 30),
        "N2": ("Nitrogen", "Carbon Steel", "None", "10% RT", 10, 40),
        "FL": ("Flare Relief", "A106-B", "Personal Prot.", "20% RT", 5, 120),
    }

    def generate_line_list(self, traced_lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        line_list = []
        for l in traced_lines:
            srv = l.get("service", "HC")
            srv_info = self.SERVICE_SPECS.get(srv, ("Process Fluid", "Carbon Steel", "None", "10% RT", 20, 60))
            diam = l.get("diameter", '6"')
            spec = l.get("spec", "Cl.300")

            line_list.append({
                "line_number": l.get("line_tag"),
                "service_code": srv,
                "service_description": srv_info[0],
                "nominal_diameter": diam,
                "piping_spec": spec,
                "material": srv_info[1],
                "design_pressure_barg": srv_info[4],
                "design_temp_celsius": srv_info[5],
                "insulation": srv_info[2],
                "ndt_requirement": srv_info[3],
                "from_equipment": l.get("from_node", "HEADER_INLET"),
                "to_equipment": l.get("to_node", "HEADER_OUTLET"),
                "valves_installed": l.get("valves_in_line", []),
                "governing_code": "ASME B31.3",
                "specialist_agent": "specialist-linepipe"
            })
        return line_list

agent_line_list = LineListAgent()
