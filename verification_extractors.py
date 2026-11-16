import os
import re
import json
import logging
from pathlib import Path
import docx
from openpyxl import load_workbook

from verification_db import (
    save_attributes,
    get_processed_documents_metadata,
    save_processed_document,
    delete_processed_document,
    clear_document_attributes
)

logger = logging.getLogger(__name__)

# Pattern O&G pour détecter les tags d'équipements principaux
TAG_PATTERN = r"\b([A-Z]{1,4}-\d{2,5}[A-Z0-9]*)\b"


def resolve_project_for_file(file_path: Path) -> dict:
    """Resolve the project name and project_id for a given file path based on its directory structure."""
    try:
        # Resolve path relative to 'data'
        abs_path = file_path.resolve()
        
        # Search for "data" in the parents
        data_idx = -1
        for i, parent in enumerate(abs_path.parents):
            if parent.name.lower() == "data":
                data_idx = i
                break
                
        if data_idx != -1:
            # The immediate child of "data" is the project or "00-Projet"
            proj_parent = abs_path.parents[data_idx - 1]
            if proj_parent.name == "00-Projet" and data_idx >= 2:
                project_dir = abs_path.parents[data_idx - 2].name
            else:
                project_dir = proj_parent.name
                
            project_id = project_dir.lower().replace(" ", "_").replace("&", "and")
            project_name = project_dir
            if "-" in project_dir:
                parts = project_dir.split("-", 1)
                if parts[0].strip().isdigit():
                    project_name = parts[1].strip()
            return {"project_id": project_id, "project_name": project_name}
    except Exception as e:
        logger.debug("Project resolution error for %s: %s", file_path, e)
        
    return {"project_id": "general", "project_name": "Equipements Generaux"}


def extract_attributes_from_docx(file_path: Path) -> list[dict]:
    """Extract attributes from tables and text in a docx file."""
    attributes = []
    proj_info = resolve_project_for_file(file_path)
    filename = file_path.name

    if not file_path.exists():
        return []

    try:
        doc = docx.Document(str(file_path))
        
        # 1. Parse tables
        for table in doc.tables:
            headers = []
            if len(table.rows) > 0:
                headers = [cell.text.strip().lower() for cell in table.rows[0].cells]
                
            # If headers look like an equipment table
            for row in table.rows[1:]:
                cells = [c.text.strip() for c in row.cells]
                if not any(cells):
                    continue
                    
                # Search for tags in row cells
                row_tag = None
                for cell_text in cells:
                    tag_match = re.search(TAG_PATTERN, cell_text)
                    if tag_match:
                        # Exclude document refs like "DAO-99" or "LDBP5"
                        candidate = tag_match.group(1)
                        if not re.match(r"^(DAO|LDBP|REV|DWG|SOW|ANNEXE)\d*$", candidate, re.IGNORECASE):
                            row_tag = candidate.upper()
                            break
                            
                if not row_tag:
                    continue
                    
                # Extract key attributes based on headers
                for h_idx, header in enumerate(headers):
                    if h_idx >= len(cells):
                        continue
                    val = cells[h_idx]
                    if not val or val == row_tag:
                        continue
                        
                    # Standardize attribute names
                    attr_name = None
                    if "spécification" in header or "spec" in header or "caractéristique" in header:
                        attr_name = "technical_spec"
                    elif "désignation" in header or "name" in header or "equipement" in header or "nom" in header:
                        attr_name = "description"
                    elif "fonction" in header or "remarque" in header or "role" in header:
                        attr_name = "function"
                    elif "qté" in header or "quantité" in header or "qty" in header:
                        attr_name = "quantity"
                        
                    if attr_name:
                        attributes.append({
                            "project_id": proj_info["project_id"],
                            "tag": row_tag,
                            "document": filename,
                            "attribute_name": attr_name,
                            "attribute_value": val,
                            "unit": "",
                            "confidence": 1.0
                        })
                        
                        # Sub-extract parameters like pressure, flow, temperature from specification text
                        _parse_sub_attributes(val, row_tag, filename, proj_info["project_id"], attributes)

        # 2. Parse paragraphs for any isolated specification lists
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            # Search for tag: spec pattern
            tag_match = re.search(r"\b([A-Z]{1,4}-\d{2,5}[A-Z0-9]*)\b\s*[:\-]\s*(.*)", text)
            if tag_match:
                tag = tag_match.group(1).upper()
                spec = tag_match.group(2).strip()
                if not re.match(r"^(DAO|LDBP|REV|DWG|SOW|ANNEXE)\d*$", tag, re.IGNORECASE):
                    attributes.append({
                        "project_id": proj_info["project_id"],
                        "tag": tag,
                        "document": filename,
                        "attribute_name": "specification_text",
                        "attribute_value": spec,
                        "unit": "",
                        "confidence": 0.8
                    })
                    _parse_sub_attributes(spec, tag, filename, proj_info["project_id"], attributes)

    except Exception as e:
        logger.error("Error extracting from DOCX %s: %s", filename, e)

    return attributes


