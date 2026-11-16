"""
DeerFlow V4 — report_agent.py
Agent autonome de génération de rapports techniques complets.
Produit des rapports Word (.docx) ou texte à la demande d'un agent.
"""
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("generated_visuals")
REPORTS_DIR.mkdir(exist_ok=True)


def generate_equipment_report(tag: str, output_format: str = "text") -> str:
    """
    Génère un rapport technique complet sur un équipement.
    Croise : Knowledge Graph et Data Sheets.
    output_format : "text" (toujours disponible) ou "docx" (nécessite python-docx)
    """
    try:
        report_data = _collect_equipment_data(tag)
        
        if output_format == "docx":
            return _generate_docx_report(tag, report_data)
        else:
            return _generate_text_report(tag, report_data)
    except Exception as e:
        logger.error("[ReportAgent] Erreur génération rapport %s: %s", tag, e)
        return f"Erreur lors de la génération du rapport pour {tag}: {e}"


def call_llm_sync(prompt: str, system_prompt: str = "") -> str:
    """Appelle Ollama de manière synchrone avec un timeout court pour extraction rapide."""
    try:
        import httpx
        from config import OLLAMA_BASE_URL, OLLAMA_MODEL, LLM_TEMPERATURE
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        # Timeout court (45s) et contexte réduit (2048) pour une réponse JSON rapide
        with httpx.Client(timeout=45) as client:
            response = client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": LLM_TEMPERATURE,
                        "num_predict": 250,   # JSON court = suffisant
                        "num_ctx": 2048,       # Contexte réduit = réponse plus rapide
                    },
                },
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.warning("[ReportAgent] LLM sync extraction skipped (timeout or error): %s", e)
    return ""


def _collect_equipment_data(tag: str) -> Dict[str, Any]:
    """Collecte toutes les données disponibles sur un équipement."""
    data = {"tag": tag.upper(), "timestamp": datetime.now().isoformat()}
    
    # 1. Knowledge Graph
    try:
        from knowledge_graph import get_neo4j_kg
        kg = get_neo4j_kg()
        if kg.disponible():
            kg_info = kg.chercher_equipement(tag)
            data["kg"] = kg_info
            impact = kg.analyser_impact(tag, profondeur=2)
            data["impact"] = impact
    except Exception as e:
        data["kg"] = {}
        logger.debug("[ReportAgent] KG unavailable: %s", e)
    
    # 2. Documents (BM25 / Chroma)
    try:
        from retriever import get_retriever
        retriever = get_retriever()
        docs = retriever.retrieve(f"{tag} fournisseur prix delai livraison specification technique")
        data["docs"] = [
            {"source": d.source, "excerpt": d.content}
            for d in docs[:4]
        ]
    except Exception as e:
        data["docs"] = []
        logger.debug("[ReportAgent] Retriever unavailable: %s", e)
    
    # 3. SCADA live (Désactivé - Focus Ingénierie)
    data["scada"] = {}
        
    # 4. Synthèse IA enrichie (Fournisseur, Montant, Délai de livraison, Détails techniques)
    commercial_info = {
        "fournisseur": "Non identifié dans les documents",
        "montant": "Non spécifié dans les documents",
        "delai_livraison": "Non spécifié dans les documents",
        "synthese_technique": "Aucune spécification technique extraite par IA."
    }
    
    if data.get("docs"):
        context_text = "\n\n".join([
            f"--- Extrait du document : {d['source']} ---\n{d['excerpt'][:500]}"
            for d in data["docs"]
        ])
        
        prompt = f"""
Analyse les extraits documentaires suivants concernant l'équipement "{tag.upper()}".
Extraits :
{context_text}

Remplis et retourne UNIQUEMENT un objet JSON contenant les informations suivantes extraites de ces documents (ne mets pas de texte avant ou après le JSON) :
{{
  "fournisseur": "nom du fournisseur ou constructeur de l'équipement (ou 'Non identifié' si absent)",
  "montant": "prix, montant ou coût d'acquisition de l'équipement avec sa devise (ou 'Non spécifié' si absent)",
  "delai_livraison": "délai de livraison ou date de livraison (ou 'Non spécifié' si absent)",
  "synthese_technique": "un résumé des caractéristiques techniques clés (matériaux, pressions de calcul, température, dimensions, puissance, débit) extraites de ces documents (ou 'Non identifié' si absent)"
}}
"""
        system_prompt = "Tu es un extracteur d'informations techniques et financières précis qui ne retourne que du JSON valide."
        
        raw_json = call_llm_sync(prompt, system_prompt)
        if raw_json:
            try:
                import json
                clean_json = raw_json.strip()
                if clean_json.startswith("```"):
                    clean_json = clean_json.split("\n", 1)[1]
                if clean_json.endswith("```"):
                    clean_json = clean_json.rsplit("\n", 1)[0]
                if clean_json.startswith("json"):
                    clean_json = clean_json[4:].strip()
                clean_json = clean_json.strip()
                
                extracted = json.loads(clean_json)
                for k in commercial_info:
                    if k in extracted and extracted[k]:
                        commercial_info[k] = extracted[k]
            except Exception as e:
                logger.error("[ReportAgent] Failed parsing LLM commercial JSON: %s (Raw: %s)", e, raw_json)

    data["commercial"] = commercial_info
    return data


