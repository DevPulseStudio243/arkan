"""
arh_knowledge_graph.py
======================
Gestionnaire du Knowledge Graph Réglementaire ARH.

Modélise la hiérarchie complète et les relations de traçabilité ARH :
  Projet -> Unité -> Équipement -> Document -> Section -> Norme/Décret -> Article -> Essai -> Inspection -> Contrôle -> Observation -> Commentaire -> Correction -> Validation
"""

from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional

DB_PATH = Path("arh_knowledge_graph.db")


class ARHKnowledgeGraph:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=60.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=60000")
        except Exception:
            pass
        return conn

    def _init_db(self):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS arh_nodes (
                        id TEXT PRIMARY KEY,
                        node_type TEXT NOT NULL,
                        name TEXT NOT NULL,
                        dossier_id TEXT,
                        project_id TEXT,
                        properties_json TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS arh_edges (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_id TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        relation_type TEXT NOT NULL,
                        properties_json TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(source_id) REFERENCES arh_nodes(id),
                        FOREIGN KEY(target_id) REFERENCES arh_nodes(id)
                    )
                """)
                conn.commit()
        except Exception as e:
            pass

    def add_node(
        self,
        node_id: str,
        node_type: str,
        name: str,
        dossier_id: str = "",
        project_id: str = "",
        properties: Dict[str, Any] = None
    ) -> str:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO arh_nodes (id, node_type, name, dossier_id, project_id, properties_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (node_id, node_type, name, dossier_id, project_id, json.dumps(properties or {})))
                conn.commit()
        except Exception:
            pass
        return node_id

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        properties: Dict[str, Any] = None
    ):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO arh_edges (source_id, target_id, relation_type, properties_json)
                    VALUES (?, ?, ?, ?)
                """, (source_id, target_id, relation_type, json.dumps(properties or {})))
                conn.commit()
        except Exception:
            pass

    def build_equipment_hierarchy(
        self,
        project_name: str,
        unit_name: str,
        equipment_tag: str,
        equipment_type: str,
        dossier_id: str
    ) -> str:
        """
        Construit l'arborescence initiale : Projet -> Unité -> Équipement
        """
        proj_id = f"PROJ_{project_name.upper().replace(' ', '_')}"
        unit_id = f"UNIT_{unit_name.upper().replace(' ', '_')}"
        eq_id = f"EQ_{equipment_tag.upper().replace(' ', '_')}"

        self.add_node(proj_id, "Projet", project_name, dossier_id, proj_id)
        self.add_node(unit_id, "Unité", unit_name, dossier_id, proj_id)
        self.add_node(eq_id, "Équipement", equipment_tag, dossier_id, proj_id, {"equipment_type": equipment_type})

        self.add_edge(proj_id, unit_id, "CONTIENT_UNITE")
        self.add_edge(unit_id, eq_id, "CONTIENT_EQUIPEMENT")

        return eq_id

    def get_graph_for_dossier(self, dossier_id: str) -> Dict[str, Any]:
        """
        Récupère l'intégralité du graphe sous forme de nœuds et d'arêtes pour la visualisation.
        """
        nodes = []
        edges = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, node_type, name, dossier_id, project_id, properties_json FROM arh_nodes WHERE dossier_id = ?", (dossier_id,))
            for row in cursor.fetchall():
                nodes.append({
                    "id": row[0],
                    "type": row[1],
                    "name": row[2],
                    "dossier_id": row[3],
                    "project_id": row[4],
                    "properties": json.loads(row[5] or "{}")
                })

            node_ids = {n["id"] for n in nodes}
            cursor.execute("SELECT source_id, target_id, relation_type, properties_json FROM arh_edges")
            for row in cursor.fetchall():
                if row[0] in node_ids and row[1] in node_ids:
                    edges.append({
                        "source": row[0],
                        "target": row[1],
                        "relation": row[2],
                        "properties": json.loads(row[3] or "{}")
                    })
        except Exception:
            pass

        return {"nodes": nodes, "edges": edges}
