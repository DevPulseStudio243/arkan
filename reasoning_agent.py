"""
DeerFlow Lite — Reasoning Agent (ReAct) v1.0
Agent raisonneur avec boucle Thought → Action → Observation.
Utilise Qwen 2.5 14B pour le raisonnement et l'appel d'outils.
"""
import json
import re
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field as PydanticField

import httpx

logger = logging.getLogger(__name__)

# ── Configuration Agent ──────────────────────────────────────
try:
    from config import OLLAMA_BASE_URL
except ImportError:
    OLLAMA_BASE_URL = "http://localhost:11434"

# Le modele dedie au raisonnement — Llama 3.1 8B (plus rapide et s'adapte mieux au VRAM GPU)
AGENT_MODEL = "llama3.1:8b"
AGENT_TIMEOUT = 240        # secondes (14B est plus lent mais plus precis)
AGENT_MAX_ITERATIONS = 12  # sécurité anti-boucle infinie (augmenté de 6 à 12 pour DeepSeek-R1 et auto-critique)
AGENT_TEMPERATURE = 0.1


# ── Structures de données ────────────────────────────────────
@dataclass
class AgentStep:
    """Une étape du raisonnement de l'agent."""
    step_type: str           # "thought", "action", "observation", "answer"
    content: str
    tool_name: str = ""
    tool_input: str = ""
    duration_ms: float = 0.0


@dataclass
class AgentResult:
    """Résultat complet de l'agent raisonneur."""
    answer: str
    steps: list[AgentStep] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    total_time: float = 0.0
    iterations: int = 0
    model_used: str = ""
    used_memory: bool = False
    selected_agent: str = ""



# ── Outils de l'Agent ────────────────────────────────────────
def tool_search_documents(query: str, discipline: str = "") -> str:
    """Recherche sémantique + BM25 dans la base documentaire."""
    try:
        from retriever import get_retriever, build_context_string
        retriever = get_retriever()
        results = retriever.retrieve(query, top_k=5, discipline_filter=discipline or None)
        if not results:
            return "Aucun document pertinent trouvé pour cette requête."

        # Appliquer le reranking
        try:
            from reranker import semantic_rerank
            results = semantic_rerank(query, results)
        except Exception:
            pass

        sources = list(set(r.source for r in results if r.source and r.source != "unknown"))
        context = build_context_string(results, max_tokens=2000)
        source_list = "\n".join(f"  - {s}" for s in sources) if sources else "  (aucune source identifiée)"
        return f"[{len(results)} documents trouvés]\nSources:\n{source_list}\n\nContenu pertinent:\n{context}"
    except Exception as e:
        logger.error(f"tool_search_documents error: {e}")
        return f"Erreur de recherche: {e}"


def tool_search_keywords(query: str) -> str:
    """Recherche BM25 pure (mots-clés exacts, tags équipement)."""
    try:
        from retriever import get_retriever
        retriever = get_retriever()
        retriever._ensure_initialized()
        if retriever._bm25_index is None:
            return "Index BM25 non disponible."

        import numpy as np
        tokens = retriever._tokenize(query)
        if not tokens:
            return "Aucun mot-clé valide extrait de la requête."

        scores = retriever._bm25_index.get_scores(tokens)
        top_indices = np.argsort(scores)[::-1][:5]

        parts = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            meta = retriever._bm25_corpus_metadatas[idx] if idx < len(retriever._bm25_corpus_metadatas) else {}
            source = meta.get("source", "?")
            text = retriever._bm25_corpus_texts[idx][:500]
            parts.append(f"[{source}] (score={scores[idx]:.2f})\n{text}")

        if not parts:
            return "Aucun résultat BM25 pertinent."
        return "\n---\n".join(parts)
    except Exception as e:
        logger.error(f"tool_search_keywords error: {e}")
        return f"Erreur recherche par mots-clés: {e}"


def tool_query_lightrag(question: str, mode: str = "hybrid") -> str:
    """
    Interroge le graphe de connaissances LightRAG.
    Idéal pour des synthèses de projet, des analyses transversales ou des questions multi-documents complexes.
    Modes supportés : 'local' (détails précis), 'global' (synthèse thématique), 'hybrid' (les deux).
    """
    try:
        from lightrag_integration import get_lightrag
        lr = get_lightrag()
        if lr.disponible():
            if mode not in ("local", "global", "hybrid"):
                mode = "hybrid"
            res = lr.query(question, mode=mode)
            if res:
                return res
            return "Aucun résultat trouvé dans le graphe LightRAG."
        return "Le graphe de connaissances LightRAG n'est pas disponible actuellement (Neo4j déconnecté ou désactivé)."
    except Exception as e:
        return f"Erreur lors de l'exécution de l'outil LightRAG : {e}"



def tool_query_knowledge_graph(entity: str = "", query: str = "") -> str:
    """Consulte le Knowledge Graph pour une entité (tag, équipement, norme)."""
    entity = entity or query
    if not entity:
        return "Erreur: Le paramètre 'entity' ou 'query' est requis."
    try:
        from knowledge_graph import query_graph, get_neo4j_kg
        kg = get_neo4j_kg()
        
        # 1. Vérifier si c'est un projet
        if kg.disponible():
            projets = kg.get_stats().get("Projet", 0)
            if projets > 0:
                # On essaie de voir s'il y a un projet avec ce nom
                eqs = kg.equipements_projet(entity)
                if eqs:
                    res = f"=== PROJET {entity.upper()} ===\n"
                    for eq in eqs:
                        res += f"- {eq['tag']} ({eq.get('type', 'N/A')}): {eq.get('description', '')}\n"
                    return res[:3000]
                    
        # 2. Requête d'équipement / norme classique
        result = query_graph(entity)
        if not result or result.get("type") is None and not result.get("pressions") and not result.get("documents"):
            return f"Aucune entité '{entity}' trouvée dans le Knowledge Graph."
            
        res_str = f"=== {entity.upper()} ===\n"
        
        # Format Neo4j
        if "tag" in result:
            res_str += f"Type: {result.get('type', 'Inconnu')}\n"
            if result.get("description"): res_str += f"Description: {result['description']}\n"
            if result.get("pressions"): res_str += f"Pressions: {', '.join(result['pressions'])}\n"
            if result.get("temperatures"): res_str += f"Températures: {', '.join(result['temperatures'])}\n"
            if result.get("normes"): res_str += f"Normes applicables: {', '.join(result['normes'])}\n"
            if result.get("documents"): res_str += f"Documents: {', '.join(result['documents'])}\n"
            return res_str
            
        # Format JSON Legacy
        res_str += f"Type: {result.get('type')}\n"
        if result.get("sources"):
            res_str += f"Sources: {', '.join(result['sources'][:3])}\n"
        rels = result.get("relationships", [])
        if rels:
            res_str += "Relations:\n"
            for rel in rels[:10]:
                other = rel["target"] if rel["source"] == entity.upper() else rel["source"]
                res_str += f"  - {rel['relation']}: {other}\n"
        return res_str
    except Exception as e:
        logger.error(f"tool_query_knowledge_graph error: {e}")
        return f"Erreur KG: {e}"

