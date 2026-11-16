"""
Script autonome pour enrichir le graphe Neo4j via l'extraction LLM (GraphRAG).
Ce script prend les derniers chunks indexés dans ChromaDB et les analyse avec l'IA.
"""
import sys
import logging
from knowledge_graph import get_neo4j_kg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("enrich_graph")

def run_enrichment(limit=5):
    kg = get_neo4j_kg()
    if not kg.disponible():
        logger.error("Neo4j n'est pas disponible. Abandon.")
        sys.exit(1)
        
    logger.info("Connexion ChromaDB pour récupérer des textes...")
    # On importe indexer pour récupérer les chunks facilement
    try:
        from indexer import get_collection
        collection = get_collection()
        docs = collection.get(limit=limit, include=["documents", "metadatas"])
    except Exception as e:
        logger.error(f"Erreur connexion ChromaDB: {e}")
        sys.exit(1)
        
    if not docs or not docs.get("documents"):
        logger.warning("Aucun document trouvé dans ChromaDB.")
        sys.exit(0)
        
    textes = docs["documents"]
    metadatas = docs.get("metadatas", [])
    
    logger.info(f"Démarrage de l'extraction IA sur {len(textes)} chunks...")
    
    succes = 0
    for i, (text, meta) in enumerate(zip(textes, metadatas)):
        source = meta.get("source", f"chunk_{i}")
        logger.info(f"\n--- Traitement chunk {i+1}/{len(textes)} : {source} ---")
        
        # Appel LLM pour extraire le graphe
        data = kg.extraire_entites_llm(text)
        logger.info(f"JSON extrait : {data}")
        if data and (data.get("equipments") or data.get("properties") or data.get("connections")):
            # Enrichir
            res = kg.enrichir_graphe_depuis_llm(source, text)
            if res:
                succes += 1
            
    logger.info(f"\nTerminé. {succes}/{len(textes)} chunks enrichis avec succès dans Neo4j.")

if __name__ == "__main__":
    # Pour le test, on limite à 3 chunks pour que ce soit rapide.
    run_enrichment(limit=3)
