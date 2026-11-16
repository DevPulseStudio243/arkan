"""
obsidian_vault_engine.py
========================
Moteur de Vault Obsidian pour ARKAN EPC Intelligence.
Transforme l'ensemble des connaissances d'ARKAN (Projets, Contrats, Équipements,
Dossiers Réglementaires ARH, Normes de construction et Mémoire des Agents)
en un Second Cerveau local structuré en Markdown interconnecté par [[wikilinks]].

Compatible à 100% avec l'application Obsidian, visualisable en Graph View & Mindmap,
et auditable directement par les ingénieurs EPC et les agents autonomes (DOTS).
"""

import os
import re
import json
import logging
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple

logger = logging.getLogger("obsidian_vault")
logger.setLevel(logging.INFO)

# Répertoire racine du projet et du Vault Obsidian
PROJECT_ROOT = Path("d:/DATA BASE IA")
VAULT_DIR = PROJECT_ROOT / "arkan_vault"

# Sous-dossiers structurés selon les meilleures pratiques PKM / Obsidian
DIR_INDEX = VAULT_DIR / "00_Index"
DIR_PROJECTS = VAULT_DIR / "01_Projets"
DIR_CONTRACTS = VAULT_DIR / "02_Contrats"
DIR_EQUIPMENT = VAULT_DIR / "03_Equipements"
DIR_ARH = VAULT_DIR / "04_Dossiers_ARH"
DIR_STANDARDS = VAULT_DIR / "05_Normes_EPC"
DIR_AGENT_MEMORY = VAULT_DIR / "06_Memoire_Agents"
DIR_OBSIDIAN = VAULT_DIR / ".obsidian"

ALL_VAULT_DIRS = [
    VAULT_DIR,
    DIR_INDEX,
    DIR_PROJECTS,
    DIR_CONTRACTS,
    DIR_EQUIPMENT,
    DIR_ARH,
    DIR_STANDARDS,
    DIR_AGENT_MEMORY,
    DIR_OBSIDIAN
]

WIKILINK_REGEX = re.compile(r"\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]")


def ensure_vault_directories():
    """Initialise l'arborescence du Vault sur le disque."""
    for d in ALL_VAULT_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    
    # Configuration par défaut pour Obsidian si inexistante
    app_json = DIR_OBSIDIAN / "app.json"
    if not app_json.exists():
        app_json.write_text(json.dumps({
            "useMarkdownLinks": False,
            "newFileFolderPath": "06_Memoire_Agents",
            "showLineNumber": True,
            "readableLineLength": True
        }, indent=2), encoding="utf-8")

    graph_json = DIR_OBSIDIAN / "graph.json"
    if not graph_json.exists():
        graph_json.write_text(json.dumps({
            "collapse-filter": False,
            "search": "",
            "threshold": -3,
            "repelStrength": 10,
            "linkStrength": 1,
            "linkDistance": 250,
            "scale": 1.0,
            "close": False
        }, indent=2), encoding="utf-8")


def sanitize_filename(name: str) -> str:
    """Nettoie une chaîne pour en faire un nom de fichier valide sans corrompre les tags techniques."""
    if not name:
        return "Sans_Nom"
    s = re.sub(r'[\\/*?:"<>|]', '_', str(name)).strip()
    s = re.sub(r'\s+', ' ', s)
    return s[:120].strip() or "Sans_Nom"


# =============================================================================
# SYNCHRONISATION DES NORMES ET STANDARDS EPC
# =============================================================================

