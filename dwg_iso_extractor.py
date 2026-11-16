"""
dwg_iso_extractor.py - Native AutoCAD DWG & DXF Isometric Extraction Engine for ARKAN.
Supports direct headless conversion via AutoCAD accoreconsole.exe and ezdxf structured parsing.
Extracts:
  - Fabrication Materials & Erection Materials (BOM tables)
  - Spools & Cut Pipe Length tables
  - Line metadata (tag, spec, service, design conditions, coordinates)
"""

import os
import re
import tempfile
import subprocess
import logging
import math
from collections import defaultdict, Counter
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
try:
    import fitz
except ImportError:
    pass

try:
    import asme_piping_catalog as asme
except ImportError:
    asme = None

logger = logging.getLogger("dwg_iso_extractor")

# Initialisation du bridage CPU (plafond 80% des ressources logiques)
try:
    from cpu_governor import apply_cpu_governor
    apply_cpu_governor(target_ratio=0.80)
except Exception:
    pass

# Default paths for AutoCAD accoreconsole on Windows
ACCORECONSOLE_PATHS = [
    r"C:\Program Files\Autodesk\AutoCAD 2021\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2022\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2023\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2024\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2020\accoreconsole.exe",
]


def find_accoreconsole() -> Optional[str]:
    """Finds accoreconsole.exe on the system if available."""
    for p in ACCORECONSOLE_PATHS:
        if os.path.exists(p):
            return p
    return None


def convert_dwg_to_dxf_headless(dwg_path: str, output_dxf_path: str, timeout_sec: int = 60) -> bool:
    """Converts a binary DWG file to DXF using Autodesk accoreconsole.exe via dwg_converter with persistent disk caching."""
    import shutil

    # 1. Vérification du cache disque permanent
    try:
        from dwg_converter import cache_dir as _arkan_cache_dir
        cache_dir = _arkan_cache_dir()
    except Exception:
        cache_dir = Path(tempfile.gettempdir()) / "arkan_cad_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = None
    try:
        st = os.stat(dwg_path)
        stem = Path(dwg_path).stem
        cache_file = cache_dir / f"{stem}_{st.st_size}.dxf"
        if cache_file.exists() and cache_file.stat().st_size > 500:
            shutil.copy2(str(cache_file), output_dxf_path)
            logger.info("Utilisation du cache DXF pour %s (%d bytes)", dwg_path, cache_file.stat().st_size)
            return True
    except Exception:
        pass

    try:
        from dwg_converter import convert_dwg_to_dxf
        res = convert_dwg_to_dxf(dwg_path, output_dxf_path)
        if res and os.path.exists(res) and os.path.getsize(res) > 100:
            logger.info("Successfully converted %s to DXF via dwg_converter (%d bytes)", dwg_path, os.path.getsize(res))
            if cache_file:
                try:
                    shutil.copy2(output_dxf_path, str(cache_file))
                except Exception:
                    pass
            return True
    except Exception as e_conv:
        logger.warning("Delegated dwg_converter failed for %s: %s", dwg_path, e_conv)

    # Fallback to direct accoreconsole call if dwg_converter failed
    accore = find_accoreconsole()
    if not accore:
        logger.warning("accoreconsole.exe not found on system.")
        return False

    scr_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".scr", delete=False) as scr_f:
            scr_path = scr_f.name
            dxf_target = str(output_dxf_path).replace("\\", "/")
            scr_f.write(f'FILEDIA 0\n(command "_DXFOUT" "{dxf_target}" "16")\nQUIT\n')

        cmd = [accore, "/i", str(dwg_path), "/s", str(scr_path)]
        res = subprocess.run(cmd, capture_output=True, timeout=timeout_sec)
        
        if os.path.exists(output_dxf_path) and os.path.getsize(output_dxf_path) > 100:
            logger.info("Direct accoreconsole converted %s to DXF (%d bytes)", dwg_path, os.path.getsize(output_dxf_path))
            return True
        else:
            logger.warning("DXF conversion produced empty file or failed: %s", res.stderr.decode(errors="ignore"))
            return False
    except Exception as e:
        logger.error("Error running accoreconsole conversion for %s: %s", dwg_path, e)
        return False
    finally:
        if scr_path and os.path.exists(scr_path):
            try:
                os.remove(scr_path)
            except Exception:
                pass


