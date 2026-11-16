"""
Arkan V6 — Audit Engine
Ce module applique des règles d'ingénierie et de sécurité sur le DTIM
pour identifier les anomalies de procédés.
"""

import logging
from typing import List, Dict, Any
from dtim_model import DTIMProject, PipeEntity, EquipmentEntity, InstrumentEntity

logger = logging.getLogger(__name__)

class AuditEngine:
    def __init__(self):
        pass

    def audit_project(self, project: DTIMProject) -> List[Dict[str, Any]]:
        """
        Exécute l'audit complet du projet et retourne une liste d'anomalies.
        """
        anomalies = []
        logger.info("Lancement de l'audit de conception sur le projet: %s", project.project_name)

        # 1. Check for isolated and dead-leg pipes
        for pipe in project.pipes:
            # Check connection fields from metadata (populated during tracer run)
            from_eq = pipe.metadata.get("from_equipment", "OPEN") if pipe.metadata else "OPEN"
            to_eq = pipe.metadata.get("to_equipment", "OPEN") if pipe.metadata else "OPEN"

            # Isolated Line: both ends open
            if from_eq == "OPEN" and to_eq == "OPEN":
                anomalies.append({
                    "rule": "Isolated Pipe",
                    "severity": "HIGH",
                    "target_type": "Pipe",
                    "target_id": pipe.line_number,
                    "message": f"La conduite {pipe.line_number} est isolée (From=OPEN, To=OPEN)."
                })

            # Dead-leg: exactly one end open
            elif from_eq == "OPEN" or to_eq == "OPEN":
                anomalies.append({
                    "rule": "Dead-leg Detection",
                    "severity": "MEDIUM",
                    "target_type": "Pipe",
                    "target_id": pipe.line_number,
                    "message": f"La conduite {pipe.line_number} possède un tronçon borgne (stagnant)."
                })

        # 2. Check safety valves (PSV) on high risk fluid lines
        high_risk_fluids = {"HC", "FL", "HP", "OIL", "GAS", "LPG", "NG"}
        
        # Check if there is any PSV component in the project
        psv_tags = {c.tag for c in project.components if hasattr(c, "tag") and "psv" in c.tag.lower()}

        for pipe in project.pipes:
            if pipe.fluid in high_risk_fluids:
                # High risk lines must be protected by a safety device or connection to a PSV loop
                # Basic check: verify if a PSV is referenced in the line list metadata or spec
                is_protected = False
                for p_tag in psv_tags:
                    if p_tag in pipe.line_number:
                        is_protected = True
                        break
                
                # If the line length is significant and no PSV is found
                if not is_protected and len(pipe.polyline) > 5:
                    anomalies.append({
                        "rule": "PSV Safety Check",
                        "severity": "HIGH",
                        "target_type": "Pipe",
                        "target_id": pipe.line_number,
                        "message": f"La conduite à haut risque {pipe.line_number} (fluide={pipe.fluid}) n'a pas de vanne de protection de surpression (PSV) identifiée."
                    })

        # 3. Check for diameter compatibility at junctions
        # If we have TEE nodes, verify that adjacent edges (pipes) have consistent diameters or a Reducer exists
        for node in project.nodes:
            if node.node_type == "TEE":
                # Find all pipes close to this TEE
                adjacent_diameters = set()
                for pipe in project.pipes:
                    start_dist = self._dist(node.position, pipe.start_point)
                    end_dist = self._dist(node.position, pipe.end_point)
                    if start_dist <= 15.0 or end_dist <= 15.0:
                        if pipe.diameter:
                            adjacent_diameters.add(pipe.diameter)
                
                # If we have multiple different diameters meeting at a TEE node without a reducer
                if len(adjacent_diameters) > 1:
                    # Check if a Reducer component is at the same location
                    has_reducer = any(
                        "reducer" in c.equipment_type.lower() and self._dist(node.position, (c.bbox[0], c.bbox[1])) <= 30.0
                        for c in project.components if isinstance(c, EquipmentEntity)
                    )
                    
                    if not has_reducer:
                        anomalies.append({
                            "rule": "Diameter Mismatch at TEE",
                            "severity": "WARNING",
                            "target_type": "Node",
                            "target_id": node.id,
                            "message": f"Incohérence de diamètres ({adjacent_diameters}) à la jonction TEE sans réducteur de diamètre associé."
                        })

        logger.info("Audit complété. %s anomalies détectées.", len(anomalies))
        return anomalies

    def _dist(self, p1, p2) -> float:
        import math
        return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)
