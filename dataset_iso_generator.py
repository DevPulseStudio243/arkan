"""
dataset_iso_generator.py
Générateur de dataset synthétique avancé pour le Fine-Tuning Vision-LLM & SFT (Qwen2.5 / Unsloth).
Spécialisé pour la lecture complète des plans isométriques :
1. Plans de Type A (Avec tableau de bordereau MTO explicite)
2. Plans de Type B (Plans de tracé pur SANS bordereau, avec cotes d'entraxe, déduction des take-offs et métré de tube coupé net)
"""

import json
import random
from pathlib import Path
from typing import List, Dict, Any

LINES_SPECS = [
    {"service": "P", "fluid": "Crude Oil Process", "spec": "A1A cl.150", "rating": "150#", "mat_pipe": "ASTM A106 Gr.B", "mat_flange": "ASTM A105"},
    {"service": "HC", "fluid": "Hydrocarbon Liquid", "spec": "1CS1P", "rating": "300#", "mat_pipe": "ASTM A106 Gr.B", "mat_flange": "ASTM A105"},
    {"service": "PG", "fluid": "Process Gas", "spec": "2CS1P", "rating": "600#", "mat_pipe": "ASTM A106 Gr.B", "mat_flange": "ASTM A105"},
    {"service": "GL", "fluid": "Gas Lift Injection", "spec": "3CS1P", "rating": "600#", "mat_pipe": "ASTM A106 Gr.B", "mat_flange": "ASTM A105"},
    {"service": "LNG", "fluid": "Cryogenic Methane", "spec": "1LT1P", "rating": "300#", "mat_pipe": "ASTM A333 Gr.6", "mat_flange": "ASTM A350 LF2"},
    {"service": "SOUR", "fluid": "Acid Gas H2S (NACE)", "spec": "3CS1P-NACE", "rating": "900#", "mat_pipe": "ASTM A106 Gr.B", "mat_flange": "ASTM A105 (NACE)"},
    {"service": "STM", "fluid": "Superheated Steam", "spec": "3SS1P-H", "rating": "900#", "mat_pipe": "ASTM A335 P11", "mat_flange": "ASTM A182 F11"}
]

DIAMETERS_CONFIG = {
    "2\"": {"sch": "SCH 40", "od_mm": 60.3, "elbow_c_e": 76.2, "tee_c_e": 63.5, "flg_h": 63.5, "valve_l": 178.0, "bolts_per_flg": 4, "bolt_desc": "5/8\" X 75MM"},
    "3\"": {"sch": "SCH 40", "od_mm": 88.9, "elbow_c_e": 114.3, "tee_c_e": 85.7, "flg_h": 69.8, "valve_l": 203.0, "bolts_per_flg": 4, "bolt_desc": "5/8\" X 80MM"},
    "4\"": {"sch": "SCH 40", "od_mm": 114.3, "elbow_c_e": 152.4, "tee_c_e": 104.8, "flg_h": 76.2, "valve_l": 229.0, "bolts_per_flg": 8, "bolt_desc": "5/8\" X 85MM"},
    "6\"": {"sch": "SCH 40", "od_mm": 168.3, "elbow_c_e": 228.6, "tee_c_e": 142.9, "flg_h": 88.9, "valve_l": 267.0, "bolts_per_flg": 8, "bolt_desc": "3/4\" X 90MM"},
    "8\"": {"sch": "SCH 40", "od_mm": 219.1, "elbow_c_e": 304.8, "tee_c_e": 177.8, "flg_h": 101.6, "valve_l": 292.0, "bolts_per_flg": 8, "bolt_desc": "3/4\" X 100MM"},
    "10\"": {"sch": "SCH 40", "od_mm": 273.0, "elbow_c_e": 381.0, "tee_c_e": 215.9, "flg_h": 101.6, "valve_l": 330.0, "bolts_per_flg": 12, "bolt_desc": "7/8\" X 110MM"},
    "12\"": {"sch": "SCH 40", "od_mm": 323.8, "elbow_c_e": 457.2, "tee_c_e": 254.0, "flg_h": 114.3, "valve_l": 356.0, "bolts_per_flg": 12, "bolt_desc": "7/8\" X 120MM"}
}

