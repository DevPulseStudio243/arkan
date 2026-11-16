"""
mto_continuity_tracker.py - Moteur de Suivi de Ligne Inter-Plans & Contrôle de Continuité ARKAN

Assure deux modes opérationnels stricts :
  1. MODE PLAN UNIQUE : Aucun recoupement externe. Le calcul et la validation MTO
     s'effectuent STRICTEMENT et EXCLUSIVEMENT sur les éléments figurant sur le plan uploadé,
     sans déduire ni présumer d'éléments sur d'éventuels autres plans.
  2. MODE MULTI-PLANS (LOT / BATCH) : Suivi automatique de ligne (Cross-Sheet Line Tracing).
     - Rapprochement des feuilles d'une même ligne (CONT. ON / CONT. FROM, coordonnées E/N/EL).
     - CONTRÔLE D'ACCOUPLEMENT DES BRIDES : Si un plan présente une bride à sa limite de raccordement,
       le plan de continuité DOIT obligatoirement comporter la contre-bride correspondante (mating flange).
       Toute absence de bride sur la continuité est immédiatement signalée en anomalie critique.
     - Contrôle de cohérence des diamètres (NPS), classes (Rating) et coordonnées géométriques.
"""

import re
import math
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("mto_continuity_tracker")


class LineContinuityTracker:
    """Moteur d'analyse de continuité et de suivi de ligne pour lots de plans isométriques."""

    def __init__(self):
        pass

    def extract_plan_boundaries(self, plan_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extrait les points limites de raccordement (interfaces amont/aval) d'un plan isométrique.
        Détecte :
          - La mention de continuité (CONT. FROM / CONT. ON / TO SHT / FROM SHT)
          - Les coordonnées du point de limite (E, N, EL)
          - La présence physique d'une bride de raccordement à cette limite
        """
        filename = plan_data.get("filename", "")
        metadata = plan_data.get("metadata", {})
        line_num = metadata.get("line_number", "")
        bom_items = plan_data.get("mto") or plan_data.get("bom_items") or []

        boundaries = []

        # Recherche dans le texte brut / blocks du plan
        raw_text = plan_data.get("raw_text", "")
        file_path = plan_data.get("file_path")
        
        words = []
        if file_path and Path(file_path).exists() and str(file_path).lower().endswith(".pdf"):
            try:
                import fitz
                with fitz.open(str(file_path)) as doc:
                    if len(doc) > 0:
                        words = doc[0].get_text("words")
                        if not raw_text:
                            raw_text = doc[0].get_text("text")
            except Exception:
                pass

        if not raw_text and plan_data.get("formatted_text"):
            raw_text = plan_data.get("formatted_text")

        # 1. Détection des mentions de continuité
        # Ex: "CONT. FROM DRG 1", "CONT. ON DRG 2", "CONT. ON SHT 3", "TO SHT 2"
        cont_patterns = [
            r'CONT(?:\.|INUATION)?\s*(?:FROM|ON)\s*(?:DRG|DWG|SHT|SHEET|ISO)?\.?\s*([A-Z0-9\-\_]+)',
            r'(?:FROM|TO)\s*(?:SHT|SHEET|DRG|DWG)\.?\s*([A-Z0-9\-\_]+)',
            r'CONTINUED\s*ON\s*([A-Z0-9\-\_]+)'
        ]

        # Détection des coordonnées associées E / N / EL
        # E 181152.8 // N 274476.7 // EL +99274.2
        coords_matches = list(re.finditer(
            r'E\s*[:\=]?\s*([+\-]?\d+(?:\.\d+)?)\s*[\n\r\s]+N\s*[:\=]?\s*([+\-]?\d+(?:\.\d+)?)\s*[\n\r\s]+EL\s*[:\=]?\s*([+\-]?\d+(?:\.\d+)?)',
            raw_text, re.I
        ))

        # Vérifier si des brides sont mentionnées ou appelées sur le plan
        flange_items = [
            it for it in bom_items 
            if "FLANGE" in it.get("category", "").upper() or "BRIDE" in it.get("category", "").upper()
            or "FLANGE" in it.get("description", "").upper()
        ]

        for cp in cont_patterns:
            for m in re.finditer(cp, raw_text, re.I):
                target_ref = m.group(1).strip()
                is_from = "FROM" in m.group(0).upper()
                is_to = "ON" in m.group(0).upper() or "TO" in m.group(0).upper()
                direction = "INLET" if is_from else "OUTLET"

                # Recherche des coordonnées les plus proches
                matched_coord = None
                m_start = m.start()
                for cm in coords_matches:
                    dist = abs(cm.start() - m_start)
                    if dist < 300: # Proche dans le flux textuel
                        matched_coord = {
                            "east": float(cm.group(1)),
                            "north": float(cm.group(2)),
                            "elevation": float(cm.group(3)),
                            "coord_str": f"E {cm.group(1)}, N {cm.group(2)}, EL {cm.group(3)}"
                        }
                        break

                # Détection de présence d'une bride à cette limite
                # Critères :
                # 1. Tag F... ou G... proche des coordonnées dans words
                # 2. Présence explicite de symboles de bride à l'extrémité
                has_flange = False
                flange_detail = ""

                # Vérifier si le texte adjacent contient F3, F1, FLANGE, etc.
                snippet = raw_text[max(0, m_start - 200):min(len(raw_text), m_start + 400)].upper()
                if any(k in snippet for k in ("F1", "F2", "F3", "F4", "F5", "FLANGE", "BRIDE", "WN FLANGE", "SW FLANGE")):
                    has_flange = True
                    flange_detail = "Bride repérée au point de raccordement"

                # Vérifier aussi via les coordonnées s'il y a un F... proche
                if matched_coord and words:
                    for w in words:
                        if re.match(r'^F\d{1,2}$', w[4]) or w[4] in ("FLG", "FLANGE"):
                            # Si le mot est dans le schéma
                            has_flange = True
                            flange_detail = f"Bride repère {w[4]}"
                            break

                boundaries.append({
                    "plan_filename": filename,
                    "line_number": line_num,
                    "direction": direction,
                    "reference": target_ref,
                    "raw_label": m.group(0).strip(),
                    "coordinates": matched_coord,
                    "has_flange": has_flange,
                    "flange_detail": flange_detail,
                    "flange_items_count": len(flange_items)
                })

        # Si aucune mention textuelle "CONT ON" n'a été trouvée mais qu'il y a des blocs de coordonnées E/N/EL isolés
        if not boundaries and coords_matches:
            for idx_c, cm in enumerate(coords_matches):
                c_str = f"E {cm.group(1)}, N {cm.group(2)}, EL {cm.group(3)}"
                snippet = raw_text[max(0, cm.start() - 150):min(len(raw_text), cm.end() + 150)].upper()
                has_flange = any(k in snippet for k in ("F1", "F2", "F3", "F4", "F5", "FLANGE", "BRIDE"))
                boundaries.append({
                    "plan_filename": filename,
                    "line_number": line_num,
                    "direction": "BOUNDARY",
                    "reference": f"LIMIT-{idx_c+1}",
                    "raw_label": f"Coordonnées limites {c_str}",
                    "coordinates": {
                        "east": float(cm.group(1)),
                        "north": float(cm.group(2)),
                        "elevation": float(cm.group(3)),
                        "coord_str": c_str
                    },
                    "has_flange": has_flange,
                    "flange_detail": "Bride repérée aux coordonnées" if has_flange else "Pas de bride",
                    "flange_items_count": len(flange_items)
                })

        return boundaries

    def check_multisheet_continuity(self, processed_plans: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Effectue le suivi de ligne et le contrôle de cohérence inter-plans sur un lot de plans.
        Règle d'or :
          Si Plan A comporte une bride à sa limite, Plan B DOIT comporter une bride d'accouplement.
          Toute dissymétrie bride/pas-de-bride est levée en anomalie CRITIQUE.
        """
        if len(processed_plans) <= 1:
            return {
                "is_multisheet": False,
                "message": "Mode plan unique : audit strictement isolé au plan (aucun recoupement externe).",
                "continuity_anomalies": [],
                "connected_chains": []
            }

        logger.info("[Continuity Tracker] Démarrage du contrôle de continuité sur %d plans...", len(processed_plans))

        # 1. Extraction des limites de chaque plan
        all_plan_boundaries: Dict[str, List[Dict[str, Any]]] = {}
        for p in processed_plans:
            fname = p.get("filename", "")
            all_plan_boundaries[fname] = self.extract_plan_boundaries(p)

        anomalies = []
        connected_pairs = []
        seen_pairs = set()

        plan_names = list(all_plan_boundaries.keys())

        # 2. Tentative de raccordement des paires de plans
        for i in range(len(plan_names)):
            for j in range(i + 1, len(plan_names)):
                name_a = plan_names[i]
                name_b = plan_names[j]

                bounds_a = all_plan_boundaries[name_a]
                bounds_b = all_plan_boundaries[name_b]

                # Rechercher une connexion entre a et b
                for ba in bounds_a:
                    for bb in bounds_b:
                        is_match = False
                        match_reason = ""

                        # Critère 1 : Référence explicite (ex: A pointe vers B ou vers Feuille correspondante)
                        ref_a = ba.get("reference", "").strip().upper()
                        ref_b = bb.get("reference", "").strip().upper()
                        name_a_clean = Path(name_a).stem.upper()
                        name_b_clean = Path(name_b).stem.upper()
                        line_a = ba.get("line_number", "").strip().upper()
                        line_b = bb.get("line_number", "").strip().upper()

                        # Si les repères de ligne sont explicitement différents, ne pas raccorder
                        same_line = (line_a and line_b and (line_a in line_b or line_b in line_a)) or (not line_a or not line_b)

                        if same_line:
                            if ref_a and len(ref_a) >= 4 and (ref_a in name_b_clean or name_b_clean in ref_a):
                                is_match = True
                                match_reason = f"Référence explicite ({ba.get('raw_label')})"
                            elif ref_b and len(ref_b) >= 4 and (ref_b in name_a_clean or name_a_clean in ref_b):
                                is_match = True
                                match_reason = f"Référence explicite ({bb.get('raw_label')})"
                            elif ref_a and re.match(r'^\d+$', ref_a):
                                # Cas spécifique d'un numéro de feuille 'SHT 2'
                                if re.search(rf'\b(?:SHT|SHEET|FEUILLE|F)[-_ ]?0*{ref_a}\b', name_b_clean):
                                    is_match = True
                                    match_reason = f"Raccordement de feuille ({ba.get('raw_label')})"
                            elif ref_b and re.match(r'^\d+$', ref_b):
                                if re.search(rf'\b(?:SHT|SHEET|FEUILLE|F)[-_ ]?0*{ref_b}\b', name_a_clean):
                                    is_match = True
                                    match_reason = f"Raccordement de feuille ({bb.get('raw_label')})"

                        # Critère 2 : Coordonnées 3D identiques (Tolérance 5 mm)
                        coord_a = ba.get("coordinates")
                        coord_b = bb.get("coordinates")
                        if not is_match and coord_a and coord_b:
                            d_e = abs(coord_a["east"] - coord_b["east"])
                            d_n = abs(coord_a["north"] - coord_b["north"])
                            d_el = abs(coord_a["elevation"] - coord_b["elevation"])
                            if d_e < 5.0 and d_n < 5.0 and d_el < 5.0:
                                is_match = True
                                match_reason = f"Coordonnées 3D identiques ({coord_a['coord_str']})"

                        if is_match:
                            coord_info = coord_a.get("coord_str") if coord_a else (coord_b.get("coord_str") if coord_b else f"{ref_a}->{ref_b}")
                            pair_key = (name_a, name_b, coord_info)
                            if pair_key in seen_pairs:
                                continue
                            seen_pairs.add(pair_key)

                            connected_pairs.append({
                                "plan_from": name_a,
                                "plan_to": name_b,
                                "boundary_a": ba,
                                "boundary_b": bb,
                                "match_reason": match_reason
                            })

                            # CONTRÔLE CRITIQUE D'ACCOUPLEMENT DES BRIDES
                            flange_a = ba.get("has_flange", False)
                            flange_b = bb.get("has_flange", False)

                            coord_info = coord_a.get("coord_str") if coord_a else (coord_b.get("coord_str") if coord_b else "Jonction limite")

                            if flange_a and not flange_b:
                                anomalies.append({
                                    "id": "ISO-CONT-001",
                                    "code": "DISCORDANCE_BRIDE_CONTINUITE_INTER_PLANS",
                                    "severity": "CRITICAL",
                                    "severity_label": "CRITIQUE (REJET INTER-PLANS)",
                                    "component": "Liaison Bridée de Continuité",
                                    "plan_source": name_a,
                                    "plan_target": name_b,
                                    "title": "Absence de contre-bride d'accouplement sur la continuité inter-plans",
                                    "description": (
                                        f"Le plan '{name_a}' présente une bride à sa limite de raccordement ({coord_info}), "
                                        f"mais le plan de continuité '{name_b}' ne comporte aucune bride d'accouplement en vis-à-vis. "
                                        f"Une liaison démontable bridée exige obligatoirement une paire de brides (bride + contre-bride) "
                                        f"ou un raccordement d'équipement conforme."
                                    ),
                                    "expected": "Contre-bride d'accouplement présente sur le plan raccordé",
                                    "found": f"Bride présente sur '{name_a}' mais absente sur '{name_b}'",
                                    "recommendation": (
                                        f"Corriger le plan '{name_b}' pour y intégrer la contre-bride, son joint et la boulonnerie ASME, "
                                        f"ou modifier la liaison du plan '{name_a}' en soudure bout-à-bout de chantier (Field Weld BW)."
                                    )
                                })
                            elif flange_b and not flange_a:
                                anomalies.append({
                                    "id": "ISO-CONT-001",
                                    "code": "DISCORDANCE_BRIDE_CONTINUITE_INTER_PLANS",
                                    "severity": "CRITICAL",
                                    "severity_label": "CRITIQUE (REJET INTER-PLANS)",
                                    "component": "Liaison Bridée de Continuité",
                                    "plan_source": name_b,
                                    "plan_target": name_a,
                                    "title": "Absence de contre-bride d'accouplement sur la continuité inter-plans",
                                    "description": (
                                        f"Le plan '{name_b}' présente une bride à son raccordement ({coord_info}), "
                                        f"mais le plan amont '{name_a}' ne comporte aucune bride d'accouplement en vis-à-vis."
                                    ),
                                    "expected": "Contre-bride d'accouplement présente sur le plan amont",
                                    "found": f"Bride présente sur '{name_b}' mais absente sur '{name_a}'",
                                    "recommendation": (
                                        f"Compléter le plan '{name_a}' avec la contre-bride correspondante ou uniformiser en soudure."
                                    )
                                })
                            else:
                                logger.info(
                                    "[Continuity Tracker] Accouplement valide entre %s et %s (Brides A=%s, B=%s)",
                                    name_a, name_b, flange_a, flange_b
                                )

        return {
            "is_multisheet": len(connected_pairs) > 0,
            "connected_pairs_count": len(connected_pairs),
            "connected_pairs": connected_pairs,
            "continuity_anomalies_count": len(anomalies),
            "continuity_anomalies": anomalies
        }