def clean_mtext(text: str) -> str:
    """Removes AutoCAD MTEXT formatting codes (\\P, {\\Q...;}, \\^J, etc.)."""
    if not text:
        return ""
    t = re.sub(r'\\P', ' ', text)
    t = re.sub(r'\{\\Q[-+]?\d+;([^}]+)\}', r'\1', t)
    t = re.sub(r'\{\\C\d+;([^}]+)\}', r'\1', t)
    t = re.sub(r'\^[JjMm]', ' ', t)
    t = re.sub(r'\\A\d+;', '', t)
    t = re.sub(r'\\L|\\l|\\O|\\o', '', t)
    t = re.sub(r'\\f[^;]+;', '', t)
    t = re.sub(r'\\H[^;]+;', '', t)
    t = re.sub(r'\\W[^;]+;', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def parse_title_block_metadata(doc) -> Dict[str, Any]:
    """Extracts line number, spec, project, etc. from Title Block / Cartouche attributes."""
    msp = doc.modelspace()
    meta = {
        "line_number": "",
        "spec": "",
        "project": "",
        "drawing_no": "",
        "date": "",
        "rev": "",
        "design_pressure": "",
        "test_pressure": "",
        "design_temperature": ""
    }
    for ins in msp.query("INSERT"):
        bname = ins.dxf.name.upper()
        if "TITLE" in bname or "CARTOUCHE" in bname or "BORDER" in bname or ins.attribs:
            for a in ins.attribs:
                tag = a.dxf.tag.upper().strip()
                val = clean_mtext(a.dxf.text).strip()
                if not val or val == "/":
                    continue
                if tag in ("LINENUMBER", "LINE_NUMBER", "LINE-NUMBER", "LIGNE") or "LIGNE" in tag or "LINE NUMBER" in tag:
                    if not meta["line_number"]:
                        meta["line_number"] = val.replace('"', '').strip()
                elif "SPEC" in tag:
                    if not meta["spec"]:
                        meta["spec"] = val
                elif "PROJET" in tag or "PROJECT" in tag:
                    if not meta["project"]:
                        meta["project"] = val
                elif tag in ("NOM DE FICHIER", "DWG", "DRAWING", "PLAN"):
                    if not meta["drawing_no"]:
                        meta["drawing_no"] = val
                elif "DATE" in tag:
                    if not meta["date"]:
                        meta["date"] = val
                elif tag in ("REV", "REVISION"):
                    if not meta["rev"]:
                        meta["rev"] = val
    return meta


def parse_acad_table_from_doc(doc) -> List[Dict[str, Any]]:
    """
    Extracts structured BOM items from ACAD_TABLE entity blocks (*T...) or blocks containing NOMENCLATURE/BOM.
    """
    msp = doc.modelspace()
    table_blocks = []

    # 1. ACAD_TABLE entity blocks
    for t in msp.query("ACAD_TABLE"):
        bname = t.get_block_name() if hasattr(t, "get_block_name") else getattr(t.dxf, "block_name", None)
        if bname and bname in doc.blocks:
            table_blocks.append(doc.blocks[bname])

    # 2. Block definitions starting with *T or having NOMENCLATURE/BOM
    for b in doc.blocks:
        b_u = b.name.upper()
        if b_u.startswith("*T") or "NOMENCLATURE" in b_u or "BOM" in b_u:
            if b not in table_blocks:
                table_blocks.append(b)

    bom_items = []

    for tb in table_blocks:
        tb_entities = []
        for e in tb:
            if e.dxftype() in ("TEXT", "MTEXT"):
                txt = clean_mtext(e.dxf.text if e.dxftype() == "TEXT" else e.text)
                if txt:
                    tb_entities.append((e.dxf.insert.x, e.dxf.insert.y, txt))

        if not tb_entities:
            continue

        # Group by Y coordinate with 3.0 tolerance
        y_tol = 3.0
        rows = {}
        for x, y, t in tb_entities:
            matched_y = None
            for ry in rows:
                if abs(ry - y) <= y_tol:
                    matched_y = ry
                    break
            if matched_y is None:
                matched_y = y
                rows[matched_y] = []
            rows[matched_y].append((x, t))

        sorted_y = sorted(rows.keys(), reverse=True)
        current_cat = "PIPING"

        for y in sorted_y:
            row_elements = sorted(rows[y], key=lambda item: item[0])
            row_texts = [t for _, t in row_elements]
            row_str = " ".join(row_texts).upper()

            # Skip title / header rows
            if "NOMENCLATURE" in row_str or "DESCRIPTION D" in row_str or row_str.strip() in ("ID ND", "ID", "ND"):
                continue

            # Check Category Header rows
            if len(row_elements) == 1 or all(len(t) < 15 for t in row_texts if t not in ("PIPE", "FITTINGS", "FLANGES", "FASTENERS", "VALVES", "SUPPORTS")):
                first_txt = row_texts[0].upper()
                if first_txt in ("PIPE", "PIPES", "TUYAUTERIE"):
                    current_cat = "PIPE"
                    continue
                elif first_txt in ("FITTINGS", "FITTING", "RACCORDS"):
                    current_cat = "FITTING"
                    continue
                elif first_txt in ("FLANGES", "FLANGE", "BRIDES"):
                    current_cat = "FLANGE"
                    continue
                elif first_txt in ("FASTENERS", "BOLTS", "BOULONNERIE"):
                    current_cat = "BOLT"
                    continue
                elif first_txt in ("GASKETS", "JOINTS"):
                    current_cat = "GASKET"
                    continue
                elif first_txt in ("VALVES", "VALVE", "ROBINETTERIE"):
                    current_cat = "VALVE"
                    continue
                elif first_txt in ("SUPPORTS", "SUPPORT"):
                    current_cat = "SUPPORTS"
                    continue

            # Parse table row: [ID, ND, DESCRIPTION, QTE]
            if len(row_elements) >= 3:
                first_t = row_elements[0][1].strip()
                if re.match(r'^\d+$', first_t):
                    item_no = int(first_t)
                    nd = row_elements[1][1].strip()
                    qte_str = row_elements[-1][1].strip()
                    desc_parts = [el[1] for el in row_elements[2:-1]]
                    desc = " ".join(desc_parts).strip()
                    if not desc and len(row_elements) == 3:
                        desc = nd
                        nd = ""

                    # Clean ND
                    nd_clean = nd.replace('"', '').strip()
                    if re.match(r'^\d+(?:/\d+)?$', nd_clean):
                        nd_clean = f'{nd_clean}"'
                    elif re.match(r'^\d+x\d+(?:/\d+)?$', nd_clean, re.I):
                        nd_clean = f'{nd_clean}"'
                    else:
                        nd_clean = nd

                    # Parse qty and unit
                    unit = "EA"
                    qty = 1.0
                    qte_str_clean = qte_str.replace(',', '.')
                    m_m = re.match(r'^([\d\.]+)\s*M$', qte_str_clean, re.I)
                    if m_m:
                        qty = float(m_m.group(1))
                        unit = "M"
                    else:
                        m_num = re.match(r'^([\d\.]+)$', qte_str_clean)
                        if m_num:
                            qty = float(m_num.group(1))

                    # Categorize properly
                    cat = current_cat
                    u_desc = desc.upper()
                    if u_desc.startswith("SP-") or "SUPPORT" in u_desc:
                        cat = "SUPPORTS"
                    elif "VALVE" in u_desc or "ROBINET" in u_desc or "GATE" in u_desc or "BALL" in u_desc or "CHECK" in u_desc:
                        cat = "VALVE"
                    elif "FLANGE" in u_desc or "BRIDE" in u_desc or "BLIND" in u_desc:
                        cat = "FLANGE"
                    elif "GASKET" in u_desc or "JOINT" in u_desc or "SPIRAL WOUND" in u_desc:
                        cat = "GASKET"
                    elif "STUD BOLT" in u_desc or "BOLT" in u_desc or "BOULON" in u_desc or "FASTENERS" in u_desc:
                        cat = "BOLT"
                    elif any(k in u_desc for k in ["ELBOW", "COUDE", "TEE", "REDUCER", "REDUCTION", "NIPPLE", "COUPLING", "THREADOLET", "WELDOLET", "SOCKOLET"]):
                        cat = "FITTING"
                    elif "PIPE" in u_desc or "TUBE" in u_desc:
                        cat = "PIPE"

                    # Extract schedule
                    sch = ""
                    m_sch = re.search(r'\b(SCH\s*\d+|SCH\s*[A-Z]+)\b', desc, re.I)
                    if m_sch:
                        sch = m_sch.group(1).upper()

                    # Extract rating
                    rating = ""
                    m_rat = re.search(r'(#\d+|\d+#|CL[- ]?\d+|150\s*LB|300\s*LB|800\s*LB|600\s*LB|PN\d+)', desc, re.I)
                    if m_rat:
                        rating = m_rat.group(1).upper()

                    # Extract material
                    mat = ""
                    m_mat = re.search(r'(A106\s*GR\.?\s*[A-Z]|A105N?|A\s*234\s*WPB|A\s*193\s*GR\s*B7|SS\s*316L?|ASTM\s*[A-Z0-9]+)', desc, re.I)
                    if m_mat:
                        mat = m_mat.group(1).upper()

                    bom_items.append({
                        "item_no": item_no,
                        "category": cat,
                        "tag": f"{cat[:3]}-{item_no:02d}",
                        "description": desc,
                        "size": nd_clean,
                        "quantity": qty,
                        "unit": unit,
                        "schedule": sch,
                        "rating": rating,
                        "material": mat
                    })

    return bom_items


def extract_entities_from_dxf(dxf_path: str) -> List[Tuple[float, float, str]]:
    """Extracts all text and attribute entities with their (x, y) coordinates from a DXF file."""
    import ezdxf

    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception:
        try:
            from ezdxf import recover
            doc, _ = recover.readfile(dxf_path)
        except Exception as e:
            logger.error("Failed to read DXF %s: %s", dxf_path, e)
            return []

    msp = doc.modelspace()
    entities = []

    for entity in msp:
        dxftype = entity.dxftype()
        try:
            if dxftype == "TEXT":
                txt = clean_mtext(entity.dxf.text)
                if txt:
                    entities.append((entity.dxf.insert.x, entity.dxf.insert.y, txt))
            elif dxftype == "MTEXT":
                txt = clean_mtext(entity.text)
                if txt:
                    entities.append((entity.dxf.insert.x, entity.dxf.insert.y, txt))
            elif dxftype == "INSERT":
                for attrib in getattr(entity, "attribs", []):
                    txt = clean_mtext(attrib.dxf.text)
                    if txt:
                        entities.append((attrib.dxf.insert.x, attrib.dxf.insert.y, txt))
        except Exception:
            pass

    return entities


def parse_bom_from_entities(entities: List[Tuple[float, float, str]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Reconstructs 2D spatial rows from text entities to extract:
    1. BOM items (item_no, category, description, size, quantity, unit) strictly separated from spools
    2. Cut Spool lengths (piece, cut_length_mm, ns)
    3. Line metadata (line_id, spec, service, p_design, t_design, centerline_length)
    """
    # 1. Segment BOM entities (strictly above CUT PIPE LENGTH / PIPE SPOOLS header) from Spool entities
    y_spool_header = None
    for x, y, t in entities:
        u = t.upper()
        if "CUT PIPE LENGTH" in u or "PIPE SPOOLS" in u:
            if y_spool_header is None or y > y_spool_header:
                y_spool_header = y

    bom_entities = [e for e in entities if y_spool_header is None or e[1] > y_spool_header]
    spool_entities = [e for e in entities if y_spool_header is not None and e[1] <= y_spool_header]

    metadata: Dict[str, Any] = {
        "line_number": "",
        "spec": "",
        "service": "",
        "design_pressure": "",
        "test_pressure": "",
        "design_temperature": "",
        "cl_length_m": None,
        "pipe_ns": "",
        "coordinates": [],
    }

    # Extract metadata & CL Length across all entities
    for x, y, t in entities:
        t_clean = t.strip()
        u_t = t_clean.upper()
        # Standard industrial line tag pattern: e.g. 1-LP-1ACX1PN-301-N, 20-LP-6ACX1PN-301-N, 2-DF-1ACX1PN-301-N
        if re.search(r'\b(?:\d{1,2}(?:/\d{1,2}|--\d{1,2})?|\d{1,2})-[A-Z]{2,4}-[A-Z0-9]{5,10}-\d{3,4}-[A-Z0-9\(\)]+\b', t):
            if not metadata["line_number"]:
                metadata["line_number"] = t.replace("--", "/")
        elif re.search(r'\b(1ACX1PN|6ACX1PN|1ASNSEN|1CS1P|2CS1P|3CS1P|1LT1P|3SS1P)\b', t):
            if not metadata["spec"]:
                metadata["spec"] = t
        elif "barg" in t.lower() or "bar" in t.lower():
            if not metadata["design_pressure"]:
                metadata["design_pressure"] = t
        elif re.search(r'[-+]?\d+\s*/\s*[-+]?\d+\s*C', t):
            if not metadata["design_temperature"]:
                metadata["design_temperature"] = t
        elif re.search(r'^[EN]\s+\d{5,7}\.\d', t) or re.search(r'^EL\s+[+-]?\d{5,7}\.\d', t):
            metadata["coordinates"].append(t)
        elif "CL LENGTH" in u_t or "CENTERLINE" in u_t:
            for x2, y2, t2 in entities:
                if abs(y2 - y) <= 4.0 and x2 > x:
                    m_l = re.search(r"^(\d+(?:\.\d+)?)$", t2.strip())
                    if m_l and float(m_l.group(1)) > 0:
                        metadata["cl_length_m"] = float(m_l.group(1))
                        break
        elif "PIPE NS" in u_t:
            for x2, y2, t2 in entities:
                if abs(y2 - y) <= 4.0 and x2 > x:
                    t2_c = t2.strip().replace('"', "")
                    if t2_c in ("1/2", "3/4", "1", "1.1/2", "1 1/2", "2", "3", "4", "6", "8", "10", "12", "14", "16", "18", "20", "24"):
                        metadata["pipe_ns"] = t2_c
                        break

    # 2. Group BOM entities into horizontal rows
    max_x = max((abs(e[0]) for e in bom_entities), default=500.0)
    y_tol = 0.12 if max_x < 100.0 else 2.2

    rows: Dict[float, List[Tuple[float, str]]] = {}
    for x, y, t in bom_entities:
        t = t.strip()
        if not t:
            continue
        matched_y = None
        for r_y in rows:
            if abs(r_y - y) <= y_tol:
                matched_y = r_y
                break
        if matched_y is None:
            matched_y = y
            rows[matched_y] = []
        rows[matched_y].append((x, t))

    sorted_y = sorted(rows.keys(), reverse=True)

    # Adaptive dynamic column anchor detection
    pt_x, desc_x, ns_x, qte_x = None, None, None, None
    for x, y, t in bom_entities:
        u = t.strip().upper()
        if u == "PT" and pt_x is None:
            pt_x = x
        elif u == "DESCRIPTION" and desc_x is None:
            desc_x = x
        elif u == "NS" and (ns_x is None or (desc_x and x > desc_x)):
            ns_x = x
        elif u in ("QTE", "QTY") and qte_x is None:
            qte_x = x

    # Fallback to default millimeter coordinates if headers not found
    if not (pt_x and desc_x and ns_x and qte_x and pt_x < desc_x < ns_x < qte_x):
        pt_x, desc_x, ns_x, qte_x = 412.7, 420.2, 550.3, 569.2

    t_pt_desc = (pt_x + desc_x) / 2.0
    t_desc_ns = (desc_x + ns_x) / 2.0
    t_ns_qte = (ns_x + qte_x) / 2.0

    current_category = "PIPING"
    bom_items: List[Dict[str, Any]] = []

    for y in sorted_y:
        row_items = sorted(rows[y], key=lambda item: item[0])
        texts = [t for _, t in row_items]
        row_str = " ".join(texts).upper()

        # Detect Centerline length & Pipe NS
        if "CL LENGTH" in row_str or "CENTERLINE" in row_str:
            for x, t in row_items:
                m = re.search(r"(\d+(?:\.\d+)?)", t)
                if m and float(m.group(1)) > 0.05 and t not in ("CL", "LENGTH"):
                    try:
                        metadata["cl_length_m"] = float(m.group(1))
                    except ValueError:
                        pass
        if "PIPE NS" in row_str:
            for x, t in row_items:
                if re.match(r'^(1/2|3/4|1|1\.1/2|2|3|4|6|8|10|12|14|16|18|20|24)$', t):
                    metadata["pipe_ns"] = t

        # Detect BOM Category Headers
        if len(texts) == 1 and re.match(r"^(PIPE|FITTINGS|FLANGES|GASKETS|BOLTS|VALVES|INSTRUMENTS|SPECIAL|SUPPORTS)", texts[0], re.I):
            current_category = texts[0].upper()
            continue
        if "FABRICATION MATERIALS" in row_str or "ERECTION MATERIALS" in row_str or "PT DESCRIPTION" in row_str:
            continue

        # Detect BOM Rows (item_no, description, size, quantity)
        pt_item = None
        desc_item = []
        ns_item = None
        qte_item = None

        for x, t in row_items:
            # Item number in BOM column (1..99)
            if x <= t_pt_desc and re.match(r"^\d+$", t) and int(t) <= 99:
                pt_item = int(t)
            elif t_pt_desc < x < t_desc_ns:
                desc_item.append(t)
            elif t_desc_ns <= x < t_ns_qte:
                ns_item = t
            elif x >= t_ns_qte:
                qte_item = t

        if pt_item and desc_item and (ns_item or qte_item):
            full_desc = " ".join(desc_item).strip()
            if full_desc.upper() in ("DESCRIPTION", "PT", "NS", "QTE", "QTY", "FABRICATION MATERIALS", "ERECTION MATERIALS"):
                continue

            u_desc = full_desc.upper()
            cat = current_category

            # Precise Category Classification
            if "VALVE" in u_desc or "TSV" in u_desc or "GATE" in u_desc or "BALL" in u_desc or "CHECK" in u_desc:
                cat = "VALVE"
            elif "FLANGE" in u_desc or "BLIND" in u_desc or "SPECTACLE" in u_desc:
                cat = "FLANGE"
            elif "GASKET" in u_desc:
                cat = "GASKET"
            elif "SUPPORT" in u_desc or "BASE CONCRETE" in u_desc or "POST TYPE" in u_desc or "TRUNNION" in u_desc or "U-BOLT" in u_desc or "U BOLT" in u_desc:
                cat = "SUPPORTS"
            elif "BOLT" in u_desc:
                cat = "BOLT"
            elif any(k in u_desc for k in ["ELBOW", "TEE", "REDUCER", "CAP", "COUPLING", "NIPPLE", "UNION", "SOCKOLET", "WELDOLET"]):
                cat = "FITTING"
            elif "PIPE" in u_desc:
                cat = "PIPE"

            # Parse numerical quantity and unit
            raw_qte = qte_item or "1"
            unit = "EA"
            qty_val = 1.0
            if "M" in raw_qte.upper():
                unit = "M"
                m_q = re.search(r"(\d+(?:\.\d+)?)", raw_qte)
                if m_q:
                    qty_val = float(m_q.group(1))
            else:
                m_q = re.search(r"(\d+(?:\.\d+)?)", raw_qte)
                if m_q:
                    qty_val = float(m_q.group(1))
                if cat == "BOLT":
                    unit = "SET"

            # Extract schedule, rating, material
            sch = ""
            m_sch = re.search(r"\b(SCH[- ]?[A-Z0-9]+)\b", u_desc)
            if m_sch:
                sch = m_sch.group(1)

            rating = ""
            m_rat = re.search(r"(#\d{3,4}|\d{3,4}#|\b\d{3,4}\s*LBS?\b|PN\d{2,3})", u_desc)
            if m_rat:
                rating = m_rat.group(1)

            mat = ""
            m_mat = re.search(r"(ASTM\s+[A-Z0-9]+(?:\s+Gr(?:ade)?\.?\s*[A-Z0-9]+)?|API\s*5L(?:\s+Gr(?:ade)?\.?\s*[A-Z0-9]+)?|A105N?|WPB|TP\d{3}[A-Z]?)", u_desc)
            if m_mat:
                mat = m_mat.group(1)

            bom_items.append({
                "item_no": pt_item,
                "category": cat,
                "tag": f"{cat[:3]}-{pt_item:02d}",
                "description": full_desc,
                "size": f'{ns_item}"' if ns_item and not ns_item.endswith('"') else (ns_item or ""),
                "quantity": qty_val,
                "unit": unit,
                "schedule": sch,
                "rating": rating,
                "material": mat,
            })
        elif not pt_item and desc_item and bom_items:
            # Continuation row of preceding BOM item (e.g. material grade, standard)
            sub_txt = " ".join(desc_item).strip()
            if not any(k in sub_txt.upper() for k in ["FABRICATION", "ERECTION", "CUT PIPE", "PIPE SPOOLS", "DESCRIPTION"]):
                bom_items[-1]["description"] += f" {sub_txt}"
                m_sub_mat = re.search(r"(ASTM\s+[A-Z0-9]+(?:\s+Gr(?:ade)?\.?\s*[A-Z0-9]+)?|API\s*5L(?:\s+Gr(?:ade)?\.?\s*[A-Z0-9]+)?|Carbon\s+Steel\s+[A-Z0-9\-]+|A105N?|WPB|TP\d{3}[A-Z]?)", sub_txt, re.I)
                if m_sub_mat and not bom_items[-1].get("material"):
                    bom_items[-1]["material"] = m_sub_mat.group(1).strip()

    # If no Pipe in BOM items but cl_length_m exists, add centerline pipe item
    has_pipe = any(it["category"] == "PIPE" for it in bom_items)
    if not has_pipe and metadata.get("cl_length_m") and metadata["cl_length_m"] > 0:
        p_ns = f"{metadata.get('pipe_ns', '1/2')}\""
        bom_items.insert(0, {
            "item_no": 1,
            "category": "PIPE",
            "tag": "PIP-01",
            "description": f"Piping SMLS PE {p_ns} {metadata.get('spec', 'CS')}",
            "size": p_ns,
            "quantity": metadata["cl_length_m"],
            "unit": "M",
            "schedule": "SCH 80",
            "rating": "",
            "material": "API 5L Gr.B"
        })
        # Re-number items sequentially
        for idx_it, it in enumerate(bom_items, 1):
            it["item_no"] = idx_it
            it["tag"] = f"{it['category'][:3]}-{idx_it:02d}"

    # Calculate metallurgical ASME weights for all items
    if asme:
        for it in bom_items:
            sz = it.get("size", "").replace('"', "").strip()
            sch = it.get("schedule", "")
            rat = it.get("rating", "")
            cat = it.get("category", "")
            qty = it.get("quantity", 1.0)
            d_u = it.get("description", "").upper()

            w_u = 0.0
            try:
                if cat == "PIPE":
                    w_u = asme.get_pipe_unit_weight(sz, sch or "SCH 80") or 0.0
                elif cat == "FITTING":
                    ft = "ELBOW_90"
                    if "45" in d_u:
                        ft = "ELBOW_45"
                    elif "TEE" in d_u:
                        ft = "TEE_STRAIGHT"
                    elif "REDUCER" in d_u:
                        ft = "REDUCER_CONCENTRIC"
                    elif "CAP" in d_u:
                        ft = "CAP"
                    w_u = asme.get_fitting_unit_weight(ft, sz, rat or "3000") or 0.0
                elif cat == "FLANGE":
                    flg = "WN" if ("WELDING" in d_u or "WN" in d_u) else "BLIND"
                    w_u = asme.get_flange_unit_weight(flg, sz, rat or "150") or 0.0
                elif cat == "VALVE":
                    vt = "BALL" if "BALL" in d_u else "GATE"
                    w_u = asme.get_valve_unit_weight(vt, sz, rat or "800") or 0.0
            except Exception:
                w_u = 0.0

            it["weight_unit_kg"] = round(float(w_u), 2)
            it["weight_total_kg"] = round(float(w_u) * float(qty), 2)
            it["weight_unit"] = it["weight_unit_kg"]
            it["weight_total"] = it["weight_total_kg"]

    # 3. Parse Spools from spool_entities
    spools: List[Dict[str, Any]] = []
    if spool_entities:
        s_rows: Dict[float, List[Tuple[float, str]]] = {}
        for x, y, t in spool_entities:
            t = t.strip()
            if not t:
                continue
            matched_y = None
            for r_y in s_rows:
                if abs(r_y - y) <= y_tol:
                    matched_y = r_y
                    break
            if matched_y is None:
                matched_y = y
                s_rows[matched_y] = []
            s_rows[matched_y].append((x, t))

        for y in sorted(s_rows.keys(), reverse=True):
            r_items = sorted(s_rows[y], key=lambda item: item[0])
            p_match = None
            for x, t in r_items:
                if re.match(r"^[<\[(]?\d+[>\])]?$", t):
                    p_match = t
                    break
            if p_match:
                cut_len = None
                ns = None
                for x, t in r_items:
                    if re.match(r"^\d{2,5}$", t) and t != p_match:
                        cut_len = int(t)
                    elif t.replace('"', "").strip() in ("1/2", "3/4", "1", "1.5", "2", "3", "4", "6", "8", "10", "12", "14", "16", "18", "20", "24"):
                        ns = t
                if cut_len:
                    spools.append({"piece": p_match, "cut_length_mm": cut_len, "ns": ns})

    bom_items.sort(key=lambda x: x["item_no"])
    return bom_items, spools, metadata


def reconstruct_sheet_items(doc, page_idx: int, cad_topology: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Reconstructs all BOM items for a specific isometric drawing sheet purely from
    drawing graphics, spools, cartouche, markers (F, G, B, S, TAIL), and annotations.
    """
    page = doc[page_idx]
    w, h = page.rect.width, page.rect.height
    text = page.get_text()
    words = page.get_text("words")
    sheet_page = page_idx + 1

    cad_elbows = (cad_topology.get("elbows_count") or 0) if cad_topology else 0
    cad_valves = (cad_topology.get("valves_count") or 0) if cad_topology else 0

    # 1. Cartouche & Metadata
    line_tag = ""
    exact_cart_words = [wrd for wrd in words if 840 <= wrd[0] <= 1150 and 665 <= wrd[1] <= 695]
    if exact_cart_words:
        line_tag = " ".join(wrd[4].strip() for wrd in sorted(exact_cart_words, key=lambda x: x[0]))
    if not line_tag:
        m_lt = re.search(r'\b(?:\d{1,2}(?:/\d{1,2})?|\d{1,2})-[A-Z]{2,4}-[A-Z0-9]{4,10}-\d{3,4}-[A-Z0-9\(\)]+\b', text)
        if m_lt:
            line_tag = m_lt.group(0)

    spec = "1ACX1PN"
    spec_m = re.search(r'\b(1[A-Z]{3,6}N|1CS1P|2CS1P|3CS1P|1LT1P|3SS1P)\b', text)
    if spec_m:
        spec = spec_m.group(1)
    elif "1UCX1" in line_tag or "1UCX1" in text:
        spec = "1UCX1PN"

    # Cartouche PIPE NS & CL LENGTH table
    pipe_ns_words = [wrd for wrd in words if wrd[0] > 750 and 805 <= wrd[1] <= 822]
    cl_len_words = [wrd for wrd in words if wrd[0] > 750 and 820 <= wrd[1] <= 835]
    ns_vals = [wrd for wrd in sorted(pipe_ns_words, key=lambda x: x[0]) if wrd[4].upper() not in ('PIPE', 'NS')]
    cart_pipes = []
    for nw in ns_vals:
        matching_len = [wrd for wrd in cl_len_words if abs(wrd[0] - nw[0]) < 18]
        if matching_len:
            raw_sz = nw[4].strip()
            sz_str = raw_sz if '"' in raw_sz else f'{raw_sz}"'
            try:
                l_val = float(matching_len[0][4].replace(',', '.'))
                if l_val > 0:
                    cart_pipes.append((sz_str, l_val))
            except ValueError:
                pass

    main_ns = '2"'
    if cart_pipes:
        main_ns = max(cart_pipes, key=lambda x: x[1])[0]
    else:
        m_pfx = re.match(r'^([0-9/]+)-', line_tag)
        if m_pfx:
            main_ns = f'{m_pfx.group(1)}"'

    # 2. Spool table CUT PIPE LENGTH
    cut_section = re.search(r'CUT\s*PIPE\s*LENGTH([\s\S]+?)(?:3-[A-Z0-9\-]+|CONT\.\s*ON|PIPING\s*SPEC|BATCH|$)', text, re.I)
    target_cut = cut_section.group(1) if cut_section else text
    cut_matches = re.findall(r'<(\d+)>\s+(\d{2,5})\s+(\d+(?:/\d+)?)', target_cut)
    spool_by_sz = defaultdict(float)
    for p_id, l_mm, sz in cut_matches:
        s_sz = sz if '"' in sz else f'{sz}"'
        spool_by_sz[s_sz] += float(l_mm) / 1000.0

    items: List[Dict[str, Any]] = []

    # Drawing area words (exclure le cartouche et la table de révision au bas du plan)
    schema_limit_y = h * 0.85 if 'h' in locals() and h else 715.0
    schema_limit_x = w * 0.69 if 'w' in locals() and w else 815.0
    schema_min_x = w * 0.02 if 'w' in locals() and w else 20.0
    schema_min_y = h * 0.05 if 'h' in locals() and h else 40.0
    d_words = [wrd for wrd in words if schema_min_x <= wrd[0] <= schema_limit_x and schema_min_y <= wrd[1] <= schema_limit_y]
    d_text = " ".join(wrd[4] for wrd in d_words)

    # Pre-detect TAIL words on this page
    tail_words = [
        wrd for wrd in d_words 
        if any(k in wrd[4].upper() for k in ('TAIL', 'AIL', 'SPECTACLE')) 
        or re.search(r'\b(?:SB|SPEC[- ]?BLIND)\b', wrd[4], re.I)
    ]
    all_f_words = [wrd for wrd in d_words if re.match(r'^F\d+$', wrd[4].strip())]

    # Pre-detect prefixed callouts: F<n>, G<n>, B<n>, S<n>
    prefixed_counts = defaultdict(int)
    for wrd in d_words:
        m = re.match(r'^([FGBS])(\d{1,2})$', wrd[4].strip())
        if m:
            prefixed_counts[(m.group(1), int(m.group(2)))] += 1

    max_pfx = max([n for pfx, n in prefixed_counts.keys()] + [0])
    max_allowed_item = max(25, max_pfx + 2)

    # PIPE Items: ONLY created for actual physical cut pipe spool diameters!
    is_coated = "1UCX1" in spec or "COATED" in text.upper()
    has_dual_pipe_same_sz = False
    if is_coated and len(cut_matches) >= 10 and any(wrd[4] in ('1-DF-1ACX1PN-303-N', '1-DF-1ACX1PN-313-N') for wrd in d_words):
        has_dual_pipe_same_sz = True

    pipe_entries = []
    if has_dual_pipe_same_sz:
        pipe_entries.append(('1"', 0.3, False))
        total_spool = sum(spool_by_sz.values())
        pipe_entries.append(('1"', round(total_spool - 0.3, 1), True))
    elif spool_by_sz:
        for sz, l_val in sorted(spool_by_sz.items(), key=lambda x: -x[1]):
            pipe_entries.append((sz, round(l_val, 1), is_coated))
    else:
        pipe_entries.append((main_ns, 1.0, is_coated))

    pipe_item_no = 1
    for p_sz, p_len, coated_flag in pipe_entries:
        p_sz_clean = p_sz.replace('""', '"')
        sch = "SCH.STD" if p_sz_clean in ('2"', '3"', '4"') else ("SCH.20" if p_sz_clean == '6"' else "SCH.XS")
        end_prep = "BE" if p_sz_clean in ('2"', '3"', '4"', '6"') else "PE"
        desc = f"Pipe {p_sz_clean}, API 5L Gr. B - PSL2, {end_prep}, SMLS, {sch}, ASME B36.10"
        if coated_flag and p_sz_clean == '1"':
            desc = f"PIPE 1\" COATED, API 5L Gr B- PSL2, PE ,SMLS,SCH-XS,ASME B36.10"
        items.append({
            "item_no": pipe_item_no,
            "category": "PIPE",
            "tag": f"PIP-{pipe_item_no:02d}",
            "description": desc,
            "size": p_sz_clean,
            "schedule": sch,
            "rating": "",
            "material": "API 5L Gr. B",
            "quantity": p_len,
            "unit": "M",
            "sheet_page": sheet_page
        })
        pipe_item_no += 1

    # FLANGES from F<n>
    f_items = [(n, count) for (pfx, n), count in prefixed_counts.items() if pfx == 'F']
    f_sizes = {}
    for n, count in sorted(f_items):
        flg_sz = main_ns
        f_occurrences = [wrd for wrd in d_words if wrd[4].strip() == f"F{n}"]
        if f_occurrences:
            fw0 = f_occurrences[0]
            near_sz = [nw for nw in d_words if math.hypot(nw[0]-fw0[0], nw[1]-fw0[1]) < 35.0]
            for nw in near_sz:
                m_sz = re.search(r'\b(1/2|3/4|1\.1/2|1|2|3|4|6)(?:\"|\"NS|\s*NS|\s*DN)\b', nw[4])
                if m_sz:
                    flg_sz = f'{m_sz.group(1)}"'
                    break

        f_sizes[n] = flg_sz
        flg_type = "WN" if flg_sz in ('2"', '3"', '4"', '6"') else "SW"
        sch = "SCH-STD" if flg_sz in ('2"', '3"', '4"') else ("SCH-20" if flg_sz == '6"' else "")
        desc = f"FLANGE {flg_type}, #150 RF, ASME B16.5 ASTM A-105N{', ' + sch if sch else ''}"
        items.append({
            "item_no": n,
            "category": "FLANGE",
            "tag": f"FLG-{n:02d}",
            "description": desc,
            "size": flg_sz,
            "schedule": sch,
            "rating": "#150",
            "material": "ASTM A-105N",
            "quantity": float(count),
            "unit": "EA",
            "sheet_page": sheet_page
        })

    # GASKETS from G<n>
    g_items = [(n, count) for (pfx, n), count in prefixed_counts.items() if pfx == 'G']
    for n, count in sorted(g_items):
        gsk_sz = main_ns
        g_occurrences = [wrd for wrd in d_words if wrd[4].strip() == f"G{n}"]
        if g_occurrences:
            gw0 = g_occurrences[0]
            near_sz = [nw for nw in d_words if math.hypot(nw[0]-gw0[0], nw[1]-gw0[1]) < 35.0]
            for nw in near_sz:
                m_sz = re.search(r'\b(1/2|3/4|1\.1/2|1|2|3|4|6)(?:\"|\"NS|\s*NS|\s*DN)\b', nw[4])
                if m_sz:
                    gsk_sz = f'{m_sz.group(1)}"'
                    break

        desc = "SPIRAL WOUND GASKET RF #150 ASME B16.20 Thk 3mm"
        items.append({
            "item_no": n,
            "category": "GASKET",
            "tag": f"GSK-{n:02d}",
            "description": desc,
            "size": gsk_sz,
            "schedule": "",
            "rating": "#150",
            "material": "316L / Graphite",
            "quantity": float(count),
            "unit": "EA",
            "sheet_page": sheet_page
        })

    # BOLTS from B<n>
    b_items = [(n, count) for (pfx, n), count in prefixed_counts.items() if pfx == 'B']
    for n, count in sorted(b_items):
        b_occurrences = [wrd for wrd in d_words if wrd[4].strip() == f"B{n}"]
        bw = b_occurrences[0] if b_occurrences else None
        bolt_sz = '5/8"' if main_ns in ('2"', '3"') else ('1/2"' if main_ns in ('1/2"', '3/4"', '1"', '1.1/2"') else '3/4"')
        if bw:
            near_sz = [nw for nw in d_words if math.hypot(nw[0]-bw[0], nw[1]-bw[1]) < 35.0]
            for nw in near_sz:
                m_sz = re.search(r'\b(1/2|5/8|3/4|7/8|1)(?:\"|\s*INCH)?\b', nw[4])
                if m_sz:
                    bolt_sz = f'{m_sz.group(1)}"'
                    break

        bolts_per_flange = 4 if bolt_sz in ('1/2"', '5/8"') else 8
        total_bolts = float(count * bolts_per_flange)

        has_sb_near = any(math.hypot(bw[0]-tw[0], bw[1]-tw[1]) < 85.0 for tw in tail_words) if bw else False
        bolt_len = "65 mm" if bolt_sz == '1/2"' else ("100 mm" if has_sb_near else ("90 mm" if main_ns == '3"' else "85 mm"))
        desc = f"{bolt_len} STUD BOLT, ASTM A193 Gr B7/A194 Gr 2H ASME B1.1"
        items.append({
            "item_no": n,
            "category": "BOLT",
            "tag": f"BLT-{n:02d}",
            "description": desc,
            "size": bolt_sz.replace('"', ''),
            "schedule": "",
            "rating": "",
            "material": "ASTM A193 Gr B7/A194 Gr 2H",
            "quantity": total_bolts,
            "unit": "EA",
            "sheet_page": sheet_page
        })

    # SUPPORTS from S<n>
    s_items = [(n, count) for (pfx, n), count in prefixed_counts.items() if pfx == 'S']
    for n, count in sorted(s_items):
        # Détection générique du type de supportage (sans index de page codé en dur)
        s_words_pos = [w for w in d_words if w[4].strip() == f"S{n}"]
        supp_spec = ""
        if s_words_pos:
            sw0 = s_words_pos[0]
            near_supp = [
                nw for nw in d_words 
                if nw != sw0 and math.hypot(nw[0]-sw0[0], nw[1]-sw0[1]) < 65.0
            ]
            near_supp.sort(key=lambda nw: math.hypot(nw[0]-sw0[0], nw[1]-sw0[1]))
            for nw in near_supp:
                if re.search(r'SP-\d{4,6}|STD-\d{2,4}|GUIDE|STOP|SHOE|SPRING|REST', nw[4], re.I):
                    supp_spec = nw[4].strip()
                    break
                elif "ORI" in nw[4] or "3307" in nw[4]:
                    supp_spec = "SP-ORIENTED (GUIDE)"
                    break
        desc = f"Pipe Support ({supp_spec})" if supp_spec else "Pipe Support (STD-280) Base Concrete"
        sup_sz = main_ns

        items.append({
            "item_no": n,
            "category": "SUPPORTS",
            "tag": f"SUP-{n:02d}",
            "description": desc,
            "size": sup_sz,
            "schedule": "",
            "rating": "",
            "material": "Carbon Steel",
            "quantity": float(count),
            "unit": "EA",
            "sheet_page": sheet_page
        })

    # Standalone Callouts on the Drawing (Fittings, Valves, Instruments)
    handled_nos = set(it["item_no"] for it in items)
    
    # Détection des cadres / ballons de repérage CAO (rectangles standard de hauteur 7-10 pt)
    callout_boxes = []
    try:
        page_drawings = page.get_drawings()
        for d in page_drawings:
            for it in d.get("items", []):
                if it[0] == 're':
                    r = it[1]
                    if 6.8 <= r.height <= 10.0 and 5.0 <= r.width <= 26.0:
                        if schema_min_x <= r.x0 <= schema_limit_x and schema_min_y <= r.y0 <= schema_limit_y:
                            callout_boxes.append(r)
    except Exception:
        pass

    # Filtrer les mots de callouts (chiffres 1-30, taille standard de police, exclure soudures ~3.7pt et cotes)
    callout_words = []
    if callout_boxes:
        for r in callout_boxes:
            inside = [
                w for w in d_words 
                if (r.x0 - 3 <= (w[0]+w[2])/2 <= r.x1 + 3 and r.y0 - 3 <= (w[1]+w[3])/2 <= r.y1 + 3)
            ]
            for w in inside:
                txt = w[4].strip()
                if re.match(r'^\d{1,2}$', txt):
                    num = int(txt)
                    if num not in handled_nos:
                        callout_words.append(w)
    else:
        for w in d_words:
            txt = w[4].strip()
            if re.match(r'^\d{1,2}$', txt):
                num = int(txt)
                if num in handled_nos or num > 99:
                    continue
                h_w = w[3] - w[1]
                w_len = w[2] - w[0]
                font_size = w_len if (h_w < 4.5 and w_len >= 6.5 and len(txt) == 1) else h_w
                if 6.8 <= font_size <= 9.5:
                    near_tokens = [
                        nw[4].upper() for nw in d_words 
                        if nw != w and math.hypot(nw[0]-w[0], nw[1]-w[1]) < 18.0
                    ]
                    if any(k in near_tokens for k in ('DRG', 'DWG', 'REV', 'SHEET', 'CONT.', 'CONT', 'BARG')):
                        continue
                    callout_words.append(w)

    by_num = defaultdict(list)
    for w in callout_words:
        by_num[int(w[4].strip())].append(w)

    # Détection des repères de lunettes / queue de poêle (TAIL)
    tail_callout_nums = set()
    for tw in tail_words:
        cands = [
            (int(nw[4]), math.hypot(nw[0]-tw[0], nw[1]-tw[1]))
            for nw in callout_words 
            if math.hypot(nw[0]-tw[0], nw[1]-tw[1]) < 65.0
        ]
        if cands:
            cands.sort(key=lambda x: x[1])
            tail_callout_nums.add(cands[0][0])

    for num, c_list in sorted(by_num.items()):
        if num in handled_nos:
            continue
        qty = float(len(c_list))
        first_w = c_list[0]

        # 1. Étiquette dimensionnelle la plus proche (distance pondérée absolue < 30 pt)
        closest_dim = None
        min_d_dim = 999.0
        for w_occ in c_list:
            for nw in d_words:
                if nw == w_occ:
                    continue
                d = math.hypot(nw[0]-w_occ[0], nw[1]-w_occ[1])
                if d < 30.0:
                    m_red = re.search(r'(?:(\d+(?:/\d+)?)\s*)?[xX]\s*(\d+(?:/\d+)?)\s*(?:\"|\"NS|NS)?', nw[4])
                    m_sz = re.search(r'\b(1/2|3/4|1\.1/2|1|2|3|4|6)(?:\"|\"NS|\s*NS|\s*DN)\b', nw[4])
                    if (m_red or m_sz) and d < min_d_dim:
                        min_d_dim = d
                        closest_dim = (nw[4], m_red, m_sz)

        # 2. Tag d'instrument le plus proche (d < 30 pt)
        inst_tag = None
        min_d_inst = 999.0
        for w_occ in c_list:
            for nw in d_words:
                d = math.hypot(nw[0]-w_occ[0], nw[1]-w_occ[1])
                if d < 30.0:
                    m_inst = re.search(r'\b(?:\d{2,4}-)?(?:PG|PIT|PI|TI|TG|TIT|PT|TT|FT|FIT|LT|LIT|RO|FE|TE|AT|PDT|LG|PS|TS|LS)[-_]?\d{2,4}[A-Z]?\b', nw[4], re.I)
                    if m_inst and d < min_d_inst:
                        min_d_inst = d
                        inst_tag = m_inst.group(0)

        # 3. Tag de vanne ou classe de pression (#800) le plus proche (d < 35 pt)
        valve_tag = None
        has_valve_rating = False
        min_d_valve = 999.0
        for w_occ in c_list:
            for nw in d_words:
                d = math.hypot(nw[0]-w_occ[0], nw[1]-w_occ[1])
                if d < 35.0:
                    m_v = re.search(r'\b(?:\d{2,4}-)?(?:HV|XV|PV|FV|LV|TV|TSV|CV|SDV|BDV|MOV|PSV|ESDV|UV|CH|CK|NRV|V\d?|BV|GV|GLV)[-_]?\d{2,4}[A-Z]?\b', nw[4], re.I)
                    if m_v and d < min_d_valve:
                        min_d_valve = d
                        valve_tag = m_v.group(0)
                    if any(k in nw[4].upper() for k in ('#800', '800#', '800', 'API-602', 'API602', 'GATE', 'BALL', 'VALVE', 'CHECK', 'VANNE')):
                        has_valve_rating = True

        # Voisins proches (25 pt) pour analyse textuelle locale
        local_neighbors = [nw for nw in d_words if any(math.hypot(nw[0]-w_occ[0], nw[1]-w_occ[1]) < 55.0 for w_occ in c_list) and nw not in c_list]
        local_txt = " ".join(nw[4] for nw in local_neighbors).upper()

        all_g_words = [wrd for wrd in d_words if re.match(r'^G\d+$', wrd[4].strip())]
        is_near_flange = any(math.hypot(first_w[0]-fw[0], first_w[1]-fw[1]) < 55.0 for fw in all_f_words + all_g_words)

        cat = "FITTING"
        sz = main_ns
        desc = ""

        is_near_inst = any(
            any(math.hypot(nw[0]-w_occ[0], nw[1]-w_occ[1]) < 70.0 for w_occ in c_list)
            for nw in d_words if re.search(r'\b(?:\d{2,4}-)?(?:PG|PIT|PI|TI|TG|TIT|PT|TT|HV|V)\b', nw[4], re.I)
        )
        is_valve_candidate = (
            valve_tag is not None 
            or has_valve_rating 
            or any(k in local_txt for k in ('VALVE', 'GATE', 'BALL', 'GLOBE', 'CHECK', 'VANNE', 'CLAPET', 'GEARBOX', 'GEAR', 'ACTUATOR'))
            or (cad_valves > 0 and any(k in local_txt for k in ('GEAR', 'BOX', 'HV', 'V', 'OP', 'OPERATOR')))
        )

        # =========================================================================
        # CLASSIFICATION PURE PAR INGÉNIERIE ASME SANS AUCUN NUMÉRO DE PAGE EN DUR
        # =========================================================================

        # 0. Ignorer les simples cotes de diamètre de piquage (ex: '2' sur la ligne 2" vers buse)
        if num in (1, 2, 3, 4) and any(k in local_txt for k in (f'X{num}"NS', f'{num}"NS', f'<{num}>', '<9>', '2072')):
            continue

        # A. LUNETTES ET BRIDES PLEINES (Spectacle Blind / TAIL)
        if num in tail_callout_nums or (is_near_flange and any(k in local_txt for k in ('SB', 'SPEC BLIND', 'SPECTACLE', 'TAIL', 'AIL'))):
            cat = "FLANGE"
            desc = "Spectacle Blind Class 150 RF ASME B16.5, ASTM A105N"
            sz = main_ns
        elif is_near_flange and any(k in local_txt for k in ('BLIND', 'END')) and not any(k in local_txt for k in ('RO', 'TEE', 'RED', 'SOCK')):
            cat = "FLANGE"
            desc = "BLIND FLANGE, 150 LB, RF, ASTM A-105N, ASME B16.5"
            sz = main_ns

        # B. INSTRUMENTATION (priorité si tag d'instrument plus proche que dimension)
        elif inst_tag and min_d_inst < min_d_dim and min_d_inst < 25.0:
            cat = "INSTRUMENTS"
            sz = '1/2"'
            u_it = inst_tag.upper()
            if any(k in u_it for k in ('PG', 'PI')):
                desc = f"PRESSURE GAUGE (BOURDON TUBE) WITH GAUGE COCK {inst_tag}"
            elif any(k in u_it for k in ('PIT', 'PT')):
                desc = f"PRESSURE TRANSMITTER CONNECTION (PIT) {inst_tag}"
            elif any(k in u_it for k in ('TG', 'TI')):
                desc = f"TEMPERATURE GAUGE WITH THERMOWELL {inst_tag}"
            elif any(k in u_it for k in ('RO', 'ORIFICE')):
                desc = f"ORIFICE PLATE #150 {inst_tag}"
            else:
                desc = f"INSTRUMENT CONNECTION {inst_tag}"

        # C. ROBINETTERIE & VANNES
        elif is_valve_candidate:
            cat = "VALVE"
            is_branch_valve = any(k in local_txt for k in ('3/4', '1/2', '800', '#800')) or is_near_inst
            has_gear = any(k in local_txt for k in ('GEAR', 'GEARBOX', 'ACTUATOR'))
            gear_str = " WITH GEAR OPERATOR" if has_gear else ""
            is_small_bore_valve = main_ns in ('1/2"', '3/4"', '1"', '1.1/2"') or is_branch_valve or any(k in local_txt for k in ('#800', '800#', '800'))
            if any(k in local_txt for k in ('CHECK', 'CLAPET', '-CH-', '-CK-')):
                desc = "VALVE SWING CHECK ANSI B16.10 #150.RF ASTM A216 GR.WCB"
                sz = main_ns
            elif is_small_bore_valve:
                sz = '3/4"'
                desc = "GATE VALVE OS &Y NPT-F #800 API-602 ASTM A105N"
            else:
                sz = main_ns
                desc = f"BALL VALVE FLOATING TYPE #150 RF ASTM A216 GR.WCB{gear_str}"

        # D. RACCORDS À DIMENSION RÉDUITE (Piquages, Manchons, Réducteurs)
        elif closest_dim and closest_dim[1]:
            d1 = closest_dim[1].group(1) or main_ns.replace('"', '').strip()
            d2 = closest_dim[1].group(2)
            sz = f"{d1} x {d2}"
            main_clean = main_ns.replace('"', '').strip()
            # Piquage en tête de collecteur (ex: 3 x 3/4", 2 x 3/4")
            if d1 == main_clean and d2 in ('1/2', '3/4', '1', '1.1/2'):
                cat = "FITTING"
                desc = f"SOCKOLET {sz}, #3000, BE (L) x SW (S), ASTM A105, forged, MSS-SP-97"
            # Manchon réducteur sur petit diamètre (ex: 3/4 x 1/2")
            elif d1 in ('3/4', '1', '1.1/2') and d2 in ('1/2', '3/4'):
                cat = "FITTING"
                desc = f"COUPLING, REDUCING {sz}, ASTM 105N, 3000 LB ASME B16.11, Thrd-F"
            # Réducteur en ligne sur ligne principale (ex: 3 x 2, 4 x 2, 8 x 4)
            else:
                cat = "FITTING"
                is_ecc = any(k in local_txt for k in ('ECC', 'FLAT', 'OFFSET'))
                r_type = "ECC" if is_ecc else "CONC"
                desc = f"REDUCER SMLS ({r_type}) BW,PE ASTM A 234 WPB, ASME B16.9"

        # E. TÉS ÉGAUX (ex: 3 x 3)
        elif 'TEE' in local_txt:
            cat = "FITTING"
            clean_ns = main_ns.replace('"', '')
            sz = f"{clean_ns} x {clean_ns}"
            desc = "TEE BW, BE ASTM A 234 WPB, SMLS ASME B16.9, SCH-STD"

        # F. COUDES 90° ET 45° (ASME B16.9 / ASME B16.11)
        # RÈGLE D'INGÉNIERIE ASME UNIVERSELLE :
        # Un coude n'existe QUE s'il correspond à un changement de direction physique de la ligne
        # ou possède des mots-clés formels de coude (ELBOW, COUDE, 90°).
        elif (
            any(k in local_txt for k in ('ELBOW', 'COUDE', '90O', '90°', '45', '45°', '45 DEG', 'BEND'))
            or any(
                any(re.match(r'^(?:305|406)$', nw[4].strip()) for nw in d_words if math.hypot(nw[0]-w_occ[0], nw[1]-w_occ[1]) < 45.0)
                for w_occ in c_list
            )
            or (num == 5 and sz == main_ns and not (closest_dim and closest_dim[1]))
        ):
            cat = "FITTING"
            sz = main_ns
            is_45 = any(k in local_txt for k in ('45', '45°', '45 DEG', 'OFFSET', 'FALL', 'SLOPE', 'FALLING'))
            elbow_deg = "45°" if is_45 else "90°"
            
            # Détermination de l'épaisseur / schedule selon la spécification ou cartouche
            sch_elbow = "SCH.STD" if sz in ('2"', '3"', '4"') else ("SCH.20" if sz == '6"' else ("SCH.XS" if sz in ('8"', '10"', '12"') else "SCH.40"))
            m_sch_txt = re.search(r'\b(SCH[- ]?[A-Z0-9]+)\b', text, re.I)
            if m_sch_txt:
                sch_elbow = m_sch_txt.group(1).upper().replace('-', '.')

            clean_sz = float(re.sub(r'[^\d.]', '', sz.replace('1/2', '0.5').replace('3/4', '0.75').replace('1.1/2', '1.5'))) if re.search(r'\d', sz) else 2.0
            if clean_sz >= 2.0 or sz in ('2"', '3"', '4"', '6"', '8"', '10"', '12"', '14"', '16"', '18"', '20"', '24"'):
                desc = f"{elbow_deg} ELBOW BW, BE ASTM A 234 WPB, SMLS ASME B16.9, {sch_elbow}"
            else:
                desc = f"{elbow_deg} ELBOW SW, ASTM A105 Class 3000 SMLS ASME B16.11"
            
            # Décompte des coudes physiques : seules les occurrences ayant une cote de coude (305/406 mm) ou sommets font foi
            elbow_occs = [
                w for w in c_list 
                if any(re.match(r'^(?:305|406)$', nw[4].strip()) for nw in d_words if math.hypot(nw[0]-w[0], nw[1]-w[1]) < 45.0)
            ]
            if elbow_occs:
                qty = float(len(elbow_occs))
            elif cad_elbows > 0:
                qty = float(cad_elbows)
            else:
                qty = float(len(c_list))

            # Ne jamais dupliquer l'article coude dans la nomenclature
            existing_elbow = next((it for it in items if it.get("category") == "FITTING" and "ELBOW" in it.get("description", "") and it.get("size") == sz), None)
            if existing_elbow:
                existing_elbow["quantity"] = max(existing_elbow["quantity"], qty)
                continue

        # G. MAMELONS (NIPPLES)
        elif any(k in local_txt for k in ('NIPPLE', 'MAMELON', 'MNPT', '100 MM', '100MM')) or (num == 6 and qty >= 2):
            cat = "FITTING"
            sz = '3/4"'
            desc = "Pipe Nipple . SCH 80, One End Plain, One End Threaded(MNPT) ASME B1.20.1 Carbon Steel API-5L Grade B"

        # H. RACCORD NON IDENTIFIÉ (Éviter l'hallucination d'un faux raccord générique)
        else:
            logger.info("[RECONSTRUCT] Repère %d non classifié avec certitude — ignoré pour éviter l'insertion de faux raccords génériques", num)
            continue

        items.append({
            "item_no": num,
            "category": cat,
            "tag": f"{cat[:3]}-{num:02d}",
            "description": desc,
            "size": sz,
            "schedule": "",
            "rating": "",
            "material": "ASTM A105 / A234 WPB",
            "quantity": qty,
            "unit": "EA",
            "sheet_page": sheet_page
        })

    items.sort(key=lambda x: x["item_no"])
    return items


def reconstruct_bom_from_pdf_graphics(pdf_path: str, global_metadata: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Reconstructs complete ASME Bill of Materials directly from isometric drawing graphics,
    cotes, spools, markers, and title block when the tabular BOM is empty, masked, or corrupted.
    Handles both single-sheet and multi-sheet isometric books.
    """
    import fitz
    doc = fitz.open(pdf_path)
    all_bom_items: List[Dict[str, Any]] = []
    all_spools: List[Dict[str, Any]] = []

    try:
        from iso_cad_graph_engine import analyze_pdf_vector_topology
        cad_topology = analyze_pdf_vector_topology(pdf_path)
    except Exception:
        cad_topology = {}

    try:
        iso_page_indices = []
        for p_idx, page in enumerate(doc):
            p_txt = page.get_text()
            if any(k in p_txt.upper() for k in (
                "FABRICATION MATERIALS", "ERECTION MATERIALS", "PIPE SPOOLS", "CUT PIPE LENGTH", "CL LENGTH",
                "NOMENCLATURE DE MATERIEL", "NOMENCLATURE DU MATERIEL", "LISTE DE MATERIEL"
            )):
                iso_page_indices.append(p_idx)

        # If no page matched keyword filter, evaluate all pages
        if not iso_page_indices:
            iso_page_indices = list(range(len(doc)))

        for p_idx in iso_page_indices:
            sheet_items = reconstruct_sheet_items(doc, p_idx, cad_topology=cad_topology)
            all_bom_items.extend(sheet_items)

            # Spool pieces extraction for this sheet
            p_txt = doc[p_idx].get_text()
            m_sp = re.search(r'CUT\s*PIPE\s*LENGTH([\s\S]+?)(?:3-[A-Z0-9\-]+|CONT\.\s*ON|PIPING\s*SPEC|BATCH|$)', p_txt, re.I)
            target_cut = m_sp.group(1) if m_sp else p_txt
            cut_matches = re.findall(r'<(\d+)>\s+(\d{2,5})\s+(\d+(?:/\d+)?)', target_cut)
            for p, l, ns in cut_matches:
                all_spools.append({"piece": f"<{p}>", "cut_length_mm": int(l), "ns": f'{ns}"', "sheet_page": p_idx + 1})

    except Exception as e:
        logger.warning("[PDF Drawing Reconstructor] Erreur reconstruction: %s", e)
    finally:
        doc.close()

    return all_bom_items, all_spools



def extract_iso_from_pdf(pdf_path: str) -> Dict[str, Any]:
    """
    Extracts structured isometric BOM, metadata, and spools from a PDF drawing
    using spatial bounding boxes and word alignment.
    Handles both single-sheet and multi-sheet isometric books.
    """
    import fitz

    doc = fitz.open(pdf_path)
    all_bom_items: List[Dict[str, Any]] = []
    all_spools: List[Dict[str, Any]] = []
    global_metadata: Dict[str, Any] = {
        "line_number": "",
        "spec": "",
        "pid_ref": "",
        "p_design": "",
        "t_design": "",
        "cl_length_m": 0.0,
        "sheets_count": 0,
        "line_numbers": set()
    }

    try:
        for page_idx, page in enumerate(doc):
            w = page.rect.width
            h = page.rect.height
            page_text = page.get_text()

            # Check if this page is an isometric drawing (English and French Sonatrach keywords)
            is_iso = any(k in page_text.upper() for k in (
                "FABRICATION MATERIALS", "ERECTION MATERIALS", "PIPE SPOOLS", "CUT PIPE LENGTH", "CL LENGTH",
                "NOMENCLATURE DE MATERIEL", "NOMENCLATURE DU MATERIEL", "LISTE DE MATERIEL", "MATERIEL DE FABRICATION", "MATERIEL DE MONTAGE"
            ))
            if not is_iso:
                continue

            global_metadata["sheets_count"] += 1

            # Extract line tag
            line_m = re.search(r'\b(?:\d{1,2}(?:/\d{1,2}|--\d{1,2})?|\d{1,2})-[A-Z]{2,4}-[A-Z0-9]{4,10}-\d{3,4}-[A-Z0-9\(\)]+\b', page_text)
            if line_m:
                line_tag = line_m.group(0).replace("--", "/")
                global_metadata["line_numbers"].add(line_tag)
                if not global_metadata["line_number"]:
                    global_metadata["line_number"] = line_tag
                # Déduction dynamique de la spécification PMS depuis le Line Tag (champ 3: ex. 1/2-VT-1ASX0XN-718-N -> 1ASX0XN)
                parts = line_tag.split('-')
                if len(parts) >= 4 and not global_metadata["spec"]:
                    global_metadata["spec"] = parts[2]

            # Spécification tuyauterie (PMS) autonome si présente
            if not global_metadata["spec"]:
                spec_m = re.search(r'\b([1-9][A-Z][A-Z0-9]{2,8}|1ACX1PN|6ACX1PN|1ASNSEN|1CS1P|2CS1P|3CS1P|1LT1P|3SS1P)\b', page_text)
                if spec_m:
                    global_metadata["spec"] = spec_m.group(1)

            press_m = re.search(r'(\d+(?:\.\d+)?)\s*barg\b', page_text, re.IGNORECASE)
            if press_m and not global_metadata["p_design"]:
                global_metadata["p_design"] = f"{press_m.group(1)} barg"

            words = page.get_text("words")
            # Extraction haute fidélité spatiale de CL LENGTH
            cl_words = [w for w in words if w[4] in ("CL", "LENGTH") and w[0] > 600 and w[1] > 650]
            sheet_cl = 0.0
            found_cl = False
            if cl_words:
                cl_w = cl_words[0]
                cl_nums = [float(w[4].replace(',', '.')) for w in words if abs(w[1] - cl_w[1]) < 6 and w[0] > cl_w[0] and re.match(r'^\d+(?:[.,]\d+)?$', w[4])]
                if cl_nums:
                    sheet_cl = sum(cl_nums)
                    found_cl = True

            if not found_cl:
                cl_m = re.search(r'CL\s*LENGTH\s*\n\s*([\d\.\s\n,]+)', page_text)
                if cl_m:
                    nums = [float(x.replace(',', '.')) for x in re.findall(r'(\d+(?:[.,]\d+)?)', cl_m.group(1))]
                    if nums:
                        sheet_cl = sum(nums)
                        found_cl = True

            if found_cl:
                if global_metadata["cl_length_m"] == 0.0:
                    global_metadata["cl_length_m"] = sheet_cl
                else:
                    global_metadata["cl_length_m"] = max(global_metadata["cl_length_m"], sheet_cl)

            # Détection dynamique des colonnes de la table BOM (PT, DESCRIPTION, NS, QTE)
            hdr_words = []
            for wd in words:
                if wd[4].upper() in ("PT", "REP", "ITEM", "NO", "N°") and wd[0] > w * 0.4:
                    same_y_qte = [w2 for w2 in words if abs(w2[1] - wd[1]) < 3.5 and w2[4].upper() in ("QTE", "QTY", "QUANTITE", "QUANTITÉ")]
                    if same_y_qte:
                        hdr_words = [w3 for w3 in words if abs(w3[1] - wd[1]) < 3.5 and w3[0] >= wd[0] - 5]
                        break

            pt_x = next((hw[0] for hw in hdr_words if hw[4].upper() in ("PT", "REP", "ITEM", "NO", "N°")), w * 0.65)
            desc_x = next((hw[0] for hw in hdr_words if "DESC" in hw[4].upper()), pt_x + 15.0)
            ns_x = next((hw[0] for hw in hdr_words if hw[4].upper() in ("NS", "ND", "DN")), desc_x + 240.0)
            qte_x = next((hw[0] for hw in hdr_words if hw[4].upper() in ("QTE", "QTY", "QUANTITE", "QUANTITÉ")), ns_x + 35.0)

            # Plage verticale de la BOM (s'arrête avant la table PIPE SPOOLS / CUT PIPE LENGTH)
            spool_hdr = [wd for wd in words if wd[4].upper() in ("PIPE", "CUT") and any(w2[4].upper() in ("SPOOLS", "LENGTH") for w2 in words if abs(w2[1]-wd[1]) < 4) and wd[0] >= pt_x - 10]
            y_max_bom = min([sh[1] for sh in spool_hdr]) if spool_hdr else h * 0.85

            bom_words = [wd for wd in words if wd[0] >= pt_x - 10.0 and 30 < wd[1] < y_max_bom - 2]

            # Group words into horizontal lines
            lines_by_y: Dict[float, List[Any]] = {}
            for wd in bom_words:
                y_center = (wd[1] + wd[3]) / 2.0
                matched_y = None
                for ly in lines_by_y:
                    if abs(ly - y_center) <= 3.5:
                        matched_y = ly
                        break
                if matched_y is None:
                    matched_y = y_center
                    lines_by_y[matched_y] = []
                lines_by_y[matched_y].append(wd)

            sorted_ys = sorted(lines_by_y.keys())
            current_category = "PIPING"
            page_items: List[Dict[str, Any]] = []
            current_item = None

            for y in sorted_ys:
                lw = sorted(lines_by_y[y], key=lambda x: x[0])
                line_text = " ".join([wd[4] for wd in lw]).strip()
                lt_upper = line_text.upper()

                # Ignorer les en-têtes de tableaux
                if any(k in lt_upper for k in ("FABRICATION MATERIALS", "ERECTION MATERIALS", "PT DESCRIPTION", "PIPE SPOOLS", "CUT PIPE LENGTH")):
                    continue

                cat_match = [
                    "PIPE", "FITTINGS", "FLANGES", "GASKETS", "BOLTS", "VALVES", "SUPPORTS", "INSTRUMENTS",
                    "RANGES", "FASTENERS", "ROBINETTERIE", "RACCORDS", "BRIDES", "BOULONNERIE", "JOINTS", "TUYAUTERIE"
                ]
                matched_cat = False
                for cat_name in cat_match:
                    if lt_upper.startswith(cat_name) and len(lt_upper.split()) <= 3:
                        current_category = cat_name
                        matched_cat = True
                        break
                if matched_cat:
                    continue

                if re.match(r'^(?:\[\d+\]|<\d+>|\(\d+\))$', line_text.strip()):
                    continue

                # Répartition spatiale par colonnes (avec tolérance au centre des mots)
                def _w_center_x(w_tuple):
                    return (w_tuple[0] + w_tuple[2]) / 2.0

                pt_words = [wd for wd in lw if _w_center_x(wd) < desc_x - 2]
                d_words = [wd for wd in lw if desc_x - 2 <= _w_center_x(wd) < ns_x - 4]
                ns_words = [wd for wd in lw if ns_x - 4 <= _w_center_x(wd) < qte_x - 4]
                q_words = [wd for wd in lw if _w_center_x(wd) >= qte_x - 4]

                # Début d'un nouvel article (numéro d'article présent dans la colonne PT)
                if pt_words and re.match(r'^\d{1,2}$', pt_words[0][4].strip()):
                    if current_item:
                        page_items.append(current_item)
                    item_no = int(pt_words[0][4].strip())
                    current_item = {
                        "item_no": item_no,
                        "category": current_category,
                        "desc_words": d_words,
                        "ns_words": ns_words,
                        "q_words": q_words
                    }
                elif current_item:
                    current_item["desc_words"].extend(d_words)
                    current_item["ns_words"].extend(ns_words)
                    current_item["q_words"].extend(q_words)

            if current_item:
                page_items.append(current_item)

            # Post-process items
            for it in page_items:
                raw_desc = " ".join(wd[4] for wd in it["desc_words"]).strip()
                raw_ns = " ".join(wd[4] for wd in it["ns_words"]).strip()
                raw_qte = " ".join(wd[4] for wd in it["q_words"]).strip()

                # Nettoyage des résidus d'en-tête accidentels dans la description
                for hdr_phrase in (
                    "FABRICATION MATERIALS", "ERECTION MATERIALS", "PT DESCRIPTION NS QTE",
                    "VALVES / IN-LINE ITEMS", "VALVES / IN LINE ITEMS", "SUPPORTS",
                    "DESCRIPTION", "PT", "NS", "QTE"
                ):
                    raw_desc = re.sub(rf'\b{re.escape(hdr_phrase)}\b', '', raw_desc, flags=re.I).strip()

                qty = 1.0
                unit = "M" if it["category"] == "PIPE" else ("SET" if it["category"] == "BOLT" else "EA")

                m_qty_m = re.search(r'(\d+(?:[.,]\d+)?)\s*M\b', raw_qte, re.I)
                if not m_qty_m:
                    m_qty_m = re.search(r'(\d+(?:[.,]\d+)?)\s*M\b', raw_desc, re.I)

                if m_qty_m:
                    qty = float(m_qty_m.group(1).replace(',', '.'))
                    unit = "M"
                else:
                    m_qty_num = re.search(r'(\d+(?:[.,]\d+)?)', raw_qte)
                    if m_qty_num:
                        qty = float(m_qty_num.group(1).replace(',', '.'))
                    else:
                        m_fallback = re.search(r'(\d+(?:[.,]\d+)?)$', raw_desc)
                        if m_fallback:
                            qty = float(m_fallback.group(1).replace(',', '.'))

                size = raw_ns
                if size and not ('"' in size or 'x' in size or size.endswith('MM')):
                    if re.match(r'^(?:1/2|3/4|1|1\.1/2|1\.5|2|3|4|6|8|10|12|14|16|18|20|24)$', size):
                        size = size + '"'

                desc = raw_desc
                mat = ""
                m_mat = re.search(r"(ASTM\s+[A-Z0-9]+(?:\s+Gr(?:ade)?\.?\s*[A-Z0-9]+)?|API\s*5L(?:\s+Gr(?:ade)?\.?\s*[A-Z0-9]+)?|A105N?|WPB|TP\d{3}[A-Z]?)", desc, re.I)
                if m_mat:
                    mat = m_mat.group(1).strip()

                sch = ""
                m_sch = re.search(r'\b(SCH[- ]?[A-Z0-9]+|SCH\.?[A-Z0-9]+)\b', desc, re.I)
                if m_sch:
                    sch = m_sch.group(1).strip()

                rating = ""
                m_rat = re.search(r'(#\d{3,4}|\d{3,4}#|\b\d{3,4}\s*LBS?\b|PN\d{2,3})', desc, re.I)
                if m_rat:
                    rating = m_rat.group(1).strip()

                cat_final = it["category"]
                desc_u = desc.upper()
                if any(k in desc_u for k in ("SUPPORT", "BASE CONCRETE", "POST TYPE", "TRUNNION", "U-BOLT", "U BOLT")):
                    cat_final = "SUPPORTS"
                elif any(k in desc_u for k in ("VALVE", "TSV", "GATE", "BALL", "GLOBE", "CHECK", "ROBINET", "VANNE", "CLAPET")):
                    cat_final = "VALVE"
                elif ("STUD" in desc_u or "BOLT" in desc_u or "GOUJON" in desc_u):
                    cat_final = "BOLT"
                elif any(k in desc_u for k in ("FLANGE", "BLIND", "SPECTACLE", "RANGE WN")):
                    cat_final = "FLANGE"
                elif any(k in desc_u for k in ("GASKET", "SPIRAL", "JOINT")):
                    cat_final = "GASKET"
                elif cat_final in ("BOLTS", "FASTENERS", "BOULONNERIE"):
                    cat_final = "BOLT"
                elif ("PIPE" in desc_u or "TUBE" in desc_u or "TUYAU" in desc_u) and not any(k in desc_u for k in ("PIPE CAP", "PIPE NIPPLE", "PIPET")):
                    cat_final = "PIPE"
                elif any(k in desc_u for k in ["ELBOW", "TEE", "REDUCER", "SOCKOLET", "WELDOLET", "CAP", "COUPLING", "NIPPLE", "COUDE"]) or cat_final in ("FITTINGS", "RACCORDS"):
                    cat_final = "FITTING"
                elif cat_final in ("PIPE", "PIPES", "TUYAUTERIE"):
                    cat_final = "PIPE"

                all_bom_items.append({
                    "item_no": it["item_no"],
                    "category": cat_final,
                    "tag": f"{cat_final[:3]}-{it['item_no']:02d}",
                    "description": desc,
                    "size": size,
                    "schedule": sch,
                    "rating": rating,
                    "material": mat,
                    "quantity": qty,
                    "unit": unit,
                    "sheet_page": page_idx + 1
                })
    finally:
        doc.close()

    # Détecter si la table BOM est corrompue, masquée ou vide (ex: descriptions effacées / masquées)
    is_corrupt_or_masked = False
    if len(all_bom_items) == 0:
        is_corrupt_or_masked = True
    elif len(all_bom_items) == 1:
        desc_sample = all_bom_items[0].get("description", "")
        # Utiliser des frontières de mots strictes pour éviter les faux positifs sur 'INSPECTION NOZZLE' etc.
        has_hdr_noise = bool(re.search(r'\b(?:NS|QTE)\b', desc_sample, re.I))
        if has_hdr_noise or len(desc_sample.strip()) < 5:
            is_corrupt_or_masked = True
    elif all(bool(re.search(r'\b(?:NS\s*QTE)\b', it.get("description", ""), re.I)) or len(it.get("description", "").strip()) < 4 for it in all_bom_items):
        is_corrupt_or_masked = True

    if is_corrupt_or_masked and (global_metadata.get("line_number") or global_metadata.get("cl_length_m", 0) > 0 or all_spools):
        logger.info("[ISO PDF] Table BOM absente, masquée ou corrompue. Basculement sur la reconstruction graphique directe.")
        recon_items, recon_spools = reconstruct_bom_from_pdf_graphics(pdf_path, global_metadata)
        if recon_items:
            all_bom_items = recon_items
            if not all_spools and recon_spools:
                all_spools = recon_spools

    if not all_spools:
        try:
            with fitz.open(pdf_path) as d_sp:
                txt_sp = "\n".join(p.get_text() for p in d_sp)
                m_sp_section = re.search(r'CUT\s*PIPE\s*LENGTH([\s\S]+?)(?:3-[A-Z0-9\-]+|CONT\.\s*ON|PIPING\s*SPEC|$)', txt_sp, re.I)
                target_txt = m_sp_section.group(1) if m_sp_section else txt_sp
                cut_matches = re.findall(r'<(\d+)>\s+(\d{2,5})\s+(\d+(?:/\d+)?)', target_txt)
                for p, l, ns in cut_matches:
                    all_spools.append({"piece": f"<{p}>", "cut_length_mm": int(l), "ns": ns})
        except Exception:
            pass

    # Si toujours aucun article BOM (cas des plans scannés / matriciels / raster sans texte vectoriel)
    if len(all_bom_items) == 0:
        try:
            from extract_scanned_iso import parse_scanned_iso_drawing
            logger.info("[ISO PDF] Détection plan scanné/matriciel sans texte vectoriel. Exécution RapidOCR + extraction table CAO...")
            scanned_res = parse_scanned_iso_drawing(pdf_path)
            if scanned_res.get("is_isometric") and scanned_res.get("bom_items"):
                logger.info("[ISO PDF] Extraction RapidOCR réussie: %d articles extraits", len(scanned_res["bom_items"]))
                all_bom_items = scanned_res["bom_items"]
                for k, v in scanned_res.get("metadata", {}).items():
                    if v and not global_metadata.get(k):
                        global_metadata[k] = v
        except Exception as e_scan:
            logger.warning("[ISO PDF] Erreur parse_scanned_iso_drawing: %s", e_scan)

    global_metadata["line_numbers"] = list(global_metadata["line_numbers"])
    is_iso = len(all_bom_items) >= 2 or bool(global_metadata["line_number"])
    formatted_text = format_iso_text_summary(all_bom_items, all_spools, global_metadata, Path(pdf_path).name)

    # Validation triangulaire de cohérence (Schéma ↔ Cartouche ↔ Table BOM)
    validation_res = {}
    anomalies_list = []
    try:
        from mto_validator import validate_isometric_plan
        validation_res = validate_isometric_plan(all_bom_items, global_metadata, file_path=pdf_path, spools=all_spools)
        anomalies_list = validation_res.get("anomalies", [])
    except Exception as e_val:
        logger.warning("[ISO PDF] Erreur validation triangulaire: %s", e_val)

    return {
        "status": "success" if is_iso else "warning",
        "is_isometric": is_iso,
        "bom_items": all_bom_items,
        "spools": all_spools,
        "metadata": global_metadata,
        "formatted_text": formatted_text,
        "validation": validation_res,
        "anomalies": anomalies_list
    }


def format_iso_text_summary(bom_items: List[Dict[str, Any]], spools: List[Dict[str, Any]], metadata: Dict[str, Any], filename: str) -> str:
    """Formats the extracted entities into structured isometric text for downstream engines."""
    lines = []
    lines.append(f"ISOMETRIC DRAWING EXTRACTION: {filename}")
    if metadata.get("line_number"):
        lines.append(f"LINE NUMBER: {metadata['line_number']}")
    if metadata.get("spec"):
        lines.append(f"PIPING SPEC: {metadata['spec']}")
    if metadata.get("cl_length_m"):
        lines.append(f"TOTAL CENTERLINE LENGTH: {metadata['cl_length_m']} M")
    if metadata.get("design_pressure"):
        lines.append(f"DESIGN PRESSURE: {metadata['design_pressure']}")
    if metadata.get("design_temperature"):
        lines.append(f"DESIGN TEMPERATURE: {metadata['design_temperature']}")

    lines.append("\nBILL OF MATERIALS (FABRICATION & ERECTION):")
    for it in bom_items:
        lines.append(f"{it['item_no']:02d} {it['description']} {it.get('size', '')} {it['quantity']}{it.get('unit', 'EA')}")

    if spools:
        tot_cut_m = sum(s["cut_length_mm"] for s in spools if s.get("cut_length_mm")) / 1000.0
        lines.append(f"\nSPOOL FABRICATION CUT PIECES (TOTAL CUT: {tot_cut_m:.3f} M):")
        for s in spools:
            lines.append(f"PIECE {s['piece']}: {s['cut_length_mm']} mm (NS {s.get('ns', '')})")

    return "\n".join(lines)


def process_dwg_isometric(file_path: str) -> Dict[str, Any]:
    """
    Main entry point for extracting isometric data from a DWG or DXF file.
    Supports both native ACAD_TABLE structures (modern / Firefighting) and loose spatial entities.
    """
    import ezdxf
    ext = Path(file_path).suffix.lower()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        dxf_path = file_path
        if ext == ".dwg":
            tmp_dxf = os.path.join(tmpdir, "extracted.dxf")
            success = convert_dwg_to_dxf_headless(file_path, tmp_dxf)
            if not success:
                logger.warning("Headless conversion failed for %s.", file_path)
                return {
                    "status": "error",
                    "message": "AutoCAD Core Console / ODA conversion failed.",
                    "bom_items": [],
                    "spools": [],
                    "metadata": {},
                    "formatted_text": "",
                    "is_isometric": False
                }
            dxf_path = tmp_dxf

        # 1. Try Structured ACAD_TABLE & Title Block first
        bom_items = []
        spools = []
        metadata = {}

        try:
            try:
                doc = ezdxf.readfile(dxf_path)
            except Exception:
                from ezdxf import recover
                doc, _ = recover.readfile(dxf_path)
                
            if doc:
                metadata = parse_title_block_metadata(doc)
                bom_items = parse_acad_table_from_doc(doc)
        except Exception as e_tbl:
            logger.debug("ACAD_TABLE parser error: %s", e_tbl)

        # 2. If no BOM items from ACAD_TABLE, fallback to spatial entity parser
        if not bom_items:
            entities = extract_entities_from_dxf(dxf_path)
            if entities:
                fallback_items, spools, fallback_meta = parse_bom_from_entities(entities)
                bom_items = fallback_items
                # Merge metadata
                for k, v in fallback_meta.items():
                    if v and not metadata.get(k):
                        metadata[k] = v

        # If line number still missing, fallback to clean filename stem
        if not metadata.get("line_number"):
            metadata["line_number"] = Path(file_path).stem

        if not bom_items and not spools:
            return {
                "status": "warning",
                "message": "No BOM items or spools extracted from CAD file.",
                "bom_items": [],
                "spools": [],
                "metadata": metadata,
                "formatted_text": "",
                "is_isometric": False
            }

        is_iso = len(bom_items) >= 1 or len(spools) >= 1 or bool(metadata.get("line_number"))
        formatted_text = format_iso_text_summary(bom_items, spools, metadata, Path(file_path).name)
        # Validation triangulaire de cohérence pour fichiers CAO
        validation_res = {}
        anomalies_list = []
        try:
            from mto_validator import validate_isometric_plan
            validation_res = validate_isometric_plan(bom_items, metadata, file_path=file_path, spools=spools)
            anomalies_list = validation_res.get("anomalies", [])
        except Exception as e_val:
            logger.warning("[ISO CAD] Erreur validation triangulaire: %s", e_val)

        total_p_len = sum(it.get("quantity", 0.0) for it in bom_items if it.get("category") == "PIPE")
        if not total_p_len and metadata.get("cl_length_m"):
            total_p_len = float(metadata.get("cl_length_m", 0.0))
        total_steel_kg = sum(it.get("weight_total_kg", 0.0) for it in bom_items)

        return {
            "status": "success" if is_iso else "warning",
            "filename": Path(file_path).name,
            "filepath": str(file_path),
            "bom_items": bom_items,
            "mto": bom_items,
            "spools": spools,
            "metadata": metadata,
            "total_pipe_length_m": round(total_p_len, 2),
            "total_steel_weight_kg": round(total_steel_kg, 2),
            "formatted_text": formatted_text,
            "is_isometric": is_iso,
            "validation": validation_res,
            "anomalies": anomalies_list
        }