DEFAULT_EPC_STANDARDS = [
    {
        "code": "ASME_B31.3",
        "title": "Process Piping Design & Construction",
        "discipline": "Tuyauterie Industrielle & P&ID",
        "description": "Code de conception, fabrication, inspection et essais sous pression pour la tuyauterie de procédé pétrochimique et raffinage.",
        "key_rules": [
            "Calcul d'épaisseur minimale de paroi selon pression et contrainte admissible (Formule ASME B31.3 §304.1.2)",
            "Épreuve hydrostatique obligatoire à 1.5 x Pression de calcul (ou pneumatique à 1.1x)",
            "Critères de contrôle non destructif (CND/NDT) selon la sévérité du fluide (Catégorie D, Normal, Fluide Toxique M)"
        ],
        "tags": ["ASME", "Tuyauterie", "Procédé", "Hydrotest", "P&ID"]
    },
    {
        "code": "ASME_VIII_Div1",
        "title": "Boiler & Pressure Vessel Code (Appareils à Pression)",
        "discipline": "Équipements Mécaniques Sous Pression",
        "description": "Règles pour la construction des appareils à pression non soumis à la flamme (séparateurs, colonnes, ballons de recette).",
        "key_rules": [
            "Surépaisseur de corrosion minimale (Corrosion Allowance) de 3.0 mm en milieu hydrocarbures humides",
            "Calcul du facteur de joint de soudure (E = 1.0 pour radiographie 100%, 0.85 pour contrôle partiel spot)",
            "Pression d'épreuve hydrostatique en atelier = 1.3 x MAWP x (S_test / S_design)"
        ],
        "tags": ["ASME", "Appareils_Pression", "Ballons", "Separateurs", "ARH"]
    },
    {
        "code": "API_650",
        "title": "Welded Tanks for Oil Storage (Bacs de Stockage)",
        "discipline": "Stockage Hydrocarbures",
        "description": "Norme internationale régissant la conception et l'érection des réservoirs cylindriques verticaux de stockage pétrolier.",
        "key_rules": [
            "Conception du fond et robe selon la méthode One-Foot Method ou Variable-Design-Point Method",
            "Dispositifs d'ancrage sismique et contre le vent (Wind Girder)",
            "Évacuation d'urgence et toits flottants avec joints d'étanchéité double lèvre"
        ],
        "tags": ["API", "Stockage", "Bacs", "Raffinerie", "Sonatrach"]
    },
    {
        "code": "Reglementation_ARH_Algerie",
        "title": "Réglementation ARH & Sécurité Industrielle Sonatrach",
        "discipline": "Conformité Réglementaire Sonatrach / ARH",
        "description": "Cadre réglementaire de l'Autorité de Régulation des Hydrocarbures (ARH) en Algérie pour l'homologation des dossiers techniques d'installations pétrolières.",
        "key_rules": [
            "Concordance tripartite obligatoire : P&ID révisé = Lignes List certifiée = Plans d'ensemble ISO",
            "PV d'épreuve hydrostatique validé avec manomètre étalonné et enregistreur de pression certifié",
            "Traçabilité intégrale des certificats matière EN 10204 3.1 avec numéro de coulée (Heat No.) rattaché au plan"
        ],
        "tags": ["ARH", "Sonatrach", "Réglementation", "Homologation", "Contrôle"]
    }
]


def sync_standards_to_vault():
    """Génère les fiches de normes EPC dans le Vault."""
    for std in DEFAULT_EPC_STANDARDS:
        filename = f"{sanitize_filename(std['code'])}.md"
        filepath = DIR_STANDARDS / filename
        content = f"""---
id: "{std['code']}"
type: "norme_epc"
titre: "{std['title']}"
discipline: "{std['discipline']}"
tags: {json.dumps(std['tags'], ensure_ascii=False)}
updated_at: "{datetime.now().isoformat()}"
---

# [[{std['code']}]] — {std['title']}

> **Discipline :** `{std['discipline']}`  
> **Type de Référentiel :** Norme Internationale & Réglementaire EPC

## 1. Description & Domaine d'Application
{std['description']}

## 2. Exigences Techniques Majeures
{chr(10).join(f"- {r}" for r in std['key_rules'])}

## 3. Connexions Métier & Dossiers Associés
- Voir l'index général : [[MOC_Master]]
- Voir la réglementation nationale : [[Reglementation_ARH_Algerie]]
- Équipements soumis à cette norme : Rechercher dans [[03_Equipements/]]
"""
        filepath.write_text(content, encoding="utf-8")


# =============================================================================
# SYNCHRONISATION DES PROJETS & CONTRATS DEPUIS PROCUREMENT.DB
# =============================================================================

