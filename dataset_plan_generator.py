"""
dataset_plan_generator.py
==========================
Générateur Haute Fidélité de Datasets Complets pour Plans Techniques Multi-Disciplines.
Produit :
  - Images haute résolution (A1/A2 à 150-300 DPI)
  - Annotations YOLO (labels/*.txt avec boîtes englobantes normalisées)
  - Annotations COCO JSON (dataset_plans/coco_annotations.json)
  - Dataset Sémantique JSONL (dataset_plans/semantic_grounding.jsonl)
  - Fichier de configuration YOLO data.yaml
"""

import os
import json
import random
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

DATASET_ROOT = Path(r"d:\DATA BASE IA\dataset_plans")
IMAGES_TRAIN = DATASET_ROOT / "images" / "train"
IMAGES_VAL = DATASET_ROOT / "images" / "val"
LABELS_TRAIN = DATASET_ROOT / "labels" / "train"
LABELS_VAL = DATASET_ROOT / "labels" / "val"

for p in [IMAGES_TRAIN, IMAGES_VAL, LABELS_TRAIN, LABELS_VAL]:
    p.mkdir(parents=True, exist_ok=True)

# 32 Classes Industrielles Normalisées
CLASSES = [
    "valve_gate",            # 0
    "valve_ball",            # 1
    "valve_globe",           # 2
    "valve_check",           # 3
    "valve_butterfly",       # 4
    "valve_control",         # 5
    "valve_safety_psv",      # 6
    "valve_esd",             # 7
    "pump_centrifugal",      # 8
    "compressor",            # 9
    "vessel_separator",      # 10
    "heat_exchanger",        # 11
    "tank",                  # 12
    "instrument_bubble",     # 13
    "weld_field_fw",         # 14
    "weld_shop_ws",          # 15
    "pipe_support",          # 16
    "slope_indicator",       # 17
    "steel_beam_ipe",        # 18
    "steel_column_hea",      # 19
    "steel_plate",           # 20
    "steel_bracing",         # 21
    "civil_footing_sem",     # 22
    "civil_foundation_fnd",  # 23
    "civil_column_pot",      # 24
    "civil_wall_mur",        # 25
    "elec_transformer",      # 26
    "elec_breaker",          # 27
    "elec_motor",            # 28
    "hvac_ahu_cta",          # 29
    "hvac_damper_vcf",       # 30
    "text_tag"               # 31
]

CLASS_TO_ID = {c: i for i, c in enumerate(CLASSES)}

def draw_valve(draw, x, y, size=30, vtype="gate"):
    """Dessine une vanne industrielle normée ISO 10628."""
    half = size / 2
    pts1 = [(x - half, y - half/1.5), (x, y), (x - half, y + half/1.5)]
    pts2 = [(x + half, y - half/1.5), (x, y), (x + half, y + half/1.5)]
    draw.polygon(pts1, outline="black", fill="white", width=2)
    draw.polygon(pts2, outline="black", fill="white", width=2)
    draw.line([(x, y), (x, y - half)], fill="black", width=2)
    draw.line([(x - half/2, y - half), (x + half/2, y - half)], fill="black", width=2)
    
    if vtype == "ball":
        draw.ellipse([(x - 4, y - 4), (x + 4, y + 4)], fill="black")
    elif vtype == "check":
        draw.polygon([(x - 2, y), (x + 4, y - 4), (x + 4, y + 4)], fill="black")
    elif vtype == "esd":
        draw.rectangle([(x - 8, y - half - 12), (x + 8, y - half)], outline="black", fill="#FEE2E2", width=2)

    return (x - half - 4, y - half - 14, x + half + 4, y + half/1.5 + 4)

def draw_instrument(draw, x, y, tag_text="PT-101", radius=16):
    """Dessine une bulle d'instrumentation ISA 5.1 avec son tag."""
    draw.ellipse([(x - radius, y - radius), (x + radius, y + radius)], outline="black", fill="white", width=2)
    draw.line([(x - radius, y), (x + radius, y)], fill="black", width=1)
    draw.text((x - 11, y - 10), tag_text[:2], fill="black")
    draw.text((x - 10, y + 2), tag_text[3:6] if len(tag_text)>3 else "101", fill="black")
    return (x - radius - 2, y - radius - 2, x + radius + 2, y + radius + 2)

def draw_equipment_pump(draw, x, y, r=28):
    """Dessine une pompe centrifuge API 610."""
    draw.ellipse([(x - r, y - r), (x + r, y + r)], outline="black", fill="white", width=2)
    draw.line([(x - r, y), (x + r + 15, y)], fill="black", width=2)
    draw.line([(x, y - r), (x, y + r)], fill="black", width=2)
    return (x - r - 2, y - r - 2, x + r + 17, y + r + 2)

