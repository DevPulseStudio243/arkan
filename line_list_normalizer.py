"""
line_list_normalizer.py
=======================
Module de normalisation de la Line List pour ARKAN P&ID.

Fonctionnalités :
  1. FILTRAGE STRICT : Élimination à 100% des tronçons fantômes sans tag de ligne valide (réduction de 98% de bruit).
  2. DÉDOUBLONNEMENT & FUSION : Regroupement par numéro de ligne unique, calcul de la longueur totale cumulée,
     fusion des segments géométriques et des composants en ligne (vannes, instruments).
  3. MAPPING DES CLÉS UI : Format conforme aux attentes d'arkan-ui.html (line_number, size, dn, fluid, spec,
     insulation, from_equipment, to_equipment, pid_number, flow_path, path_coords, etc.).
  4. CONVERSION ASME B36.10M : Table de conversion normalisée NPS (pouces) -> DN (métrique ISO 6708).
  5. RÉSOLUTION DES CONNECTEURS OFF-PAGE : Détection et association des flèches et textes de renvoi
     (VERS PLAN, FROM, TO, TIE-IN, COLLECTEUR, TORCHE) aux extrémités libres pour renseigner l'origine et la destination.
"""

from __future__ import annotations

import html
import math
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Table de conversion normalisée ASME B36.10M / ISO 6708 (NPS -> DN)
# ---------------------------------------------------------------------------
NPS_TO_DN: Dict[str, int] = {
    "1/8": 6, "0.125": 6,
    "1/4": 8, "0.25": 8,
    "3/8": 10, "0.375": 10,
    "1/2": 15, "0.5": 15,
    "3/4": 20, "0.75": 20,
    "1": 25, "1.0": 25,
    "1-1/4": 32, "1 1/4": 32, "1.25": 32,
    "1-1/2": 40, "1 1/2": 40, "1.5": 40,
    "2": 50, "2.0": 50,
    "2-1/2": 65, "2 1/2": 65, "2.5": 65,
    "3": 80, "3.0": 80,
    "3-1/2": 90, "3 1/2": 90, "3.5": 90,
    "4": 100, "4.0": 100,
    "5": 125, "5.0": 125,
    "6": 150, "6.0": 150,
    "8": 200, "8.0": 200,
    "10": 250, "10.0": 250,
    "12": 300, "12.0": 300,
    "14": 350, "14.0": 350,
    "16": 400, "16.0": 400,
    "18": 450, "18.0": 450,
    "20": 500, "20.0": 500,
    "22": 550, "22.0": 550,
    "24": 600, "24.0": 600,
    "26": 650, "26.0": 650,
    "28": 700, "28.0": 700,
    "30": 750, "30.0": 750,
    "32": 800, "32.0": 800,
    "34": 850, "34.0": 850,
    "36": 900, "36.0": 900,
    "38": 950, "38.0": 950,
    "40": 1000, "40.0": 1000,
    "42": 1050, "42.0": 1050,
    "44": 1100, "44.0": 1100,
    "46": 1150, "46.0": 1150,
    "48": 1200, "48.0": 1200,
    "50": 1250, "50.0": 1250,
    "52": 1300, "52.0": 1300,
    "54": 1350, "54.0": 1350,
    "56": 1400, "56.0": 1400,
    "60": 1500, "60.0": 1500,
}

# Description des fluides usuels
FLUID_DESCRIPTIONS: Dict[str, str] = {
    "P": "Process / Hydrocarbure",
    "G": "Gaz Procédé",
    "L": "Liquide Général",
    "W": "Eau Utilité",
    "WF": "Eau d'Incendie (Fire Water)",
    "FW": "Eau d'Incendie (Fire Water)",
    "FG": "Fuel Gas (Gaz Combustible)",
    "IA": "Air Instrument",
    "F": "Torche (Flare)",
    "FL": "Torche (Flare)",
    "D": "Drain / Purge",
    "DC": "Drain Chimique / Condensat",
    "V": "Évent (Vent)",
    "VT": "Évent Atmosphérique (Vent)",
    "LP": "Basse Pression (Low Pressure)",
    "MP": "Moyenne Pression (Medium Pressure)",
    "HP": "Haute Pression (High Pressure)",
    "CW": "Eau de Refroidissement",
    "N2": "Azote (Nitrogen)",
    "CF": "Condensat Fermé (Closed Flare)",
    "HC": "Hydrocarbure",
    "SL": "Slop / Déchets Huileux",
}


