"""
Arkan V6 — Material Take-Off (MTO) Engine
Ce module calcule automatiquement les quantitatifs matériels du réseau P&ID.
Il estime les longueurs de tuyauteries, les poids d'acier et liste les composants.
"""

import logging
from typing import Dict, Any
from dtim_model import DTIMProject, EquipmentEntity, InstrumentEntity

logger = logging.getLogger(__name__)

# Theoretical linear weight for standard carbon steel pipes (Schedule 40) in kg/m
PIPING_WEIGHT_MAP = {
    "0.5": 1.27, "0.75": 1.69, "1": 2.50, "1.5": 4.05, "2": 5.44,
    "3": 11.29, "4": 16.07, "6": 28.26, "8": 42.55, "10": 60.31,
    "12": 73.86, "14": 81.44, "16": 93.27, "18": 105.10, "20": 117.00,
    "24": 140.70, "28": 180.00, "30": 200.00, "32": 220.00, "36": 250.00,
    "48": 350.00
}

class MTOEngine:
    def __init__(self, scale_ratio: float = 0.05):
        """
        scale_ratio: Factor to convert drawing units (pixels/mm) to real meters.
                     Default: 1 unit = 0.05 meters.
        """
        self.scale_ratio = scale_ratio

    def calculate_mto(self, project: DTIMProject) -> Dict[str, Any]:
        """
        Calcule les métrés physiques et le tonnage d'acier à partir du DTIMProject.
        """
        logger.info("Début du calcul MTO pour le projet: %s", project.project_name)

        total_length_meters = 0.0
        total_steel_weight_kg = 0.0
        pipe_summary = []
        valve_inventory = {}
        instrument_index = []

        # 1. Calculate Pipe Lengths & Steel weight
        for pipe in project.pipes:
            # Calculate Euclidean length of the polyline
            pixel_length = 0.0
            for i in range(len(pipe.polyline) - 1):
                p1 = pipe.polyline[i]
                p2 = pipe.polyline[i+1]
                pixel_length += self._dist(p1, p2)

            real_length_meters = pixel_length * self.scale_ratio
            total_length_meters += real_length_meters

            # Steel weight calculation based on size in inches
            diameter_str = str(pipe.diameter).replace('"', '').strip()
            unit_weight = PIPING_WEIGHT_MAP.get(diameter_str, 20.0) # default 20 kg/m
            weight_kg = real_length_meters * unit_weight
            total_steel_weight_kg += weight_kg

            pipe_summary.append({
                "line_number": pipe.line_number,
                "diameter": pipe.diameter,
                "fluid": pipe.fluid,
                "spec": pipe.spec,
                "length_meters": round(real_length_meters, 2),
                "weight_kg": round(weight_kg, 1)
            })

        # 2. Count valves by type and diameter
        for comp in project.components:
            if comp.id.startswith("VL-") or "valve" in comp.entity_type.lower():
                vtype = getattr(comp, "equipment_type", "Valve")
                # Look for diameter in attributes or default 4"
                diameter = comp.metadata.get("size", "4") if comp.metadata else "4"
                
                key = (vtype, diameter)
                valve_inventory[key] = valve_inventory.get(key, 0) + 1

        # 3. List instruments
        for comp in project.components:
            if isinstance(comp, InstrumentEntity):
                instrument_index.append({
                    "tag": comp.tag,
                    "loop": comp.loop,
                    "isa_symbol": comp.isa_symbol,
                    "thresholds": comp.thresholds
                })

        # Format valve inventory list for output
        valve_list = [
            {"type": k[0], "diameter": k[1], "quantity": v}
            for k, v in valve_inventory.items()
        ]

        logger.info("MTO Complété. Longueur totale: %.2f m | Tonnage: %.2f tonnes",
                    total_length_meters, total_steel_weight_kg / 1000.0)

        return {
            "project_name": project.project_name,
            "total_length_meters": round(total_length_meters, 2),
            "total_steel_weight_kg": round(total_steel_weight_kg, 1),
            "total_steel_tonnage": round(total_steel_weight_kg / 1000.0, 2),
            "pipes": pipe_summary,
            "valves": valve_list,
            "instruments": instrument_index
        }

    def _dist(self, p1, p2) -> float:
        import math
        return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)
