"""
DeerFlow Lite - Knowledge Graph v3.0
Migration Neo4j : graphe de connaissances Oil & Gas.

Architecture :
- Neo4jKnowledgeGraph : driver neo4j natif, transactions ACID, index Cypher.
- Fallback JSON automatique si Neo4j indisponible (rétrocompatibilité totale).
- Thread-safe : le driver Neo4j gère nativement la concurrence (pool interne).
- Schéma : Equipement, Document, Norme, Materiau, Propriete, Projet, Feedback.
"""
import json
import logging
import os
import re
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# --- Patterns extraction entités ---
_EQUIPMENT_TAG_RE = re.compile(r"\b([A-Z]{1,4}-\d{2,5}[A-Z]?(?:/[A-Z])?)\b")
_NORM_RE = re.compile(
    r"\b((?:API|ASME|ISO|NFPA|ATEX|IEC|EN|NF|DNV|NACE|ASTM|AWS)"
    r"[\s\-]?[A-Z0-9\.\-]{1,20})\b"
)
_MATERIAL_RE = re.compile(
    r"\b((?:ASTM\s?)?[A-Z]\d{2,4}(?:\s?Gr\.?\s?[A-Z0-9]+)?|"
    r"(?:SS|CS|AS)\s?\d{3}[A-Z]?|"
    r"(?:Inconel|Monel|Hastelloy|Duplex|Super\s?Duplex|Inox)\s?\d*|"
    r"(?:acier\s+(?:carbone|inoxydable|allie))|"
    r"(?:carbon\s+steel|stainless\s+steel|alloy\s+steel))\b",
    re.IGNORECASE,
)

try:
    from config import (
        NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE,
        NEO4J_ENABLED, KNOWLEDGE_GRAPH_PATH,
    )
except ImportError:
    NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "deerflow_oilgas_2025")
    NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
    NEO4J_ENABLED = os.environ.get("NEO4J_ENABLED", "true").lower() == "true"
    KNOWLEDGE_GRAPH_PATH = "knowledge_graph.json"


# ===========================================================================
#  Neo4jKnowledgeGraph — driver natif
# ===========================================================================

