"""
Arkan V6 — AI GraphRAG Engine
Ce module implémente le moteur de raisonnement d'IA sur le graphe de procédés.
Il traduit les questions d'ingénierie en requêtes Cypher pour interroger Neo4j,
ou interroge directement le modèle DTIM en mémoire si Neo4j est hors ligne.
"""

import os
import re
import logging
from typing import Dict, Any, List
from dtim_model import DTIMProject, EquipmentEntity, InstrumentEntity, PipeEntity
from mto_engine import MTOEngine
from audit_engine import AuditEngine

logger = logging.getLogger(__name__)

class AIEngine:
    def __init__(self):
        self.uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self.user = os.environ.get("NEO4J_USER", "neo4j")
        self.password = os.environ.get("NEO4J_PASSWORD", "deerflow_oilgas_2025")
        self.database = os.environ.get("NEO4J_DATABASE", "neo4j")
        self.driver = None
        self.connected = False

        try:
            from neo4j import GraphDatabase
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            with self.driver.session(database=self.database) as session:
                session.run("RETURN 1")
            self.connected = True
            logger.info("AI Engine connecté avec succès à Neo4j pour GraphRAG.")
        except Exception as e:
            logger.warning("AI Engine : Neo4j indisponible. Mode sémantique local activé. Erreur: %s", e)
            self.connected = False

    def close(self):
        if self.driver:
            self.driver.close()

    def ask_question(self, question: str, project: DTIMProject) -> Dict[str, Any]:
        """
        Interroge le graphe Neo4j via Cypher (si connecté) ou le DTIM local
        pour répondre à une question technique en langage naturel.
        """
        question_lower = question.lower()
        logger.info("AI question reçue: '%s'", question)

        # 1. GRAPH MODE (Neo4j connected)
        if self.connected and self.driver:
            try:
                cypher_query, params = self._translate_to_cypher(question_lower, project.project_name)
                if cypher_query:
                    logger.info("AI Cypher généré: %s", cypher_query)
                    with self.driver.session(database=self.database) as session:
                        result = session.run(cypher_query, **params)
                        records = [dict(record) for record in result]
                    
                    answer = self._format_cypher_result_to_answer(question, records)
                    return {
                        "question": question,
                        "engine_mode": "Neo4j GraphRAG",
                        "cypher_query": cypher_query,
                        "raw_results": records,
                        "answer": answer
                    }
            except Exception as e:
                logger.error("AI Graph Mode a échoué, repli sur le mode local. Erreur: %s", e)

        # 2. LOCAL FALLBACK MODE (DTIM / Procedural)
        return self._ask_local_dtim(question_lower, project)

    def _translate_to_cypher(self, question: str, project_name: str) -> tuple:
        """
        Traduit des questions types d'ingénieurs en requêtes Cypher.
        """
        # Ex: "quelles vannes sont sur la ligne 301" -> MATCH (p:Pipe {line_number: '301', project_name: $proj})
        match_valves = re.search(r"(vanne|valves?).*ligne\s*([0-9a-zA-Z\-]+)", question)
        if match_valves:
            line_num = match_valves.group(2)
            query = """
            MATCH (p:Pipe {line_number: $line_num, project_name: $project_name})
            MATCH (c:Component:Valve {project_name: $project_name})
            WHERE c.tag CONTAINS $line_num OR c.id CONTAINS $line_num
            RETURN c.tag AS tag, c.type AS type
            """
            return query, {"line_num": line_num, "project_name": project_name}

        # Ex: "quel est le tonnage d'acier"
        if "tonnage" in question or "poids" in question or "acier" in question:
            query = """
            MATCH (p:Pipe {project_name: $project_name})
            RETURN sum(p.weight) as total_weight
            """
            return query, {"project_name": project_name}

        # Ex: "anomalies" or "audit"
        if "anomalie" in question or "audit" in question or "erreur" in question:
            query = """
            MATCH (p:Pipe {project_name: $project_name})
            WHERE p.from_equipment = 'OPEN' AND p.to_equipment = 'OPEN'
            RETURN p.line_number AS isolated_pipe
            """
            return query, {"project_name": project_name}

        return None, {}

    def _format_cypher_result_to_answer(self, question: str, records: List[Dict[str, Any]]) -> str:
        if not records:
            return "Aucun résultat trouvé dans le graphe de procédés Neo4j."

        if "total_weight" in records[0]:
            weight = records[0]["total_weight"] or 0.0
            return f"Le tonnage d'acier total estimé pour ce réseau est de {weight / 1000.0:.2f} tonnes (soit {weight:.1f} kg)."

        if "tag" in records[0]:
            valves_list = [r["tag"] for r in records if r.get("tag")]
            return f"J'ai trouvé les vannes suivantes associées à votre demande : {', '.join(valves_list)}."

        if "isolated_pipe" in records[0]:
            pipes = [r["isolated_pipe"] for r in records if r.get("isolated_pipe")]
            return f"Alerte Audit : Les conduites suivantes sont isolées dans le graphe : {', '.join(pipes)}."

        return f"Résultat du graphe : {str(records)}"

    def _ask_local_dtim(self, question: str, project: DTIMProject) -> Dict[str, Any]:
        """
        Interroge localement les objets DTIM en mémoire (fallback sémantique).
        """
        # 1. Search for valves on a line
        match_valves = re.search(r"(vanne|valves?).*ligne\s*([0-9a-zA-Z\-]+)", question)
        if match_valves:
            line_num = match_valves.group(2)
            found_valves = []
            for comp in project.components:
                if comp.id.startswith("VL-") or "valve" in comp.entity_type.lower():
                    tag = getattr(comp, "tag", "")
                    if line_num in tag or line_num in comp.id:
                        found_valves.append(tag)
            
            valves_str = ", ".join(found_valves) if found_valves else "Aucune"
            return {
                "question": question,
                "engine_mode": "DTIM Semantic Fallback",
                "answer": f"DTIM local : Les vannes suivantes sont localisées sur la ligne {line_num} : {valves_str}."
            }

        # 2. Search for steel weight / MTO summary
        if "tonnage" in question or "poids" in question or "acier" in question:
            mto = MTOEngine(scale_ratio=0.05).calculate_mto(project)
            return {
                "question": question,
                "engine_mode": "DTIM MTO Fallback",
                "answer": f"DTIM local : Le tonnage d'acier total estimé est de {mto['total_steel_tonnage']} tonnes ({mto['total_steel_weight_kg']} kg)."
            }

        # 3. Search for audit rules
        if "anomalie" in question or "audit" in question or "erreur" in question:
            anom = AuditEngine().audit_project(project)
            return {
                "question": question,
                "engine_mode": "DTIM Audit Fallback",
                "answer": f"DTIM local : L'audit a détecté {len(anom)} anomalies de procédé (dont {len([a for a in anom if a['severity'] == 'HIGH'])} alertes de sévérité HIGH)."
            }

        return {
            "question": question,
            "engine_mode": "DTIM Unknown Fallback",
            "answer": "Désolé, je n'ai pas pu faire correspondre votre question à une règle d'audit ou de MTO locale."
        }
