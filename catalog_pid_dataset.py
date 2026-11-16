import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PID_Cataloger")

def detect_project_and_discipline(filename: str) -> Dict[str, str]:
    fn = filename.upper()
    project = "Autre / Référence"
    discipline = "P&ID"
    
    # Détection Projet
    if "C1124" in fn:
        project = "Projet C1124 (GCB / Sonatrach)"
    elif "C1125" in fn or "REDCO" in fn:
        project = "Projet C1125 (REDCO)"
    elif "C2025-ROH" in fn or "ROH1" in fn:
        project = "Projet C2025-ROH1 (Rhourde Oulad Hadda)"
    elif "GHBR" in fn or "DZ-GHBR" in fn:
        project = "Projet DZ-GHBR (Gassi Touil / Rhourde El Baguel)"
    elif "C3321" in fn or "GGE" in fn:
        project = "Projet C3321-GGE"
    elif "C3421" in fn or "ROK1" in fn:
        project = "Projet C3421-ROK1 (Rhourde Oulad Kechkeche)"
    elif "C7521" in fn:
        project = "Projet C7521-GCB"
    elif "C2121" in fn:
        project = "Projet C2121-GCB"
    elif "C0322" in fn:
        project = "Projet C0322-GCB"
    elif "C9521" in fn:
        project = "Projet C9521-GCB"
    elif "TRHT" in fn or "08572" in fn:
        project = "Projet 08572-TRHT (Touat Gaz / Sonatrach)"
    elif "ATEL" in fn:
        project = "Modèles d'Ingénierie & Procédés (Aspen HYSYS)"
    elif "WELL" in fn:
        project = "Têtes de Puits & Collecteurs"
    elif "PIG" in fn:
        project = "Gares de Racleurs (Scraper Traps)"
    elif "BVS" in fn:
        project = "Postes de Sectionnement (BVS)"

    # Détection Discipline / Type
    if "PID" in fn or "-DC-" in fn:
        discipline = "P&ID (Tuyauterie & Instrumentation)"
    elif "PFD" in fn or "-DA-" in fn:
        discipline = "PFD (Schéma de Procédé)"
    elif "UFD" in fn or "-DB-" in fn:
        discipline = "UFD (Schéma des Utilités)"
    elif "LGD" in fn or "LEGEND" in fn:
        discipline = "Légende & Symboles ISA"
    elif "LIS" in fn or "LST" in fn or "LINE" in fn:
        discipline = "Line List (Inventaire de Lignes)"
    elif "ESD" in fn or "SAFETY" in fn:
        discipline = "ESD / Sécurité & Arrêt d'Urgence"
    elif "BOD" in fn:
        discipline = "BOD (Basis of Design)"
    elif "DTS" in fn or "DATA" in fn:
        discipline = "DTS (Spécifications Techniques)"
    elif "PLA" in fn:
        discipline = "Plan d'Implantation / Layout"

    return {"project": project, "discipline": discipline}

def build_pid_catalog():
    target_dirs = [
        Path("data/DATASET_PID"),
        Path("data/ROK1_PID")
    ]
    
    catalog: List[Dict[str, Any]] = []
    projects_stats: Dict[str, Dict[str, int]] = {}
    
    for base_dir in target_dirs:
        if not base_dir.exists():
            continue
            
        for file_path in base_dir.rglob("*"):
            if file_path.suffix.lower() in [".pdf", ".dwg", ".dxf"]:
                info = detect_project_and_discipline(file_path.name)
                proj = info["project"]
                disc = info["discipline"]
                
                if proj not in projects_stats:
                    projects_stats[proj] = {"total": 0, "pdf": 0, "dwg": 0, "dxf": 0}
                
                ext = file_path.suffix.lower().replace(".", "")
                projects_stats[proj]["total"] += 1
                if ext in projects_stats[proj]:
                    projects_stats[proj][ext] += 1
                    
                entry = {
                    "filename": file_path.name,
                    "filepath": str(file_path).replace("\\", "/"),
                    "project": proj,
                    "discipline": disc,
                    "extension": ext,
                    "size_kb": round(file_path.stat().st_size / 1024, 1)
                }
                catalog.append(entry)
                
    output_path = Path("data/pid_catalog.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "total_plans": len(catalog),
            "projects_summary": projects_stats,
            "plans": catalog
        }, f, ensure_ascii=False, indent=2)
        
    logger.info("Catalogue PID généré avec succès dans %s (%d plans répertoriés)", output_path, len(catalog))
    return catalog, projects_stats

if __name__ == "__main__":
    catalog, stats = build_pid_catalog()
    print(f"\n=== CATALOGUE PLANS P&ID D'INGÉNIERIE ===")
    print(f"Total des plans indexés : {len(catalog)}")
    print("\nRépartition par Projet :")
    for proj, s in stats.items():
        print(f"  • {proj:50s} : {s['total']:3d} plans (PDF: {s['pdf']:2d}, DWG: {s['dwg']:2d})")