def get_procurement_data_from_sqlite() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Extrait directement les projets, contrats et articles de la base SQLite procurement.db."""
    db_path = PROJECT_ROOT / "data" / "procurement.db"
    if not db_path.exists():
        return [], [], []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM procurement_projects ORDER BY name ASC")
        projects = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM contracts ORDER BY created_at DESC")
        contracts = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM contract_items ORDER BY contract_id, reference ASC")
        items = [dict(r) for r in cursor.fetchall()]

        return projects, contracts, items
    except Exception as e:
        logger.error(f"Erreur lecture SQLite procurement: {e}")
        return [], [], []
    finally:
        conn.close()


def sync_projects_and_contracts_to_vault() -> Dict[str, int]:
    """Synchronise Projets, Contrats et Équipements de SQLite vers le Vault Obsidian."""
    projects, contracts, items = get_procurement_data_from_sqlite()

    # Mappage des items par contrat
    items_by_contract: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        cid = it.get("contract_id")
        items_by_contract.setdefault(cid, []).append(it)

    # Mappage des contrats par projet
    contracts_by_project: Dict[str, List[Dict[str, Any]]] = {}
    for c in contracts:
        pid = c.get("project_id") or "general"
        contracts_by_project.setdefault(pid, []).append(c)

    counts = {"projects": 0, "contracts": 0, "items": 0}

    # 1. Génération des fiches Projets
    # Assurer au moins le projet "general" si non présent
    project_ids_seen = set()
    for proj in projects:
        pid = proj["id"]
        project_ids_seen.add(pid)
        pname = proj.get("name") or pid
        pcode = proj.get("code") or ""
        pdesc = proj.get("description") or "Projet EPC"
        proj_contracts = contracts_by_project.get(pid, [])

        filename = f"{sanitize_filename(pname)}.md"
        filepath = DIR_PROJECTS / filename

        contracts_links = []
        total_budget = 0.0
        for ctr in proj_contracts:
            c_num = ctr.get("numero_contrat") or ctr.get("id")
            c_fourn = ctr.get("fournisseur") or "Fournisseur"
            c_label = f"{c_num} - {c_fourn}"
            contracts_links.append(f"- [[{c_label}]] (Fournisseur: {c_fourn} | Montant: {float(ctr.get('montant') or 0):,.2f} {ctr.get('devise', 'DZD')})")
            total_budget += float(ctr.get("montant") or 0.0)

        contracts_text = "\n".join(contracts_links) if contracts_links else "*(Aucun contrat rattaché pour le moment)*"

        content = f"""---
id: "{pid}"
type: "projet_epc"
nom: "{pname}"
code: "{pcode}"
total_contrats: {len(proj_contracts)}
budget_engage: {total_budget:.2f}
updated_at: "{datetime.now().isoformat()}"
---

# [[{pname}]]

> **Code Projet :** `{pcode or 'N/A'}`  
> **Statut :** En cours d'exécution EPC  
> **Nombre de Contrats :** {len(proj_contracts)}  
> **Engagement Total :** `{total_budget:,.2f} DZD`

## 1. Description du Projet & Localisation
{pdesc}

## 2. Contrats & Commandes d'Approvisionnement Rattachés
{contracts_text}

