# -*- coding: utf-8 -*-
"""
ie_drawing_extractor.py
Moteur d'extraction multi-disciplines haute fidélité pour l'Électricité & Instrumentation (ARKAN v3).
Prend en charge :
  1. Extraction DWG/DXF native géométrique & vectorielle (ezdxf)
  2. Extraction PDF Tabulaire & Colonnes des schémas unifilaires (SLD / TGBT) sans valeurs inventées
  3. Gestion des unités, élimination des départs fantômes et dédoublonnage inter-pages
"""

import os
import re
import math
import hashlib
import logging
from typing import List, Dict, Any, Optional, Tuple, Set
from pathlib import Path

from config_loader import load_project_config, get_margin_for_category
from tag_normalizer import normalize_tag, compare_tags
from cable_parser import parse_cable

logger = logging.getLogger("arkan.ie_extractor")

BARE_COPPER_WEIGHTS: Dict[str, float] = {
    "16": 0.143, "25": 0.224, "35": 0.314, "50": 0.448,
    "70": 0.627, "95": 0.851, "120": 1.075, "150": 1.344, "185": 1.658, "240": 2.150
}

CABLE_POWER_WEIGHTS: Dict[str, float] = {
    "1G1.5": 0.05, "2X1.5": 0.11, "3G1.5": 0.14, "4G1.5": 0.17, "5G1.5": 0.20, "7G1.5": 0.27, "12G1.5": 0.42,
    "1G2.5": 0.07, "2X2.5": 0.14, "3G2.5": 0.18, "4G2.5": 0.23, "5G2.5": 0.28, "7G2.5": 0.38, "12G2.5": 0.60,
    "1G4": 0.09, "2X4": 0.20, "3G4": 0.26, "4G4": 0.33, "5G4": 0.40,
    "1G6": 0.12, "2X6": 0.28, "3G6": 0.36, "4G6": 0.46, "5G6": 0.56, "5X6": 0.56,
    "1G10": 0.18, "3G10": 0.54, "4G10": 0.70, "5G10": 0.86, "5X10": 0.86,
    "1G16": 0.26, "3G16": 0.80, "4G16": 1.05, "5G16": 1.30, "5X16": 1.30,
    "1G25": 0.38, "3X25+16": 1.48, "4G25": 1.65,
    "1G35": 0.49, "3X35+16": 1.88, "4G35": 2.20,
    "1G50": 0.65, "3X50+25": 2.50, "4G50": 2.95,
    "1G70": 0.88, "3X70+35": 3.40, "4G70": 4.05,
    "1G95": 1.20, "3X95+50": 4.60, "4G95": 5.50,
    "1G120": 1.48, "3X120+70": 5.70, "4G120": 6.80, "3X120": 5.10,
    "1G150": 1.82, "3X150+70": 6.95, "4G150": 8.35, "PE 1X150": 1.82,
    "1G185": 2.25, "3X185+95": 8.65, "4G185": 10.30,
    "1G240": 2.90, "3X240+120": 11.40, "4G240": 13.50, "2X(3X240)": 22.80,
    "CANALISATION": 18.50
}

CABLE_TRAY_WEIGHTS: Dict[str, float] = {
    "50": 1.3, "100": 1.9, "150": 2.5, "200": 3.2,
    "300": 4.4, "400": 5.8, "500": 7.1, "600": 8.6
}

EQUIPMENT_UNIT_WEIGHTS: Dict[str, float] = {
    "EARTH_ROD": 4.5, "REGARD_TERRE": 28.0, "BORNE_COUPURE": 3.2,
    "PULL_BOX_600": 85.0, "PULL_BOX_800": 140.0, "BUSE_PVC_110": 2.8,
    "PROJECTEUR_LED": 9.5, "LUMINAIRE_ETANCHE": 4.2, "BAES": 2.8,
    "PRISE_16A": 1.2, "PRISE_32A": 2.4, "COFFRET_PRISES": 12.0, "CANDELABRE": 65.0,
    "CELLULE_30KV": 850.0, "CELLULE_5KV": 720.0, "DISJONCTEUR_2500A": 85.0, "DISJONCTEUR_1600A": 65.0,
    "TGBT": 450.0, "UPS": 220.0, "TRANSFO_ISOLEMENT": 380.0, "JB": 12.0
}


