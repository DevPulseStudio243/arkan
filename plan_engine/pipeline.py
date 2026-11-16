"""
ARQAN Plan Engine - Façade d'Orchestration Maître (Master Pipeline)
Orchestre les 3 couches complètes (1 Orchestrateur + 18 Modèles Spécialisés + 4 Agents Logiques)
couvrant TOUTES les disciplines : P&ID, ISO, Structure, Civil, Électricité (Force & Chemins),
Instrumentation (Boucles & JB), Télécom & SCADA / F&G, CVC / HVAC, VRD et Architecture.
"""

import sys
import logging
from typing import Dict, Any, Optional
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Couche 1 : Orchestrateur & Routeur
from plan_engine.router.plan_router import plan_router

# Couche 2 : Modèles spécialisés
from plan_engine.models.m01_pid_symbols import m01
from plan_engine.models.m02_technical_ocr import m02
from plan_engine.models.m03_line_tracer import m03
from plan_engine.models.m04_control_loops import m04
from plan_engine.models.m05_isometric_parser import m05
from plan_engine.models.m06_flow_direction import m06
from plan_engine.models.m08_structural_steel import m08
from plan_engine.models.m09_foundations_geotech import m09
from plan_engine.models.m10_architectural import m10
from plan_engine.models.m11_underground_vrd import m11
from plan_engine.models.m12_dimensions_scaler import m12
from plan_engine.models.m13_sld_unifilar import m13
from plan_engine.models.m14_cabling_instrument import m14
from plan_engine.models.m15_legends_standards import m15
from plan_engine.models.m16_title_block_ocr import m16
from plan_engine.models.m17_telecom_scada_cctv import m17
from plan_engine.models.m18_hvac_ventilation_ducts import m18

# Couche 3 : Agents logiques
from plan_engine.agents.agent_line_list import agent_line_list
from plan_engine.agents.agent_cross_validator import agent_cross_validator
from plan_engine.agents.agent_aggregator import agent_aggregator
from plan_engine.agents.agent_reporter import agent_reporter

logger = logging.getLogger("plan_engine.pipeline")

class PlanMultiAgentPipeline:
    """Façade unifiée pour l'exécution complète du système multi-agents de lecture de plans."""

    def __init__(self):
        self.router = plan_router
        self.models = {
            "m01": m01, "m02": m02, "m03": m03, "m04": m04,
            "m05": m05, "m06": m06, "m08": m08, "m09": m09,
            "m10": m10, "m11": m11, "m12": m12, "m13": m13,
            "m14": m14, "m15": m15, "m16": m16, "m17": m17,
            "m18": m18
        }
        self.agents = {
            "agent_line_list": agent_line_list,
            "agent_cross_validator": agent_cross_validator,
            "agent_aggregator": agent_aggregator,
            "agent_reporter": agent_reporter
        }

    def process_plan(self, text_content: str, filename: str = "", discipline_override: Optional[str] = None) -> Dict[str, Any]:
        # 1. COUCHE 1 : DÉTECTION & ROUTAGE
        route_info = self.router.route_document(text_content, filename=filename)
        if discipline_override:
            route_info["primary_discipline"] = discipline_override

        disc = route_info["primary_discipline"]

        # 2. COUCHE 2 : MODÈLES D'EXTRACTION SPÉCIALISÉS
        title_block = m16.extract_title_block(text_content, filename=filename)
        standards = m15.get_standards_context(disc)
        tags_data = m02.extract_tags(text_content)
        dimensions = m12.extract_dimensions(text_content)

        symbols = m01.extract_symbols(text_content)
        traced_lines = m03.trace_connectivity(tags_data.get("piping_lines", []), symbols)
        flow_dirs = m06.analyze_flows(traced_lines)
        control_loops = m04.extract_loops(text_content)
        isometric_data = m05.parse_isometric(text_content) if disc in ("isometric", "pid") else {}
        structural_data = m08.extract_structural(text_content) if disc in ("steel", "civil") else {}
        foundations_data = m09.extract_foundations(text_content) if disc in ("civil", "steel") else {}

        # Nouveaux modules dédiés & enrichis
        electrical_data = m13.extract_sld_and_cabling(text_content) if disc in ("electrical", "pid") else {}
        instrumentation_data = m14.extract_instrument_cabling(text_content) if disc in ("instrumentation", "pid", "electrical") else {}
        telecom_data = m17.extract_telecom_scada(text_content) if disc in ("telecom", "instrumentation", "electrical") else {}
        hvac_data = m18.extract_hvac(text_content) if disc in ("hvac", "architectural") else {}
        architectural_data = m10.extract_architectural(text_content) if disc == "architectural" else {}
        vrd_data = m11.extract_vrd(text_content) if disc == "vrd" else {}

        extractions = {
            "title_block": title_block,
            "standards": standards,
            "tags": tags_data,
            "dimensions": dimensions,
            "symbols": symbols,
            "traced_lines": traced_lines,
            "flow_directions": flow_dirs,
            "control_loops": control_loops,
            "isometric": isometric_data,
            "structural": structural_data,
            "foundations": foundations_data,
            "electrical_power_and_trays": electrical_data,
            "instrumentation_and_jb": instrumentation_data,
            "telecom_scada_and_fg": telecom_data,
            "hvac_ventilation_and_ducts": hvac_data,
            "architectural": architectural_data,
            "vrd": vrd_data
        }

        # 3. COUCHE 3 : AGENTS LOGIQUES D'ORCHESTRATION
        line_list = agent_line_list.generate_line_list(traced_lines)
        cross_validation = agent_cross_validator.validate_cross_plans({
            "discipline": disc,
            "symbols": symbols,
            "lines": traced_lines,
            "sld": electrical_data,
            "foundations": foundations_data,
            "instrumentation": instrumentation_data,
            "telecom": telecom_data,
            "hvac": hvac_data
        })
        aggregated = agent_aggregator.aggregate_all(route_info, extractions)
        final_deliverable = agent_reporter.generate_final_report(aggregated, cross_validation, line_list)

        return {
            "status": "SUCCESS",
            "orchestrator_route": route_info,
            "line_list": line_list,
            "cross_validation": cross_validation,
            "aggregated_knowledge_graph": aggregated,
            "deliverable_report": final_deliverable
        }

master_pipeline = PlanMultiAgentPipeline()