## 3. Relations & Deuxième Cerveau
- Index global des Projets : [[MOC_Master]]
- Référentiel Réglementaire Applicable : [[Reglementation_ARH_Algerie]]
- Norme de Tuyauterie : [[ASME_B31.3]]
- Norme Appareils sous Pression : [[ASME_VIII_Div1]]
"""
        filepath.write_text(content, encoding="utf-8")
        counts["projects"] += 1

    # 2. Génération des fiches Contrats et des Équipements
    for ctr in contracts:
        cid = ctr["id"]
        c_num = ctr.get("numero_contrat") or "CTR-SANS-NUMERO"
        c_fourn = ctr.get("fournisseur") or "Fournisseur Inconnu"
        c_objet = ctr.get("objet") or "Fourniture d'équipements et matériels EPC"
        c_montant = float(ctr.get("montant") or 0.0)
        c_devise = ctr.get("devise") or "DZD"
        c_delai = ctr.get("delai_livraison") or "Non spécifié"
        c_doc_path = ctr.get("document_path") or ""
        pid = ctr.get("project_id") or "general"

        # Trouver le nom du projet
        matching_proj = next((p for p in projects if p["id"] == pid), None)
        proj_name = matching_proj.get("name") if matching_proj else pid

        c_title = f"{c_num} - {c_fourn}"
        filename = f"{sanitize_filename(c_title)}.md"
        filepath = DIR_CONTRACTS / filename

        ctr_items = items_by_contract.get(cid, [])

        items_md_list = []
        for it in ctr_items:
            it_id = it.get("id")
            it_ref = it.get("reference") or "ITEM"
            it_desig = it.get("designation") or "Désignation matériel"
            it_qty = float(it.get("quantite_contractuelle") or 1.0)
            it_unit = it.get("unite") or "U"
            it_pu = float(it.get("prix_unitaire") or 0.0)
            it_delai = it.get("delai_livraison") or c_delai

            eq_title = f"{it_ref} - {it_desig[:60].strip()}"
            items_md_list.append(f"- [[{eq_title}]] | Qté: **{it_qty} {it_unit}** | P.U: **{it_pu:,.2f} {c_devise}** | Délai: *{it_delai}*")

            # Créer la note individuelle pour cet Équipement / Article dans 03_Equipements
            eq_filename = f"{sanitize_filename(eq_title)}.md"
            eq_filepath = DIR_EQUIPMENT / eq_filename
            eq_content = f"""---
id: "{it_id}"
type: "equipement_materiel"
reference_tag: "{it_ref}"
designation: "{it_desig}"
quantite: {it_qty}
unite: "{it_unit}"
prix_unitaire: {it_pu:.2f}
devise: "{c_devise}"
contrat_source: "[[{c_title}]]"
projet: "[[{proj_name}]]"
fournisseur: "{c_fourn}"
updated_at: "{datetime.now().isoformat()}"
---

# [[{eq_title}]]

> **Tag / Repère Matériel :** `{it_ref}`  
> **Contrat d'Achat :** [[{c_title}]]  
> **Projet EPC :** [[{proj_name}]]  
> **Fournisseur :** `{c_fourn}`

## 1. Spécifications & Données d'Achat
- **Désignation Complète :** {it_desig}
- **Quantité Contractuelle :** `{it_qty} {it_unit}`
- **Prix Unitaire :** `{it_pu:,.2f} {c_devise}`
- **Montant Ligne :** `{(it_qty * it_pu):,.2f} {c_devise}`
- **Délai d'Acheminement Chantier :** `{it_delai}`

## 2. Traçabilité & Contrôles d'Ingénierie
- Norme de Construction / Conception : [[ASME_B31.3]] / [[ASME_VIII_Div1]]
- Réception Matière : Certificat 3.1 & Contrôle Dimensionnel
- Dossier Réglementaire ARH : [[Reglementation_ARH_Algerie]]
"""
            eq_filepath.write_text(eq_content, encoding="utf-8")
            counts["items"] += 1

        items_text = "\n".join(items_md_list) if items_md_list else "*(Aucun article enregistré dans ce bordereau)*"

        pdf_link_text = f"[Consulter le Document PDF]({c_doc_path})" if c_doc_path else "*(Aucun fichier PDF joint au contrat)*"

        content = f"""---
id: "{cid}"
type: "contrat_procurement"
numero_contrat: "{c_num}"
fournisseur: "{c_fourn}"
montant_ht: {c_montant:.2f}
devise: "{c_devise}"
projet_id: "{pid}"
projet_nom: "[[{proj_name}]]"
nombre_articles: {len(ctr_items)}
document_path: "{c_doc_path}"
updated_at: "{datetime.now().isoformat()}"
---

# [[{c_title}]]

> **Projet Parent :** [[{proj_name}]]  
> **Fournisseur Contractuel :** `{c_fourn}`  
> **Montant Global HT :** `{c_montant:,.2f} {c_devise}`  
> **Délai de Livraison :** `{c_delai}`  
> **Fichier Document :** {pdf_link_text}

## 1. Objet du Contrat & Prestation
{c_objet}

## 2. Bordereau des Prix Unitaire (BPU) & Équipements Commandés
{items_text}