def _parse_sub_attributes(text: str, tag: str, document: str, project_id: str, attributes: list):
    """Scan text for engineering properties (pressure, temperature, flow, materials) and append as individual attributes."""
    # Pressure: e.g. "pression 4 bars", "28 bars", "Ps=4b", "Pd=28b"
    pressures = re.findall(r"\b(?:pression|pressures|ps|pd)?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(bar|bars|barg|bara|psi|psig|kpa|mpa)\b", text, re.IGNORECASE)
    for val, unit in pressures:
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "pressure",
            "attribute_value": val.replace(",", "."),
            "unit": unit.lower(),
            "confidence": 0.9
        })

    # Design vs Operating Pressure
    design_pressures = re.findall(r"\b(?:design|calcul|maxi|max\.?)\s*(?:pression|pressure|ps)?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(bar|bars|barg|bara|psi|psig|kpa|mpa)\b", text, re.IGNORECASE)
    for val, unit in design_pressures:
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "design_pressure",
            "attribute_value": val.replace(",", "."),
            "unit": unit.lower(),
            "confidence": 0.95
        })

    op_pressures = re.findall(r"\b(?:operating|service|fonctionnement|normal|opératoire|operatoire)\s*(?:pression|pressure|pop)?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(bar|bars|barg|bara|psi|psig|kpa|mpa)\b", text, re.IGNORECASE)
    for val, unit in op_pressures:
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "operating_pressure",
            "attribute_value": val.replace(",", "."),
            "unit": unit.lower(),
            "confidence": 0.95
        })

    # Flow rate: e.g. "débit 150m3/h", "2.035 Millions de STD m3/jour"
    flows = re.findall(r"\b(?:débit|flow|capacité)?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(m³/h|m3/h|l/min|gpm|Mm³std/j|Mm3std/j|Nm³/h)\b", text, re.IGNORECASE)
    for val, unit in flows:
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "flow_rate",
            "attribute_value": val.replace(",", "."),
            "unit": unit,
            "confidence": 0.9
        })

    # Temperature: e.g. "température -40°C", "200 deg C", "80°C"
    temps = re.findall(r"\b(?:température|temp|ts|td)?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(°C|deg\s*C|celsius)\b", text, re.IGNORECASE)
    for val, unit in temps:
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "temperature",
            "attribute_value": val.replace(",", "."),
            "unit": "°C",
            "confidence": 0.9
        })

    # Design vs Operating Temperature
    design_temps = re.findall(r"\b(?:design|calcul|maxi|max\.?|ts)\s*(?:température|temp|temperature)?\s*[:=]?\s*(-?\d+(?:[.,]\d+)?)\s*(°C|deg\s*C|celsius)\b", text, re.IGNORECASE)
    for val, unit in design_temps:
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "design_temperature",
            "attribute_value": val.replace(",", "."),
            "unit": "°C",
            "confidence": 0.95
        })

    op_temps = re.findall(r"\b(?:operating|service|fonctionnement|normal|opératoire|operatoire)\s*(?:température|temp|temperature)?\s*[:=]?\s*(-?\d+(?:[.,]\d+)?)\s*(°C|deg\s*C|celsius)\b", text, re.IGNORECASE)
    for val, unit in op_temps:
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "operating_temperature",
            "attribute_value": val.replace(",", "."),
            "unit": "°C",
            "confidence": 0.95
        })

    # NPSH: Available (NPSHa) vs Required (NPSHr)
    npshas = re.findall(r"\b(?:npsha|npsh\s*\(a\)|npsh\s*disponible|npsh\s*disp\.?)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(m|meter|meters|mètres|metres)\b", text, re.IGNORECASE)
    for val, unit in npshas:
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "npsha",
            "attribute_value": val.replace(",", "."),
            "unit": "m",
            "confidence": 0.95
        })

    npshrs = re.findall(r"\b(?:npshr|npsh\s*\(r\)|npsh\s*requis|npsh\s*req\.?)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(m|meter|meters|mètres|metres)\b", text, re.IGNORECASE)
    for val, unit in npshrs:
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "npshr",
            "attribute_value": val.replace(",", "."),
            "unit": "m",
            "confidence": 0.95
        })

    # Actuator Fail-Safe Position
    if re.search(r"\b(?:fc|fail\s*closed|fail\s*to\s*close|fermeture\s*de\s*sécurité|fermeture\s*de\s*securite|fermé\s*sur\s*manque|ferme\s*sur\s*manque)\b", text, re.IGNORECASE):
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "fail_safe",
            "attribute_value": "FC",
            "unit": "",
            "confidence": 0.90
        })
    elif re.search(r"\b(?:fo|fail\s*open|fail\s*to\s*open|ouverture\s*de\s*sécurité|ouverture\s*de\s*securite|ouvert\s*sur\s*manque)\b", text, re.IGNORECASE):
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "fail_safe",
            "attribute_value": "FO",
            "unit": "",
            "confidence": 0.90
        })
    elif re.search(r"\b(?:fl|fail\s*last|fail\s*locked|fail\s*as\s*is|dernière\s*position|derniere\s*position)\b", text, re.IGNORECASE):
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "fail_safe",
            "attribute_value": "FL",
            "unit": "",
            "confidence": 0.90
        })

    # Corrosion Allowance
    corrosions = re.findall(r"\b(?:corrosion\s*allowance|surépaisseur\s*de\s*corrosion|surépaisseur|ca)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(mm|millimètre|millimetres|millimetre|millimètres)\b", text, re.IGNORECASE)
    for val, unit in corrosions:
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "corrosion_allowance",
            "attribute_value": val.replace(",", "."),
            "unit": "mm",
            "confidence": 0.95
        })

    # Materials: e.g. "acier inox", "inox 316", "carbon steel"
    materials = re.findall(r"\b(acier\s+inox|acier\s+carbone|carbon\s+steel|stainless\s+steel|316L|304L|ASTM\s+A\d{3}|duplex|inconel)\b", text, re.IGNORECASE)
    for mat in materials:
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "material",
            "attribute_value": mat.strip(),
            "unit": "",
            "confidence": 0.85
        })

    # Sound Pressure Level (noise): e.g. "sound pressure level 85 dBA"
    noises = re.findall(
        r"\b(?:sound\s+pressure\s+level|noise\s+level|niveau\s+de\s+bruit|pression\s+acoustique|sound\s+level)\b.*?\b(\d+(?:[.,]\d+)?)\s*(db|dba|db\(a\))\b",
        text,
        re.IGNORECASE
    )
    # Direct unit pattern fallback (if label is on a different line)
    if not noises:
        noises = re.findall(r"\b(\d+(?:[.,]\d+)?)\s*(dba|db\(a\))\b", text, re.IGNORECASE)

    for val, unit in noises:
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "sound_pressure_level",
            "attribute_value": val.replace(",", "."),
            "unit": unit.lower(),
            "confidence": 0.95
        })

    # Hardness: e.g. "min 220 HB", "220 HB", "hardness maximum 271 HB", "28 HRC"
    hardness = re.findall(r"\b(?:min\.?|max\.?|minimum|maximum)?\s*(\d+)\s*(hb|hrc|hcv)\b", text, re.IGNORECASE)
    for val, unit in hardness:
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "hardness",
            "attribute_value": val,
            "unit": unit.lower(),
            "confidence": 0.9
        })

    # Flange Ratings and Facings (VAL-01 / VAL-02 / VAL-03)
    # 1. Check for asymmetric flange configuration on a single line (e.g. "1500# RTJ 300# RF")
    # We remove the leading word boundary \b to handle text merging (e.g. "Yes1500#")
    dual_match = re.search(r"(\d+)#\s*(rf|rtj)?\b.*?(?:^|[^0-9])(\d+)#\s*(rf|rtj)?\b", text, re.IGNORECASE)
    if dual_match:
        in_val, in_face, out_val, out_face = dual_match.groups()
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "inlet_flange_rating",
            "attribute_value": in_val,
            "unit": "#",
            "confidence": 0.95
        })
        if in_face:
            attributes.append({
                "project_id": project_id,
                "tag": tag,
                "document": document,
                "attribute_name": "inlet_flange_facing",
                "attribute_value": in_face.upper(),
                "unit": "",
                "confidence": 0.95
            })
        attributes.append({
            "project_id": project_id,
            "tag": tag,
            "document": document,
            "attribute_name": "outlet_flange_rating",
            "attribute_value": out_val,
            "unit": "#",
            "confidence": 0.95
        })
        if out_face:
            attributes.append({
                "project_id": project_id,
                "tag": tag,
                "document": document,
                "attribute_name": "outlet_flange_facing",
                "attribute_value": out_face.upper(),
                "unit": "",
                "confidence": 0.95
            })
    else:
        # Single flange rating or facing matches
        single_ratings = re.findall(r"(\d+)\s*(?:#|class|cl)\b", text, re.IGNORECASE)
        for r_val in single_ratings:
            attributes.append({
                "project_id": project_id,
                "tag": tag,
                "document": document,
                "attribute_name": "flange_rating",
                "attribute_value": r_val,
                "unit": "#",
                "confidence": 0.90
            })
        facings = re.findall(r"\b(rf|rtj)\b", text, re.IGNORECASE)
        for f_val in facings:
            attributes.append({
                "project_id": project_id,
                "tag": tag,
                "document": document,
                "attribute_name": "flange_facing",
                "attribute_value": f_val.upper(),
                "unit": "",
                "confidence": 0.90
            })