def tool_get_project_equipments(project_name: str = "", project: str = "") -> str:
    """Récupère la liste de tous les équipements d'un projet via SQLite ou Neo4j."""
    project_name = project_name or project
    if not project_name:
        return "Erreur: Le paramètre 'project_name' ou 'project' est requis."
    
    # 1. Tenter la recherche dans SQLite (data/verification.db)
    try:
        import sqlite3
        from pathlib import Path
        db_path = Path("data/verification.db")
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # Normalisation basique pour chercher le projet
            norm_name = project_name.lower().strip().replace(" ", "_").replace("-", "_")
            words = [w for w in norm_name.split("_") if len(w) > 2]
            
            # Récupérer tous les project_ids existants
            cursor.execute("SELECT DISTINCT project_id FROM equipment_attributes")
            all_projects = [row[0] for row in cursor.fetchall()]
            
            matched_project = None
            for p_id in all_projects:
                p_norm = p_id.lower().replace("-", "_").replace(" ", "_")
                if norm_name in p_norm or p_norm in norm_name:
                    matched_project = p_id
                    break
                for w in words:
                    if w in p_norm:
                        matched_project = p_id
                        break
            
            if matched_project:
                cursor.execute(
                    "SELECT tag, attribute_name, attribute_value, document FROM equipment_attributes WHERE project_id = ?",
                    (matched_project,)
                )
            else:
                # Si aucun projet spécifique ne matche, retourner la liste globale d'équipements SQLite
                cursor.execute(
                    "SELECT tag, attribute_name, attribute_value, document FROM equipment_attributes LIMIT 300"
                )
            rows = cursor.fetchall()
            if rows:
                # Grouper par tag
                eq_dict = {}
                for tag, attr_name, attr_val, doc in rows:
                    if tag not in eq_dict:
                        eq_dict[tag] = {"attrs": {}, "doc": doc}
                    eq_dict[tag]["attrs"][attr_name] = attr_val
                    
                header = f"=== ÉQUIPEMENTS PROJET (SQLite: {matched_project}) ===\n" if matched_project else "=== ÉQUIPEMENTS DE LA BASE (SQLite) ===\n"
                res = header
                for tag, info in sorted(eq_dict.items())[:50]:
                    attrs_str = ", ".join([f"{k}: {v}" for k, v in info["attrs"].items() if v and v != "Spécification absente"])
                    res += f"- {tag} (Source: {info['doc']})"
                    if attrs_str:
                        res += f" -- {attrs_str}"
                    res += "\n"
                if len(eq_dict) > 50:
                    res += f"\n... et {len(eq_dict)-50} autres équipements dans la base."
                conn.close()
                return res
            conn.close()
    except Exception as e:
        logger.error(f"SQLite project equipment lookup error: {e}")


    # 2. Fallback Neo4j
    try:
        from knowledge_graph import get_neo4j_kg
        kg = get_neo4j_kg()
        if not kg.disponible():
            return "Neo4j non disponible et aucun équipement trouvé dans SQLite."
            
        eqs = kg.equipements_projet(project_name)
        if not eqs:
            with kg._driver.session(database=kg._database) as session:
                records = list(session.run("MATCH (e:Equipement) RETURN e.tag AS tag, e.type AS type, e.description AS description LIMIT 100"))
                eqs = [dict(r) for r in records]
                
        if not eqs:
            return f"Aucun équipement trouvé pour le projet {project_name}."
            
        res = f"=== ÉQUIPEMENTS (Projet {project_name} - Neo4j) ===\n"
        for eq in eqs[:50]:
            res += f"- {eq['tag']} ({eq.get('type', 'N/A')}): {eq.get('description', '')}\n"
        if len(eqs) > 50:
            res += f"\n... et {len(eqs)-50} autres équipements."
        return res
    except Exception as e:
        logger.error(f"tool_get_project_equipments Neo4j error: {e}")
        return f"Erreur: {e}"

def tool_analyze_impact_neo4j(tag: str = "", entity: str = "", query: str = "", depth: str = "2") -> str:
    """Analyse l'impact d'une panne ou d'un changement d'équipement via Neo4j."""
    tag = tag or entity or query
    if not tag:
        return "Erreur: Le paramètre 'tag' ou 'entity' ou 'query' est requis."
    try:
        from knowledge_graph import get_neo4j_kg
        kg = get_neo4j_kg()
        if not kg.disponible():
            return "Neo4j non disponible pour l'analyse d'impact."
        
        profondeur = int(depth) if depth.isdigit() else 2
        result = kg.analyser_impact(tag, profondeur)
        
        if "error" in result:
            return f"Erreur d'analyse d'impact : {result['error']}"
            
        impacts = result.get("equipements_impactes", [])
        normes = result.get("normes_concernees", [])
        
        if not impacts:
            return f"Aucun impact détecté pour {tag} à une profondeur de {profondeur}."
            
        res_str = f"=== ANALYSE D'IMPACT (Graph RAG) pour {tag} ===\n"
        res_str += f"Profondeur de recherche : {profondeur} sauts\n"
        res_str += f"Équipements dépendants / impactés ({len(impacts)}) : {', '.join(impacts)}\n"
        if normes:
            res_str += f"Normes à vérifier : {', '.join(normes)}\n"
            
        return res_str
    except Exception as e:
        logger.error(f"tool_analyze_impact_neo4j error: {e}")
        return f"Erreur: {e}"

