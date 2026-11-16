# arh_knowledge_graph.py

- ARHKnowledgeGraph · class · L19-L160 — class ARHKnowledgeGraph
- __init__ · method · L20-L22 — def __init__(self, db_path: Path = DB_PATH)
- _get_connection · method · L24-L31 — def _get_connection(self)
- _init_db · method · L33-L62 — def _init_db(self)
- add_node · method · L64-L83 — def add_node( self, node_id: str, node_type: str, name: str, dossier_id: str = "", project_id: str = "", properties: Dict[str, Any] = None ) -> str
- add_edge · method · L85-L101 — def add_edge( self, source_id: str, target_id: str, relation_type: str, properties: Dict[str, Any] = None )
- build_equipment_hierarchy · method · L103-L125 — def build_equipment_hierarchy( self, project_name: str, unit_name: str, equipment_tag: str, equipment_type: str, dossier_id: str ) -> str
- get_graph_for_dossier · method · L127-L160 — def get_graph_for_dossier(self, dossier_id: str) -> Dict[str, Any]