## 3. Liens de Navigation & Conformité
- Projet rattaché : [[{proj_name}]]
- Norme Tuyauterie Process : [[ASME_B31.3]]
- Exigences ARH Sonatrach : [[Reglementation_ARH_Algerie]]
- Index général du Second Cerveau : [[MOC_Master]]
"""
        filepath.write_text(content, encoding="utf-8")
        counts["contracts"] += 1

    return counts


# =============================================================================
# SYNCHRONISATION DES DOSSIERS ET REMARQUES ARH
# =============================================================================

def sync_arh_dossiers_to_vault() -> int:
    """Synchronise les dossiers techniques ARH existants dans le Vault."""
    arh_count = 0
    arh_db = PROJECT_ROOT / "data" / "arh_compliance.db"
    dossiers = []

    if arh_db.exists():
        conn = sqlite3.connect(str(arh_db))
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dossiers'")
            if cursor.fetchone():
                cursor.execute("SELECT * FROM dossiers")
                dossiers = [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.debug(f"Lecture dossiers ARH: {e}")
        finally:
            conn.close()

    # Si aucun dossier dans la base, on génère la structure modèle du dossier ARH
    if not dossiers:
        dossiers = [{
            "id": "ARH-DOSSIER-PILOTE",
            "titre": "Dossier Technique Réglementaire ARH - Pilote",
            "statut": "En cours de revue de conformité",
            "pieces_count": 6,
            "remarques": "Vérification de la conformité du P&ID et des épreuves hydrostatiques"
        }]

    for d in dossiers:
        did = d.get("id") or "ARH-01"
        dtitre = d.get("titre") or f"Dossier ARH {did}"
        filename = f"{sanitize_filename(dtitre)}.md"
        filepath = DIR_ARH / filename

        content = f"""---
id: "{did}"
type: "dossier_arh"
titre: "{dtitre}"
statut: "{d.get('statut', 'En revue')}"
updated_at: "{datetime.now().isoformat()}"
---

# [[{dtitre}]]

> **Référence Dossier :** `{did}`  
> **Organisme Régulateur :** Autorité de Régulation des Hydrocarbures (ARH)  
> **Référentiel Obligatoire :** [[Reglementation_ARH_Algerie]]

## 1. Synthèse de Conformité
Ce dossier regroupe les pièces techniques réglementaires requises pour l'homologation d'exploitation pétrolière.

## 2. Normes & Standards Associés
- [[ASME_B31.3]] (Tuyauterie & Essais de Pression)
- [[ASME_VIII_Div1]] (Appareils à Pression)
- [[API_650]] (Bacs de Stockage)

## 3. Matrice de Concordance
- Équipements contrôlés : Voir les fiches d'équipements rattachées dans [[03_Equipements/]]
- Index général : [[MOC_Master]]
"""
        filepath.write_text(content, encoding="utf-8")
        arh_count += 1

    return arh_count


# =============================================================================
# SYNCHRONISATION DE LA MÉMOIRE DES AGENTS (DOTS / APPRENTISSAGE)
# =============================================================================

def sync_agent_memory_to_vault():
    """Génère les fiches de mémoire persistante et leçons apprises par les agents."""
    log_file = DIR_AGENT_MEMORY / "DOTS_Decision_Log.md"
    if not log_file.exists():
        log_file.write_text(f"""---
id: "dots-memory-log"
type: "memoire_agent"
titre: "Journal des Décisions & Mémoire DOTS"
updated_at: "{datetime.now().isoformat()}"
---

# [[DOTS_Decision_Log]] — Journal des Décisions & Apprentissage Autonome

Ce document constitue la **mémoire cumulative permanente** des agents ARKAN (DOTS 24/7, Spécialistes P&ID, Superviseur Procurement et Arbitre ARH).

## 1. Règles d'Extraction & Bonnes Pratiques Apprises
- **Extraction NuExtract-3 sur Bordereaux Algériens :** Prioriser la détection des unités standards EPC (`U`, `LOT`, `ENS`, `M`, `KG`). En cas de mention forfaitaire ("compris"), attribuer l'unité `LOT` et la référence de regroupement.
- **Concordance ARH :** Ne jamais valider une épreuve hydrostatique sans vérifier la température minimale de conception métal (MDMT) selon la courbe d'impact [[ASME_VIII_Div1]].

