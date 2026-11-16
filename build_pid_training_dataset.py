import os
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Any
import openpyxl
import fitz

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PID_Dataset_Builder")

def parse_sonatrach_comments(excel_path: Path) -> List[Dict[str, Any]]:
    """Extrait les règles d'or et corrections d'ingénierie Sonatrach depuis le fichier Excel."""
    dataset = []
    if not excel_path.exists():
        logger.warning(f"Fichier commentaires absent: {excel_path}")
        return dataset

    wb = openpyxl.load_workbook(excel_path, data_only=True)
    sheet = wb.active
    
    for row_idx in range(4, sheet.max_row + 1):
        sheet_tag = sheet.cell(row=row_idx, column=1).value
        comment = sheet.cell(row=row_idx, column=2).value
        reponse = sheet.cell(row=row_idx, column=3).value
        status = sheet.cell(row=row_idx, column=4).value
        impact = sheet.cell(row=row_idx, column=5).value
        
        if comment and str(comment).strip():
            comment_str = str(comment).strip().replace("\n", " ")
            reponse_str = str(reponse or "Modifications intégrées selon les standards Sonatrach").strip().replace("\n", " ")
            sheet_str = str(sheet_tag or "P&ID Standard").strip()
            impact_str = str(impact or "Mise en conformité du schéma de tuyauterie").strip().replace("\n", " ")
            
            entry = {
                "instruction": f"En tant qu'ingénieur de procédé EPC, quelle est la modification et la règle de sécurité requise par Sonatrach pour le plan {sheet_str} concernant la remarque : {comment_str} ?",
                "input": f"Plan: {sheet_str} | État: {status or 'Revue technique'}",
                "output": f"Spécification technique Sonatrach : {reponse_str}. Impact sur le P&ID : {impact_str}. "
                          f"Exigence normative : Garantir les positions de verrouillage de sécurité (LO/LC) sur les soupapes PSV, "
                          f"la séparation hermétique des collecteurs de torche HP et BP, et l'insertion de clapets anti-retour sur les refoulements.",
                "source": "Sonatrach EPF Review Comments"
            }
            dataset.append(entry)
            
    logger.info(f"Commentaires Sonatrach extraits : {len(dataset)} exemples d'entraînement.")
    return dataset

def extract_pdf_pid_topology(pdf_path: Path, max_pages: int = 1) -> Dict[str, Any]:
    """Extrait le texte et les symboles majeurs d'un plan P&ID PDF."""
    try:
        doc = fitz.open(pdf_path)
        all_text = ""
        for i in range(min(len(doc), max_pages)):
            all_text += doc[i].get_text() + "\n"
        
        # Détection des lignes de tuyauteries
        line_patterns = [
            r'\b(\d{1,2}\"[A-Za-z0-9\-]+)\b',
            r'\b([0-9]{1,2}\"-[A-Z]{2,4}-[0-9]{3,5}-[A-Z0-9]+)\b'
        ]
        lines = []
        for p in line_patterns:
            lines.extend(re.findall(p, all_text))
        lines = list(dict.fromkeys(lines))[:15]
        
        # Détection des équipements
        equip_pattern = r'\b([A-Z]{1,2}-[0-9]{3,4}[A-Z0-9]*)\b'
        raw_equips = re.findall(equip_pattern, all_text)
        valid_equips = [e for e in raw_equips if not e.startswith(("ISO-", "API-", "REV-", "DOC-"))]
        equipments = list(dict.fromkeys(valid_equips))[:10]
        
        # Détection des instruments
        inst_pattern = r'\b([PLTF][IETVCA][C]?[0-9]{3,4}[A-Z]?)\b'
        instruments = list(dict.fromkeys(re.findall(inst_pattern, all_text)))[:12]
        
        return {
            "filename": pdf_path.name,
            "equipments": equipments,
            "pipelines": lines,
            "instruments": instruments
        }
    except Exception as e:
        return {"filename": pdf_path.name, "error": str(e), "equipments": [], "pipelines": [], "instruments": []}

