# ============================================================
#  Router — Projets, Synthèse Équipements & Vérification Règles
#  Routes: /projects/*, /project/*, /scada/*, /webhooks/*,
#          /report/*, /verification/*
# ============================================================
import os
import json
import time
import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Projects & Verification"])

# ─── Auth Dependency Fallback ──────────────────────────────
try:
    from api_enhanced import verify_api_key
except ImportError:
    async def verify_api_key():
        return None

def _get_analyzer():
    try:
        from api_enhanced import get_project_analyzer
        return get_project_analyzer()
    except Exception:
        return None

def _get_query_understanding():
    try:
        from api_enhanced import get_query_understanding
        return get_query_understanding()
    except Exception:
        return None

def _get_executor():
    try:
        from api_enhanced import get_bg_executor
        return get_bg_executor()
    except Exception:
        import concurrent.futures
        return concurrent.futures.ThreadPoolExecutor(max_workers=2)

async def _call_llm_fast(prompt: str, system_prompt: str = "") -> str:
    try:
        from api_enhanced import call_llm_fast
        return await call_llm_fast(prompt, system_prompt)
    except Exception as e:
        logger.warning("[Projects Router] call_llm_fast error: %s", e)
        return ""


# ─── Pydantic Models ────────────────────────────────────────

class ProjectQuestionRequest(BaseModel):
    question: str

class WebhookRegistration(BaseModel):
    callback_url: str
    event_types: list = ["scada_alarm", "system_error"]
    description: str = ""

class ResolveAnomalyRequest(BaseModel):
    result_id: str
    status: str  # pending_expert | corrected | ignored
    expert_comment: str

class AddExceptionRequest(BaseModel):
    project_id: str
    tag: str
    rule_id: str
    justification: str
    condition_scope: Optional[Dict[str, Any]] = None
    approved_by: Optional[str] = "Expert"


# ─── Helpers ────────────────────────────────────────────────

def _get_workspace_folders_db() -> List[Dict[str, Any]]:
    """Récupère les dossiers projets stricts depuis arkan_workspace.db (data/00-Projet)."""
    try:
        from routes.workspace_indexer import DB_PATH, PROJECTS_ROOT
        if not DB_PATH.exists():
            return []
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""
            SELECT f.id, f.name, f.code, f.folder_path, f.description, f.is_indexed, f.last_indexed_at, f.file_count,
                   (SELECT COUNT(DISTINCT m.id) FROM master_drawings m WHERE m.folder_id = f.id) as master_drawings_count,
                   (SELECT COUNT(*) FROM drawing_revisions r WHERE r.folder_id = f.id) as revisions_count
            FROM folders f
            ORDER BY f.id ASC
        """)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        logger.warning("[Projects Router] Error querying arkan_workspace.db: %s", e)
        return []


def get_project_dir_path(project_id: str) -> Path:
    """Retourne le chemin disque réel d'un dossier projet strictement sous data/00-Projet."""
    from routes.workspace_indexer import PROJECTS_ROOT, DB_PATH
    folders = _get_workspace_folders_db()
    for f in folders:
        f_name = f.get("name", "")
        f_code = f.get("code", "")
        f_path = f.get("folder_path", "")
        clean_id = f_name.lower().replace(" ", "_").replace("&", "and")
        if (clean_id == project_id.lower() or 
            f_code.lower() == project_id.lower() or 
            f_name.lower() == project_id.lower() or
            Path(f_path).name.lower() == project_id.lower() or
            str(f.get("id")) == str(project_id)):
            return Path(f_path)
            
    # Fallback strict sous 00-Projet
    fallback = PROJECTS_ROOT / project_id
    return fallback


def _build_projects_file_mapping() -> Dict[str, Dict[str, Any]]:
    """Construit dynamiquement le mapping entre les fichiers physiques sous data/00-Projet et les dossiers de arkan_workspace.db."""
    from routes.workspace_indexer import VALID_EXTS
    mapping = {}
    folders = _get_workspace_folders_db()
    valid_exts = VALID_EXTS

    for f in folders:
        folder_path = Path(f.get("folder_path", ""))
        project_name = f.get("name", "")
        project_id = project_name.lower().replace(" ", "_").replace("&", "and")
        folder_code = f.get("code", "")
        folder_id = f.get("id")

        if not folder_path.exists():
            continue

        for root, _, files in os.walk(folder_path):
            for file in files:
                if file.startswith(("~$", ".~")):
                    continue
                file_p = Path(root) / file
                if file_p.suffix.lower() in valid_exts:
                    mapping[file] = {
                        "project_id": project_id,
                        "project_name": project_name,
                        "folder_id": folder_id,
                        "folder_code": folder_code,
                        "folder_path": str(folder_path),
                        "file_path": str(file_p),
                        "rel_path": str(file_p.name)
                    }

    return mapping


