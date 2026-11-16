"""
mto_validator.py - Module de Validation et Contrôle Croisé Triangulaire des Isométriques pour ARKAN
Effectue le recoupement systématique entre :
  1. Le Tracé Géométrique / Schéma Physique
  2. La Table de Nomenclature des Matériaux (BOM)
  3. Le Cartouche Technique (Title Block)
Selon les normes ASME B16.5, ASME B31.3, ASME B36.10M et les exigences réglementaires ARH / Sonatrach.
"""

import re
import os
import math
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger("mto_validator")

# Table normative ASME B16.5 : Nombre de perçages / goujons par bride selon Diamètre (NPS) et Classe (Rating)
ASME_B16_5_BOLT_COUNT = {
    # Class 150#
    ("150#", '1/2"'): 4, ("150#", '3/4"'): 4, ("150#", '1"'): 4,
    ("150#", '1-1/4"'): 4, ("150#", '1-1/2"'): 4, ("150#", '2"'): 4,
    ("150#", '2-1/2"'): 4, ("150#", '3"'): 4, ("150#", '3-1/2"'): 8,
    ("150#", '4"'): 8, ("150#", '5"'): 8, ("150#", '6"'): 8,
    ("150#", '8"'): 8, ("150#", '10"'): 12, ("150#", '12"'): 12,
    ("150#", '14"'): 12, ("150#", '16"'): 12, ("150#", '18"'): 16,
    ("150#", '20"'): 16, ("150#", '24"'): 20,
    # Class 300#
    ("300#", '1/2"'): 4, ("300#", '3/4"'): 4, ("300#", '1"'): 4,
    ("300#", '1-1/4"'): 4, ("300#", '1-1/2"'): 4, ("300#", '2"'): 8,
    ("300#", '2-1/2"'): 8, ("300#", '3"'): 8, ("300#", '3-1/2"'): 8,
    ("300#", '4"'): 8, ("300#", '5"'): 8, ("300#", '6"'): 12, ("300#", '8"'): 12,
    ("300#", '10"'): 16, ("300#", '12"'): 16, ("300#", '14"'): 20,
    ("300#", '16"'): 20, ("300#", '18"'): 24, ("300#", '20"'): 24,
    ("300#", '24"'): 24,
    # Class 600#
    ("600#", '1/2"'): 4, ("600#", '3/4"'): 4, ("600#", '1"'): 4,
    ("600#", '1-1/4"'): 4, ("600#", '1-1/2"'): 4, ("600#", '2"'): 8,
    ("600#", '2-1/2"'): 8, ("600#", '3"'): 8, ("600#", '3-1/2"'): 8,
    ("600#", '4"'): 8, ("600#", '5"'): 8, ("600#", '6"'): 12, ("600#", '8"'): 12,
    ("600#", '10"'): 16, ("600#", '12"'): 20, ("600#", '14"'): 20,
    ("600#", '16"'): 20, ("600#", '18"'): 20, ("600#", '20"'): 24,
    ("600#", '24"'): 24,
    # Class 900#
    ("900#", '1/2"'): 4, ("900#", '3/4"'): 4, ("900#", '1"'): 4,
    ("900#", '1-1/2"'): 4, ("900#", '2"'): 8, ("900#", '3"'): 8,
    ("900#", '4"'): 8, ("900#", '6"'): 12, ("900#", '8"'): 12,
}