class Neo4jKnowledgeGraph:
    """
    Graphe de connaissances Neo4j pour DeerFlow Lite Oil & Gas.

    Schéma des nœuds :
      (:Equipement {tag, type, description, source})
      (:Document   {nom, chemin, discipline, date_indexation})
      (:Norme      {code, organisme, titre})
      (:Materiau   {designation, specification})
      (:Propriete  {valeur, unite, type_prop})
      (:Projet     {nom, site, client, phase})
      (:Feedback   {question, rating, grounding_ratio, date})

    Le driver Neo4j est thread-safe par nature (pool de connexions interne).
    """

    def __init__(
        self,
        uri: str = NEO4J_URI,
        user: str = NEO4J_USER,
        password: str = NEO4J_PASSWORD,
        database: str = NEO4J_DATABASE,
    ):
        self._uri = uri
        self._user = user
        self._password = password
        self._database = database
        self._driver = None
        self._available = False
        self._connect()

    # ------------------------------------------------------------------
    # Connexion
    # ------------------------------------------------------------------

    def _connect(self):
        """Tente de se connecter à Neo4j. Ne lève pas d'exception."""
        if not NEO4J_ENABLED:
            logger.info("Neo4j désactivé (NEO4J_ENABLED=false). Mode fallback JSON.")
            return
        try:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(
                self._uri,
                auth=(self._user, self._password),
            )
            # Vérification de la connexion
            with self._driver.session(database=self._database) as session:
                session.run("RETURN 1")
            self._available = True
            logger.info("Neo4j connecté : %s (base: %s)", self._uri, self._database)
        except Exception as e:
            self._available = False
            self._driver = None
            logger.warning("Neo4j non disponible (%s). Fallback JSON actif.", e)

    def disponible(self) -> bool:
        """Retourne True si Neo4j est connecté et opérationnel."""
        return self._available and self._driver is not None

    def close(self):
        """Ferme le driver Neo4j proprement."""
        if self._driver:
            try:
                self._driver.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Initialisation du schéma (contraintes + index)
    # ------------------------------------------------------------------

    def initialiser_schema(self):
        """Crée les contraintes d'unicité et les index de performance."""
        if not self.disponible():
            return
        contraintes = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Equipement) REQUIRE e.tag IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document)   REQUIRE d.nom IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Norme)      REQUIRE n.code IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Projet)     REQUIRE p.nom IS UNIQUE",
        ]
        index_cypher = [
            "CREATE INDEX IF NOT EXISTS FOR (e:Equipement) ON (e.tag)",
            "CREATE INDEX IF NOT EXISTS FOR (e:Equipement) ON (e.type)",
            "CREATE INDEX IF NOT EXISTS FOR (d:Document)   ON (d.discipline)",
        ]
        with self._driver.session(database=self._database) as session:
            for cypher in contraintes + index_cypher:
                try:
                    session.run(cypher)
                except Exception as e:
                    logger.warning("Schéma: %s → %s", cypher[:60], e)
        logger.info("Schéma Neo4j initialisé (contraintes + index).")

    # ------------------------------------------------------------------
    # Ajout d'entités
    # ------------------------------------------------------------------

    def _normaliser_tag(self, tag: str) -> str:
        """Résolution d'entités: normalise les tags (ex: 'P 101', 'Pump-101' -> 'P-101')."""
        import re
        t = tag.upper().strip()
        t = re.sub(r'^(PUMP|POMPE|COMPRESSEUR|COMPRESSOR|VANNE|VALVE)[\s\-]*', '', t)
        t = re.sub(r'([A-Z]{1,4})[\s_]+(\d{2,5})', r'\1-\2', t)
        return t

    def ajouter_equipement(self, tag: str, description: str, source: str,
                           type_eq: str = "Inconnu", system_parent: str = "") -> bool:
        """Crée ou met à jour un nœud :Equipement avec sous-label dynamique et hiérarchie."""
        if not self.disponible():
            return False
            
        tag_norm = self._normaliser_tag(tag)
        
        # Déduction du sous-label (Ontologie Neo4j)
        sub_label = ""
        type_lower = type_eq.lower()
        if "pomp" in type_lower or "pump" in type_lower: sub_label = ":Pompe"
        elif "compress" in type_lower: sub_label = ":Compresseur"
        elif "vanne" in type_lower or "valve" in type_lower: sub_label = ":Vanne"
        elif "sep" in type_lower: sub_label = ":Separateur"
        elif "echang" in type_lower or "exchang" in type_lower: sub_label = ":Echangeur"
        elif "cuve" in type_lower or "tank" in type_lower: sub_label = ":Cuve"

        cypher = f"""
        MERGE (e:Equipement{sub_label} {{tag: $tag}})
        ON CREATE SET e.description = $desc, e.type = $type_eq,
                      e.source = $source, e.created = datetime()
        ON MATCH  SET e.description = $desc, e.updated = datetime()
        """
        try:
            with self._driver.session(database=self._database) as session:
                session.run(cypher, tag=tag_norm, desc=description,
                            type_eq=type_eq, source=source)
                            
            if system_parent:
                sys_norm = self._normaliser_tag(system_parent)
                cypher_sys = f"""
                MERGE (s:Systeme {{nom: $sys_nom}})
                WITH s
                MATCH (e:Equipement {{tag: $tag}})
                MERGE (e)-[:FAIT_PARTIE_DE]->(s)
                """
                with self._driver.session(database=self._database) as session:
                    session.run(cypher_sys, sys_nom=sys_norm, tag=tag_norm)
                    
            return True
        except Exception as e:
            logger.error("ajouter_equipement(%s): %s", tag, e)
            return False

    def ajouter_propriete(self, tag: str, relation: str, valeur: str,
                          unite: str, source: str) -> bool:
        """
        Crée un nœud :Propriete et la relation depuis l'équipement.
        relation: 'A_PRESSION' | 'A_TEMPERATURE' | 'A_DEBIT'
        """
        if not self.disponible():
            return False
        cypher = f"""
        MATCH (e:Equipement {{tag: $tag}})
        CREATE (p:Propriete {{valeur: $valeur, unite: $unite,
                              type_prop: $type_prop, source: $source,
                              created: datetime()}})
        MERGE (e)-[:{relation}]->(p)
        """
        try:
            with self._driver.session(database=self._database) as session:
                session.run(cypher, tag=tag.upper(), valeur=valeur,
                            unite=unite, type_prop=relation, source=source)
            return True
        except Exception as e:
            logger.error("ajouter_propriete(%s, %s): %s", tag, relation, e)
            return False

    def ajouter_conformite(self, tag: str, code_norme: str, source: str) -> bool:
        """Crée ou met à jour un nœud :Norme et la relation CONFORME_A."""
        if not self.disponible():
            return False
        cypher = """
        MERGE (n:Norme {code: $code})
        ON CREATE SET n.source = $source, n.created = datetime()
        WITH n
        MATCH (e:Equipement {tag: $tag})
        MERGE (e)-[:CONFORME_A]->(n)
        """
        try:
            with self._driver.session(database=self._database) as session:
                session.run(cypher, code=code_norme, tag=tag.upper(), source=source)
            return True
        except Exception as e:
            logger.error("ajouter_conformite(%s, %s): %s", tag, code_norme, e)
            return False

    def ajouter_connexion(self, tag_a: str, tag_b: str, relation: str, source: str) -> bool:
        """Crée une relation dynamique (ex: CONNECTE_A, ALIMENTE) entre deux équipements."""
        if not self.disponible() or not tag_a or not tag_b:
            return False
        # Sanitize relation name for Cypher
        import re
        safe_rel = re.sub(r'[^A-Z0-9_]', '_', relation.upper().strip())
        if not safe_rel:
            safe_rel = "CONNECTE_A"
            
        cypher = f"""
        MERGE (a:Equipement {{tag: $tag_a}})
        MERGE (b:Equipement {{tag: $tag_b}})
        MERGE (a)-[r:{safe_rel}]->(b)
        ON CREATE SET r.source = $source, r.created = datetime()
        """
        try:
            with self._driver.session(database=self._database) as session:
                session.run(cypher, tag_a=tag_a.upper(), tag_b=tag_b.upper(), source=source)
            return True
        except Exception as e:
            logger.error("ajouter_connexion(%s, %s, %s): %s", tag_a, tag_b, safe_rel, e)
            return False

    def ajouter_document(self, nom: str, chemin: str = "",
                         discipline: str = "", tags_mentionnes: list = None) -> bool:
        """Crée ou met à jour un nœud :Document avec ses équipements mentionnés."""
        if not self.disponible():
            return False
        cypher_doc = """
        MERGE (d:Document {nom: $nom})
        ON CREATE SET d.chemin = $chemin, d.discipline = $discipline,
                      d.date_indexation = datetime()
        ON MATCH  SET d.discipline = $discipline, d.updated = datetime()
        """
        try:
            with self._driver.session(database=self._database) as session:
                session.run(cypher_doc, nom=nom, chemin=chemin, discipline=discipline)
                if tags_mentionnes:
                    for tag in tags_mentionnes:
                        cypher_rel = """
                        MATCH (d:Document {nom: $nom})
                        MERGE (e:Equipement {tag: $tag})
                        MERGE (d)-[:MENTIONNE]->(e)
                        """
                        session.run(cypher_rel, nom=nom, tag=tag.upper())
            return True
        except Exception as e:
            logger.error("ajouter_document(%s): %s", nom, e)
            return False

    def ajouter_projet(self, nom: str, site: str = "", client: str = "",
                       phase: str = "") -> bool:
        """Crée ou met à jour un nœud :Projet."""
        if not self.disponible():
            return False
        cypher = """
        MERGE (p:Projet {nom: $nom})
        ON CREATE SET p.site = $site, p.client = $client, p.phase = $phase,
                      p.created = datetime()
        ON MATCH  SET p.updated = datetime()
        """
        try:
            with self._driver.session(database=self._database) as session:
                session.run(cypher, nom=nom, site=site, client=client, phase=phase)
            return True
        except Exception as e:
            logger.error("ajouter_projet(%s): %s", nom, e)
            return False

    def ajouter_feedback(self, question: str, rating: str,
                         grounding_ratio: float = 0.0) -> bool:
        """Enregistre un feedback comme nœud :Feedback dans le graphe."""
        if not self.disponible():
            return False
        cypher = """
        CREATE (f:Feedback {question: $question, rating: $rating,
                            grounding_ratio: $ratio, date: datetime()})
        """
        try:
            with self._driver.session(database=self._database) as session:
                session.run(cypher, question=question, rating=rating,
                            ratio=grounding_ratio)
            return True
        except Exception as e:
            logger.error("ajouter_feedback: %s", e)
            return False

    # ------------------------------------------------------------------
    # Requêtes
    # ------------------------------------------------------------------

    def chercher_equipement(self, tag: str) -> dict:
        """
        Retourne toutes les données d'un équipement (tag, pressions, normes, docs).
        """
        if not self.disponible():
            return {}
        cypher = """
        MATCH (e:Equipement {tag: $tag})
        OPTIONAL MATCH (e)-[:A_PRESSION]->(p:Propriete)
        OPTIONAL MATCH (e)-[:A_TEMPERATURE]->(t:Propriete)
        OPTIONAL MATCH (e)-[:CONFORME_A]->(n:Norme)
        OPTIONAL MATCH (d:Document)-[:MENTIONNE]->(e)
        RETURN e,
               collect(DISTINCT p.valeur + ' ' + coalesce(p.unite,'')) AS pressions,
               collect(DISTINCT t.valeur + ' ' + coalesce(t.unite,'')) AS temperatures,
               collect(DISTINCT n.code) AS normes,
               collect(DISTINCT d.nom)  AS documents
        """
        try:
            with self._driver.session(database=self._database) as session:
                record = session.run(cypher, tag=tag.upper()).single()
                if not record:
                    return {}
                e = record["e"]
                return {
                    "tag": e.get("tag", tag),
                    "description": e.get("description", ""),
                    "type": e.get("type", ""),
                    "pressions": [v for v in record["pressions"] if v.strip()],
                    "temperatures": [v for v in record["temperatures"] if v.strip()],
                    "normes": record["normes"],
                    "documents": record["documents"],
                }
        except Exception as e:
            logger.error("chercher_equipement(%s): %s", tag, e)
            return {}

    def equipements_projet(self, nom_projet: str) -> list:
        """Retourne tous les équipements d'un projet."""
        if not self.disponible():
            return []
        cypher = """
        MATCH (eq:Equipement)-[:FAIT_PARTIE_DE]->(p:Projet {nom: $nom})
        RETURN eq.tag AS tag, eq.type AS type, eq.description AS description
        ORDER BY eq.tag
        """
        try:
            with self._driver.session(database=self._database) as session:
                return [dict(r) for r in session.run(cypher, nom=nom_projet)]
        except Exception as e:
            logger.error("equipements_projet(%s): %s", nom_projet, e)
            return []

    def chemin_equipements(self, tag_a: str, tag_b: str, max_sauts: int = 6) -> list:
        """Retourne le chemin le plus court entre deux équipements (max_sauts)."""
        if not self.disponible():
            return []
        cypher = """
        MATCH path = shortestPath(
          (a:Equipement {tag: $tag_a})-[*..%d]-(b:Equipement {tag: $tag_b})
        )
        RETURN [n IN nodes(path) | coalesce(n.tag, n.nom, n.code, '')] AS chemin
        """ % max_sauts
        try:
            with self._driver.session(database=self._database) as session:
                result = session.run(cypher, tag_a=tag_a.upper(), tag_b=tag_b.upper())
                record = result.single()
                return record["chemin"] if record else []
        except Exception as e:
            logger.error("chemin_equipements(%s→%s): %s", tag_a, tag_b, e)
            return []

    def analyser_impact(self, tag: str, profondeur: int = 2) -> dict:
        """
        Analyse d'impact: trouve tous les équipements dépendants et les normes affectées
        si l'équipement spécifié tombe en panne ou subit une modification.
        """
        if not self.disponible():
            return {"error": "Neo4j non disponible"}
        
        # Trouver les dépendances (on suppose des relations génériques ou on explore tout ce qui est connecté)
        # Pour être plus robuste sans schéma strict de flux, on cherche tous les voisins jusqu'à `profondeur` sauts.
        cypher = """
        MATCH (start:Equipement {tag: $tag})
        CALL apoc.path.subgraphNodes(start, {
            maxLevel: $profondeur,
            labelFilter: "+Equipement"
        }) YIELD node
        WHERE node <> start
        RETURN collect(DISTINCT node.tag) AS impacts
        """
        
        # Fallback si APOC n'est pas dispo
        cypher_fallback = """
        MATCH (start:Equipement {tag: $tag})-[*1..%d]-(node:Equipement)
        RETURN collect(DISTINCT node.tag) AS impacts
        """ % profondeur
        
        try:
            with self._driver.session(database=self._database) as session:
                try:
                    result = session.run(cypher, tag=tag.upper(), profondeur=profondeur)
                except Exception:
                    # APOC missing, fallback
                    result = session.run(cypher_fallback, tag=tag.upper())
                    
                record = result.single()
                impacts = record["impacts"] if record else []
                
                # Chercher aussi les normes
                cypher_normes = """
                MATCH (start:Equipement {tag: $tag})-[:CONFORME_A]->(n:Norme)
                RETURN collect(DISTINCT n.code) AS normes
                """
                normes = session.run(cypher_normes, tag=tag.upper()).single()["normes"]
                
                return {
                    "tag": tag.upper(),
                    "equipements_impactes": impacts,
                    "normes_concernees": normes
                }
        except Exception as e:
            logger.error("analyser_impact(%s): %s", tag, e)
            return {"error": str(e)}

    def equipements_sans_pression(self) -> list:
        """Retourne les équipements sans propriété de pression (données manquantes)."""
        if not self.disponible():
            return []
        cypher = """
        MATCH (e:Equipement)
        WHERE NOT (e)-[:A_PRESSION]->()
        RETURN e.tag AS tag ORDER BY e.tag
        """
        try:
            with self._driver.session(database=self._database) as session:
                return [r["tag"] for r in session.run(cypher)]
        except Exception as e:
            logger.error("equipements_sans_pression: %s", e)
            return []

    def build_context(self, question: str, timeout_s: float = 2.0) -> str:
        """
        Construit un contexte Neo4j enrichi pour le pipeline RAG.
        Timeout intégré pour ne pas bloquer le pipeline.
        """
        if not self.disponible():
            return ""
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(self._build_context_internal, question)
            try:
                return future.result(timeout=timeout_s)
            except concurrent.futures.TimeoutError:
                logger.warning("build_context Neo4j timeout (%ss)", timeout_s)
                return ""
            except Exception as e:
                logger.warning("build_context Neo4j: %s", e)
                return ""

    def _build_context_internal(self, question: str) -> str:
        """Construction interne du contexte enrichi (appelé avec timeout)."""
        tags = _EQUIPMENT_TAG_RE.findall(question.upper())
        parts = []

        for tag in tags[:5]:
            info = self.chercher_equipement(tag)
            if not info:
                continue
            lines = [f"[KNOWLEDGE GRAPH] Équipement {tag}:"]
            if info.get("description"):
                lines.append(f"  Description: {info['description']}")
            if info.get("pressions"):
                lines.append(f"  Pression(s): {', '.join(info['pressions'])}")
            if info.get("temperatures"):
                lines.append(f"  Température(s): {', '.join(info['temperatures'])}")
            if info.get("normes"):
                lines.append(f"  Normes applicables: {', '.join(info['normes'][:5])}")
            if info.get("documents"):
                lines.append(f"  Sources: {', '.join(info['documents'][:3])}")

            # ── Connexions P&ID (nouvelles relations GraphRAG) ──
            try:
                cypher_conn = """
                MATCH (e:Equipement {tag: $tag})-[r]->(b:Equipement)
                WHERE type(r) IN ['CONNECTE_A','ALIMENTE','ALIMENTE_PAR','REFOULE_VERS','ASPIRE_DE','BYPASS_DE']
                RETURN type(r) AS rel, b.tag AS target LIMIT 10
                UNION
                MATCH (a:Equipement)-[r]->(e:Equipement {tag: $tag})
                WHERE type(r) IN ['CONNECTE_A','ALIMENTE','ALIMENTE_PAR','REFOULE_VERS','ASPIRE_DE','BYPASS_DE']
                RETURN type(r) AS rel, a.tag AS target LIMIT 10
                """
                with self._driver.session(database=self._database) as session:
                    conns = list(session.run(cypher_conn, tag=tag.upper()))
                if conns:
                    conn_strs = [f"{c['rel']} {c['target']}" for c in conns]
                    lines.append(f"  Connexions P&ID: {', '.join(conn_strs)}")
            except Exception:
                pass

            # ── Propriétés techniques supplémentaires ──
            try:
                cypher_props = """
                MATCH (e:Equipement {tag: $tag})-[r:A_DEBIT]->(p:Propriete)
                RETURN 'Débit' AS prop, p.valeur AS val, p.unite AS unite
                UNION
                MATCH (e:Equipement {tag: $tag})-[r:A_PUISSANCE]->(p:Propriete)
                RETURN 'Puissance' AS prop, p.valeur AS val, p.unite AS unite
                """
                with self._driver.session(database=self._database) as session:
                    props = list(session.run(cypher_props, tag=tag.upper()))
                for prop in props:
                    lines.append(f"  {prop['prop']}: {prop['val']} {prop['unite'] or ''}")
            except Exception:
                pass

            parts.append("\n".join(lines))

        return "\n\n".join(parts) if parts else ""

    def get_stats(self) -> dict:
        """Retourne les statistiques du graphe Neo4j."""
        if not self.disponible():
            return {"disponible": False}
        cypher = """
        MATCH (n) RETURN labels(n)[0] AS label, count(*) AS cnt
        """
        try:
            with self._driver.session(database=self._database) as session:
                stats = {r["label"]: r["cnt"] for r in session.run(cypher)}
            stats["disponible"] = True
            return stats
        except Exception as e:
            logger.error("get_stats: %s", e)
            return {"disponible": False, "error": str(e)}

    def add_document_to_graph(self, source: str, text: str) -> None:
        """
        Extrait les entités d'un texte et les insère dans Neo4j.
        Compatible avec l'interface de l'ancienne version JSON.
        """
        if not self.disponible():
            # Fallback vers JSON
            _add_document_to_graph_json(source, text)
            return
        tags = list(dict.fromkeys(_EQUIPMENT_TAG_RE.findall(text)))
        norms = list(dict.fromkeys(_NORM_RE.findall(text)))
        nom_doc = os.path.basename(source)

        tags_upper = [t.upper() for t in tags]
        self.ajouter_document(nom_doc, chemin=source, tags_mentionnes=tags_upper)

        for tag in tags_upper:
            self.ajouter_equipement(tag, "", nom_doc)

        for norm in norms:
            for tag in tags_upper:
                self.ajouter_conformite(tag, norm.strip(), nom_doc)

        logger.info("add_document_to_graph: %s → %d équipements, %d normes",
                    nom_doc, len(tags_upper), len(norms))

    def extraire_entites_llm(self, text: str) -> dict:
        """Utilise le LLM pour extraire des entités et relations complexes."""
        try:
            import httpx
            import os
            
            OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
            # Force localhost if it's 'http://ollama:11434' and we are running outside docker
            if "ollama:11434" in OLLAMA_BASE_URL:
                OLLAMA_BASE_URL = "http://127.0.0.1:11434"
                
            LLM_MODEL = os.environ.get("ARKAN_LLM_MODEL", os.environ.get("DEERFLOW_LLM_MODEL", "qwen2.5:14b"))
            
            prompt = f"""Tu es un expert en ingénierie Oil & Gas. 
Analyse le texte suivant et extrais les entités et relations sous format JSON STRICTEMENT.
Ne réponds que par le bloc JSON, sans aucun autre texte.
Utilise exactement cette structure:
{{
  "equipments": [{{"tag": "P-101A", "type": "pompe", "description": "Pompe centrifuge d'injection", "system": "Unite_Separation"}}],
  "properties": [{{"tag": "P-101A", "relation": "A_PRESSION", "valeur": "28", "unite": "barg"}}],
  "connections": [{{"source": "P-101A", "target": "V-200", "relation": "REFOULE_VERS"}}],
  "norms": [{{"tag": "P-101A", "norm": "API 610"}}]
}}
Instructions importantes :
1. Pour "connections.relation", utilise des termes directionnels comme: REFOULE_VERS, ASPIRE_DE, ALIMENTE, BYPASS.
2. Pour "equipments.system", indique le système parent ou l'unité si mentionné.
Si rien n'est trouvé, renvoie des listes vides.

Texte:
{text[:3000]}
"""
            r = httpx.post(f"{OLLAMA_BASE_URL}/api/chat", json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": 1024}
            }, timeout=300)  # 300s : qwen2.5:14b peut etre lent sur RTX 3050
            
            if r.status_code == 200:
                content = r.json().get("message", {}).get("content", "")
                import re
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if match:
                    import json
                    return json.loads(match.group(0))
        except Exception as e:
            logger.error("Erreur extraire_entites_llm: %s", e)
        return {}

    def enrichir_graphe_depuis_llm(self, source: str, text: str,
                                   prefetched_data: dict = None) -> bool:
        """
        Extrait dynamiquement les entités via l'IA et les intègre au graphe Neo4j.
        prefetched_data : dict JSON déjà extrait (evite un double appel LLM).
        """
        if not self.disponible():
            return False

        # Si on a déjà les données (appel depuis enrich_graph_batch), on les réutilise
        data = prefetched_data if prefetched_data else self.extraire_entites_llm(text)
        if not data:
            return False
            
        nom_doc = os.path.basename(source)
        self.ajouter_document(nom_doc, chemin=source)
        
        # 1. Equipements
        for eq in data.get("equipments", []):
            if "tag" in eq:
                self.ajouter_equipement(eq["tag"], eq.get("description", ""), nom_doc, eq.get("type", "Inconnu"), eq.get("system", ""))
                self.ajouter_document(nom_doc, tags_mentionnes=[self._normaliser_tag(eq["tag"])])
                
        # 2. Propriétés (Pression, Temp, Debit)
        for prop in data.get("properties", []):
            if "tag" in prop and "valeur" in prop and "relation" in prop:
                self.ajouter_propriete(
                    self._normaliser_tag(prop["tag"]), prop["relation"], str(prop["valeur"]), 
                    prop.get("unite", ""), nom_doc
                )
                
        # 3. Connexions (P&ID logique directionnel)
        for conn in data.get("connections", []):
            if "source" in conn and "target" in conn and "relation" in conn:
                self.ajouter_connexion(self._normaliser_tag(conn["source"]), self._normaliser_tag(conn["target"]), conn["relation"], nom_doc)
                
        # 4. Normes
        for norm in data.get("norms", []):
            if "tag" in norm and "norm" in norm:
                self.ajouter_conformite(norm["tag"], norm["norm"], nom_doc)
                
        logger.info("GraphRAG enrichi depuis %s : %d eq, %d props, %d conns", 
                    nom_doc, len(data.get("equipments",[])), len(data.get("properties",[])), len(data.get("connections",[])))
        return True

    def vider_test(self) -> None:
        """Supprime les nœuds créés lors des tests (tag TEST-* ou source test)."""
        if not self.disponible():
            return
        cypher = """
        MATCH (n)
        WHERE n.tag STARTS WITH 'TEST-' OR n.source = 'test.pdf'
           OR (n.nom IS NOT NULL AND n.nom STARTS WITH 'test')
        DETACH DELETE n
        """
        try:
            with self._driver.session(database=self._database) as session:
                session.run(cypher)
            logger.info("vider_test: nœuds de test supprimés")
        except Exception as e:
            logger.warning("vider_test: %s", e)

    def migrer_depuis_json(self, json_path: str = None) -> int:
        """
        Migre les entités du knowledge_graph.json vers Neo4j.
        Retourne le nombre d'entités migrées.
        """
        if not self.disponible():
            logger.warning("migrer_depuis_json: Neo4j non disponible")
            return 0
        path = json_path or KNOWLEDGE_GRAPH_PATH
        if not os.path.exists(path):
            logger.info("migrer_depuis_json: %s introuvable", path)
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                graph = json.load(f)
        except Exception as e:
            logger.error("migrer_depuis_json: lecture JSON: %s", e)
            return 0

        entities = graph.get("entities", {})
        count = 0
        for key, entity in entities.items():
            name = entity.get("name", key)
            etype = entity.get("type", "inconnu")
            sources = entity.get("sources", [])
            source = sources[0] if sources else ""
            if etype == "equipment":
                self.ajouter_equipement(name, "", source)
                count += 1
            elif etype == "norm":
                # Les normes sans équipement associé
                if self.disponible():
                    try:
                        with self._driver.session(database=self._database) as s:
                            s.run("MERGE (n:Norme {code: $code})", code=name)
                        count += 1
                    except Exception:
                        pass
        logger.info("migrer_depuis_json: %d entités migrées depuis %s", count, path)
        return count