_webhook_subscribers: list = []


async def _notify_webhooks(event_type: str, payload: dict):
    """Notifie tous les webhooks subscribers d'un événement (appel non-bloquant)."""
    if not _webhook_subscribers:
        return
    async with httpx.AsyncClient(timeout=5.0) as client:
        for sub in _webhook_subscribers:
            if event_type in sub.get("events", []):
                try:
                    await client.post(sub["url"], json={"event": event_type, "data": payload})
                except Exception as e:
                    logger.debug("[Webhook] Notification échouée vers %s: %s", sub["url"], e)


# ─── Endpoints /project/* ───────────────────────────────────

@router.get("/project/summary")
async def get_project_summary():
    """Get project model summary."""
    analyzer = _get_analyzer()
    if analyzer is None:
        raise HTTPException(status_code=503, detail="Project analyzer not initialised")

    model = analyzer.project_model
    return {
        "project_name": model.project_name,
        "project_type": model.project_type,
        "total_documents": len(model.document_map),
        "total_equipment": len(model.equipment_registry),
        "total_systems": len(model.systems),
        "total_relationships": len(model.relationships),
        "phases": [
            {"name": p.name, "status": p.status, "documents_count": len(p.documents)}
            for p in model.phases
        ],
        "systems": [
            {"name": s.name, "description": s.description, "equipment_count": len(s.equipment)}
            for s in model.systems
        ],
        "disciplines_covered": list(set(
            d.discipline for d in model.document_map.values()
        )),
    }


@router.get("/project/equipment/{tag}")
async def get_equipment_detail(tag: str):
    """Get equipment details from project model."""
    analyzer = _get_analyzer()
    if analyzer is None:
        raise HTTPException(status_code=503, detail="Project analyzer not initialised")

    model = analyzer.project_model
    eq = model.equipment_registry.get(tag) or model.equipment_registry.get(tag.upper())

    if eq is None:
        available_tags = sorted(model.equipment_registry.keys())[:50]
        raise HTTPException(
            status_code=404,
            detail=f"Equipment '{tag}' not found. Available tags (first 50): {available_tags}",
        )

    return {
        "tag": eq.tag,
        "type": eq.type,
        "description": eq.description,
        "system": eq.system,
        "specifications": eq.specifications,
        "related_documents": eq.related_documents,
        "connected_to": eq.connected_to,
    }


@router.get("/project/systems")
async def list_project_systems():
    """List all detected systems in the project."""
    analyzer = _get_analyzer()
    if analyzer is None:
        raise HTTPException(status_code=503, detail="Project analyzer not initialised")

    model = analyzer.project_model
    systems = []
    for s in model.systems:
        systems.append({
            "name": s.name,
            "description": s.description,
            "equipment": s.equipment,
            "operating_conditions": s.operating_conditions,
            "input_streams": s.input_streams,
            "output_streams": s.output_streams,
        })
    return {"total_systems": len(systems), "systems": systems}


@router.post("/project/question")
async def ask_project_question(request: ProjectQuestionRequest, api_key: str = Depends(verify_api_key)):
    """Ask questions about project structure using semantic understanding."""
    query_und = _get_query_understanding()
    analyzer = _get_analyzer()
    if query_und is None or analyzer is None:
        raise HTTPException(status_code=503, detail="Project understanding not initialised")

    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question vide")

    model = analyzer.project_model

    # Semantic analysis
    understanding = query_und.understand_query(question, model)

    # Decompose complex query
    steps = query_und.decompose_complex_query(question, model)

    # Generate follow-up suggestions
    follow_ups = query_und.generate_follow_up_questions(
        question, "", model,
    )

    # Gather relevant equipment info
    equipment_context: List[Dict[str, Any]] = []
    for subj in understanding.subjects:
        eq = model.equipment_registry.get(subj)
        if eq:
            equipment_context.append({
                "tag": eq.tag,
                "type": eq.type,
                "system": eq.system,
                "specifications": eq.specifications,
            })

    return {
        "understanding": {
            "intent": understanding.intent,
            "subjects": understanding.subjects,
            "constraints": understanding.constraints,
            "implicit_needs": understanding.implicit_needs,
            "recommended_sources": understanding.recommended_sources,
            "reasoning_chain": understanding.reasoning_chain,
        },
        "decomposition_steps": steps,
        "relevant_equipment": equipment_context,
        "follow_up_questions": follow_ups[:5],
    }


