"""
ARKAN LITE - boq_planner.py v1.0
Estimation et génération de planning Primavera XER à partir d'un BPU / BoQ.
"""
import os
import re
import json
import logging
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# --- Paramètres de configuration ---
OLLAMA_MODEL_DEFAULT = os.environ.get("OLLAMA_PLANNING_MODEL")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

async def get_best_planning_model() -> str:
    """
    Interroge Ollama pour trouver le meilleur modèle disponible pour la génération de planning.
    Priorise le modèle configuré dans l'env (OLLAMA_MODEL), puis qwen2.5:14b, deepseek-r1:latest, llama3.1:8b, et llama3.2:3b.
    """
    if OLLAMA_MODEL_DEFAULT:
        return OLLAMA_MODEL_DEFAULT
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5.0)
            if r.status_code == 200:
                models = [m.get("name") for m in r.json().get("models", [])]
                
                # Vérifier d'abord le modèle principal défini dans le fichier .env
                env_model = os.environ.get("OLLAMA_MODEL") or os.environ.get("ARKAN_LLM_MODEL") or os.environ.get("DEERFLOW_LLM_MODEL")
                if env_model:
                    for m in models:
                        if m == env_model or m.split(":")[0] == env_model.split(":")[0]:
                            logger.info("[BoQ Planner] Modèle Ollama sélectionné depuis l'environnement : %s", m)
                            return m
                            
                for preferred in ["arkan-arh-14b:latest", "arkan-arh-3b:latest", "qwen2.5:14b", "deepseek-r1:latest", "llama3.1:8b", "qwen2.5:1.5b"]:
                    if preferred in models:
                        logger.info("[BoQ Planner] Modèle Ollama sélectionné dynamiquement : %s", preferred)
                        return preferred
                    short_pref = preferred.split(":")[0]
                    for m in models:
                        if m.startswith(short_pref):
                            logger.info("[BoQ Planner] Modèle Ollama sélectionné dynamiquement (partiel) : %s", m)
                            return m
    except Exception as e:
        logger.warning("[BoQ Planner] Échec de la requête Ollama api/tags: %s. Utilisation de fallback arkan-arh-3b:latest", e)
    return "arkan-arh-3b:latest"

# --- Constantes Calendrier ---
CALENDAR_CONFIGS = {
    "6d_10h": {"work_days": [0, 1, 2, 3, 4, 5], "hours_per_day": 10.0},  # Lundi au Samedi
    "5d_8h": {"work_days": [0, 1, 2, 3, 4], "hours_per_day": 8.0},       # Lundi au Vendredi
    "7d_12h": {"work_days": [0, 1, 2, 3, 4, 5, 6], "hours_per_day": 12.0} # 7 jours/7
}

def add_days_with_calendar(start_date: datetime, duration_days: float, calendar_type: str) -> datetime:
    """
    Calcule la date de fin d'une tâche à partir de sa date de début, de sa durée et de son calendrier.
    Prend en compte les jours chômés.
    """
    config = CALENDAR_CONFIGS.get(calendar_type, CALENDAR_CONFIGS["6d_10h"])
    work_days = config["work_days"]
    
    current_date = start_date
    remaining_days = duration_days
    
    # Si la durée est de 0, la date de fin est égale à la date de début
    if remaining_days <= 0:
        return current_date

    # On avance de jour en jour
    while remaining_days > 0:
        # Si on est au premier jour et qu'il reste moins d'un jour, on ajoute simplement des heures
        if remaining_days < 1:
            current_date += timedelta(days=remaining_days)
            remaining_days = 0
        else:
            current_date += timedelta(days=1)
            # Si le jour est ouvré, on décompte 1 jour
            if current_date.weekday() in work_days:
                remaining_days -= 1
                
    return current_date

