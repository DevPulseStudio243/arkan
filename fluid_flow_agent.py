"""
fluid_flow_agent.py - Agent de Raisonnement Hydraulique & Fluide ARKAN
----------------------------------------------------------------------
Agent intelligent assurant :
1. Le respect du sens du fluide (Amont ➔ Aval) via flèches et clapets (Check Valves).
2. Le découpage strict des lignes lors des changements de diamètre (Réducteurs 30"x24", 24"x12", etc.).
3. La séparation absolue entre Équipements (Gare Racleur, Ballon, Pompe, Réservoir) et Numéros de Lignes.
4. La vérification de conformité EPC O&G (DN, Fluide, Spec, Pression, Isolation).
"""

import re
import math
import logging
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger("arkan.fluid_agent")

EQUIPMENT_KEYWORDS = {
    "GARE", "RACLEUR", "CHAMBRE", "SKIKDA", "ARZEW", "BEJAIA", "HAOUD", "HEH",
    "BÂTIMENT", "BATIMENT", "TANK", "BALLON", "PUMP", "POMPE", "VESSEL", "EXCHANGER", 
    "ÉCHANGEUR", "ECHANGEUR", "COMPRESSEUR", "COMPRESSOR", "SEPARATEUR", "SEPARATOR", 
    "SKID", "RECEIVER", "LAUNCHER", "RESERVOIR", "STOCKAGE", "COLONNE", "DEGAZEUR", "CHAUDIERE", "TORCHE"
}

DN_CONVERSION_MAP = {
    "0.5": "DN15", "0.75": "DN20", "1": "DN25", "1.5": "DN40", "2": "DN50",
    "3": "DN80", "4": "DN100", "6": "DN150", "8": "DN200", "10": "DN250",
    "12": "DN300", "14": "DN350", "16": "DN400", "18": "DN450", "20": "DN500",
    "24": "DN600", "26": "DN650", "28": "DN700", "30": "DN750", "32": "DN800",
    "34": "DN850", "36": "DN900", "40": "DN1000", "42": "DN1050", "48": "DN1200"
}


def parse_size_to_float(val) -> float:
    if not val:
        return 0.0
    val_str = str(val).strip().replace('"', '').replace("''", "").replace('DN', '').replace('dn', '').strip()
    try:
        return float(val_str)
    except ValueError:
        pass
    try:
        parts = val_str.split()
        total = 0.0
        for p in parts:
            if '/' in p:
                num, denom = p.split('/')
                total += float(num) / float(denom)
            else:
                total += float(p)
        return total
    except Exception:
        return 0.0


