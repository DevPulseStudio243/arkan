"""
Script pour enrichir les nœuds Neo4j vides avec les données de la base documentaire (ChromaDB).
"""
import sys
import json
import logging
from knowledge_graph import get_neo4j_kg
from retriever import get_retriever
from entities import _get_equipment_description

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Enricher")

def enrich_nodes():
    kg = get_neo4j_kg()
    retriever = get_retriever()
    
    # 1. Récupérer les équipements
    res = kg._driver.execute_query("MATCH (e:Equipement) RETURN e.tag AS tag, e.description AS desc")
    tags = [record["tag"] for record in res.records if not record["desc"]]
    
    logger.info(f"{len(tags)} équipements à enrichir trouvés.")
    
    updated_count = 0
    for tag in tags:
        # A. Description de base via la taxonomie
        base_desc = _get_equipment_description(tag)
        if base_desc == "Équipement inconnu":
            base_desc = ""
            
        # B. Chercher dans ChromaDB pour des infos techniques
        chunks = retriever.retrieve(tag, top_k=3)
        context = " ".join([c.content for c in chunks]).lower()
        
        # Extraction très basique de la pression et température par Regex (pour être rapide)
        import re
        p_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(bar|barg|bara|psi|kpa|mpa)', context)
        t_match = re.search(r'(-?\d+(?:[.,]\d+)?)\s*(degc|°c|celsius|°f|deg f)', context)
        
        pression = p_match.group(0) if p_match else ""
        temperature = t_match.group(0) if t_match else ""
        
        # Enrichir la description avec ce qu'on a trouvé
        desc_parts = []
        if base_desc:
            desc_parts.append(base_desc)
        if pression:
            desc_parts.append(f"Pression: {pression}")
        if temperature:
            desc_parts.append(f"Température: {temperature}")
            
        final_desc = " | ".join(desc_parts)
        
        if final_desc:
            # Mise à jour Neo4j
            query = """
            MATCH (e:Equipement {tag: $tag})
            SET e.description = $desc,
                e.type = $type,
                e.pression = $p,
                e.temperature = $t
            """
            kg._driver.execute_query(
                query, 
                tag=tag, 
                desc=final_desc, 
                type=base_desc, 
                p=pression, 
                t=temperature
            )
            logger.info(f"✅ {tag} enrichi : {final_desc}")
            updated_count += 1
        else:
            logger.debug(f"Aucune info trouvée pour {tag}")
            
    logger.info(f"Enrichissement terminé. {updated_count} nœuds mis à jour.")

if __name__ == "__main__":
    enrich_nodes()