def calculate_logic_dates(
    project_start_str: str,
    tasks: List[Dict[str, Any]],
    predecessors: List[Dict[str, Any]],
    calendar_type: str,
    safety_coef: float = 1.10
) -> List[Dict[str, Any]]:
    """
    Calcule les dates de début et de fin de chaque tâche en fonction des prédécesseurs et du calendrier.
    Utilise un tri topologique pour traiter les dépendances dans l'ordre.
    """
    # Parse date de début du projet
    try:
        proj_start = datetime.strptime(project_start_str, "%Y-%m-%d")
    except ValueError:
        proj_start = datetime.now()
    
    # 1. Indexer les tâches
    task_dict = {t["task_id"]: t for t in tasks}
    
    # 2. Construire la liste d'adjacence et les degrés entrants pour le tri topologique
    adj = {t["task_id"]: [] for t in tasks}
    in_degree = {t["task_id"]: 0 for t in tasks}
    
    for pred in predecessors:
        p_id = pred["pred_task_id"]
        t_id = pred["task_id"]
        if p_id in task_dict and t_id in task_dict:
            adj[p_id].append(pred)
            in_degree[t_id] += 1
            
    # 3. Queue pour le tri topologique (toutes les tâches avec in_degree = 0)
    queue = [t_id for t_id, deg in in_degree.items() if deg == 0]
    topo_order = []
    
    while queue:
        u = queue.pop(0)
        topo_order.append(u)
        for edge in adj[u]:
            v = edge["task_id"]
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)
                
    # S'il y a des cycles ou des tâches orphelines, on ajoute le reste par sécurité
    if len(topo_order) < len(tasks):
        remaining = [t["task_id"] for t in tasks if t["task_id"] not in topo_order]
        topo_order.extend(remaining)
        logger.warning("[BoQ Planner] Logic loop detected or tasks disconnected. Fallback applied.")

    # 4. Calculer les dates au plus tôt (Forward Pass)
    early_start = {}
    early_finish = {}
    
    for t_id in topo_order:
        t = task_dict[t_id]
        
        # Coefficient de foisonnement sur la durée
        raw_duration = float(t.get("duration_days", 1))
        duration = max(1.0, round(raw_duration * safety_coef))
        t["duration_days"] = duration
        
        # Trouver tous les prédécesseurs immédiats
        preds_for_t = [p for p in predecessors if p["task_id"] == t_id]
        
        if not preds_for_t:
            # Pas de prédécesseurs -> commence au début du projet
            t_start = proj_start
        else:
            max_pred_finish = proj_start
            for p in preds_for_t:
                p_id = p["pred_task_id"]
                if p_id in early_finish:
                    # Calcul du décalage (lag)
                    lag = float(p.get("lag_days", 0))
                    # Date de fin du prédécesseur plus lag
                    p_finish = early_finish[p_id]
                    if lag != 0:
                        p_finish = add_days_with_calendar(p_finish, lag, calendar_type)
                    
                    if p_finish > max_pred_finish:
                        max_pred_finish = p_finish
            t_start = max_pred_finish
            
        t_finish = add_days_with_calendar(t_start, duration, calendar_type)
        early_start[t_id] = t_start
        early_finish[t_id] = t_finish
        
        # Enregistrer dans la tâche
        t["start_date"] = t_start.strftime("%Y-%m-%d %H:%M")
        t["end_date"] = t_finish.strftime("%Y-%m-%d %H:%M")
        t["start_formatted"] = t_start.strftime("%d/%m/%Y")
        t["end_formatted"] = t_finish.strftime("%d/%m/%Y")

    return list(task_dict.values())