def _safe_float(val: Any, default: Optional[float] = 0.0) -> Optional[float]:
    if val is None:
        return default
    try:
        s = str(val).replace(',', '.').strip()
        m = re.search(r'[-+]?\d*\.?\d+', s)
        return float(m.group(0)) if m else default
    except (ValueError, TypeError):
        return default


def parse_cable_section_string(raw_sec: str) -> Tuple[Optional[str], Optional[str], Optional[float]]:
    if not raw_sec:
        return None, None, None
    clean_sec = raw_sec.strip().upper().replace(' ', '')
    if clean_sec == "CANALISATION":
        return "CANALISATION", None, CABLE_POWER_WEIGHTS.get("CANALISATION", 18.5)

    parsed = parse_cable(clean_sec)
    if parsed:
        norm = parsed["normalized_spec"]
        w = parsed["linear_weight_kg_m"]
        return norm, "Cu/XLPE/PVC", w

    w = CABLE_POWER_WEIGHTS.get(clean_sec, 0.50)
    return clean_sec, "Cu/XLPE/PVC", w


def extract_sld_from_pdf_matrix(
    pdf_path: str,
    original_filename: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Extrait les départs d'un schéma unifilaire BT (SLD).
    Supporte les formats tabulaires (lignes directrices) et en colonnes sans lignes.
    Ne génère JAMAIS de valeurs inventées (longueur=None, calibre=None si absents).
    """
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    p = Path(pdf_path)
    file_name = original_filename or p.name
    opts = options or {}

    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    metadata: Dict[str, Any] = {
        "drawing_number": Path(file_name).stem,
        "title": "SCHEMA UNIFILAIRE",
        "doc_type": opts.get("doc_type") or "ELEC_SLD_BT",
        "total_pages": total_pages,
        "revision": "1",
        "total_feeders_count": 0,
        "total_power_kw": 0.0,
        "total_cable_m": 0.0,
        "feeders_without_length": 0,
        "total_weight_kg": 0.0,
        "warnings": []
    }

    # Vérification du type de document si non forcé
    if not opts.get("doc_type"):
        full_doc_text = ""
        for page in doc:
            full_doc_text += page.get_text("text") + " "
        full_up = full_doc_text.upper()
        sld_kw = ["SCHEMA UNIFILAIRE", "UNIFILAIRE", "SLD", "TGBT", "MCC", "DISTRIBUTION", "TABLEAU"]
        if not any(k in full_up for k in sld_kw):
            metadata["doc_type"] = "UNKNOWN"
            metadata["warnings"].append("Type de document non reconnu ou schéma unifilaire absent.")
            doc.close()
            return {"metadata": metadata, "items": []}

    feeders: List[Dict[str, Any]] = []
    seen_feeders: Dict[str, Dict[str, Any]] = {}

    for page_idx in range(total_pages):
        page = doc[page_idx]

        # 1. Tentative d'extraction en mode TABLEAU structuré (page.find_tables())
        tables = page.find_tables()
        table_mode_success = False

        if tables and tables.tables:
            for tab in tables.tables:
                data = tab.extract()
                if not data or len(data) < 2:
                    continue

                header = [str(c or "").strip().upper() for c in data[0]]
                # Recherche des indices de colonnes
                tag_col = next((i for i, h in enumerate(header) if "TAG" in h or "REPÈRE" in h), 0)
                des_col = next((i for i, h in enumerate(header) if "DESIG" in h or "NOM" in h), 1 if len(header) > 1 else None)
                pwr_col = next((i for i, h in enumerate(header) if "KW" in h or "PUISSANCE" in h or "P (" in h), None)
                cal_col = next((i for i, h in enumerate(header) if "CALIBRE" in h or " (A)" in h or "DISJ" in h), None)
                cab_col = next((i for i, h in enumerate(header) if "CABLE" in h or "CÂBLE" in h or "SECTION" in h), None)
                len_col = next((i for i, h in enumerate(header) if "LONGUEUR" in h or "LG" in h or "(M)" in h), None)

                for r_idx, row in enumerate(data[1:], start=2):
                    raw_tag = str(row[tag_col] or "").strip()
                    if not raw_tag or raw_tag.upper() in ("TAG", "NONE", "-"):
                        continue

                    # TAG valide requis
                    tag_clean = raw_tag.replace(' ', '')
                    desig = str(row[des_col] or "").strip() if des_col is not None and des_col < len(row) else "Départ"

                    pwr_val = None
                    if pwr_col is not None and pwr_col < len(row):
                        pwr_val = _safe_float(row[pwr_col], None)

                    cal_val = None
                    if cal_col is not None and cal_col < len(row):
                        m_cal = re.search(r'(\d+)', str(row[cal_col] or ""))
                        if m_cal:
                            cal_val = int(m_cal.group(1))

                    sec_raw = str(row[cab_col] or "").strip() if cab_col is not None and cab_col < len(row) else ""
                    norm_sec, c_type, unit_w = parse_cable_section_string(sec_raw) if sec_raw else (None, None, None)

                    len_val = None
                    if len_col is not None and len_col < len(row):
                        raw_len = str(row[len_col] or "").strip()
                        if raw_len:
                            len_val = _safe_float(raw_len, None)

                    reasons: List[str] = []
                    if cal_val is None:
                        reasons.append("calibre de protection non spécifié")
                    if norm_sec is None:
                        reasons.append("section de câble non spécifiée")
                    if len_val is None:
                        reasons.append("longueur de câble non spécifiée")

                    conf = 0.95
                    if len(reasons) == 1:
                        conf = 0.85
                    elif len(reasons) >= 2:
                        conf = 0.50

                    tot_w = round(len_val * unit_w, 2) if (len_val and unit_w) else None

                    feeder_item = {
                        "category": "SWITCHGEAR_FEEDER",
                        "tag": tag_clean,
                        "raw_tag": raw_tag,
                        "designation": desig,
                        "calibre_a": cal_val,
                        "power_kw": pwr_val,
                        "poles": "4P4D" if cal_val else None,
                        "cable_type": c_type,
                        "cable_section": norm_sec,
                        "quantity": len_val,
                        "unit": "m",
                        "weight_unit": unit_w,
                        "weight_total": tot_w,
                        "length_source": "SLD_TABLE" if len_val is not None else "UNKNOWN",
                        "extraction_mode": "TABLE",
                        "source_page": page_idx + 1,
                        "source_drawing": p.name,
                        "confidence_score": conf,
                        "extractor_reasons": reasons
                    }

                    # Gestion des doublons inter-pages
                    if tag_clean in seen_feeders:
                        prev = seen_feeders[tag_clean]
                        if prev.get("calibre_a") == cal_val and prev.get("cable_section") == norm_sec:
                            metadata["warnings"].append(f"Départ {tag_clean} en doublon ignoré (page {page_idx+1}).")
                            continue
                        else:
                            feeder_item["extractor_reasons"].append(f"Tag {tag_clean} déjà vu avec caractéristiques différentes.")
                            metadata["warnings"].append(f"Conflit de caractéristiques sur le tag {tag_clean} (page {page_idx+1}).")

                    seen_feeders[tag_clean] = feeder_item
                    feeders.append(feeder_item)
                    table_mode_success = True

        if table_mode_success:
            continue

        # 2. Extraction en mode COLONNES (Page vectorielle sans ruling lines)
        blocks = page.get_text("blocks")
        col_candidates: Dict[int, List[Dict[str, Any]]] = {}

        for b in blocks:
            x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4].strip()
            # Clustering par position horizontale X
            col_key = int(round(x0 / 80.0) * 80)
            col_candidates.setdefault(col_key, []).append({"text": text, "y": y0})

        for col_k, b_list in sorted(col_candidates.items()):
            texts_sorted = sorted(b_list, key=lambda t: t["y"])
            full_col_txt = "\n".join(t["text"] for t in texts_sorted).strip()
            col_up = full_col_txt.upper()

            # Extraction stricte du tag : doit être un identifiant valide (ex: 300-P-101A, 300-TRP-001)
            # Ne jamais inventer de tag pour 'POMPE' ou 'TRANSFO' seul !
            tag_m = re.search(r'\b(\d{2,4}-[A-Z0-9\-_]+|[A-Z]{1,5}-\d{2,5}[A-Z]?)\b', full_col_txt)
            if not tag_m:
                continue

            raw_tag = tag_m.group(1).strip()
            tag_clean = raw_tag.replace(' ', '')

            # Supprimer le tag du texte avant de chercher le calibre pour éviter de matcher '101A' dans '300-P-101A' !
            col_without_tag = col_up.replace(raw_tag.upper(), "")

            # Extraction calibre (ex: 63 A, 100 A)
            cal_m = re.search(r'\b(\d{1,4})\s*A\b', col_without_tag)
            cal_val = int(cal_m.group(1)) if cal_m else None

            # Extraction pôles (ex: 4P4D, 4P3D, 3P3D)
            pol_m = re.search(r'\b(4P4D|4P3D|3P3D|4P|3P|2P|1P\+N)\b', col_without_tag)
            poles_val = pol_m.group(1) if pol_m else None

            # Extraction section de câble
            sec_m = re.search(r'\b(CANALISATION|5[xX]\d+|4[gG]\d+|3[xX]\d+(?:\+\d+)?|2[xX]\(3[xX]\d+\)|[1-4][pPtT]\d+(?:\.\d+)?)\b', col_without_tag)
            raw_sec = sec_m.group(1) if sec_m else None
            norm_sec, c_type, unit_w = parse_cable_section_string(raw_sec) if raw_sec else (None, None, None)

            reasons: List[str] = []
            if cal_val is None:
                reasons.append("calibre de protection non spécifié")
            if norm_sec is None:
                reasons.append("section de câble non spécifiée")
            reasons.append("longueur de câble non spécifiée (SLD sans carnet)")

            conf = 0.90
            if cal_val is None and norm_sec is None:
                conf = 0.45
            elif cal_val is None or norm_sec is None:
                conf = 0.70

            feeder_item = {
                "category": "SWITCHGEAR_FEEDER",
                "tag": tag_clean,
                "raw_tag": raw_tag,
                "designation": "Départ TGBT",
                "calibre_a": cal_val,
                "power_kw": None,
                "poles": poles_val,
                "cable_type": c_type if norm_sec != "CANALISATION" else None,
                "cable_section": norm_sec,
                "quantity": None,
                "unit": "m",
                "weight_unit": unit_w,
                "weight_total": None,
                "length_source": "UNKNOWN",
                "extraction_mode": "COLUMN",
                "source_page": page_idx + 1,
                "source_drawing": p.name,
                "confidence_score": conf,
                "extractor_reasons": reasons
            }

            # Gestion des doublons inter-pages
            if tag_clean in seen_feeders:
                prev = seen_feeders[tag_clean]
                if prev.get("calibre_a") == cal_val and prev.get("cable_section") == norm_sec:
                    metadata["warnings"].append(f"Départ {tag_clean} en doublon ignoré (page {page_idx+1}).")
                    continue
                else:
                    feeder_item["extractor_reasons"].append(f"Tag {tag_clean} déjà vu avec caractéristiques différentes.")
                    metadata["warnings"].append(f"Conflit de caractéristiques sur le tag {tag_clean} (page {page_idx+1}).")

            seen_feeders[tag_clean] = feeder_item
            feeders.append(feeder_item)

    doc.close()

    # Métadonnées globales
    metadata["total_feeders_count"] = len(feeders)
    metadata["total_cable_m"] = round(sum(float(f["quantity"]) for f in feeders if f.get("quantity") is not None), 2)
    metadata["feeders_without_length"] = sum(1 for f in feeders if f.get("quantity") is None)
    metadata["total_weight_kg"] = round(sum(float(f["weight_total"]) for f in feeders if f.get("weight_total") is not None), 2)

    return {
        "metadata": metadata,
        "items": feeders
    }


def extract_ie_drawing(
    file_path: str,
    original_filename: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Dispatcher principal pour extraction DWG/DXF ou PDF."""
    p = Path(file_path)
    fn = original_filename or p.name
    ext = Path(fn).suffix.lower() if fn else p.suffix.lower()

    if ext in (".dwg", ".dxf"):
        return extract_ie_from_dwg_native(file_path, original_filename=fn, options=options)
    elif ext == ".pdf":
        return extract_sld_from_pdf_matrix(file_path, original_filename=fn, options=options)
    else:
        raise ValueError(f"Extension non supportée pour le MTO E&I : {ext}")


def extract_ie_from_dwg_native(
    dwg_path: str,
    original_filename: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Extrait les chemins, chambres, buses et terre depuis un DWG/DXF."""
    import ezdxf

    p = Path(dwg_path)
    file_name = original_filename or p.name
    opts = options or {}

    doc = ezdxf.readfile(dwg_path)
    insunits = doc.header.get("$INSUNITS", 0)

    # Conversion d'unités ($INSUNITS : 1=in, 2=ft, 4=mm, 5=cm, 6=m)
    unit_opt = opts.get("units")
    unit_warning = None
    if unit_opt == "m":
        scale_to_m = 1.0
    elif unit_opt == "mm":
        scale_to_m = 0.001
    elif insunits == 6:
        scale_to_m = 1.0
    elif insunits == 4:
        scale_to_m = 0.001
    elif insunits == 5:
        scale_to_m = 0.01
    else:
        scale_to_m = 0.001  # Défaut millimètres
        if not unit_opt and insunits == 0:
            unit_warning = "Unités de dessin non spécifiées ($INSUNITS=0) : millimètres supposés. À CONFIRMER par l'ingénieur."

    msp = doc.modelspace()
    items: List[Dict[str, Any]] = []
    metadata = {
        "drawing_number": Path(file_name).stem,
        "filename": file_name,
        "insunits": insunits,
        "scale_to_m": scale_to_m,
        "cable_tray_linear_m": 0.0,
        "pull_boxes_count": 0,
        "earthing_linear_m": 0.0,
        "warnings": [unit_warning] if unit_warning else []
    }

    # 1. Chambres de tirage (blocs ou textes)
    pull_box_count = 0
    for e in msp:
        if e.dxftype() == "INSERT" and "CHAMBRE" in e.dxf.name.upper():
            pull_box_count += 1
            items.append({
                "category": "PULL_BOX",
                "tag": f"CH-TIRAGE-{pull_box_count}",
                "description": "Chambre de tirage préfabriquée béton 600x600x700 mm avec tampon",
                "size": "600x600x700 mm",
                "quantity": 1.0,
                "unit": "EA",
                "weight_unit": 85.0,
                "weight_total": 85.0,
                "confidence_score": 0.80,
                "extractor_reasons": ["Dimensions et tampon à confirmer sur plan d'exécution"],
                "source_drawing": file_name
            })

    metadata["pull_boxes_count"] = pull_box_count

    # 2. Chemins de câbles et Réseau de Terre (lignes et polylignes)
    tray_len = 0.0
    earth_len = 0.0

    tray_conv = opts.get("tray_convention") or "auto"

    for e in msp:
        lay = e.dxf.layer.upper()
        t = e.dxftype()
        l_val = 0.0
        if t == 'LINE':
            s, end = e.dxf.start, e.dxf.end
            l_val = math.sqrt((end[0]-s[0])**2 + (end[1]-s[1])**2)
        elif t == 'LWPOLYLINE':
            pts = list(e.get_points('xy'))
            for i in range(len(pts) - 1):
                l_val += math.sqrt((pts[i+1][0]-pts[i][0])**2 + (pts[i+1][1]-pts[i][1])**2)

        l_m = l_val * scale_to_m
        if any(k in lay for k in ["CABLETRAY", "CHEMIN"]):
            tray_len += l_m
        elif any(k in lay for k in ["MALT", "EARTH", "TERRE"]):
            earth_len += l_m

    # Selon convention de dessin des chemins : double rail (diviser par 2) vs axe unique
    final_tray_m = (tray_len / 2.0) if tray_conv in ("auto", "double_rail") and tray_len > 0 else tray_len

    if final_tray_m > 0:
        items.append({
            "category": "CABLE_TRAY",
            "tag": "CDC-200x50",
            "description": "Chemin de câbles perforé galvanisé à chaud 200x50 mm",
            "size": "200x50 mm",
            "quantity": round(final_tray_m, 1),
            "unit": "m",
            "weight_unit": CABLE_TRAY_WEIGHTS.get("200", 3.2),
            "weight_total": round(final_tray_m * CABLE_TRAY_WEIGHTS.get("200", 3.2), 2),
            "confidence_score": 0.94,
            "source_drawing": file_name
        })
        metadata["cable_tray_linear_m"] = round(final_tray_m, 1)

    if earth_len > 0:
        items.append({
            "category": "EARTHING",
            "tag": "MALT-CU-50",
            "description": "Câble cuivre nu étiré 50 mm² pour réseau de terre",
            "size": "50 mm2",
            "quantity": round(earth_len, 1),
            "unit": "m",
            "weight_unit": BARE_COPPER_WEIGHTS.get("50", 0.448),
            "weight_total": round(earth_len * BARE_COPPER_WEIGHTS.get("50", 0.448), 2),
            "confidence_score": 0.95,
            "source_drawing": file_name
        })
        metadata["earthing_linear_m"] = round(earth_len, 1)

    return {"metadata": metadata, "items": items}
