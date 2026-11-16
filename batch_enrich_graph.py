"""
DeerFlow Lite - GraphRAG Batch Ingestion
Script pour automatiser l'enrichissement de Neo4j depuis les documents via l'IA.
Lit les fichiers dans /data, extrait le texte, et appelle l'API LLM pour créer les relations.
"""
import os
import glob
import logging
import time

# Forcer le chargement du .env local avant toute importation
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# Auto-détection de l'environnement (Docker vs Windows local)
# Si on n'est pas dans un conteneur Docker, on remplace "neo4j" et "ollama" par localhost
IN_DOCKER = os.path.exists("/.dockerenv")
if not IN_DOCKER:
    if "neo4j" in os.environ.get("NEO4J_URI", ""):
        os.environ["NEO4J_URI"] = os.environ["NEO4J_URI"].replace("neo4j", "localhost")
    if "ollama" in os.environ.get("OLLAMA_BASE_URL", ""):
        os.environ["OLLAMA_BASE_URL"] = os.environ["OLLAMA_BASE_URL"].replace("ollama", "127.0.0.1")

# Imports locaux DeerFlow
from knowledge_graph import get_neo4j_kg
from file_processor import FileProcessor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("batch_enrich_graph")

DATA_DIR = "./data"
CHUNK_SIZE = 3000  # Limite par bloc pour que l'IA extraie précisément les JSON

def run_batch_ingestion():
    kg = get_neo4j_kg()
    if not kg.disponible():
        logger.error("Neo4j n'est pas disponible. Veuillez démarrer la base Neo4j.")
        return

    logger.info("=== DÉMARRAGE DE L'ENRICHISSEMENT GRAPHRAG (BATCH) ===")
    
    files = []
    for ext in ["**/*.pdf", "**/*.txt", "**/*.md"]:
        files.extend(glob.glob(os.path.join(DATA_DIR, ext), recursive=True))
        
    if not files:
        logger.warning(f"Aucun document trouvé dans {DATA_DIR}.")
        return
        
    logger.info(f"{len(files)} document(s) trouvé(s) pour analyse LLM.")
    
    total_chunks = 0
    total_success = 0

    for filepath in files:
        filename = os.path.basename(filepath)
        logger.info(f"Traitement de : {filename}")
        
        try:
            # Lecture du texte via le processeur existant
            processor = FileProcessor()
            result = processor.process(filepath)
            text = result.text
            if not text or len(text.strip()) < 50:
                logger.info(f"Ignoré: {filename} (Texte trop court ou illisible).")
                continue
                
            # Découpage du texte en blocs
            chunks = [text[i:i+CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)]
            logger.info(f"Fichier divisé en {len(chunks)} bloc(s).")
            
            for i, chunk in enumerate(chunks):
                logger.info(f"  -> Analyse LLM du bloc {i+1}/{len(chunks)}...")
                t0 = time.time()
                
                # Appel direct à l'IA pour extraire JSON et l'insérer dans Neo4j
                success = kg.enrichir_graphe_depuis_llm(filepath, chunk)
                
                duration = time.time() - t0
                if success:
                    logger.info(f"  -> Succès ({duration:.1f}s) - Entités injectées.")
                    total_success += 1
                else:
                    logger.warning(f"  -> Échec/Rien trouvé ({duration:.1f}s).")
                    
                total_chunks += 1
                
        except Exception as e:
            logger.error(f"Erreur fatale sur {filename}: {e}")
            
    logger.info("=== FIN DE L'ENRICHISSEMENT ===")
    logger.info(f"Bilan : {total_success}/{total_chunks} blocs ont généré des entités Neo4j.")

if __name__ == "__main__":
    run_batch_ingestion()