VALVE_TYPES = ["VANNE A OPERCULE", "VANNE A BOISSEAU SPHERIQUE", "VANNE A CLAPET", "VANNE A SOUPAPE"]

def generate_implicit_iso_sample(sample_id: int) -> Dict[str, Any]:
    """Génère un exemple de plan de tracé pur SANS bordereau pré-imprimé."""
    cfg = random.choice(LINES_SPECS)
    size = random.choice(list(DIAMETERS_CONFIG.keys()))
    dcfg = DIAMETERS_CONFIG[size]
    sch = dcfg["sch"]
    
    clean_size = size.replace('"', '')
    clean_spec = cfg['spec'].split()[0]
    line_num = f"{clean_size}-{cfg['service']}-{random.randint(100, 999)}-{clean_spec}"
    dwg_no = f"ISO-TR-{random.randint(1000, 9999)}-{chr(65 + (sample_id % 26))}"
    
    # 4 à 6 cotes en mm
    num_cotes = random.randint(4, 6)
    cotes = [random.randint(800, 3500) for _ in range(num_cotes)]
    total_axis_mm = sum(cotes)
    
    num_elbows = 2
    num_tees = 1 if num_cotes >= 5 else 0
    num_flanges = 3 if num_tees == 1 else 2
    num_valves = 1
    
    # Take-offs précis selon ASME B16.9 / B16.5 / B16.10
    ded_elbows = num_elbows * 2 * dcfg["elbow_c_e"]
    ded_tees = num_tees * 3 * dcfg["tee_c_e"]
    ded_flanges = num_flanges * dcfg["flg_h"]
    ded_valve = num_valves * dcfg["valve_l"]
    
    total_ded_mm = ded_elbows + ded_tees + ded_flanges + ded_valve
    cut_length_mm = max(800, total_axis_mm - total_ded_mm)
    cut_length_m = round(cut_length_mm / 1000.0, 3)
    axis_length_m = round(total_axis_mm / 1000.0, 3)
    
    total_welds = 2 * num_flanges + 2 * num_elbows + 3 * num_tees + 2 * num_valves
    
    ocr_lines = []
    for w in range(1, total_welds + 1):
        ocr_lines.append(str(w))
    for c in cotes:
        ocr_lines.append(str(c))
        
    ocr_lines.append(f"BRIDE WN {size} {cfg['rating']} RF {sch}")
    ocr_lines.append(f"COUDE 90° GR {size} {sch} BW")
    if num_tees > 0:
        ocr_lines.append(f"TE EGAL {size} {sch} BW")
        ocr_lines.append(f"BRIDE WN {size} {cfg['rating']} RF {sch} (PIQUAGE)")
    v_type = random.choice(VALVE_TYPES)
    ocr_lines.append(f"{v_type} {size} {cfg['rating']} BW")
    ocr_lines.append(f"BRIDE WN {size} {cfg['rating']} RF {sch}")
    ocr_lines.append(f"COUDE 90° GR {size} {sch} BW")
    
    ocr_lines.append("Y (Nord) X (Est)")
    ocr_lines.append("Z (Haut)")
    ocr_lines.append("Légende")
    ocr_lines.append(f"Soudure bout à bout (numérotée 1 à {total_welds})")
    ocr_lines.append("Cotes en mm, entre axes. Plan isométrique sans échelle.")
    ocr_lines.append("PLAN ISOMÉTRIQUE")
    ocr_lines.append(f"Ligne {line_num}")
    ocr_lines.append(f"LIGNE : {line_num}")
    ocr_lines.append(f"SPEC : {cfg['spec']}")
    ocr_lines.append(f"MATIÈRE : {cfg['mat_pipe']}")
    ocr_lines.append("ÉCHELLE : Sans échelle (NTS)")
    ocr_lines.append("DATE : 30/09/2026")
    ocr_lines.append("RÉV. : A")
    
    raw_ocr = "\n".join(ocr_lines)
    
    mto = [
        {
            "category": "PIPE",
            "tag": "PIP-01",
            "description": f"TUBE SMLS BE {size} {sch} {cfg['mat_pipe']}",
            "size": size,
            "schedule": sch,
            "rating": cfg["rating"],
            "material": cfg["mat_pipe"],
            "quantity": cut_length_m,
            "unit": "M",
            "length_centerline_m": axis_length_m,
            "takeoffs_deducted_m": round(total_ded_mm / 1000.0, 3)
        },
        {
            "category": "FLANGE",
            "tag": "FLA-02",
            "description": f"BRIDE WN {size} {cfg['rating']} RF {sch}",
            "size": size,
            "schedule": sch,
            "rating": cfg["rating"],
            "material": cfg["mat_flange"],
            "quantity": float(num_flanges),
            "unit": "EA"
        },
        {
            "category": "FITTING",
            "tag": "FIT-03",
            "description": f"COUDE 90° GR {size} {sch} BW",
            "size": size,
            "schedule": sch,
            "rating": cfg["rating"],
            "material": "ASTM A234 WPB",
            "quantity": float(num_elbows),
            "unit": "EA"
        }
    ]
    if num_tees > 0:
        mto.append({
            "category": "FITTING",
            "tag": "FIT-04",
            "description": f"TE EGAL {size} {sch} BW",
            "size": size,
            "schedule": sch,
            "rating": cfg["rating"],
            "material": "ASTM A234 WPB",
            "quantity": float(num_tees),
            "unit": "EA"
        })
    mto.append({
        "category": "VALVE",
        "tag": "VAL-05",
        "description": f"{v_type} {size} {cfg['rating']} BW",
        "size": size,
        "schedule": sch,
        "rating": cfg["rating"],
        "material": "ASTM A216 WCB",
        "quantity": float(num_valves),
        "unit": "EA"
    })
    mto.append({
        "category": "GASKET",
        "tag": "GAS-06",
        "description": f"JOINT SPIRALÉ RF {cfg['rating']} {size} SS316L/GRAPHITE",
        "size": size,
        "schedule": sch,
        "rating": cfg["rating"],
        "material": "SS316L / Graphite",
        "quantity": float(num_flanges),
        "unit": "EA"
    })
    total_bolts = num_flanges * dcfg["bolts_per_flg"]
    mto.append({
        "category": "BOLT",
        "tag": "BOL-07",
        "description": f"GOUJONS {dcfg['bolt_desc']} W/ 2 NUTS ASTM A193 B7 / A194 2H",
        "size": size,
        "schedule": sch,
        "rating": cfg["rating"],
        "material": "ASTM A193 B7 / A194 2H",
        "quantity": float(total_bolts),
        "unit": "SET"
    })
    
    cot_reasoning = f"""Raisonnement d'ingénierie (Plan sans bordereau MTO) :
1. Cartouche : Ligne={line_num}, Diamètre principal={size}, Spécification={cfg['spec']}, Matière={cfg['mat_pipe']}.
2. Cotes d'entraxe : {cotes} -> Somme brute entraxe = {total_axis_mm} mm ({axis_length_m} m).
3. Déduction des take-offs des raccords (ASME B16.9/B16.5/B16.10) :
   - {num_elbows} coudes 90° LR (2x{dcfg['elbow_c_e']}mm = {ded_elbows}mm)
   - {num_tees} té ({ded_tees}mm)
   - {num_flanges} brides ({ded_flanges}mm)
   - {num_valves} vanne ({ded_valve}mm)
   Total encombrements déduits = {total_ded_mm} mm ({total_ded_mm/1000.0:.3f} m).
   Longueur débitée nette du tube (PIPE) = {total_axis_mm} - {total_ded_mm} = {cut_length_mm} mm ({cut_length_m} m).
4. Composants agrégés : {num_flanges} brides, {num_elbows} coudes, {num_tees} té, {num_valves} vanne.
5. Dérivation : {num_flanges} joints spiralés RF et {total_bolts} jeux de goujons."""

    conversations = [
        {
            "role": "user",
            "content": f"Tu es un ingénieur expert en tuyauterie industrielle. Analyse cet isométrique technique SANS BORDEREAU DE MATÉRIEL, calcule le métré linéaire de tube débité net après déduction des take-offs de raccords, regroupe les composants et génère le MTO complet en JSON strict :\n\n{raw_ocr}"
        },
        {
            "role": "assistant",
            "content": f"{cot_reasoning}\n\n```json\n" + json.dumps({
                "plan_type": "IMPLICIT_MTO",
                "metadata": {
                    "line_number": line_num,
                    "spec": cfg["spec"],
                    "material": cfg["mat_pipe"],
                    "rating": cfg["rating"]
                },
                "pipe_net_cut_length_m": cut_length_m,
                "pipe_centerline_length_m": axis_length_m,
                "takeoffs_deducted_m": round(total_ded_mm / 1000.0, 3),
                "total_items": len(mto),
                "mto": mto
            }, indent=2) + "\n```"
        }
    ]
    
    return {
        "id": f"iso_imp_{sample_id:05d}",
        "type": "IMPLICIT_MTO",
        "raw_text": raw_ocr,
        "conversations": conversations
    }

