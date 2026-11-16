import os
import sys
import glob
import json
import math
import re
import traceback
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.abspath("."))

from pid_analyzer import parse_pid_pdf, _categorize_and_enrich_elements
from fluid_flow_agent import FluidFlowReasoningAgent
from piping_topology_tracer import parse_line_tag

def run_audit_on_plan(pdf_path: str):
    filename = os.path.basename(pdf_path)
    print(f"\n=======================================================")
    print(f"AUDITING: {filename}")
    print(f"=======================================================")
    
    try:
        res = parse_pid_pdf(pdf_path, output_image_dir="generated_visuals", discipline="pid")
    except Exception as e:
        print(f"[FATAL ERROR] parse_pid_pdf failed on {filename}: {e}")
        traceback.print_exc()
        return {"filename": filename, "status": "CRASH", "error": str(e)}

    elements = res.get("elements", [])
    raw_lines = res.get("lines", [])
    
    # 1. Consolidate lines using FluidFlowReasoningAgent
    agent = FluidFlowReasoningAgent()
    consolidated_lines = agent.process_and_validate_lines(raw_lines, [])
    
    # 2. Component-to-line spatial association
    for el in elements:
        tag = el.get("tag", "")
        curr_line = el.get("line", "")
        if not curr_line or "Non associé" in curr_line or curr_line == tag:
            matched_line = None
            matched_pipe = None
            # Check direct pipe membership
            for pipe in consolidated_lines:
                p_valves = pipe.get("valves", [])
                p_comps = [c.get("tag") if isinstance(c, dict) else str(c) for c in pipe.get("line_components", [])]
                if tag in p_valves or tag in p_comps:
                    matched_line = pipe.get("line_number", "")
                    matched_pipe = pipe
                    break
            # Check geometric proximity
            if not matched_line:
                box = el.get("box", [0, 0, 0, 0])
                cx = (box[0] + box[2]) / 2 if box else 0
                cy = (box[1] + box[3]) / 2 if box else 0
                if cx and cy:
                    best_dist = float('inf')
                    for pipe in consolidated_lines:
                        for seg in pipe.get("path_coords", []):
                            if len(seg) >= 4:
                                x1, y1, x2, y2 = seg[:4]
                                dx, dy = x2 - x1, y2 - y1
                                d = math.hypot(cx - x1, cy - y1) if dx == 0 and dy == 0 else \
                                    math.hypot(cx - (x1 + max(0, min(1, ((cx - x1)*dx + (cy - y1)*dy)/(dx*dx + dy*dy)))*dx),
                                               cy - (y1 + max(0, min(1, ((cx - x1)*dx + (cy - y1)*dy)/(dx*dx + dy*dy)))*dy))
                                if d < best_dist and d <= 80.0:
                                    best_dist = d
                                    matched_line = pipe.get("line_number", "")
                                    matched_pipe = pipe
            if matched_line:
                el["line"] = matched_line
                if matched_pipe and tag and tag not in matched_pipe.setdefault("valves", []):
                    if any(p in tag.upper() for p in ("HV", "XV", "CV", "CH", "JI", "MOV", "SDV", "BDV")):
                        matched_pipe["valves"].append(tag)

    # 3. Categorize
    categorized = _categorize_and_enrich_elements(elements, [], [])
    valves = categorized.get("valves", [])
    instruments = categorized.get("instruments", [])
    equipment = categorized.get("equipment", [])
    cross_refs = categorized.get("cross_references", [])
    
    # 4. Analyze quality metrics & detect flaws
    flaws = []
    
    # Audit lines
    invalid_lines = []
    for l in consolidated_lines:
        ltag = l.get("line_number", "")
        # Check if line tag is invalid (e.g. single number or missing fluid)
        parsed = parse_line_tag(ltag)
        if not parsed:
            invalid_lines.append(ltag)
            flaws.append(f"Invalid line tag: '{ltag}'")
        elif parsed.get("fluid", "-") in ("-", "") and "EXISTANT" not in ltag.upper():
            invalid_lines.append(ltag)
            flaws.append(f"Line tag has no valid fluid code: '{ltag}'")

    # Check for duplicate phantom tags (e.g. HV-100 when 100-HV-001 exists)
    all_tags = [e.get("tag", "") for e in elements]
    area_prefixed = [t for t in all_tags if re.match(r'^\d{2,4}-[A-Z]{1,4}-\d+', t)]
    for ap in area_prefixed:
        m = re.match(r'^\d{2,4}-([A-Z]{1,4})-(\d+)', ap)
        if m:
            phantom = f"{m.group(1)}-{m.group(2)}"
            if phantom in all_tags and phantom != ap:
                flaws.append(f"Phantom duplicate tag found: '{phantom}' alongside '{ap}'")

    # Audit component association rate
    total_physical = len(valves) + len(instruments)
    associated = sum(1 for c in (valves + instruments) if c.get("line") and "Non associé" not in c.get("line") and c.get("line") != c.get("tag"))
    assoc_rate = (associated / total_physical * 100.0) if total_physical > 0 else 100.0

    print(f"-> Lines extracted: {len(consolidated_lines)} (Invalid: {len(invalid_lines)})")
    for l in consolidated_lines[:8]:
        print(f"   Line: {l['line_number']:28} | DN: {l.get('size_dn',''):6} | Fluid: {l.get('fluid',''):4} | {l.get('from_equipment','')} -> {l.get('to_equipment','')}")
    if len(consolidated_lines) > 8:
        print(f"   ... (+{len(consolidated_lines)-8} lines)")

    print(f"-> Physical Components: {total_physical} (Valves: {len(valves)}, Instruments: {len(instruments)}, Equipment: {len(equipment)})")
    print(f"-> Line Association Rate: {associated}/{total_physical} ({assoc_rate:.1f}%)")
    print(f"-> Cross References / OPCs: {len(cross_refs)}")
    if flaws:
        print(f"-> FLAWS DETECTED ({len(flaws)}):")
        for f in flaws[:5]:
            print(f"   [!] {f}")
        if len(flaws) > 5:
            print(f"   ... (+{len(flaws)-5} more)")
    else:
        print("-> [OK] No anomalies or fake entities detected!")

    return {
        "filename": filename,
        "status": "PASS" if not flaws and assoc_rate >= 75.0 else "WARN",
        "lines_count": len(consolidated_lines),
        "valves_count": len(valves),
        "instruments_count": len(instruments),
        "equipment_count": len(equipment),
        "cross_refs_count": len(cross_refs),
        "assoc_rate": round(assoc_rate, 1),
        "flaws": flaws
    }

if __name__ == "__main__":
    pdf_dir = r"C:\Users\MSI\Desktop\pid\PDF"
    pdf_files = sorted(glob.glob(os.path.join(pdf_dir, "*.pdf")))
    print(f"Found {len(pdf_files)} PDF plans to audit in {pdf_dir}")
    
    results = []
    for pdf_p in pdf_files:
        r = run_audit_on_plan(pdf_p)
        results.append(r)
        
    print("\n" + "="*70)
    print("SUMMARY AUDIT ACROSS ALL PLANS")
    print("="*70)
    for r in results:
        status_str = f"[{r['status']}]"
        print(f"{status_str:8} {r['filename']:40} | Lines: {r.get('lines_count', 0):2d} | Comps: {r.get('valves_count',0)+r.get('instruments_count',0):3d} | Assoc: {r.get('assoc_rate',0)}% | Flaws: {len(r.get('flaws',[]))}")
    
    # Save results to json
    with open("audit_full_report.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nFull audit written to audit_full_report.json")