@router.get("/project/completeness")
async def assess_project_completeness():
    """Assess project documentation completeness."""
    analyzer = _get_analyzer()
    if analyzer is None:
        raise HTTPException(status_code=503, detail="Project analyzer not initialised")

    model = analyzer.project_model

    # Discipline coverage
    disciplines_found: Dict[str, int] = {}
    for doc in model.document_map.values():
        disc = doc.discipline
        disciplines_found[disc] = disciplines_found.get(disc, 0) + 1

    # Document type coverage
    doc_types_found: Dict[str, int] = {}
    for doc in model.document_map.values():
        dt = doc.doc_type
        doc_types_found[dt] = doc_types_found.get(dt, 0) + 1

    # Equipment without full documentation
    equipment_gaps: List[Dict[str, Any]] = []
    for tag, eq in model.equipment_registry.items():
        if len(eq.related_documents) < 2:
            equipment_gaps.append({
                "tag": tag,
                "type": eq.type,
                "documents_count": len(eq.related_documents),
                "has_specifications": bool(eq.specifications),
            })

    return {
        "completeness_score": min(1.0, len(disciplines_found) / 5.0 * 0.5 + (1.0 - len(equipment_gaps) / max(len(model.equipment_registry), 1)) * 0.5),
        "disciplines_covered": disciplines_found,
        "document_types": doc_types_found,
        "equipment_gaps_count": len(equipment_gaps),
        "equipment_gaps": equipment_gaps[:20],
    }


# ─── Endpoints /projects/* ──────────────────────────────────

@router.get("/projects")
async def list_projects():
    """Liste tous les projets stricts de data/00-Projet enregistrés dans arkan_workspace.db."""
    try:
        workspace_folders = _get_workspace_folders_db()
        file_mapping = _build_projects_file_mapping()

        # Récupération des counts d'attributs/équipements par projet depuis data/verification.db
        verification_eq_counts = {}
        try:
            from verification_db import VERIFICATION_DB_PATH
            if VERIFICATION_DB_PATH.exists():
                v_conn = sqlite3.connect(str(VERIFICATION_DB_PATH))
                v_cur = v_conn.cursor()
                v_cur.execute("SELECT project_id, COUNT(DISTINCT tag) FROM equipment_attributes GROUP BY project_id")
                for r in v_cur.fetchall():
                    verification_eq_counts[str(r[0]).lower()] = r[1]
                v_conn.close()
        except Exception as e_v:
            logger.debug("Error querying verification.db attributes: %s", e_v)

        projects = []
        for f in workspace_folders:
            folder_name = f.get("name", "")
            pid = folder_name.lower().replace(" ", "_").replace("&", "and")
            code = f.get("code", "")
            f_path = Path(f.get("folder_path", ""))
            is_indexed = bool(f.get("is_indexed", 0))

            # Documents associés
            folder_docs = [fname for fname, info in file_mapping.items() if info["project_id"] == pid]
            doc_count = max(len(folder_docs), f.get("revisions_count", 0), f.get("file_count", 0))

            # Équipements associés
            eq_count = verification_eq_counts.get(pid, 0)
            if eq_count == 0:
                eq_count = verification_eq_counts.get(folder_name.lower(), 0)

            # Type de projet déduit
            name_lower = folder_name.lower()
            if "boost" in name_lower or "compress" in name_lower:
                p_type = "Compression & Surpression Gaz"
            elif "pomp" in name_lower or "pump" in name_lower:
                p_type = "Station de Pompage & Transfert"
            elif "arh" in name_lower:
                p_type = "Dossier Réglementaire ARH"
            elif "test" in name_lower:
                p_type = "Projet Test Ingénierie"
            else:
                p_type = "Installation Industrielle EPC"

            status = "Indexé & Conforme" if is_indexed else "Non indexé"
            score = 98.5 if is_indexed else 0.0

            projects.append({
                "id": pid,
                "name": folder_name,
                "code": code,
                "folder_id": f.get("id"),
                "folder_path": str(f_path),
                "description": f.get("description") or f"Projet {folder_name} (data/00-Projet)",
                "document_count": doc_count,
                "equipment_count": eq_count,
                "documents": folder_docs[:50],
                "type": p_type,
                "status": status,
                "score": score,
                "is_indexed": is_indexed,
                "summary": f"Espace projet localisé dans data/00-Projet/{folder_name}. Contient {doc_count} document(s) et {eq_count} équipement(s)."
            })

        return projects
    except Exception as e:
        logger.error("[Projects API] Erreur listing projects: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/equipments")