def _generate_text_report(tag: str, data: Dict[str, Any]) -> str:
    """Génère un rapport au format texte structuré."""
    lines = [
        f"{'='*60}",
        f"  RAPPORT TECHNIQUE — {data['tag']}",
        f"  Généré le : {data['timestamp']}",
        f"{'='*60}",
        "",
    ]
    
    comm = data.get("commercial", {})
    if comm:
        lines.append("── SYNTHÈSE COMMERCIALE & TECHNIQUE (IA) ───────────────")
        lines.append(f"  Fournisseur         : {comm.get('fournisseur', 'Non identifié')}")
        lines.append(f"  Montant / Coût      : {comm.get('montant', 'Non spécifié')}")
        lines.append(f"  Délai de livraison  : {comm.get('delai_livraison', 'Non spécifié')}")
        lines.append(f"  Détails Techniques  : {comm.get('synthese_technique', 'Non spécifié')}")
        lines.append("")

    kg = data.get("kg", {})
    if kg:
        lines.append("── DONNÉES KNOWLEDGE GRAPH (P&ID) ──────────────────────")
        lines.append(f"  Type        : {kg.get('type', 'N/A')}")
        lines.append(f"  Description : {kg.get('description', 'N/A')}")
        if kg.get("pressions"):
            lines.append(f"  Pressions   : {', '.join(kg['pressions'])}")
        if kg.get("temperatures"):
            lines.append(f"  Températures: {', '.join(kg['temperatures'])}")
        if kg.get("normes"):
            lines.append(f"  Normes      : {', '.join(kg['normes'])}")
        if kg.get("documents"):
            lines.append(f"  Sources doc : {', '.join(kg['documents'][:3])}")
        lines.append("")
    
    scada = data.get("scada", {})
    if scada:
        lines.append("── DONNÉES SCADA TEMPS RÉEL ────────────────────────────")
        for k, v in scada.items():
            if k not in ("tag", "timestamp"):
                lines.append(f"  {k:<18}: {v}")
        status = scada.get("status", "OK")
        if status == "WARNING":
            lines.append("  ⚠ ALARME ACTIVE : Intervention recommandée !")
        lines.append("")
    
    impact = data.get("impact", {})
    if impact and impact.get("equipements_impactes"):
        lines.append("── ANALYSE D'IMPACT ────────────────────────────────────")
        lines.append(f"  Équipements dépendants : {', '.join(impact['equipements_impactes'][:10])}")
        if impact.get("normes_concernees"):
            lines.append(f"  Normes à vérifier      : {', '.join(impact['normes_concernees'])}")
        lines.append("")
    
    docs = data.get("docs", [])
    if docs:
        lines.append("── EXTRAITS DOCUMENTAIRES RÉFÉRENCÉS ───────────────────")
        for d in docs:
            lines.append(f"  [Source: {d['source']}]")
            lines.append(f"  {d['excerpt'][:300]}...")
            lines.append("")
    
    lines.append(f"{'='*60}")
    lines.append("  Fin du rapport — DeerFlow V4")
    lines.append(f"{'='*60}")
    
    return "\n".join(lines)


def _generate_docx_report(tag: str, data: Dict[str, Any]) -> str:
    """Génère un rapport Word (.docx) et retourne le chemin du fichier."""
    try:
        import docx
        from docx.shared import Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        
        doc = docx.Document()
        
        # Style
        style = doc.styles['Normal']
        style.font.name = 'Segoe UI'
        style.font.size = Pt(11)
        
        # Titre
        title = doc.add_heading(f'Rapport Technique : {data["tag"]}', 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        doc.add_paragraph(f"Généré le : {data['timestamp']}")
        doc.add_paragraph()
        
        # 1. Synthèse commerciale et technique IA
        comm = data.get("commercial", {})
        if comm:
            doc.add_heading("1. Fiche Commerciale & Technique (IA RAG)", level=1)
            for k, val in [("Fournisseur", comm.get("fournisseur")), 
                           ("Montant / Coût", comm.get("montant")),
                           ("Délai de livraison", comm.get("delai_livraison")),
                           ("Synthèse Technique", comm.get("synthese_technique"))]:
                p = doc.add_paragraph()
                p.add_run(f"{k} : ").bold = True
                p.add_run(str(val))
            doc.add_paragraph()

        # 2. KG
        kg = data.get("kg", {})
        if kg:
            doc.add_heading("2. Données P&ID / Knowledge Graph", level=1)
            for k, v in [("Type", kg.get("type")), ("Description", kg.get("description")),
                         ("Pressions", ", ".join(kg.get("pressions", []))),
                         ("Normes", ", ".join(kg.get("normes", [])))]:
                if v:
                    p = doc.add_paragraph()
                    p.add_run(f"{k}: ").bold = True
                    p.add_run(str(v))
        
        # SCADA
        scada = data.get("scada", {})
        if scada:
            doc.add_heading("2. Données SCADA Temps Réel", level=1)
            tbl = doc.add_table(rows=1, cols=2)
            tbl.style = 'Table Grid'
            tbl.rows[0].cells[0].text = "Paramètre"
            tbl.rows[0].cells[1].text = "Valeur"
            for k, v in scada.items():
                if k not in ("tag", "timestamp"):
                    row = tbl.add_row()
                    row.cells[0].text = str(k)
                    row.cells[1].text = str(v)
        
        # Docs
        docs = data.get("docs", [])
        if docs:
            doc.add_heading("3. Références Documentaires", level=1)
            for d in docs:
                p = doc.add_paragraph()
                p.add_run(f"[{d['source']}] ").bold = True
                p.add_run(d["excerpt"][:300])
        
        # Sauvegarde
        fname = f"rapport_{data['tag'].replace('-', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"
        fpath = REPORTS_DIR / fname
        doc.save(str(fpath))
        
        return (
            f"✅ Rapport DOCX généré avec succès !\n"
            f"  Fichier : {fname}\n"
            f"  Chemin  : {fpath}\n"
            f"  URL     : /visuals/{fname}"
        )
    except ImportError:
        logger.warning("[ReportAgent] python-docx non installé, fallback texte.")
        return _generate_text_report(data["tag"], data)
    except Exception as e:
        return f"Erreur génération DOCX: {e}"