def generate_explicit_iso_sample(sample_id: int) -> Dict[str, Any]:
    """Génère un exemple d'isométrique avec tableau BOM explicite."""
    cfg = random.choice(LINES_SPECS)
    size = random.choice(list(DIAMETERS_CONFIG.keys()))
    sch = DIAMETERS_CONFIG[size]["sch"]
    clean_size = size.replace('"', '')
    clean_spec = cfg['spec'].split()[0]
    line_num = f"{clean_size}-{cfg['service']}-{random.randint(10000, 99999)}-{clean_spec}-H"
    dwg_no = f"ISO-EXP-{random.randint(1000, 9999)}-{chr(65 + (sample_id % 26))}"
    
    pipe_length = round(random.uniform(4.0, 45.0), 1)
    num_elbows = random.randint(2, 6)
    num_tees = random.randint(0, 2)
    num_flanges = random.randint(2, 4)
    num_valves = random.randint(1, 2)
    
    bom_lines = []
    bom_truth = []
    item_idx = 1
    
    # Pipe
    bom_lines.append(f"{item_idx:<4} PIPE SMLS BE {sch:<10} {pipe_length}M  {size:<6} {sch:<10} {cfg['mat_pipe']}")
    bom_truth.append({
        "item_no": item_idx, "category": "PIPE", "tag": f"PIP-{item_idx:02d}",
        "description": f"PIPE SMLS BE {sch}", "size": size, "schedule": sch,
        "rating": cfg["rating"], "material": cfg["mat_pipe"], "quantity": pipe_length, "unit": "M"
    })
    item_idx += 1
    
    # Elbows
    bom_lines.append(f"{item_idx:<4} ELBOW 90 LR BW {sch:<8} {num_elbows:<5} {size:<6} {sch:<10} ASTM A234 WPB")
    bom_truth.append({
        "item_no": item_idx, "category": "FITTING", "tag": f"FIT-{item_idx:02d}",
        "description": f"ELBOW 90 LR BW {sch}", "size": size, "schedule": sch,
        "rating": cfg["rating"], "material": "ASTM A234 WPB", "quantity": float(num_elbows), "unit": "EA"
    })
    item_idx += 1
    
    if num_tees > 0:
        bom_lines.append(f"{item_idx:<4} TEE EQUAL BW {sch:<10} {num_tees:<5} {size:<6} {sch:<10} ASTM A234 WPB")
        bom_truth.append({
            "item_no": item_idx, "category": "FITTING", "tag": f"FIT-{item_idx:02d}",
            "description": f"TEE EQUAL BW {sch}", "size": size, "schedule": sch,
            "rating": cfg["rating"], "material": "ASTM A234 WPB", "quantity": float(num_tees), "unit": "EA"
        })
        item_idx += 1
        
    bom_lines.append(f"{item_idx:<4} FLANGE WN RF {cfg['rating']} {sch:<5} {num_flanges:<5} {size:<6} {cfg['rating']:<10} {cfg['mat_flange']}")
    bom_truth.append({
        "item_no": item_idx, "category": "FLANGE", "tag": f"FLA-{item_idx:02d}",
        "description": f"FLANGE WN RF {cfg['rating']} {sch}", "size": size, "schedule": sch,
        "rating": cfg["rating"], "material": cfg["mat_flange"], "quantity": float(num_flanges), "unit": "EA"
    })
    item_idx += 1
    
    for _ in range(num_valves):
        v_name = random.choice(VALVE_TYPES)
        bom_lines.append(f"{item_idx:<4} {v_name} {cfg['rating']:<5} 1     {size:<6} {cfg['rating']:<10} ASTM A216-WCB")
        bom_truth.append({
            "item_no": item_idx, "category": "VALVE", "tag": f"VAL-{item_idx:02d}",
            "description": f"{v_name} {cfg['rating']}", "size": size, "schedule": sch,
            "rating": cfg["rating"], "material": "ASTM A216-WCB", "quantity": 1.0, "unit": "EA"
        })
        item_idx += 1
        
    bom_text = "\n".join(bom_lines)
    raw_text = f"""
========================================================================
ENGINEERING CONTRACTOR: ARKAN EPC DESIGN CORP
DRAWING NUMBER: {dwg_no}
LINE NUMBER: {line_num}
PIPING SPEC: {cfg['spec']}
MATERIAL: {cfg['mat_pipe']}
DESIGN PRESS: 25.0 BARG
DESIGN TEMP: 120.0 DEG C
========================================================================
BILL OF MATERIALS / NOMENCLATURE DE TUYAUTERIE (BOM)
ITEM  TAG / DESCRIPTION               QTY   NPS   SCH/RATING  MATERIAL
{bom_text}
========================================================================
"""
    conversations = [
        {
            "role": "user",
            "content": f"Tu es un ingénieur expert en tuyauterie industrielle. Analyse cet isométrique technique avec bordereau BOM et extrait en JSON strict la nomenclature complète (MTO) :\n\n{raw_text.strip()}"
        },
        {
            "role": "assistant",
            "content": "```json\n" + json.dumps({
                "plan_type": "EXPLICIT_BOM",
                "metadata": {
                    "line_number": line_num,
                    "drawing_number": dwg_no,
                    "piping_spec": cfg["spec"]
                },
                "total_items": len(bom_truth),
                "mto": bom_truth
            }, indent=2) + "\n```"
        }
    ]
    return {
        "id": f"iso_exp_{sample_id:05d}",
        "type": "EXPLICIT_BOM",
        "raw_text": raw_text.strip(),
        "conversations": conversations
    }