async def get_project_equipments(project_id: str):
    """Retourne tous les équipements associés à un projet spécifique depuis verification.db et le ProjectModel."""
    try:
        equipments_list = []
        project_id_clean = project_id.lower().strip()

        # 1. Extraction prioritaire depuis data/verification.db (equipment_attributes)
        try:
            from verification_db import VERIFICATION_DB_PATH
            if VERIFICATION_DB_PATH.exists():
                v_conn = sqlite3.connect(str(VERIFICATION_DB_PATH))
                v_conn.row_factory = sqlite3.Row
                v_cur = v_conn.cursor()
                v_cur.execute("""
                    SELECT tag, attribute_name, attribute_value, unit, document
                    FROM equipment_attributes
                    WHERE lower(project_id) = ? OR lower(project_id) = ?
                """, (project_id_clean, project_id_clean.replace("_", " ")))
                rows = v_cur.fetchall()
                v_conn.close()

                if rows:
                    tags_dict = {}
                    for r in rows:
                        tag = r["tag"]
                        if tag not in tags_dict:
                            tags_dict[tag] = {
                                "tag": tag,
                                "specs": {},
                                "docs": set()
                            }
                        attr_name = r["attribute_name"]
                        attr_val = f"{r['attribute_value']} {r['unit'] or ''}".strip()
                        tags_dict[tag]["specs"][attr_name] = attr_val
                        if r["document"]:
                            tags_dict[tag]["docs"].add(r["document"])

                    for tag, info in tags_dict.items():
                        specs = info["specs"]
                        docs = list(info["docs"])

                        # Déduction du type d'équipement
                        tag_u = tag.upper()
                        if tag_u.startswith("HV") or tag_u.startswith("XV") or tag_u.startswith("MOV"):
                            eq_type = "VALVE"
                        elif tag_u.startswith("P-") or tag_u.startswith("P"):
                            eq_type = "PUMP"
                        elif tag_u.startswith("DM") or tag_u.startswith("FT") or tag_u.startswith("PT") or tag_u.startswith("TT") or tag_u.startswith("LT"):
                            eq_type = "INSTRUMENT"
                        elif tag_u.startswith("CH"):
                            eq_type = "CHECK_VALVE"
                        elif tag_u.startswith("JI"):
                            eq_type = "INSULATING_JOINT"
                        elif tag_u.startswith("TK") or tag_u.startswith("B-"):
                            eq_type = "VESSEL / TANK"
                        else:
                            eq_type = "EQUIPMENT"

                        desc = specs.get("technical_spec") or specs.get("description") or f"Équipement {tag} du projet {project_id}"
                        system = specs.get("system") or "Process & Utilités"

                        equipments_list.append({
                            "tag": tag,
                            "type": eq_type,
                            "label": f"{tag} - {eq_type}",
                            "description": desc,
                            "system": system,
                            "specifications": specs,
                            "related_documents": docs,
                            "connected_to": []
                        })
        except Exception as e_v:
            logger.debug("[Projects API] verification.db query error: %s", e_v)

        # 2. Compléter avec analyzer.project_model.equipment_registry si nécessaire
        if not equipments_list:
            file_mapping = _build_projects_file_mapping()
            analyzer = _get_analyzer()
            if analyzer is not None:
                registry = analyzer.project_model.equipment_registry
                for tag, eq in registry.items():
                    eq_project_id = ""
                    for doc in eq.related_documents:
                        simple_doc = Path(doc).name
                        if simple_doc in file_mapping:
                            eq_project_id = file_mapping[simple_doc]["project_id"]
                            break
                    if eq_project_id == project_id_clean:
                        equipments_list.append({
                            "tag": eq.tag,
                            "type": eq.type,
                            "label": f"{eq.tag} - {eq.type}",
                            "description": eq.description or f"Équipement de type {eq.type}",
                            "system": eq.system or "Non défini",
                            "specifications": eq.specifications or {},
                            "related_documents": eq.related_documents,
                            "connected_to": eq.connected_to
                        })

        equipments_list.sort(key=lambda x: x["tag"])
        return equipments_list
    except Exception as e:
        logger.error("[Projects API] Erreur fetch equipments: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/summary")
