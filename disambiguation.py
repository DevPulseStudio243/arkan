"""
DeerFlow V4 — disambiguation.py
Module de résolution d'ambiguïtés entre équipements similaires.
Ex: "P-101" vs "P-101A" vs "P-101B" — lequel est visé ?
"""
import re
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

TAG_RE = re.compile(r'\b([A-Z]{1,4}-\d{2,5}[A-Z]?)\b')

class DisambiguationEngine:
    """
    Résolveur d'ambiguïtés pour les tags d'équipements Oil & Gas.
    Stratégie : 
    1. Extraction des tags candidats dans la question.
    2. Recherche des tags existants dans le KG Neo4j.
    3. Si plusieurs candidats similaires (P-101, P-101A), résolution par contexte.
    """

    def resolve(self, question: str, context_docs: List[Any] = None) -> Dict[str, Any]:
        """
        Identifie et résout les ambiguïtés dans une question.
        Retourne : {tags_found, resolved_tags, is_ambiguous, disambiguation_note}
        """
        tags_in_question = list(set(TAG_RE.findall(question.upper())))
        
        if not tags_in_question:
            return {
                "tags_found": [],
                "resolved_tags": [],
                "is_ambiguous": False,
                "disambiguation_note": ""
            }
        
        # Chercher les tags similaires dans le KG
        similar_groups = self._find_similar_tags(tags_in_question)
        
        if not similar_groups:
            return {
                "tags_found": tags_in_question,
                "resolved_tags": tags_in_question,
                "is_ambiguous": False,
                "disambiguation_note": ""
            }
        
        # Résolution par contexte documentaire
        resolved, note = self._resolve_by_context(question, similar_groups, context_docs or [])
        
        return {
            "tags_found": tags_in_question,
            "resolved_tags": resolved,
            "is_ambiguous": len(similar_groups) > 0,
            "disambiguation_note": note,
        }

    def _find_similar_tags(self, tags: List[str]) -> Dict[str, List[str]]:
        """Cherche les tags similaires dans Neo4j."""
        groups = {}
        try:
            from knowledge_graph import get_neo4j_kg
            kg = get_neo4j_kg()
            if not kg.disponible():
                return {}
            
            for tag in tags:
                # Trouver tous les variants : P-101 → P-101A, P-101B
                base = re.sub(r'[A-Z]$', '', tag)  # P-101A → P-101
                with kg._driver.session(database=kg._database) as session:
                    result = session.run(
                        "MATCH (e:Equipement) WHERE e.tag STARTS WITH $base RETURN e.tag AS tag",
                        base=base
                    )
                    variants = [r["tag"] for r in result if r["tag"] != tag]
                    if variants:
                        groups[tag] = variants
        except Exception as e:
            logger.debug("[Disambig] KG lookup failed: %s", e)
        
        return groups

    def _resolve_by_context(
        self, question: str, similar_groups: Dict[str, List[str]], 
        docs: List[Any]
    ) -> Tuple[List[str], str]:
        """Résolution par contexte : cherche quel tag apparaît le plus dans les documents."""
        resolved = []
        notes = []
        
        # Concaténer le texte des documents
        doc_text = " ".join(getattr(d, "text", str(d)) for d in docs[:5]).upper()
        
        for queried_tag, variants in similar_groups.items():
            all_candidates = [queried_tag] + variants
            best_tag = queried_tag
            best_count = doc_text.count(queried_tag)
            
            for v in variants:
                count = doc_text.count(v)
                if count > best_count:
                    best_count = count
                    best_tag = v
            
            resolved.append(best_tag)
            
            if best_tag != queried_tag:
                notes.append(
                    f"Ambiguïté '{queried_tag}' → résolu vers '{best_tag}' "
                    f"(autres variants: {', '.join(variants)})"
                )
        
        # Ajouter les tags non-ambigus
        for tag_in_q in similar_groups:
            pass  # Déjà traités
        
        note_str = " | ".join(notes) if notes else ""
        return resolved if resolved else list(similar_groups.keys()), note_str


# ── Singleton ──────────────────────────────────────────────
_engine: Optional[DisambiguationEngine] = None

def get_disambiguation_engine() -> DisambiguationEngine:
    global _engine
    if _engine is None:
        _engine = DisambiguationEngine()
    return _engine
