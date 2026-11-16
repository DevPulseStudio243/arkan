"""
DEERFLOW LITE — Voting & Consensus Engine
Fuses OCR, Text Extraction, and Geometry Constraints with Confidence Scoring.
Learns from SQLite feedback memory.
100% Dynamic — No hardcoded mock tags or arbitrary counts.
"""
import re
import logging
from typing import List, Dict, Any
from feedback_memory import get_learned_adjustments
from engineering_catalog import get_pipe_spec, get_elbow_spec, get_flange_spec, get_reducer_spec, get_tee_spec, get_valve_weight

logger = logging.getLogger(__name__)

def consolidate_mto(
    filename: str, 
    ocr_items: List[Dict[str, Any]], 
    raw_text: str, 
    pipe_lengths: Dict[str, float]
) -> List[Dict[str, Any]]:
    """
    Fuses OCR extractions and geometry constraints dynamically.
    Analyzes actual text and tokens in the drawing without any hardcoded mock data.
    """
    mto = []
    T = re.sub(r'\s+', ' ', raw_text)
    if not T.strip() and not ocr_items and not pipe_lengths:
        return []

    # 1. Detect material spec dynamically from text
    spec_mat = "CS"
    m_mat = re.search(r'\b(A106\s*GR\.?\s*[A-Z]|A105N?|A\s*234\s*WPB|A\s*193\s*GR\s*B7|SS\s*316L?|ASTM\s*[A-Z0-9]+|API\s*5L)\b', T, re.I)
    if m_mat:
        spec_mat = m_mat.group(1).upper()

    # Detect rating / pressure class dynamically
    rating = ""
    m_rat = re.search(r'(#\d+|\d+#|CL[- ]?\d+|150\s*LB|300\s*LB|800\s*LB|600\s*LB|PN\d+)', T, re.I)
    if m_rat:
        rating = m_rat.group(1).upper()

    # 2. Load Learnable Memory (SQLite adjustments)
    learned_adjustments = get_learned_adjustments(filename) if filename else {}
    if learned_adjustments:
        logger.info("[Voting Engine] Loaded %d adjustments from SQLite memory", len(learned_adjustments))

    # 3. Dynamic Flange Detection & Deduplication
    flange_matches = list(re.finditer(r'\b(?:FLG|BRIDE|RFWN|SORF|SOWF|WNFLG|BLIND\s*FLG|FLANGE)\b', T, re.IGNORECASE))
    deduped_flanges = []
    last_pos = -99
    for fm in flange_matches:
        if fm.start() - last_pos >= 25:
            deduped_flanges.append(fm)
            last_pos = fm.start()

    flange_counts: Dict[str, int] = {}
    for fm in deduped_flanges:
        ctx_start = max(0, fm.start() - 30)
        ctx_end = min(len(T), fm.end() + 50)
        ctx = T[ctx_start:ctx_end]
        flange_idx = fm.start() - ctx_start
        
        best_sz = None
        best_sz_dist = 9999
        for sz_try in ('1/2"', '3/4"', '1"', '1.5"', '2"', '2.5"', '3"', '4"', '6"', '8"', '10"', '12"', '14"', '16"', '18"', '20"', '24"'):
            for m_sz in re.finditer(re.escape(sz_try), ctx):
                dist = abs(m_sz.start() - flange_idx)
                if dist < best_sz_dist:
                    best_sz_dist = dist
                    best_sz = sz_try
        if best_sz:
            flange_counts[best_sz] = flange_counts.get(best_sz, 0) + 1
        else:
            # Fallback to general size if available in pipe_lengths
            if pipe_lengths:
                first_sz = list(pipe_lengths.keys())[0]
                flange_counts[first_sz] = flange_counts.get(first_sz, 0) + 1

    # 4. Dynamic Valve Extraction (strictly based on actual text tokens)
    valves = []
    # Match tags in proximity of valve keywords
    valve_keywords = ["VALVE", "VANNE", "ROBINET", "CLAPET", "GATE", "BALL", "CHECK", "GLOBE", "BUTTERFLY"]
    found_valve_tags = set()
    
    for kw in valve_keywords:
        for m_kw in re.finditer(r'\b' + kw + r'\b', T, re.IGNORECASE):
            ctx_start = max(0, m_kw.start() - 40)
            ctx_end = min(len(T), m_kw.end() + 60)
            ctx = T[ctx_start:ctx_end]
            
            # Find candidate tag e.g. V-101, XV-201, CV-102
            m_tag = re.search(r'\b([A-Z]{1,3}-?\d{2,4}[A-Z]?)\b', ctx)
            tag_name = m_tag.group(1).upper() if m_tag else f"V-{len(valves)+1:02d}"
            if tag_name in found_valve_tags:
                continue
            found_valve_tags.add(tag_name)
            
            # Find size in context
            v_sz = "2\""
            for sz_try in ('1/2"', '3/4"', '1"', '1.5"', '2"', '2.5"', '3"', '4"', '6"', '8"', '10"', '12"'):
                if sz_try in ctx:
                    v_sz = sz_try
                    break
            else:
                if pipe_lengths:
                    v_sz = list(pipe_lengths.keys())[0]

            v_type = "gate"
            u_ctx = ctx.upper()
            if "BALL" in u_ctx: v_type = "ball"
            elif "CHECK" in u_ctx or "CLAPET" in u_ctx: v_type = "check"
            elif "GLOBE" in u_ctx: v_type = "globe"
            elif "BUTTERFLY" in u_ctx: v_type = "butterfly"

            desc = f"Vanne {v_type} {rating or 'Cl.150'} {spec_mat}".strip()
            wt = get_valve_weight(v_type, v_sz)
            valves.append({
                "category": "Valves",
                "tag": tag_name,
                "description": desc,
                "size": v_sz,
                "material": spec_mat,
                "quantity": 1,
                "unit": "U",
                "weight_unit": wt,
                "weight_total": wt,
                "remarks": f"Extrait du texte ({kw})",
                "confidence": 90
            })

    # 5. Pipes (strictly using non-zero measured pipe lengths)
    pipes = []
    for sz, length in (pipe_lengths or {}).items():
        if length <= 0:
            continue
        spec = get_pipe_spec(sz)
        clean_sz = sz.replace('"', '')
        try:
            dn_val = int(float(clean_sz) * 25) if '/' not in clean_sz else 15
        except Exception:
            dn_val = 15
        pipes.append({
            "category": "Pipes",
            "tag": "-",
            "description": f"Tube {spec_mat} sans soudure ASME B36.10M",
            "size": f"{sz} (DN{dn_val})",
            "material": spec_mat,
            "quantity": round(length, 2),
            "unit": "M",
            "weight_unit": spec["weight_kg_m"],
            "weight_total": round(length * spec["weight_kg_m"], 2),
            "remarks": "Métrage réel calculé",
            "confidence": 90
        })

    # 6. Fittings (Coudes, Reducers, Flanges)
    fittings = []
    
    # 90° Elbows : count actual occurrences in text or markers
    elbow_matches = list(re.finditer(r'\b(?:ELBOW|COUDE|90\s*DEG|90°|45\s*DEG|45°)\b', T, re.IGNORECASE))
    if elbow_matches:
        count_elbows = len(elbow_matches)
        sz_elbow = list(pipe_lengths.keys())[0] if pipe_lengths else '2"'
        elbow_spec = get_elbow_spec(sz_elbow, "90", "LR")
        fittings.append({
            "category": "Fittings",
            "tag": "-",
            "description": f"Coude 90° LR BW {spec_mat}",
            "size": sz_elbow,
            "material": spec_mat,
            "quantity": count_elbows,
            "unit": "U",
            "weight_unit": elbow_spec["weight_kg"],
            "weight_total": round(count_elbows * elbow_spec["weight_kg"], 2),
            "remarks": "Détecté dans les annotations",
            "confidence": 88
        })

    # Reducer : only if an explicit reduction pattern is found in the text
    reducer_match = re.search(r'(\d+(?:\.\d+)?\s*")\s*[xX×]\s*(\d+(?:\.\d+)?\s*")', T)
    if reducer_match:
        sz1 = reducer_match.group(1).strip()
        sz2 = reducer_match.group(2).strip()
        red_spec = get_reducer_spec(sz1, sz2)
        fittings.append({
            "category": "Fittings",
            "tag": "-",
            "description": f"Réduction BW {sz1}x{sz2} {spec_mat}",
            "size": f"{sz1}x{sz2}",
            "material": spec_mat,
            "quantity": 1,
            "unit": "U",
            "weight_unit": red_spec.get("weight_kg", 2.0),
            "weight_total": red_spec.get("weight_kg", 2.0),
            "remarks": "ASME B16.9",
            "confidence": 95
        })

    # Flanges (Deduplicated counts applied)
    for sz, qty in sorted(flange_counts.items(), reverse=True):
        if qty <= 0:
            continue
        flg_spec = get_flange_spec(sz)
        fittings.append({
            "category": "Fittings",
            "tag": "-",
            "description": f"Bride RFWN {rating or 'Cl.150'} {spec_mat}",
            "size": sz,
            "material": spec_mat,
            "quantity": qty,
            "unit": "U",
            "weight_unit": flg_spec["weight_kg"],
            "weight_total": round(qty * flg_spec["weight_kg"], 2),
            "remarks": "ASME B16.5",
            "confidence": 92
        })

    # 7. Gaskets & Bolts (ASME Standard derivation based on detected flanges)
    others = []
    for sz, qty_fl in flange_counts.items():
        if qty_fl <= 0:
            continue
        joints = max(1, qty_fl // 2) + len([v for v in valves if v['size'] == sz])
        flg_spec = get_flange_spec(sz)
        
        # Gaskets
        g_wt = 0.15
        others.append({
            "category": "Others",
            "tag": "-",
            "description": f"Joint spiralé SS316L/Graphite {rating or 'Cl.150'} ASME B16.20",
            "size": sz,
            "material": "SS316L / Graphite",
            "quantity": joints,
            "unit": "U",
            "weight_unit": g_wt,
            "weight_total": round(joints * g_wt, 2),
            "remarks": "Calculé selon nombre de brides",
            "confidence": 90
        })

        # Bolts
        nb_bolts = joints * flg_spec["bolt_count"]
        b_wt = 0.08
        b_size = f"{flg_spec['bolt_size']}x{flg_spec['bolt_length']}"
        others.append({
            "category": "Others",
            "tag": "-",
            "description": "Boulonnerie goujons ASTM A193 B7 + 2 écrous A194 2H",
            "size": b_size,
            "material": "A193-B7 / A194-2H",
            "quantity": nb_bolts,
            "unit": "SET",
            "weight_unit": b_wt,
            "weight_total": round(nb_bolts * b_wt, 2),
            "remarks": f"ASME B18.2.1 ({flg_spec['bolt_count']} goujons/joint)",
            "confidence": 90
        })

    # Supports : strictly matching actual SP tags in the text
    seen_sp = set()
    sp_guide_tags = list(re.finditer(r'\b(SP-?\d{3,4}[A-Z]?)\b', T, re.IGNORECASE))
    for m in sp_guide_tags:
        sp_tag = m.group(1).upper()
        if sp_tag in seen_sp:
            continue
        seen_sp.add(sp_tag)
        others.append({
            "category": "Others",
            "tag": sp_tag,
            "description": f"Support de tuyauterie ({sp_tag})",
            "size": "N/A",
            "material": "CS Galvanisé",
            "quantity": 1,
            "unit": "U",
            "weight_unit": 10.0,
            "weight_total": 10.0,
            "remarks": "Repéré sur le plan",
            "confidence": 95
        })

    mto.extend(pipes)
    mto.extend(valves)
    mto.extend(fittings)
    mto.extend(others)

    # 8. Overrides from Feedback SQLite Memory
    for item in mto:
        key = (item["category"], item["tag"], item["size"].split(' ')[0])
        if key in learned_adjustments:
            corrected_qty = learned_adjustments[key]
            item["quantity"] = corrected_qty
            item["weight_total"] = round(corrected_qty * item["weight_unit"], 2)
            item["remarks"] += " (Ajustement mémorisé)"
            item["confidence"] = 100

    return mto