def extract_attributes_from_xlsx(file_path: Path) -> list[dict]:
    """Extract attributes from Excel spreadsheets."""
    attributes = []
    proj_info = resolve_project_for_file(file_path)
    filename = file_path.name

    if not file_path.exists():
        return []

    try:
        wb = load_workbook(str(file_path), data_only=True)
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            for row in ws.iter_rows(values_only=True):
                # Look for equipment tag
                row_tag = None
                cells = [str(c).strip() for c in row if c is not None]
                if not cells:
                    continue
                    
                for cell_text in cells:
                    tag_match = re.search(TAG_PATTERN, cell_text)
                    if tag_match:
                        candidate = tag_match.group(1)
                        if not re.match(r"^(DAO|LDBP|REV|DWG|SOW|ANNEXE)\d*$", candidate, re.IGNORECASE):
                            row_tag = candidate.upper()
                            break
                            
                if not row_tag:
                    continue
                
                # Treat cells containing numbers with units as attributes
                for cell in cells:
                    if cell == row_tag:
                        continue
                    _parse_sub_attributes(cell, row_tag, filename, proj_info["project_id"], attributes)
    except Exception as e:
        logger.error("Error extracting from XLSX %s: %s", filename, e)

    return attributes


def is_in_legend_or_cartouche(index: int, content: str) -> bool:
    """Helper to detect if a match is inside a legend, title block (cartouche) or revision area."""
    start = max(0, index - 150)
    end = min(len(content), index + 150)
    window = content[start:end].lower()
    for word in ("légende", "legende", "legend", "cartouche", "révision", "revision", "title block", "document title", "dessiné", "drawn", "approved", "approuvé"):
        if word in window:
            return True
    return False


