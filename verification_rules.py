import json
import re
import hashlib
import logging
from collections import defaultdict
from pathlib import Path

from verification_db import (
    get_db_connection,
    save_verification_results,
    get_exceptions
)
from engineering_tools import UNIT_TABLE

logger = logging.getLogger(__name__)


def normalize_value(val_str: str, unit: str) -> tuple[float, str]:
    """Normalize numeric values to standard units for comparison (bar, °C, m³/h, kW)."""
    try:
        val = float(val_str)
    except ValueError:
        return None, unit
        
    u = unit.lower().strip()
    
    # 1. Pressions -> bar
    if u in ("psi", "psig"):
        return val / 14.5038, "bar"
    elif u == "kpa":
        return val / 100.0, "bar"
    elif u == "mpa":
        return val * 10.0, "bar"
    
    # 2. Débits -> m3/h
    elif u in ("gpm", "gpm"):
        return val / 4.40287, "m3/h"
    elif u == "m3/s" or u == "m³/s":
        return val * 3600.0, "m3/h"
    elif u in ("l/s", "ls"):
        return val * 3.6, "m3/h"
        
    return val, u


def is_value_different(val_a: str, unit_a: str, val_b: str, unit_b: str, tolerance: float = 0.05) -> bool:
    """Compare two engineering values, applying unit conversion and a percentage tolerance."""
    # Try float comparison
    norm_a, n_unit_a = normalize_value(val_a, unit_a)
    norm_b, n_unit_b = normalize_value(val_b, unit_b)
    
    if norm_a is not None and norm_b is not None:
        if n_unit_a == n_unit_b:
            diff_ratio = abs(norm_a - norm_b) / (max(norm_a, norm_b) + 1e-8)
            return diff_ratio > tolerance
            
    # Fallback to string normalization comparison for materials/descriptions
    clean_a = re.sub(r"[\s\-\_]+", "", val_a.lower())
    clean_b = re.sub(r"[\s\-\_]+", "", val_b.lower())
    
    # Check if one is a substring of the other (ex: "acier inoxydable 316L" contains "316L")
    if len(clean_a) >= 3 and len(clean_b) >= 3:
        if clean_a in clean_b or clean_b in clean_a:
            return False
            
    return clean_a != clean_b


def check_exception_suppression(tag: str, rule_id: str, value_a: str, value_b: str, exceptions: list[dict]) -> bool:
    """Check if an anomaly should be suppressed because of a learned exception."""
    for exc in exceptions:
        # Check tag and rule
        if exc["rule_id"] != rule_id:
            continue
        if exc["tag"] and exc["tag"].upper() != tag.upper():
            continue
            
        # If conditions exist
        conditions = exc.get("condition_scope", {})
        if not conditions:
            # Global exception for tag or rule
            return True
            
        # Check if values fall under exception scope (e.g. pressure < 10)
        try:
            max_press = conditions.get("max_pressure")
            if max_press is not None:
                # Get max of both values
                press_a, _ = normalize_value(value_a, "bar")
                press_b, _ = normalize_value(value_b, "bar")
                p = max(press_a or 0, press_b or 0)
                if p <= float(max_press):
                    return True
        except Exception:
            pass
            
    return False


def get_project_dir_path(project_id: str) -> Path:
    """Resolve project directory path from project_id."""
    base_dir = Path("d:/DATA BASE IA")
    data_path = base_dir / "data"
    
    # 1. Check data/00-Projet/
    proj_path = data_path / "00-Projet"
    if proj_path.exists():
        for p in proj_path.iterdir():
            if p.is_dir():
                if p.name.lower().replace(" ", "_").replace("&", "and") == project_id.lower():
                    return p
    # 2. Fallback
    return data_path / project_id