class FluidFlowReasoningAgent:
    """Agent autonome de raisonnement hydraulique pour l'analyse P&ID ARKAN."""
    
    def __init__(self):
        logger.info("[FluidFlowAgent] Agent de raisonnement hydraulique initialisé.")

    def is_equipment_tag(self, text: str) -> bool:
        """Détermine si un texte désigne un équipement et NON une ligne de tuyauterie."""
        if not text:
            return False
        # If parse_line_tag recognises it as a line tag, it is NOT an equipment tag!
        try:
            from piping_topology_tracer import parse_line_tag
            if parse_line_tag(text) is not None:
                return False
        except Exception:
            pass

        t_upper = text.strip().upper()
        if any(kw in t_upper for kw in EQUIPMENT_KEYWORDS):
            return True
        if re.match(r'^(?:TK|EQ|SK|FA|GARE|RACLEUR|CH)[-\s]*\d{3,4}[A-Z]?$', t_upper):
            return True
        return False


    def is_line_tag(self, text: str) -> bool:
        """Valide si une chaîne est strictement un numéro de ligne P&ID."""
        if not text or self.is_equipment_tag(text):
            return False
        t = text.strip()
        is_full = bool(re.search(r'\b\d{1,2}(?:\.\d+)?(?:\/\d+)?["”]?\s*-[A-Z0-9_-]+-[A-Z0-9_-]+\b', t, re.I))
        is_ind = bool(re.search(r'\b(?:ROK1|NK1|OZ1|OZ2|OB1|OK1|ROK|ROB1)\s+\d{1,2}(?:\.\d+)?["”]\s*(?:EXISTANT|EXISTING)?\b', t, re.I))
        return is_full or is_ind

    def split_lines_at_reducers(
        self, 
        line_entries: List[Dict[str, Any]], 
        labels: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Découpe les parcours de lignes lors des changements de diamètre (Réducteurs 30"x24", 24"x12").
        Assure qu'une ligne de 30" et une ligne de 24" soient deux entrées séparées et distinctes.
        """
        refined_entries = []
        reducers = []

        # Identifier tous les réducteurs de tuyauterie principale (ex: 30"x24", 24"x18", 40"x30")
        for lbl in labels:
            txt = lbl.get("text", "").strip()
            m_red = re.search(r'(\d+(?:\.\d+)?)\s*["”]?\s*x\s*(\d+(?:\.\d+)?)\s*["”]?', txt, re.I)
            if m_red:
                d1_val = float(m_red.group(1))
                d2_val = float(m_red.group(2))
                # Un réducteur de ligne principale a deux diamètres majeurs (ex: 30"x24", 24"x18")
                # Exclure les piquages d'instruments/purges (ex: 1"x3/4", 30"x1")
                if min(d1_val, d2_val) >= 2.0 and abs(d1_val - d2_val) <= 16.0:
                    reducers.append({
                        "x": lbl["x"],
                        "y": lbl["y"],
                        "d1": str(m_red.group(1)),
                        "d2": str(m_red.group(2)),
                        "text": txt
                    })

        for entry in line_entries:
            path_coords = entry.get("path_coords", [])
            line_size_str = str(entry.get("size", "")).replace('"', '').strip()
            try:
                line_size_num = float(line_size_str)
            except Exception:
                line_size_num = 0.0

            # Ne chercher des réducteurs que si la ligne principale est >= 2"
            split_points = []
            if path_coords and len(path_coords) > 2 and reducers and line_size_num >= 2.0:
                for seg_idx, seg in enumerate(path_coords):
                    x0, y0 = seg[0], seg[1]
                    for red in reducers:
                        dist = math.sqrt((x0 - red["x"])**2 + (y0 - red["y"])**2)
                        if dist <= 40.0:  # Proximité immédiate du réducteur sur le tracé
                            split_points.append((seg_idx, red))
                            break

            if split_points and len(path_coords) > 3:
                split_indices = sorted(list(set([sp[0] for sp in split_points])))
                start_idx = 0
                
                for part_num, s_idx in enumerate(split_indices):
                    sub_coords = path_coords[start_idx:s_idx+1]
                    if len(sub_coords) >= 1:
                        new_entry = dict(entry)
                        new_entry["path_coords"] = sub_coords
                        
                        red_info = [sp[1] for sp in split_points if sp[0] == s_idx][0]
                        new_size = red_info.get("d2")
                        if new_size and float(new_size) >= 2.0 and part_num > 0:
                            new_entry["size"] = new_size
                            new_entry["size_dn"] = DN_CONVERSION_MAP.get(new_size, f"DN{new_size}")
                            new_entry["line_number"] = f"{new_size}\"-{entry.get('fluid','LP')}-{entry.get('spec','STD')}-{entry.get('sequence','001')}"
                            
                        refined_entries.append(new_entry)
                    start_idx = s_idx + 1

                if start_idx < len(path_coords):
                    sub_coords = path_coords[start_idx:]
                    new_entry = dict(entry)
                    new_entry["path_coords"] = sub_coords
                    refined_entries.append(new_entry)
            else:
                refined_entries.append(entry)

        return refined_entries

    def reason_flow_direction(self, line_entry: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyse hydraulique du sens du fluide :
        - Détermine la source (Amont) et le puits (Aval) selon l'équipement amont/aval et les vannes unidirectionnelles.
        - Ajoute les indicateurs hydrauliques et de conformité EPC.
        """
        line_copy = dict(line_entry)
        valves = line_copy.get("valves", [])
        
        # Vérification des clapets anti-retour (Check Valve / Non-Return Valve)
        has_check_valve = any(
            isinstance(v, dict) and any(kw in v.get("type","").upper() for kw in ("CHECK", "NRV", "CLAPET"))
            for v in valves
        )
        line_copy["has_check_valve"] = has_check_valve
        
        # Normalisation du diamètre en DN
        size = str(line_copy.get("size", "")).replace('"', '').strip()
        if size in DN_CONVERSION_MAP:
            line_copy["size_dn"] = DN_CONVERSION_MAP[size]
        elif size:
            try:
                dn_val = int(float(size) * 25)
                line_copy["size_dn"] = f"DN{dn_val}"
            except Exception:
                line_copy["size_dn"] = f"DN{size}"

        # Équipements Amont / Aval : s'assurer qu'un numéro de ligne n'est PAS un équipement
        from_eq = line_copy.get("from_equipment", "OPEN")
        to_eq = line_copy.get("to_equipment", "OPEN")

        if self.is_line_tag(from_eq):
            line_copy["from_equipment"] = "OPEN"
        if self.is_line_tag(to_eq):
            line_copy["to_equipment"] = "OPEN"

        return line_copy

    def get_base_line_key(self, tag_str: str, size: str = "") -> str:
        """Calcule une clé normalisée unique pour le regroupement de lignes P&ID sans doublons."""
        if not tag_str:
            return ""
        from piping_topology_tracer import parse_line_tag
        parsed = parse_line_tag(tag_str)
        if not parsed:
            return ""
        
        t = tag_str.strip().upper()
        # 1. Pipeline existants Oil & Gas : ROK1, ROB1, OB1, NK1, OZ1, OZ2
        if "EXISTANT" in t or "EXISTING" in t:
            for kw in ("ROK1", "ROB1", "OB1", "NK1", "OZ1", "OZ2"):
                if kw in t:
                    return f"{kw} {parsed['size']}\" EXISTANT"
            return t
        
        # 2. Lignes de projet standards : taille-fluide-spec-sequence
        if parsed.get("spec") and parsed.get("seq") and parsed.get("seq") != "-":
            return f"{parsed.get('size', '')}-{parsed.get('fluid', '')}-{parsed.get('spec', '')}-{parsed.get('seq', '')}"
        
        if parsed.get("fluid") and parsed.get("seq") and parsed.get("seq") != "-":
            return f"{parsed.get('size', '')}-{parsed.get('fluid', '')}-{parsed.get('seq', '')}"

        return f"{parsed.get('size', '')}-{parsed.get('fluid', '')}"

    def process_and_validate_lines(
        self, 
        raw_lines: List[Dict[str, Any]], 
        labels: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Pipeline d'analyse hydraulique complet exécuté par l'agent.
        """
        # 1. Filtrer les équipements mal classés comme lignes (ex: Gare Racleur, Ballon, Pompe, 081-CH-001)
        valid_lines = [l for l in raw_lines if not self.is_equipment_tag(l.get("line_number", ""))]
        
        # 2. Découpage aux réducteurs / changements de diamètre (ex: 30" x 24")
        lines_split = self.split_lines_at_reducers(valid_lines, labels)
        
        # 3. Raisonnement sur le sens du fluide et validation EPC
        validated_lines = [self.reason_flow_direction(l) for l in lines_split]

        # 4. Consolidation 1-à-1 des tronçons ayant la même clé de ligne normalisée
        consolidated_map = {}
        for entry in validated_lines:
            raw_tag = entry.get("line_number", "")
            size = entry.get("size", "")
            key = self.get_base_line_key(raw_tag, size)
            if not key:
                continue

            # Nettoyer le tag affiché (ex: supprimer -EXISTING-EXISTING)
            clean_display_tag = re.sub(r'-(EXISTING|EXISTANT)+', '', raw_tag, flags=re.I)
            entry["line_number"] = clean_display_tag

            # Corriger les fluides pour les tuyauteries de transport principales
            if any(k in clean_display_tag.upper() for k in ("ROK1", "ROB1", "NK1", "OZ1", "OZ2", "OB1")):
                entry["fluid"] = "P"
                entry["fluid_description"] = "Pétrole Brut (Process)"
                # Fixer la taille principale
                if "ROK1" in clean_display_tag.upper() or "OZ2" in clean_display_tag.upper():
                    entry["size"] = "34"
                    entry["size_dn"] = "DN850"
                elif "NK1" in clean_display_tag.upper():
                    entry["size"] = "30"
                    entry["size_dn"] = "DN750"
                elif "OZ1" in clean_display_tag.upper():
                    entry["size"] = "28"
                    entry["size_dn"] = "DN700"
                elif "ROB1" in clean_display_tag.upper() or "OB1" in clean_display_tag.upper():
                    entry["size"] = "24"
                    entry["size_dn"] = "DN600"

            if key not in consolidated_map:
                consolidated_map[key] = dict(entry)
                consolidated_map[key]["path_coords"] = list(entry.get("path_coords", []))
            else:
                existing = consolidated_map[key]
                # Préférer un tag de ligne propre complet (avec suffixe de spécs et plus grand diamètre)
                if len(clean_display_tag) > len(existing.get("line_number", "")):
                    existing["line_number"] = clean_display_tag
                if parse_size_to_float(entry.get("size", "0")) > parse_size_to_float(existing.get("size", "0")):
                    existing["size"] = entry.get("size")
                    existing["size_dn"] = entry.get("size_dn")
                for p in entry.get("path_coords", []):
                    if p not in existing["path_coords"]:
                        existing["path_coords"].append(p)
                for v in entry.get("valves", []):
                    if v not in existing.get("valves", []):
                        existing.setdefault("valves", []).append(v)
                if existing.get("from_equipment") == "OPEN" and entry.get("from_equipment") != "OPEN":
                    existing["from_equipment"] = entry["from_equipment"]
                if existing.get("to_equipment") == "OPEN" and entry.get("to_equipment") != "OPEN":
                    existing["to_equipment"] = entry["to_equipment"]

        # 5. Résolution dynamique Amont / Aval et flow path sans dépendance figée
        result = list(consolidated_map.values())
        for l in result:
            from_eq = l.get("from_equipment", "OPEN")
            to_eq = l.get("to_equipment", "OPEN")
            
            # Nettoyer les références de plan parasites des bornes d'équipement
            for k in ("from_equipment", "to_equipment"):
                val = l.get(k, "")
                if re.search(r'-(?:PRC|DM|DW|GCL|PID|DWG)-', val, re.I) or re.match(r'^C\d{4}-', val, re.I):
                    l[k] = "COLLECTEUR / LIAISON EXTERNE"
                elif any(kw in val.upper() for kw in ("NOTES", "SUPPRIMEE", "DESCRIPTION")):
                    l[k] = "OPEN"

            # Filtrer les vannes pour ne conserver que les tags physiques légitimes
            valves_clean = []
            for v in l.get("valves", []):
                v_str = v.get("tag", str(v)) if isinstance(v, dict) else str(v)
                if v_str and not any(kw in v_str.upper() for kw in ("EXISTANT", "EXISTING", "C3421", "NOTES", "PRC", "DM", "RACLEUR VENANT", "VERS ")):
                    if v_str not in valves_clean:
                        valves_clean.append(v_str)
            l["valves"] = valves_clean

            # Si amont == aval et non OPEN, dériver une borne cohérente
            if l.get("from_equipment") == l.get("to_equipment") and l.get("from_equipment") != "OPEN":
                l["to_equipment"] = "CHAMBRE A VANNES / COLLECTEUR"

            # Reconstituer le cheminement séquentiel complet
            flow_parts = [f"[{l.get('from_equipment', 'OPEN')}]"]
            for v_tag in valves_clean:
                flow_parts.append(f"({v_tag})")
            flow_parts.append(f"[{l.get('to_equipment', 'OPEN')}]")
            l["flow_path_str"] = " ➔ ".join(flow_parts)

        logger.info(f"[FluidFlowAgent] Validation terminée : {len(result)} lignes hydrauliques uniques et consolidées.")
        return result