def extract_attributes_from_pfd_html(file_path: Path) -> list[dict]:
    """Extract tags and descriptions from Svg/HTML PFD layout files, filtering out legend/cartouche metadata."""
    attributes = []
    proj_info = resolve_project_for_file(file_path)
    filename = file_path.name

    if not file_path.exists():
        return []

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Extract PFD Tags using pattern matches
        # e.g., FA-1301Q / Ballon aspiration
        pfd_tags = re.finditer(r"\b([A-Z]{2,4}-\d{3,5}[A-Z]?)\b\s*[\n\r]*\s*(?:<[^>]+>\s*)*\s*([A-Za-zÀ-ÿ\s\-–]{3,40})", content)
        for m in pfd_tags:
            tag = m.group(1).upper().strip()
            desc = m.group(2).strip()

            # Ignore tags located in the legend, revision history or title block
            if is_in_legend_or_cartouche(m.start(), content):
                logger.info("Ignoring tag %s (%s) because it is located in a legend/cartouche/revision area.", tag, desc)
                continue

            # Clean description of HTML tags or newlines
            desc = re.sub(r"\s+", " ", desc)
            if len(desc) > 3 and not re.match(r"^(DCS|PSV|PT|TT|FT|Loop|Shelter|Transfo|UPS|MCC|GL|DWG|TDS|Réf)", desc, re.IGNORECASE):
                attributes.append({
                    "project_id": proj_info["project_id"],
                    "tag": tag,
                    "document": filename,
                    "attribute_name": "description",
                    "attribute_value": desc,
                    "unit": "",
                    "confidence": 0.95
                })
                # Add presence attribute
                attributes.append({
                    "project_id": proj_info["project_id"],
                    "tag": tag,
                    "document": filename,
                    "attribute_name": "present_on_p&id",
                    "attribute_value": "True",
                    "unit": "",
                    "confidence": 1.0
                })
    except Exception as e:
        logger.error("Error extracting from PFD HTML %s: %s", filename, e)

    return attributes