def load_project_specs(project_id: str) -> dict:
    """Load declarative project specifications from project folder or fall back to defaults."""
    project_dir = get_project_dir_path(project_id)
    specs_file = project_dir / "project_specs.json"
    
    # Defaults
    defaults = {
        "project_id": project_id,
        "project_name": project_id.upper(),
        "required_flange_facing": "RTJ",
        "noise_limit_continuous_dba": 85.0,
        "noise_limit_upset_dba": 110.0,
        "duplex_min_hardness_hb": 220.0,
        "sour_service": True,
        "allowable_design_pressure_margin_pct": 10.0,
        "allowable_design_pressure_margin_min_bar": 2.0,
        "allowable_design_temperature_margin_degc": 10.0,
        "npsh_safety_margin_m": 1.0
    }
    
    if specs_file.exists():
        try:
            with open(specs_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    if isinstance(v, (int, float)):
                        defaults[k] = float(v)
                    else:
                        defaults[k] = v
        except Exception as e:
            logger.error("Failed to load project_specs.json at %s: %s", specs_file, e)
            
    return defaults


def load_project_documents_text(project_dir: Path) -> dict[str, str]:
    """Read and preprocess text from all files in the project folder."""
    import os
    docs_text = {}
    if not project_dir.exists():
        return docs_text
        
    for root, _, files in os.walk(project_dir):
        for file in files:
            if file.startswith("~$") or file.startswith("."):
                continue
            path = Path(root) / file
            text = ""
            try:
                if file.endswith(".pdf"):
                    from extractors import extract_pdf
                    res = extract_pdf(str(path))
                    text = res.get("text", "")
                elif file.endswith(".docx"):
                    import docx
                    doc = docx.Document(str(path))
                    text = "\n".join([p.text for p in doc.paragraphs])
                elif file.endswith(".txt") or file.endswith(".md"):
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
            except Exception as e:
                logger.error("Error reading %s for LLM: %s", file, e)
                
            if text.strip():
                from verification_extractors import preprocess_fragmented_text
                cleaned = preprocess_fragmented_text(text)
                # Cap to prevent token limit overflow (16k total context)
                if len(cleaned) > 20000:
                    cleaned = cleaned[:20000] + "\n... [TRUNCATED] ..."
                docs_text[file] = cleaned
    return docs_text


def run_semantic_llm_verification(project_id: str, exceptions: list[dict]) -> list[dict]:
    """Use Ollama local LLM to do semantic validation of all documents in the project."""
    import httpx
    
    # Check if Ollama is online before loading texts or initiating request
    try:
        from config import OLLAMA_BASE_URL
    except ImportError:
        OLLAMA_BASE_URL = "http://localhost:11434"
        
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=0.2)
        if resp.status_code != 200:
            logger.warning("Ollama is offline. Bypassing semantic LLM verification.")
            return []
    except Exception:
        logger.warning("Ollama is offline. Bypassing semantic LLM verification.")
        return []

    project_dir = get_project_dir_path(project_id)
    docs_text = load_project_documents_text(project_dir)
    if not docs_text:
        logger.info("No documents found for semantic verification in project %s", project_id)
        return []
        
    try:
        from config import LLM_MODEL, OLLAMA_BASE_URL, LLM_TIMEOUT
    except ImportError:
        LLM_MODEL = "qwen2.5:14b"
        OLLAMA_BASE_URL = "http://localhost:11434"
        LLM_TIMEOUT = 300
        
    system_prompt = (
        "En tant qu'ingénieur principal en contrôle qualité et ingénierie dans l'industrie Oil & Gas, "
        "votre rôle est d'analyser sémantiquement les documents d'ingénierie d'un projet pour identifier "
        "les contradictions de conception technique selon les standards Bechtel, Fluor, Technip et Shell.\n\n"
        "Inspectez les documents fournis (Data Sheets, Spécifications, Plans) et recherchez :\n"
        "1. Contradictions de pressions, de températures, de débits, de diamètres et de matériaux.\n"
        "2. Écarts par rapport aux spécifications (ex: brides de sortie asymétriques là où le même rating est exigé, faces de brides RF vs exigence RTJ, etc.).\n"
        "3. Seuils acoustiques ou de bruit (ex: niveau de bruit de 85 dBA dans la Data Sheet vs 95 dBA / 110 dBA limites spécification).\n\n"
        "Retournez UNIQUEMENT une liste JSON valide. Chaque anomalie doit avoir la structure suivante :\n"
        "{\n"
        "  \"tag\": \"Tag de l'équipement (ex: HV-0102, V-102) ou 'GLOBAL'\",\n"
        "  \"rule_id\": \"Identifiant de règle (ex: COH_FLANGE_RATING, COH_SOUND_PRESSURE_LEVEL, COH_PRESSURE_DISCREPANCY)\",\n"
        "  \"severity\": \"MAJEUR\" ou \"BLOQUANT\" ou \"MINEUR\",\n"
        "  \"description\": \"Description claire et détaillée en français du problème, citant les valeurs contradictoires et leurs sources.\",\n"
        "  \"doc_source_a\": \"Nom du document A\",\n"
        "  \"value_a\": \"Valeur document A\",\n"
        "  \"doc_source_b\": \"Nom du document B\",\n"
        "  \"value_b\": \"Valeur document B\"\n"
        "}\n\n"
        "Ne retournez aucune phrase d'explication en dehors du JSON. Juste le JSON."
    )
    
    user_prompt = f"Voici les documents du projet {project_id} :\n\n"
    for filename, text in docs_text.items():
        user_prompt += f"=== DOCUMENT: {filename} ===\n{text}\n\n"
    user_prompt += "Analysez ces documents et retournez les anomalies au format JSON."
    
    logger.info("Calling local LLM (%s) for semantic verification of project %s...", LLM_MODEL, project_id)
    
    try:
        resp = httpx.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_ctx": 16384,
                },
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        
        # Clean JSON block
        json_match = re.search(r"(\[.*\])", content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
            
        anomalies = []
        parsed = json.loads(content.strip())
        for a in parsed:
            tag = a.get("tag", "GLOBAL").upper()
            rule_id = a.get("rule_id", "COH_SEMANTIC")
            val_a = str(a.get("value_a", ""))
            val_b = str(a.get("value_b", ""))
            
            if check_exception_suppression(tag, rule_id, val_a, val_b, exceptions):
                continue
                
            sig = f"{project_id}:{tag}:{rule_id}:{a.get('doc_source_a','')}:{a.get('doc_source_b','')}"
            rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
            
            anomalies.append({
                "result_id": rid,
                "tag": tag,
                "rule_id": rule_id,
                "severity": a.get("severity", "MAJEUR"),
                "description": a.get("description", "Incohérence détectée par IA."),
                "doc_source_a": a.get("doc_source_a", ""),
                "value_a": val_a,
                "doc_source_b": a.get("doc_source_b", ""),
                "value_b": val_b
            })
        logger.info("LLM semantic verification found %d anomalies", len(anomalies))
        return anomalies
    except Exception as e:
        logger.error("LLM semantic verification failed: %s", e)
        return []
def run_wiring_verification(project_id: str, exceptions: list[dict]) -> list[dict]:
    """Audit wiring schedules, terminal strip connections, and DCS signal types if files are available."""
    project_dir = get_project_dir_path(project_id)
    inst_path = project_dir / "instrument_index.json"
    cable_path = project_dir / "cable_schedule.json"
    wiring_path = project_dir / "cabinet_wiring.json"
    
    if not (inst_path.exists() and cable_path.exists() and wiring_path.exists()):
        logger.info("[Wiring Audit] Files not present for project %s. Skipping.", project_id)
        return []
        
    try:
        with open(inst_path, "r", encoding="utf-8") as f:
            inst_index = json.load(f)
        with open(cable_path, "r", encoding="utf-8") as f:
            cable_sched = json.load(f)
        with open(wiring_path, "r", encoding="utf-8") as f:
            wiring_matrix = json.load(f)
    except Exception as e:
        logger.error("[Wiring Audit] Error reading files: %s", e)
        return []
        
    # Build graph representation
    instruments = {i["tag"]: i for i in inst_index}
    cables = {c["tag"]: c for c in cable_sched}
    graph = defaultdict(set)
    
    def add_link(node_a, node_b, cable_tag, wire_label):
        graph[node_a].add((node_b, cable_tag, wire_label))
        graph[node_b].add((node_a, cable_tag, wire_label))
        
    for conn in wiring_matrix:
        cable = conn.get("cable_tag")
        wire = conn.get("wire_label")
        side_a = conn.get("side_a_node")
        side_b = conn.get("side_b_node")
        if side_a and side_b:
            add_link(side_a, side_b, cable, wire)
            
    def find_paths_dfs(start, end_prefix, visited, current_path):
        if start.startswith(end_prefix):
            return [current_path]
        if start not in graph:
            return []
        paths = []
        visited.add(start)
        for neighbor, cable, wire in graph[start]:
            if neighbor not in visited:
                new_path = current_path + [(start, neighbor, cable, wire)]
                res_paths = find_paths_dfs(neighbor, end_prefix, set(visited), new_path)
                paths.extend(res_paths)
        return paths

    anomalies = []
    
    # 1. Continuity & Loop Compliance
    for inst_tag, inst in instruments.items():
        if inst.get("status") != "ACTIVE":
            continue
            
        paths = find_paths_dfs(inst_tag, "DCS-", set(), [])
        
        if not paths:
            rule_id = "COH_WIRING_CONTINUITY"
            if not check_exception_suppression(inst_tag, rule_id, "Absent on DCS", "No path", exceptions):
                sig = f"{project_id}:{inst_tag}:{rule_id}"
                rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                anomalies.append({
                    "result_id": rid,
                    "tag": inst_tag,
                    "rule_id": rule_id,
                    "severity": "BLOQUANT",
                    "description": f"L'instrument actif '{inst_tag}' ne possède aucune connexion électrique valide atteignant le DCS.",
                    "doc_source_a": "cabinet_wiring.json",
                    "value_a": "No connection path",
                    "doc_source_b": "instrument_index.json",
                    "value_b": "ACTIVE"
                })
        else:
            positive_path = False
            negative_path = False
            for p in paths:
                first_segment = p[0]
                wire_label = first_segment[3].upper()
                if "+" in wire_label or "POS" in wire_label or "BK" in wire_label or "BLACK" in wire_label or "1" in wire_label:
                    positive_path = True
                if "-" in wire_label or "NEG" in wire_label or "WH" in wire_label or "WHITE" in wire_label or "2" in wire_label:
                    negative_path = True
            
            if not (positive_path and negative_path):
                rule_id = "COH_WIRING_LOOP_INCOMPLETE"
                if not check_exception_suppression(inst_tag, rule_id, "Incomplete", "Loop required", exceptions):
                    sig = f"{project_id}:{inst_tag}:{rule_id}"
                    rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                    anomalies.append({
                        "result_id": rid,
                        "tag": inst_tag,
                        "rule_id": rule_id,
                        "severity": "BLOQUANT",
                        "description": f"Boucle électrique incomplète pour l'instrument '{inst_tag}'. Pas de polarité positive ou négative détectée.",
                        "doc_source_a": "cabinet_wiring.json",
                        "value_a": f"Pos: {positive_path} | Neg: {negative_path}",
                        "doc_source_b": "instrument_index.json",
                        "value_b": "Loop Required"
                    })

    # 2. Color/Label Mismatches
    for node, edges in graph.items():
        if ":" not in node:
            continue
        parts = node.split(":")
        if len(parts) < 3:
            continue
        device, strip, pin = parts[0], parts[1], parts[2]
        
        if len(edges) == 2:
            edge_list = list(edges)
            wire_a = edge_list[0][2].upper()
            wire_b = edge_list[1][2].upper()
            
            def get_color_family(w):
                if "BK" in w or "BLACK" in w or "NOIR" in w or w == "+" or w == "1":
                    return "POSITIVE_BLACK"
                if "WH" in w or "WHITE" in w or "BLANC" in w or w == "-" or w == "2":
                    return "NEGATIVE_WHITE"
                return w
                
            fam_a = get_color_family(wire_a)
            fam_b = get_color_family(wire_b)
            
            if fam_a != fam_b:
                rule_id = "COH_WIRE_COLOR_MISMATCH"
                if not check_exception_suppression(device, rule_id, wire_a, wire_b, exceptions):
                    sig = f"{project_id}:{device}:{rule_id}:{strip}:{pin}"
                    rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                    anomalies.append({
                        "result_id": rid,
                        "tag": device,
                        "rule_id": rule_id,
                        "severity": "MAJEUR",
                        "description": f"Changement de couleur de conducteur détecté dans '{device}' sur le bornier '{strip}' borne '{pin}'.",
                        "doc_source_a": "cabinet_wiring.json",
                        "value_a": f"Fil A: {wire_a} (câble {edge_list[0][1]})",
                        "doc_source_b": "cabinet_wiring.json",
                        "value_b": f"Fil B: {wire_b} (câble {edge_list[1][1]})"
                    })

    # 3. Terminal Block Overflow (>2 wires)
    for node, edges in graph.items():
        if ":" not in node:
            continue
        parts = node.split(":")
        device = parts[0]
        if len(edges) > 2:
            rule_id = "COH_TERMINAL_OVERFLOW"
            if not check_exception_suppression(device, rule_id, f"Count: {len(edges)}", "Max 2", exceptions):
                sig = f"{project_id}:{node}:{rule_id}"
                rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                anomalies.append({
                    "result_id": rid,
                    "tag": device,
                    "rule_id": rule_id,
                    "severity": "MAJEUR",
                    "description": f"Surcharge de fils sur la borne physique '{node}' ({len(edges)} connectés, max 2).",
                    "doc_source_a": "cabinet_wiring.json",
                    "value_a": f"{len(edges)} fils",
                    "doc_source_b": "cabinet_wiring.json",
                    "value_b": "Max 2 fils"
                })

    # 4. Signal Type Compliance
    for inst_tag, inst in instruments.items():
        if inst.get("status") != "ACTIVE":
            continue
        paths = find_paths_dfs(inst_tag, "DCS-", set(), [])
        if not paths:
            continue
        inst_signal = inst.get("signal_type", "").upper()
        for p in paths:
            last_segment = p[-1]
            dcs_node = last_segment[1]
            
            card_type = ""
            if "CARD-AI" in dcs_node:
                card_type = "AI"
            elif "CARD-AO" in dcs_node:
                card_type = "AO"
            elif "CARD-DI" in dcs_node:
                card_type = "DI"
            elif "CARD-DO" in dcs_node:
                card_type = "DO"
                
            if card_type and inst_signal != card_type:
                rule_id = "COH_SIGNAL_TYPE_COMPLIANCE"
                if not check_exception_suppression(inst_tag, rule_id, inst_signal, card_type, exceptions):
                    sig = f"{project_id}:{inst_tag}:{rule_id}:{dcs_node}"
                    rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                    anomalies.append({
                        "result_id": rid,
                        "tag": inst_tag,
                        "rule_id": rule_id,
                        "severity": "BLOQUANT",
                        "description": f"Incompatibilité de signal : '{inst_tag}' ({inst_signal}) raccordé sur le canal DCS '{dcs_node}' ({card_type}).",
                        "doc_source_a": "instrument_index.json",
                        "value_a": inst_signal,
                        "doc_source_b": "cabinet_wiring.json",
                        "value_b": f"DCS {card_type}"
                    })

    logger.info("[Wiring Audit] Completed. Found %d anomalies.", len(anomalies))
    return anomalies


def check_pressure_propagation(project_id: str, tag_attrs: dict, connections: list, exceptions: list) -> list:
    """Propulse la pression de calcul depuis les sources (pompes, compresseurs) à travers le graphe procédé.
    
    Détecte si un équipement aval connecté possède une pression de calcul (design) inférieure 
    à la pression de service maximale propagée en amont sans organe de détente régulé (PCV/PV/PSV).
    """
    anomalies = []
    from collections import defaultdict, deque
    
    # 1. Construire le graphe orienté des connexions
    flow_graph = defaultdict(list)
    for conn in connections:
        src = conn["source"].upper().strip()
        tgt = conn["target"].upper().strip()
        doc = conn.get("document", "P&ID")
        flow_graph[src].append((tgt, doc))
        
    # 2. Récupérer les pressions de conception (design) de tous les équipements
    design_pressures = {}  # {tag: (val_bar, orig_val, orig_unit, doc)}
    for tag, attrs in tag_attrs.items():
        for a in attrs:
            if a["attribute_name"] == "design_pressure":
                try:
                    val_bar, _ = normalize_value(a["attribute_value"], a["unit"])
                    if val_bar is not None:
                        design_pressures[tag] = (val_bar, a["attribute_value"], a["unit"], a["document"])
                        break
                except Exception:
                    pass
                    
    # 3. Propager à partir de chaque source haute pression (Compresseur, Pompe)
    for source_tag, (p_source_bar, orig_val, orig_unit, src_doc) in design_pressures.items():
        if not source_tag.startswith(("C-", "P-", "K-")):
            continue
            
        # Parcours BFS
        queue = deque([(source_tag, src_doc)])
        visited = {source_tag}
        
        while queue:
            curr_tag, curr_doc = queue.popleft()
            
            # Récupérer les voisins connectés
            for next_tag, next_doc in flow_graph.get(curr_tag, []):
                if next_tag in visited:
                    continue
                visited.add(next_tag)
                
                # Seuil de coupure / Specification break : 
                # Si on croise un régulateur de pression, une soupape ou un organe de détente, on arrête la propagation
                if next_tag.startswith(("PCV", "PV", "PRV", "PSV", "RO", "LV", "LCV")):
                    continue
                    
                # Vérifier si l'équipement raccordé a une pression de design insuffisante
                if next_tag in design_pressures:
                    p_limit_bar, limit_val, limit_unit, limit_doc = design_pressures[next_tag]
                    
                    # On ne vérifie pas pour les autres compresseurs ou pompes qui ont leur propre surpression
                    if next_tag.startswith(("C-", "P-", "K-")):
                        continue
                        
                    if p_limit_bar < p_source_bar:
                        rule_id = "NORM_PRESSURE_PROPAGATION"
                        
                        # Vérifier si supprimé par dérogation
                        if check_exception_suppression(next_tag, rule_id, f"{p_source_bar} bar", f"{p_limit_bar} bar", exceptions):
                            continue
                            
                        sig = f"{project_id}:{source_tag}:{next_tag}:{rule_id}"
                        rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                        
                        description = (
                            f"Risque de surpression (Propagation de Pression) : L'équipement amont {source_tag} "
                            f"(Design: {orig_val} {orig_unit} dans {src_doc}) est connecté directement à {next_tag} "
                            f"(Design: {limit_val} {limit_unit} dans {limit_doc}) sans barrière de détente visible. "
                            f"La pression de calcul de {next_tag} est inférieure à la pression de service maximale propagée."
                        )
                        
                        anomalies.append({
                            "result_id": rid,
                            "tag": next_tag,
                            "rule_id": rule_id,
                            "severity": "BLOQUANT",
                            "description": description,
                            "doc_source_a": src_doc,
                            "value_a": f"{orig_val} {orig_unit}",
                            "doc_source_b": limit_doc,
                            "value_b": f"{limit_val} {limit_unit}"
                        })
                
                # Continuer la propagation
                queue.append((next_tag, next_doc))
                
    return anomalies


def run_verification_pipeline(project_id: str) -> list[dict]:
    """Execute the full multi-agent verification pipeline on a project."""
    anomalies = []
    
    # Load project specifications
    specs = load_project_specs(project_id)
    
    # Load attributes and learned exceptions
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM equipment_attributes WHERE project_id = ?", (project_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    exceptions = get_exceptions(project_id)
    
    # Group attributes by tag
    tag_attrs = defaultdict(list)
    for row in rows:
        tag_attrs[row["tag"].upper()].append(row)
        
    # === AGENT 1: COHÉRENCE INTER-DOCUMENTS ===
    for tag, attrs in tag_attrs.items():
        # Compare each attribute type across different files
        attr_by_name = defaultdict(list)
        for a in attrs:
            attr_by_name[a["attribute_name"].lower()].append(a)
            
        for name, occs in attr_by_name.items():
            if len(occs) < 2:
                continue
                
            # Compare all pairs
            for i in range(len(occs)):
                for j in range(i + 1, len(occs)):
                    a = occs[i]
                    b = occs[j]
                    
                    if a["document"] == b["document"]:
                        continue
                        
                    if is_value_different(a["attribute_value"], a["unit"], b["attribute_value"], b["unit"]):
                        rule_id = f"COH_{name.upper()}"
                        
                        # Check if suppressed
                        if check_exception_suppression(tag, rule_id, a["attribute_value"], b["attribute_value"], exceptions):
                            continue
                            
                        # Generate unique result id based on conflict signature
                        sig = f"{project_id}:{tag}:{rule_id}:{a['document']}:{b['document']}"
                        rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                        
                        description = (
                            f"Incohérence détectée pour l'attribut '{name}' de {tag} : "
                            f"Valeur '{a['attribute_value']} {a['unit']}' dans {a['document']} vs "
                            f"Valeur '{b['attribute_value']} {b['unit']}' dans {b['document']}."
                        )
                        
                        anomalies.append({
                            "result_id": rid,
                            "tag": tag,
                            "rule_id": rule_id,
                            "severity": "MAJEUR",
                            "description": description,
                            "doc_source_a": a["document"],
                            "value_a": f"{a['attribute_value']} {a['unit']}".strip(),
                            "doc_source_b": b["document"],
                            "value_b": f"{b['attribute_value']} {b['unit']}".strip()
                        })

    # === DÉTERMINISTE : REGLES METIERS OIL & GAS DYNAMIQUES & COHERENCE ===
    for tag, attrs in tag_attrs.items():
        if tag.startswith(("S-", "SPEC")):
            continue
            
        inlet_rating = None
        outlet_rating = None
        inlet_facing = None
        outlet_facing = None
        ds_doc = None
        sound_level = None
        is_duplex = False
        has_hardness = False
        
        # New properties variables
        design_pressure = None
        operating_pressure = None
        design_pressure_unit = "bar"
        operating_pressure_unit = "bar"
        design_pressure_doc = None
        operating_pressure_doc = None

        design_temp = None
        operating_temp = None
        design_temp_doc = None
        operating_temp_doc = None

        npsha = None
        npshr = None
        npsha_doc = None
        npshr_doc = None

        corrosion_allowance = None
        corrosion_allowance_doc = None
        material_val = ""
        material_doc = None

        fail_safes = []
        pressures_raw = []

        for a in attrs:
            name_lower = a["attribute_name"].lower()
            val = a["attribute_value"]
            unit = a["unit"]
            doc = a["document"]

            if name_lower == "inlet_flange_rating":
                inlet_rating = val
                ds_doc = doc
            elif name_lower == "outlet_flange_rating":
                outlet_rating = val
                ds_doc = doc
            elif name_lower == "inlet_flange_facing":
                inlet_facing = val
                ds_doc = doc
            elif name_lower == "outlet_flange_facing":
                outlet_facing = val
                ds_doc = doc
            elif name_lower == "sound_pressure_level":
                sound_level = val
                ds_doc = doc
            elif name_lower == "material" and any(x in val.lower() for x in ("duplex", "a995", "f51", "s31803")):
                is_duplex = True
                material_val = val
                material_doc = doc
                ds_doc = doc
            elif name_lower == "material":
                material_val = val
                material_doc = doc
            elif name_lower == "hardness":
                has_hardness = True
            elif name_lower == "pressure":
                pressures_raw.append(a)
            elif name_lower == "design_pressure":
                design_pressure = val
                design_pressure_unit = unit
                design_pressure_doc = doc
            elif name_lower == "operating_pressure":
                operating_pressure = val
                operating_pressure_unit = unit
                operating_pressure_doc = doc
            elif name_lower == "design_temperature":
                design_temp = val
                design_temp_doc = doc
            elif name_lower == "operating_temperature":
                operating_temp = val
                operating_temp_doc = doc
            elif name_lower == "npsha":
                npsha = val
                npsha_doc = doc
            elif name_lower == "npshr":
                npshr = val
                npshr_doc = doc
            elif name_lower == "corrosion_allowance":
                corrosion_allowance = val
                corrosion_allowance_doc = doc
            elif name_lower == "fail_safe":
                fail_safes.append((val, doc))
                
        # 1. Inlet vs Outlet rating equal (N-001)
        if inlet_rating and outlet_rating and inlet_rating != outlet_rating:
            rule_id = "NORM_FLANGE_RATING_EQUAL"
            if not check_exception_suppression(tag, rule_id, inlet_rating, outlet_rating, exceptions):
                sig = f"{project_id}:{tag}:{rule_id}:{ds_doc}"
                rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                anomalies.append({
                    "result_id": rid,
                    "tag": tag,
                    "rule_id": rule_id,
                    "severity": "BLOQUANT",
                    "description": f"Ratings de bride asymétriques sur {tag} : Entrée = {inlet_rating}# vs Sortie = {outlet_rating}#. Les spécifications générales du projet exigent des ratings d'entrée et de sortie identiques.",
                    "doc_source_a": ds_doc,
                    "value_a": f"Inlet: {inlet_rating}#",
                    "doc_source_b": ds_doc,
                    "value_b": f"Outlet: {outlet_rating}#"
                })
                
        # 2. Facing conformity from specs (N-002)
        required_facing = specs.get("required_flange_facing", "RTJ")
        if inlet_facing and inlet_facing != required_facing:
            rule_id = "NORM_FLANGE_FACING_RTJ"
            if not check_exception_suppression(tag, rule_id, inlet_facing, required_facing, exceptions):
                sig = f"{project_id}:{tag}:{rule_id}:inlet:{ds_doc}"
                rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                anomalies.append({
                    "result_id": rid,
                    "tag": tag,
                    "rule_id": rule_id,
                    "severity": "BLOQUANT",
                    "description": f"Finition de bride d'entrée non-conforme sur {tag} : Face '{inlet_facing}' détectée, alors que la spécification générale exige obligatoirement une finition {required_facing}.",
                    "doc_source_a": ds_doc,
                    "value_a": inlet_facing,
                    "doc_source_b": "Project Specifications",
                    "value_b": required_facing
                })
        if outlet_facing and outlet_facing != required_facing:
            rule_id = "NORM_FLANGE_FACING_RTJ"
            if not check_exception_suppression(tag, rule_id, outlet_facing, required_facing, exceptions):
                sig = f"{project_id}:{tag}:{rule_id}:outlet:{ds_doc}"
                rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                anomalies.append({
                    "result_id": rid,
                    "tag": tag,
                    "rule_id": rule_id,
                    "severity": "BLOQUANT",
                    "description": f"Finition de bride de sortie non-conforme sur {tag} : Face '{outlet_facing}' détectée, alors que la spécification générale exige obligatoirement une finition {required_facing}.",
                    "doc_source_a": ds_doc,
                    "value_a": outlet_facing,
                    "doc_source_b": "Project Specifications",
                    "value_b": required_facing
                })
 
        # 3. Sound pressure level verification from specs (N-004)
        if sound_level:
            try:
                val_sound = float(sound_level.replace(",", "."))
                noise_limit_cont = specs.get("noise_limit_continuous_dba", 85.0)
                noise_limit_upset = specs.get("noise_limit_upset_dba", 110.0)
                
                # Check against continuous limit
                if val_sound > noise_limit_cont:
                    rule_id = "NORM_SOUND_PRESSURE_LEVEL"
                    if not check_exception_suppression(tag, rule_id, sound_level, f"{noise_limit_cont} dBA", exceptions):
                        sig = f"{project_id}:{tag}:{rule_id}:{ds_doc}"
                        rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                        anomalies.append({
                            "result_id": rid,
                            "tag": tag,
                            "rule_id": rule_id,
                            "severity": "MAJEUR",
                            "description": f"Audit Acoustique : Niveau de pression acoustique garanti de {sound_level} dBA sur la fiche technique dépasse la limite admissible en opération continue ({noise_limit_cont} dBA).",
                            "doc_source_a": ds_doc,
                            "value_a": f"{sound_level} dBA",
                            "doc_source_b": "Project Specifications",
                            "value_b": f"{noise_limit_cont} dBA"
                        })
            except Exception:
                pass
 
        # 4. Duplex material hardness verification from specs (N-003)
        if is_duplex and not has_hardness:
            min_hardness = specs.get("duplex_min_hardness_hb", 220.0)
            rule_id = "NORM_DUPLEX_HARDNESS_MISSING"
            if not check_exception_suppression(tag, rule_id, "Missing", f"{min_hardness} HB", exceptions):
                sig = f"{project_id}:{tag}:{rule_id}:{ds_doc}"
                rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                anomalies.append({
                    "result_id": rid,
                    "tag": tag,
                    "rule_id": rule_id,
                    "severity": "MAJEUR",
                    "description": f"Dureté du matériau duplex manquante sur {tag} : Pièces en acier duplex spécifiées dans {ds_doc}, mais aucune contrainte de dureté minimale (min {min_hardness:.0f} HB exigé par la spécification) n'est fournie dans la fiche technique.",
                    "doc_source_a": ds_doc,
                    "value_a": "Spécification absente",
                    "doc_source_b": "Project Specifications",
                    "value_b": f"Dureté min. {min_hardness:.0f} HB"
                })

        # 5. Règle VES-01 : Marge de Pression de Design pour les Pressure Vessels (ASME VIII / Shell DEPs)
        is_vessel = tag.startswith(("V-", "D-", "C-")) and not tag.startswith(("VALVE", "HV-", "XV-", "PV-", "LV-"))
        if is_vessel and design_pressure and operating_pressure:
            try:
                dp_bar, _ = normalize_value(design_pressure, design_pressure_unit)
                op_bar, _ = normalize_value(operating_pressure, operating_pressure_unit)
                if dp_bar is not None and op_bar is not None:
                    required_margin_pct = specs.get("allowable_design_pressure_margin_pct", 10.0)
                    required_margin_bar = specs.get("allowable_design_pressure_margin_min_bar", 2.0)
                    
                    target_pct = op_bar * (1.0 + required_margin_pct / 100.0)
                    target_min = op_bar + required_margin_bar
                    min_allowed_dp = max(target_pct, target_min)
                    
                    if dp_bar < min_allowed_dp - 1e-3:
                        rule_id = "NORM_VESSEL_DESIGN_PRESSURE_MARGIN"
                        if not check_exception_suppression(tag, rule_id, f"{design_pressure} {design_pressure_unit}", f"{operating_pressure} {operating_pressure_unit}", exceptions):
                            sig = f"{project_id}:{tag}:{rule_id}:{design_pressure_doc}"
                            rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                            anomalies.append({
                                "result_id": rid,
                                "tag": tag,
                                "rule_id": rule_id,
                                "severity": "BLOQUANT",
                                "description": (
                                    f"Marge de pression de calcul insuffisante sur {tag} : "
                                    f"Pression de calcul = {design_pressure} {design_pressure_unit} ({dp_bar:.2f} bar) vs "
                                    f"Pression de service = {operating_pressure} {operating_pressure_unit} ({op_bar:.2f} bar) dans {design_pressure_doc}. "
                                    f"L'ASME VIII exige une marge minimale de {required_margin_pct}% ou {required_margin_bar} bar "
                                    f"(exigence minimale calculée = {min_allowed_dp:.2f} bar)."
                                ),
                                "doc_source_a": design_pressure_doc,
                                "value_a": f"Calcul: {design_pressure} {design_pressure_unit}",
                                "doc_source_b": operating_pressure_doc,
                                "value_b": f"Service: {operating_pressure} {operating_pressure_unit}"
                            })
            except Exception as e:
                logger.error("Error evaluating pressure margin for %s: %s", tag, e)

        # 6. Règle VES-02 : Marge de Température de Design
        if is_vessel and design_temp and operating_temp:
            try:
                dt_val = float(design_temp.replace(",", "."))
                ot_val = float(operating_temp.replace(",", "."))
                required_margin_t = specs.get("allowable_design_temperature_margin_degc", 10.0)
                
                if dt_val < ot_val + required_margin_t:
                    rule_id = "NORM_VESSEL_DESIGN_TEMPERATURE_MARGIN"
                    if not check_exception_suppression(tag, rule_id, design_temp, operating_temp, exceptions):
                        sig = f"{project_id}:{tag}:{rule_id}:{design_temp_doc}"
                        rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                        anomalies.append({
                            "result_id": rid,
                            "tag": tag,
                            "rule_id": rule_id,
                            "severity": "BLOQUANT",
                            "description": (
                                f"Marge de température de calcul insuffisante sur {tag} : "
                                f"Température de calcul = {design_temp} °C vs "
                                f"Température de service = {operating_temp} °C dans {design_temp_doc}. "
                                f"La spécification exige une marge minimale de {required_margin_t}°C."
                            ),
                            "doc_source_a": design_temp_doc,
                            "value_a": f"Calcul: {design_temp} °C",
                            "doc_source_b": operating_temp_doc,
                            "value_b": f"Service: {operating_temp} °C"
                        })
            except Exception as e:
                logger.error("Error evaluating temperature margin for %s: %s", tag, e)

        # 7. Règle PMP-01 : Marge NPSH des Pompes
        is_pump = tag.startswith(("P-", "PP-"))
        if is_pump and npsha and npshr:
            try:
                n_a = float(npsha.replace(",", "."))
                n_r = float(npshr.replace(",", "."))
                required_margin_npsh = specs.get("npsh_safety_margin_m", 1.0)
                
                if n_a < n_r + required_margin_npsh:
                    rule_id = "NORM_PUMP_NPSH_MARGIN"
                    if not check_exception_suppression(tag, rule_id, npsha, npshr, exceptions):
                        sig = f"{project_id}:{tag}:{rule_id}:{npsha_doc}"
                        rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                        anomalies.append({
                            "result_id": rid,
                            "tag": tag,
                            "rule_id": rule_id,
                            "severity": "BLOQUANT",
                            "description": (
                                f"Marge de sécurité NPSH insuffisante pour la pompe {tag} dans {npsha_doc} : "
                                f"NPSH disponible (NPSHa) = {npsha} m vs NPSH requis (NPSHr) = {npshr} m. "
                                f"API 610 exige une marge minimale de {required_margin_npsh} m."
                            ),
                            "doc_source_a": npsha_doc,
                            "value_a": f"NPSHa: {npsha} m",
                            "doc_source_b": npshr_doc,
                            "value_b": f"NPSHr: {npshr} m"
                        })
            except Exception as e:
                logger.error("Error evaluating NPSH margin for %s: %s", tag, e)

        # 8. Règle VES-03 : Surépaisseur de corrosion minimale pour service acide H2S (NACE MR0175)
        is_carbon_steel = any(x in material_val.lower() for x in ("carbone", "carbon steel", "a105", "a216", "wcb", "a350"))
        is_sour = specs.get("sour_service", True)
        if is_sour and is_carbon_steel and is_vessel:
            ca_val = 0.0
            if corrosion_allowance:
                try:
                    ca_val = float(corrosion_allowance.replace(",", "."))
                except Exception:
                    pass
            if ca_val < 3.0:
                rule_id = "NORM_SOUR_SERVICE_CORROSION_ALLOWANCE"
                if not check_exception_suppression(tag, rule_id, str(ca_val), "3.0 mm", exceptions):
                    sig = f"{project_id}:{tag}:{rule_id}:{material_doc if material_doc else ds_doc}"
                    rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                    anomalies.append({
                        "result_id": rid,
                        "tag": tag,
                        "rule_id": rule_id,
                        "severity": "MAJEUR",
                        "description": (
                            f"Surépaisseur de corrosion insuffisante sur l'appareil sous pression en acier carbone {tag} "
                            f"opérant en service acide (Sour Service H2S) dans {material_doc if material_doc else ds_doc} : "
                            f"CA = {corrosion_allowance or '0'} mm détectée, alors qu'une surépaisseur minimale de 3.0 mm "
                            f"est requise pour lutter contre la corrosion humide sulfurée (H2S)."
                        ),
                        "doc_source_a": material_doc if material_doc else ds_doc,
                        "value_a": f"CA: {corrosion_allowance or 'Non spécifiée'} mm",
                        "doc_source_b": "NACE Specification",
                        "value_b": "CA min: 3.0 mm"
                    })

        # 9. Règle de cohérence fail-safe inter-documents (VAL-05)
        if len(fail_safes) >= 2:
            first_fs, first_doc = fail_safes[0]
            for fs, doc in fail_safes[1:]:
                if fs != first_fs:
                    rule_id = "COH_FAIL_SAFE"
                    if not check_exception_suppression(tag, rule_id, first_fs, fs, exceptions):
                        sig = f"{project_id}:{tag}:{rule_id}:{first_doc}:{doc}"
                        rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                        anomalies.append({
                            "result_id": rid,
                            "tag": tag,
                            "rule_id": rule_id,
                            "severity": "BLOQUANT",
                            "description": (
                                f"Contradiction critique de position de sécurité pour {tag} : "
                                f"Valeur '{first_fs}' spécifiée dans {first_doc} vs "
                                f"Valeur '{fs}' dans {doc}. Les positions de sécurité doivent être alignées."
                            ),
                            "doc_source_a": first_doc,
                            "value_a": first_fs,
                            "doc_source_b": doc,
                            "value_b": fs
                        })

    # === AGENT 2: CONFORMITÉ AUX NORMES (H2S GENERAL & DESIGN PRESSURE LIMITS) ===
    for tag, attrs in tag_attrs.items():
        is_sour_service = specs.get("sour_service", True)
        materials = []
        pressures = []
        
        for a in attrs:
            val_lower = a["attribute_value"].lower()
            name_lower = a["attribute_name"].lower()
            if "h2s" in val_lower or "sour" in val_lower or "acide" in val_lower:
                is_sour_service = True
            if name_lower == "material":
                materials.append(a)
            if name_lower == "pressure":
                pressures.append(a)
                
        if is_sour_service:
            allowed_materials = ["316l", "316", "duplex", "super duplex", "inconel", "alloy 625", "alloy 825", "inox", "stainless steel"]
            for m in materials:
                mat_val = m["attribute_value"].lower()
                if any(x in mat_val for x in ["carbone", "carbon steel", "a216", "a105", "a350", "a516"]) and not any(y in mat_val for y in allowed_materials):
                    rule_id = "NORM_H2S_MATERIAL"
                    if check_exception_suppression(tag, rule_id, m["attribute_value"], "H2S Service", exceptions):
                        continue
                        
                    sig = f"{project_id}:{tag}:{rule_id}:{m['document']}"
                    rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                    
                    description = (
                        f"Non-conformité critique H2S (ISO 15156) sur {tag} : Le matériau "
                        f"déclaré '{m['attribute_value']}' dans {m['document']} n'est pas certifié "
                        f"pour le service acide/H2S (acier carbone sans traitement)."
                    )
                    
                    anomalies.append({
                        "result_id": rid,
                        "tag": tag,
                        "rule_id": rule_id,
                        "severity": "BLOQUANT",
                        "description": description,
                        "doc_source_a": m["document"],
                        "value_a": m["attribute_value"],
                        "doc_source_b": "ISO 15156 Spec",
                        "value_b": "H2S material certification required"
                    })
 
        # Check ASME VIII Pressure limits
        for p in pressures:
            try:
                p_val, _ = normalize_value(p["attribute_value"], p["unit"])
                if "ldbp" in project_id and p_val > 30.0:
                    rule_id = "NORM_ASME_PRESSURE"
                    if check_exception_suppression(tag, rule_id, p["attribute_value"], "30 bar limit", exceptions):
                        continue
                        
                    sig = f"{project_id}:{tag}:{rule_id}:{p['document']}"
                    rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                    
                    anomalies.append({
                        "result_id": rid,
                        "tag": tag,
                        "rule_id": rule_id,
                        "severity": "MAJEUR",
                        "description": f"Pression élevée ({p_val:.1f} bar) détectée pour {tag} dans {p['document']}, dépassant les limites du réseau LDBP (max 30 bar).",
                        "doc_source_a": p["document"],
                        "value_a": f"{p['attribute_value']} {p['unit']}",
                        "doc_source_b": "ASME Class limit",
                        "value_b": "< 30 bar"
                    })
            except Exception:
                pass

        # Check mandatory attributes CFIHOS
        class_name = None
        t_up = tag.upper().strip()
        if t_up.startswith(("P-", "PP-")):
            class_name = "Pump"
        elif t_up.startswith(("V-", "D-", "C-")) and not t_up.startswith(("VALVE", "HV", "XV", "PV", "LV", "TV")):
            class_name = "Vessel"
        elif t_up.startswith(("HV-", "XV-", "PV-", "LV-", "TV-")):
            class_name = "Valve"
            
        if class_name:
            existing_attrs = {a["attribute_name"].lower() for a in attrs}
            mandatory_map = {}
            if class_name == "Pump":
                mandatory_map = {
                    "npsha": ("NPSH disponible", "MAJEUR"),
                    "npshr": ("NPSH requis", "MAJEUR"),
                    "material": ("Matériau", "MINEUR")
                }
            elif class_name == "Vessel":
                mandatory_map = {
                    "design_pressure": ("Pression de calcul", "MAJEUR"),
                    "operating_pressure": ("Pression de service", "MAJEUR"),
                    "design_temperature": ("Température de calcul", "MAJEUR"),
                    "operating_temperature": ("Température de service", "MAJEUR"),
                    "corrosion_allowance": ("Surépaisseur de corrosion", "MINEUR"),
                    "material": ("Matériau", "MINEUR")
                }
            elif class_name == "Valve":
                mandatory_map = {
                    "fail_safe": ("Position de sécurité fail-safe", "MAJEUR"),
                    "material": ("Matériau", "MINEUR")
                }
                if "flange_rating" not in existing_attrs and "inlet_flange_rating" not in existing_attrs:
                    existing_attrs.discard("flange_rating")
                else:
                    existing_attrs.add("flange_rating")
                    
                if "flange_facing" not in existing_attrs and "inlet_flange_facing" not in existing_attrs:
                    existing_attrs.discard("flange_facing")
                else:
                    existing_attrs.add("flange_facing")
                    
                mandatory_map["flange_rating"] = ("Rating des brides", "MINEUR")
                mandatory_map["flange_facing"] = ("Finition de face des brides", "MINEUR")

            doc_source = attrs[0]["document"] if attrs else "Spécifications du projet"
            for attr_key, (attr_label, severity) in mandatory_map.items():
                if attr_key not in existing_attrs:
                    rule_id = "ONT_MANDATORY_ATTRIBUTES_MISSING"
                    if not check_exception_suppression(tag, rule_id, attr_key, "Missing", exceptions):
                        sig = f"{project_id}:{tag}:{rule_id}:{attr_key}"
                        rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                        anomalies.append({
                            "result_id": rid,
                            "tag": tag,
                            "rule_id": rule_id,
                            "severity": severity,
                            "description": f"Audit CFIHOS : L'équipement '{tag}' (classe {class_name}) ne possède pas l'attribut obligatoire '{attr_label}' ({attr_key}) requis pour sa spécification technique dans {doc_source}.",
                            "doc_source_a": doc_source,
                            "value_a": "Spécification absente",
                            "doc_source_b": "CFIHOS mandatory attributes requirement",
                            "value_b": "Présence requise"
                        })
 
    # Load connected_to relationships from project-specific knowledge_graph.db for topological checks
    connections = []
    try:
        from knowledge_graph import _init_db
        db_path = _init_db(project_id)
        import sqlite3
        conn_kg = sqlite3.connect(str(db_path))
        conn_kg.row_factory = sqlite3.Row
        cursor_kg = conn_kg.cursor()
        cursor_kg.execute("SELECT source, target, document FROM relationships WHERE relation = 'connected_to'")
        connections = [dict(r) for r in cursor_kg.fetchall()]
        conn_kg.close()
    except Exception as e:
        logger.error("Failed to load connections from KG at %s: %s", db_path, e)

    # === TOPOLOGY: PROPAGATION DE PRESSION (NORM_PRESSURE_PROPAGATION) ===
    if connections:
        try:
            prop_anomalies = check_pressure_propagation(project_id, tag_attrs, connections, exceptions)
            anomalies.extend(prop_anomalies)
            logger.info("[Topology] Pressure propagation check completed. Found %d anomalies.", len(prop_anomalies))
        except Exception as e:
            logger.error("Error during pressure propagation check: %s", e)

    # === SÉCURITÉ : TARAGE PSV VS PRESSION DE CALCUL ÉQUIPEMENT PROTÉGÉ (NORM_PSV_SET_PRESSURE) ===
    for tag, attrs in tag_attrs.items():
        if not tag.startswith("PSV"):
            continue
            
        # Get PSV set pressure
        psv_pressure_vals = []
        psv_doc = None
        for a in attrs:
            if a["attribute_name"] == "pressure":
                try:
                    val_bar, _ = normalize_value(a["attribute_value"], a["unit"])
                    if val_bar is not None:
                        psv_pressure_vals.append((val_bar, a["attribute_value"], a["unit"]))
                        psv_doc = a["document"]
                except Exception:
                    pass
                    
        if not psv_pressure_vals or not psv_doc:
            continue
            
        psv_bar, psv_orig_val, psv_orig_unit = max(psv_pressure_vals, key=lambda x: x[0])
        
        # Find all connected equipment (either source or target of psv_tag in connections)
        connected_tags = set()
        for conn_row in connections:
            s_tag = conn_row["source"].upper()
            t_tag = conn_row["target"].upper()
            if s_tag == tag:
                connected_tags.add(t_tag)
            elif t_tag == tag:
                connected_tags.add(s_tag)
                
        # For each connected equipment, check its design pressure
        for conn_tag in connected_tags:
            # Skip other PSVs or instruments
            if conn_tag.startswith(("PSV", "PT", "TT", "FT", "LT", "ZT")):
                continue
                
            conn_attrs = tag_attrs.get(conn_tag, [])
            conn_pressure_vals = []
            conn_doc = None
            for a in conn_attrs:
                if a["attribute_name"] == "pressure":
                    try:
                        val_bar, _ = normalize_value(a["attribute_value"], a["unit"])
                        if val_bar is not None:
                            conn_pressure_vals.append((val_bar, a["attribute_value"], a["unit"]))
                            conn_doc = a["document"]
                    except Exception:
                        pass
                        
            if not conn_pressure_vals or not conn_doc:
                continue
                
            conn_bar, conn_orig_val, conn_orig_unit = max(conn_pressure_vals, key=lambda x: x[0])
            
            # Tarage de la PSV ne doit pas excéder la pression de calcul
            if psv_bar > conn_bar * 1.01:
                rule_id = "NORM_PSV_SET_PRESSURE"
                if check_exception_suppression(tag, rule_id, f"{psv_orig_val} {psv_orig_unit}", f"{conn_orig_val} {conn_orig_unit}", exceptions):
                    continue
                    
                sig = f"{project_id}:{tag}:{conn_tag}:{rule_id}:{psv_doc}"
                rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                
                description = (
                    f"Surpression de sécurité non conforme sur {tag} : La vanne de sécurité a une pression de tarage de "
                    f"{psv_orig_val} {psv_orig_unit} ({psv_bar:.1f} bar) qui dépasse la pression de calcul de l'équipement "
                    f"protégé {conn_tag} ({conn_orig_val} {conn_orig_unit} / {conn_bar:.1f} bar) dans {conn_doc}. "
                    f"Selon la norme ASME Section VIII, la pression de tarage de la PSV ne doit jamais dépasser la MAWP/pression de calcul de l'équipement protégé."
                )
                
                anomalies.append({
                    "result_id": rid,
                    "tag": tag,
                    "rule_id": rule_id,
                    "severity": "BLOQUANT",
                    "description": description,
                    "doc_source_a": psv_doc,
                    "value_a": f"Tarage PSV: {psv_orig_val} {psv_orig_unit}",
                    "doc_source_b": conn_doc,
                    "value_b": f"Pression calcul {conn_tag}: {conn_orig_val} {conn_orig_unit}"
                })

    # === CORRESPONDANCE TOPOLOGIQUE PFD ↔ P&ID (PID_TOPOLOGY_MISMATCH) ===
    # Group connections by document type
    pfd_graph = defaultdict(set)
    pid_graph = defaultdict(set)
    
    for conn_row in connections:
        src = conn_row["source"].upper().strip()
        tgt = conn_row["target"].upper().strip()
        doc = conn_row["document"].lower()
        
        # Identify main process equipment only (vessels, pumps, compressors)
        # Skip instrumentation to keep topological comparison focused
        if src.startswith(("PT", "TT", "FT", "LT", "ZT")) or tgt.startswith(("PT", "TT", "FT", "LT", "ZT")):
            continue
            
        is_pfd = "pfd" in doc or "implantation" in doc
        if is_pfd:
            pfd_graph[src].add(tgt)
        else:
            pid_graph[src].add(tgt)
            
    # DFS helper to find a path in a graph
    def has_path(graph, start, end, visited=None):
        if visited is None:
            visited = set()
        if start == end:
            return True
        visited.add(start)
        for neighbor in graph.get(start, []):
            if neighbor not in visited:
                if has_path(graph, neighbor, end, visited):
                    return True
        return False
        
    # Check each connection in the PFD graph
    for src, tgts in pfd_graph.items():
        for tgt in tgts:
            # Check path in P&ID graph
            path_exists = has_path(pid_graph, src, tgt)
            if not path_exists:
                # Check for reversed path (flow inversion)
                reversed_exists = has_path(pid_graph, tgt, src)
                rule_id = "PID_TOPOLOGY_MISMATCH"
                
                sig = f"{project_id}:{src}:{tgt}:{rule_id}"
                rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                
                if reversed_exists:
                    if check_exception_suppression(src, rule_id, f"connect_to_{tgt}", "inverted", exceptions):
                        continue
                    description = (
                        f"Inversion de flux critique détectée entre {src} et {tgt} : "
                        f"Le plan PFD montre un écoulement de {src} vers {tgt}, "
                        f"alors que le plan P&ID indique un écoulement inverse de {tgt} vers {src}."
                    )
                    anomalies.append({
                        "result_id": rid,
                        "tag": src,
                        "rule_id": rule_id,
                        "severity": "BLOQUANT",
                        "description": description,
                        "doc_source_a": "PFD Drawing",
                        "value_a": f"Ecoulement {src} -> {tgt}",
                        "doc_source_b": "P&ID Drawing",
                        "value_b": f"Ecoulement {tgt} -> {src}"
                    })
                else:
                    # Equipment disconnected
                    if check_exception_suppression(src, rule_id, f"connect_to_{tgt}", "disconnected", exceptions):
                        continue
                    description = (
                        f"Écart de connexion topologique entre {src} et {tgt} : "
                        f"Le PFD indique une connexion directe de {src} vers {tgt}, "
                        f"mais aucune connexion ni écoulement n'a été trouvé entre eux sur le plan P&ID."
                    )
                    anomalies.append({
                        "result_id": rid,
                        "tag": src,
                        "rule_id": rule_id,
                        "severity": "MAJEUR",
                        "description": description,
                        "doc_source_a": "PFD Drawing",
                        "value_a": f"Connecté à {tgt}",
                        "doc_source_b": "P&ID Drawing",
                        "value_b": "Non connecté / Isolé"
                    })

    # === ONTOLOGIE DE FLUX PROCÉDÉ (ONT_EQUIPMENT_ISOLATED, ONT_EQUIPMENT_NO_INLET, ONT_EQUIPMENT_NO_OUTLET) ===
    if connections:
        for tag in tag_attrs.keys():
            t_up = tag.upper().strip()
            if t_up.startswith(("PT", "TT", "FT", "LT", "ZT", "SPEC", "S-", "DAO", "LDBP", "REV", "DWG", "ANNEXE")):
                continue
                
            class_name = None
            if t_up.startswith(("P-", "PP-")):
                class_name = "Pump"
            elif t_up.startswith(("V-", "D-", "C-")) and not t_up.startswith(("VALVE", "HV", "XV", "PV", "LV", "TV")):
                class_name = "Vessel"
            elif t_up.startswith(("HV-", "XV-", "PV-", "LV-", "TV-")):
                class_name = "Valve"
                
            if class_name or any(t_up.startswith(pref) for pref in ("HV-", "V-", "P-", "PP-", "C-", "K-", "E-", "FA-", "XV-", "PV-", "LV-", "TV-")):
                incoming_count = sum(1 for conn_row in connections if conn_row["target"].upper().strip() == t_up)
                outgoing_count = sum(1 for conn_row in connections if conn_row["source"].upper().strip() == t_up)
                
                doc_source = tag_attrs[tag][0]["document"] if tag_attrs[tag] else "Plans de procédé"
                
                if incoming_count == 0 and outgoing_count == 0:
                    rule_id = "ONT_EQUIPMENT_ISOLATED"
                    if not check_exception_suppression(tag, rule_id, "isolated", "Topological Graph", exceptions):
                        sig = f"{project_id}:{tag}:{rule_id}"
                        rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                        anomalies.append({
                            "result_id": rid,
                            "tag": tag,
                            "rule_id": rule_id,
                            "severity": "MAJEUR",
                            "description": f"Audit Ontologique : L'équipement '{tag}' ({class_name or 'Equipement Process'}) est isolé topologiquement sur les plans de procédé. Aucune connexion d'entrée ou de sortie n'a été détectée dans le graphe.",
                            "doc_source_a": doc_source,
                            "value_a": "Aucune connexion amont/aval",
                            "doc_source_b": "Topological Flow Specifications",
                            "value_b": "Connexion requise"
                        })
                elif incoming_count == 0 and class_name in ("Pump", "Valve"):
                    rule_id = "ONT_EQUIPMENT_NO_INLET"
                    if not check_exception_suppression(tag, rule_id, "no_inlet", "Topological Graph", exceptions):
                        sig = f"{project_id}:{tag}:{rule_id}"
                        rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                        anomalies.append({
                            "result_id": rid,
                            "tag": tag,
                            "rule_id": rule_id,
                            "severity": "MAJEUR",
                            "description": f"Audit Ontologique : L'équipement actif '{tag}' (classe {class_name}) possède des connexions de sortie mais aucune conduite d'entrée/aspiration dans le graphe des flux.",
                            "doc_source_a": doc_source,
                            "value_a": f"Sorties: {outgoing_count} | Entrées: 0",
                            "doc_source_b": "Topological Flow Specifications",
                            "value_b": "Conduite d'aspiration/entrée requise"
                        })
                elif outgoing_count == 0 and class_name in ("Pump", "Valve"):
                    rule_id = "ONT_EQUIPMENT_NO_OUTLET"
                    if not check_exception_suppression(tag, rule_id, "no_outlet", "Topological Graph", exceptions):
                        sig = f"{project_id}:{tag}:{rule_id}"
                        rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                        anomalies.append({
                            "result_id": rid,
                            "tag": tag,
                            "rule_id": rule_id,
                            "severity": "MAJEUR",
                            "description": f"Audit Ontologique : L'équipement actif '{tag}' (classe {class_name}) possède des connexions d'entrée mais aucune conduite de sortie/refoulement dans le graphe des flux (cul-de-sac).",
                            "doc_source_a": doc_source,
                            "value_a": f"Entrées: {incoming_count} | Sorties: 0",
                            "doc_source_b": "Topological Flow Specifications",
                            "value_b": "Conduite de refoulement/sortie requise"
                        })
 
    # === AGENT 3: TAGS & P&ID DRAWING MATCH ===
    # Get all tags declared present on PFD drawing
    pfd_tags = set()
    pfd_sources = {}
    other_tags = set()
    other_sources = {}
    
    for tag, attrs in tag_attrs.items():
        is_on_pfd = False
        is_on_doc = False
        for a in attrs:
            if a["attribute_name"] == "present_on_p&id":
                is_on_pfd = True
                pfd_sources[tag] = a["document"]
            else:
                is_on_doc = True
                other_sources[tag] = a["document"]
                
        if is_on_pfd:
            pfd_tags.add(tag)
        if is_on_doc:
            other_tags.add(tag)
            
    # Anomalie: Tag dans la spécification technique/Data Sheet mais absent sur le plan P&ID/PFD
    missing_on_drawing = other_tags - pfd_tags
    for tag in missing_on_drawing:
        # Avoid minor instrument tags like PT/TT that might not be on PFD
        if tag.startswith(("PT", "TT", "FT", "LT")):
            continue
            
        rule_id = "PID_MISSING_TAG"
        if check_exception_suppression(tag, rule_id, "Absent on PFD", "Present in DS", exceptions):
            continue
            
        sig = f"{project_id}:{tag}:{rule_id}"
        rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
        
        anomalies.append({
            "result_id": rid,
            "tag": tag,
            "rule_id": rule_id,
            "severity": "MAJEUR",
            "description": f"Tag équipement '{tag}' présent en spécification ({other_sources[tag]}) mais absent sur le plan PFD/P&ID.",
            "doc_source_a": other_sources[tag],
            "value_a": "Present in specs",
            "doc_source_b": "PFD Drawing",
            "value_b": "Absent"
        })
        
    # === ANALYSE SÉMANTIQUE PAR LLM (QWEN) ===
    llm_anomalies = run_semantic_llm_verification(project_id, exceptions)
    anomalies.extend(llm_anomalies)

    # === AUDIT DU CÂBLAGE ET RACCORDEMENT ÉLECTRIQUE (INSTRUMENTATION) ===
    wiring_anomalies = run_wiring_verification(project_id, exceptions)
    anomalies.extend(wiring_anomalies)

    # === AUDIT DES DOCUMENTS PAR RAPPORT AUX MANUELS O&G (RAG SENTINEL) ===
    try:
        handbook_anomalies = run_handbook_rag_verification(project_id, exceptions)
        anomalies.extend(handbook_anomalies)
    except Exception as e:
        logger.error("Failed running handbook RAG verification: %s", e)

    # === AUDIT DES RETARDS DE DOCUMENTS PAR RAPPORT AU PLANNING XER ===
    try:
        planning_delays = run_planning_delays_verification(project_id, exceptions)
        anomalies.extend(planning_delays)
    except Exception as e:
        logger.error("Failed running planning delays verification: %s", e)

    # Save results to SQLite
    save_verification_results(project_id, anomalies)
    return anomalies


def run_handbook_rag_verification(project_id: str, exceptions: list[dict]) -> list[dict]:
    """Run SentinelAuditor on each project document to find violations of general O&G standards/manuals."""
    import hashlib
    from sentinel_auditor import get_auditor
    
    project_dir = get_project_dir_path(project_id)
    docs_text = load_project_documents_text(project_dir)
    if not docs_text:
        logger.info("No documents found for handbook RAG verification in project %s", project_id)
        return []
        
    logger.info("Running Sentinel-OG Handbook RAG cross-check on %d documents for project %s...", len(docs_text), project_id)
    auditor = get_auditor()
    anomalies = []
    
    for filename, text in docs_text.items():
        try:
            logger.info("Auditing document: %s against handbook database...", filename)
            report = auditor.audit_text(text, source=filename)
            for f in report.findings:
                # Severity mapping
                sev = "MINEUR"
                if f.severity == "ERREUR":
                    sev = "BLOQUANT"
                elif f.severity == "WARNING":
                    sev = "MAJEUR"
                    
                # Extrait le tag ou cherche un pattern dans la claim
                tag = "GLOBAL"
                tag_match = re.search(r"\b(\d{2,4}[-_]?[A-Z]{2,4}[-_]?\d{2,4}[A-Z]?)\b", f.claim_raw, re.IGNORECASE)
                if tag_match:
                    tag = tag_match.group(1).upper()
                else:
                    tag_match = re.search(r"\b(\d{2,4}[-_]?[A-Z]{2,4}[-_]?\d{2,4}[A-Z]?)\b", f.description, re.IGNORECASE)
                    if tag_match:
                        tag = tag_match.group(1).upper()
                
                rule_id = f"NORM_{f.category.upper()}"
                
                # Check suppression
                if check_exception_suppression(tag, rule_id, f.claim_raw, f.reference, exceptions):
                    continue
                    
                sig = f"{project_id}:{tag}:{rule_id}:{filename}:{f.description}"
                rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                
                desc = f.description
                if f.suggestion:
                    desc += f" [Correction recommandee : {f.suggestion}]"
                
                anomalies.append({
                    "result_id": rid,
                    "tag": tag,
                    "rule_id": rule_id,
                    "severity": sev,
                    "description": desc,
                    "doc_source_a": filename,
                    "value_a": f.claim_raw or "Donnee du document",
                    "doc_source_b": f.reference or "Normes & Manuels O&G",
                    "value_b": "Exigence standard applicable"
                })
        except Exception as e:
            logger.error("Failed to audit document %s against handbook: %s", filename, e)
            
    logger.info("Handbook RAG verification found %d anomalies for project %s", len(anomalies), project_id)
    return anomalies


def run_planning_delays_verification(project_id: str, exceptions: list[dict]) -> list[dict]:
    """Check if document tasks in the project planning are late (missing from project files)."""
    import os
    import hashlib
    import re
    from datetime import datetime
    import planning_analyzer

    project_dir = get_project_dir_path(project_id)
    if not project_dir.exists():
        return []

    # Find XER files in project directory
    xer_files = [f for f in os.listdir(project_dir) if f.lower().endswith('.xer')]
    if not xer_files:
        logger.info("[Planning Audit] No XER file found in project directory %s", project_dir)
        return []

    # Get list of files in project directory (excluding XER, system files)
    project_files = [
        f for f in os.listdir(project_dir)
        if os.path.isfile(project_dir / f) and not f.lower().endswith(('.xer', '.ini', '.db', '.tmp'))
    ]

    anomalies = []
    now = datetime.now()

    # Keywords to detect document/deliverable tasks
    doc_keywords = (
        "ds", "datasheet", "data sheet", "spec", "specification", "spécification",
        "calcul", "note", "drawing", "plan", "p&id", "pfd", "schema", "schéma",
        "câblage", "report", "rapport", "isometric", "isométrique", "deliverable", "livrable"
    )

    for xer_name in xer_files:
        xer_path = project_dir / xer_name
        try:
            with open(xer_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            data = planning_analyzer.parse_xer_file(content)
            tasks = data.get("tasks", [])
            
            for t in tasks:
                task_name = t.get("task_name", "").lower()
                task_code = t.get("task_code", "").lower()
                
                # Check if it's a document/deliverable task
                is_doc_task = any(kw in task_name or kw in task_code for kw in doc_keywords)
                if not is_doc_task:
                    continue
                
                # We only check uncompleted/active tasks that have a target date
                status = t.get("status_code", "")
                if status == "TK_Complete":
                    continue
                
                end_str = t.get("target_end_date")
                if not end_str:
                    continue
                
                try:
                    end_dt = datetime.strptime(end_str, "%Y-%m-%d")
                except:
                    continue
                
                # If target end date is in the past, it should be delivered (file must exist)
                if end_dt < now:
                    # Look for tag in task_code or task_name
                    tag = "GLOBAL"
                    tag_match = re.search(r"\b(\d{2,4}[-_]?[A-Z]{2,4}[-_]?\d{2,4}[A-Z]?)\b", t.get("task_code", "") + " " + t.get("task_name", ""), re.IGNORECASE)
                    if tag_match:
                        tag = tag_match.group(1).upper()
                    
                    # Try to find a matching file
                    file_found = False
                    clean_task_code = re.sub(r'[^a-zA-Z0-9]', '', task_code)
                    
                    for filename in project_files:
                        clean_filename = re.sub(r'[^a-zA-Z0-9]', '', filename.lower())
                        # Match by tag
                        if tag != "GLOBAL" and tag.lower() in filename.lower():
                            file_found = True
                            break
                        # Match by task code
                        if clean_task_code and clean_task_code in clean_filename:
                            file_found = True
                            break
                        # Match by similar terms
                        if tag != "GLOBAL" and tag.lower() in clean_filename:
                            file_found = True
                            break
                    
                    if not file_found:
                        # Document is late!
                        rule_id = "PLAN_DOC_DELAYED"
                        
                        # Set severity based on critical path
                        is_critical = t.get("is_critical", False)
                        severity = "BLOQUANT" if is_critical else "MAJEUR"
                        
                        delay_days = (now - end_dt).days
                        desc = (
                            f"Retard de livrable : Le document '{t.get('task_name')}' (Code: {t.get('task_code')}) "
                            f"devait etre livre le {t.get('end_formatted') or end_str} selon le planning '{xer_name}'. "
                            f"Aucun fichier correspondant n'a ete trouve dans le dossier du projet. Retard de {delay_days} jours."
                        )
                        
                        if is_critical:
                            desc += " [ACTIVITE SUR LE CHEMIN CRITIQUE]"
                        
                        if check_exception_suppression(tag, rule_id, t.get("task_code"), str(delay_days), exceptions):
                            continue
                            
                        sig = f"{project_id}:{t.get('task_code')}:{rule_id}:{xer_name}"
                        rid = hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
                        
                        anomalies.append({
                            "result_id": rid,
                            "tag": tag,
                            "rule_id": rule_id,
                            "severity": severity,
                            "description": desc,
                            "doc_source_a": xer_name,
                            "value_a": f"Date cible: {t.get('end_formatted') or end_str}",
                            "doc_source_b": "Dossier Projet",
                            "value_b": "Fichier absent/non-livre"
                        })
        except Exception as e:
            logger.error("[Planning Audit] Error analyzing XER file %s for delays: %s", xer_name, e)
            
    return anomalies