def build_pid_training_dataset():
    excel_path = Path("data/DATASET_PID/3-Process/COMMENTAIRES SH PID EPF - PR.XLSX")
    dataset: List[Dict[str, Any]] = []
    
    # 1. Règles d'or & Revues Sonatrach
    sh_comments = parse_sonatrach_comments(excel_path)
    dataset.extend(sh_comments)
    
    # 2. Ingestion des P&IDs réels du dataset
    catalog_path = Path("data/pid_catalog.json")
    if catalog_path.exists():
        with open(catalog_path, encoding="utf-8") as f:
            catalog_data = json.load(f)
            
        pdf_plans = [
            p for p in catalog_data.get("plans", []) 
            if p["extension"] == "pdf" and ("P&ID" in p.get("discipline", "") or "PID" in p.get("discipline", ""))
        ]
        logger.info(f"Plans P&ID trouvés : {len(pdf_plans)}. Extraction de la topologie sur 120 plans représentatifs...")
        
        sample_plans = pdf_plans[:120]
        for p_info in sample_plans:
            f_path = Path(p_info["filepath"])
            if f_path.exists():
                topo = extract_pdf_pid_topology(f_path)
                eq_list = topo.get("equipments", [])
                pl_list = topo.get("pipelines", [])
                inst_list = topo.get("instruments", [])
                
                if eq_list or pl_list or inst_list:
                    dataset.append({
                        "instruction": f"Génère la topologie de procédé P&ID normalisée pour le plan technique '{p_info['filename']}' du projet '{p_info['project']}'.",
                        "input": f"Projet : {p_info['project']} | Document : {p_info['filename']}",
                        "output": json.dumps({
                            "title": p_info['filename'].replace(".pdf", ""),
                            "project": p_info['project'],
                            "equipments": eq_list,
                            "pipelines": pl_list,
                            "instruments": inst_list,
                            "standard": "Sonatrach / ISA-5.1"
                        }, ensure_ascii=False, indent=2),
                        "source": p_info['filename']
                    })

    # 3. Synthèse de cas d'ingénierie réutilisables (Archetypes P&ID)
    archetypes = [
        {
            "prompt": "Concevoir le P&ID d'un séparateur de production diphasique HP (High Pressure) avec régulation de niveau et sécurité torche.",
            "equipments": [
                {"tag": "V-101", "type": "vessel", "label": "HP Production Separator", "design_pressure": "68 barg", "design_temp": "85 °C"},
                {"tag": "P-101A/B", "type": "pump", "label": "Condensate Transfer Pumps (1+1)", "design_pressure": "75 barg"}
            ],
            "pipelines": [
                {"tag": "8\"-HC-1001-A1A", "from": "Manifold Amont", "to": "V-101", "diameter": 8, "fluid": "HC", "class": "A1A"},
                {"tag": "6\"-HC-1002-A1A", "from": "V-101", "to": "P-101A/B", "diameter": 6, "fluid": "HC", "class": "A1A"},
                {"tag": "4\"-FG-1003-A1A", "from": "V-101", "to": "HP Flare Header", "diameter": 4, "fluid": "FG", "class": "A1A"}
            ],
            "valves": [
                {"tag": "XV-1001", "type": "control_valve", "pipeline": "8\"-HC-1001-A1A", "fail": "FC", "role": "Emergency Shutdown (ESDV)"},
                {"tag": "LCV-101", "type": "control_valve", "pipeline": "6\"-HC-1002-A1A", "fail": "FC", "role": "Level Control Valve"},
                {"tag": "PSV-101A/B", "type": "psv", "pipeline": "4\"-FG-1003-A1A", "fail": "FO", "role": "Dual Safety Relief Valves (1 Duty + 1 Standby Locked Open)"}
            ],
            "instruments": [
                {"tag": "LT-101", "loop": "101", "type": "Transmetteur de Niveau Radar"},
                {"tag": "LIC-101", "loop": "101", "type": "Contrôleur Indicateur de Niveau DCS"},
                {"tag": "PT-101", "loop": "102", "type": "Transmetteur de Pression"},
                {"tag": "PIC-101", "loop": "102", "type": "Contrôleur de Pression DCS"}
            ]
        },
        {
            "prompt": "Concevoir le P&ID d'une gare de racleurs (Pig Launcher / Scraper Trap) 12\" classe 600 pour oléoduc / gazoduc.",
            "equipments": [
                {"tag": "PL-201", "type": "pig_launcher", "label": "12\" Main Line Pig Launcher", "design_pressure": "95 barg", "design_temp": "60 °C"}
            ],
            "pipelines": [
                {"tag": "12\"-HC-2001-D1A", "from": "Ligne Principale", "to": "PL-201", "diameter": 12, "fluid": "HC", "class": "D1A"},
                {"tag": "4\"-HC-2002-D1A", "from": "Ligne de Kicker", "to": "PL-201", "diameter": 4, "fluid": "HC", "class": "D1A"},
                {"tag": "2\"-HC-2003-D1A", "from": "PL-201", "to": "Ligne de Purge / Vent", "diameter": 2, "fluid": "HC", "class": "D1A"}
            ],
            "valves": [
                {"tag": "MOV-2001", "type": "gate", "pipeline": "12\"-HC-2001-D1A", "role": "Isolation Trap Motorisée"},
                {"tag": "HV-2002", "type": "ball", "pipeline": "4\"-HC-2002-D1A", "role": "Vanne de Kicker"},
                {"tag": "PSV-201", "type": "psv", "pipeline": "2\"-HC-2003-D1A", "role": "Soupape Thermique Trap"}
            ],
            "instruments": [
                {"tag": "PIG-SIG-201", "loop": "201", "type": "Détecteur de Passage Racleur Bidirectionnel"},
                {"tag": "PI-201", "loop": "202", "type": "Manomètre Local avec vanne d'isolement et purge DBB"}
            ]
        },
        {
            "prompt": "Concevoir le P&ID d'une tête de puits de production (Wellhead Christmas Tree) avec injection d'inhibiteur de corrosion et vanne de sécurité de fond (SSSV).",
            "equipments": [
                {"tag": "X-TREE-01", "type": "wellhead", "label": "Christmas Tree Tête de Puits", "design_pressure": "345 barg (5000 psi)"}
            ],
            "pipelines": [
                {"tag": "4\"-HC-3001-API5K", "from": "Tubing Puits", "to": "Flowline Collecte", "diameter": 4, "fluid": "HC", "class": "API5K"},
                {"tag": "1/2\"-CI-3002-316L", "from": "Skid Injection Chimique", "to": "Tête de Puits", "diameter": 0.5, "fluid": "CI", "class": "316L"}
            ],
            "valves": [
                {"tag": "SSSV-01", "type": "surface_safety", "pipeline": "Fond de puits", "role": "Subsurface Safety Valve (Hydraulique fail-close)"},
                {"tag": "WV-01", "type": "wing_valve", "pipeline": "4\"-HC-3001-API5K", "role": "Production Wing Valve Hydraulique"},
                {"tag": "CHOKE-01", "type": "choke", "pipeline": "4\"-HC-3001-API5K", "role": "Duse de Régulation Réglable"}
            ],
            "instruments": [
                {"tag": "PT-301", "loop": "301", "type": "Transmetteur Pression Tête de Puits"},
                {"tag": "TT-301", "loop": "302", "type": "Transmetteur Température Tête de Puits"}
            ]
        }
    ]

    for arch in archetypes:
        dataset.append({
            "instruction": arch["prompt"],
            "input": "Conception P&ID selon standards Sonatrach / ASME B31.3 / ISA-5.1",
            "output": json.dumps({
                "equipments": arch["equipments"],
                "pipelines": arch["pipelines"],
                "valves": arch["valves"],
                "instruments": arch["instruments"]
            }, ensure_ascii=False, indent=2),
            "source": "Standard EPC Archetype"
        })

    # Sauvegarde du dataset
    dataset_file = Path("data/training_pid_dataset.jsonl")
    with open(dataset_file, "w", encoding="utf-8") as f:
        for entry in dataset:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
    logger.info(f"Dataset de fine-tuning généré : {len(dataset)} paires d'entraînement sauvegardées dans {dataset_file}.")
    return dataset_file, len(dataset)

if __name__ == "__main__":
    out_file, count = build_pid_training_dataset()
    print(f"\n=== DATASET P&ID GÉNÉRÉ AVEC SUCCÈS ===")
    print(f"Fichier : {out_file}")
    print(f"Nombre de paires d'entraînement : {count}")