def generate_dataset(total_samples: int = 1000):
    samples = []
    # 50% Plans sans bordereau (Type B / Implicite avec take-offs), 50% Plans avec bordereau (Type A)
    half = total_samples // 2
    for i in range(1, half + 1):
        samples.append(generate_implicit_iso_sample(i))
    for i in range(half + 1, total_samples + 1):
        samples.append(generate_explicit_iso_sample(i))
        
    random.shuffle(samples)
    
    split_idx = int(total_samples * 0.9)
    train_data = samples[:split_idx]
    eval_data = samples[split_idx:]
    
    target_dirs = [
        Path("kaggle_dataset_iso_mto"),
        Path("data/fine_tuning_iso")
    ]
    
    for tdir in target_dirs:
        tdir.mkdir(parents=True, exist_ok=True)
        train_file = tdir / "iso_mto_train.jsonl"
        eval_file = tdir / "iso_mto_eval.jsonl"
        
        with open(train_file, "w", encoding="utf-8") as f:
            for s in train_data:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
                
        with open(eval_file, "w", encoding="utf-8") as f:
            for s in eval_data:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
                
        print(f"[Dataset-Generator] Sauvegardé dans {tdir} : {len(train_data)} train, {len(eval_data)} eval")

if __name__ == "__main__":
    generate_dataset(1000)