## 2. Points de Vigilance Fournisseurs
- Suivi rigoureux des délais d'acheminement et des certificats matière 3.1.

## 3. Liens de Navigation
- Référentiel des Projets : [[MOC_Master]]
""", encoding="utf-8")


# =============================================================================
# GÉNÉRATION DU MASTER MAP OF CONTENT (MOC_MASTER.MD)
# =============================================================================

def generate_master_moc():
    """Génère le Map of Content (MOC) central qui relie l'ensemble du Vault."""
    projects_notes = sorted([p.stem for p in DIR_PROJECTS.glob("*.md")])
    contracts_notes = sorted([c.stem for c in DIR_CONTRACTS.glob("*.md")])
    standards_notes = sorted([s.stem for s in DIR_STANDARDS.glob("*.md")])
    arh_notes = sorted([a.stem for a in DIR_ARH.glob("*.md")])
    eq_count = len(list(DIR_EQUIPMENT.glob("*.md")))

    content = f"""---
id: "moc-master"
type: "map_of_content"
titre: "Second Cerveau d'Ingénierie EPC — Carte Générale"
total_projets: {len(projects_notes)}
total_contrats: {len(contracts_notes)}
total_equipements: {eq_count}
total_normes: {len(standards_notes)}
updated_at: "{datetime.now().isoformat()}"
---

# 🧠 Second Cerveau EPC — ARKAN Obsidian Mind Vault

Bienvenue dans le **Cerveau d'Ingénierie Unifié d'ARKAN**.  
Toutes les données techniques, contractuelles et réglementaires sont stockées en fichiers Markdown locaux interconnectés par `[[wikilinks]]`.

---

## 📁 1. Projets EPC Actifs ({len(projects_notes)})
{chr(10).join(f"- [[{p}]]" for p in projects_notes) if projects_notes else "*(Aucun projet)*"}

## 📜 2. Contrats & Commandes d'Approvisionnement ({len(contracts_notes)})
{chr(10).join(f"- [[{c}]]" for c in contracts_notes) if contracts_notes else "*(Aucun contrat)*"}

## ⚙️ 3. Équipements & Articles Répertoriés ({eq_count})
Les équipements et articles de bordereaux sont indexés individuellement dans le dossier `03_Equipements/` et reliés à leurs contrats d'origine.

## 🛡️ 4. Conformité Réglementaire & Dossiers ARH ({len(arh_notes)})
{chr(10).join(f"- [[{a}]]" for a in arh_notes) if arh_notes else "*(Aucun dossier ARH)*"}

## 📚 5. Référentiels & Normes de Construction ({len(standards_notes)})
{chr(10).join(f"- [[{s}]]" for s in standards_notes) if standards_notes else "*(Aucune norme)*"}

## 🤖 6. Mémoire & Apprentissages des Agents IA
- [[DOTS_Decision_Log]] — Journal des décisions et règles apprises

---
*Dernière synchronisation automatique : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    (DIR_INDEX / "MOC_Master.md").write_text(content, encoding="utf-8")


# =============================================================================
# EXTRACTION DU GRAPHE DE CONNAISSANCES (NODES & EDGES) POUR L'INTERFACE
# =============================================================================

CLUSTER_META = {
    "projet_epc": {"cluster": "projects", "label": "Projet EPC", "color": "#38BDF8", "icon": "ph-folder"},
    "contrat_procurement": {"cluster": "contracts", "label": "Contrat d'Achat", "color": "#EC4899", "icon": "ph-file-text"},
    "equipement_materiel": {"cluster": "equipment", "label": "Équipement / Article", "color": "#10B981", "icon": "ph-gear"},
    "dossier_arh": {"cluster": "arh", "label": "Dossier ARH", "color": "#F59E0B", "icon": "ph-shield-check"},
    "norme_epc": {"cluster": "standards", "label": "Norme Technique", "color": "#8B5CF6", "icon": "ph-book-bookmark"},
    "memoire_agent": {"cluster": "agent_memory", "label": "Mémoire Agent IA", "color": "#06B6D4", "icon": "ph-brain"},
    "map_of_content": {"cluster": "index", "label": "Index Central MOC", "color": "#F43F5E", "icon": "ph-compass"},
}


def build_vault_knowledge_graph() -> Dict[str, Any]:
    """
    Parcourt l'ensemble du Vault Obsidian pour extraire le graphe de connaissances :
    tous les nœuds (notes Markdown) et toutes les arêtes (liens [[wikilinks]]).
    """
    ensure_vault_directories()

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    nodes_by_key: Dict[str, Dict[str, Any]] = {}
    edges_set: Set[Tuple[str, str]] = set()

    md_files = list(VAULT_DIR.rglob("*.md"))

    for fpath in md_files:
        if ".obsidian" in fpath.parts:
            continue

        raw_text = fpath.read_text(encoding="utf-8", errors="replace")
        rel_path = fpath.relative_to(VAULT_DIR).as_posix()
        stem = fpath.stem

        # Analyse du Frontmatter YAML basique
        frontmatter = {}
        content_body = raw_text
        if raw_text.startswith("---"):
            parts = raw_text.split("---", 2)
            if len(parts) >= 3:
                yaml_block = parts[1]
                content_body = parts[2]
                for line in yaml_block.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        frontmatter[k] = v

        node_type = frontmatter.get("type", "note")
        meta = CLUSTER_META.get(node_type, {
            "cluster": "general",
            "label": "Note",
            "color": "#94A3B8",
            "icon": "ph-notepad"
        })

        # Premier paragraphe ou résumé
        snippet_lines = [l.strip() for l in content_body.splitlines() if l.strip() and not l.startswith("#") and not l.startswith(">")]
        snippet = snippet_lines[0] if snippet_lines else ""

        node_obj = {
            "id": stem,
            "title": frontmatter.get("titre") or frontmatter.get("nom") or stem,
            "path": rel_path,
            "type": node_type,
            "cluster": meta["cluster"],
            "cluster_label": meta["label"],
            "color": meta["color"],
            "icon": meta["icon"],
            "snippet": snippet[:200],
            "frontmatter": frontmatter,
            "outgoing_count": 0,
            "incoming_count": 0
        }
        nodes_by_key[stem.lower()] = node_obj
        nodes.append(node_obj)

    # Deuxième passe : extraire les arêtes [[wikilinks]]
    for fpath in md_files:
        if ".obsidian" in fpath.parts:
            continue
        raw_text = fpath.read_text(encoding="utf-8", errors="replace")
        src_stem = fpath.stem
        src_node = nodes_by_key.get(src_stem.lower())
        if not src_node:
            continue

        matches = WIKILINK_REGEX.findall(raw_text)
        for target_link, alias in matches:
            target_link = target_link.strip()
            # Nettoyage si le lien contient un chemin ou extension .md
            target_clean = Path(target_link).stem.lower()

            target_node = nodes_by_key.get(target_clean)
            if target_node and target_node["id"] != src_node["id"]:
                edge_pair = (src_node["id"], target_node["id"])
                if edge_pair not in edges_set:
                    edges_set.add(edge_pair)
                    edges.append({
                        "source": src_node["id"],
                        "target": target_node["id"],
                        "label": alias.strip() if alias else ""
                    })
                    src_node["outgoing_count"] += 1
                    target_node["incoming_count"] += 1

    return {
        "status": "success",
        "vault_path": str(VAULT_DIR),
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "nodes": nodes,
        "edges": edges,
        "clusters": CLUSTER_META
    }


# =============================================================================
# SYNCHRONISATION GLOBALE DU SECOND CERVEAU
# =============================================================================

def sync_full_vault() -> Dict[str, Any]:
    """Exécute une synchronisation complète et retourne les statistiques du Vault."""
    ensure_vault_directories()
    sync_standards_to_vault()
    proc_counts = sync_projects_and_contracts_to_vault()
    arh_count = sync_arh_dossiers_to_vault()
    sync_agent_memory_to_vault()
    generate_master_moc()

    graph = build_vault_knowledge_graph()

    return {
        "status": "success",
        "synced_at": datetime.now().isoformat(),
        "vault_dir": str(VAULT_DIR),
        "counts": {
            "projects": proc_counts["projects"],
            "contracts": proc_counts["contracts"],
            "equipment": proc_counts["items"],
            "arh": arh_count,
            "standards": len(DEFAULT_EPC_STANDARDS),
            "total_nodes": graph["total_nodes"],
            "total_edges": graph["total_edges"]
        }
    }


def read_note_content(relative_path: str) -> Dict[str, Any]:
    """Lit une note Markdown dans le Vault et extrait ses liens entrants et sortants."""
    clean_rel = relative_path.lstrip("/\\")
    filepath = (VAULT_DIR / clean_rel).resolve()

    # Sécurité traversal
    if not str(filepath).startswith(str(VAULT_DIR.resolve())):
        raise ValueError("Chemin de note non autorisé en dehors du Vault.")

    if not filepath.exists() or not filepath.is_file():
        # Essayer de trouver par stem
        candidates = list(VAULT_DIR.rglob(f"{Path(clean_rel).stem}.md"))
        if candidates:
            filepath = candidates[0]
        else:
            raise FileNotFoundError(f"Note introuvable : {clean_rel}")

    raw_text = filepath.read_text(encoding="utf-8", errors="replace")
    stem = filepath.stem

    # Chercher les backlinks (notes qui pointent vers cette note)
    backlinks = []
    wikilink_pattern = re.compile(rf"\[\[{re.escape(stem)}(?:\|[^\]]+)?\]\]", re.IGNORECASE)

    for other_file in VAULT_DIR.rglob("*.md"):
        if other_file.stem.lower() == stem.lower() or ".obsidian" in other_file.parts:
            continue
        try:
            txt = other_file.read_text(encoding="utf-8", errors="replace")
            if wikilink_pattern.search(txt):
                backlinks.append({
                    "id": other_file.stem,
                    "path": other_file.relative_to(VAULT_DIR).as_posix()
                })
        except Exception:
            pass

    return {
        "status": "success",
        "stem": stem,
        "path": filepath.relative_to(VAULT_DIR).as_posix(),
        "absolute_path": str(filepath),
        "content": raw_text,
        "backlinks": backlinks
    }


def append_agent_memory(title: str, content: str, tags: Optional[List[str]] = None, links: Optional[List[str]] = None) -> Dict[str, Any]:
    """Permet aux agents DOTS ou ARH d'ajouter une note de réflexion ou décision dans le Vault."""
    ensure_vault_directories()
    safe_title = sanitize_filename(title)
    filename = f"{safe_title}.md"
    filepath = DIR_AGENT_MEMORY / filename

    tag_list = tags or ["Memoire_Agent", "DOTS", "Apprentissage"]
    link_items = [f"- [[{l}]]" for l in (links or ["MOC_Master"])]

    note_text = f"""---
id: "agent-mem-{int(datetime.now().timestamp())}"
type: "memoire_agent"
titre: "{title}"
tags: {json.dumps(tag_list, ensure_ascii=False)}
created_at: "{datetime.now().isoformat()}"
---

# [[{safe_title}]]

> **Source :** Agent Autonome ARKAN  
> **Date d'Enregistrement :** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`  
> **Tags :** `{', '.join(tag_list)}`

## 1. Contexte & Décision de l'Agent
{content}

## 2. Références & Liens Croisés
{chr(10).join(link_items)}
"""
    filepath.write_text(note_text, encoding="utf-8")
    return {"status": "success", "file": str(filepath.relative_to(VAULT_DIR).as_posix())}


def open_vault_locally() -> Dict[str, Any]:
    """Ouvre le dossier Vault dans l'Explorateur Windows ou lance Obsidian s'il est associé aux protocoles."""
    ensure_vault_directories()
    try:
        if os.name == 'nt':
            os.startfile(str(VAULT_DIR))
            return {"status": "success", "message": f"Dossier Vault ouvert dans l'Explorateur : {VAULT_DIR}"}
        else:
            subprocess.Popen(["xdg-open", str(VAULT_DIR)])
            return {"status": "success", "message": f"Dossier Vault ouvert : {VAULT_DIR}"}
    except Exception as e:
        logger.error(f"Erreur ouverture locale du Vault: {e}")
        return {"status": "error", "detail": str(e)}