# ── Outils Planning & Cost Control ────────────────────────
def tool_compute_evm(BAC: str, BCWP: str, BCWS: str, ACWP: str) -> str:
    """Calcule les métriques Earned Value Management (EVM) d'un projet.

    Utilise-moi quand tu as des données de performance projet (budget, réalisé, plan)
    pour calculer les indicateurs CPI, SPI, EAC, ETC, VAC, TCPI.

    Args:
        BAC:  Budget At Completion - budget total du projet (ex: "1000000")
        BCWP: Budgeted Cost of Work Performed - Valeur Acquise / EV (ex: "450000")
        BCWS: Budgeted Cost of Work Scheduled - Valeur Planifiée / PV (ex: "500000")
        ACWP: Actual Cost of Work Performed - Coût Réel / AC (ex: "480000")

    Returns:
        Résultat structuré avec tous les KPIs EVM et leur interprétation.
    """
    try:
        from agents import PlanningCostAgent
        agent = PlanningCostAgent()
        bac = float(BAC.replace(",", ".").replace(" ", ""))
        bcwp = float(BCWP.replace(",", ".").replace(" ", ""))
        bcws = float(BCWS.replace(",", ".").replace(" ", ""))
        acwp = float(ACWP.replace(",", ".").replace(" ", ""))
        metrics = agent.compute_evm_metrics(bac, bcwp, bcws, acwp)
        lines = [
            "=== ANALYSE EVM (Earned Value Management) ===",
            f"  BAC  (Budget Total)       : {metrics['BAC']:,.2f}",
            f"  EV   (Valeur Acquise)     : {metrics['EV_BCWP']:,.2f}",
            f"  PV   (Valeur Planifiée)   : {metrics['PV_BCWS']:,.2f}",
            f"  AC   (Coût Réel)          : {metrics['AC_ACWP']:,.2f}",
            "",
            "--- Indices de Performance ---",
            f"  CPI  (Cost Perf. Index)   : {metrics['CPI']}  → {metrics['statut_cout']}",
            f"  SPI  (Sched. Perf. Index) : {metrics['SPI']}  → {metrics['statut_planning']}",
            f"  TCPI (To-Complete PI)     : {metrics['TCPI']}",
            "",
            "--- Prévisions à Terminaison ---",
            f"  EAC  (Estim. à Terminaison): {metrics['EAC']:,.2f}",
            f"  ETC  (Reste à Dépenser)    : {metrics['ETC']:,.2f}",
            f"  VAC  (Variance Budget)     : {metrics['VAC']:,.2f}  ({'Dépassement' if metrics['VAC'] < 0 else 'Économie'})",
            f"  Avancement                 : {metrics['pct_complete']}%",
            "",
            "--- Interprétation AACE 81R-13 ---",
        ]
        if metrics['CPI'] < 0.9:
            lines.append("  ⚠ ALERTE COÛ T: CPI<0.9 = dérive critique. Action corrective immédiate requise.")
        elif metrics['CPI'] < 1.0:
            lines.append("  ⚠ ATTENTION COÛ T: surveiller - risque de dépassement budget.")
        else:
            lines.append("  ✅ COÛTS: Performance satisfaisante.")
        if metrics['SPI'] < 0.9:
            lines.append("  ⚠ ALERTE PLANNING: SPI<0.9 = retard significatif. Récupération requise.")
        elif metrics['SPI'] < 1.0:
            lines.append("  ⚠ ATTENTION PLANNING: léger retard - surveiller le chemin critique.")
        else:
            lines.append("  ✅ PLANNING: En ligne avec le calendrier.")
        return "\n".join(lines)
    except ValueError as e:
        return f"Erreur de conversion numérique: {e}. Assurez-vous que BAC/BCWP/BCWS/ACWP sont des nombres."
    except Exception as e:
        logger.error(f"tool_compute_evm error: {e}")
        return f"Erreur calcul EVM: {e}"


def tool_analyze_planning_risk(schedule_delay_days: str, cost_overrun_pct: str, phase: str) -> str:
    """Analyse l'impact d'un écart planning/coût et génère des recommandations.

    Utilise-moi quand un retard ou dépassement est constaté pour obtenir
    une analyse de risque structurée et des actions correctives.

    Args:
        schedule_delay_days: Retard planning en jours (ex: "45")
        cost_overrun_pct: Dépassement de coût en % (ex: "12.5")
        phase: Phase actuelle du projet (ex: "Engineering", "Procurement", "Construction")

    Returns:
        Analyse de risque structurée avec actions correctives AACE/PMI.
    """
    try:
        delay = float(schedule_delay_days)
        overrun = float(cost_overrun_pct)
        phase = phase.strip()

        # Classification du niveau de risque
        if delay > 90 or overrun > 20:
            risk_level = "CRITIQUE 🔴"
            escalation = "Escalade immédiate vers le directeur de projet et le client. Comité de crise requis."
        elif delay > 30 or overrun > 10:
            risk_level = "MAJEUR 🟠"
            escalation = "Rapport d'écart formel requis. Revue Recovery Plan sous 48h."
        elif delay > 14 or overrun > 5:
            risk_level = "MODERE 🟡"
            escalation = "Revue hebdomadaire renforcée. Mise à jour du Risk Register."
        else:
            risk_level = "FAIBLE 🟢"
            escalation = "Surveillance standard. Documenter dans le rapport mensuel."

        # Recommandations selon la phase
        phase_lower = phase.lower()
        if "engineering" in phase_lower or "ingénierie" in phase_lower:
            specific = (
                "Phase Engineering: revoir les priorités de délivrance des documents "
                "(IFC en premier), optimiser les revues inter-disciplines, "
                "envisager ressources supplémentaires sur le chemin critique."
            )
        elif "procurement" in phase_lower or "approvisionnement" in phase_lower:
            specific = (
                "Phase Procurement: identifier les équipements long-lead en retard, "
                "activer les clauses d'accélération fournisseurs, "
                "vérifier les inspections FAT pour ne pas retarder les livraisons."
            )
        elif "construction" in phase_lower:
            specific = (
                "Phase Construction: audit du chemin critique Primavera P6, "
                "ressources supplémentaires (héures supplémentaires / sous-traitants additionnels), "
                "replanification rolling wave sur 4 semaines, "
                "vérifier les accès/permis pouvant causer des interférences."
            )
        else:
            specific = "Analyser le chemin critique et identifier les activités à accélérer en priorité."

        result = [
            f"=== ANALYSE RISQUE PLANNING & COÛT (Phase: {phase}) ===",
            f"  Retard Planning   : {delay:.0f} jours",
            f"  Dépassement Coût  : {overrun:.1f}%",
            f"  Niveau de Risque  : {risk_level}",
            "",
            f"ACTION IMMÉDIATE: {escalation}",
            "",
            f"RECOMMANDATIONS SPÉCIFIQUES ({phase.upper()}): {specific}",
            "",
            "RÉFÉRENCES APPLICABLES:",
            "  - AACE 29R-03 Forensic Schedule Analysis",
            "  - AACE 58R-10 Integrated Cost and Schedule Risk Analysis",
            "  - PMI PMBOK 7e éd. - Performance Domains: Délivrance & Incertitude",
        ]
        return "\n".join(result)
    except ValueError as e:
        return f"Erreur: {e}. Assurez-vous que schedule_delay_days et cost_overrun_pct sont des nombres."
    except Exception as e:
        logger.error(f"tool_analyze_planning_risk error: {e}")
        return f"Erreur analyse risque: {e}"


# ── Outil Vision : Génération de diagrammes ─────────────────
def tool_generate_diagram(title: str, sections) -> str:
    """Génère un visuel de synthèse (diagramme / carte) et retourne son URL.
    
    Utilise-moi quand l'utilisateur demande un schéma, un résumé visuel,
    ou quand les données sont mieux représentées sous forme de tableau/carte.
    
    Args:
        title: Titre du diagramme (ex: 'Pompe P-101', 'Système de compression').
        sections: Liste de sections ou JSON string — liste de sections [{"title": str, "points": [str, ...]}].
                  Exemple: '[{"title": "Spécifications", "points": ["Débit: 120 m3/h", "Pression: 6 bar"]}]'
    
    Returns:
        URL de l'image générée (accessible via /visuals/) ou un message d'erreur.
    """
    try:
        import json as _json
        from vision_generator import get_vision_generator
        
        # Déterminer les sections_data de manière robuste
        if isinstance(sections, list):
            sections_data = sections
        elif isinstance(sections, dict):
            sections_data = [sections]
        elif isinstance(sections, str):
            try:
                sections_data = _json.loads(sections)
                if not isinstance(sections_data, list):
                    sections_data = [{"title": "Contenu", "points": [str(sections_data)]}]
            except Exception:
                # Fallback: créer une section unique avec le texte brut
                sections_data = [{"title": "Informations", "points": [s.strip() for s in sections.split(",") if s.strip()]}]
        else:
            sections_data = [{"title": "Informations", "points": [str(sections)]}]
        
        generator = get_vision_generator()
        output_path = generator.generate_project_summary_card(title, sections_data)
        
        if output_path is None:
            return "Erreur: Impossible de générer le diagramme (vérifiez que Pillow est installé)."
        
        # Construire l'URL relative accessible via FastAPI /visuals/
        import os as _os
        filename = _os.path.basename(output_path)
        url = f"/visuals/{filename}"
        
        logger.info(f"[Diagram Tool] Visuel généré: {filename}")
        return (
            f"✅ Diagramme généré avec succès !\n"
            f"URL: {url}\n"
            f"Fichier: {filename}\n"
            f"Pour afficher ce diagramme dans la réponse, inclure: ![{title}]({url})"
        )
    except ImportError:
        return "Erreur: La bibliothèque 'Pillow' (PIL) n'est pas installée. Lancez: pip install Pillow"
    except Exception as e:
        logger.error(f"tool_generate_diagram error: {e}")
        return f"Erreur lors de la génération du diagramme: {e}"