def preprocess_fragmented_text(text: str) -> str:
    """Merge fragmented vertical lines in PDF text (common in multi-column or poorly extracted tables)."""
    lines = text.splitlines()
    processed_lines = []
    current_line = []
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue  # SKIP empty lines without flushing!
            
        low = stripped.lower().strip(',.;:')
        if len(stripped) < 15 or stripped.isdigit() or any(x in low for x in ('db', 'dba', 'db(a)', '%')):
            current_line.append(stripped)
        else:
            if current_line:
                processed_lines.append(' '.join(current_line))
                current_line = []
            processed_lines.append(stripped)
            
    if current_line:
        processed_lines.append(' '.join(current_line))
        
    return '\n'.join(processed_lines)


def determine_main_tag(text: str) -> str:
    """Identify the main equipment tag of a document using prefixes and frequency."""
    tags = re.findall(TAG_PATTERN, text)
    valid_tags = []
    for t in tags:
        t_up = t.upper()
        # Exclude common document references
        if re.match(r"^(DAO|LDBP|REV|DWG|SOW|ANNEXE)\d*$", t_up, re.IGNORECASE):
            continue
        # Exclude piping lines
        if t_up.startswith(("PH-", "PL-", "GL-", "PE-", "IE-")):
            continue
        valid_tags.append(t_up)
        
    if not valid_tags:
        return None
        
    # Heuristics for main equipment prefixes
    main_prefixes = ("HV-", "V-", "P-", "PP-", "C-", "K-", "E-", "FA-", "XV-", "PV-", "LV-", "TV-", "SP-", "S-")
    main_tags = [t for t in valid_tags if any(t.startswith(pref) for pref in main_prefixes)]
    
    # Priority for valves and main process equipment over drawings or standards
    primary_prefixes = ("HV-", "V-", "P-", "PP-", "C-", "K-", "E-", "FA-", "XV-", "PV-", "LV-", "TV-")
    primary_tags = [t for t in main_tags if any(t.startswith(pref) for pref in primary_prefixes)]
    if primary_tags:
        return primary_tags[0]
        
    if main_tags:
        return main_tags[0]
        
    return valid_tags[0]


