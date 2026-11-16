"""
arh_concordance_graph.py
========================
Moteur de Concordance Multi-Documents basé sur un Graphe de Connaissances (NetworkX / LightRAG style).
Relie les entités d'ingénierie (équipements, tags, paramètres physiques) à travers tous les documents
d'un dossier ARH et détecte les discordances croisées avec validation dimensionnelle Pint.
"""

import re
import logging
from typing import Dict, List, Any, Optional, Tuple
import networkx as nx
from arh_dimensional_engine import dimensional_engine

logger = logging.getLogger("ARHConcordanceGraph")

class MultiDocumentConcordanceGraph:
    """Graphe de réconciliation et de détection des discordances inter-documents."""

    def __init__(self):
        self.graph = nx.MultiDiGraph()
        self.doc_nodes = set()
        self.equipment_nodes = set()

    def add_document(self, doc_name: str, doc_type: str = "GENERAL", metadata: Optional[Dict[str, Any]] = None):
        """Ajoute un document source au graphe."""
        if not doc_name:
            return
        clean_name = doc_name.strip()
        self.doc_nodes.add(clean_name)
        self.graph.add_node(
            clean_name,
            node_type="DOCUMENT",
            doc_type=doc_type,
            metadata=metadata or {}
        )

    def add_assertion(
        self,
        doc_name: str,
        equipment_tag: str,
        parameter_name: str,
        raw_value: Any,
        raw_unit: str = "",
        page: str = "",
        snippet: str = "",
        dimension_type: str = "pressure"
    ):
        """
        Ajoute une assertion déclarée par un document sur un équipement :
        (Doc) --[ASSERTS {param, value, unit, page}]--> (Equipment)
        """
        if not doc_name or not equipment_tag or not parameter_name or raw_value is None:
            return
            
        doc_name = doc_name.strip()
        eq_tag = equipment_tag.strip().upper()
        param = parameter_name.strip().lower()
        
        self.add_document(doc_name)
        self.equipment_nodes.add(eq_tag)
        self.graph.add_node(eq_tag, node_type="EQUIPMENT")
        
        # Tentative de conversion en float si applicable
        num_val = None
        clean_val_str = str(raw_value).strip().replace(',', '.')
        try:
            num_val = float(clean_val_str)
        except ValueError:
            pass
            
        self.graph.add_edge(
            doc_name,
            eq_tag,
            key=f"{param}_{len(self.graph.get_edge_data(doc_name, eq_tag) or {})}",
            parameter=param,
            raw_value=raw_value,
            num_value=num_val,
            unit=raw_unit.strip(),
            dimension_type=dimension_type,
            page=str(page),
            snippet=str(snippet)
        )

    def detect_discrepancies(self, tolerance_pct: float = 2.0) -> List[Dict[str, Any]]:
        """
        Parcourt le graphe pour identifier les discordances physiques ou textuelles
        entre deux documents affirmant des valeurs contradictoires pour le même paramètre.
        """
        discrepancies: List[Dict[str, Any]] = []
        
        for eq_tag in self.equipment_nodes:
            # Récupérer toutes les assertions ciblant cet équipement
            in_edges = self.graph.in_edges(eq_tag, data=True)
            
            # Regrouper les assertions par paramètre
            by_param: Dict[str, List[Dict[str, Any]]] = {}
            for u, v, data in in_edges:
                p = data.get("parameter")
                if not p:
                    continue
                item = {
                    "document": u,
                    "parameter": p,
                    "raw_value": data.get("raw_value"),
                    "num_value": data.get("num_value"),
                    "unit": data.get("unit", ""),
                    "dimension_type": data.get("dimension_type", "pressure"),
                    "page": data.get("page", ""),
                    "snippet": data.get("snippet", "")
                }
                by_param.setdefault(p, []).append(item)
                
            # Pour chaque paramètre, comparer toutes les paires issues de documents distincts
            for param, assertions in by_param.items():
                if len(assertions) < 2:
                    continue
                    
                seen_pairs = set()
                for i in range(len(assertions)):
                    for j in range(i + 1, len(assertions)):
                        a1 = assertions[i]
                        a2 = assertions[j]
                        
                        # Pas de comparaison si émis par le même document
                        if a1["document"] == a2["document"]:
                            continue
                            
                        pair_id = tuple(sorted([a1["document"], a2["document"]])) + (param,)
                        if pair_id in seen_pairs:
                            continue
                        seen_pairs.add(pair_id)
                        
                        # Comparaison numérique / physique
                        if a1["num_value"] is not None and a2["num_value"] is not None:
                            dim = a1.get("dimension_type") or "pressure"
                            is_conc, expl = dimensional_engine.physically_concordant(
                                a1["num_value"], a1["unit"],
                                a2["num_value"], a2["unit"],
                                dimension_type=dim,
                                tol_pct=tolerance_pct
                            )
                            if not is_conc:
                                severity = "CRITICAL" if any(k in param for k in ["pression", "pressure", "epaisseur", "thickness", "stress"]) else "MAJOR"
                                discrepancies.append({
                                    "equipment": eq_tag,
                                    "parameter": param,
                                    "severity": severity,
                                    "doc1": a1["document"],
                                    "val1": f"{a1['raw_value']} {a1['unit']}".strip(),
                                    "page1": a1["page"],
                                    "doc2": a2["document"],
                                    "val2": f"{a2['raw_value']} {a2['unit']}".strip(),
                                    "page2": a2["page"],
                                    "explanation": expl,
                                    "observation": (
                                        f"Discordance de dimensionnement sur l'équipement {eq_tag} ({param.upper()}) : "
                                        f"'{a1['document']}' (p. {a1['page']}) indique {a1['raw_value']} {a1['unit']}, alors que "
                                        f"'{a2['document']}' (p. {a2['page']}) indique {a2['raw_value']} {a2['unit']}. {expl}"
                                    )
                                })
                        else:
                            # Comparaison textuelle stricte (ex: Nuance d'acier, Code de calcul)
                            v1_str = str(a1["raw_value"]).strip().upper()
                            v2_str = str(a2["raw_value"]).strip().upper()
                            if v1_str and v2_str and v1_str != v2_str:
                                discrepancies.append({
                                    "equipment": eq_tag,
                                    "parameter": param,
                                    "severity": "MAJOR",
                                    "doc1": a1["document"],
                                    "val1": a1["raw_value"],
                                    "page1": a1["page"],
                                    "doc2": a2["document"],
                                    "val2": a2["raw_value"],
                                    "page2": a2["page"],
                                    "explanation": f"Différence textuelle ({v1_str} != {v2_str})",
                                    "observation": (
                                        f"Discordance de spécification sur l'équipement {eq_tag} ({param.upper()}) : "
                                        f"'{a1['document']}' (p. {a1['page']}) spécifie '{a1['raw_value']}', alors que "
                                        f"'{a2['document']}' (p. {a2['page']}) spécifie '{a2['raw_value']}'."
                                    )
                                })
                                
        return discrepancies

    def export_concordance_matrix(self) -> Dict[str, Any]:
        """Génère un tableau synthétique consolidé de tous les paramètres par équipement."""
        matrix: Dict[str, Any] = {}
        for eq_tag in self.equipment_nodes:
            matrix[eq_tag] = {}
            for u, v, data in self.graph.in_edges(eq_tag, data=True):
                p = data.get("parameter")
                val_repr = f"{data.get('raw_value')} {data.get('unit', '')}".strip()
                doc = u
                pg = data.get("page", "")
                matrix[eq_tag].setdefault(p, []).append({
                    "document": doc,
                    "value": val_repr,
                    "page": pg
                })
        return matrix
