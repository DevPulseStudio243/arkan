"""
DEERFLOW LITE — Primavera P6 XER Schedule Quality Auditor (DCMA 14-Point)
v2.0 — WBS extraction, Project ID, orig_duration, near-critical, task_type, Gantt data
"""
import logging
from datetime import datetime
from typing import Dict, List, Any, Tuple, Optional

logger = logging.getLogger(__name__)

NEAR_CRITICAL_THRESHOLD_HRS = 80.0  # 10 working days

TASK_TYPE_LABELS = {
    "TT_Task":    "Tache",
    "TT_Mile":    "Jalon",
    "TT_Rsrc":    "Ressource",
    "TT_LOE":     "LOE",
    "TT_WBS":     "Niveau WBS",
    "TT_FinMile": "Jalon Fin",
}

def parse_date(date_str):
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

def format_date_fr(dt):
    if not dt:
        return ""
    return dt.strftime("%d/%m/%Y")

def parse_xer_file(content: str) -> dict:
    """
    Parses XER file text and extracts tasks, relations, WBS, and project metadata.
    Returns enriched data for DCMA audit, Gantt rendering, and filtering.
    """
    lines = content.split("\n")
    current_table = ""
    fields = []
    raw_tasks = []
    task_preds = []
    raw_projects = []
    raw_wbs = []
    raw_rsrc = []
    raw_taskrsrc = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("%T"):
            current_table = line[3:].strip()
            fields = []
        elif line.startswith("%F"):
            fields = line[3:].strip().split("\t")
        elif line.startswith("%R"):
            values = line[3:].strip().split("\t")
            row = {}
            for i, f in enumerate(fields):
                if i < len(values):
                    row[f.lower()] = values[i]
            if current_table == "TASK":
                raw_tasks.append(row)
            elif current_table == "TASKPRED":
                task_preds.append(row)
            elif current_table == "PROJECT":
                raw_projects.append(row)
            elif current_table == "PROJWBS":
                raw_wbs.append(row)
            elif current_table == "RSRC":
                raw_rsrc.append(row)
            elif current_table == "TASKRSRC":
                raw_taskrsrc.append(row)

    # Project metadata
    project_name = "Projet Planification"
    project_id = ""
    if raw_projects:
        p = raw_projects[0]
        project_name = p.get("project_name") or p.get("export_project_name") or project_name
        project_id   = p.get("proj_short_name") or p.get("project_id") or ""

    # WBS lookup
    wbs_map  = {}
    wbs_list = []
    for w in raw_wbs:
        wbs_id    = w.get("wbs_id", "")
        parent_id = w.get("parent_wbs_id", "")
        short     = w.get("wbs_short_name", "") or w.get("short_name", "")
        name      = w.get("wbs_name", "") or w.get("name", short)
        if wbs_id:
            wbs_map[wbs_id] = {"short": short, "name": name, "parent_id": parent_id}
            wbs_list.append({"id": wbs_id, "parent_id": parent_id, "short": short, "name": name})

    # Relation sets
    tasks_with_pred = set(p.get("task_id")      for p in task_preds if p.get("task_id"))
    tasks_with_succ = set(p.get("pred_task_id") for p in task_preds if p.get("pred_task_id"))

    # Pre-build task lookup map for predecessors/successors names
    task_info_map = {
        row.get("task_id"): {
            "code": row.get("task_code", ""),
            "name": row.get("task_name", "Activite sans nom")
        }
        for row in raw_tasks if row.get("task_id")
    }

    preds_by_task = {}
    succs_by_task = {}
    for p in task_preds:
        tid = p.get("task_id")
        pid = p.get("pred_task_id")
        ptype = p.get("pred_type", "PR_FS")
        rel_type = ptype.replace("PR_", "") if ptype else "FS"
        try:
            lag_days = float(p.get("lag_hr_cnt") or 0) / 8.0
        except:
            lag_days = 0.0
        if tid and pid:
            if tid not in preds_by_task:
                preds_by_task[tid] = []
            pred_info = task_info_map.get(pid, {"code": f"ID:{pid}", "name": "Activite inconnue"})
            preds_by_task[tid].append({
                "task_id": pid,
                "code": pred_info["code"],
                "name": pred_info["name"],
                "type": rel_type,
                "lag": round(lag_days, 1)
            })
            if pid not in succs_by_task:
                succs_by_task[pid] = []
            succ_info = task_info_map.get(tid, {"code": f"ID:{tid}", "name": "Activite inconnue"})
            succs_by_task[pid].append({
                "task_id": tid,
                "code": succ_info["code"],
                "name": succ_info["name"],
                "type": rel_type,
                "lag": round(lag_days, 1)
            })

    # Resource mapping
    rsrc_map = {
        row.get("rsrc_id"): row.get("rsrc_name") or row.get("rsrc_short_name") or "Ressource sans nom"
        for row in raw_rsrc if row.get("rsrc_id")
    }
    resources_by_task = {}
    for tr in raw_taskrsrc:
        tid = tr.get("task_id")
        rid = tr.get("rsrc_id")
        if tid and rid:
            rname = rsrc_map.get(rid)
            if rname:
                if tid not in resources_by_task:
                    resources_by_task[tid] = []
                resources_by_task[tid].append(rname)

    # Parse TASKRSRC for costs and units
    task_costs = {}
    task_units = {}
    for tr in raw_taskrsrc:
        tid = tr.get("task_id")
        if not tid:
            continue
        try:
            t_qty = float(tr.get("target_qty") or 0.0)
            a_qty = float(tr.get("act_qty") or 0.0)
            t_cost = float(tr.get("target_cost") or tr.get("target_cost_amt") or 0.0)
            a_cost = float(tr.get("act_cost") or tr.get("act_cost_amt") or 0.0)
        except:
            t_qty, a_qty, t_cost, a_cost = 0.0, 0.0, 0.0, 0.0
            
        if tid not in task_costs:
            task_costs[tid] = {"planned": 0.0, "actual": 0.0}
        if tid not in task_units:
            task_units[tid] = {"planned": 0.0, "actual": 0.0}
            
        task_costs[tid]["planned"] += t_cost
        task_costs[tid]["actual"] += a_cost
        task_units[tid]["planned"] += t_qty
        task_units[tid]["actual"] += a_qty

    tasks = []
    for row in raw_tasks:
        def safe_float(v):
            try: return float(v or 0)
            except: return 0.0

        float_val    = safe_float(row.get("total_float_hr_cnt"))
        remain_durn  = safe_float(row.get("remain_drtn_hr_cnt") or row.get("remain_durn_hr_cnt")) / 8.0
        orig_durn    = safe_float(
            row.get("target_drtn_hr_cnt") or 
            row.get("orig_drtn_hr_cnt") or 
            row.get("target_durn_hr_cnt") or 
            row.get("orig_durn_hr_cnt")
        ) / 8.0
        phys_comp    = safe_float(row.get("phys_complete_pct"))
        status_code  = row.get("status_code", "")
        is_done      = status_code in ("TK_Complete", "TK_Suspend")
        is_critical  = float_val <= 0 and not is_done
        is_near_crit = (0 < float_val <= NEAR_CRITICAL_THRESHOLD_HRS) and not is_done

        wbs_id  = row.get("wbs_id", "")
        wbs_info = wbs_map.get(wbs_id, {})
        task_type_raw   = row.get("task_type", "TT_Task")
        task_type_label = TASK_TYPE_LABELS.get(task_type_raw, task_type_raw)

        start_dt = parse_date(row.get("target_start_date") or row.get("act_start_date") or row.get("start_date"))
        end_dt   = parse_date(row.get("target_end_date")   or row.get("act_end_date")   or row.get("end_date"))

        # Fallbacks for cost & units if not cost-loaded in XER
        tid_val = row.get("task_id", "")
        tc_planned = task_costs.get(tid_val, {}).get("planned", 0.0)
        tc_actual = task_costs.get(tid_val, {}).get("actual", 0.0)
        tu_planned = task_units.get(tid_val, {}).get("planned", 0.0)
        tu_actual = task_units.get(tid_val, {}).get("actual", 0.0)
        
        d_days = max(orig_durn, 1.0)
        if tc_planned == 0.0:
            tc_planned = d_days * 1000.0
            tc_actual = tc_planned * (phys_comp / 100.0)
        if tu_planned == 0.0:
            tu_planned = d_days * 8.0
            tu_actual = tu_planned * (phys_comp / 100.0)

        tasks.append({
            "task_id":          row.get("task_id", ""),
            "task_code":        row.get("task_code", ""),
            "task_name":        row.get("task_name", "") or "Activite sans nom",
            "status_code":      status_code,
            "task_type":        task_type_raw,
            "task_type_label":  task_type_label,
            "wbs_id":           wbs_id,
            "wbs_short":        wbs_info.get("short", ""),
            "wbs_name":         wbs_info.get("name", ""),
            "target_start_date": start_dt.strftime("%Y-%m-%d") if start_dt else "",
            "target_end_date":   end_dt.strftime("%Y-%m-%d")   if end_dt   else "",
            "start_formatted":  format_date_fr(start_dt),
            "end_formatted":    format_date_fr(end_dt),
            "orig_durn_days":   round(orig_durn, 1),
            "remain_durn_hr_cnt": remain_durn,
            "total_float_hr_cnt": float_val,
            "total_float_days": round(float_val / 8.0, 1),
            "phys_complete_pct": phys_comp,
            "is_critical":      is_critical,
            "is_near_critical": is_near_crit,
            "has_predecessor":  row.get("task_id") in tasks_with_pred,
            "has_successor":    row.get("task_id") in tasks_with_succ,
            "constraint_type":  row.get("cstr_type", ""),
            "predecessors":     preds_by_task.get(row.get("task_id"), []),
            "successors":       succs_by_task.get(row.get("task_id"), []),
            "resources":        resources_by_task.get(row.get("task_id"), []),
            "planned_cost":     tc_planned,
            "actual_cost":      tc_actual,
            "planned_units":    tu_planned,
            "actual_units":     tu_actual,
        })

    total_tasks       = len(tasks) or 1
    rel_count         = len(task_preds) or 1
    completed_tasks   = sum(1 for t in tasks if t["status_code"] == "TK_Complete")
    critical_tasks    = sum(1 for t in tasks if t["is_critical"])
    near_critical_cnt = sum(1 for t in tasks if t["is_near_critical"])
    in_progress_tasks = sum(1 for t in tasks if t["status_code"] == "TK_Active")
    fs_rels = sum(1 for p in task_preds if p.get("pred_type") == "PR_FS")
    ss_rels = sum(1 for p in task_preds if p.get("pred_type") == "PR_SS")
    ff_rels = sum(1 for p in task_preds if p.get("pred_type") == "PR_FF")
    sf_rels = sum(1 for p in task_preds if p.get("pred_type") == "PR_SF")

    now = datetime.now()
    delayed_list = []
    for t in tasks:
        if t["status_code"] != "TK_Complete":
            end_dt = parse_date(t["target_end_date"])
            if end_dt and end_dt < now:
                delayed_list.append({
                    "task_id":      t["task_id"],
                    "task_code":    t["task_code"],
                    "task_name":    t["task_name"],
                    "formattedEnd": t["end_formatted"],
                    "delayDays":    (now - end_dt).days,
                    "wbs_short":    t["wbs_short"],
                })
    delayed_list.sort(key=lambda x: x["delayDays"], reverse=True)

    task_map = {t["task_id"]: (t["task_code"], t["task_name"]) for t in tasks}

    # --- KPI Analysis & Gaps ---
    # Adjacency list and task details map
    adj = {t["task_id"]: [] for t in tasks}
    task_by_id = {t["task_id"]: t for t in tasks}
    for p in task_preds:
        src = p.get("pred_task_id")
        tgt = p.get("task_id")
        if src in adj and tgt in adj:
            adj[src].append(tgt)

    # 1. Open ends logic lists
    open_ends_list = []
    for t in tasks:
        if t["status_code"] != "TK_Complete":
            if not t["has_predecessor"] and not t["has_successor"]:
                open_ends_list.append({"code": t["task_code"], "name": t["task_name"], "detail": "Sans prédécesseur ni successeur"})
            elif not t["has_predecessor"]:
                open_ends_list.append({"code": t["task_code"], "name": t["task_name"], "detail": "Sans prédécesseur"})
            elif not t["has_successor"]:
                open_ends_list.append({"code": t["task_code"], "name": t["task_name"], "detail": "Sans successeur"})

    # 2. Lags & Leads checks
    lags_list = []
    leads_list = []
    lag_count = 0
    negative_lag_count = 0
    for p in task_preds:
        try:
            lag_val = float(p.get("lag_hr_cnt") or 0)
            pred_id = p.get("pred_task_id")
            succ_id = p.get("task_id")
            if pred_id in task_by_id and succ_id in task_by_id:
                pred_code = task_by_id[pred_id]["task_code"]
                succ_code = task_by_id[succ_id]["task_code"]
                succ_name = task_by_id[succ_id]["task_name"]
                if lag_val > 0:
                    lag_count += 1
                    if len(lags_list) < 20:
                        lags_list.append({"code": succ_code, "name": succ_name, "detail": f"Pred: {pred_code} (Lag: {lag_val/8.0:.1f}j)"})
                elif lag_val < 0:
                    negative_lag_count += 1
                    if len(leads_list) < 20:
                        leads_list.append({"code": succ_code, "name": succ_name, "detail": f"Pred: {pred_code} (Lead: {lag_val/8.0:.1f}j)"})
        except ValueError:
            pass

    # 3. Hard constraints, high float, negative float, long durations
    hard_constraints_list = []
    high_float_list = []
    negative_float_list = []
    high_duration_list = []
    critical_path_list = []
    hard_constraint_types = ["CS_MANDSTRT", "CS_MANDFIN", "CS_MUSTSTRT", "CS_MUSTFIN"]

    for t in tasks:
        if t["constraint_type"] in hard_constraint_types:
            hard_constraints_list.append({"code": t["task_code"], "name": t["task_name"], "detail": f"Contrainte: {t['constraint_type']}"})
        if t["total_float_hr_cnt"] > (44 * 8):
            high_float_list.append({"code": t["task_code"], "name": t["task_name"], "detail": f"Marge: {t['total_float_days']:.1f}j"})
        if t["total_float_hr_cnt"] < 0:
            negative_float_list.append({"code": t["task_code"], "name": t["task_name"], "detail": f"Marge: {t['total_float_days']:.1f}j"})
        if t["remain_durn_hr_cnt"] > 44:
            high_duration_list.append({"code": t["task_code"], "name": t["task_name"], "detail": f"Durée: {t['remain_durn_hr_cnt']:.1f}j"})
        if t["is_critical"]:
            critical_path_list.append({"code": t["task_code"], "name": t["task_name"], "detail": "Activité critique"})

    # 4. Invalid dates
    invalid_dates_list = []
    for t in tasks:
        start_dt = parse_date(t["target_start_date"])
        end_dt = parse_date(t["target_end_date"])
        if start_dt and end_dt and start_dt > end_dt:
            invalid_dates_list.append({
                "code": t["task_code"],
                "name": t["task_name"],
                "detail": f"Début ({format_date_fr(start_dt)}) après Fin ({format_date_fr(end_dt)})"
            })

    # 5. Missing resources
    missing_resources_list = []
    for t in tasks:
        if t["task_type"] == "TT_Task" and t["status_code"] != "TK_Complete":
            if not t.get("resources"):
                missing_resources_list.append({
                    "code": t["task_code"],
                    "name": t["task_name"],
                    "detail": "Aucune ressource affectée"
                })

    # 6. Missed tasks
    now_dt = datetime.now()
    missed_tasks_list = []
    for t in tasks:
        if t["status_code"] != "TK_Complete":
            end_dt = parse_date(t["target_end_date"])
            if end_dt and end_dt < now_dt:
                missed_tasks_list.append({
                    "code": t["task_code"],
                    "name": t["task_name"],
                    "detail": f"Prévue le {format_date_fr(end_dt)}"
                })

    # 7. Critical path continuity test
    critical_path_test_list = []
    crit_tasks = [t for t in tasks if t["is_critical"]]
    crit_ids = {t["task_id"] for t in crit_tasks}
    for t in crit_tasks:
        has_crit_pred = any(p["task_id"] in crit_ids for p in t["predecessors"])
        has_crit_succ = any(s["task_id"] in crit_ids for s in t["successors"])
        is_project_start = not t["has_predecessor"]
        is_project_finish = not t["has_successor"]
        if not is_project_start and not has_crit_pred:
            critical_path_test_list.append({
                "code": t["task_code"],
                "name": t["task_name"],
                "detail": "Rupture : aucun prédécesseur critique"
            })
        elif not is_project_finish and not has_crit_succ:
            critical_path_test_list.append({
                "code": t["task_code"],
                "name": t["task_name"],
                "detail": "Rupture : aucun successeur critique"
            })

    # 8. Baseline Execution Index (BEI)
    should_be_completed = sum(1 for t in tasks if parse_date(t["target_end_date"]) and parse_date(t["target_end_date"]) <= now_dt)
    if should_be_completed == 0:
        bei_value = 1.0
    else:
        bei_value = completed_tasks / should_be_completed

    # 9. Redundant links (transitive reduction path check)
    def has_alternative_path(start, target, current, visited):
        if current == target:
            return True
        if current in visited:
            return False
        visited.add(current)
        for nxt in adj[current]:
            if start == current and nxt == target:
                continue
            if has_alternative_path(start, target, nxt, visited):
                return True
        return False

    redundant_links_list = []
    for p in task_preds:
        src = p.get("pred_task_id")
        tgt = p.get("task_id")
        if src in adj and tgt in adj:
            visited = set()
            if has_alternative_path(src, tgt, src, visited):
                src_code = task_by_id[src]["task_code"]
                tgt_code = task_by_id[tgt]["task_code"]
                redundant_links_list.append({
                    "code": tgt_code,
                    "name": task_by_id[tgt]["task_name"],
                    "detail": f"Lien superflu depuis {src_code}"
                })

    # 10. Out-of-sequence links
    out_of_sequence_list = []
    for p in task_preds:
        pred_id = p.get("pred_task_id")
        succ_id = p.get("task_id")
        pred_type = p.get("pred_type", "PR_FS")
        if pred_id in task_by_id and succ_id in task_by_id:
            pred = task_by_id[pred_id]
            succ = task_by_id[succ_id]
            pred_end = parse_date(pred["target_end_date"])
            succ_start = parse_date(succ["target_start_date"])
            if pred_end and succ_start and "FS" in pred_type and succ_start < pred_end:
                out_of_sequence_list.append({
                    "code": succ["task_code"],
                    "name": succ["task_name"],
                    "detail": f"Début avant fin de {pred['task_code']}"
                })

    # Counts
    open_ends_count = len(open_ends_list)
    hard_constraint_count = len(hard_constraints_list)
    high_float_count = len(high_float_list)
    negative_float_count = len(negative_float_list)
    high_duration_count = len(high_duration_list)
    invalid_dates_count = len(invalid_dates_list)
    missing_resources_count = len(missing_resources_list)
    missed_tasks_count = len(missed_tasks_list)
    critical_path_test_count = len(critical_path_test_list)
    redundant_links_count = len(redundant_links_list)
    out_of_sequence_count = len(out_of_sequence_list)
    critical_tasks_pct = (critical_tasks / total_tasks) * 100

    stats = {
        "totalTasks":           total_tasks,
        "completedTasks":       completed_tasks,
        "criticalTasks":        critical_tasks,
        "nearCriticalTasks":    near_critical_cnt,
        "inProgressTasks":      in_progress_tasks,
        "averageProgress":      sum(t["phys_complete_pct"] for t in tasks) / len(tasks) if tasks else 0.0,
        "delayedTasks":         len(delayed_list),
        "openEndsCount":        open_ends_count,
        "lagCount":             lag_count,
        "negativeLagCount":     negative_lag_count,
        "hardConstraintCount":  hard_constraint_count,
        "highFloatCount":       high_float_count,
        "negativeFloatCount":   negative_float_count,
        "highDurationCount":    high_duration_count,
        "invalidDatesCount":    invalid_dates_count,
        "missingResourcesCount": missing_resources_count,
        "missedTasksCount":     missed_tasks_count,
        "criticalPathTestCount": critical_path_test_count,
        "redundantLinksCount":  redundant_links_count,
        "outOfSequenceCount":   out_of_sequence_count,
        "notFSRelationshipCount": ss_rels + ff_rels + sf_rels,
        "fsRelationshipCount":  fs_rels,
        "ssRelationshipCount":  ss_rels,
        "ffRelationshipCount":  ff_rels,
        "sfRelationshipCount":  sf_rels,
        "criticalTasksPct":     critical_tasks_pct,
        "nearCriticalTasksPct": (near_critical_cnt / total_tasks) * 100,
        "maxTotalFloat":        max((t["total_float_hr_cnt"] / 8.0 for t in tasks), default=0.0),
        "projectId":            project_id,
        "wbsList":              wbs_list,
        "overallScore":         0
    }

    health_check = [
        {"id": 1,  "key": "open_ends",       "description": "DCMA 1 : Liaisons ouvertes (Open Ends)",       "threshold": "<5%",   "target": 5,  "actual": round((open_ends_count / total_tasks)*100),      "unit": "%",   "status": "green" if (open_ends_count/total_tasks)<=0.05 else "red",      "failingTasks": open_ends_list[:15]},
        {"id": 2,  "key": "leads",            "description": "DCMA 2 : Lags negatifs (Leads)",             "threshold": "0",     "target": 0,  "actual": negative_lag_count,                              "unit": "rel", "status": "green" if negative_lag_count==0 else "red",                   "failingTasks": leads_list[:15]},
        {"id": 3,  "key": "lags",             "description": "DCMA 3 : Lags positifs (Lags)",              "threshold": "<5%",   "target": 5,  "actual": round((lag_count/total_tasks)*100),               "unit": "%",   "status": "green" if (lag_count/total_tasks)<=0.05 else "red",            "failingTasks": lags_list[:15]},
        {"id": 4,  "key": "fs_rels",          "description": "DCMA 4 : Types de relations (Ratio FS)",     "threshold": ">90%",  "target": 90, "actual": round((fs_rels/rel_count)*100),                  "unit": "%",   "status": "green" if (fs_rels/rel_count)>=0.9 else "red",                "failingTasks": []},
        {"id": 5,  "key": "hard_constraints", "description": "DCMA 5 : Contraintes strictes (Hard)",       "threshold": "<5%",   "target": 5,  "actual": round((hard_constraint_count/total_tasks)*100),   "unit": "%",   "status": "green" if (hard_constraint_count/total_tasks)<=0.05 else "red","failingTasks": hard_constraints_list[:15]},
        {"id": 6,  "key": "high_float",       "description": "DCMA 6 : Marge elevee (High Float >44d)",     "threshold": "<5%",   "target": 5,  "actual": round((high_float_count/total_tasks)*100),        "unit": "%",   "status": "green" if (high_float_count/total_tasks)<=0.05 else "red",     "failingTasks": high_float_list[:15]},
        {"id": 7,  "key": "negative_float",   "description": "DCMA 7 : Marge negative (Negative Float)",    "threshold": "0",     "target": 0,  "actual": negative_float_count,                            "unit": "act", "status": "green" if negative_float_count==0 else "red",                 "failingTasks": negative_float_list[:15]},
        {"id": 8,  "key": "long_durations",   "description": "DCMA 8 : Durees longues (>44d)",              "threshold": "<5%",   "target": 5,  "actual": round((high_duration_count/total_tasks)*100),     "unit": "%",   "status": "green" if (high_duration_count/total_tasks)<=0.05 else "red",  "failingTasks": high_duration_list[:15]},
        {"id": 9,  "key": "invalid_dates",    "description": "DCMA 9 : Dates invalides (Invalid Dates)",    "threshold": "0",     "target": 0,  "actual": invalid_dates_count,                             "unit": "act", "status": "green" if invalid_dates_count==0 else "red",                  "failingTasks": invalid_dates_list[:15]},
        {"id": 10, "key": "resources",        "description": "DCMA 10 : Taches sans ressource (Resources)", "threshold": "<5%",   "target": 5,  "actual": round((missing_resources_count/total_tasks)*100), "unit": "%",   "status": "green" if (missing_resources_count/total_tasks)<=0.05 else "red","failingTasks": missing_resources_list[:15]},
        {"id": 11, "key": "missed_tasks",     "description": "DCMA 11 : Taches en retard (Missed Tasks)",   "threshold": "<5%",   "target": 5,  "actual": round((missed_tasks_count/total_tasks)*100),      "unit": "%",   "status": "green" if (missed_tasks_count/total_tasks)<=0.05 else "red",    "failingTasks": missed_tasks_list[:15]},
        {"id": 12, "key": "critical_path_test","description": "DCMA 12 : Test de continuite chemin crit.",  "threshold": "100%",  "target": 100,"actual": 100 if critical_path_test_count==0 else 0,       "unit": "%",   "status": "green" if critical_path_test_count==0 else "red",              "failingTasks": critical_path_test_list[:15]},
        {"id": 13, "key": "critical_path",    "description": "DCMA 13 : Densite du chemin critique",         "threshold": "10-25%","target": 15, "actual": round(critical_tasks_pct),                       "unit": "%",   "status": "green" if 10<=critical_tasks_pct<=25 else "red",               "failingTasks": critical_path_list[:15]},
        {"id": 14, "key": "bei",              "description": "DCMA 14 : Indice d'execution (BEI)",          "threshold": ">=1.0", "target": 1.0,"actual": round(bei_value, 2),                             "unit": "idx", "status": "green" if bei_value>=1.0 else "red",                           "failingTasks": missed_tasks_list[:15]},
        {"id": 15, "key": "redundant_links",   "description": "Liaisons redundantes (Transitives)",          "threshold": "<10%",  "target": 10, "actual": round((redundant_links_count/total_tasks)*100),   "unit": "%",   "status": "green" if (redundant_links_count/total_tasks)<=0.10 else "red","failingTasks": redundant_links_list[:15]},
        {"id": 16, "key": "out_of_sequence",  "description": "Liaisons hors-sequence (Out-of-Seq)",         "threshold": "0",     "target": 0,  "actual": out_of_sequence_count,                           "unit": "act", "status": "green" if out_of_sequence_count==0 else "red",                "failingTasks": out_of_sequence_list[:15]},
    ]
    pass_count = sum(1 for h in health_check if h["status"] != "red")
    stats["overallScore"] = round((pass_count / len(health_check)) * 100)

    gantt_tasks = sorted(
        [t for t in tasks if t["target_start_date"]],
        key=lambda t: t["target_start_date"]
    )[:5000]

    # ============================================================
    # NEW: EVM & S-CURVE CALCULATIONS
    # ============================================================
    import datetime as dt_mod

    # 1. Determine timeline range
    project_start_date = None
    project_end_date = None
    for t in tasks:
        s_d = parse_date(t["target_start_date"])
        e_d = parse_date(t["target_end_date"])
        if s_d:
            if not project_start_date or s_d < project_start_date:
                project_start_date = s_d
        if e_d:
            if not project_end_date or e_d > project_end_date:
                project_end_date = e_d

    if not project_start_date:
        project_start_date = datetime.now()
    if not project_end_date:
        project_end_date = project_start_date + dt_mod.timedelta(days=30)

    total_project_days = (project_end_date - project_start_date).days or 1

    # Group timeline into points (max 60 points)
    step_days = max(1, total_project_days // 60)
    timeline_dates = []
    curr_d = project_start_date
    while curr_d <= project_end_date:
        timeline_dates.append(curr_d)
        curr_d += dt_mod.timedelta(days=step_days)
    if not timeline_dates or timeline_dates[-1] < project_end_date:
        timeline_dates.append(project_end_date)

    evm_dates_labels = [d.strftime("%Y-%m-%d") for d in timeline_dates]

    pv_cost_series = []
    ev_cost_series = []
    ac_cost_series = []
    pv_units_series = []
    ev_units_series = []
    ac_units_series = []

    # Get P6 Recalc date / Cut-off date
    status_date_obj = None
    if raw_projects:
        p_meta = raw_projects[0]
        status_date_obj = parse_date(p_meta.get("last_recalc_date") or p_meta.get("status_date"))
    if not status_date_obj:
        status_date_obj = datetime.now()
        if status_date_obj < project_start_date:
            status_date_obj = project_start_date + dt_mod.timedelta(days=total_project_days // 3)
        elif status_date_obj > project_end_date:
            status_date_obj = project_end_date

    # Pre-calculate task timeline details
    task_time_data = []
    for t in tasks:
        s_d = parse_date(t["target_start_date"]) or project_start_date
        e_d = parse_date(t["target_end_date"]) or project_end_date
        t_dur = max(1, (e_d - s_d).days)
        task_time_data.append({
            "task_id": t["task_id"],
            "start": s_d,
            "end": e_d,
            "duration": t_dur,
            "p_cost": t["planned_cost"],
            "a_cost": t["actual_cost"],
            "p_units": t["planned_units"],
            "a_units": t["actual_units"],
            "progress": t["phys_complete_pct"]
        })

    for d_point in timeline_dates:
        pv_c = 0.0
        ev_c = 0.0
        ac_c = 0.0
        pv_u = 0.0
        ev_u = 0.0
        ac_u = 0.0

        for t_info in task_time_data:
            s_d = t_info["start"]
            e_d = t_info["end"]
            t_dur = t_info["duration"]

            # Planned Value
            if d_point >= e_d:
                pv_c += t_info["p_cost"]
                pv_u += t_info["p_units"]
            elif d_point >= s_d:
                frac = (d_point - s_d).days / t_dur
                pv_c += t_info["p_cost"] * frac
                pv_u += t_info["p_units"] * frac

            # Actual & Earned (only up to status date/cutoff)
            if d_point <= status_date_obj:
                if d_point >= e_d:
                    ev_c += t_info["p_cost"] * (t_info["progress"] / 100.0)
                    ev_u += t_info["p_units"] * (t_info["progress"] / 100.0)
                elif d_point >= s_d:
                    worked_days = max(1, (status_date_obj - s_d).days)
                    frac_worked = min(1.0, (d_point - s_d).days / worked_days)
                    ev_c += t_info["p_cost"] * (t_info["progress"] / 100.0) * frac_worked
                    ev_u += t_info["p_units"] * (t_info["progress"] / 100.0) * frac_worked

                if d_point >= e_d:
                    ac_c += t_info["a_cost"]
                    ac_u += t_info["a_units"]
                elif d_point >= s_d:
                    worked_days = max(1, (status_date_obj - s_d).days)
                    frac_worked = min(1.0, (d_point - s_d).days / worked_days)
                    ac_c += t_info["a_cost"] * frac_worked
                    ac_u += t_info["a_units"] * frac_worked

        pv_cost_series.append(round(pv_c, 2))
        pv_units_series.append(round(pv_u, 2))

        if d_point <= status_date_obj:
            ev_cost_series.append(round(ev_c, 2))
            ac_cost_series.append(round(ac_c, 2))
            ev_units_series.append(round(ev_u, 2))
            ac_units_series.append(round(ac_u, 2))
        else:
            ev_cost_series.append(None)
            ac_cost_series.append(None)
            ev_units_series.append(None)
            ac_units_series.append(None)

    total_planned_cost = sum(t["planned_cost"] for t in tasks)
    total_planned_units = sum(t["planned_units"] for t in tasks)

    current_pv_cost = 0.0
    current_ev_cost = 0.0
    current_ac_cost = 0.0
    current_pv_units = 0.0
    current_ev_units = 0.0
    current_ac_units = 0.0

    for t_info in task_time_data:
        s_d = t_info["start"]
        e_d = t_info["end"]
        t_dur = t_info["duration"]

        if status_date_obj >= e_d:
            current_pv_cost += t_info["p_cost"]
            current_pv_units += t_info["p_units"]
        elif status_date_obj >= s_d:
            frac = (status_date_obj - s_d).days / t_dur
            current_pv_cost += t_info["p_cost"] * frac
            current_pv_units += t_info["p_units"] * frac

        current_ev_cost += t_info["p_cost"] * (t_info["progress"] / 100.0)
        current_ev_units += t_info["p_units"] * (t_info["progress"] / 100.0)

        current_ac_cost += t_info["a_cost"]
        current_ac_units += t_info["a_units"]

    spi_cost = round(current_ev_cost / current_pv_cost, 2) if current_pv_cost > 0 else 1.0
    cpi_cost = round(current_ev_cost / current_ac_cost, 2) if current_ac_cost > 0 else 1.0
    eac_cost = round(total_planned_cost / cpi_cost, 2) if cpi_cost > 0 else total_planned_cost
    vac_cost = round(total_planned_cost - eac_cost, 2)

    spi_units = round(current_ev_units / current_pv_units, 2) if current_pv_units > 0 else 1.0
    cpi_units = round(current_ev_units / current_ac_units, 2) if current_ac_units > 0 else 1.0
    eac_units = round(total_planned_units / cpi_units, 2) if cpi_units > 0 else total_planned_units
    vac_units = round(total_planned_units - eac_units, 2)

    # ============================================================
    # NEW: MONTE CARLO STRESS RISK ANALYSIS
    # ============================================================
    import numpy as np

    task_by_id = {t["task_id"]: t for t in tasks}
    iterations = 1000
    num_tasks = len(tasks)
    
    mins = np.zeros(num_tasks)
    modes = np.zeros(num_tasks)
    maxs = np.zeros(num_tasks)
    
    for i, t in enumerate(tasks):
        orig = t["orig_durn_days"]
        if orig > 0 and t["task_type"] not in ("TT_Mile", "TT_FinMile"):
            mins[i] = orig * 0.85
            modes[i] = orig
            maxs[i] = orig * 1.35

    durations_matrix = np.zeros((iterations, num_tasks))
    valid_mask = maxs > mins
    if np.any(valid_mask):
        durations_matrix[:, valid_mask] = np.random.triangular(
            mins[valid_mask], modes[valid_mask], maxs[valid_mask], 
            size=(iterations, np.sum(valid_mask))
        )

    run_finishes_arr = np.sum(durations_matrix, axis=1)
    run_finishes = run_finishes_arr.tolist()

    p10_days = float(np.percentile(run_finishes_arr, 10))
    p50_days = float(np.percentile(run_finishes_arr, 50))
    p80_days = float(np.percentile(run_finishes_arr, 80))
    p90_days = float(np.percentile(run_finishes_arr, 90))
    
    task_critical_counts = {t["task_id"]: 0 for t in tasks}

    p50_date = project_start_date + dt_mod.timedelta(days=p50_days)
    p80_date = project_start_date + dt_mod.timedelta(days=p80_days)
    p90_date = project_start_date + dt_mod.timedelta(days=p90_days)

    base_finish_days = max( ((parse_date(t["target_end_date"]) or project_end_date) - project_start_date).days for t in tasks ) if tasks else 0
    base_finish_date = project_start_date + dt_mod.timedelta(days=base_finish_days)

    prob_vs_base_cnt = sum(1 for f in run_finishes if f <= base_finish_days)
    prob_vs_base = round((prob_vs_base_cnt / iterations) * 100)

    finish_dates_counts = {}
    for f in run_finishes:
        fd = (project_start_date + dt_mod.timedelta(days=f)).strftime("%Y-%m-%d")
        finish_dates_counts[fd] = finish_dates_counts.get(fd, 0) + 1

    risk_histogram = [
        {"date": fd, "count": count}
        for fd, count in sorted(finish_dates_counts.items())
    ]

    task_criticality_map = {
        task_by_id[tid]["task_code"]: round((count / iterations) * 100)
        for tid, count in task_critical_counts.items()
    }

    # Add Monte Carlo & EVM KPIs to global stats
    stats["bacCost"] = total_planned_cost
    stats["spiCost"] = spi_cost
    stats["cpiCost"] = cpi_cost
    stats["eacCost"] = eac_cost
    stats["vacCost"] = vac_cost
    stats["p50Date"] = p50_date.strftime("%Y-%m-%d")
    stats["p80Date"] = p80_date.strftime("%Y-%m-%d")
    stats["p90Date"] = p90_date.strftime("%Y-%m-%d")
    stats["probVsBase"] = prob_vs_base

    return {
        "stats":        stats,
        "tasks":        tasks,
        "ganttTasks":   gantt_tasks,
        "projectName":  project_name,
        "projectId":    project_id,
        "wbsList":      wbs_list,
        "healthCheck":  health_check,
        "delayedTasks": delayed_list,
        "evm": {
            "dates": evm_dates_labels,
            "pv_cost": pv_cost_series,
            "ev_cost": ev_cost_series,
            "ac_cost": ac_cost_series,
            "pv_units": pv_units_series,
            "ev_units": ev_units_series,
            "ac_units": ac_units_series,
            "cutoff_date": status_date_obj.strftime("%Y-%m-%d")
        },
        "risk": {
            "p50": p50_date.strftime("%Y-%m-%d"),
            "p80": p80_date.strftime("%Y-%m-%d"),
            "p90": p90_date.strftime("%Y-%m-%d"),
            "prob_vs_base": prob_vs_base,
            "base_finish": base_finish_date.strftime("%Y-%m-%d"),
            "histogram": risk_histogram,
            "criticality": task_criticality_map
        }
    }


async def generate_ai_planning_report(data: dict, lang: str = "fr", rag_context: str = "") -> str:
    """
    Calls the local LLM via call_llm to perform schedule audit analysis.
    """
    health_summary = "\n".join(
        f"- {h['description']}: {h['actual']}{h['unit']} (Statut: {'Succes' if h['status'] != 'red' else 'Echec'})"
        for h in data["healthCheck"]
    )
    
    # Format top 5 critical tasks for prompt context
    crit_list = data.get("criticalTasks") or []
    if crit_list:
        critical_summary = "\n".join(
            f"- {t.get('task_code')} : {t.get('task_name')} (Debut: {t.get('start_formatted') or t.get('target_start_date')}, Fin: {t.get('end_formatted') or t.get('target_end_date')}, Marge: {t.get('total_float_days', 0)}j)"
            for t in crit_list[:5]
        )
    else:
        critical_summary = "Aucune activite critique particuliere."

    # Format top 5 delayed tasks for prompt context
    del_list = data.get("delayedTasks") or []
    if del_list:
        delayed_summary = "\n".join(
            f"- {t.get('task_code')} : {t.get('task_name')} (Fin Prevue: {t.get('formattedEnd') or t.get('end_formatted')}, Retard: {t.get('delayDays')} jours)"
            for t in del_list[:5]
        )
    else:
        delayed_summary = "Aucune activite en retard particuliere."

    system_prompt = (
        "You are a Senior Planning & Scheduling Consultant expert in DCMA 14-point schedule audits.\n"
        "Analyze the project data and provide a detailed report in three distinct sections:\n\n"
        "SECTION1: [Structural & Critical Path Risks]\n"
        "Discuss logic breaks, critical path density/continuity issues, structural float anomalies, redundant (transitive) links, and out-of-sequence links.\n"
        "Cite the key critical or delayed activities by name/code and explain their impact on the project.\n\n"
        "SECTION2: [Technical Gap Analysis]\n"
        "Explain the 'Why' behind logic fails, negative floats, hard constraints, lags, missing resources, and execution index (BEI) deviations.\n\n"
        "SECTION3: [Correction Roadmap]\n"
        "Provide actionable DOs and DONTs for the planner to fix the schedule, clean up obsolete links, and restore critical path integrity.\n\n"
        "Format the response professionally. Use the exact SECTION1:, SECTION2:, SECTION3: headers."
    )
    if rag_context:
        system_prompt += (
            f"\n\nUse corporate planning guidelines from RAG Context:\n"
            f"=== CORPORATE GUIDELINES ===\n{rag_context}\n============================\n"
        )
    near_critical = data["stats"].get("nearCriticalTasks", 0)
    if lang == "en":
        prompt = (
            f"Project: {data['projectName']} (ID: {data['stats'].get('projectId', 'N/A')})\n"
            f"Total Activities: {data['stats']['totalTasks']}\n"
            f"Critical Path Density: {round(data['stats']['criticalTasksPct'])}%\n"
            f"Near-Critical Activities: {near_critical}\n"
            f"Overall Health Score: {data['stats']['overallScore']}%\n\n"
            f"EVM Performance Index: SPI = {data['stats'].get('spiCost', 1.0)}, CPI = {data['stats'].get('cpiCost', 1.0)}\n"
            f"Estimated budget at completion (EAC): {data['stats'].get('eacCost', 0.0)} DZD (Planned BAC: {data['stats'].get('bacCost', 0.0)} DZD)\n"
            f"Monte Carlo Date Confidences: P50 = {data['stats'].get('p50Date', 'N/A')}, P80 = {data['stats'].get('p80Date', 'N/A')}, P90 = {data['stats'].get('p90Date', 'N/A')}\n"
            f"Probability to finish before the deterministic base date: {data['stats'].get('probVsBase', 0)}%\n\n"
            f"DCMA Audit Indicators:\n{health_summary}\n\n"
            f"Key Critical Tasks to Analyze:\n{critical_summary}\n\n"
            f"Key Delayed Tasks to Analyze:\n{delayed_summary}\n\n"
            f"Please generate the strategic report in English."
        )
    elif lang == "ar":
        prompt = (
            f"\u0645\u0634\u0631\u0648\u0639: {data['projectName']}\n"
            f"\u0625\u062c\u0645\u0627\u0644\u064a \u0627\u0644\u0623\u0646\u0634\u0637\u0629: {data['stats']['totalTasks']}\n"
            f"\u0643\u062b\u0627\u0641\u0629 \u0627\u0644\u0645\u0633\u0627\u0631 \u0627\u0644\u062d\u0631\u062c: {round(data['stats']['criticalTasksPct'])}%\n"
            f"EVM (SPI/CPI): {data['stats'].get('spiCost', 1.0)} / {data['stats'].get('cpiCost', 1.0)}\n"
            f"Monte Carlo P80: {data['stats'].get('p80Date', 'N/A')}\n"
            f"DCMA:\n{health_summary}\n\n"
            f"Key Critical:\n{critical_summary}\n\n"
            f"Key Delayed:\n{delayed_summary}\n\n"
            f"\u0627\u0644\u0631\u062c\u0627\u0621 \u062a\u0648\u0644\u064a\u062f \u0627\u0644\u062a\u0642\u0631\u064a\u0631 \u0628\u0627\u0644\u0639\u0631\u0628\u064a\u0629."
        )
    else:
        prompt = (
            f"Projet: {data['projectName']} (ID: {data['stats'].get('projectId', 'N/A')})\n"
            f"Total Activites: {data['stats']['totalTasks']}\n"
            f"Densite Chemin Critique: {round(data['stats']['criticalTasksPct'])}%\n"
            f"Activites Near-Critical: {near_critical}\n"
            f"Score Global de Sante: {data['stats']['overallScore']}%\n\n"
            f"Indices EVM : SPI = {data['stats'].get('spiCost', 1.0)}, CPI = {data['stats'].get('cpiCost', 1.0)}\n"
            f"Budget estimé à terminaison (EAC) : {data['stats'].get('eacCost', 0.0)} DZD (BAC Planifié : {data['stats'].get('bacCost', 0.0)} DZD)\n"
            f"Monte Carlo Confiances Dates : P50 = {data['stats'].get('p50Date', 'N/A')}, P80 = {data['stats'].get('p80Date', 'N/A')}, P90 = {data['stats'].get('p90Date', 'N/A')}\n"
            f"Probabilité de finir avant la date planifiée de base : {data['stats'].get('probVsBase', 0)}%\n\n"
            f"Indicateurs DCMA:\n{health_summary}\n\n"
            f"Principales activites critiques a commenter :\n{critical_summary}\n\n"
            f"Principales activites en retard a commenter :\n{delayed_summary}\n\n"
            f"Generer le rapport en Francais."
        )
    from api_enhanced import call_llm
    try:
        return await call_llm(prompt, system_prompt, timeout=600)
    except Exception as e:
        logger.error("[Planning AI] LLM invocation failed: %s", e)
        return "Erreur lors de la generation du rapport par le modele local."