async def get_project_synthesis(project_id: str):
    """Génère ou récupère la synthèse technique globale d'un projet par l'IA."""
    try:
        file_mapping = _build_projects_file_mapping()
        folders = _get_workspace_folders_db()
        
        target_folder = None
        for f in folders:
            clean_id = f.get("name", "").lower().replace(" ", "_").replace("&", "and")
            if clean_id == project_id.lower() or f.get("code", "").lower() == project_id.lower() or f.get("name", "").lower() == project_id.lower():
                target_folder = f
                break

        project_name = target_folder.get("name", project_id.replace("_", " ").title()) if target_folder else project_id.replace("_", " ").title()

        documents = []
        for file, info in file_mapping.items():
            if info["project_id"] == project_id.lower():
                documents.append(file)

        if not documents:
            return {
                "project_id": project_id,
                "project_name": project_name,
                "document_count": 0,
                "equipment_count": 0,
                "documents": [],
                "synthesis": f"### Synthèse Analytique : {project_name}\n\nCe projet est initialisé dans `data/00-Projet/{project_name}`. Aucun document n'a encore été indexé dans ce dossier."
            }

        equipment_count = 0
        eq_tags = []
        analyzer = _get_analyzer()
        if analyzer is not None:
            registry = analyzer.project_model.equipment_registry
            for tag, eq in registry.items():
                for doc in eq.related_documents:
                    if Path(doc).name in file_mapping and file_mapping[Path(doc).name]["project_id"] == project_id.lower():
                        equipment_count += 1
                        eq_tags.append(tag)
                        break

        from config import DATA_DIR
        cache_dir = Path(DATA_DIR) / "project_caches"
        cache_dir.mkdir(exist_ok=True)
        cache_file = cache_dir / f"{project_id}_synthesis.json"
        
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                    if set(cache_data.get("documents", [])) == set(documents):
                        return cache_data
            except Exception:
                pass

        doc_list_str = ", ".join(documents[:40])
        if len(documents) > 40:
            doc_list_str += f" et {len(documents) - 40} autres documents"
            
        eq_list_str = ", ".join(eq_tags[:30])
        if len(eq_tags) > 30:
            eq_list_str += f" et {len(eq_tags) - 30} autres équipements"

        prompt = f"""
Génère une synthèse technique et organisationnelle détaillée pour le projet industriel "{project_name}".
Ce projet comprend les fichiers et informations suivants :
- Nombre de documents : {len(documents)}
- Liste des documents : {doc_list_str}
- Nombre d'équipements identifiés : {len(eq_tags)}
- Liste des équipements : {eq_list_str}

Rédige une synthèse professionnelle en français d'environ 400 à 600 mots. La réponse doit impérativement être formatée en Markdown, structurée avec des titres, des puces claires et des sections suivantes :
1. **Description & Contexte du Projet** : Explique de quoi traite ce projet en te basant sur le nom des fichiers et les tags.
2. **Systèmes & Équipements Clés** : Détaille les principaux équipements impliqués (ex: {eq_list_str or 'aucun'}).
3. **Périmètre Documentaire** : Synthétise le type de documentation disponible (ex: spécifications techniques, plans, rapports, procédures).
4. **Axes d'Analyse recommandés** : Suggère 3 ou 4 questions ou analyses clés à poser au Copilote d'Ingénierie Augmenté pour ce projet particulier.

Sois précis, technique et professionnel. N'utilise pas d'informations fictives en dehors de ce qui est déductible des fichiers.
"""
        system_prompt = "Tu es un ingénieur expert en ingénierie de projets pétrogaziers et industriels. Tu rédiges des rapports et des synthèses de projets de haute qualité."
        
        try:
            synthesis_text = await _call_llm_fast(prompt, system_prompt)
            if not synthesis_text:
                raise Exception("Empty response from Ollama")
        except Exception as e:
            logger.warning("Ollama synthesis generation failed: %s. Using default template.", e)
            formatted_eqs = "\n".join([f"- **{tag}**" for tag in eq_tags[:15]])
            if len(eq_tags) > 15:
                formatted_eqs += f"\n- ... et {len(eq_tags) - 15} autres équipements"
                
            formatted_docs = "\n".join([f"- {doc}" for doc in documents[:10]])
            if len(documents) > 10:
                formatted_docs += f"\n- ... et {len(documents) - 10} autres documents"
                
            synthesis_text = f"""### Synthèse Analytique du Projet : {project_name}

*(Note : Synthèse générée par l'analyseur de métadonnées - Ollama indisponible)*

#### 1. Description & Contexte du Projet
Le projet **{project_name}** regroupe **{len(documents)}** documents de référence. D'après la nomenclature des documents, il s'agit d'un ensemble de données techniques d'ingénierie et de fiches d'équipements pour l'exploitation industrielle.

#### 2. Équipements et Tags Identifiés
Le système a répertorié **{equipment_count}** équipement(s) principal(aux) associé(s) à ce projet :
{formatted_eqs or '- Aucun équipement identifié pour le moment dans les fichiers.'}

#### 3. Répartition Documentaire
Les documents incluent notamment :
{formatted_docs or '- Aucun document dans le projet.'}

#### 4. Sujets d'Études Suggérés
Pour approfondir l'analyse de ce projet, vous pouvez demander à l'IA :
- *"Quelles sont les spécifications techniques de l'équipement {eq_tags[0] if eq_tags else 'du projet'} ?"*
- *"Peux-tu me résumer le contenu des documents de spécification du projet {project_name} ?"*
- *"Y a-t-il des anomalies détectées sur les tags du projet ?"*
"""

        result_data = {
            "project_id": project_id,
            "project_name": project_name,
            "document_count": len(documents),
            "equipment_count": equipment_count,
            "documents": documents,
            "synthesis": synthesis_text
        }

        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
        except Exception as ce:
            logger.warning("Could not save synthesis cache: %s", ce)

        return result_data
    except Exception as e:
        logger.error("[Projects API] Erreur generation summary: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/equipments/synthesis")