# Registre des outils
def tool_analyze_engineering_pdf(file_path: str = "", path: str = "", filename: str = "") -> str:
    """Analyse détaillée d'un PDF technique (plans, ISO, data sheets) pour extraire les tags et tableaux."""
    file_path = file_path or path or filename
    if not file_path:
        return "Erreur: Le paramètre 'file_path' ou 'path' ou 'filename' est requis."
    try:
        from engineering_analyzer import get_engineering_analyzer
        from pathlib import Path
        analyzer = get_engineering_analyzer()
        
        # Résoudre le chemin si c'est juste un nom de fichier
        from config import DATA_DIR
        full_path = Path(file_path)
        if not full_path.is_absolute():
            # Chercher dans le dossier data
            matches = list(DATA_DIR.glob(f"**/{file_path}"))
            if matches:
                full_path = matches[0]
            else:
                return f"Erreur: Fichier '{file_path}' non trouvé dans le dossier {DATA_DIR}."
        
        results = analyzer.analyze_pdf(str(full_path))
        if "error" in results:
            return f"Erreur d'analyse: {results['error']}"
            
        return results["summary"]
    except Exception as e:
        logger.error(f"tool_analyze_engineering_pdf error: {e}")
        return f"Erreur d'analyse technique: {e}"

def tool_analyze_image_vision(image_name: str = "", image: str = "", image_path: str = "", file_path: str = "") -> str:
    """Analyse visuelle d'une image (P&ID, schéma, photo) via le modèle Vision (LLaVa/Qwen-VL)."""
    image_name = image_name or image or image_path or file_path
    if not image_name:
        return "Erreur: Le paramètre 'image_name' ou 'image' ou 'image_path' ou 'file_path' est requis."
    try:
        from config import DATA_DIR
        from pathlib import Path
        import base64
        
        full_path = Path(image_name)
        if not full_path.is_absolute():
            matches = list(DATA_DIR.glob(f"**/{image_name}"))
            if matches:
                full_path = matches[0]
            else:
                return f"Erreur: Image '{image_name}' introuvable dans {DATA_DIR}."
                
        with open(full_path, "rb") as fh:
            img_bytes = fh.read()
        
        b64 = base64.b64encode(img_bytes).decode('utf-8')
        
        # Appel direct au modèle de vision avec prompt multimodal avancé
        from file_processor import _call_vision_model_b64
        prompt = (
            "Tu es un expert en lecture de plans techniques Oil & Gas (P&ID, ISO, géométries). "
            "Analyse cette image technique et extrais avec précision :\n"
            "1. Les symboles d'ingénierie (vannes, pompes, compresseurs).\n"
            "2. Les sens de flux (flèches de tuyauterie) et les connexions logiques (qui alimente quoi).\n"
            "3. Tous les tags d'équipements et d'instruments visibles.\n"
            "Sois très descriptif sur la géométrie et les liaisons entre les éléments."
        )
        vision_result = _call_vision_model_b64(b64, prompt)
        
        if not vision_result:
            return "Le modèle de vision n'a rien détecté sur cette image."
            
        return f"=== RÉSULTAT ANALYSE VISUELLE ({image_name}) ===\n{vision_result}"
    except Exception as e:
        logger.error(f"tool_analyze_image_vision error: {e}")
        return f"Erreur d'analyse d'image: {e}"


def tool_query_traceability_db(sql_query: str) -> str:
    """Exécute une requête SQL SELECT (lecture seule) sur la base de traçabilité matérielle SQLite.
    Tables disponibles :
    - isometrics: id, line_number, revision, title, project_id, file_path, status, created_at, updated_at
    - bom_items: id, iso_id, category, tag, description, size, material, quantity, unit, weight_unit, weight_total, remarks, heat_number, spool_number, status, created_at, updated_at
    - heat_numbers: heat_number, material_spec, diameter, manufacturer, mtr_file_path, chemical_composition, mechanical_properties, inspector, status, created_at, updated_at
    - welds: id, iso_id, weld_number, weld_type, size, schedule, welder_id, weld_date, fitup_status, fitup_date, visual_status, visual_date, ndt_type, ndt_status, ndt_date, heat_number_1, heat_number_2, status, created_at, updated_at
    - spools: id, iso_id, spool_number, shop_field, fabricator, fitup_date, welding_date, ndt_date, painting_date, status, created_at, updated_at
    """
    import sqlite3
    import json
    from config import DATA_DIR
    
    query_clean = sql_query.strip()
    if not query_clean.lower().startswith("select"):
        return "Erreur: Seules les requêtes SELECT (lecture seule) sont autorisées sur la base de traçabilité matérielle."
        
    db_path = DATA_DIR / "traceability.db"
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query_clean)
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "Aucun résultat trouvé."
            
        results = [dict(r) for r in rows]
        return json.dumps(results, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"tool_query_traceability_db error: {e}")
        return f"Erreur lors de l'exécution de la requête SQL: {e}"