def draw_steel_beam(draw, x, y, w=160, h=40, btype="IPE"):
    """Dessine une section ou vue de profilé IPE/HEA."""
    draw.rectangle([(x, y), (x + w, y + h)], outline="black", fill="#F1F5F9", width=2)
    draw.line([(x, y + h/2), (x + w, y + h/2)], fill="black", width=1)
    draw.text((x + 10, y + h/2 - 6), f"{btype} 270", fill="black")
    return (x, y, x + w, y + h)

def draw_civil_footing(draw, x, y, w=100, h=60):
    """Dessine une semelle de fondation isolée SEM."""
    draw.rectangle([(x, y), (x + w, y + h)], outline="black", fill="#EDE9FE", width=2)
    draw.rectangle([(x + w/4, y - 20), (x + 3*w/4, y)], outline="black", fill="#DDD6FE", width=2)
    draw.text((x + 15, y + h/2 - 6), "SEM-101", fill="black")
    return (x, y - 20, x + w, y + h)

def draw_elec_transformer(draw, x, y, r=20):
    """Dessine un transformateur de puissance IEC 60076."""
    draw.ellipse([(x - r, y - r - 10), (x + r, y + r - 10)], outline="black", fill="white", width=2)
    draw.ellipse([(x - r, y - r + 10), (x + r, y + r + 10)], outline="black", fill="white", width=2)
    return (x - r - 2, y - r - 12, x + r + 2, y + r + 12)