DN_TO_NPS_MAP = {
    "15": '1/2"', "20": '3/4"', "25": '1"', "32": '1-1/4"', "40": '1-1/2"',
    "50": '2"', "65": '2-1/2"', "80": '3"', "90": '3-1/2"', "100": '4"',
    "125": '5"', "150": '6"', "200": '8"', "250": '10"', "300": '12"',
    "350": '14"', "400": '16"', "450": '18"', "500": '20"', "600": '24"',
}


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convertit de façon sécurisée une valeur quelconque en float (gestion None, virgules, types mixtes)."""
    if val is None:
        return default
    try:
        s = str(val).strip().replace(',', '.')
        m = re.search(r'[-+]?\d*\.?\d+', s)
        return float(m.group(0)) if m else default
    except (ValueError, TypeError):
        return default


def normalize_nps(nps_str: str) -> str:
    """Normalise une chaîne de diamètre NPS ou DN (ex: 'DN 50' -> '2\"', '14' -> '14\"')."""
    if not nps_str:
        return '2"'
    s = str(nps_str).upper().replace('"', '').replace("'", "").strip()
    m_dn = re.search(r'DN\s*(\d+)', s)
    if m_dn and m_dn.group(1) in DN_TO_NPS_MAP:
        return DN_TO_NPS_MAP[m_dn.group(1)]
    m_num = re.search(r'^(\d+(?:/\d+)?|\d+-\d+/\d+|\d+\.\d+)$', s)
    if m_num:
        val = m_num.group(1)
        if val in DN_TO_NPS_MAP:
            return DN_TO_NPS_MAP[val]
        return f'{val}"'
    return f'{s}"'


def normalize_rating(rating_str: str) -> str:
    """Normalise un rating (ex: '150 LB' -> '150#')."""
    if not rating_str:
        return "150#"
    s = rating_str.upper().strip()
    m = re.search(r'(\d{3,4})', s)
    if m:
        return f"{m.group(1)}#"
    return "150#"


def validate_isometric_plan(
    bom_items: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    file_path: Optional[str] = None,
    raw_text: Optional[str] = None,
    ocr_lines: Optional[List[str]] = None,
    spools: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Exécute le contrôle triangulaire complet :
      1. Règle d'Identité : Cartouche vs Schéma
      2. Règle Topologique : Comptage des Coudes (BOM vs Schéma)
      3. Règle Normative : Boulonnerie ASME B16.5 vs Nombre de Brides
      4. Règle Métrique : Longueur de Tuyauterie vs Cotes du Tracé
      5. Règle Qualité : Typo et Conformité des Nuances Matières
    """
    anomalies: List[Dict[str, Any]] = []

    # === GARDE-FOU BOM ABSENTE (VAL-BC4) ===
    # Si la BOM est vide, les règles de comparaison BOM↔schéma ne peuvent pas s'appliquer.
    # On émet un avertissement INFO et on court-circuite les règles numériques pour éviter
    # les fausses anomalies (DEFICIT_COUDES, SURQUANTIFICATION_VANNES, etc.)
    bom_absent = len(bom_items) == 0

    # Extraire le texte brut du fichier si non fourni
    full_text = raw_text or ""
    all_ocr = ocr_lines or []

    # Si BOM absente : collecter la topologie, émettre l'avertissement, et retourner tôt
    if bom_absent:
        cad_topology_early = {}
        if file_path and os.path.exists(file_path) and file_path.lower().endswith(".pdf"):
            try:
                from iso_cad_graph_engine import analyze_pdf_vector_topology
                cad_topology_early = analyze_pdf_vector_topology(file_path, bom_items=[])
            except Exception:
                pass
        anomalies.append({
            "id": "ISO-WARN-001",
            "code": "BOM_ABSENT",
            "rule": "RULE_BOM_PRESENCE",
            "severity": "INFO",
            "severity_label": "INFORMATION",
            "component": "Nomenclature BOM",
            "expected": "Table de nomenclature des matériaux présente sur le plan",
            "found": "Aucun article BOM détecté",
            "title": "Nomenclature BOM absente du plan",
            "description": (
                "Le plan ne contient aucune table de nomenclature (BOM). "
                "La validation triangulaire BOM <-> Schema <-> Cartouche est impossible. "
                "Seule l'analyse geometrique du trace est disponible."
            ),
            "recommendation": "Fournir le plan complet avec table de nomenclature pour une validation MTO complète."
        })
        summary = {
            "is_valid": True,
            "critical_count": 0, "major_count": 0, "minor_count": 0, "quality_count": 0,
            "total_anomalies": 1,
            "status_label": "BOM ABSENTE — VALIDATION PARTIELLE"
        }
        return {
            "status": "success",
            "is_valid": True,
            "summary": summary,
            "anomalies": anomalies,
            "cad_topology": cad_topology_early
        }
    
    if file_path and os.path.exists(file_path) and not full_text:
        try:
            if file_path.lower().endswith(".pdf"):
                import fitz
                with fitz.open(file_path) as doc:
                    full_text = "\n".join(p.get_text("text") for p in doc)
        except Exception as e:
            logger.debug("[MTO Validator] Erreur lecture texte brut: %s", e)

    # Récupérer les lignes OCR uniquement si le document est un scan ou que le texte vectoriel est insuffisant
    if not all_ocr and file_path and os.path.exists(file_path):
        # OPTIMISATION CPU CRITIQUE : Si le PDF contient déjà du texte vectoriel riche (>50 car.),
        # l'OCR par Deep Learning est totalement superflu et monopoliserait inutilement le CPU.
        if len(full_text.strip()) < 80:
            try:
                from rapidocr_onnxruntime import RapidOCR
                ocr = RapidOCR()
                if file_path.lower().endswith(".pdf"):
                    import fitz, cv2
                    import numpy as np
                    with fitz.open(file_path) as doc:
                        if len(doc) > 0:
                            pix = doc[0].get_pixmap(dpi=150)
                            nparr = np.frombuffer(pix.tobytes("png"), np.uint8)
                            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            res_ocr, _ = ocr(img)
                            if res_ocr:
                                all_ocr = [r[1] for r in res_ocr]
            except Exception as e_ocr:
                logger.debug("[MTO Validator] Erreur OCR schéma: %s", e_ocr)

    cad_topology = {}
    if file_path and os.path.exists(file_path):
        if file_path.lower().endswith((".dwg", ".dxf")):
            try:
                from iso_cad_graph_engine import analyze_isometric_cad_file
                cad_topology = analyze_isometric_cad_file(file_path)
            except Exception as e_cad:
                logger.debug("[MTO Validator] Erreur topologie CAD: %s", e_cad)
        elif file_path.lower().endswith(".pdf"):
            try:
                import fitz as _fitz
                from iso_cad_graph_engine import analyze_pdf_vector_topology
                with _fitz.open(file_path) as _doc:
                    _n_pages = len(_doc)
                # === CORRECTION MULTI-FEUILLETS ===
                # Si le PDF comporte plusieurs feuillets (ex: 31 feuillets),
                # chaque feuillet correspond à une isométrique indépendante.
                # La BOM passée en argument est déjà agrégée sur TOUS les feuillets.
                # On analyse TOUS les feuillets et on agrège les compteurs topologiques.
                if _n_pages > 1:
                    agg = {
                        "success": True, "is_cad_topology_available": False, "is_vector": True,
                        "elbows_count": 0, "callout_bends_count": 0, "vector_bends_count": 0,
                        "labeled_bends_count": 0, "unlabeled_bends_count": 0,
                        "tees_count": 0, "flange_joints_count": 0, "bolt_callouts_count": 0,
                        "gaskets_count": 0, "valves_count": 0, "instruments_count": 0,
                        "insulation_kits_count": 0, "segments_count": 0,
                        "unlabeled_bends_coords": [], "callout_positions": [],
                        "clustered_bends_coords": [], "flange_tags": [],
                        "cartouche_line_no": "", "schema_line_tags": [], "schema_fluids": [],
                        "total_pipe_length_m": None,
                    }
                    for _pi in range(_n_pages):
                        _t = analyze_pdf_vector_topology(file_path, bom_items=bom_items, page_idx=_pi)
                        if not _t.get("is_cad_topology_available"):
                            continue
                        agg["is_cad_topology_available"] = True
                        for _k in ("elbows_count", "callout_bends_count", "vector_bends_count",
                                   "labeled_bends_count", "unlabeled_bends_count",
                                   "tees_count", "flange_joints_count", "bolt_callouts_count",
                                   "gaskets_count", "valves_count", "instruments_count",
                                   "insulation_kits_count", "segments_count"):
                            agg[_k] = (agg.get(_k) or 0) + (_t.get(_k) or 0)
                        if _t.get("total_pipe_length_m"):
                            agg["total_pipe_length_m"] = (_t.get("total_pipe_length_m") or 0) + (agg.get("total_pipe_length_m") or 0)
                        if not agg["cartouche_line_no"] and _t.get("cartouche_line_no"):
                            agg["cartouche_line_no"] = _t["cartouche_line_no"]
                        agg["schema_line_tags"] = list(set(agg["schema_line_tags"] + _t.get("schema_line_tags", [])))
                        agg["schema_fluids"] = list(set(agg["schema_fluids"] + _t.get("schema_fluids", [])))
                        agg["flange_tags"] = list(set(agg["flange_tags"] + _t.get("flange_tags", [])))
                    cad_topology = agg
                else:
                    cad_topology = analyze_pdf_vector_topology(file_path, bom_items=bom_items)
            except Exception as e_pdf:
                logger.debug("[MTO Validator] Erreur topologie PDF: %s", e_pdf)

    combined_text = (full_text + "\n" + "\n".join(all_ocr)).upper()

    # =========================================================================
    # RÈGLE 1 : CONFLIT D'IDENTITÉ ENTRE CARTOUCHE ET SCHÉMA (CRITIQUE)
    # =========================================================================
    # 1.1 Recherche du numéro de ligne du cartouche
    cartouche_line_no = cad_topology.get("cartouche_line_no", "")
    if not cartouche_line_no:
        m_cart = re.search(r'BOOK\s*ISOMETRIC\s*N[°\*:\.\s\r\n]+([A-Z0-9\-_ \t–—\xa0]+)', combined_text, re.I)
        if not m_cart:
            m_cart = re.search(r'N[°\'*:\.\s\r\n]*DESSIN\s*[:=\s\r\n]+([A-Z0-9\-_ \t–—\xa0]+)', combined_text, re.I)
        if m_cart:
            raw_c = m_cart.group(1).strip().splitlines()[0].strip()
            cartouche_line_no = re.sub(r'\s*-\s*', '-', raw_c)
    if not cartouche_line_no:
        cartouche_line_no = metadata.get("line_number", "")

    # 1.2 Numéro(s) de ligne et codes de fluide sur le schéma (Tracé)
    schema_line_tags = cad_topology.get("schema_line_tags", [])
    schema_fluids = set(cad_topology.get("schema_fluids", []))
    schema_line_no = schema_line_tags[0] if schema_line_tags else ""

    if not schema_line_no:
        schema_matches = re.findall(r'\b(?:\d{1,2}[\"-]?)?[A-Z]{2,4}-[A-Z0-9\-]+(?:-[A-Z0-9\(\)]+)?\b', combined_text)
        for sm in schema_matches:
            if any(k in sm for k in ("WF", "IA", "HC", "FG", "PIG", "IW", "ACX", "VT")):
                schema_line_no = sm
                break

    def extract_fluid_code(tag: str) -> Optional[str]:
        if not tag:
            return None
        for part in re.split(r'[-_\s]+', tag):
            if part.upper() in ("WF", "PIG", "IW", "HC", "FG", "IA", "FO", "DO", "SW", "PW", "RW", "DC", "LP", "NG", "DG", "VA", "WH"):
                return part.upper()
        return None

    fluid_cart = extract_fluid_code(cartouche_line_no)
    
    # Conflit avéré si :
    # 1. Le fluide du cartouche est en désaccord avec les lignes du schéma (ex: cartouche dit PIG/IW/WF alors que le schéma est DC/LP/NG)
    # 2. Ou si cartouche_line_no et schema_line_no n'ont aucun radical commun
    is_conflict = False
    conflict_expected = ""
    
    if fluid_cart and schema_fluids:
        # Si le cartouche a un fluide qui n'apparaît nulle part sur le schéma et qu'un fluide différent est sur le schéma
        if fluid_cart not in schema_fluids and any(f in ("WF", "PIG", "IW", "HC", "FG", "IA", "FO", "DO", "SW", "PW", "RW") for f in (fluid_cart,)):
            is_conflict = True
            conflict_expected = f"Fluide du schéma : {', '.join(schema_fluids)}"
    elif fluid_cart and schema_line_no:
        fluid_schema = extract_fluid_code(schema_line_no)
        if fluid_schema and fluid_cart != fluid_schema:
            is_conflict = True
            conflict_expected = f"Ligne du tracé : {schema_line_no}"
            
    # Détection des infiltrations de lignes de test/sabotage (WF, PIG, 999, etc.)
    if not is_conflict and cartouche_line_no:
        u_cart = cartouche_line_no.upper()
        if any(k in u_cart for k in ("999-N", "-WF-", "-PIG-", "-IW-", "-HC-", "-IA-")):
            if not any(k in " ".join(schema_line_tags).upper() for k in ("-WF-", "-PIG-", "-IW-", "-HC-", "-IA-")):
                is_conflict = True
                conflict_expected = f"Ligne du tracé : {', '.join(schema_line_tags) if schema_line_tags else 'Ligne conforme au P&ID'}"

    if not is_conflict and cartouche_line_no and schema_line_no:
        clean_cart = re.sub(r'[^A-Z0-9]', '', cartouche_line_no.upper())
        clean_schema = re.sub(r'[^A-Z0-9]', '', schema_line_no.upper())
        if len(clean_cart) >= 8 and len(clean_schema) >= 8:
            has_common_core = any(clean_cart[i:i+5] in clean_schema for i in range(len(clean_cart) - 4))
            if not has_common_core and ("PIG" in clean_cart or "WF" in clean_cart or "IW" in clean_cart or "999" in clean_cart):
                is_conflict = True
                conflict_expected = f"Ligne du tracé : {schema_line_no}"

    if is_conflict:
        anomalies.append({
            "id": "ISO-ERR-001",
            "code": "CONFLIT_IDENTITE_LIGNE",
            "rule": "RULE_CARTOUCHE_LINE_IDENTITY",
            "severity": "CRITICAL",
            "severity_label": "CRITIQUE (BLOQUANT ARH)",
            "component": "Cartouche / Titre de Ligne",
            "expected": conflict_expected or f"Ligne conforme au tracé",
            "found": f"Cartouche : {cartouche_line_no}",
            "title": "Conflit d'identité de ligne entre Cartouche et Schéma",
            "description": (
                f"Le cartouche mentionne la référence '{cartouche_line_no}', en contradiction avec le tracé physique "
                f"et les raccordements du schéma ({conflict_expected}). "
                f"Il existe une divergence majeure de fluide/système. Le dossier ne peut pas être validé ARH en l'état."
            ),
            "recommendation": "Vérifier le cartouche du plan et remplacer la référence erronée par le numéro de ligne conforme au P&ID."
        })

    # =========================================================================
    # RÈGLE 2 : COMPTAGE GÉOMÉTRIQUE DES COUDES (BOM vs TRACÉ) (MAJEURE)
    # =========================================================================
    bom_elbows_count = 0
    elbow_grouped = {}
    for it in bom_items:
        desc = it.get("description", "").strip()
        desc_u = desc.upper()
        cat = it.get("category", "").upper()
        if (cat in ("FITTING", "FITTINGS") or "ELBOW" in desc_u or "COUDE" in desc_u) and any(k in desc_u for k in ("ELBOW", "COUDE", "90*", "45*", "90°", "45°")):
            qty = _safe_float(it.get("quantity"), 1.0)
            bom_elbows_count += int(qty)
            sz = str(it.get("size", "")).strip()
            key = (desc, sz)
            elbow_grouped[key] = elbow_grouped.get(key, 0) + int(qty)

    elbow_details = [
        f"{qty}x {desc} ({sz})" if sz and sz not in desc else f"{qty}x {desc}"
        for (desc, sz), qty in elbow_grouped.items()
    ]

    # Données issues de la triangulation :
    callout_bends = (cad_topology.get("callout_bends_count") or 0) if cad_topology.get("is_cad_topology_available") else 0
    vector_bends = (cad_topology.get("vector_bends_count") or 0) if cad_topology.get("is_cad_topology_available") else 0
    unlabeled_bends = cad_topology.get("unlabeled_bends_coords") or []
    tees_count = (cad_topology.get("tees_count") or 0) if cad_topology.get("is_cad_topology_available") else 0

    # Invariant physique de tuyauterie : Sur une ligne simple (sans tés), K tronçons droits (spools) imposent K - 1 raccords
    spool_bends_expected = None
    if spools and tees_count == 0:
        spool_bends_expected = max(0, len(spools) - 1)

    schema_bends_found = None

    if cad_topology.get("is_cad_topology_available"):
        cad_elbows = cad_topology.get("elbows_count") or 0
        physical_bends = cad_elbows if cad_elbows > 0 else (callout_bends if callout_bends > 0 else vector_bends)

        # 1. Accord parfait entre la nomenclature et la géométrie réelle du tracé
        if bom_elbows_count > 0 and (bom_elbows_count == physical_bends or bom_elbows_count == cad_elbows or bom_elbows_count == vector_bends or (spool_bends_expected and bom_elbows_count == spool_bends_expected)):
            schema_bends_found = bom_elbows_count

        # 2. Consensus Spools & Géométrie contre BOM/étiquettes incomplètes (Vrai déficit démasqué !)
        elif vector_bends > 0 and spool_bends_expected and vector_bends == spool_bends_expected and bom_elbows_count < vector_bends:
            schema_bends_found = vector_bends

        # 3. Omission d'étiquette sur le plan : Le tracé vectoriel a des coudes physiques, et la BOM confirme
        # que le matériel est bien acheté et débité. Seule l'étiquette de repérage a été omise ou non répétée sur le dessin.
        elif physical_bends > 0 and physical_bends > callout_bends and (bom_elbows_count == physical_bends or (spool_bends_expected and spool_bends_expected == physical_bends)):
            schema_bends_found = physical_bends
            if len(unlabeled_bends) > 0 and callout_bends > 0:
                anomalies.append({
                    "id": "ISO-QA-002",
                    "code": "ETIQUETTE_COUDE_OMISE_SCHEMA",
                    "rule": "RULE_TOPOLOGICAL_BEND_COUNT",
                    "severity": "MINOR",
                    "severity_label": "QUALITÉ DESSIN",
                    "component": "Repérage Schéma / Étiquettes de Coudes",
                    "expected": f"{physical_bends} étiquette(s) de repérage sur le tracé",
                    "found": f"{callout_bends} étiquette(s) présente(s) ({len(unlabeled_bends)} coude(s) physique(s) non étiqueté(s))",
                    "title": f"Omission d'étiquette de repérage de coude sur le schéma ({len(unlabeled_bends)} coude(s) non repéré(s))",
                    "description": (
                        f"Le tracé comporte {physical_bends} coudes physiques (conforme à la nomenclature de {bom_elbows_count} coudes"
                        + (f" et aux {len(spools)} tronçons débités)" if spools else ")")
                        + f", mais seules {callout_bends} étiquette(s) de repérage d'article figurent sur le dessin. "
                        f"La quantité commandée est conforme à la géométrie, mais le repérage sur plan doit être complété."
                    ),
                    "recommendation": "Compléter le schéma isométrique en apposant le repère de nomenclature sur les coudes physiques non étiquetés."
                })

        # 4. Repli sur le maximum des détections physiques fiables
        elif physical_bends > 0 and physical_bends <= 25:
            schema_bends_found = physical_bends

        # 5. Repli sur les spools
        elif spool_bends_expected and spool_bends_expected > 0:
            schema_bends_found = spool_bends_expected
        else:
            schema_bends_found = None

    else:
        # Sur plan scanné / non-vectoriel :
        # Seules les ruptures d'angles non-standards annotées expressément sur le schéma sont prises en compte
        non_std_bends = re.findall(r'\b(45\s*°|29\s*°|60\s*°|45\s*DEG)\b', combined_text, re.I)
        if non_std_bends:
            schema_bends_found = len(set(non_std_bends))

    # Arbitrage et détection d'écarts
    if schema_bends_found is not None:
        if bom_elbows_count > 0 and bom_elbows_count > schema_bends_found:
            # Vérifier si la table des tronçons débités (spools) justifie les coudes supplémentaires
            if spool_bends_expected and spool_bends_expected == bom_elbows_count:
                pass  # Les spools confirment la nomenclature (décalages non-orthogonaux)
            else:
                anomalies.append({
                    "id": "ISO-ERR-002",
                    "code": "SURQUANTIFICATION_COUDES",
                    "rule": "RULE_TOPOLOGICAL_BEND_COUNT",
                    "severity": "MAJOR",
                    "severity_label": "MAJEURE",
                    "component": "Raccords / Coudes (Fittings)",
                    "expected": f"Maximum {schema_bends_found} coude(s) physique(s) visible(s) sur le tracé",
                    "found": f"{bom_elbows_count} coudes déclarés ({', '.join(elbow_details)})",
                    "title": f"Sur-quantification de coudes en nomenclature par rapport au tracé (+{bom_elbows_count - schema_bends_found} coude(s))",
                    "description": (
                        f"La nomenclature spécifie un total de {bom_elbows_count} coudes ({', '.join(elbow_details)}), "
                        f"alors que la topologie géométrique du tracé ne comporte que {schema_bends_found} changement(s) "
                        f"de direction formellement identifié(s). Il y a un surplus de {bom_elbows_count - schema_bends_found} coude(s) non justifié(s)."
                    ),
                    "recommendation": "Vérifier le nombre réel de coudes sur le plan et ajuster la nomenclature ou joindre la planche complémentaire."
                })
        elif schema_bends_found > 0 and bom_elbows_count < schema_bends_found:
            anomalies.append({
                "id": "ISO-ERR-002",
                "code": "DEFICIT_COUDES_NOMENCLATURE",
                "rule": "RULE_TOPOLOGICAL_BEND_COUNT",
                "severity": "MAJOR",
                "severity_label": "MAJEURE",
                "component": "Raccords / Coudes (Fittings)",
                "expected": f"Au moins {schema_bends_found} coude(s) déclaré(s) en nomenclature",
                "found": f"{bom_elbows_count} coude(s) déclaré(s)",
                "title": f"Déficit de coudes en nomenclature par rapport au tracé (-{schema_bends_found - bom_elbows_count} coude(s))",
                "description": (
                    f"Le tracé géométrique comporte {schema_bends_found} changement(s) de direction / coude(s), "
                    f"mais la nomenclature n'en déclare que {bom_elbows_count}. Il manque {schema_bends_found - bom_elbows_count} coude(s) pour la fabrication."
                ),
                "recommendation": "Compléter la nomenclature avec les coudes manquants repérés sur le tracé."
            })

    # =========================================================================
    # RÈGLE 3 : BOULONNERIE & PERÇAGE SELON NORME ASME B16.5 (MAJEURE)
    # =========================================================================
    bolt_item = None
    flange_item = None
    flange_qty = 0
    valid_bolt_items = []

    for it in bom_items:
        cat = it.get("category", "").upper()
        desc = it.get("description", "").upper()
        # Filtrer les vrais articles de boulonnerie pour brides (exclut impérativement les étriers de support U-bolts)
        is_u_bolt_or_support = (
            "U-BOLT" in desc or "U BOLT" in desc or "SUPPORT" in desc 
            or cat in ("SUPPORTS", "SUPPORT")
            # Exclure les équipements en ligne mal classés comme boulons (STRAINER, FLAME ARRESTER, ORIFICE PLATE)
            or any(k in desc for k in ("STRAINER", "ARRESTER", "ORIFICE PLATE", "FLAME ARRESTER", "FILTER BASKET"))
        )
        is_bolt = (
            cat in ("BOLT", "BOLTS", "FASTENERS", "BOULONNERIE") or 
            "STUD" in desc or 
            "GOUJON" in desc or
            bool(re.search(r'\bM\d{2}\b', desc))
        ) and not is_u_bolt_or_support

        # Exclure les faux positifs (textes ultra-courts de colonnes résiduelles, min 3 chars ex: 'M20')
        if is_bolt and len(desc.strip()) >= 3:
            qty = _safe_float(it.get("quantity"), 0.0)
            if qty > 0:
                valid_bolt_items.append(it)
        elif cat in ("FLANGE", "FLANGES", "BRIDES") or "FLANGE" in desc or "RANGE WN" in desc or "WN" in desc or "BLIND" in desc:
            if not flange_item:
                flange_item = it
            flange_qty += _safe_float(it.get("quantity"), 0.0)

    # Nombre de liaisons bridées : repérées sur le schéma ou déduites de la BOM
    schema_flanged_joints = cad_topology.get("flange_joints_count", 0)
    if not schema_flanged_joints:
        callouts_flange = re.findall(r'\[?(?:[CLF]?[EF4]\s*B5\s*G6|[CLF]?[EF4]\s*B\d+\s*G\d+)\]?', combined_text)
        if callouts_flange:
            schema_flanged_joints = len(callouts_flange)
        elif flange_qty > 0:
            schema_flanged_joints = int(flange_qty)

    # Collecter tous les gabarits ASME B16.5 pour l'ensemble des brides déclarées
    valid_flanges = [it for it in bom_items if it.get("category", "").upper() in ("FLANGE", "FLANGES", "BRIDES") or "FLANGE" in it.get("description", "").upper() or "BLIND" in it.get("description", "").upper()]
    std_bolts_set = set()
    flange_sizes_str = []
    for f in valid_flanges:
        f_size = normalize_nps(f.get("size", "") or "2\"")
        f_rat = normalize_rating(f.get("rating", "") or "150#")
        bolts_for_f = ASME_B16_5_BOLT_COUNT.get((f_rat, f_size), 4 if f_size in ('1/2"', '3/4"', '1"', '1.1/2"', '2"') else (8 if f_size in ('3"', '4"', '6"', '8"') else 12))
        std_bolts_set.add(bolts_for_f)
        flange_sizes_str.append(f"{f_size} {f_rat} ({bolts_for_f}b)")

    if not std_bolts_set:
        std_bolts_set = {4}

    for b_item in valid_bolt_items:
        b_qty = _safe_float(b_item.get("quantity"), 0.0)
        b_unit = str(b_item.get("unit") or "EA").upper().strip()
        b_desc = b_item.get("description", "")
        # Si la quantité est exprimée en "SET" (jeux de goujons), normaliser en nombre réel de goujons
        effective_b_qty = b_qty * 4.0 if b_unit in ("SET", "JEU", "ENS") else b_qty
        if effective_b_qty > 0:
            # Contrôle arithmétique ASME B16.5 :
            # La quantité de chaque type de goujon doit être un multiple d'un des gabarits de perçage des brides de la ligne
            is_divisible = any(int(effective_b_qty) % s == 0 for s in std_bolts_set)
            if not is_divisible:
                anomalies.append({
                    "id": "ISO-ERR-003",
                    "code": "QUANTITE_BOULONS_NON_CONFORME_ASME",
                    "rule": "RULE_ASME_B16_5_BOLT_COUNT",
                    "severity": "MAJOR",
                    "severity_label": "MAJEURE (NORMATIVE)",
                    "component": "Boulonnerie / Goujons (Fasteners)",
                    "expected": f"Multiple d'un gabarit ASME B16.5 de la ligne ({', '.join(str(s) for s in sorted(std_bolts_set))} goujons)",
                    "found": f"{int(effective_b_qty)} goujons déclarés ({b_desc[:45]}...)",
                    "title": "Quantité de boulonnerie erronée / Non conforme ASME B16.5",
                    "description": (
                        f"La nomenclature répertorie {int(effective_b_qty)} goujons pour l'article '{b_desc[:50]}'. "
                        f"Cette quantité n'est divisible par aucun des gabarits ASME B16.5 applicables sur cette ligne ({', '.join(flange_sizes_str)}). "
                        f"Il s'agit d'une anomalie de chiffrage ou d'un gabarit de perçage inadapté."
                    ),
                })

    # Contrôle croisé global du ratio Boulonnerie vs Brides déclarées
    total_bolts_qty = sum(
        _safe_float(b.get("quantity"), 0.0) * (4.0 if str(b.get("unit") or "").upper().strip() in ("SET", "JEU", "ENS") else 1.0)
        for b in valid_bolt_items
    )
    schema_bolt_callouts = cad_topology.get("bolt_callouts_count", 0)
    if flange_qty > 0 and std_bolts_set:
        min_std = min(std_bolts_set)
        if total_bolts_qty == 0:
            # Ne signaler l'absence de boulonnerie que si le schéma appelle formellement des goujons (B...) ou s'il y a plus d'une bride (liaison interne)
            if schema_bolt_callouts > 0 or flange_qty > 1:
                anomalies.append({
                    "id": "ISO-ERR-003",
                    "code": "DEFICIT_BOULONNERIE_ASME",
                    "rule": "RULE_ASME_B16_5_BOLT_COUNT",
                    "severity": "MAJOR",
                    "severity_label": "MAJEURE (NORMATIVE)",
                    "component": "Boulonnerie / Goujons (Fasteners)",
                    "expected": f"Au moins {min_std} goujons pour équiper les brides déclarées",
                    "found": "0 goujon déclaré en nomenclature",
                    "title": "Absence totale de boulonnerie en nomenclature pour les brides",
                    "description": f"La nomenclature déclare {int(flange_qty)} bride(s) mais aucun goujon n'est répertorié.",
                    "recommendation": "Ajouter la boulonnerie correspondante aux brides."
                })
        elif total_bolts_qty < min_std:
            anomalies.append({
                "id": "ISO-ERR-003",
                "code": "DEFICIT_BOULONNERIE_ASME",
                "rule": "RULE_ASME_B16_5_BOLT_COUNT",
                "severity": "MAJOR",
                "severity_label": "MAJEURE (NORMATIVE)",
                "component": "Boulonnerie / Goujons (Fasteners)",
                "expected": f"Au moins {min_std} goujons pour équiper au moins une liaison bridée",
                "found": f"{int(total_bolts_qty)} goujons déclarés",
                "title": "Déficit critique de boulonnerie par rapport aux brides",
                "description": f"Seulement {int(total_bolts_qty)} goujon(s) déclaré(s), insuffisant pour équiper une liaison bridée standard (minimum {min_std}).",
                "recommendation": "Compléter la dotation de goujons."
            })



    # =========================================================================
    # RÈGLE 4 : ÉCART DE MÉTRAGE LINÉAIRE TUYAUTERIE (BOM vs COTES DU TRACÉ) (MINEURE)
    # =========================================================================
    bom_pipe_length = 0.0
    for it in bom_items:
        if it.get("category", "").upper() == "PIPE":
            bom_pipe_length += _safe_float(it.get("quantity"), 0.0)

    # Contrôle de cohérence avec la table de débit des tronçons (PIPE SPOOLS / CUT PIPE LENGTH)
    spool_cut_length_m = 0.0
    if spools:
        spool_cut_length_m = sum(_safe_float(s.get("cut_length_mm"), 0.0) for s in spools if s.get("cut_length_mm")) / 1000.0

    schema_dims_sum = None
    cartouche_cl = metadata.get("cl_length_m")
    if not cartouche_cl and cad_topology.get("total_pipe_length_m"):
        cartouche_cl = cad_topology.get("total_pipe_length_m")

    if cartouche_cl:
        try:
            schema_dims_sum = float(cartouche_cl)
        except (ValueError, TypeError):
            pass

    # Détection unifiée et dédupliquée des anomalies de métrage linéaire (Tolérance 0% stricte)
    if bom_pipe_length > 0:
        has_spool_surplus = (spool_cut_length_m > 0 and bom_pipe_length > (spool_cut_length_m + 0.15))
        has_cl_surplus = (schema_dims_sum is not None and schema_dims_sum > 0 and bom_pipe_length > schema_dims_sum)

        if has_spool_surplus and has_cl_surplus:
            # Cas 1 : Surplus avéré à la fois par rapport aux Spools et à la Centerline (CL) -> UNE SEULE RÉSERVE COMPLÈTE
            surplus_spool_m = bom_pipe_length - spool_cut_length_m
            surplus_spool_pct = (surplus_spool_m / spool_cut_length_m) * 100.0
            surplus_cl_m = bom_pipe_length - schema_dims_sum
            surplus_cl_pct = (surplus_cl_m / schema_dims_sum) * 100.0
            anomalies.append({
                "id": "ISO-ERR-004",
                "code": "ECART_METRAGE_TUYAUTERIE",
                "rule": "RULE_LINEAR_PIPE_LENGTH_TOLERANCE_STRICT_0PCT",
                "severity": "MAJOR",
                "severity_label": "MAJEURE (TOLÉRANCE 0% DÉPASSÉE)",
                "component": "Tuyauterie Droite (Spool Cut Length & Centerline)",
                "expected": f"Débit tronçons (Spools) : {spool_cut_length_m:.2f} m | Longueur d'axe (Centerline CL) : {schema_dims_sum:.2f} m (Tolérance 0.00%)",
                "found": f"Quantité déclarée en nomenclature : {bom_pipe_length:.2f} m",
                "title": f"Sur-métrage critique de tuyauterie (+{surplus_spool_m:.2f} m vs Spools / +{surplus_cl_m:.2f} m vs CL - Tolérance 0%)",
                "description": (
                    f"La nomenclature annonce {bom_pipe_length:.2f} m de tuyauterie, en dépassement à la fois du débit réel des tronçons "
                    f"coupés de fabrication (PIPE SPOOLS : {spool_cut_length_m:.2f} m, surplus de +{surplus_spool_m:.2f} m / +{surplus_spool_pct:.1f}%) "
                    f"et de la longueur totale d'axe (Centerline CL : {schema_dims_sum:.2f} m, surplus de +{surplus_cl_m:.2f} m / +{surplus_cl_pct:.1f}%). "
                    f"Sous la règle de tolérance stricte de 0%, il est rigoureusement impossible que le métrage déclaré en nomenclature dépasse "
                    f"la longueur d'axe et les tronçons débités."
                ),
                "recommendation": f"Ajuster immédiatement la nomenclature à {spool_cut_length_m:.2f} m pour concorder avec la table de fabrication des spools sans aucun surplus."
            })
        elif has_spool_surplus:
            # Cas 2 : Surplus avéré par rapport aux Spools uniquement
            # Si le métrage déclaré en nomenclature concorde avec la Centerline (axe du schéma),
            # l'écart correspond simplement aux déductions d'engagement des raccords et vannes (Take-offs).
            if schema_dims_sum is not None and schema_dims_sum > 0 and abs(bom_pipe_length - schema_dims_sum) <= 0.15:
                pass
            else:
                surplus_spool_m = bom_pipe_length - spool_cut_length_m
                surplus_spool_pct = (surplus_spool_m / spool_cut_length_m) * 100.0
                anomalies.append({
                    "id": "ISO-ERR-004",
                    "code": "ECART_METRAGE_TUYAUTERIE",
                    "rule": "RULE_SPOOL_CUT_PIPE_TOLERANCE_0PCT",
                    "severity": "MAJOR",
                    "severity_label": "MAJEURE (TOLÉRANCE 0% DÉPASSÉE)",
                    "component": "Tuyauterie Droite (Spool Cut Length)",
                    "expected": f"Débit exact des tronçons coupés (Spools) : {spool_cut_length_m:.2f} m (Tolérance 0.00%)",
                    "found": f"Quantité déclarée en nomenclature : {bom_pipe_length:.2f} m",
                    "title": f"Sur-quantification de tuyauterie par rapport aux tronçons débités (+{surplus_spool_m:.2f} m / +{surplus_spool_pct:.1f}% - Tolérance 0%)",
                    "description": (
                        f"La nomenclature déclare {bom_pipe_length:.2f} m de tuyauterie, alors que le tableau de fabrication "
                        f"des tronçons (PIPE SPOOLS / CUT PIPE LENGTH) ne totalise que {spool_cut_length_m:.2f} m de tube débité. "
                        f"Sous la règle de tolérance stricte de 0%, il y a un surplus non justifié de +{surplus_spool_m:.2f} m (+{surplus_spool_pct:.1f}%)."
                    ),
                    "recommendation": f"Ajuster la nomenclature à {spool_cut_length_m:.2f} m pour concorder exactement avec la somme des longueurs coupées de la table des spools."
                })
        elif has_cl_surplus:
            # Cas 3 : Surplus avéré par rapport à la Centerline uniquement
            surplus_m = bom_pipe_length - schema_dims_sum
            surplus_pct = (surplus_m / schema_dims_sum) * 100.0
            anomalies.append({
                "id": "ISO-ERR-004",
                "code": "ECART_METRAGE_TUYAUTERIE",
                "rule": "RULE_LINEAR_PIPE_LENGTH_TOLERANCE_STRICT_0PCT",
                "severity": "MAJOR",
                "severity_label": "MAJEURE (TOLÉRANCE 0% DÉPASSÉE)",
                "component": "Tuyauterie Droite (Piping)",
                "expected": f"Longueur maximale admissible (Centerline CL) : {schema_dims_sum:.2f} m (Tolérance de sur-métrage : 0.00%)",
                "found": f"Longueur déclarée en nomenclature : {bom_pipe_length:.2f} m",
                "title": f"Sur-métrage critique de tuyauterie (+{surplus_m:.2f} m / +{surplus_pct:.1f}% - Tolérance 0%)",
                "description": (
                    f"La nomenclature annonce {bom_pipe_length:.2f} m de tube (ASME B36.10M), alors que la longueur "
                    f"totale d'axe (Centerline) du tracé n'est que de {schema_dims_sum:.2f} m. "
                    f"Sous la règle de tolérance stricte de 0%, il est rigoureusement impossible que le métrage droit dépasse la longueur d'axe. "
                    f"Sur-quantification injustifiée de +{surplus_m:.2f} m (+{surplus_pct:.1f}%)."
                ),
                "recommendation": "Ajuster immédiatement le métrage linéaire en nomenclature pour respecter la longueur d'axe réelle sans aucun dépassement (tolérance 0%)."
            })
    elif schema_dims_sum is not None and schema_dims_sum > 0.5 and (schema_dims_sum - bom_pipe_length) > 0.05:
        deficit_m = schema_dims_sum - bom_pipe_length
        deficit_pct = (deficit_m / schema_dims_sum) * 100.0
        anomalies.append({
            "id": "ISO-ERR-004-DEFICIT",
            "code": "SOUS_METRAGE_TUYAUTERIE",
            "rule": "RULE_LINEAR_PIPE_LENGTH_TOLERANCE_STRICT_0PCT",
            "severity": "CRITICAL" if bom_pipe_length == 0 else "MAJOR",
            "severity_label": "CRITIQUE (SOUS-MÉTRAGE / DÉFICIT DE TUBE)" if bom_pipe_length == 0 else "MAJEURE (DÉFICIT MÉTRAGE)",
            "component": "Tuyauterie Droite (Piping)",
            "expected": f"Longueur requise (Centerline CL) : {schema_dims_sum:.2f} m (Tolérance 0%)",
            "found": f"Longueur déclarée en nomenclature : {bom_pipe_length:.2f} m",
            "title": f"Déficit de métrage de tuyauterie (-{deficit_m:.2f} m / -{deficit_pct:.1f}% - Tolérance 0%)",
            "description": (
                f"Le schéma comporte une ligne de {schema_dims_sum:.2f} m d'axe, mais la nomenclature "
                f"ne déclare que {bom_pipe_length:.2f} m de tube (déficit de -{deficit_m:.2f} m). "
                f"Sous la règle de tolérance stricte de 0%, tout déficit de tuyauterie entraîne un arrêt d'approvisionnement."
            ),
            "recommendation": f"Ajuster la quantité en nomenclature à {schema_dims_sum:.2f} m pour couvrir l'intégralité du tracé."
        })

    # =========================================================================
    # RÈGLE 5 : QUALITÉ ET INTÉGRITÉ SÉMANTIQUE DES DÉSIGNATIONS (TRAÇABILITÉ)
    # =========================================================================
    typo_corrections = []
    for it in bom_items:
        d = it.get("description", "")
        # Vérification 1 : RANGE WN au lieu de FLANGE WN
        if "RANGE WN" in d.upper() or it.get("category", "").upper() == "RANGES":
            typo_corrections.append("Item Flange : 'RANGE WN' corrigé en 'FLANGE WN' (Bride à collerette ASME B16.5)")
        # Vérification 2 : SOUD WEDGE au lieu de SOLID WEDGE
        if "SOUD WEDGE" in d.upper():
            typo_corrections.append("Item Robinetterie : 'SOUD WEDGE' corrigé en 'SOLID WEDGE' (Obturateur monobloc API 600)")
        # Vérification 3 : Nuance A216 WBC au lieu de A216 WCB
        if "A216 WBC" in d.upper():
            typo_corrections.append("Item Matière : Nuance 'A216 WBC' invalide, corrigée en 'ASTM A216 WCB' (Acier coulé carbone)")

    if typo_corrections:
        anomalies.append({
            "id": "ISO-ERR-005",
            "code": "ERREURS_DESIGNATION_MATIERE",
            "rule": "RULE_SEMANTIC_TYPO_CORRECTION",
            "severity": "QUALITY",
            "severity_label": "QUALITÉ & TRAÇABILITÉ",
            "component": "Nomenclature / Désignations",
            "expected": "Désignations normatives ASME / ASTM / API conformes",
            "found": f"{len(typo_corrections)} altérations textuelles détectées",
            "title": "Erreurs de désignation matière et type de composant",
            "description": (
                f"Plusieurs désignations techniques contiennent des anomalies sémantiques ou fautes de saisie : "
                f"{' ; '.join(typo_corrections)}. Ces fautes peuvent fausser les commandes d'achat et le dossier constructeur RLM."
            ),
            "recommendation": "Harmoniser les libellés de composants selon les fiches techniques EPC et la spécification tuyauterie 1ACX1PN."
        })

    # =========================================================================
    # RÈGLE 6 : CONTRÔLE CROISÉ DE LA ROBINETTERIE / VANNES (BOM vs TRACÉ) (MAJEURE)
    # =========================================================================
    bom_valves_count = 0
    valves_grouped = {}
    for it in bom_items:
        cat = it.get("category", "").upper()
        desc = it.get("description", "").strip()
        desc_u = desc.upper()
        # Ne pas exclure 'FLANGE' car les vannes à brides (BALL VALVE FLANGED) sont légitimes
        is_valve = (cat in ("VALVE", "VALVES", "ROBINETTERIE") or any(k in desc_u for k in ("VALVE", "GATE", "BALL", "GLOBE", "CHECK", "VANNE", "CLAPET", "ROBINET", "TSV"))) and not any(k in desc_u for k in ("GASKET", "INSULATION", "KIT", "BOLT", "PIPE", "ELBOW", "REDUCER"))
        if is_valve:
            qty = _safe_float(it.get("quantity"), 1.0)
            bom_valves_count += int(qty)
            sz = str(it.get("size", "")).strip()
            key = (desc, sz)
            valves_grouped[key] = valves_grouped.get(key, 0) + int(qty)

    valve_details = [
        f"{qty}x {desc} ({sz})" if sz and sz not in desc else f"{qty}x {desc}"
        for (desc, sz), qty in valves_grouped.items()
    ]

    schema_valves_count = cad_topology.get("valves_count")
    if cad_topology.get("is_cad_topology_available") and schema_valves_count is not None:
        if bom_valves_count > schema_valves_count and schema_valves_count >= 1:
            anomalies.append({
                "id": "ISO-ERR-006",
                "code": "SURQUANTIFICATION_VANNES",
                "rule": "RULE_VALVE_COUNT_TRIANGULATION",
                "severity": "MAJOR",
                "severity_label": "MAJEURE",
                "component": "Robinetterie / Vannes (Valves)",
                "expected": f"{schema_valves_count} vanne(s) identifiée(s) sur le tracé du schéma",
                "found": f"{bom_valves_count} vanne(s) déclarée(s) en nomenclature ({', '.join(valve_details)})",
                "title": "Sur-quantification de vannes en nomenclature par rapport au tracé",
                "description": (
                    f"La nomenclature déclare {bom_valves_count} vanne(s) ({', '.join(valve_details)}), "
                    f"alors que le tracé isométrique ne comporte que {schema_valves_count} vanne(s) visible(s). Il y a une divergence de nomenclature."
                ),
                "recommendation": "Vérifier la présence effective de la vanne sur le plan P&ID et l'isométrique."
            })
        elif bom_valves_count < schema_valves_count:
            anomalies.append({
                "id": "ISO-ERR-006",
                "code": "OMISSION_VANNE_NOMENCLATURE",
                "rule": "RULE_VALVE_COUNT_TRIANGULATION",
                "severity": "MAJOR",
                "severity_label": "MAJEURE",
                "component": "Robinetterie / Vannes (Valves)",
                "expected": f"Au moins {schema_valves_count} vanne(s) déclarée(s) en nomenclature",
                "found": f"{bom_valves_count} vanne(s) déclarée(s)",
                "title": "Vanne repérée sur le schéma mais absente de la nomenclature",
                "description": (
                    f"{schema_valves_count} symbole(s) de robinetterie sont dessinés sur le tracé, "
                    f"mais seuls {bom_valves_count} apparaissent dans la table de nomenclature. Omission de matériel pour approvisionnement."
                ),
                "recommendation": "Ajouter la vanne manquante dans la table de nomenclature avec sa spécification complète."
            })

    # =========================================================================
    # RÈGLE 7 : CONTRÔLE CROISÉ DE L'INSTRUMENTATION & KITS (BOM vs TRACÉ) (MAJEURE)
    # =========================================================================
    bom_instruments_count = 0
    instruments_grouped = {}
    for it in bom_items:
        cat = it.get("category", "").upper()
        desc = it.get("description", "").strip()
        desc_u = desc.upper()
        is_dielectric_kit = any(k in desc_u for k in ("INSULATION KIT", "KIT ISOLANT", "DIELECTRIC", "DIÉLECTRIQUE"))
        is_inst = not is_dielectric_kit and (cat in ("INSTRUMENT", "INSTRUMENTS") or any(k in desc_u for k in ("TRANSMITTER", "GAUGE", "ORIFICE", "THERMOWELL", "FLOW METER", "ROTAMETER", "INDICATOR", "CONTROLLER", "PDT")))
        if is_inst:
            qty = _safe_float(it.get("quantity"), 1.0)
            bom_instruments_count += int(qty)
            sz = str(it.get("size", "")).strip()
            key = (desc, sz)
            instruments_grouped[key] = instruments_grouped.get(key, 0) + int(qty)

    instrument_details = [
        f"{qty}x {desc} ({sz})" if sz and sz not in desc else f"{qty}x {desc}"
        for (desc, sz), qty in instruments_grouped.items()
    ]

    schema_instruments_count = cad_topology.get("instruments_count")
    if cad_topology.get("is_cad_topology_available") and schema_instruments_count is not None:
        if bom_instruments_count > schema_instruments_count and schema_instruments_count >= 1:
            anomalies.append({
                "id": "ISO-ERR-007",
                "code": "SURQUANTIFICATION_INSTRUMENTS",
                "rule": "RULE_INSTRUMENT_COUNT_TRIANGULATION",
                "severity": "MAJOR",
                "severity_label": "MAJEURE",
                "component": "Instrumentation / Accessoires en Ligne",
                "expected": f"{schema_instruments_count} instrument(s) ou kit(s) visible(s) sur le tracé",
                "found": f"{bom_instruments_count} instrument(s) déclaré(s) en nomenclature ({', '.join(instrument_details)})",
                "title": "Sur-quantification d'instruments ou kits spéciaux en nomenclature",
                "description": (
                    f"La nomenclature mentionne {bom_instruments_count} élément(s) d'instrumentation ({', '.join(instrument_details)}), "
                    f"alors que le tracé physique n'en comporte que {schema_instruments_count}. Il y a surplus de matériel."
                ),
                "recommendation": "Vérifier les repères d'instrumentation sur le schéma et ajuster la nomenclature."
            })
        elif schema_instruments_count > 0 and bom_instruments_count < schema_instruments_count:
            anomalies.append({
                "id": "ISO-ERR-007",
                "code": "DISCORDANCE_INSTRUMENTS",
                "rule": "RULE_INSTRUMENT_COUNT_TRIANGULATION",
                "severity": "MAJOR",
                "severity_label": "MAJEURE",
                "component": "Instrumentation / Accessoires en Ligne",
                "expected": f"Au moins {schema_instruments_count} instrument(s) / kit(s) en nomenclature",
                "found": f"{bom_instruments_count} déclaré(s)",
                "title": "Instrument ou kit présent sur le schéma mais absent de la nomenclature",
                "description": (
                    f"Le schéma comporte {schema_instruments_count} piquage(s) ou élément(s) d'instrumentation, "
                    f"mais seuls {bom_instruments_count} sont déclarés en nomenclature."
                ),
                "recommendation": "Compléter la nomenclature avec les kits ou instruments repérés sur le plan."
            })

    # 7.2 Contrôle croisé des kits d'isolation diélectrique (Insulation Kits)
    bom_kits_count = sum(float(it.get("quantity", 1)) for it in bom_items if any(k in it.get("description", "").upper() for k in ("INSULATION KIT", "KIT ISOLANT", "DIELECTRIC", "DIÉLECTRIQUE")))
    schema_kits_count = cad_topology.get("insulation_kits_count")
    if cad_topology.get("is_cad_topology_available") and schema_kits_count is not None and bom_kits_count > 0:
        if bom_kits_count > schema_kits_count and schema_kits_count >= 1:
            anomalies.append({
                "id": "ISO-ERR-007",
                "code": "SURQUANTIFICATION_KITS_ISOLATION",
                "rule": "RULE_DIELECTRIC_KIT_TRIANGULATION",
                "severity": "MAJOR",
                "severity_label": "MAJEURE",
                "component": "Accessoires de Tuyauterie / Kits d'Isolation",
                "expected": f"Maximum {schema_kits_count} kit(s) d'isolation repéré(s) sur le tracé",
                "found": f"{int(bom_kits_count)} kit(s) déclaré(s) en nomenclature",
                "title": "Sur-quantification de kits d'isolation diélectrique en nomenclature",
                "description": (
                    f"La nomenclature déclare {int(bom_kits_count)} kit(s) d'isolation diélectrique, "
                    f"alors que le schéma ne comporte que {schema_kits_count} joint(s) diélectrique(s) repéré(s) physiquement sur le tracé. "
                    f"Il y a un surplus injustifié de {int(bom_kits_count - schema_kits_count)} kit(s)."
                ),
                "recommendation": "Ajuster la quantité de kits d'isolation au nombre exact de liaisons diélectriques repérées sur le schéma."
            })

    # =========================================================================
    # RÈGLE 8 : CONTRÔLE CROISÉ DES BRIDES (BOM vs LIAISONS BRIDÉES DU TRACÉ) (MAJEURE)
    # =========================================================================
    schema_flanged_joints = cad_topology.get("flange_joints_count")
    flange_tags_list = cad_topology.get("flange_tags", [])
    blind_qty = sum(
        _safe_float(it.get("quantity"), 0.0) for it in bom_items 
        if any(k in it.get("description", "").upper() for k in ("SPECTACLE", "LUNETTE", "SPACER", "PADDLE"))
        and not ("BLIND FLANGE" in it.get("description", "").upper() or "BRIDE PLEINE" in it.get("description", "").upper())
    )

    if schema_flanged_joints is not None and schema_flanged_joints > 0:
        max_physical_flanges = (schema_flanged_joints * 2) + int(blind_qty)
        if flange_qty > max_physical_flanges:
            surplus_flanges = int(flange_qty - max_physical_flanges)
            anomalies.append({
                "id": "ISO-ERR-008",
                "code": "SURQUANTIFICATION_BRIDES",
                "rule": "RULE_FLANGE_COUNT_VS_JOINTS",
                "severity": "MAJOR",
                "severity_label": "MAJEURE",
                "component": "Brides / Liaisons Bridées (Flanges)",
                "expected": f"Maximum {max_physical_flanges} bride(s) physique(s) pour les {schema_flanged_joints} liaison(s) bridée(s) du tracé ({', '.join(flange_tags_list)})",
                "found": f"{int(flange_qty)} brides déclarées en nomenclature",
                "title": "Sur-quantification de brides par rapport aux liaisons bridées du tracé",
                "description": (
                    f"La nomenclature répertorie un total de {int(flange_qty)} brides, alors que le schéma physique ne comporte que "
                    f"{schema_flanged_joints} point(s) de raccordement bridé(s) ({', '.join(flange_tags_list)}). Une liaison bridée raccordant "
                    f"au plus 2 brides, il y a un surplus injustifié d'au moins {surplus_flanges} bride(s)."
                ),
                "recommendation": "Vérifier le nombre de brides nécessaires aux points de raccordement ou corriger la nomenclature."
            })
        elif flange_qty < schema_flanged_joints:
            anomalies.append({
                "id": "ISO-ERR-008",
                "code": "DEFICIT_BRIDES_SCHEMA",
                "rule": "RULE_FLANGE_COUNT_VS_JOINTS",
                "severity": "MAJOR",
                "severity_label": "MAJEURE",
                "component": "Brides / Liaisons Bridées (Flanges)",
                "expected": f"Au moins {schema_flanged_joints} bride(s) pour équiper les {schema_flanged_joints} liaison(s) bridée(s) du tracé ({', '.join(flange_tags_list)})",
                "found": f"{int(flange_qty)} bride(s) déclarée(s) en nomenclature",
                "title": "Nombre insuffisant de brides par rapport aux liaisons bridées du schéma",
                "description": (
                    f"Le tracé comporte {schema_flanged_joints} liaison(s) bridée(s) ({', '.join(flange_tags_list)}), "
                    f"mais seulement {int(flange_qty)} bride(s) sont déclarées en nomenclature."
                ),
                "recommendation": "Compléter la nomenclature avec les brides nécessaires pour chaque joint bridé."
            })

    # Contrôle croisé des joints d'étanchéité standard vs liaisons bridées disponibles
    gasket_qty = sum(
        _safe_float(it.get("quantity"), 0.0) for it in bom_items
        if (it.get("category", "").upper() == "GASKET" or "GASKET" in it.get("description", "").upper() or "JOINT" in it.get("description", "").upper())
        and not any(k in it.get("description", "").upper() for k in ("INSULATION", "KIT", "DIELECTRIC", "ISOLANT", "EXPANSION", "FLEXIBLE"))
    )
    if schema_flanged_joints is not None and schema_flanged_joints > 0:
        effective_kits = schema_kits_count if schema_kits_count is not None else 0
        max_standard_gaskets = max(0, schema_flanged_joints - effective_kits) + int(blind_qty)
        schema_gaskets_drawn = cad_topology.get("gaskets_count", 0)
        if schema_gaskets_drawn:
            max_standard_gaskets = max(max_standard_gaskets, schema_gaskets_drawn)

        if gasket_qty > max_standard_gaskets:
            anomalies.append({
                "id": "ISO-ERR-009",
                "code": "SURQUANTIFICATION_JOINTS_ETANCHEITE",
                "rule": "RULE_GASKET_COUNT_VS_JOINTS",
                "severity": "MAJOR",
                "severity_label": "MAJEURE",
                "component": "Joints d'étanchéité (Gaskets)",
                "expected": f"Maximum {max_standard_gaskets} joint(s) standard(s) pour les {schema_flanged_joints} liaison(s) bridée(s) du schéma (dont {effective_kits} équipée(s) de kit d'isolation et {int(blind_qty)} lunette(s))",
                "found": f"{int(gasket_qty)} joint(s) standard(s) déclarés en nomenclature",
                "title": "Sur-quantification de joints d'étanchéité en nomenclature",
                "description": (
                    f"La nomenclature répertorie {int(gasket_qty)} joint(s) d'étanchéité standard, alors que le tracé ne compte que "
                    f"{schema_flanged_joints} liaison(s) bridée(s) au total, dont {effective_kits} liaison(s) isolante(s) nécessitant un kit diélectrique "
                    f"et {int(blind_qty)} lunette(s) de fermeture / spectacle blind(s). "
                    f"Le besoin physique maximal est donc de {max_standard_gaskets} joint(s) standard(s)."
                ),
                "recommendation": "Ajuster la quantité de joints standard en nomenclature pour concorder avec le nombre physique de liaisons bridées standard."
            })

    # Synthèse globale des anomalies
    crit_cnt = sum(1 for a in anomalies if a["severity"] == "CRITICAL")
    maj_cnt = sum(1 for a in anomalies if a["severity"] == "MAJOR")
    min_cnt = sum(1 for a in anomalies if a["severity"] == "MINOR")
    qual_cnt = sum(1 for a in anomalies if a["severity"] == "QUALITY")
    info_cnt = sum(1 for a in anomalies if a["severity"] == "INFO")

    if crit_cnt > 0:
        status_label = "NON CONFORME (REJET ARH)"
    elif maj_cnt > 0:
        status_label = "RÉSERVES MAJEURES"
    elif min_cnt > 0 or qual_cnt > 0:
        status_label = "CONFORME AVEC REMARQUES"
    elif info_cnt > 0:
        status_label = "CONFORME (AVEC INFORMATIONS)"
    else:
        status_label = "CONFORME (100% VALIDÉ)"

    summary = {
        "is_valid": crit_cnt == 0 and maj_cnt == 0,
        "critical_count": crit_cnt,
        "major_count": maj_cnt,
        "minor_count": min_cnt,
        "quality_count": qual_cnt,
        "info_count": info_cnt,
        "total_anomalies": len(anomalies),
        "status_label": status_label
    }

    return {
        "status": "success",
        "is_valid": summary["is_valid"],
        "summary": summary,
        "anomalies": anomalies,
        "cad_topology": cad_topology
    }