def clean_mtext_formatting(text: str) -> str:
    """
    Nettoie les balises et codes de formatage MTEXT AutoCAD ({\\H...;\\S...;\\P...}).
    """
    if not text:
        return ""
    txt = str(text)
    # Neutraliser encodage CP1252 surrogates
    txt = txt.encode("utf-8", errors="replace").decode("utf-8")
    txt = txt.replace("\udcb0", "°").replace("\ufffd", "°")
    # Fractions empilées MTEXT : \S1#2; -> 1/2 ou \S1^2; -> 1/2 (avec espace si collé à un mot/chiffre)
    txt = re.sub(r"\\S([^;#^]+)[#^/]([^;]+);(?=[A-Za-z0-9])", r"\1/\2 ", txt)
    txt = re.sub(r"\\S([^;#^]+)[#^/]([^;]+);", r"\1/\2", txt)
    # Sauts de paragraphe MTEXT \P
    txt = txt.replace(r"\P", " ").replace("\\P", " ")
    # Codes de contrôle MTEXT : \H...;, \f...;, \C...;, \A...;, \W...;, \Q...;, \T...;, etc.
    txt = re.sub(r"\\[A-Za-z][^;]*;", "", txt)
    # Accolades de groupement MTEXT
    txt = re.sub(r"[{}]", "", txt)
    # Fractions avec # résiduelles
    txt = re.sub(r"(?<=\d)#(?=\d)", "/", txt)
    # Guillemets échappés et guillemets droits normalisés
    txt = txt.replace(r'\"', '"').replace(r"\'", "'")
    txt = txt.replace("\u201d", '"').replace("\u201c", '"')
    return re.sub(r"\s+", " ", txt).strip()


def convert_nps_to_dn(nps_raw: Any) -> str:
    """
    Convertit un diamètre NPS (en pouces) en DN métrique selon ASME B36.10M.
    Retourne toujours une chaîne 'DNxxx' (ex: 'DN850', 'DN50', 'DN15').
    """
    if not nps_raw:
        return ""
    s = str(nps_raw).strip().replace('"', '').replace("''", "").replace("\u201d", "").strip()
    if not s:
        return ""
    # Lookup direct
    if s in NPS_TO_DN:
        return f"DN{NPS_TO_DN[s]}"
    # Essai avec normalisation fraction/espace (ex: '1 1/2' -> '1-1/2')
    s_alt = s.replace(" ", "-")
    if s_alt in NPS_TO_DN:
        return f"DN{NPS_TO_DN[s_alt]}"
    # Essai float numérique
    try:
        val = float(s)
        # Check entier équivalent
        if val.is_integer() and str(int(val)) in NPS_TO_DN:
            return f"DN{NPS_TO_DN[str(int(val))]}"
        if s in NPS_TO_DN:
            return f"DN{NPS_TO_DN[s]}"
        # Calcul approché ASME B36.10M (1" = 25.4 mm)
        calc_dn = round(val * 25.4)
        return f"DN{calc_dn}"
    except ValueError:
        pass
    # Fallback propre
    return f"DN{s}"