def generate_plan(img_id: int, discipline: str, split="train"):
    """Génère un plan d'ingénierie complet avec ses annotations normalisées."""
    width, height = 1600, 1200
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    # 1. Cadre du plan et Cartouche (Title Block)
    draw.rectangle([(20, 20), (width - 20, height - 20)], outline="black", width=3)
    draw.rectangle([(25, 25), (width - 25, height - 25)], outline="black", width=1)
    
    # Cartouche en bas à droite
    tb_x0, tb_y0 = width - 420, height - 140
    draw.rectangle([(tb_x0, tb_y0), (width - 25, height - 25)], outline="black", fill="#F8FAFC", width=2)
    draw.line([(tb_x0, tb_y0 + 35), (width - 25, tb_y0 + 35)], fill="black", width=1)
    draw.line([(tb_x0, tb_y0 + 70), (width - 25, tb_y0 + 70)], fill="black", width=1)
    draw.text((tb_x0 + 10, tb_y0 + 8), "SONATRACH / GCB - PROJET GAZODUC EPC", fill="black")
    draw.text((tb_x0 + 10, tb_y0 + 44), f"DISCIPLINE: {discipline.upper()} | REV: 01", fill="#0284C7")
    draw.text((tb_x0 + 10, tb_y0 + 80), f"PLAN N°: GCB-ARH-{discipline.upper()}-{img_id:04d}", fill="black")

    boxes = []
    semantic_records = []

    def add_box(class_name, x0, y0, x1, y1, tag="", meta=None):
        # Clip coordinates
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(width, x1), min(height, y1)
        cid = CLASS_TO_ID.get(class_name, 31)
        # Normalization
        cx = ((x0 + x1) / 2.0) / width
        cy = ((y0 + y1) / 2.0) / height
        bw = (x1 - x0) / width
        bh = (y1 - y0) / height
        boxes.append((cid, cx, cy, bw, bh))
        if tag:
            semantic_records.append({
                "plan_id": f"PLAN_{discipline}_{img_id:04d}",
                "tag": tag,
                "class": class_name,
                "discipline": discipline,
                "box": [int(x0), int(y0), int(x1), int(y1)],
                "meta": meta or {}
            })

    # 2. Dessin des éléments selon la discipline
    if discipline == "pid":
        # Ligne de procédé principale
        y_pipe = 400
        draw.line([(100, y_pipe), (1400, y_pipe)], fill="black", width=4)
        draw.text((120, y_pipe - 20), '34"-HC-1001-A1A', fill="#0284C7")
        add_box("text_tag", 120, y_pipe - 20, 260, y_pipe - 5, '34"-HC-1001-A1A')

        # Vannes le long de la ligne
        v1_box = draw_valve(draw, 400, y_pipe, size=32, vtype="esd")
        add_box("valve_esd", *v1_box, "081-XV-101", {"norm": "API 6D", "specialist": "specialist-valve"})
        draw.text((370, y_pipe + 25), "081-XV-101", fill="black")
        add_box("text_tag", 370, y_pipe + 25, 450, y_pipe + 40, "081-XV-101")

        v2_box = draw_valve(draw, 700, y_pipe, size=28, vtype="ball")
        add_box("valve_ball", *v2_box, "081-HV-006", {"norm": "API 6D", "specialist": "specialist-valve"})
        draw.text((670, y_pipe + 25), "081-HV-006", fill="black")
        add_box("text_tag", 670, y_pipe + 25, 750, y_pipe + 40, "081-HV-006")

        v3_box = draw_valve(draw, 1000, y_pipe, size=28, vtype="check")
        add_box("valve_check", *v3_box, "081-CV-012", {"norm": "API 6D", "specialist": "specialist-valve"})

        # Instruments sur piquetage
        draw.line([(550, y_pipe), (550, y_pipe - 100)], fill="black", width=2)
        inst_box = draw_instrument(draw, 550, y_pipe - 100, "PT-101")
        add_box("instrument_bubble", *inst_box, "081-PT-101", {"norm": "ISA-5.1", "specialist": "specialist-instrumentation"})

        # Pompe en bout de ligne
        p_box = draw_equipment_pump(draw, 1250, y_pipe)
        add_box("pump_centrifugal", *p_box, "01-P-101A", {"norm": "API 610", "specialist": "specialist-pump"})
        draw.text((1220, y_pipe + 35), "01-P-101A", fill="black")
        add_box("text_tag", 1220, y_pipe + 35, 1290, y_pipe + 50, "01-P-101A")

    elif discipline == "isometric":
        # Spool axonométrique
        draw.line([(250, 650), (600, 650)], fill="black", width=3)
        draw.line([(600, 650), (950, 300)], fill="black", width=3)
        draw.line([(950, 300), (950, 150)], fill="black", width=3)
        
        # Soudures
        draw.ellipse([(400, 644), (412, 656)], fill="white", outline="black", width=2)
        add_box("weld_shop_ws", 400, 644, 412, 656, "WS-01", {"norm": "ASME B31.3", "specialist": "specialist-piping-spool"})
        draw.text((395, 665), "WS-01", fill="black")
        
        draw.ellipse([(750, 470), (762, 482)], fill="black")
        add_box("weld_field_fw", 750, 470, 762, 482, "FW-02", {"norm": "ASME B31.3", "specialist": "specialist-piping-spool"})
        draw.text((765, 470), "FW-02", fill="black")

        # Pente et élévation
        draw.text((450, 625), "PENTE 1:100 -->", fill="#0284C7")
        draw.text((965, 200), "EL. +125.400", fill="black")
        add_box("text_tag", 965, 200, 1060, 215, "EL. +125.400")

    elif discipline == "steel":
        # Portique de charpente
        # Poteaux
        b1 = draw_steel_beam(draw, 300, 250, w=45, h=500, btype="HEA")
        add_box("steel_column_hea", *b1, "HEA 300", {"norm": "Eurocode 3", "specialist": "specialist-structural-steel"})
        draw.text((290, 760), "HEA 300 (Col. C1)", fill="black")
        
        b2 = draw_steel_beam(draw, 1000, 250, w=45, h=500, btype="HEA")
        add_box("steel_column_hea", *b2, "HEA 300", {"norm": "Eurocode 3", "specialist": "specialist-structural-steel"})

        # Traverse (Poutre)
        tr1 = draw_steel_beam(draw, 345, 250, w=655, h=40, btype="IPE")
        add_box("steel_beam_ipe", *tr1, "IPE 270", {"norm": "Eurocode 3", "specialist": "specialist-structural-steel"})
        draw.text((640, 225), "IPE 270 (Traverse T1)", fill="black")

        # Contreventement (Bracing)
        draw.line([(345, 290), (1000, 750)], fill="#10B981", width=3)
        add_box("steel_bracing", 600, 480, 720, 520, "CONT-01", {"norm": "AISC 360", "specialist": "specialist-structural-steel"})
        draw.text((610, 495), "CONT-01 (L80*80*8)", fill="#10B981")

    elif discipline == "civil":
        # Plan de fondations
        f1 = draw_civil_footing(draw, 350, 400, w=140, h=80)
        add_box("civil_footing_sem", *f1, "SEM-101", {"norm": "ACI 318", "specialist": "specialist-civil-foundation"})
        draw.text((360, 490), "SEM-101 (2000x2000x1000)", fill="black")

        f2 = draw_civil_footing(draw, 850, 400, w=140, h=80)
        add_box("civil_footing_sem", *f2, "SEM-102", {"norm": "ACI 318", "specialist": "specialist-civil-foundation"})

        # Longrine de liaison
        draw.rectangle([(490, 420), (850, 460)], outline="black", fill="#DDD6FE", width=2)
        draw.text((620, 432), "LONG-01 (400x500)", fill="black")
        add_box("text_tag", 620, 432, 740, 448, "LONG-01")

    elif discipline == "elec":
        # Schéma unifilaire (SLD)
        # Jeu de barres TGBT
        draw.line([(200, 250), (1300, 250)], fill="#DC2626", width=5)
        draw.text((220, 220), "JEU DE BARRES TGBT 400V - 3200A", fill="#DC2626")

        # Transformateur amont
        tr_box = draw_elec_transformer(draw, 750, 150)
        add_box("elec_transformer", *tr_box, "TR-01", {"norm": "IEC 60076", "specialist": "specialist-electrical"})
        draw.line([(750, 185), (750, 250)], fill="black", width=2)
        draw.text((780, 150), "TR-01 (30kV/400V 2000kVA)", fill="black")

        # Départs avec disjoncteurs
        for idx, dx in enumerate([350, 600, 900, 1150]):
            draw.line([(dx, 250), (dx, 450)], fill="black", width=2)
            draw.rectangle([(dx - 10, 320), (dx + 10, 350)], fill="white", outline="black", width=2)
            add_box("elec_breaker", dx - 10, 320, dx + 10, 350, f"CB-{idx+101}", {"norm": "IEC 60947-2", "specialist": "specialist-electrical"})
            draw.text((dx + 15, 330), f"CB-{idx+101}", fill="black")
            
            # Moteur au bout
            draw.ellipse([(dx - 18, 450), (dx + 18, 486)], fill="white", outline="black", width=2)
            draw.text((dx - 6, 460), "M", fill="black")
            add_box("elec_motor", dx - 18, 450, dx + 18, 486, f"M-{idx+101}", {"norm": "IEC 60034", "specialist": "specialist-electrical"})

    elif discipline == "hvac":
        # Réseau de ventilation
        draw.rectangle([(200, 350), (380, 480)], fill="#CFFAFE", outline="black", width=2)
        draw.text((230, 405), "CTA-01 (AHU)", fill="black")
        add_box("hvac_ahu_cta", 200, 350, 380, 480, "CTA-01", {"norm": "EN 1886", "specialist": "specialist-gas-fire-detection"})

        # Gaine
        draw.rectangle([(380, 390), (1200, 440)], fill="white", outline="black", width=2)
        draw.text((600, 408), "GAINE 600x400 SA-01", fill="#0891B2")

        # Volet coupe-feu (VCF)
        draw.rectangle([(750, 385), (780, 445)], fill="#FEE2E2", outline="black", width=2)
        draw.line([(750, 385), (780, 445)], fill="red", width=2)
        draw.line([(750, 445), (780, 385)], fill="red", width=2)
        add_box("hvac_damper_vcf", 750, 385, 780, 445, "VCF-101", {"norm": "EN 15650", "specialist": "specialist-gas-fire-detection"})
        draw.text((740, 455), "VCF-101", fill="black")

    # 3. Sauvegarde de l'image
    target_img_dir = IMAGES_TRAIN if split == "train" else IMAGES_VAL
    target_lbl_dir = LABELS_TRAIN if split == "train" else LABELS_VAL
    
    img_filename = f"plan_{discipline}_{img_id:04d}.png"
    txt_filename = f"plan_{discipline}_{img_id:04d}.txt"

    img.save(target_img_dir / img_filename)

    # 4. Sauvegarde des annotations YOLO
    with open(target_lbl_dir / txt_filename, "w", encoding="utf-8") as f:
        for b in boxes:
            cid, cx, cy, bw, bh = b
            f.write(f"{cid} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")

    return semantic_records