# ===========================================================================
#  Singleton Neo4j
# ===========================================================================

_neo4j_kg: Optional[Neo4jKnowledgeGraph] = None
_neo4j_lock = threading.Lock()


def get_neo4j_kg() -> Neo4jKnowledgeGraph:
    """Retourne le singleton Neo4jKnowledgeGraph (thread-safe)."""
    global _neo4j_kg
    if _neo4j_kg is None:
        with _neo4j_lock:
            if _neo4j_kg is None:
                _neo4j_kg = Neo4jKnowledgeGraph()
    return _neo4j_kg


# ===========================================================================
#  Fallback JSON — rétrocompatibilité si Neo4j absent
# ===========================================================================

_GRAPH_LOCK = threading.Lock()
_BATCH_GRAPH: Optional[dict] = None


def _copy_empty() -> dict:
    return {"entities": {}, "relationships": [], "document_index": {}}

import sqlite3

from pathlib import Path

KNOWLEDGE_GRAPH_DB_PATH = KNOWLEDGE_GRAPH_PATH.replace(".json", ".db")
_INITIALIZED_DB_PATHS = set()

def get_project_db_path(project_id: Optional[str] = None) -> Path:
    """Resolve the SQLite database path, supporting project-specific databases."""
    if not project_id or project_id == "general":
        return Path("d:/DATA BASE IA/knowledge_graph.db")
        
    # Resolve the project directory
    base_dir = Path("d:/DATA BASE IA")
    data_path = base_dir / "data"
    proj_parent = data_path / "00-Projet"
    
    if proj_parent.exists():
        for p in proj_parent.iterdir():
            if p.is_dir():
                # Compare project IDs (lowercase with underscores)
                p_id = p.name.lower().replace(" ", "_").replace("&", "and")
                if p_id == project_id.lower() or p.name.lower() == project_id.lower():
                    return p / "knowledge_graph.db"
                    
    # Fallback to data/<project_id>/knowledge_graph.db
    fallback_path = data_path / project_id / "knowledge_graph.db"
    return fallback_path