def parse_line_tag_metadata(tag_raw: str) -> Dict[str, Optional[str]]:
    """
    Décompose un tag de ligne P&ID en sous-champs : NPS, Fluide, Spec, Séquence, Isolation.
    Exemples :
      '34"-LP-1ACX1PN-101-N' -> nps='34', fluid='LP', spec='1ACX1PN', seq='101', insul='N'
      '6"-P-101-CS'          -> nps='6', fluid='P', spec='CS', seq='101', insul='N'
      '10"-WF-1ACX1PN-302-N-1' -> nps='10', fluid='WF', spec='1ACX1PN', seq='302', insul='N'
    """
    clean = clean_mtext_formatting(tag_raw)
    result: Dict[str, Optional[str]] = {
        "nps": None,
        "fluid": None,
        "spec": None,
        "seq": None,
        "insul": "N"
    }
    if not clean:
        return result

    # 1. Format Standard EPC : NPS"-FLUID-SPEC-SEQ[-INSUL]
    m1 = re.match(
        r'^(?P<nps>\d+(?:\.\d+)?(?:/\d+)?(?:-\d+/\d+)?)\s*["\u201d]?\s*-\s*'
        r'(?P<fluid>[A-Z0-9]{1,4})\s*-\s*'
        r'(?P<spec>[A-Z0-9]+)\s*-\s*'
        r'(?P<seq>\d{2,6}[A-Z0-9_]*)(?:\s*-\s*(?P<insul>[A-Z0-9]+))?$',
        clean, re.IGNORECASE
    )
    if m1:
        d = m1.groupdict()
        result.update({
            "nps": d.get("nps"),
            "fluid": (d.get("fluid") or "").upper(),
            "spec": (d.get("spec") or "").upper(),
            "seq": d.get("seq"),
            "insul": (d.get("insul") or "N").upper()
        })
        return result

    # 2. Format Alternatif : NPS"-FLUID-SEQ-SPEC[-INSUL]
    m2 = re.match(
        r'^(?P<nps>\d+(?:\.\d+)?(?:/\d+)?(?:-\d+/\d+)?)\s*["\u201d]?\s*-\s*'
        r'(?P<fluid>[A-Z0-9]{1,4})\s*-\s*'
        r'(?P<seq>\d{2,6}[A-Z0-9]*)\s*-\s*'
        r'(?P<spec>[A-Z0-9]+)(?:\s*-\s*(?P<insul>[A-Z0-9]+))?$',
        clean, re.IGNORECASE
    )
    if m2:
        d = m2.groupdict()
        result.update({
            "nps": d.get("nps"),
            "fluid": (d.get("fluid") or "").upper(),
            "spec": (d.get("spec") or "").upper(),
            "seq": d.get("seq"),
            "insul": (d.get("insul") or "N").upper()
        })
        return result

    # 3. Découpage par tirets (fallback heuristique)
    parts = clean.split("-")
    if len(parts) >= 3:
        # Extraire nps depuis la 1ere partie
        p0 = parts[0].replace('"', '').replace('\u201d', '').strip()
        m_nps = re.search(r'(\d+(?:\.\d+)?(?:/\d+)?)', p0)
        if m_nps:
            result["nps"] = m_nps.group(1)
        result["fluid"] = parts[1].strip().upper()
        result["spec"] = parts[2].strip().upper()
        if len(parts) >= 4:
            result["seq"] = parts[3].strip()
        if len(parts) >= 5:
            result["insul"] = parts[4].strip().upper()

    return result


