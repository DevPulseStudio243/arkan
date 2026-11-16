"""
Arkan V6 — Neo4j Graph Exporter
Ce module gère la sérialisation et l'exportation du jumeau numérique DTIM
vers la base de données orientée graphes Neo4j.
"""

import os
import math
import logging
from typing import Any, Dict, Optional
from dtim_model import DTIMProject, EquipmentEntity, InstrumentEntity, PipeEntity, Port, DTIMNode, DTIMEdge

logger = logging.getLogger(__name__)

class Neo4jExporter:
    def __init__(self):
        self.uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self.user = os.environ.get("NEO4J_USER", "neo4j")
        self.password = os.environ.get("NEO4J_PASSWORD", "deerflow_oilgas_2025")
        self.database = os.environ.get("NEO4J_DATABASE", "neo4j")
        self.enabled = os.environ.get("NEO4J_ENABLED", "true").lower() == "true"
        self.driver = None
        self.connected = False

        if self.enabled:
            try:
                from neo4j import GraphDatabase
                self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
                # Quick connection test
                with self.driver.session(database=self.database) as session:
                    session.run("RETURN 1")
                self.connected = True
                logger.info("Connecté avec succès au serveur Neo4j (%s)", self.uri)
            except Exception as e:
                logger.warning("Serveur Neo4j indisponible (%s). Mode dégradé local actif. Erreur: %s", self.uri, e)
                self.connected = False
        else:
            logger.info("Exportateur Neo4j désactivé par configuration.")

    def close(self):
        if self.driver:
            self.driver.close()

    def export_project(self, project: DTIMProject) -> bool:
        """
        Exporte le projet DTIM complet dans Neo4j sous forme de nœuds et relations de procédé.
        Si Neo4j est hors ligne, retourne False sans faire planter le pipeline.
        """
        if not self.enabled or not self.connected or not self.driver:
            logger.info("Export Neo4j sauté (mode local ou serveur hors ligne).")
            return False

        try:
            with self.driver.session(database=self.database) as session:
                # 1. Clear previous graph state for this project
                logger.info("Nettoyage du graphe précédent pour le projet: %s", project.project_name)
                session.run(
                    "MATCH (n {project_name: $project_name}) DETACH DELETE n",
                    project_name=project.project_name
                )

                # 2. Export drawings
                for dwg in project.drawings:
                    session.run(
                        """
                        CREATE (d:Drawing {
                            id: $id,
                            name: $name,
                            revision: $revision,
                            scale: $scale,
                            source: $source,
                            project_name: $project_name
                        })
                        """,
                        id=dwg["id"],
                        name=dwg["name"],
                        revision=dwg["revision"],
                        scale=dwg["scale"],
                        source=dwg["source"],
                        project_name=project.project_name
                    )

                # 3. Export components (Equipment, Valves, Instruments)
                for comp in project.components:
                    labels = "Component"
                    if isinstance(comp, InstrumentEntity):
                        labels = "Component:Instrument"
                    elif isinstance(comp, EquipmentEntity):
                        t_lower = getattr(comp, "equipment_type", "").lower()
                        # Robust check for valves by type string or original ID formatting
                        if "valve" in t_lower or "vanne" in t_lower or "clapet" in t_lower or comp.id.startswith("VL-"):
                            labels = "Component:Valve"
                        else:
                            labels = "Component:Equipment"

                    session.run(
                        f"""
                        CREATE (c:{labels} {{
                            id: $id,
                            tag: $tag,
                            type: $type,
                            bbox: $bbox,
                            source: $source,
                            confidence: $confidence,
                            project_name: $project_name
                        }})
                        """,
                        id=comp.id,
                        tag=getattr(comp, "tag", ""),
                        type=comp.entity_type if not hasattr(comp, "equipment_type") else getattr(comp, "equipment_type"),
                        bbox=getattr(comp, "bbox", []),
                        source=comp.source,
                        confidence=comp.confidence,
                        project_name=project.project_name
                    )

                    # Export Ports for this component
                    if hasattr(comp, "ports"):
                        for port in comp.ports:
                            session.run(
                                """
                                MATCH (c:Component {id: $comp_id, project_name: $project_name})
                                CREATE (p:Port {
                                    id: $id,
                                    name: $name,
                                    type: $type,
                                    position: $position,
                                    project_name: $project_name
                                })
                                CREATE (c)-[:HAS_PORT]->(p)
                                """,
                                comp_id=comp.id,
                                id=port.id,
                                name=port.name,
                                type=port.port_type,
                                position=port.position,
                                project_name=project.project_name
                            )

                # 4. Export pipes
                from mto_engine import PIPING_WEIGHT_MAP
                for pipe in project.pipes:
                    # Calculate weight for Neo4j property
                    pixel_len = 0.0
                    for k in range(len(pipe.polyline) - 1):
                        p1 = pipe.polyline[k]
                        p2 = pipe.polyline[k+1]
                        pixel_len += math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)
                    real_len = pixel_len * 0.05
                    dia_str = str(pipe.diameter).replace('"', '').strip()
                    unit_w = PIPING_WEIGHT_MAP.get(dia_str, 20.0)
                    weight_kg = real_len * unit_w

                    session.run(
                        """
                        CREATE (p:Pipe {
                            id: $id,
                            line_number: $line_number,
                            diameter: $diameter,
                            spec: $spec,
                            fluid: $fluid,
                            service: $service,
                            source: $source,
                            weight: $weight,
                            from_equipment: $from_eq,
                            to_equipment: $to_eq,
                            project_name: $project_name
                        })
                        """,
                        id=pipe.id,
                        line_number=pipe.line_number,
                        diameter=pipe.diameter,
                        spec=pipe.spec,
                        fluid=pipe.fluid,
                        service=pipe.service,
                        source=pipe.source,
                        weight=weight_kg,
                        from_eq=pipe.metadata.get("from_equipment", "OPEN") if pipe.metadata else "OPEN",
                        to_eq=pipe.metadata.get("to_equipment", "OPEN") if pipe.metadata else "OPEN",
                        project_name=project.project_name
                    )

                # 5. Export nodes (TEE, CROSS, nozzles)
                for node in project.nodes:
                    session.run(
                        """
                        CREATE (n:Node {
                            id: $id,
                            type: $type,
                            position: $position,
                            confidence: $confidence,
                            project_name: $project_name
                        })
                        """,
                        id=node.id,
                        type=node.node_type,
                        position=node.position,
                        confidence=node.confidence,
                        project_name=project.project_name
                    )

                # 6. Export topological relations and process flow connectivity edges (Bug n°2 Fix)
                logger.info("Exportation des arêtes de connectivité de procédé dans Neo4j...")
                for pipe in project.pipes:
                    from_eq = pipe.metadata.get("from_equipment", "OPEN") if pipe.metadata else "OPEN"
                    to_eq = pipe.metadata.get("to_equipment", "OPEN") if pipe.metadata else "OPEN"
                    from_port = pipe.metadata.get("from_port", "") if pipe.metadata else ""
                    to_port = pipe.metadata.get("to_port", "") if pipe.metadata else ""

                    # Connection from upstream equipment to Pipe
                    if from_eq and from_eq != "OPEN":
                        # Standard link Component -> Pipe
                        session.run(
                            """
                            MATCH (c:Component {tag: $from_eq, project_name: $project_name})
                            MATCH (p:Pipe {id: $pipe_id, project_name: $project_name})
                            MERGE (c)-[:CONNECTED_TO]->(p)
                            MERGE (c)-[:FLOWS_TO]->(p)
                            """,
                            from_eq=from_eq,
                            pipe_id=pipe.id,
                            project_name=project.project_name
                        )

                        # Detailed link Port -> Pipe
                        if from_port:
                            port_id = f"EQ-{from_eq}.{from_port}"
                            session.run(
                                """
                                MATCH (pt:Port {id: $port_id, project_name: $project_name})
                                MATCH (p:Pipe {id: $pipe_id, project_name: $project_name})
                                MERGE (pt)-[:CONNECTED_TO]->(p)
                                MERGE (pt)-[:FLOWS_TO]->(p)
                                """,
                                port_id=port_id,
                                pipe_id=pipe.id,
                                project_name=project.project_name
                            )

                    # Connection from Pipe to downstream equipment
                    if to_eq and to_eq != "OPEN":
                        # Standard link Pipe -> Component
                        session.run(
                            """
                            MATCH (p:Pipe {id: $pipe_id, project_name: $project_name})
                            MATCH (c:Component {tag: $to_eq, project_name: $project_name})
                            MERGE (p)-[:CONNECTED_TO]->(c)
                            MERGE (p)-[:FLOWS_TO]->(c)
                            """,
                            to_eq=to_eq,
                            pipe_id=pipe.id,
                            project_name=project.project_name
                        )

                        # Detailed link Pipe -> Port
                        if to_port:
                            port_id = f"EQ-{to_eq}.{to_port}"
                            session.run(
                                """
                                MATCH (p:Pipe {id: $pipe_id, project_name: $project_name})
                                MATCH (pt:Port {id: $port_id, project_name: $project_name})
                                MERGE (p)-[:CONNECTED_TO]->(pt)
                                MERGE (p)-[:FLOWS_TO]->(pt)
                                """,
                                port_id=port_id,
                                pipe_id=pipe.id,
                                project_name=project.project_name
                            )

                logger.info("Exportation Neo4j du projet %s complétée avec arêtes de connectivité.", project.project_name)
                return True

        except Exception as e:
            logger.error("Erreur lors de l'exportation Neo4j: %s", e)
            return False