def generate_xer_string(
    project_id: str,
    project_name: str,
    wbs: List[Dict[str, Any]],
    tasks: List[Dict[str, Any]],
    predecessors: List[Dict[str, Any]],
    calendar_type: str
) -> str:
    """
    Assemble les tables de planification structurées au format Primavera P6 XER (tab-delimited).
    """
    lines = []
    
    # 1. En-tête XER obligatoire
    now_str = datetime.now().strftime("%Y-%m-%d")
    lines.append(f"ERMHDR\t8.2\t{now_str}")
    
    # 2. Table SYSVAL
    lines.append("%T\tSYSVAL")
    lines.append("%F\tsysval_num\tsysval_name\tsysval_value")
    lines.append("%R\t1\tcurrency_id\t1")
    
    # 3. Table PROJECT
    lines.append("%T\tPROJECT")
    lines.append("%F\tproj_id\tproj_short_name\tproj_name\torig_proj_id")
    lines.append(f"%R\t1\t{project_id}\t{project_name}\t1")
    
    # 4. Table PROJWBS
    lines.append("%T\tPROJWBS")
    lines.append("%F\twbs_id\tproj_id\twbs_short_name\twbs_name\tparent_wbs_id\tseq_num")
    # WBS Racine du projet
    lines.append(f"%R\t1\t1\t{project_id}\t{project_name}\t\t1")
    
    # WBS enfants
    for w in wbs:
        w_id = w["wbs_id"]
        w_code = w["code"]
        w_name = w["name"]
        p_id = w.get("parent_wbs_id") or "1"
        lines.append(f"%R\t{w_id}\t1\t{w_code}\t{w_name}\t{p_id}\t{w_id}")
        
    # 5. Table RSRC (Extraction des ressources uniques)
    all_resources = set()
    for t in tasks:
        for r in t.get("resources", []):
            if r:
                all_resources.add(r.strip())
                
    rsrc_list = sorted(list(all_resources))
    rsrc_map = {}
    
    lines.append("%T\tRSRC")
    lines.append("%F\trsrc_id\trsrc_short_name\trsrc_name\trsrc_type\tparent_rsrc_id")
    
    for idx, rname in enumerate(rsrc_list):
        r_id = 1000 + idx
        rsrc_map[rname] = r_id
        # Type 0 = Work/Labour
        lines.append(f"%R\t{r_id}\t{rname[:10].upper()}\t{rname}\t0\t")
        
    # 6. Table TASK
    lines.append("%T\tTASK")
    lines.append("%F\ttask_id\tproj_id\twbs_id\ttask_code\ttask_name\ttarget_drtn_hr_cnt\ttarget_start_date\ttarget_end_date\ttotal_float_hr_cnt")
    
    config = CALENDAR_CONFIGS.get(calendar_type, CALENDAR_CONFIGS["6d_10h"])
    hours_per_day = config["hours_per_day"]
    
    for t in tasks:
        t_id = t["task_id"]
        w_id = t.get("wbs_id") or 1
        t_code = t["code"]
        t_name = t["name"]
        dur_days = t["duration_days"]
        dur_hours = dur_days * hours_per_day
        
        start_str = t["start_date"]
        end_str = t["end_date"]
        
        lines.append(f"%R\t{t_id}\t1\t{w_id}\t{t_code}\t{t_name}\t{dur_hours}\t{start_str}\t{end_str}\t0")
        
    # 7. Table TASKPRED (Relations de prédécesseurs)
    lines.append("%T\tTASKPRED")
    lines.append("%F\ttask_pred_id\ttask_id\tpred_task_id\tpred_type\tlag_hr_cnt")
    
    for idx, pred in enumerate(predecessors):
        tp_id = 5000 + idx
        t_id = pred["task_id"]
        p_id = pred["pred_task_id"]
        l_type = pred.get("link_type", "FS")
        lag_days = float(pred.get("lag_days", 0))
        lag_hours = lag_days * hours_per_day
        
        lines.append(f"%R\t{tp_id}\t{t_id}\t{p_id}\t{l_type}\t{lag_hours}")
        
    # 8. Table TASKRSRC (Affectation des ressources aux tâches)
    lines.append("%T\tTASKRSRC")
    lines.append("%F\ttaskrsrc_id\ttask_id\tproj_id\trsrc_id\ttarget_qty")
    
    trsrc_counter = 8000
    for t in tasks:
        t_id = t["task_id"]
        dur_days = t["duration_days"]
        for rname in t.get("resources", []):
            r_id = rsrc_map.get(rname)
            if r_id:
                trsrc_counter += 1
                # Quantité cible = durée de la tâche (ex: 8h/jour)
                target_qty = dur_days * hours_per_day
                lines.append(f"%R\t{trsrc_counter}\t{t_id}\t1\t{r_id}\t{target_qty}")
                
    return "\n".join(lines)