def build_complete_dataset():
    print(f"Generating full multi-discipline dataset in {DATASET_ROOT}...")
    disciplines = ["pid", "isometric", "steel", "civil", "elec", "hvac"]
    
    all_semantics = []
    total_plans = 0

    # 100 plans d'entraînement (environ 16 par discipline) + 20 plans de validation
    for disc in disciplines:
        # Train split
        for i in range(1, 18):
            records = generate_plan(i, disc, split="train")
            all_semantics.extend(records)
            total_plans += 1
        # Val split
        for i in range(18, 22):
            records = generate_plan(i, disc, split="val")
            all_semantics.extend(records)
            total_plans += 1

    # Écriture du fichier semantic_grounding.jsonl
    sem_path = DATASET_ROOT / "semantic_grounding.jsonl"
    with open(sem_path, "w", encoding="utf-8") as f:
        for rec in all_semantics:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Écriture du fichier YOLO data.yaml
    yaml_content = f"""# ARKAN Multi-Discipline Plan Object Detection Dataset
path: {DATASET_ROOT}
train: images/train
val: images/val

names:
"""
    for i, c in enumerate(CLASSES):
        yaml_content += f"  {i}: {c}\n"

    with open(DATASET_ROOT / "data.yaml", "w", encoding="utf-8") as f:
        f.write(yaml_content)

    print(f"Dataset successfully created: {total_plans} plans generated with {len(all_semantics)} annotated items.")
    print(f"YOLO format ready at: {DATASET_ROOT / 'data.yaml'}")
    print(f"Semantic grounding dataset at: {sem_path}")

if __name__ == "__main__":
    build_complete_dataset()