def _init_db(project_id: Optional[str] = None) -> Path:
    global _INITIALIZED_DB_PATHS
    db_path = get_project_db_path(project_id)
    db_path_str = str(db_path.resolve())
    
    if db_path_str in _INITIALIZED_DB_PATHS:
        return db_path
        
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path_str)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                key TEXT PRIMARY KEY,
                name TEXT,
                type TEXT,
                sources TEXT,
                properties TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                target TEXT,
                relation TEXT,
                document TEXT,
                properties TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_index (
                document TEXT PRIMARY KEY,
                entity_keys TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_document ON relationships(document)")
        conn.commit()
        conn.close()
        
        _INITIALIZED_DB_PATHS.add(db_path_str)
        
        # If it's the global db, attempt JSON migration
        if project_id is None or project_id == "general":
            _migrate_json_to_sqlite(db_path_str)
            
    except Exception as e:
        logger.error("Failed to initialize SQLite knowledge graph at %s: %s", db_path_str, e)
        
    return db_path

def _migrate_json_to_sqlite(db_path_str: str) -> None:
    if not os.path.exists(KNOWLEDGE_GRAPH_PATH):
        return
    try:
        conn = sqlite3.connect(db_path_str)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM entities")
        count = cursor.fetchone()[0]
        if count > 0:
            conn.close()
            return
            
        logger.info("Migrating knowledge_graph.json to SQLite database at %s...", db_path_str)
        with open(KNOWLEDGE_GRAPH_PATH, "r", encoding="utf-8") as f:
            graph = json.load(f)
            
        entities = graph.get("entities", {})
        relationships = graph.get("relationships", [])
        doc_index = graph.get("document_index", {})
        
        # Batch insert entities
        entity_data = []
        for key, val in entities.items():
            sources_json = json.dumps(val.get("sources", []))
            properties_json = json.dumps(val.get("properties", {}))
            entity_data.append((key, val.get("name"), val.get("type"), sources_json, properties_json))
        
        cursor.executemany(
            "INSERT OR REPLACE INTO entities (key, name, type, sources, properties) VALUES (?, ?, ?, ?, ?)",
            entity_data
        )
        
        # Batch insert relationships
        rel_data = []
        for rel in relationships:
            props = {k: v for k, v in rel.items() if k not in ["source", "target", "relation", "document"]}
            rel_data.append((
                rel.get("source"),
                rel.get("target"),
                rel.get("relation"),
                rel.get("document"),
                json.dumps(props)
            ))
            
        cursor.executemany(
            "INSERT INTO relationships (source, target, relation, document, properties) VALUES (?, ?, ?, ?, ?)",
            rel_data
        )
        
        # Batch insert document index
        doc_data = []
        for doc, keys in doc_index.items():
            doc_data.append((doc, json.dumps(keys)))
            
        cursor.executemany(
            "INSERT OR REPLACE INTO document_index (document, entity_keys) VALUES (?, ?)",
            doc_data
        )
        
        conn.commit()
        conn.close()
        logger.info("Migration to SQLite complete: %d entities and %d relationships migrated.", len(entities), len(relationships))
    except Exception as e:
        logger.error("Failed to migrate knowledge_graph.json to SQLite: %s", e)

def load_graph(project_id: Optional[str] = None) -> dict:
    db_path = _init_db(project_id)
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Load entities
        cursor.execute("SELECT key, name, type, sources, properties FROM entities")
        entities = {}
        for row in cursor.fetchall():
            key, name, type_, sources_str, properties_str = row
            entities[key] = {
                "name": name,
                "type": type_,
                "sources": json.loads(sources_str or "[]"),
                "properties": json.loads(properties_str or "{}")
            }
            
        # Load relationships
        cursor.execute("SELECT source, target, relation, document, properties FROM relationships")
        relationships = []
        for row in cursor.fetchall():
            source, target, relation, document, properties_str = row
            rel = {
                "source": source,
                "target": target,
                "relation": relation,
                "document": document
            }
            if properties_str:
                try:
                    rel.update(json.loads(properties_str))
                except Exception: pass
            relationships.append(rel)
            
        # Load document_index
        cursor.execute("SELECT document, entity_keys FROM document_index")
        document_index = {}
        for row in cursor.fetchall():
            doc, keys_str = row
            document_index[doc] = json.loads(keys_str or "[]")
            
        conn.close()
        return {
            "entities": entities,
            "relationships": relationships,
            "document_index": document_index
        }
    except Exception:
        logger.exception("load_graph SQLite failed")
    return _copy_empty()

def save_graph(graph: dict, project_id: Optional[str] = None) -> None:
    db_path = _init_db(project_id)
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Clear existing tables
        cursor.execute("DELETE FROM entities")
        cursor.execute("DELETE FROM relationships")
        cursor.execute("DELETE FROM document_index")
        
        # Batch insert entities
        entities = graph.get("entities", {})
        entity_data = []
        for key, val in entities.items():
            sources_json = json.dumps(val.get("sources", []))
            properties_json = json.dumps(val.get("properties", {}))
            entity_data.append((key, val.get("name"), val.get("type"), sources_json, properties_json))
        
        cursor.executemany(
            "INSERT OR REPLACE INTO entities (key, name, type, sources, properties) VALUES (?, ?, ?, ?, ?)",
            entity_data
        )
        
        # Batch insert relationships
        relationships = graph.get("relationships", [])
        rel_data = []
        for rel in relationships:
            props = {k: v for k, v in rel.items() if k not in ["source", "target", "relation", "document"]}
            rel_data.append((
                rel.get("source"),
                rel.get("target"),
                rel.get("relation"),
                rel.get("document"),
                json.dumps(props)
            ))
            
        cursor.executemany(
            "INSERT INTO relationships (source, target, relation, document, properties) VALUES (?, ?, ?, ?, ?)",
            rel_data
        )
        
        # Batch insert document index
        doc_index = graph.get("document_index", {})
        doc_data = []
        for doc, keys in doc_index.items():
            doc_data.append((doc, json.dumps(keys)))
            
        cursor.executemany(
            "INSERT OR REPLACE INTO document_index (document, entity_keys) VALUES (?, ?)",
            doc_data
        )
        
        conn.commit()
        conn.close()
    except Exception:
        logger.exception("save_graph SQLite failed")

def _add_document_to_graph_json(source: str, text: str, project_id: Optional[str] = None) -> None:
    """Fallback SQLite thread-safe pour add_document_to_graph."""
    db_path = _init_db(project_id)
    
    tags = list(dict.fromkeys(_EQUIPMENT_TAG_RE.findall(text)))
    norms = list(dict.fromkeys(_NORM_RE.findall(text)))
    
    global _BATCH_GRAPH
    if _BATCH_GRAPH is not None:
        _insert_json(source, text, _BATCH_GRAPH)
        return
        
    with _GRAPH_LOCK:
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # Tags
            for tag in tags:
                key = tag.upper()
                cursor.execute("SELECT sources FROM entities WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    sources = json.loads(row[0] or "[]")
                    if source not in sources:
                        sources.append(source)
                        cursor.execute("UPDATE entities SET sources = ? WHERE key = ?", (json.dumps(sources), key))
                else:
                    cursor.execute(
                        "INSERT INTO entities (key, name, type, sources, properties) VALUES (?, ?, ?, ?, ?)",
                        (key, tag, "equipment", json.dumps([source]), json.dumps({}))
                    )
                    
            # Norms
            for norm in norms:
                key = norm.upper().strip()
                cursor.execute("SELECT sources FROM entities WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    sources = json.loads(row[0] or "[]")
                    if source not in sources:
                        sources.append(source)
                        cursor.execute("UPDATE entities SET sources = ? WHERE key = ?", (json.dumps(sources), key))
                else:
                    cursor.execute(
                        "INSERT INTO entities (key, name, type, sources, properties) VALUES (?, ?, ?, ?, ?)",
                        (key, norm, "norm", json.dumps([source]), json.dumps({}))
                    )
            
            # Document index
            cursor.execute("SELECT entity_keys FROM document_index WHERE document = ?", (source,))
            row = cursor.fetchone()
            existing_keys = []
            if row:
                existing_keys = json.loads(row[0] or "[]")
            for tag in tags:
                tk = tag.upper()
                if tk not in existing_keys:
                    existing_keys.append(tk)
            for norm in norms:
                nk = norm.upper().strip()
                if nk not in existing_keys:
                    existing_keys.append(nk)
                    
            cursor.execute(
                "INSERT OR REPLACE INTO document_index (document, entity_keys) VALUES (?, ?)",
                (source, json.dumps(existing_keys))
            )
            
            # Parse connections in text and save them
            conn_pattern = r"\b([A-Z]{1,4}-\d{2,5}[A-Z0-9]*)\b\s*(?:->|to|connected\s+to|alimente|refoule\s+vers)\s*\b([A-Z]{1,4}-\d{2,5}[A-Z0-9]*)\b"
            explicit_conns = re.findall(conn_pattern, text, re.IGNORECASE)
            for src, tgt in explicit_conns:
                s_up = src.upper().strip()
                t_up = tgt.upper().strip()
                if s_up != t_up:
                    cursor.execute(
                        "SELECT COUNT(*) FROM relationships WHERE source = ? AND target = ? AND relation = 'connected_to' AND document = ?",
                        (s_up, t_up, source)
                    )
                    if cursor.fetchone()[0] == 0:
                        cursor.execute(
                            "INSERT INTO relationships (source, target, relation, document, properties) VALUES (?, ?, ?, ?, ?)",
                            (s_up, t_up, "connected_to", source, json.dumps({}))
                        )

            # Sequential layout connection for PFD/Drawing documents
            is_pfd_doc = "pfd" in source.lower() or "implantation" in source.lower()
            if is_pfd_doc:
                raw_tags = re.findall(_EQUIPMENT_TAG_RE, text)
                pfd_main_tags = []
                for t in raw_tags:
                    t_up = t.upper().strip()
                    if not re.match(r"^(DAO|LDBP|REV|DWG|SOW|ANNEXE)\d*$", t_up, re.IGNORECASE):
                        if not t_up.startswith(("PH-", "PL-", "GL-", "PE-", "IE-", "PT", "TT", "FT", "LT", "ZT")):
                            if t_up not in pfd_main_tags:
                                pfd_main_tags.append(t_up)
                
                for idx in range(len(pfd_main_tags) - 1):
                    s_up = pfd_main_tags[idx]
                    t_up = pfd_main_tags[idx + 1]
                    cursor.execute(
                        "SELECT COUNT(*) FROM relationships WHERE source = ? AND target = ? AND relation = 'connected_to' AND document = ?",
                        (s_up, t_up, source)
                    )
                    if cursor.fetchone()[0] == 0:
                        cursor.execute(
                            "INSERT INTO relationships (source, target, relation, document, properties) VALUES (?, ?, ?, ?, ?)",
                            (s_up, t_up, "connected_to", source, json.dumps({}))
                        )
                        logger.info("Extracted PFD layout connection: %s -> %s from %s", s_up, t_up, source)

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error("Failed to add document to SQLite graph: %s", e)

def _insert_json(source: str, text: str, graph: dict) -> None:
    tags = list(dict.fromkeys(_EQUIPMENT_TAG_RE.findall(text)))
    norms = list(dict.fromkeys(_NORM_RE.findall(text)))
    for tag in tags:
        key = tag.upper()
        if key not in graph["entities"]:
            graph["entities"][key] = {"name": tag, "type": "equipment", "sources": []}
        if source not in graph["entities"][key]["sources"]:
            graph["entities"][key]["sources"].append(source)
    for norm in norms:
        key = norm.upper().strip()
        if key not in graph["entities"]:
            graph["entities"][key] = {"name": norm, "type": "norm", "sources": []}
        if source not in graph["entities"][key]["sources"]:
            graph["entities"][key]["sources"].append(source)
    graph["document_index"].setdefault(source, [])
    for t in tags:
        tk = t.upper()
        if tk not in graph["document_index"][source]:
            graph["document_index"][source].append(tk)
    for n in norms:
        nk = n.upper().strip()
        if nk not in graph["document_index"][source]:
            graph["document_index"][source].append(nk)

class batch_mode:
    """Context manager pour les mises à jour batch en mode JSON/SQLite."""
    def __enter__(self):
        global _BATCH_GRAPH
        _GRAPH_LOCK.acquire()
        _BATCH_GRAPH = load_graph()
        return _BATCH_GRAPH

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _BATCH_GRAPH
        if _BATCH_GRAPH is not None and exc_type is None:
            save_graph(_BATCH_GRAPH)
        _BATCH_GRAPH = None
        _GRAPH_LOCK.release()

# ===========================================================================
#  API publique rétrocompatible et partitionnée par projet
# ===========================================================================

def add_document_to_graph(source: str, text: str, project_id: Optional[str] = None) -> None:
    """Point d'entrée unique : Neo4j si disponible, sinon SQLite partitionné."""
    kg = get_neo4j_kg()
    if kg.disponible():
        kg.add_document_to_graph(source, text)
    else:
        _add_document_to_graph_json(source, text, project_id)

def query_graph(entity: str, project_id: Optional[str] = None) -> dict:
    """Requête une entité (Neo4j ou SQLite partitionné)."""
    kg = get_neo4j_kg()
    if kg.disponible():
        return kg.chercher_equipement(entity) or {
            "entity": entity, "type": None, "sources": [], "relationships": []}
            
    db_path = _init_db(project_id)
    with _GRAPH_LOCK:
        key = entity.upper().strip()
        result = {"entity": entity, "type": None, "sources": [], "relationships": []}
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # Query entity
            cursor.execute("SELECT type, sources FROM entities WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                result["type"] = row[0]
                result["sources"] = json.loads(row[1] or "[]")
                
            # Query relationships
            cursor.execute(
                "SELECT source, target, relation, document, properties FROM relationships WHERE source = ? OR target = ?",
                (key, key)
            )
            for r in cursor.fetchall():
                source, target, relation, document, properties_str = r
                rel = {
                    "source": source,
                    "target": target,
                    "relation": relation,
                    "document": document
                }
                if properties_str:
                    try:
                        rel.update(json.loads(properties_str))
                    except Exception: pass
                result["relationships"].append(rel)
                
            conn.close()
        except Exception as e:
            logger.error("Failed to query SQLite graph at %s: %s", db_path, e)
            
        return result

def get_document_network(filename: str, project_id: Optional[str] = None) -> dict:
    """
    Retourne le réseau d'entités associé à un document (Neo4j ou SQLite partitionné).
    """
    kg = get_neo4j_kg()
    if kg.disponible():
        try:
            cypher = """
            MATCH (d:Document {nom: $nom})-[:MENTIONNE]->(e:Equipement)
            RETURN e.tag AS tag, e.description AS description, e.type AS type
            """
            with kg._driver.session(database=kg._database) as session:
                records = list(session.run(cypher, nom=os.path.basename(filename)))
            entities = [{"name": r["tag"], "type": r["type"] or "equipment", "sources": [filename]}
                        for r in records]
            return {"document": filename, "entities": entities, "relationships": []}
        except Exception as e:
            logger.warning("get_document_network Neo4j: %s", e)

    db_path = _init_db(project_id)
    try:
        with _GRAPH_LOCK:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # Get entity keys for document
            cursor.execute("SELECT entity_keys FROM document_index WHERE document = ?", (filename,))
            row = cursor.fetchone()
            entities = []
            if row:
                keys = json.loads(row[0] or "[]")
                for key in keys:
                    cursor.execute("SELECT name, type, sources, properties FROM entities WHERE key = ?", (key,))
                    erow = cursor.fetchone()
                    if erow:
                        name, type_, sources_str, properties_str = erow
                        entities.append({
                            "name": name,
                            "type": type_,
                            "sources": json.loads(sources_str or "[]"),
                            "properties": json.loads(properties_str or "{}")
                        })
            
            # Get relationships for document
            cursor.execute(
                "SELECT source, target, relation, document, properties FROM relationships WHERE document = ?",
                (filename,)
            )
            relationships = []
            for r in cursor.fetchall():
                source, target, relation, document, properties_str = r
                rel = {
                    "source": source,
                    "target": target,
                    "relation": relation,
                    "document": document
                }
                if properties_str:
                    try:
                        rel.update(json.loads(properties_str))
                    except Exception: pass
                relationships.append(rel)
                
            conn.close()
        return {"document": filename, "entities": entities, "relationships": relationships}
    except Exception as e:
        logger.error("get_document_network SQLite failed at %s: %s", db_path, e)
        return {"document": filename, "entities": [], "relationships": []}

def build_graph_context(question: str, project_id: Optional[str] = None) -> str:
    """Construit le contexte graphe (Neo4j ou SQLite partitionné)."""
    kg = get_neo4j_kg()
    if kg.disponible():
        return kg.build_context(question)
        
    db_path = _init_db(project_id)
    try:
        tags = _EQUIPMENT_TAG_RE.findall(question.upper())
        if not tags:
            return ""
        with _GRAPH_LOCK:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            parts = []
            for tag in tags[:5]:
                cursor.execute("SELECT name, type FROM entities WHERE key = ?", (tag,))
                row = cursor.fetchone()
                if row:
                    parts.append(f"- {row[0]} ({row[1] or 'inconnu'})")
            conn.close()
        if parts:
            return "Informations du graphe de connaissances :\n" + "\n".join(parts)
    except Exception as e:
        logger.error("build_graph_context SQLite failed at %s: %s", db_path, e)
    return ""