def tool_inspect_codebase_architecture(symbol: str = "", domain: str = "") -> str:
    """Interroge la cartographie d'architecture et de code Graft/AST d'ARKAN.
    Permet de trouver la définition, la localisation (fichier:lignes), les appelants (qui appelle cette fonction/classe),
    et les modules d'un domaine EPC (ARH Sonatrach, planning CPM, vision P&ID, procurement, multi-agents, etc.).
    Paramètres:
    - symbol: Nom du composant, classe ou fonction à inspecter (ex: PipingTopologyTracer, ARHRegulatoryEngine, PlanningMultiagentEngine).
    - domain: Domaine EPC optionnel (core, arh, planning, vision, procurement, rag).
    """
    import json
    from pathlib import Path
    
    wiring_file = Path(__file__).parent / "graft" / ".graph" / "wiring.json"
    if not wiring_file.exists():
        return "Cartographie de code non disponible (fichier wiring.json introuvable)."
        
    try:
        with open(wiring_file, "r", encoding="utf-8") as f:
            wiring = json.load(f)
            
        nodes = {n["id"]: n for n in wiring.get("nodes", [])}
        edges = wiring.get("edges", [])
        
        if domain and not symbol:
            domain_lower = domain.lower()
            matching_files = [n for n in nodes.values() if n.get("kind") == "file" and domain_lower in n.get("name", "").lower()]
            res = {
                "domain": domain,
                "files_count": len(matching_files),
                "sample_files": [f["name"] for f in matching_files[:15]]
            }
            return json.dumps(res, indent=2, ensure_ascii=False)
            
        sym_clean = symbol.strip()
        matched = None
        for n in nodes.values():
            if n.get("name", "").lower() == sym_clean.lower():
                matched = n
                break
        if not matched:
            for n in nodes.values():
                if sym_clean.lower() in n.get("id", "").lower():
                    matched = n
                    break
                    
        if not matched:
            return f"Symbole '{sym_clean}' non trouvé dans la cartographie d'ARKAN."
            
        target_id = matched["id"]
        callers = [e["source"] for e in edges if e.get("target") == target_id and e.get("relation") in ("calls", "imports", "references")]
        callees = [e["target"] for e in edges if e.get("source") == target_id and e.get("relation") in ("calls", "contains")]
        
        info = {
            "symbol": matched.get("name"),
            "kind": matched.get("kind"),
            "file": matched.get("path"),
            "span": matched.get("span"),
            "signature": matched.get("signature"),
            "callers_count": len(callers),
            "callers_sample": callers[:8],
            "callees_count": len(callees),
            "callees_sample": callees[:8]
        }
        return json.dumps(info, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Erreur lors de l'inspection de l'architecture: {e}"


AGENT_TOOLS = {
    "inspect_codebase_architecture": {
        "fn": tool_inspect_codebase_architecture,
        "description": "Interroge la cartographie d'architecture et de code Graft/AST d'ARKAN. Retourne la localisation précise (fichier, lignes), la signature et les modules appelants (Blast Radius) d'un composant (ex: ARHRegulatoryEngine, PipingTopologyTracer). Paramètres: symbol (str), domain (str optionnel).",
        "params": ["symbol", "domain"],
    },
    "query_traceability_db": {
        "fn": tool_query_traceability_db,
        "description": "Exécute une requête SQL SELECT en lecture seule sur la base de traçabilité matérielle SQLite. Tables disponibles: isometrics, bom_items, heat_numbers, welds, spools. Paramètre: sql_query (str).",
        "params": ["sql_query"],
    },
    "search_documents": {
        "fn": tool_search_documents,
        "description": "Recherche sémantique dans la base documentaire Oil & Gas. Paramètres: query (str), discipline (str optionnel: piping, process, mechanical, instrumentation, electrical, hse, civil, planning).",
        "params": ["query", "discipline"],
    },
    "search_keywords": {
        "fn": tool_search_keywords,
        "description": "Recherche par mots-clés exacts (BM25). Idéal pour les tags d'équipement (P-101, V-200), références normatives (API 610, AACE 18R-97), ou termes spécifiques. Paramètre: query (str).",
        "params": ["query"],
    },
    "query_lightrag": {
        "fn": tool_query_lightrag,
        "description": "Interroge le graphe de connaissances LightRAG (Graph RAG double-niveau local/global/hybrid). Idéal pour les synthèses, les questions transversales de projet ou d'impact. Paramètres: question (str), mode (str optionnel: 'local', 'global', 'hybrid').",
        "params": ["question", "mode"],
    },

    "query_knowledge_graph": {
        "fn": tool_query_knowledge_graph,
        "description": "Consulte le graphe de connaissances pour trouver les relations entre entités (équipements, normes, documents, jalons). Paramètre: entity (str) — tag ou nom de l'entité.",
        "params": ["entity", "query"],
    },
    "get_project_equipments": {
        "fn": tool_get_project_equipments,
        "description": "Récupère la liste de tous les équipements et tags liés à un projet spécifique (ou de toute la base si aucun projet n'est trouvé). Paramètre: project_name (str).",
        "params": ["project_name", "project"],
    },
    "analyze_impact_neo4j": {
        "fn": tool_analyze_impact_neo4j,
        "description": "Analyse d'impact en profondeur via le Knowledge Graph (Graph RAG). Trouve les dépendances en cascade, les normes impactées et les équipements en aval si une panne/modification survient. Paramètre: tag (str), depth (str optionnel, defaut '2').",
        "params": ["tag", "depth", "entity", "query"],
    },
    "compute_evm": {
        "fn": tool_compute_evm,
        "description": "Calcule la performance d'un projet via l'Earned Value Management (EVM). Paramètres: BAC, BCWP, BCWS, ACWP (représentant les coûts en float ou int sous forme de chaînes de caractères). Retourne le CV, SV, CPI, SPI et la projection EAC.",
        "params": ["BAC", "BCWP", "BCWS", "ACWP"],
    },
    "analyze_planning_risk": {
        "fn": tool_analyze_planning_risk,
        "description": "Évalue les risques d'impact sur le planning et les pénalités financières. Paramètres: schedule_delay_days (int/str), cost_overrun_pct (float/str), phase (str: 'engineering', 'procurement', 'construction').",
        "params": ["schedule_delay_days", "cost_overrun_pct", "phase"],
    },
    "generate_diagram": {
        "fn": tool_generate_diagram,
        "description": "Génère un schéma visuel (carte récapitulative) contenant des informations techniques structurées. Paramètres: title (str) — titre court du diagramme, sections (JSON string) — liste de sections [{'title': str, 'points': [str, ...]}]. Toujours inclure cette image dans la réponse finale via standard Markdown image markdown syntax.",
        "params": ["title", "sections"],
    },
    "create_tool": {
        "fn": __import__("tool_maker").tool_create_tool,
        "description": "Outil spécial te permettant de coder et de sauvegarder une fonction Python pour te créer un nouvel outil sur mesure. Utilise-le SEULEMENT si tu as besoin de faire des calculs spécifiques, du parsing complexe, ou de la conversion d'unités que tu ne peux pas faire de tête de manière fiable. Paramètres: tool_name (str), description (str), python_code (str), params (list[str]). IMPORTANT: Le python_code doit définir une fonction portant le même nom que tool_name, et renvoyer une valeur sous forme de chaîne de caractères (str).",
        "params": ["tool_name", "description", "python_code", "params"],
    },
    "analyze_engineering_pdf": {
        "fn": tool_analyze_engineering_pdf,
        "description": "Analyse structurelle approfondie d'un PDF technique (P&ID, ISO, spécifications, planning Primavera export). Extrait les tags d'équipements (ex: P-101), les lignes (ex: 10-HC-1001) et les tableaux de données techniques. Paramètre: file_path (str).",
        "params": ["file_path", "path", "filename"],
    },
    "analyze_image_vision": {
        "fn": tool_analyze_image_vision,
        "description": "Utilise l'intelligence artificielle visuelle (Multimodal) pour 'lire' une image (P&ID, schéma, photo). Paramètre: image_name (str) — nom de l'image (ex: 'pid_101.png').",
        "params": ["image_name"],
    }
}

# Injecter les outils de calcul technique Oil & Gas
try:
    from engineering_tools import ENGINEERING_TOOLS
    AGENT_TOOLS.update(ENGINEERING_TOOLS)
    # Note : On garde les outils SCADA dans AGENT_TOOLS pour qu'ils soient importables par le multi-agent orchestrator,
    # mais on les filtre dans le constructeur de ReasoningAgent.
    logger.info(f"[Agent] {len(ENGINEERING_TOOLS)} outils d'ingénierie et SCADA chargés.")
except Exception as _e:
    logger.warning(f"[Agent] Outils engineering non chargés: {_e}")


# ── Prompt Système ReAct ─────────────────────────────────────
REACT_SYSTEM_PROMPT = """Tu es DEERFLOW — un Agent IA Raisonneur expert en ingénierie Oil & Gas (pétrole et gaz).
Tu résous les questions techniques en réfléchissant étape par étape et en utilisant tes outils spécialisés.
Tu es capable de faire des calculs techniques précis (pertes de charge, puissance pompe, conversions d'unités),
de lire et analyser des documents techniques (P&ID, ISO, data sheets), de générer des diagrammes visuels,
et de créer tes propres outils si besoin.

=== OUTILS DISPONIBLES ===
{tools_description}

=== MÉTHODE DE TRAVAIL (ReAct) ===
Pour chaque question, tu DOIS suivre ce cycle:

1. <thought>Réfléchis à ce que tu dois chercher et pourquoi. Décide si un diagramme visuel aiderait l'utilisateur à mieux comprendre la réponse.</thought>
2. <action tool="NOM_OUTIL">{{"param1": "valeur1"}}</action>
3. Tu recevras une <observation>...</observation> avec le résultat de l'outil.
4. Répète les étapes 1-3 si tu as besoin de plus d'informations.
5. Quand tu penses avoir la réponse, rédige un brouillon:
   <answer>Brouillon de la réponse structurée.</answer>
6. Le système te demandera de faire une auto-critique. Tu devras alors soit chercher plus d'infos, soit valider avec:
   <final_answer>La réponse finale validée, exacte et complète.</final_answer>

=== QUAND GÉNÉRER UN DIAGRAMME ===
Utilise l'outil generate_diagram lorsque:
- L'utilisateur demande un schéma, un résumé visuel, ou une représentation graphique.
- La réponse contient 3+ spécifications techniques numériques (température, pression, débit, etc.).
- Il s'agit d'un équipement avec plusieurs paramètres (pompe, compresseur, échangeur).
Inclure l'image dans la réponse avec la syntaxe Markdown: ![Titre](/visuals/nom_fichier.png)

=== RÈGLES ABSOLUES ===
- Tu ne DOIS JAMAIS inventer de données. Base-toi UNIQUEMENT sur les observations.
- Tu DOIS citer tes sources avec [Source: nom_du_document].
- Si l'information n'est pas trouvée après 2 recherches, dis-le clairement.
- Chaque valeur numérique doit être accompagnée de son unité ET de sa source.
- Commence TOUJOURS par un <thought> avant toute action.
- Ne fais JAMAIS plus de {max_iterations} itérations.
- Écris en français.

=== FORMAT DE RÉPONSE FINALE ===
La réponse dans <final_answer> (ou <answer> initial) doit être:
- Structurée avec des titres et sous-titres si nécessaire
- Précise et technique
- Avec les sources citées entre crochets [Source: ...]
- Avec les unités pour chaque valeur numérique
- Si un diagramme a été généré, inclure l'image avec ![titre](url)

=== EXEMPLE DE RAISONNEMENT ATTENDU (Claude-style Chain-of-Thought) ===
User: Quelle est la pression de design de la pompe P-101A ?
<thought>
1. Je dois trouver la pression de design de l'équipement P-101A.
2. L'outil le plus précis pour un tag d'équipement est 'search_keywords'.
</thought>
<action tool="search_keywords">{{"query": "P-101A pression design"}}</action>
<observation>[Source: datasheet_p101.pdf] Item: P-101A/B. Operating Pressure: 15 bar. Design Pressure: 18 bar. Material: CS.</observation>
<thought>
3. J'ai trouvé l'information exacte: 18 bar.
4. L'information vient de datasheet_p101.pdf.
5. Une seule valeur n'est pas suffisante pour justifier un diagramme visuel. Je vais répondre directement.
</thought>
<answer>
La pression de design de la pompe **P-101A** est de **18 bar** [Source: datasheet_p101.pdf]. 
(Note: sa pression opératoire est de 15 bar, soit une marge de design standard de +20%).
</answer>
"""


class ReActStep(BaseModel):
    """Schéma de validation Pydantic pour une étape du cycle ReAct."""
    thought: Optional[str] = PydanticField(None, description="Réflexion logique sur la question ou l'observation.")
    action_tool: Optional[str] = PydanticField(None, description="Nom de l'outil technique à appeler.")
    action_input: Optional[Dict[str, Any]] = PydanticField(None, description="Arguments à passer à l'outil.")
    answer: Optional[str] = PydanticField(None, description="Brouillon ou réponse intermédiaire.")
    final_answer: Optional[str] = PydanticField(None, description="Réponse finale validée après auto-critique.")


# ── Moteur de l'Agent ────────────────────────────────────────
class ReasoningAgent:
    """
    Agent raisonneur basé sur le pattern ReAct.
    Utilise Qwen 2.5 14B pour la réflexion et l'appel d'outils.
    """

    def __init__(self, model: str = AGENT_MODEL, max_iterations: int = AGENT_MAX_ITERATIONS):
        self.model = model
        self.max_iterations = max_iterations
        self.base_tools = AGENT_TOOLS.copy()
        # Retirer les outils SCADA (inutiles en phase d'ingénierie) de l'agent raisonneur ReAct classique
        for tool_to_remove in ["get_scada_live_data", "analyze_scada_trend"]:
            if tool_to_remove in self.base_tools:
                del self.base_tools[tool_to_remove]
        self.tools = self.base_tools.copy()
        self._http_client = None

    def _refresh_tools(self):
        """Recharge les outils dynamiques avant chaque run."""
        self.tools = self.base_tools.copy()
        try:
            from tool_maker import get_dynamic_tools
            dynamic_tools = get_dynamic_tools()
            if dynamic_tools:
                logger.info(f"[Agent] Chargement de {len(dynamic_tools)} outil(s) dynamique(s): {list(dynamic_tools.keys())}")
                self.tools.update(dynamic_tools)
        except Exception as e:
            logger.error(f"[Agent] Erreur lors du chargement des outils dynamiques: {e}")

    def _get_client(self) -> httpx.Client:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.Client(timeout=AGENT_TIMEOUT)
        return self._http_client

    def _build_tools_description(self) -> str:
        parts = []
        for name, info in self.tools.items():
            params = ", ".join(info["params"])
            parts.append(f"• {name}({params}): {info['description']}")
        return "\n".join(parts)

    def _build_system_prompt(self) -> str:
        return REACT_SYSTEM_PROMPT.format(
            tools_description=self._build_tools_description(),
            max_iterations=self.max_iterations,
        )

    def _call_llm(self, messages: list[dict]) -> str:
        """Appel au LLM via Ollama API."""
        try:
            client = self._get_client()
            resp = client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": AGENT_TEMPERATURE,
                        "top_p": 0.9,
                        "num_predict": 4096,
                    },
                },
                timeout=AGENT_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except httpx.ConnectError:
            return "<answer>Erreur: Impossible de se connecter au serveur LLM (Ollama). Vérifiez que le service est démarré.</answer>"
        except Exception as e:
            logger.error(f"Agent LLM call failed: {e}")
            return f"<answer>Erreur lors de l'appel au modèle: {e}</answer>"

    def _parse_json_step(self, text: str) -> Optional[dict]:
        """Tente de parser la réponse du modèle en JSON valide respectant le schéma ReActStep."""
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        # Essayer d'extraire un bloc JSON valide si le modèle a mis du texte autour
        if "{" in cleaned and "}" in cleaned:
            start_idx = cleaned.find("{")
            end_idx = cleaned.rfind("}")
            if start_idx != -1 and end_idx != -1:
                cleaned = cleaned[start_idx:end_idx+1]

        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                # Valider avec Pydantic
                step = ReActStep(**data)
                return step.dict()
        except Exception:
            pass
        return None

    def _parse_action(self, text: str) -> tuple[str, dict]:
        """Parse une balise <action tool="...">...</action>."""
        match = re.search(r'<action\s+tool="([^"]+)">\s*(.*?)\s*</action>', text, re.DOTALL)
        if not match:
            return "", {}
        tool_name = match.group(1).strip()
        params_raw = match.group(2).strip()

        # Essayer de parser le JSON des paramètres
        try:
            params = json.loads(params_raw)
        except json.JSONDecodeError:
            # Fallback: paramètre simple (string sans JSON)
            if tool_name in self.tools and self.tools[tool_name]["params"]:
                first_param = self.tools[tool_name]["params"][0]
                params = {first_param: params_raw.strip('"').strip("'")}
            else:
                params = {}
        return tool_name, params

    def _parse_thought(self, text: str) -> str:
        """Extrait le contenu de <thought>...</thought> ou <think>...</think>."""
        match = re.search(r'<(?:thought|think)>(.*?)</(?:thought|think)>', text, re.DOTALL)
        return match.group(1).strip() if match else ""

    def _parse_answer(self, text: str) -> str:
        """Extrait le contenu de <answer>...</answer> ou fallback pour les modèles de raisonnement."""
        match = re.search(r'<answer>(.*?)</answer>', text, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # Fallback pour les modèles de raisonnement comme deepseek-r1 (réponse brute après </think>)
        think_match = re.search(r'</(?:think|thought)>\s*(.*)', text, re.DOTALL)
        if think_match:
            content = think_match.group(1).strip()
            # On s'assure que ce n'est pas une action, ni un autre tag structurel
            if content and not re.search(r'<(?:action|final_answer|answer)', content):
                return content
        return ""

    def _parse_final_answer(self, text: str) -> str:
        """Extrait le contenu de <final_answer>...</final_answer> ou fallback pour les modèles de raisonnement."""
        match = re.search(r'<final_answer>(.*?)</final_answer>', text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    def _execute_tool(self, tool_name: str, params: dict) -> str:
        """Exécute un outil et retourne le résultat."""
        if tool_name not in self.tools:
            return f"Erreur: outil '{tool_name}' inconnu. Outils disponibles: {', '.join(self.tools.keys())}"

        tool_info = self.tools[tool_name]
        fn = tool_info["fn"]

        # Mapper les paramètres
        try:
            # Filtrer les paramètres valides
            valid_params = {k: v for k, v in params.items() if k in tool_info["params"]}
            result = fn(**valid_params)
            return result
        except Exception as e:
            logger.error(f"Tool execution error ({tool_name}): {e}")
            return f"Erreur d'exécution de l'outil {tool_name}: {e}"

    def run(self, query: str, discipline: str = "") -> AgentResult:
        """
        Exécute la boucle ReAct complète.

        Args:
            query: La question de l'utilisateur.
            discipline: Discipline optionnelle (piping, process, etc.)

        Returns:
            AgentResult avec la réponse et la trace de raisonnement.
        """
        start_time = time.time()
        steps: list[AgentStep] = []
        all_sources: set[str] = set()
        used_memory = False

        self._refresh_tools()  # Recharger les outils dynamiques

        logger.info(f"[Agent] Démarrage du raisonnement pour: '{query[:80]}...'")

        # === 1. TENTATIVE DE RAPPEL DE MÉMOIRE (Experience Recall) ===
        try:
            from agent_memory import get_agent_memory
            memory = get_agent_memory()
            past_exp = memory.recall_experience(query)
            
            if past_exp:
                logger.info(f"[Agent] 🧠 Mémoire rappelée : similaire à '{past_exp['past_query']}'")
                used_memory = True
                # Créer une étape virtuelle pour la trace
                steps.append(AgentStep(
                    step_type="thought",
                    content=f"J'ai déjà résolu un problème très similaire: '{past_exp['past_query']}'. Je vais utiliser ma mémoire pour répondre directement.",
                    duration_ms=0.0
                ))
                # Injecter la réponse passée
                final_answer = past_exp['answer']
                steps.append(AgentStep(
                    step_type="answer",
                    content=final_answer,
                    duration_ms=0.0
                ))
                
                # Extraire les sources de la réponse rappelée
                for match in re.finditer(r'\[Source:\s*([^\]]+)\]', final_answer):
                    all_sources.add(match.group(1).strip())
                
                return AgentResult(
                    answer=final_answer,
                    steps=steps,
                    sources=sorted(all_sources),
                    total_time=round(time.time() - start_time, 2),
                    iterations=0,
                    model_used=f"{self.model} (Memory Recall)",
                    used_memory=True
                )
        except Exception as e:
            logger.error(f"[Agent] Erreur lors du rappel de mémoire: {e}")

        # === 2. BOUCLE REACT NORMALE ===
        system_prompt = self._build_system_prompt()
        user_msg = f"Question: {query}"
        if discipline:
            user_msg += f"\nDiscipline: {discipline}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

        final_answer = ""
        iteration = 0

        logger.info(f"[Agent] Démarrage du raisonnement pour: '{query[:80]}...'")

        while iteration < self.max_iterations:
            iteration += 1
            step_start = time.time()

            # Appeler le LLM
            response_text = self._call_llm(messages)
            step_duration = (time.time() - step_start) * 1000

            if "Erreur lors de l'appel au modèle" in response_text or "Impossible de se connecter au serveur LLM" in response_text:
                logger.error(f"[Agent] LLM Call Error detected: {response_text}")
                final_answer = f"⚠ L'agent a échoué en raison d'une erreur LLM : {response_text}"
                steps.append(AgentStep(
                    step_type="answer",
                    content=final_answer,
                    duration_ms=step_duration,
                ))
                break

            logger.debug(f"[Agent] Itération {iteration}, réponse LLM ({step_duration:.0f}ms):\n{response_text[:300]}...")

            # Essayer de parser en JSON (Pydantic)
            json_step = self._parse_json_step(response_text)
            if json_step:
                thought = json_step.get("thought") or ""
                tool_name = json_step.get("action_tool") or ""
                tool_params = json_step.get("action_input") or {}
                answer = json_step.get("answer") or ""
                final = json_step.get("final_answer") or ""
                logger.info("[Agent] Parsing JSON structurel réussi via Pydantic.")
            else:
                # Fallback sur le parser Regex historique
                thought = self._parse_thought(response_text)
                tool_name, tool_params = self._parse_action(response_text)
                answer = self._parse_answer(response_text)
                final = self._parse_final_answer(response_text)
                
                # Fallback spécifique pour l'auto-critique DeepSeek-R1
                if not final and len(messages) >= 2 and isinstance(messages[-1].get("content"), str) and "=== PHASE D'AUTO-CRITIQUE" in messages[-1]["content"]:
                    think_match = re.search(r'</(?:think|thought)>\s*(.*)', response_text, re.DOTALL)
                    if think_match:
                        fallback_final = think_match.group(1).strip()
                        if fallback_final and not re.search(r'<(?:action|answer)', fallback_final):
                            final = fallback_final

            # 1. Enregistrer le thought s'il y en a un
            if thought:
                steps.append(AgentStep(
                    step_type="thought",
                    content=thought,
                    duration_ms=step_duration,
                ))
                logger.info(f"[Agent] 💭 Thought: {thought[:100]}...")

            # 2. Vérifier s'il y a une réponse finale confirmée
            if final:
                final_answer = final
                steps.append(AgentStep(
                    step_type="answer",
                    content=final,
                    duration_ms=step_duration,
                ))
                logger.info(f"[Agent] ✅ Réponse finale obtenue après {iteration} itérations")
                break

            # 3. Vérifier s'il y a un brouillon de réponse à critiquer
            if answer and not final:
                steps.append(AgentStep(
                    step_type="thought",
                    content="J'ai rédigé un brouillon. Je procède à l'auto-critique (Self-Reflection) pour valider l'exactitude des valeurs, des unités et des sources.",
                    duration_ms=step_duration,
                ))
                logger.info(f"[Agent] 🔍 Auto-critique déclenchée pour: {answer[:50]}...")
                
                reflection_prompt = f"""Tu viens de formuler ce brouillon de réponse :
{answer}

=== PHASE D'AUTO-CRITIQUE (Self-Reflection) ===
1. As-tu répondu de façon exhaustive à la question originale ?
2. Les unités et valeurs numériques sont-elles cohérentes et correctes ?
3. As-tu bien cité toutes les sources [Source: ...] nécessaires ?
4. N'y a-t-il aucune contradiction dans ta réponse ?

Si la réponse nécessite d'être corrigée ou enrichie :
-> Réponds avec un nouveau <thought> et une <action tool="..."> pour chercher ce qui manque.
Si la réponse est parfaite, exacte et complète :
-> Réponds UNIQUEMENT avec <final_answer>Ta réponse validée et formatée ici</final_answer>. Ne génère plus de balise <answer>."""
                
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": reflection_prompt})
                continue

            # 4. Extraire et exécuter l'action
            tool_name, tool_params = self._parse_action(response_text)
            if tool_name:
                steps.append(AgentStep(
                    step_type="action",
                    content=f"Appel: {tool_name}({json.dumps(tool_params, ensure_ascii=False)})",
                    tool_name=tool_name,
                    tool_input=json.dumps(tool_params, ensure_ascii=False),
                    duration_ms=step_duration,
                ))
                logger.info(f"[Agent] 🔧 Action: {tool_name}({json.dumps(tool_params, ensure_ascii=False)[:100]})")

                # Exécuter l'outil
                tool_start = time.time()
                observation = self._execute_tool(tool_name, tool_params)
                tool_duration = (time.time() - tool_start) * 1000

                # Recharger les outils immédiatement si un nouvel outil a été créé
                if tool_name == "create_tool" and "SUCCES" in observation:
                    logger.info("[Agent] Nouvel outil détecté, rechargement du registre...")
                    self._refresh_tools()

                # Extraire les sources de l'observation
                for match in re.finditer(r'\[([^\]]+\.(?:pdf|docx|xlsx|txt|csv|pptx))\]', observation):
                    all_sources.add(match.group(1))
                # Aussi chercher les patterns [Source: xxx]
                for match in re.finditer(r'\[Source:\s*([^\]]+)\]', observation):
                    all_sources.add(match.group(1).strip())

                steps.append(AgentStep(
                    step_type="observation",
                    content=observation[:3000],  # Tronquer les observations trop longues
                    tool_name=tool_name,
                    duration_ms=tool_duration,
                ))
                logger.info(f"[Agent] 👁 Observation: {observation[:100]}... ({tool_duration:.0f}ms)")

                # Ajouter au contexte de conversation
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": f"<observation>{observation[:3000]}</observation>"})
            else:
                # Pas d'action et pas de réponse — forcer une réponse
                if not thought:
                    # Le modèle n'a rien produit de structuré — utiliser le texte brut
                    final_answer = response_text
                    steps.append(AgentStep(
                        step_type="answer",
                        content=response_text,
                        duration_ms=step_duration,
                    ))
                    break
                else:
                    # Le modèle a réfléchi mais n'a pas agi — lui demander d'agir
                    messages.append({"role": "assistant", "content": response_text})
                    messages.append({"role": "user", "content": (
                        "Tu as réfléchi mais tu n'as pas utilisé d'outil ni donné de réponse. "
                        "Utilise un outil avec <action tool=\"...\"> ou donne ta réponse avec <answer>."
                    )})

        # Si on atteint la limite d'itérations sans réponse
        if not final_answer:
            final_answer = (
                "⚠ L'agent a atteint la limite de raisonnement sans pouvoir formuler "
                "une réponse complète. Voici ce qui a été trouvé dans les étapes précédentes."
            )
            # Essayer de compiler les observations
            observations = [s.content for s in steps if s.step_type == "observation"]
            if observations:
                final_answer += "\n\n**Informations partielles trouvées:**\n" + "\n---\n".join(observations[:3])

        # === 3. SAUVEGARDE EN MÉMOIRE ===
        if final_answer and not final_answer.startswith("⚠ L'agent a atteint la limite"):
            try:
                from agent_memory import get_agent_memory
                memory = get_agent_memory()
                memory.save_experience(query, final_answer, steps, self.model)
            except Exception as e:
                logger.error(f"Erreur lors de la sauvegarde en mémoire: {e}")

        total_time = time.time() - start_time

        return AgentResult(
            answer=final_answer,
            steps=steps,
            sources=sorted(all_sources),
            total_time=round(total_time, 2),
            iterations=iteration,
            model_used=self.model,
            used_memory=used_memory
        )


# ── Singleton ────────────────────────────────────────────────
_agent = None
_agent_lock = __import__("threading").Lock()


def get_reasoning_agent():
    """Retourne l'instance singleton du réseau d'agents (MultiAgentReasoningAgent)."""
    global _agent
    if _agent is None:
        with _agent_lock:
            if _agent is None:
                try:
                    from multi_agent_orchestrator import MultiAgentReasoningAgent
                    _agent = MultiAgentReasoningAgent()
                except Exception as e:
                    logger.warning(f"Fallback vers ReasoningAgent monolithique: {e}")
                    _agent = ReasoningAgent()
    return _agent



def reason(query: str, discipline: str = "") -> AgentResult:
    """Convenience function pour exécuter l'agent."""
    return get_reasoning_agent().run(query, discipline)