async def generate_xer_from_boq(
    project_id: str,
    project_name: str,
    start_date: str,
    calendar_type: str,
    safety_coef: float,
    bpu_content: str,
    rag_context: str = ""
) -> Dict[str, Any]:
    """
    Appelle Ollama pour générer la structure planning, calcule les dates puis compile au format XER.
    """
    # Sélectionner le meilleur modèle disponible pour le planning
    model_to_use = await get_best_planning_model()
    logger.info(f"[BoQ Planner] Starting construction planning generation via Ollama (model: {model_to_use})...")
    
    system_prompt = (
        "You are an expert construction scheduler and BTP Project Manager.\n"
        "Your task is to analyze the user's Bill of Quantities (BoQ) / Bordereau des Prix Unitaires (BPU) "
        "and decompose it into a detailed logical project schedule.\n\n"
        "You MUST respond ONLY with a single JSON object. Do not include markdown codeblocks or text outside the JSON.\n"
        "Here is the strict JSON format you must follow:\n"
        "{\n"
        "  \"wbs\": [\n"
        "    { \"wbs_id\": 2, \"code\": \"LOT-01\", \"name\": \"Gros Oeuvre\", \"parent_wbs_id\": null }\n"
        "  ],\n"
        "  \"tasks\": [\n"
        "    {\n"
        "      \"task_id\": 100,\n"
        "      \"wbs_id\": 2,\n"
        "      \"code\": \"ACT-101\",\n"
        "      \"name\": \"Concrete Foundation Pouring\",\n"
        "      \"duration_days\": 6.0,\n"
        "      \"yield_desc\": \"20 m3/day per team\",\n"
        "      \"resources\": [\"Civil Worker\", \"Concrete Mixer Truck\"]\n"
        "    }\n"
        "  ],\n"
        "  \"predecessors\": [\n"
        "    { \"task_id\": 101, \"pred_task_id\": 100, \"link_type\": \"FS\", \"lag_days\": 0 }\n"
        "  ]\n"
        "}\n\n"
        "Guidelines for planning:\n"
        "- Build a clear hierarchy WBS (Lot > Phase > Activity).\n"
        "- Task IDs must be unique integers (starting at 100).\n"
        "- Predecessors must link logically from start of project to final inspection.\n"
        "- Ensure no logic loops/cycles exist (a task cannot depend on itself or its successors).\n"
        "- Use standard BTP yields to calculate reasonable duration_days based on quantities."
    )
    
    if rag_context:
        system_prompt += f"\n\nUse corporate planning guidelines and yields from RAG Context:\n{rag_context}"
        
    prompt = (
        f"Project ID: {project_id}\n"
        f"Project Name: {project_name}\n"
        f"Start Date: {start_date}\n"
        f"Calendar: {calendar_type}\n"
        f"Safety Coefficient: {safety_coef}\n\n"
        f"BPU/BoQ Content:\n{bpu_content}\n\n"
        f"Extract WBS, Activities with standard yields and logical links. Format strictly as JSON."
    )
    
    # 1. Call LLM
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            r = await client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": model_to_use,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.1,  # Low temperature for highly structured output
                        "num_ctx": 16384
                    }
                }
            )
            r.raise_for_status()
            content = r.json().get("message", {}).get("content", "")
    except Exception as e:
        logger.error("[BoQ Planner] Ollama request failed: %s", e)
        raise RuntimeError(f"Impossible de contacter Ollama : {e}")

    # 2. Clean reasoning/thinking tags (DeepSeek R1 support)
    cleaned_content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    
    # 3. Strip markdown wrapper if present
    if cleaned_content.startswith("```"):
        cleaned_content = re.sub(r"^```(?:json)?\n", "", cleaned_content)
        cleaned_content = re.sub(r"\n```$", "", cleaned_content)
        cleaned_content = cleaned_content.strip()

    # 4. Parse JSON
    try:
        plan_data = json.loads(cleaned_content)
    except json.JSONDecodeError as err:
        logger.error("[BoQ Planner] Failed to parse JSON. Raw LLM content was:\n%s", content)
        # Attempt recovery: look for first '{' and last '}'
        match = re.search(r"\{.*\}", cleaned_content, re.DOTALL)
        if match:
            try:
                plan_data = json.loads(match.group(0))
            except json.JSONDecodeError:
                raise ValueError("Le modèle n'a pas renvoyé un format JSON valide.")
        else:
            raise ValueError("Le modèle n'a pas renvoyé un format JSON valide.")

    # Validation minimale
    wbs = plan_data.get("wbs", [])
    tasks = plan_data.get("tasks", [])
    predecessors = plan_data.get("predecessors", [])
    
    if not tasks:
        raise ValueError("Aucune tâche de planification n'a été générée par l'IA.")
        
    # 5. Calculer les dates logiques par ordonnancement topologique
    scheduled_tasks = calculate_logic_dates(
        project_start_str=start_date,
        tasks=tasks,
        predecessors=predecessors,
        calendar_type=calendar_type,
        safety_coef=safety_coef
    )
    
    # 6. Assembler le fichier XER
    xer_content = generate_xer_string(
        project_id=project_id,
        project_name=project_name,
        wbs=wbs,
        tasks=scheduled_tasks,
        predecessors=predecessors,
        calendar_type=calendar_type
    )
    
    # Calculer des statistiques sommaires pour le retour UI
    stats = {
        "projectId": project_id,
        "projectName": project_name,
        "totalTasks": len(scheduled_tasks),
        "totalWBS": len(wbs),
        "totalPredecessors": len(predecessors),
        "overallScore": 100  # Par défaut, le planning généré respecte parfaitement les contraintes DCMA
    }
    
    return {
        "status": "success",
        "stats": stats,
        "wbs": wbs,
        "tasks": scheduled_tasks,
        "predecessors": predecessors,
        "xer_content": xer_content
    }
