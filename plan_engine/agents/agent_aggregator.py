"""
Agent Logique 3 : Agrégation & Structuration Unifiée
Compile toutes les données en un graphe topologique et une base JSON/SQLite unifiée.
"""
from typing import Dict, Any

class KnowledgeAggregatorAgent:
    """Fédère les extractions Couche 2 en un objet JSON unifié prêt pour le livrable."""

    def aggregate_all(self, route_info: Dict[str, Any], extractions: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "metadata": extractions.get("title_block", {}),
            "classification": {
                "discipline": route_info.get("primary_discipline"),
                "confidence": route_info.get("confidence"),
                "standards": extractions.get("standards", {}).get("applicable_standards", [])
            },
            "equipment_and_valves": extractions.get("symbols", []),
            "piping_network": {
                "raw_tags": extractions.get("tags", {}),
                "traced_lines": extractions.get("traced_lines", []),
                "flow_directions": extractions.get("flow_directions", [])
            },
            "control_loops": extractions.get("control_loops", []),
            "isometric_data": extractions.get("isometric", {}),
            "structural_mto": extractions.get("structural", {}),
            "civil_foundations_mto": extractions.get("foundations", {}),
            "electrical_sld": extractions.get("electrical_power_and_trays", extractions.get("sld", {})),
            "electrical_power_and_trays": extractions.get("electrical_power_and_trays", {}),
            "instrumentation_and_jb": extractions.get("instrumentation_and_jb", {}),
            "telecom_scada_and_fg": extractions.get("telecom_scada_and_fg", {}),
            "hvac_ventilation_and_ducts": extractions.get("hvac_ventilation_and_ducts", {}),
            "architectural": extractions.get("architectural", {}),
            "underground_vrd": extractions.get("vrd", {}),
            "dimensions_and_scales": extractions.get("dimensions", {})
        }

agent_aggregator = KnowledgeAggregatorAgent()
