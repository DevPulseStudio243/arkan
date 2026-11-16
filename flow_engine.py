"""
Arkan V6 — Flow Inference Engine
Ce module calcule et propage la direction du fluide (flux) à travers le réseau P&ID.
Il oriente le start_point (From) et l'end_point (To) des lignes du DTIM de manière logique.
"""

import logging
import math
from typing import Dict, Any, List, Set, Tuple
from dtim_model import DTIMProject, PipeEntity, EquipmentEntity

logger = logging.getLogger(__name__)

class FlowEngine:
    def __init__(self):
        pass

    def infer_flow_directions(self, project: DTIMProject) -> DTIMProject:
        """
        Analyse la topologie 2D globale du jumeau numérique DTIM et applique
        une propagation de flux par parcours en largeur (BFS) à partir des sources de pression
        (pompes, vannes NRV, renvois de plan sémantiques) et des flèches de flux locales.
        """
        logger.info("Début de l'inférence de flux pour le projet: %s", project.project_name)

        if not project.pipes:
            logger.info("Aucune conduite à analyser dans le projet.")
            return project

        # --- Fonctions géométriques de distance ---
        def point_to_segment_distance(px, py, x1, y1, x2, y2):
            dx = x2 - x1
            dy = y2 - y1
            if dx == 0 and dy == 0:
                return math.sqrt((px - x1)**2 + (py - y1)**2)
            t = ((px - x1) * dx + (py - y1) * dy) / (dx*dx + dy*dy)
            t = max(0.0, min(1.0, t))
            proj_x = x1 + t * dx
            proj_y = y1 + t * dy
            return math.sqrt((px - proj_x)**2 + (py - proj_y)**2)

        def min_distance_to_pipe(px, py, pipe_entity: PipeEntity):
            min_d = float('inf')
            if not pipe_entity.polyline or len(pipe_entity.polyline) < 2:
                d1 = math.sqrt((px - pipe_entity.start_point[0])**2 + (py - pipe_entity.start_point[1])**2)
                d2 = math.sqrt((px - pipe_entity.end_point[0])**2 + (py - pipe_entity.end_point[1])**2)
                return min(d1, d2)
            for i in range(len(pipe_entity.polyline) - 1):
                x1, y1 = pipe_entity.polyline[i]
                x2, y2 = pipe_entity.polyline[i+1]
                d = point_to_segment_distance(px, py, x1, y1, x2, y2)
                if d < min_d:
                    min_d = d
            return min_d

        # 1. Clustering spatial des coordonnées d'extrémité pour identifier les noeuds de connexion
        tolerance = 50.0
        clusters: List[Set[Tuple[float, float]]] = []

        def get_cluster_id(pt: Tuple[float, float]) -> int:
            for idx, c_set in enumerate(clusters):
                for cpt in c_set:
                    dist = math.sqrt((pt[0] - cpt[0])**2 + (pt[1] - cpt[1])**2)
                    if dist <= tolerance:
                        c_set.add(pt)
                        return idx
            clusters.append({pt})
            return len(clusters) - 1

        # Mappage de chaque extrémité de conduite vers son ID de cluster
        pipe_node_map = {}
        for pipe in project.pipes:
            start_id = get_cluster_id(pipe.start_point)
            end_id = get_cluster_id(pipe.end_point)
            pipe_node_map[pipe.id] = (start_id, end_id)

        # Mappage des ports des équipements vers leurs clusters correspondants
        port_node_map = {} # (comp_tag, port_name) -> cluster_id
        for comp in project.components:
            if hasattr(comp, "ports"):
                for port in comp.ports:
                    p_id = get_cluster_id(port.position)
                    port_node_map[(getattr(comp, "tag", comp.id), port.name)] = p_id

        # 2. Construction de la table d'adjacence du réseau pour le BFS
        node_to_pipes: Dict[int, List[Tuple[str, str]]] = {}
        for pipe_id, (start_id, end_id) in pipe_node_map.items():
            node_to_pipes.setdefault(start_id, []).append((pipe_id, "start"))
            node_to_pipes.setdefault(end_id, []).append((pipe_id, "end"))

        # 3. Identification des points d'injection de flux (sources) et d'aspiration (puits)
        flow_sources: Dict[int, Tuple[str, str, float, str]] = {}
        
        # Cas A & B : Pompes et Clapets NRV
        for comp in project.components:
            if not isinstance(comp, EquipmentEntity):
                continue
            tag = getattr(comp, "tag", comp.id)
            etype = comp.equipment_type.lower()
            
            if any(k in etype for k in ("pompe", "pump")):
                for port in comp.ports:
                    node_id = port_node_map.get((tag, port.name))
                    if node_id is not None:
                        if port.name == "Discharge":
                            flow_sources[node_id] = ("SOURCE", tag, 1.0, f"Connected to Discharge port of Pump: {tag}")
                        elif port.name == "Suction":
                            flow_sources[node_id] = ("SINK", tag, 1.0, f"Connected to Suction port of Pump: {tag}")
                            
            elif any(k in etype for k in ("nrv", "clapet", "checkvalve", "check valve")):
                for port in comp.ports:
                    node_id = port_node_map.get((tag, port.name))
                    if node_id is not None:
                        if port.name == "OUT":
                            flow_sources[node_id] = ("SOURCE", tag, 0.95, f"Flow aligned with non-return valve: {tag}")
                        elif port.name == "IN":
                            flow_sources[node_id] = ("SINK", tag, 0.95, f"Flow aligned with non-return valve: {tag}")

        pipe_orientations: Dict[str, Tuple[str, float, str]] = {} # pipe_id -> (direction, confidence, reason)
        queue: List[Tuple[int, str, float, str, bool]] = [] # list of (node_id, source_tag, confidence, reason, is_root)
        visited_nodes: Set[int] = set()
        visited_pipes: Set[str] = set()

        # Cas C : Analyse sémantique des textes FROM / TO (renvois de plans)
        raw_elements = getattr(project, "raw_elements", [])
        for el in raw_elements:
            tag = el.get("tag", "").upper()
            etype = el.get("type", "").upper()
            box = el.get("box", [0,0,0,0])
            cx = (box[0] + box[2]) / 2
            cy = (box[1] + box[3]) / 2
            
            is_from = "FROM" in tag or "FROM" in etype or "PROVENANCE" in tag or "PROVENANCE" in etype
            is_to = "TO" in tag or "TO" in etype or "VERS" in tag or "VERS" in etype or "DESTINATION" in tag or "DESTINATION" in etype
            
            if is_from or is_to:
                # Trouver l'extrémité de conduite la plus proche du texte de renvoi
                closest_pipe = None
                closest_end = None
                min_d = float('inf')
                for pipe in project.pipes:
                    d_start = math.sqrt((cx - pipe.start_point[0])**2 + (cy - pipe.start_point[1])**2)
                    d_end = math.sqrt((cx - pipe.end_point[0])**2 + (cy - pipe.end_point[1])**2)
                    if d_start < min_d:
                        min_d = d_start
                        closest_pipe = pipe
                        closest_end = "start"
                    if d_end < min_d:
                        min_d = d_end
                        closest_pipe = pipe
                        closest_end = "end"
                
                # Seuil d'association sémantique
                if min_d <= 200.0 and closest_pipe is not None:
                    node_id = pipe_node_map[closest_pipe.id][0] if closest_end == "start" else pipe_node_map[closest_pipe.id][1]
                    if is_from:
                        flow_sources[node_id] = ("SOURCE", el.get("tag", ""), 0.90, f"Flow starts from plan connector: {el.get('tag', '')}")
                    else:
                        flow_sources[node_id] = ("SINK", el.get("tag", ""), 0.90, f"Flow ends at plan connector: {el.get('tag', '')}")

        # Cas D : Analyse des flèches de flux (FlowArrows)
        for el in raw_elements:
            etype = el.get("type", "").lower()
            tag = el.get("tag", "").lower()
            if "arrow" in etype or "flowarrow" in etype or "arrow" in tag or "flowarrow" in tag:
                box = el.get("box", [0,0,0,0])
                cx = (box[0] + box[2]) / 2
                cy = (box[1] + box[3]) / 2
                
                # Récupérer l'orientation du vecteur de la flèche
                ux = el.get("ux", 1.0)
                uy = el.get("uy", 0.0)
                
                # Trouver la conduite la plus proche de la flèche
                closest_pipe = None
                min_d = float('inf')
                for pipe in project.pipes:
                    d = min_distance_to_pipe(cx, cy, pipe)
                    if d < min_d:
                        min_d = d
                        closest_pipe = pipe
                
                # Seuil d'association locale
                if min_d <= 150.0 and closest_pipe is not None:
                    # Vecteur directeur de la conduite
                    dx = closest_pipe.end_point[0] - closest_pipe.start_point[0]
                    dy = closest_pipe.end_point[1] - closest_pipe.start_point[1]
                    
                    dot_product = ux * dx + uy * dy
                    start_cluster, end_cluster = pipe_node_map[closest_pipe.id]
                    
                    if dot_product >= 0:
                        # La flèche et la conduite sont alignées (forward)
                        pipe_orientations[closest_pipe.id] = ("forward", 0.95, f"Aligned with flow arrow: {el.get('tag', 'FlowArrow')}")
                        visited_pipes.add(closest_pipe.id)
                        # Le nœud de sortie devient une source
                        flow_sources[end_cluster] = ("SOURCE", f"Arrow-{closest_pipe.id}", 0.95, f"BFS source from flow arrow: {el.get('tag', 'FlowArrow')}")
                        # Le nœud d'entrée devient un puits
                        flow_sources[start_cluster] = ("SINK", f"Arrow-{closest_pipe.id}", 0.95, f"BFS sink from flow arrow: {el.get('tag', 'FlowArrow')}")
                    else:
                        # La flèche et la conduite sont opposées (reverse)
                        pipe_orientations[closest_pipe.id] = ("reverse", 0.95, f"Aligned with flow arrow (reverse): {el.get('tag', 'FlowArrow')}")
                        visited_pipes.add(closest_pipe.id)
                        # Le nœud de départ devient une source
                        flow_sources[start_cluster] = ("SOURCE", f"Arrow-{closest_pipe.id}", 0.95, f"BFS source from flow arrow: {el.get('tag', 'FlowArrow')}")
                        # Le nœud de fin devient un puits
                        flow_sources[end_cluster] = ("SINK", f"Arrow-{closest_pipe.id}", 0.95, f"BFS sink from flow arrow: {el.get('tag', 'FlowArrow')}")
        # Cas E : Analyse des textes FROM / TO directement dans le tag ou le texte de la conduite
        for pipe in project.pipes:
            pipe_tag = pipe.line_number.upper()
            is_from = "FROM" in pipe_tag or "PROVENANCE" in pipe_tag
            is_to = "TO" in pipe_tag or "VERS" in pipe_tag
            
            if is_from or is_to:
                # Chercher la position physique associée à ce texte
                cx, cy = None, None
                for el in raw_elements:
                    el_tag = el.get("tag", "").upper()
                    if el_tag and (el_tag in pipe_tag or pipe_tag in el_tag):
                        box = el.get("box", [0,0,0,0])
                        cx = (box[0] + box[2]) / 2
                        cy = (box[1] + box[3]) / 2
                        break
                
                # Fallback sur le centre de la ligne
                if cx is None:
                    cx = (pipe.start_point[0] + pipe.end_point[0]) / 2
                    cy = (pipe.start_point[1] + pipe.end_point[1]) / 2
                
                d_start = math.sqrt((cx - pipe.start_point[0])**2 + (cy - pipe.start_point[1])**2)
                d_end = math.sqrt((cx - pipe.end_point[0])**2 + (cy - pipe.end_point[1])**2)
                
                start_cluster, end_cluster = pipe_node_map[pipe.id]
                
                if is_from:
                    # Le nœud le plus proche de FROM est la source
                    if d_start < d_end:
                        flow_sources[start_cluster] = ("SOURCE", pipe.line_number, 0.98, f"Source oriented by FROM tag: {pipe.line_number}")
                    else:
                        flow_sources[end_cluster] = ("SOURCE", pipe.line_number, 0.98, f"Source oriented by FROM tag (end): {pipe.line_number}")
                elif is_to:
                    # Le nœud le plus proche de TO est le puits (SINK)
                    if d_start < d_end:
                        flow_sources[start_cluster] = ("SINK", pipe.line_number, 0.98, f"Sink oriented by TO tag: {pipe.line_number}")
                    else:
                        flow_sources[end_cluster] = ("SINK", pipe.line_number, 0.98, f"Sink oriented by TO tag (end): {pipe.line_number}")

        # Cas F : Analyse des conduites de Torches (Flare) et Drains
        for pipe in project.pipes:
            pipe_tag = pipe.line_number.upper()
            fluid = pipe.fluid.upper() if pipe.fluid else ""
            
            is_flare_or_drain = "FLARE" in pipe_tag or "DRAIN" in pipe_tag or fluid in ("FL", "D")
            if is_flare_or_drain:
                start_cluster, end_cluster = pipe_node_map[pipe.id]
                deg_start = len(node_to_pipes.get(start_cluster, []))
                deg_end = len(node_to_pipes.get(end_cluster, []))
                
                # Le nœud terminal (degré = 1) est un puits (SINK) vers le collecteur externe
                if deg_start == 1 and deg_end > 1:
                    flow_sources[start_cluster] = ("SINK", pipe.line_number, 0.85, f"Flare/Drain line outlet: {pipe.line_number}")
                elif deg_end == 1 and deg_start > 1:
                    flow_sources[end_cluster] = ("SINK", pipe.line_number, 0.85, f"Flare/Drain line outlet: {pipe.line_number}")

        # Initialisation de la queue du BFS avec toutes les sources confirmées (Pompes, NRV, FROM, Flèches)
        for node_id, (role, s_tag, conf, reason) in flow_sources.items():
            if role == "SOURCE":
                queue.append((node_id, s_tag, conf, reason, True))
                visited_nodes.add(node_id)

        # 4. Inférence par propagation BFS
        while queue:
            curr_node, src_tag, conf, reason, is_root = queue.pop(0)
            
            for pipe_id, role in node_to_pipes.get(curr_node, []):
                if pipe_id in visited_pipes:
                    continue
                    
                visited_pipes.add(pipe_id)
                start_cluster, end_cluster = pipe_node_map[pipe_id]
                
                actual_reason = reason if is_root else f"Propagated BFS from {src_tag}"
                
                if role == "start":
                    pipe_orientations[pipe_id] = ("forward", conf, actual_reason)
                    next_node = end_cluster
                else:
                    pipe_orientations[pipe_id] = ("reverse", conf, actual_reason)
                    next_node = start_cluster
                
                if next_node not in visited_nodes:
                    visited_nodes.add(next_node)
                    if next_node not in flow_sources or flow_sources[next_node][0] != "SINK":
                        queue.append((next_node, src_tag, conf, reason, False))

        # 5. Application des directions calculées ou application de la baseline de secours
        for pipe in project.pipes:
            if pipe.id in pipe_orientations:
                direction, conf, reason = pipe_orientations[pipe.id]
                if direction == "reverse":
                    pipe.start_point, pipe.end_point = pipe.end_point, pipe.start_point
                    pipe.polyline.reverse()
                    logger.info("Pipe %s inversé (BFS propagation).", pipe.line_number)
                pipe.metadata["flow_direction"] = "inferred"
                pipe.metadata["flow_confidence"] = conf
                pipe.metadata["flow_reasons"] = [reason]
            else:
                # Baseline par défaut gauche-droite (fallback local)
                if pipe.start_point[0] > pipe.end_point[0]:
                    pipe.start_point, pipe.end_point = pipe.end_point, pipe.start_point
                    pipe.polyline.reverse()
                    logger.info("Pipe %s orienté par défaut gauche-droite.", pipe.line_number)
                
                pipe.metadata["flow_direction"] = "default"
                pipe.metadata["flow_confidence"] = 0.70
                pipe.metadata["flow_reasons"] = ["Baseline heuristic (left-to-right default)"]

        logger.info("Inférence de flux complétée pour le projet.")
        return project
