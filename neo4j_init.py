"""
DeerFlow Lite — neo4j_init.py
Script d'initialisation Neo4j : lancé au démarrage Docker.

Actions :
  1. Attendre que Neo4j soit prêt (retry loop)
  2. Créer les contraintes d'unicité et les index Cypher
  3. Créer le nœud :Projet LDBP5 s'il n'existe pas
  4. Migrer knowledge_graph.json → Neo4j si Neo4j est vide
"""
import os
import sys
import time
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [neo4j_init] %(levelname)s %(message)s",
)
logger = logging.getLogger("neo4j_init")

NEO4J_URI      = os.environ.get("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.environ.get("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "deerflow_oilgas_2025")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
KG_JSON_PATH   = os.environ.get("KNOWLEDGE_GRAPH_PATH", "knowledge_graph.json")
MAX_WAIT_S     = int(os.environ.get("NEO4J_INIT_WAIT", "120"))


def wait_for_neo4j(max_seconds: int = MAX_WAIT_S) -> object:
    """Attend que Neo4j soit prêt et retourne le driver."""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.error("neo4j-driver non installé. Lancer: pip install neo4j")
        sys.exit(1)

    deadline = time.time() + max_seconds
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            with driver.session(database=NEO4J_DATABASE) as session:
                session.run("RETURN 1")
            logger.info("Neo4j prêt après %d tentative(s) ✓", attempt)
            return driver
        except Exception as e:
            wait = min(5, attempt * 2)
            logger.info("Neo4j pas prêt (%s) — attente %ds [tentative %d]", e, wait, attempt)
            time.sleep(wait)

    logger.error("Neo4j non disponible après %ds. Abandon.", max_seconds)
    sys.exit(1)


def creer_schema(driver) -> None:
    """Contraintes d'unicité + index de performance."""
    contraintes = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Equipement) REQUIRE e.tag IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document)   REQUIRE d.nom IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Norme)      REQUIRE n.code IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Projet)     REQUIRE p.nom IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Materiau)   REQUIRE m.designation IS UNIQUE",
    ]
    index_list = [
        "CREATE INDEX IF NOT EXISTS FOR (e:Equipement) ON (e.tag)",
        "CREATE INDEX IF NOT EXISTS FOR (e:Equipement) ON (e.type)",
        "CREATE INDEX IF NOT EXISTS FOR (d:Document)   ON (d.discipline)",
        "CREATE INDEX IF NOT EXISTS FOR (f:Feedback)   ON (f.rating)",
    ]
    with driver.session(database=NEO4J_DATABASE) as session:
        for cypher in contraintes + index_list:
            try:
                session.run(cypher)
                logger.info("  ✓ %s", cypher[:70])
            except Exception as e:
                logger.warning("  ✗ %s — %s", cypher[:70], e)
    logger.info("Schéma Neo4j créé.")


def creer_projet_ldbp5(driver) -> None:
    """Crée le nœud :Projet LDBP5 de référence s'il n'existe pas."""
    cypher = """
    MERGE (p:Projet {nom: 'LDBP5'})
    ON CREATE SET p.site   = 'Hassi-Messaoud',
                  p.client = 'SONATRACH',
                  p.phase  = 'Engineering',
                  p.created = datetime()
    """
    with driver.session(database=NEO4J_DATABASE) as session:
        session.run(cypher)
    logger.info("Projet LDBP5 créé/vérifié dans Neo4j.")


def neo4j_est_vide(driver) -> bool:
    """Retourne True si Neo4j ne contient aucun nœud Equipement."""
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run("MATCH (e:Equipement) RETURN count(e) AS n")
        record = result.single()
        return (record["n"] if record else 0) == 0


def migrer_json_vers_neo4j(driver) -> int:
    """
    Migre knowledge_graph.json vers Neo4j si le graphe est vide.
    Retourne le nombre d'entités migrées.
    """
    if not os.path.exists(KG_JSON_PATH):
        logger.info("knowledge_graph.json introuvable — migration ignorée.")
        return 0

    try:
        with open(KG_JSON_PATH, "r", encoding="utf-8") as f:
            graph = json.load(f)
    except Exception as e:
        logger.error("Lecture knowledge_graph.json: %s", e)
        return 0

    entities = graph.get("entities", {})
    if not entities:
        logger.info("JSON vide — rien à migrer.")
        return 0

    logger.info("Démarrage migration JSON → Neo4j (%d entités)...", len(entities))
    count = 0
    with driver.session(database=NEO4J_DATABASE) as session:
        for key, entity in entities.items():
            name = entity.get("name", key)
            etype = entity.get("type", "inconnu")
            sources = entity.get("sources", [])
            source = sources[0] if sources else ""
            try:
                if etype == "equipment":
                    session.run(
                        "MERGE (e:Equipement {tag: $tag}) "
                        "ON CREATE SET e.source=$src, e.created=datetime()",
                        tag=name.upper(), src=source
                    )
                elif etype == "norm":
                    session.run(
                        "MERGE (n:Norme {code: $code}) "
                        "ON CREATE SET n.source=$src, n.created=datetime()",
                        code=name.strip(), src=source
                    )
                count += 1
            except Exception as e:
                logger.warning("Migration entité %s: %s", key, e)

    logger.info("Migration terminée : %d/%d entités insérées.", count, len(entities))
    return count


def main():
    logger.info("=" * 60)
    logger.info("DEERFLOW LITE — Initialisation Neo4j")
    logger.info("URI: %s | Base: %s", NEO4J_URI, NEO4J_DATABASE)
    logger.info("=" * 60)

    # 1. Attendre Neo4j
    driver = wait_for_neo4j()

    # 2. Schéma
    creer_schema(driver)

    # 3. Projet de référence
    creer_projet_ldbp5(driver)

    # 4. Migration JSON si Neo4j vide
    if neo4j_est_vide(driver):
        logger.info("Neo4j vide — tentative de migration depuis JSON...")
        migrer_json_vers_neo4j(driver)
    else:
        logger.info("Neo4j non vide — migration ignorée.")

    driver.close()
    logger.info("Initialisation Neo4j terminée ✓")


if __name__ == "__main__":
    main()