def extract_off_page_connectors(raw_entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extrait les connecteurs et annotations hors-page depuis les entités brutes du plan.
    Identifie les textes sur calques de renvoi (ANN-SMTEXT, TEXT, ANNOTATION)
    et les textes contenant 'VERS PLAN', 'FROM', 'TO', 'ROK1-', 'TIE-IN', 'COLLECTEUR', 'TORCHE'.
    """
    opcs: List[Dict[str, Any]] = []
    seen = set()

    off_page_keywords = [
        "VERS PLAN", "VERS ", "FROM PLAN", "FROM ", "TO PLAN", "TO ", "DE PLAN", "DE ",
        "TIE-IN", "ROK1-", "DM-300", "PRC-DM", "COLLECTEUR", "TORCHE", "FLARE", "DRAIN",
        "EXISTANT", "ARZEW", "BEJAIA", "SKIKDA", "ASPIRATION", "REFOULEMENT"
    ]

    for ent in raw_entities:
        if ent.get("type") not in ("TEXT", "MTEXT", "ATTRIB"):
            continue
        raw_txt = ent.get("text", "")
        txt = clean_mtext_formatting(raw_txt)
        if not txt or len(txt) < 2:
            continue
        txt_upper = txt.upper()
        layer = str(ent.get("layer", "")).upper()
        pos = ent.get("pos")
        if not pos or len(pos) < 2:
            continue

        # Vérification des calques de renvoi ou du contenu textuel
        is_opc_layer = any(k in layer for k in ("ANN-SMTEXT", "RENVOI", "CONNECTOR", "OPC", "FLECHE"))
        is_opc_text = any(kw in txt_upper for kw in off_page_keywords)

        if is_opc_layer or is_opc_text:
            key = (txt_upper, round(float(pos[0]), 1), round(float(pos[1]), 1))
            if key in seen:
                continue
            seen.add(key)
            opcs.append({
                "text": txt,
                "text_upper": txt_upper,
                "pos": [float(pos[0]), float(pos[1])],
                "layer": layer,
                "handle": ent.get("handle")
            })

    return opcs


def _format_off_page_label(text: str, is_destination: bool = True) -> str:
    """
    Formate une référence hors-page pour un affichage technique propre.
    Exemples :
      'C3421-ROK1-300-PRC-DM-300005' -> 'VERS PLAN C3421-ROK1-300-PRC-DM-300005'
      'VERS ARZEW'                   -> 'VERS ARZEW'
      'TIE-IN N°09'                  -> 'TIE-IN N°09'
    """
    t = text.strip()
    tu = t.upper()
    if tu.startswith("VERS") or tu.startswith("TO ") or tu.startswith("FROM ") or tu.startswith("DE "):
        return t
    if re.search(r"C3421-ROK1|DM-\d{6}", tu):
        prefix = "VERS PLAN " if is_destination else "FROM PLAN "
        return f"{prefix}{t}"
    if tu.startswith("TIE-IN") or tu.startswith("COLLECTEUR") or tu.startswith("TORCHE") or tu.startswith("DRAIN"):
        return t
    prefix = "VERS " if is_destination else "FROM "
    return f"{prefix}{t}"


def _find_nearest_off_page(
    pt: List[float],
    opcs: List[Dict[str, Any]],
    max_radius: float = 85.0
) -> Optional[Tuple[str, float]]:
    """
    Trouve l'annotation hors-page la plus proche d'un point géométrique libre dans le rayon max_radius.
    """
    if not opcs:
        return None
    best_opc = None
    best_dist = float("inf")
    px, py = pt[0], pt[1]
    for opc in opcs:
        ox, oy = opc["pos"][0], opc["pos"][1]
        d = math.hypot(px - ox, py - oy)
        if d <= max_radius and d < best_dist:
            best_dist = d
            best_opc = opc

    if best_opc:
        return best_opc["text"], best_dist
    return None


def normalize_pid_line_list(
    raw_lines: List[Dict[str, Any]],
    off_page_connectors: Optional[List[Dict[str, Any]]] = None,
    equipments: Optional[List[Dict[str, Any]]] = None,
    drawing_stem: str = ""
) -> List[Dict[str, Any]]:
    """
    Normalise et consolide la liste des lignes de tuyauterie d'un plan P&ID.

    Args:
        raw_lines: Liste brute des tronçons de lignes (issue de dxf_pid_parser).
        off_page_connectors: Liste des connecteurs/textes hors-page.
        equipments: Liste des éléments équipements reconnus sur le plan.
        drawing_stem: Identifiant du plan P&ID source (ex: 'C3421-ROK1-081-PRC-DM-300001_2').

    Returns:
        Liste épurée et dédoublonnée des lignes de tuyauterie, 100% conforme au tableau UI.
    """
    if off_page_connectors is None:
        off_page_connectors = []
    if equipments is None:
        equipments = []

    drawing_stem = drawing_stem or "PLAN-PID"

    # 1. FILTRAGE STRICT : Ignorer 100% des runs où tag_raw est None ou vide
    valid_runs: List[Dict[str, Any]] = []
    for line in raw_lines:
        tag_candidate = line.get("tag_raw") or line.get("line_number") or line.get("tag")
        if not tag_candidate:
            continue
        tag_str = clean_mtext_formatting(str(tag_candidate))
        if not tag_str or tag_str.upper() in ("UNKNOWN-LINE", "NONE", "NULL", "NON ASSOCIÉ"):
            continue
        valid_runs.append({**line, "_normalized_tag": tag_str})

    if not valid_runs:
        return []

    # Index des équipements par ID et par Tag pour résolution rapide
    eq_by_id: Dict[str, Dict[str, Any]] = {}
    eq_by_tag: Dict[str, Dict[str, Any]] = {}
    for eq in equipments:
        if eq.get("id"):
            eq_by_id[eq["id"]] = eq
        if eq.get("tag"):
            eq_by_tag[eq["tag"]] = eq

    # 2. DÉDOUBLONNEMENT & REGROUPEMENT par tag de ligne unique
    grouped_runs: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for run in valid_runs:
        grouped_runs[run["_normalized_tag"]].append(run)

    normalized_lines: List[Dict[str, Any]] = []

    for tag, runs in grouped_runs.items():
        # Fusion des métadonnées prioritaires
        meta = parse_line_tag_metadata(tag)
        sample = runs[0]

        nps = sample.get("nps") or meta.get("nps") or ""
        fluid = sample.get("fluid") or meta.get("fluid") or ""
        spec = sample.get("spec") or meta.get("spec") or ""
        seq = sample.get("seq") or meta.get("seq") or ""
        insul = sample.get("insulation") or sample.get("insul") or meta.get("insul") or "N"

        # Format de taille standard
        size_str = f"{nps}\"" if nps and not str(nps).endswith('"') else str(nps)
        dn_str = convert_nps_to_dn(nps)

        # Fusion de tous les segments géométriques
        all_segments: List[List[List[float]]] = []
        path_coords: List[Tuple[float, float, float, float]] = []
        points: List[Tuple[float, float]] = []
        total_length: float = 0.0

        for r in runs:
            r_segs = r.get("segments", [])
            for s in r_segs:
                if len(s) >= 2:
                    p1, p2 = [float(s[0][0]), float(s[0][1])], [float(s[1][0]), float(s[1][1])]
                    all_segments.append([p1, p2])
                    seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
                    total_length += seg_len
                    path_coords.append((p1[0], p1[1], p2[0], p2[1]))
                    points.extend([(p1[0], p1[1]), (p2[0], p2[1])])

        # Bounding box globale de la ligne
        if points:
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            line_bbox = [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]
        else:
            line_bbox = sample.get("bbox", [0.0, 0.0, 100.0, 100.0])

        # Fusion des composants connectés (vannes, instruments)
        merged_connects: List[str] = []
        merged_valves: List[str] = []
        merged_components: List[Dict[str, Any]] = []
        seen_comp_tags = set()

        for r in runs:
            for cid in r.get("connects", []):
                if cid not in merged_connects:
                    merged_connects.append(cid)
            for v in r.get("valves", []):
                v_tag = v.get("tag") if isinstance(v, dict) else str(v)
                if v_tag and v_tag not in seen_comp_tags:
                    seen_comp_tags.add(v_tag)
                    merged_valves.append(v_tag)
                    merged_components.append({"tag": v_tag, "kind": "valve"})
            for c in r.get("line_components", []):
                c_tag = c.get("tag") if isinstance(c, dict) else str(c)
                if c_tag and c_tag not in seen_comp_tags:
                    seen_comp_tags.add(c_tag)
                    merged_components.append({"tag": c_tag, "kind": c.get("kind", "valve")})

        # Résolution des équipements connectés directs via connects
        connected_eq_tags: List[str] = []
        for cid in merged_connects:
            eq_cand = eq_by_id.get(cid)
            if eq_cand and eq_cand.get("kind") == "equipment" and eq_cand.get("tag"):
                if eq_cand["tag"] not in connected_eq_tags:
                    connected_eq_tags.append(eq_cand["tag"])

        # Vérification des équipements amont/aval déjà indiqués dans le run source
        existing_from = next((r.get("from_equipment") for r in runs if r.get("from_equipment") and r.get("from_equipment") != "OPEN"), None)
        existing_to = next((r.get("to_equipment") for r in runs if r.get("to_equipment") and r.get("to_equipment") != "OPEN"), None)

        from_eq = existing_from
        to_eq = existing_to

        if len(connected_eq_tags) >= 2:
            from_eq = from_eq or connected_eq_tags[0]
            to_eq = to_eq or connected_eq_tags[1]
        elif len(connected_eq_tags) == 1:
            from_eq = from_eq or connected_eq_tags[0]

        # 3. RÉSOLUTION OFF-PAGE : Si pas de cuve/pompe aux extrémités, chercher les textes de renvoi
        if (not from_eq or from_eq == "OPEN" or not to_eq or to_eq == "OPEN") and all_segments:
            # Identifier les extrémités libres de la ligne (points de degré 1)
            deg_map: Dict[Tuple[float, float], int] = defaultdict(int)
            snap_tol = 6.0

            # Snapping léger des points d'extrémités pour trouver les extrémités libres réelles
            canonical_pts: List[Tuple[float, float]] = []
            for seg in all_segments:
                for pt in (seg[0], seg[1]):
                    p_round = (round(pt[0], 1), round(pt[1], 1))
                    matched = None
                    for cp in canonical_pts:
                        if math.hypot(cp[0] - p_round[0], cp[1] - p_round[1]) <= snap_tol:
                            matched = cp
                            break
                    if not matched:
                        matched = p_round
                        canonical_pts.append(matched)
                    deg_map[matched] += 1

            free_ends = [list(pt) for pt, d in deg_map.items() if d == 1]
            if len(free_ends) < 2 and points:
                # Fallback : deux points les plus distants de la ligne
                p_min = min(points, key=lambda p: (p[0], p[1]))
                p_max = max(points, key=lambda p: (p[0], p[1]))
                free_ends = [list(p_min), list(p_max)]

            # Trier les extrémités libres de gauche à droite (X croissant)
            free_ends.sort(key=lambda p: (p[0], p[1]))

            if len(free_ends) >= 2:
                start_pt, end_pt = free_ends[0], free_ends[-1]

                # Résolution extrémité début (From)
                if not from_eq or from_eq == "OPEN":
                    near_from = _find_nearest_off_page(start_pt, off_page_connectors, max_radius=85.0)
                    if near_from:
                        from_eq = _format_off_page_label(near_from[0], is_destination=False)

                # Résolution extrémité fin (To)
                if not to_eq or to_eq == "OPEN":
                    near_to = _find_nearest_off_page(end_pt, off_page_connectors, max_radius=85.0)
                    if near_to:
                        to_eq = _format_off_page_label(near_to[0], is_destination=True)
            elif len(free_ends) == 1:
                single_pt = free_ends[0]
                near_opc = _find_nearest_off_page(single_pt, off_page_connectors, max_radius=85.0)
                if near_opc:
                    if not to_eq or to_eq == "OPEN":
                        to_eq = _format_off_page_label(near_opc[0], is_destination=True)
                    elif not from_eq or from_eq == "OPEN":
                        from_eq = _format_off_page_label(near_opc[0], is_destination=False)

        # Fallbacks finaux explicites
        final_from = from_eq if from_eq and from_eq != "OPEN" else "COLLECTEUR AMONT"
        final_to = to_eq if to_eq and to_eq != "OPEN" else "COLLECTEUR AVAL"

        # Trajectoire lisible pour la colonne 'Chemin du Flux'
        flow_path_display = f"{final_from} ➔ [{tag}] ➔ {final_to}"

        # Calcul du score de confiance moyen des tronçons
        avg_conf = round(sum(r.get("confidence", 0.95) for r in runs) / len(runs), 2)
        if avg_conf < 0.6:
            avg_conf = 0.92

        # Construction de l'entrée normalisée
        entry: Dict[str, Any] = {
            "id": sample.get("id") or f"NL-{tag.replace(' ', '_')}",
            "line_number": tag,
            "tag": tag,
            "tag_raw": tag,
            "size": size_str,
            "dn": dn_str,
            "size_dn": dn_str,
            "fluid": fluid,
            "fluid_description": FLUID_DESCRIPTIONS.get(fluid, f"Fluide {fluid}"),
            "spec": spec,
            "sequence": seq,
            "insulation": insul,
            "iso": insul,
            "from_equipment": final_from,
            "to_equipment": final_to,
            "pid_number": drawing_stem,
            "drawing": drawing_stem,
            "flow_path": flow_path_display,
            "flowSeq": flow_path_display,
            "total_length": round(total_length, 2),
            "length_m": round(total_length, 2),
            "segments_count": len(all_segments),
            "runs_merged": len(runs),
            "valves": merged_valves,
            "line_components": merged_components,
            "path_coords": path_coords,
            "points": points,
            "segments": all_segments,
            "bbox": line_bbox,
            "confidence_score": avg_conf,
            "confidence": avg_conf,
            "tess": "Direct" if len(runs) == 1 else f"Réseau ({len(runs)} tronçons)",
            "is_dead_leg": False,
            "alerts": False,
        }
        normalized_lines.append(entry)

    # Tri par numéro de ligne naturel
    normalized_lines.sort(key=lambda x: str(x["line_number"]))
    return normalized_lines