def extract_attributes_from_pdf(file_path: Path) -> list[dict]:
    """Extract attributes from a PDF file using the main PDF extractor and parsing its text statefully."""
    attributes = []
    proj_info = resolve_project_for_file(file_path)
    filename = file_path.name

    if not file_path.exists():
        return []

    try:
        from extractors import extract_pdf
        res = extract_pdf(str(file_path))
        text = res.get("text", "")
        if not text:
            return []

        # Reconstruct fragmented vertical sentences
        cleaned_text = preprocess_fragmented_text(text)
        # Merge spaced digits (e.g. "1 1 0 dBA" -> "110 dBA")
        for _ in range(5):
            cleaned_text = re.sub(r'(\d)[ \t]+(\d)', r'\1\2', cleaned_text)

        # Detect if it is a datasheet
        is_datasheet = "sheet" in filename.lower() or "datasheet" in filename.lower() or "data sheet" in cleaned_text.lower()
        main_tag = None
        if is_datasheet:
            main_tag = determine_main_tag(cleaned_text)
            logger.info("Determined main tag for datasheet %s: %s", filename, main_tag)

        # First pass: find the first valid equipment tag in the document to use as default
        default_tag = None
        for line in cleaned_text.splitlines():
            tag_match = re.search(TAG_PATTERN, line)
            if tag_match:
                candidate = tag_match.group(1).upper()
                if not re.match(r"^(DAO|LDBP|REV|DWG|SOW|ANNEXE)\d*$", candidate, re.IGNORECASE):
                    if not candidate.startswith(("PH-", "PL-", "GL-", "PE-", "IE-")):
                        default_tag = candidate
                        break
        
        current_tag = default_tag

        # Parse text line by line
        for line in cleaned_text.splitlines():
            line_str = line.strip()
            if not line_str:
                continue

            # Update current active tag if we see a tag in the line
            tag_match = re.search(TAG_PATTERN, line_str)
            if tag_match:
                candidate = tag_match.group(1).upper()
                # Exclude document refs and piping line tags (e.g. PH-1115, PL-999)
                if not re.match(r"^(DAO|LDBP|REV|DWG|SOW|ANNEXE)\d*$", candidate, re.IGNORECASE):
                    if not candidate.startswith(("PH-", "PL-", "GL-", "PE-", "IE-")):
                        current_tag = candidate
                    tag_to_use = main_tag if (is_datasheet and main_tag) else current_tag
                    if tag_to_use:
                        # Save a presence / technical spec reference for this line
                        attributes.append({
                            "project_id": proj_info["project_id"],
                            "tag": tag_to_use,
                            "document": filename,
                            "attribute_name": "technical_spec",
                            "attribute_value": line_str,
                            "unit": "",
                            "confidence": 0.8
                        })

            # If we don't have an active tag yet, we can't associate parameters
            tag_to_use = main_tag if (is_datasheet and main_tag) else current_tag
            if not tag_to_use:
                continue

            # Parse sub-attributes (pressure, temp, flow, material, noise) from this line
            _parse_sub_attributes(line_str, tag_to_use, filename, proj_info["project_id"], attributes)
    except Exception as e:
        logger.error("Error extracting from PDF %s: %s", filename, e)

    return attributes


