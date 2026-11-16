"""
benchmark_industrial_pid.py
===========================
Banc d'essai et de validation du nouveau pipeline P&ID (Option A) :
DXF/DWG -> JSON Sémantique Topologique -> Routeur Orthogonal -> SVG ISA-5.1
sur l'ensemble des plans industriels réels de C:\\Users\\MSI\\Desktop\\PID\\NATIVE.
"""

import datetime
import json
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

# Assurer l'encodage UTF-8 sous Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s"
)
logger = logging.getLogger("benchmark")

# Importer les composants du moteur
import dwg_converter
import dxf_to_pid_json
import pid_orthogonal_router
import pid_schematic_engine


def run_benchmark():
    native_dir = Path(r"C:\Users\MSI\Desktop\PID\NATIVE")
    output_dir = Path(r"D:\DATA BASE IA\schematic_output")
    output_dir.mkdir(parents=True, exist_ok=True)

    dwg_files = sorted(list(native_dir.glob("*.dwg")))
    logger.info(f"Trouvé {len(dwg_files)} fichiers DWG dans {native_dir}")

    results = []

    for idx, dwg_path in enumerate(dwg_files, 1):
        plan_name = dwg_path.stem
        logger.info(f"[{idx}/{len(dwg_files)}] Traitement de : {dwg_path.name} ({dwg_path.stat().st_size / 1024:.1f} KB)...")

        t0 = time.time()
        record = {
            "plan_name": dwg_path.name,
            "stem": plan_name,
            "size_kb": round(dwg_path.stat().st_size / 1024, 1),
            "status": "PENDING",
            "error": None,
        }

        try:
            # 1. Conversion DWG -> DXF
            dxf_path = dwg_converter.convert_dwg_to_dxf(str(dwg_path))
            t_dxf = time.time()
            record["dxf_conversion_time_s"] = round(t_dxf - t0, 2)
            logger.info(f"   -> DXF prêt en {record['dxf_conversion_time_s']}s : {Path(dxf_path).name}")

            # 2. Rendu complet : DXF -> JSON Topologique -> Routage Orthogonal -> SVG ISA-5.1
            out_svg = output_dir / f"{plan_name}.svg"
            out_json = output_dir / f"{plan_name}.json"

            svg_str = pid_schematic_engine.render_dxf_to_schematic(
                dxf_path=dxf_path,
                out_svg_path=out_svg,
                out_json_path=out_json,
                canvas_w=1600.0,
                canvas_h=1000.0,
            )
            t_render = time.time()
            record["pipeline_time_s"] = round(t_render - t_dxf, 2)
            record["total_time_s"] = round(t_render - t0, 2)

            # 3. Validation XML du SVG généré
            try:
                tree = ET.parse(str(out_svg))
                root = tree.getroot()
                svg_elem_count = len(list(root.iter()))
                record["svg_valid"] = True
                record["svg_element_count"] = svg_elem_count
                record["svg_size_kb"] = round(out_svg.stat().st_size / 1024, 1)
            except Exception as e_xml:
                record["svg_valid"] = False
                record["svg_error"] = str(e_xml)
                logger.error(f"   [!] Erreur XML SVG pour {plan_name}: {e_xml}")

            # 4. Analyse du JSON sémantique topologique
            with open(out_json, "r", encoding="utf-8") as jf:
                dt_data = json.load(jf)

            record["json_valid"] = True
            record["json_size_kb"] = round(out_json.stat().st_size / 1024, 1)

            top_sum = dt_data.get("topology_summary", {})
            record["total_equipments"] = top_sum.get("total_equipments", 0)
            record["connected_equipments"] = top_sum.get("connected_equipments", 0)
            record["isolated_equipments"] = top_sum.get("isolated_equipments", 0)
            record["connectivity_ratio"] = top_sum.get("connectivity_ratio", 0.0)

            record["total_circuits"] = top_sum.get("total_circuits", 0)
            record["complete_circuits"] = top_sum.get("complete_circuits", 0)
            record["open_circuits"] = top_sum.get("open_circuits", 0)

            record["total_valves"] = top_sum.get("total_valves", 0)
            record["valves_with_tag"] = top_sum.get("valves_with_tag", 0)
            record["valves_without_tag"] = top_sum.get("valves_without_tag", 0)

            record["total_instruments"] = top_sum.get("total_instruments", 0)
            record["total_loops"] = top_sum.get("total_loops", 0)
            record["complete_loops"] = top_sum.get("complete_loops", 0)

            # Vérifier les hops dans le SVG généré
            import re
            m_hops = re.search(r'Sauts \(⌒\) : <tspan[^>]*>(\d+)</tspan>', svg_str)
            record["total_hops"] = int(m_hops.group(1)) if m_hops else top_sum.get("total_hops", 0)

            record["status"] = "SUCCESS"
            logger.info(
                f"   [OK] {plan_name} : {record['total_equipments']} Eq (ratio {record['connectivity_ratio']}), "
                f"{record['total_circuits']} Cir, {record['total_valves']} Van, {record['total_hops']} Hops, "
                f"SVG valide ({record['svg_element_count']} noeuds)"
            )

        except Exception as exc:
            record["status"] = "FAILED"
            record["error"] = f"{type(exc).__name__}: {str(exc)}"
            logger.error(f"   [ECHEC] Erreur sur {plan_name}: {exc}", exc_info=True)

        results.append(record)

    # Sauvegarde des résultats
    summary_path = output_dir / "benchmark_summary.json"
    summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"\nRapport complet écrit dans : {summary_path}")

    # Affichage du tableau récapitulatif Markdown
    print("\n" + "=" * 115)
    print("TABLEAU RECAPITULATIF DE VALIDATION DU NOUVEAU PIPELINE P&ID (OPTION A)")
    print("=" * 115)
    header = f"| {'Nom du Plan':<32} | {'Eq (Co/Tot)':<12} | {'Ratio':<7} | {'Circuits':<10} | {'Vannes':<10} | {'Inst':<6} | {'Sauts (⌒)':<9} | {'SVG & JSON':<12} | {'Temps':<7} |"
    sep = f"|{'-'*34}|{'-'*14}|{'-'*9}|{'-'*12}|{'-'*12}|{'-'*8}|{'-'*11}|{'-'*14}|{'-'*9}|"
    print(header)
    print(sep)

    for r in results:
        p_name = r["plan_name"]
        if len(p_name) > 32:
            p_name = p_name[:29] + "..."
        if r["status"] == "SUCCESS":
            eq_str = f"{r['connected_equipments']}/{r['total_equipments']}"
            ratio_str = f"{r['connectivity_ratio']*100:.0f}%" if r['total_equipments'] > 0 else "N/A"
            cir_str = str(r["total_circuits"])
            van_str = f"{r['total_valves']} ({r['valves_with_tag']}t)"
            inst_str = str(r["total_instruments"])
            hops_str = str(r["total_hops"])
            status_str = f"OK ({r['svg_element_count']})"
            time_str = f"{r['total_time_s']}s"
        else:
            eq_str = "ERR"
            ratio_str = "ERR"
            cir_str = "ERR"
            van_str = "ERR"
            inst_str = "ERR"
            hops_str = "ERR"
            status_str = f"FAIL"
            time_str = "-"

        row = f"| {p_name:<32} | {eq_str:<12} | {ratio_str:<7} | {cir_str:<10} | {van_str:<10} | {inst_str:<6} | {hops_str:<9} | {status_str:<12} | {time_str:<7} |"
        print(row)
    print("=" * 115)


if __name__ == "__main__":
    run_benchmark()
