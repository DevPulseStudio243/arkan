"""
arh_descriptive_sheet_extractor.py
==================================
Extracteur haute précision pour l'État Descriptif & Fiche Technique ARH (Annexe E / Décret 21-261).
Supporte l'extraction multi-lignes, inversions Unités/Valeurs, annotations, codes ASME/ASTM,
et réconciliation avec le modèle IA fine-tuné ARH 3B.
"""

import re
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger("ARH-DescriptiveSheet")


class ARHDescriptiveSheetExtractor:
    """
    Extrait les 25+ paramètres techniques officiels d'un État Descriptif ARH :
    - Identification fabricant, année, code, lieu
    - Caractéristiques mécaniques & dimensionnelles (PMA, TMA, P_test, Epaisseur, Surépaisseur)
    - Nuances matières, contraintes admissibles, facteurs de joint, CND & traitement thermique.
    """

    def is_descriptive_sheet(self, text: str) -> bool:
        """Vérifie si le texte correspond à un État Descriptif ou Fiche Technique."""
        t_up = text.upper()
        keywords = [
            "ETAT DESCRIPTIF", "ÉTAT DESCRIPTIF", "FICHE DESCRIPTIVE",
            "ANNEXE E", "CARACTERISTIQUES TECHNIQUES DE L'EQUIPEMENT",
            "CARACTÉRISTIQUES TECHNIQUES DE L’ÉQUIPEMENT", "DESCRIPTIVE STATE",
            "EQUIPMENT DATA SHEET", "TECHNICAL DATA SHEET"
        ]
        has_title = any(k in t_up for k in keywords)
        # Exclure le sommaire ou la table des matières
        is_toc = "SOMMAIRE" in t_up or "TABLE OF CONTENTS" in t_up
        return has_title and not is_toc

    def extract_from_text(self, text: str, filename: str = "", page_num: int = 1) -> Dict[str, Any]:
        """Extrait l'ensemble des champs structurés d'un texte d'état descriptif."""
        data: Dict[str, Any] = {
            "is_descriptive_sheet": True,
            "filename": filename,
            "page": page_num,
            "manufacturer": None,
            "construction_year": None,
            "design_code": None,
            "manufacturing_location": None,
            "equipment_type": None,
            "designation": None,
            "fluid": None,
            "design_pressure": None,
            "test_pressure": None,
            "operating_pressure": None,
            "design_temperature": None,
            "operating_temperature": None,
            "test_temperature": None,
            "material": None,
            "thickness_mm": None,
            "corrosion_allowance_mm": None,
            "tensile_strength_mpa": None,
            "yield_strength_mpa": None,
            "allowable_stress_mpa": None,
            "quality_factor_e": None,
            "weld_efficiency_w": None,
            "y_factor": None,
            "heat_treatment": None,
            "ndt_inspection": None,
            "anomalies": []
        }

        # 1. Fabricant
        m_fab = re.search(r"(?:Nom\s*et\s*Adresse\s*du\s*Fabricant|Fabricant|Manufacturer)\s*[:\n]\s*([^\n]+(?:\n[^\n]+)?)", text, re.IGNORECASE)
        if m_fab:
            val = m_fab.group(1).strip()
            val = re.split(r"(?:Ann[ée]e|Code|Lieu|Type|Date)", val, flags=re.IGNORECASE)[0].strip()
            data["manufacturer"] = val

        # 2. Année de construction
        m_yr = re.search(r"(?:Ann[ée]e\s*de\s*Construction|Year\s*of\s*construction|Ann[ée]e\s*de\s*fabrication|Manufacturing\s*Year)\s*[:\n]\s*(\d{4})", text, re.IGNORECASE)
        if m_yr:
            data["construction_year"] = int(m_yr.group(1))

        # 3. Code de construction
        m_code = re.search(r"(?:Code\s*de\s*construction|Design\s*Code|Code\s*de\s*calcul)\s*[:\n]\s*([^\n]+)", text, re.IGNORECASE)
        if m_code:
            data["design_code"] = m_code.group(1).strip()

        # 4. Lieu de fabrication
        m_lieu = re.search(r"(?:Lieu|Location|Pays|Country|Origine)\s*[:\n]\s*([^\n]+)", text, re.IGNORECASE)
        if m_lieu:
            val = m_lieu.group(1).strip()
            val = re.split(r"(?:CARACT|Type|Nom|Ref)", val, flags=re.IGNORECASE)[0].strip()
            data["manufacturing_location"] = val

        # 5. Type & Dénomination
        m_type = re.search(r"(?:Type\s*[:\n]\s*)([^\n]+)", text, re.IGNORECASE)
        if m_type:
            data["equipment_type"] = m_type.group(1).strip()

        m_denom = re.search(r"(?:D[ée]nomination\s*de\s*l['’\s]*appareil|Designation|Item\s*Description)\s*[:\n]\s*([^\n]+)", text, re.IGNORECASE)
        if m_denom:
            data["designation"] = m_denom.group(1).strip()

        # 6. Fluide véhiculé
        m_fluid = re.search(r"(?:Fluide\s*v[ée]hicul[ée]|Fluide|Service\s*Fluid|Design\s*Fluid)\s*[:\n]\s*([^\n]+)", text, re.IGNORECASE)
        if m_fluid:
            data["fluid"] = m_fluid.group(1).strip()

        # 7. Pressions
        def parse_pressure(pattern: str, txt: str) -> Optional[Dict[str, Any]]:
            # Formule multiplicatrice ex: "1.5 × design pressure"
            m_mult = re.search(pattern + r"\s*[:\n/]?\s*(?:Test\s*Pressure\s*[:\n]?)?\s*(\d+(?:\.\d+)?)\s*(?:[x×*]|times)\s*(?:design\s*pressure|pression\s*de\s*(?:conception|calcul)|pma)", txt, re.IGNORECASE)
            if m_mult:
                mult_val = float(m_mult.group(1))
                des_p = data.get("design_pressure")
                if des_p:
                    v_bar = round(mult_val * des_p["value_bar"], 2)
                    v_orig = round(mult_val * des_p["value"], 2)
                    unit = des_p["unit"]
                    return {
                        "value": v_orig,
                        "unit": unit,
                        "value_bar": v_bar,
                        "display": f"{v_bar} bar ({v_orig} {unit}) [{mult_val} × P_des]"
                    }

            # Match formats: "P: (MPa) 9.2", "P: 9.2 MPa", "P: 92 bar", "P: (bar) 92"
            m = re.search(pattern + r"\s*[:\n]?\s*(?:\((mpa|bar|psi|kpa)\))?\s*(\d+(?:\.\d+)?)\s*(mpa|bar|psi|kpa)?", txt, re.IGNORECASE)
            if m:
                u1, num, u2 = m.group(1), m.group(2), m.group(3)
                unit = (u1 or u2 or "bar").upper()
                val = float(num)
                val_bar = val * 10.0 if unit == "MPA" else val / 14.5038 if unit == "PSI" else val / 100.0 if unit == "KPA" else val
                return {
                    "value": val,
                    "unit": unit,
                    "value_bar": round(val_bar, 2),
                    "display": f"{round(val_bar, 2)} bar ({val} {unit})"
                }
            return None

        data["design_pressure"] = parse_pressure(r"(?:Pression\s*de\s*calcul|Design\s*pressure|PMA|P_des)", text)
        data["test_pressure"] = parse_pressure(r"(?:Pression\s*d['’\s]*[ée]ssai|Pression\s*d['’\s]*[ée]preuve|Test\s*pressure|Hydrostatic\s*pressure|P_test)", text)
        data["operating_pressure"] = parse_pressure(r"(?:Pression\s*maximale\s*de\s*service|Operating\s*pressure|Pression\s*de\s*service)", text)

        # 8. Températures
        def parse_temp(pattern: str, txt: str) -> Optional[str]:
            m = re.search(pattern + r"\s*[:\n/]?\s*(?:Design\s*temperature)?\s*[:\n]?\s*(?:\((?:°C|C|deg\s*c)\))?\s*([+-]?\d+(?:\.\d+)?(?:\s*/\s*[+-]?\d+(?:\.\d+)?)?)\s*(?:°C|C|DEG\s*C|℃)?", txt, re.IGNORECASE)
            if m:
                return m.group(1).strip() + " °C"
            return None

        data["design_temperature"] = parse_temp(r"(?:Temp[ée]rature\s*de\s*(?:calcul|conception)|Design\s*temp(?:erature)?|TMA|T_des)", text)
        data["operating_temperature"] = parse_temp(r"(?:Temp[ée]rature\s*de\s*service|Operating\s*temp)", text)
        data["test_temperature"] = parse_temp(r"(?:Temp[ée]rature\s*d['’\s]*[ée]ssai|Temp[ée]rature\s*d['’\s]*[ée]preuve|Test\s*temp)", text)

        # 9. Matériaux Utilisés
        m_mat = re.search(r"(?:Mat[ée]riaux\s*Utilis[ée]s|Mat[ée]riau|Material\s*grade|Materials\s*Used|Material)\s*[:\n]\s*([^\n]+)", text, re.IGNORECASE)
        if m_mat:
            raw_mat = m_mat.group(1).strip()
            # Rejeter le texte procédural non métallurgique
            is_garbage = any(b in raw_mat.lower() for b in ["brand", "standard:", "shall be", "section should", "location and", "table", "process number", "placed neatly", "furnace"])
            if not is_garbage and len(raw_mat) <= 60:
                data["material"] = raw_mat

        # 10. Épaisseur
        m_thk = re.search(r"(?<!Specimen\s)(?<!Specimen\s\s)(?:Epaisseur(?:\(s\))?|Thickness|Wall\s*thickness)\s*[:\n]?\s*(?:\(mm\))?\s*(\d+(?:\.\d+)?)\s*(?:mm)?", text, re.IGNORECASE)
        if m_thk:
            val_thk = float(m_thk.group(1))
            if 0.5 <= val_thk <= 150.0:
                data["thickness_mm"] = val_thk

        # 11. Surépaisseur de corrosion
        m_ca = re.search(r"(?:Sur[ée]paisseur\s*de\s*corrosion|Corrosion\s*allowance|CA)\s*[:\n]?\s*(?:\(mm\))?\s*(\d+(?:\.\d+)?)\s*(?:mm)?", text, re.IGNORECASE)
        if m_ca:
            data["corrosion_allowance_mm"] = float(m_ca.group(1))

        # 12. Propriétés Mécaniques
        m_rm = re.search(r"(?:Charge\s*limite\s*de\s*rupture\s*min|Tensile\s*strength|Rm)\s*[:\n]?\s*(?:\(mpa\))?\s*(\d+(?:\.\d+)?)\s*(?:mpa|bar)?", text, re.IGNORECASE)
        if m_rm:
            data["tensile_strength_mpa"] = float(m_rm.group(1))

        m_reh = re.search(r"(?:Limite\s*minimale\s*d['’\s`]*[ée]lasticit[ée]|Yield\s*strength|Reh)\s*[:\n]?\s*(?:\(mpa\))?\s*(\d+(?:\.\d+)?)\s*(?:mpa|bar)?", text, re.IGNORECASE)
        if m_reh:
            data["yield_strength_mpa"] = float(m_reh.group(1))

        m_adm = re.search(r"(?:Contrainte\s*admissible|Allowable\s*stress)\s*[:\n]?\s*(?:\(mpa\))?\s*(\d+(?:\.\d+)?)\s*(?:mpa|bar)?", text, re.IGNORECASE)
        if m_adm:
            data["allowable_stress_mpa"] = float(m_adm.group(1))

        # 13. Facteurs & Coefficients
        m_e = re.search(r"(?:Quality\s*Factor\s*E|Facteur\s*E)\s*[:\n]\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if m_e: data["quality_factor_e"] = float(m_e.group(1))

        m_w = re.search(r"(?:Coef+icient\s*de\s*soudure\s*W|Joint\s*efficiency\s*W)\s*[:\n]\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if m_w: data["weld_efficiency_w"] = float(m_w.group(1))

        m_y = re.search(r"(?:Coefficient\s*Y|Factor\s*Y)\s*[:\n]\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if m_y: data["y_factor"] = float(m_y.group(1))

        # 14. Traitement thermique & CND
        m_tt = re.search(r"(?:Traitement\s*thermique|Heat\s*treatment|PWHT)\s*[:\n]\s*([^\n]+)", text, re.IGNORECASE)
        if m_tt: data["heat_treatment"] = m_tt.group(1).strip()

        m_cnd = re.search(r"(?:Essais\s*non\s*destructifs|Contr[ôo]les\s*non\s*destructifs|NDT)\s*[:\n]\s*([^\n]+)", text, re.IGNORECASE)
        if m_cnd: data["ndt_inspection"] = m_cnd.group(1).strip()

        # Contrôles de conformité Annexe E
        if not data["design_pressure"]:
            data["anomalies"].append({
                "title": "Pression de calcul non renseignée",
                "priority": "CRITICAL",
                "article": "Annexe E - Décret 21-261",
                "action": "Indiquer la pression de calcul en bar ou MPa."
            })
        if not data["test_pressure"]:
            data["anomalies"].append({
                "title": "Pression d'essai hydrostatique non renseignée",
                "priority": "CRITICAL",
                "article": "Annexe E - Décret 21-261",
                "action": "Indiquer la pression d'épreuve hydrostatique (1.5 x PMA)."
            })
        if not data["operating_temperature"] or "spécification" in (data["operating_temperature"] or "").lower():
            data["anomalies"].append({
                "title": "Température de service non chiffrée sur la fiche",
                "priority": "CRITICAL",
                "article": "Annexe E - Décret 21-261",
                "action": "Remplacer la mention générique par la valeur chiffrée exacte (ex: +65°C)."
            })

        return data
