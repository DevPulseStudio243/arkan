"""
DEERFLOW LITE — Connectivity & O&G Construction Agent
Deduces physical welds, computes painting surface areas, calculates insulation volumes, 
and exports neutral model files for Caesar II stress analysis.
"""
import math
import logging
from typing import List, Dict, Any
from engineering_catalog import get_pipe_spec

logger = logging.getLogger(__name__)

def compute_welds(mto_items: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Deduces the number of welds required for construction.
    Butt-welded fittings (Elbows, Reducers) require 2 welds.
    RFWN flanges require 1 weld.
    """
    shop_welds = 0
    field_welds = 0
    
    for item in mto_items:
        cat = item.get("category")
        desc = item.get("description", "").lower()
        qty = int(item.get("quantity", 0))
        
        if cat == "Fittings":
            if "coude" in desc or "elbow" in desc:
                # 2 welds per elbow
                shop_welds += qty * 2
            elif "réduction" in desc or "reducer" in desc:
                # 2 welds per reducer
                shop_welds += qty * 2
            elif "tée" in desc or "tee" in desc:
                # 3 welds per tee
                shop_welds += qty * 3
            elif "bride" in desc or "flange" in desc:
                # 1 weld per RFWN flange
                field_welds += qty  # flanges are often field welded
                
    return {"shop_welds": shop_welds, "field_welds": field_welds, "total_welds": shop_welds + field_welds}

def compute_paint_and_insulation(mto_items: List[Dict[str, Any]], insulation_thickness_mm: float = 50.0) -> Dict[str, float]:
    """
    Calculates the paint surface area (m2), insulation volume (m3), and rockwool weight (kg).
    Formula:
      - Paint Area = pi * OD_m * Length
      - Insulation Volume = pi * ((OD_m/2 + t_m)^2 - (OD_m/2)^2) * Length
    """
    total_paint_area = 0.0
    total_insulation_volume = 0.0
    rockwool_density = 100.0  # kg/m3
    
    for item in mto_items:
        if item.get("category") == "Pipes":
            raw_sz = item.get("size", '3"').split(' ')[0] # Extract e.g. 3"
            qty = float(item.get("quantity", 0.0)) # Length in meters
            
            spec = get_pipe_spec(raw_sz)
            od_m = spec["outer_diameter_mm"] / 1000.0
            
            # Paint area
            paint_area = math.pi * od_m * qty
            total_paint_area += paint_area
            
            # Insulation
            t_m = insulation_thickness_mm / 1000.0
            outer_r = od_m / 2.0 + t_m
            inner_r = od_m / 2.0
            ins_vol = math.pi * (outer_r**2 - inner_r**2) * qty
            total_insulation_volume += ins_vol
            
    insulation_weight = total_insulation_volume * rockwool_density
    
    return {
        "paint_area_m2": round(total_paint_area, 2),
        "insulation_volume_m3": round(total_insulation_volume, 3),
        "insulation_weight_kg": round(insulation_weight, 2)
    }

def export_to_caesar_ii(caesar_nodes: List[Dict[str, Any]], pipe_lengths: Dict[str, float]) -> str:
    """
    Generates a neutral text format file for Caesar II stress analysis import.
    Contains nodes, coordinate directions, pipe properties, pressure and temperature.
    """
    lines = []
    lines.append("======================================================================")
    lines.append(" CAESAR II NEUTRAL PIPE MODEL EXPORT - DEERFLOW DIGITAL RECONSTRUCTION")
    lines.append("======================================================================")
    lines.append(f"PROJECT REF: UTG-TRAIN-A")
    lines.append(f"DESIGN TEMPERATURE: 40 degC")
    lines.append(f"DESIGN PRESSURE: 10.3 barg")
    lines.append("----------------------------------------------------------------------")
    lines.append("NODE ID     X (mm)      Y (mm)      Z (mm)      SIZE       LABEL")
    lines.append("----------------------------------------------------------------------")
    
    for node in caesar_nodes:
        node_id = node["node_id"].ljust(10)
        x = str(node["x_mm"]).ljust(12)
        y = str(node["y_mm"]).ljust(12)
        z = str(node["z_mm"]).ljust(12)
        size = node["size"].ljust(10)
        label = node["label"]
        lines.append(f"{node_id}  {x}{y}{z}{size} {label}")
        
    lines.append("----------------------------------------------------------------------")
    lines.append("PIPING ELEMENTS & SCHEDULE PROPERTIES")
    lines.append("----------------------------------------------------------------------")
    for sz, length in pipe_lengths.items():
        spec = get_pipe_spec(sz)
        lines.append(f"SIZE: {sz.ljust(6)} | Sched: 40 | OD: {spec['outer_diameter_mm']} mm | Thickness: {spec['thickness_mm']} mm | Length: {length} m")
    
    lines.append("======================================================================")
    return "\n".join(lines)