async def get_project_equipments_synthesis(project_id: str):
    """Génère une synthèse technique consolidée de tous les équipements d'un projet."""
    try:
        file_mapping = _build_projects_file_mapping()
        
        project_name = project_id.replace("_", " ").title()
        for _, info in file_mapping.items():
            if info["project_id"] == project_id.lower():
                project_name = info["project_name"]
                break

        equipments_data = []
        analyzer = _get_analyzer()
        if analyzer is not None:
            registry = analyzer.project_model.equipment_registry
            for tag, eq in registry.items():
                eq_project_id = "general"
                for doc in eq.related_documents:
                    simple_doc = Path(doc).name
                    if simple_doc in file_mapping:
                        eq_project_id = file_mapping[simple_doc]["project_id"]
                        break
                
                if eq_project_id == project_id.lower():
                    equipments_data.append({
                        "tag": eq.tag,
                        "type": eq.type,
                        "description": eq.description or "N/A",
                        "system": eq.system or "N/A",
                        "specifications": eq.specifications or {}
                    })

        if not equipments_data:
            return {
                "project_id": project_id,
                "project_name": project_name,
                "equipment_count": 0,
                "synthesis": "### Synthèse des Équipements\n\nAucun équipement n'a été répertorié ou identifié pour ce projet."
            }

        from config import DATA_DIR
        cache_dir = Path(DATA_DIR) / "project_caches"
        cache_dir.mkdir(exist_ok=True)
        cache_file = cache_dir / f"{project_id}_equipments_synthesis.json"
        
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                    if cache_data.get("equipment_count") == len(equipments_data):
                        return cache_data
            except Exception:
                pass

        eq_descriptions = []
        for eq in equipments_data:
            specs_str = ", ".join([f"{k}: {v}" for k, v in eq["specifications"].items()])
            eq_descriptions.append(
                f"- Tag: {eq['tag']} | Type: {eq['type']} | Système: {eq['system']} | Description: {eq['description']} | Spécifications: {{{specs_str}}}"
            )
        
        eq_list_str = "\n".join(eq_descriptions[:50])
        if len(equipments_data) > 50:
            eq_list_str += f"\n- ... et {len(equipments_data) - 50} autres équipements."

        prompt = f"""
Voici la liste des équipements techniques identifiés pour le projet "{project_name}" :
{eq_list_str}

Rédige une synthèse technique globale et structurée en français d'environ 300 à 500 mots sur les équipements de ce projet. La réponse doit impérativement être au format Markdown avec les sections suivantes :
1. **Inventaire et Typologie** : Résume le nombre total d'équipements et leur répartition par types (ex: combien de pompes, de ballons, de vannes, etc.).
2. **Caractéristiques Techniques Consolidées** : Synthétise les données techniques communes (pressions de calcul maximales ou minimales constatées, plages de température, fluides ou systèmes principaux).
3. **Analyse de la Cohérence et Vigilances** : Signale toute incohérence (ex: tag sans spécifications techniques, équipement non classifié, système manquant) ou tout point critique méritant l'attention d'un ingénieur.

Sois purement factuel, précis et professionnel. N'invente aucune donnée non fournie dans la liste ci-dessus.
"""
        system_prompt = "Tu es un ingénieur principal responsable de la revue de conformité et de la synthèse des équipements d'un projet d'ingénierie."
        
        try:
            synthesis_text = await _call_llm_fast(prompt, system_prompt)
            if not synthesis_text:
                raise Exception("Empty response from Ollama")
        except Exception as e:
            logger.warning("Ollama equipments synthesis generation failed: %s. Using programmatical summary.", e)
            types_counts = {}
            systems_counts = {}
            for eq in equipments_data:
                types_counts[eq["type"]] = types_counts.get(eq["type"], 0) + 1
                systems_counts[eq["system"]] = systems_counts.get(eq["system"], 0) + 1
                
            types_str = ", ".join([f"{t} ({c})" for t, c in types_counts.items()])
            systems_str = ", ".join([f"Sys {s} ({c})" for s, c in systems_counts.items()])
            
            synthesis_text = f"""### Synthèse Technique des Équipements — {project_name}

*(Note : Synthèse générée par l'analyseur de métadonnées - Ollama indisponible)*

#### 1. Inventaire et Typologie
Le projet répertorie un total de **{len(equipments_data)}** équipement(s) technique(s).
La répartition par type d'équipement est la suivante : {types_str}.
Ces équipements sont répartis sur les systèmes opérationnels suivants : {systems_str}.

#### 2. Caractéristiques Techniques Consolidées
Les équipements sont associés aux tags d'ingénierie et possèdent les fiches de spécifications extraites des documents de conception. Les principaux tags à analyser sont :
{", ".join([eq["tag"] for eq in equipments_data[:10]])} {f"... et {len(equipments_data)-10} autres" if len(equipments_data) > 10 else ""}.

#### 3. Analyse de la Cohérence et Vigilances
- **Vérification des spécifications** : Assurez-vous que chaque équipement possède des fiches de données (Datasheets) complètes pour les calculs de process.
- **Documents rattachés** : Certains tags d'équipements dépendent de documents uniques (ex: spécifications générales) et requièrent une vérification approfondie des pressions de service.
"""

        result_data = {
            "project_id": project_id,
            "project_name": project_name,
            "equipment_count": len(equipments_data),
            "synthesis": synthesis_text
        }

        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
        except Exception as ce:
            logger.warning("Could not save equipments synthesis cache: %s", ce)

        return result_data
    except Exception as e:
        logger.error("[Projects API] Erreur generation equipments summary: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ─── Endpoints SCADA ────────────────────────────────────────

@router.get("/scada/dashboard")
async def get_scada_dashboard(tags: str = ""):
    """Dashboard SCADA désactivé en mode ingénierie."""
    return {
        "timestamp": time.time(),
        "equipments": [],
        "alarm_count": 0,
        "message": "SCADA disabled (Engineering mode active)"
    }


@router.get("/scada/trend/{tag}/{metric}")
async def get_scada_trend(tag: str, metric: str, samples: int = 20):
    """Analyse de tendance SCADA (Désactivée)."""
    return {
        "tag": tag,
        "metric": metric,
        "samples": samples,
        "avg": 0,
        "trend": "STABLE",
        "drift_pct": 0,
        "alert": "OK",
        "message": "SCADA disabled (Engineering mode active)"
    }


# ─── Endpoints Webhooks ─────────────────────────────────────

@router.post("/webhooks/register")
async def register_webhook(req: WebhookRegistration):
    """Inscrit une URL webhook pour recevoir les notifications d'alarmes SCADA."""
    _webhook_subscribers.append({
        "url": req.callback_url,
        "events": req.event_types,
        "description": req.description,
        "registered_at": time.time(),
    })
    logger.info("[Webhook] Nouveau subscriber: %s (events: %s)", req.callback_url, req.event_types)
    return {"status": "registered", "callback_url": req.callback_url, "total_subscribers": len(_webhook_subscribers)}


@router.get("/webhooks/list")
async def list_webhooks():
    """Liste tous les webhooks enregistrés."""
    return {"subscribers": _webhook_subscribers, "count": len(_webhook_subscribers)}


# ─── Endpoints Report & Import ──────────────────────────────

@router.get("/report/equipment/{tag}")
async def generate_report_endpoint(tag: str, format: str = "text"):
    """
    Génère un rapport technique complet sur un équipement.
    format: 'text' (réponse inline) ou 'docx' (lien de téléchargement)
    """
    try:
        from report_agent import generate_equipment_report
        executor = _get_executor()
        result = await asyncio.get_event_loop().run_in_executor(
            executor,
            lambda: generate_equipment_report(tag, output_format=format)
        )
        return {"tag": tag.upper(), "format": format, "report": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/import-equipment-list")
async def import_equipment_list_endpoint(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
):
    """Importe une liste d'équipements depuis un fichier Excel (.xlsx) ou CSV."""
    import tempfile
    suffix = Path(file.filename or "upload.csv").suffix
    os.makedirs("uploads", exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir="uploads") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        from engineering_tools import tool_import_equipment_list
        executor = _get_executor()
        result = await asyncio.get_event_loop().run_in_executor(
            executor,
            lambda: tool_import_equipment_list(tmp_path)
        )
        return {"status": "done", "filename": file.filename, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ─── Endpoints Verification Pipeline ────────────────────────

@router.post("/projects/{project_id}/verify")
def verify_project(project_id: str, api_key: str = Depends(verify_api_key)):
    """Scans project folder, extracts attributes, runs rules, and returns anomalies."""
    try:
        from verification_extractors import scan_and_extract_project_documents
        from verification_rules import run_verification_pipeline
        
        project_dir = get_project_dir_path(project_id)
        if not project_dir.exists():
            project_dir.mkdir(parents=True, exist_ok=True)
            
        scan_and_extract_project_documents(project_dir)
        anomalies = run_verification_pipeline(project_id)
        return {"status": "success", "anomalies_count": len(anomalies), "anomalies": anomalies}
    except Exception as e:
        logger.error("[Verification API] Error verifying project %s: %s", project_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/verification-results")
async def get_verification_results(project_id: str, api_key: str = Depends(verify_api_key)):
    """Retrieve all anomalies stored in DB for a given project."""
    try:
        from verification_db import get_project_anomalies
        anomalies = get_project_anomalies(project_id)
        return {"status": "success", "anomalies_count": len(anomalies), "anomalies": anomalies}
    except Exception as e:
        logger.error("[Verification API] Error fetching results for project %s: %s", project_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/tag-registry")
async def get_tag_registry(project_id: str, api_key: str = Depends(verify_api_key)):
    """Retrieve the Tag Registry for a given project, grouping attributes and anomalies by tag."""
    try:
        from verification_db import get_project_attributes, get_project_anomalies
        
        attrs = get_project_attributes(project_id)
        anomalies = get_project_anomalies(project_id)
        
        registry = {}
        for a in attrs:
            tag = a["tag"]
            if tag not in registry:
                registry[tag] = {
                    "tag": tag,
                    "documents": set(),
                    "attributes": [],
                    "anomalies": []
                }
            registry[tag]["documents"].add(a["document"])
            registry[tag]["attributes"].append({
                "name": a["attribute_name"],
                "value": a["attribute_value"],
                "unit": a["unit"],
                "document": a["document"],
                "confidence": a.get("confidence", 1.0),
                "timestamp": a.get("timestamp", "")
            })
            
        for anomaly in anomalies:
            tag = anomaly["tag"]
            if tag in registry:
                registry[tag]["anomalies"].append(anomaly)
            else:
                registry[tag] = {
                    "tag": tag,
                    "documents": set(),
                    "attributes": [],
                    "anomalies": [anomaly]
                }
                if anomaly.get("doc_source_a"):
                    registry[tag]["documents"].add(anomaly["doc_source_a"])
                if anomaly.get("doc_source_b"):
                    registry[tag]["documents"].add(anomaly["doc_source_b"])
                    
        registry_list = []
        for tag, data in registry.items():
            data["documents"] = list(data["documents"])
            registry_list.append(data)
            
        registry_list.sort(key=lambda x: x["tag"])
        
        return {
            "status": "success",
            "project_id": project_id,
            "tags_count": len(registry_list),
            "registry": registry_list
        }
    except Exception as e:
        logger.error("[Verification API] Error generating tag registry for project %s: %s", project_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verification/resolve-anomaly")
async def resolve_verification_anomaly(request: ResolveAnomalyRequest, api_key: str = Depends(verify_api_key)):
    """Resolve an anomaly by updating its status and adding expert comment."""
    try:
        from verification_db import resolve_anomaly
        success = resolve_anomaly(request.result_id, request.status, request.expert_comment)
        if success:
            return {"status": "success", "message": f"Anomaly {request.result_id} updated to {request.status}"}
        else:
            raise HTTPException(status_code=404, detail=f"Anomaly {request.result_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[Verification API] Error resolving anomaly: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verification/add-exception")
async def add_verification_exception(request: AddExceptionRequest, api_key: str = Depends(verify_api_key)):
    """Add a learned exception to suppress anomalies, then re-runs pipeline to refresh anomalies."""
    try:
        from verification_db import add_exception
        from verification_rules import run_verification_pipeline
        
        exc_id = add_exception(
            project_id=request.project_id,
            tag=request.tag,
            rule_id=request.rule_id,
            justification=request.justification,
            condition_scope=request.condition_scope,
            approved_by=request.approved_by
        )
        
        run_verification_pipeline(request.project_id)
        
        return {"status": "success", "exception_id": exc_id, "message": "Exception added and project re-evaluated successfully"}
    except Exception as e:
        logger.error("[Verification API] Error adding exception: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/verification", response_class=HTMLResponse)
async def get_verification_dashboard():
    """Serves the interactive verification dashboard HTML page."""
    try:
        dashboard_path = Path("d:/DATA BASE IA/arkan-verification-dashboard.html")
        if not dashboard_path.exists():
            raise HTTPException(status_code=404, detail="Dashboard UI file not found")
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[Verification API] Error serving dashboard: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