def compute_file_hash(file_path: Path) -> str:
    """Compute the MD5 hash of a file."""
    import hashlib
    hasher = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        logger.error("Failed to compute hash for %s: %s", file_path, e)
        return ""


def scan_and_extract_project_documents(project_dir_path: Path) -> int:
    """Scan all supported documents in a project folder and insert their attributes into SQLite,
    skipping already processed documents that haven't changed.
    """
    if not project_dir_path.exists():
        return 0
        
    # Resolve project_id
    dummy_file = project_dir_path / "dummy.txt"
    proj_info = resolve_project_for_file(dummy_file)
    project_id = proj_info["project_id"]
    
    logger.info("Starting document scan for project_id: %s (dir: %s)", project_id, project_dir_path)
    
    # Load already processed documents metadata
    processed_docs = get_processed_documents_metadata(project_id)
    
    # Find all files currently present on disk and collect their metadata
    current_files = {}  # file_path_str -> {mtime, size, filename, path_obj}
    for root, _, files in os.walk(project_dir_path):
        for file in files:
            path = Path(root) / file
            # Skip temp or system files
            if file.startswith("~$") or file.startswith("."):
                continue
            if not file.endswith((".docx", ".xlsx", ".pdf", ".html")):
                continue
            # For HTML, only scan PFD
            if file.endswith(".html") and "pfd" not in file.lower():
                continue
                
            try:
                file_path_str = str(path.resolve())
                mtime = str(os.path.getmtime(path))
                size = os.path.getsize(path)
                current_files[file_path_str] = {
                    "path_obj": path,
                    "filename": file,
                    "mtime": mtime,
                    "size": size
                }
            except Exception as e:
                logger.error("Error reading file metadata for %s: %s", path, e)
                
    # Detect deleted files (in DB tracking but not on disk)
    for db_file_path in list(processed_docs.keys()):
        if db_file_path not in current_files:
            filename = processed_docs[db_file_path]["filename"]
            logger.info("Document deleted from disk: %s. Cleaning up database.", filename)
            # Delete tracking record
            delete_processed_document(project_id, db_file_path)
            # Delete extracted attributes
            clear_document_attributes(project_id, filename)
            
    # Process files: new, modified, or unchanged
    extracted_count = 0
    for file_path_str, meta in current_files.items():
        path = meta["path_obj"]
        filename = meta["filename"]
        size = meta["size"]
        mtime = meta["mtime"]
        
        is_changed = True
        file_hash = ""
        
        if file_path_str in processed_docs:
            db_meta = processed_docs[file_path_str]
            # Fast check size and modification time
            if db_meta["file_size"] == size and db_meta["last_modified"] == mtime:
                # Check MD5 hash to be 100% sure
                file_hash = compute_file_hash(path)
                if db_meta["file_hash"] == file_hash:
                    is_changed = False
                    
        if not is_changed:
            logger.info("Skipping extraction for unchanged document: %s (using cached attributes)", filename)
            continue
            
        # File is new or changed: extract attributes
        logger.info("Processing new or modified document: %s", filename)
        
        if not file_hash:
            file_hash = compute_file_hash(path)
            
        file_attrs = []
        if filename.endswith(".docx"):
            file_attrs = extract_attributes_from_docx(path)
        elif filename.endswith(".xlsx"):
            file_attrs = extract_attributes_from_xlsx(path)
        elif filename.endswith(".pdf"):
            file_attrs = extract_attributes_from_pdf(path)
        elif filename.endswith(".html") and "pfd" in filename.lower():
            file_attrs = extract_attributes_from_pfd_html(path)
            
        # Wipe old attributes to prevent duplicates/obsolete values
        clear_document_attributes(project_id, filename)
        
        # Save new attributes if any
        if file_attrs:
            save_attributes(file_attrs)
            
        # Save tracking metadata
        save_processed_document(project_id, filename, file_path_str, size, mtime, file_hash)
        extracted_count += 1
        
    return extracted_count
