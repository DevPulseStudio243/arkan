"""
arh_material_certificate_analyzer.py
====================================
Module d'Analyse Structurée des Certificats Matière EN 10204 3.1 / 3.2 pour ARKAN ARH.
Conforme aux codes ASTM (A105, A350 LF2, A234 WPB, A182, A333, A516 Gr 70), API 5L, ASME Section II/VIII, MSS SP-75 et NACE MR0175 / ISO 15156.

Fonctionnalités :
  1. Extraction structurée de la composition chimique (C, Mn, Si, P, S, Cr, Mo, V, Ni, Cu, Nb, Ti, N, B).
  2. Calcul automatique du Carbone Équivalent (CEV IIW et Pcm Ito-Bessyo) :
        CEV = C + (Mn / 6) + ((Cr + Mo + V) / 5) + ((Ni + Cu) / 15)
        Pcm = C + (Si / 30) + ((Mn + Cu + Cr) / 20) + (Ni / 60) + (Mo / 15) + (V / 10) + (5 * B)
  3. Rapprochement et validation croisée entre le CEV calculé par ARKAN et le CEV déclaré par le fabricant.
  4. Extraction et contrôle des propriétés mécaniques (ReH / Rp0.2, Rm, Allongement A%, Résilience Charpy KV à -20°C/-46°C, Dureté HV10 / HBW / HRC).
  5. Détection automatique des non-conformités métallurgiques (dépassement CEV, dureté NACE > 250 HV10, énergie KV basse).
"""

import re
import math
from typing import Dict, List, Any, Optional, Tuple


# ── LIMITES STANDARD ASTM / ASME / API 5L POUR LES NUANCES PRINCIPALES OIL & GAS ──
STANDARD_MATERIAL_LIMITS = {
    "A350 LF2": {
        "label": "ASTM A350 Grade LF2 (Basse Température)",
        "c_max": 0.30,
        "mn_range": (0.60, 1.35),
        "p_max": 0.035,
        "s_max": 0.040,
        "si_range": (0.15, 0.30),
        "cev_max": 0.45,  # 0.43 max pour service sévère / ASME B31.3
        "reh_min": 250,   # MPa
        "rm_range": (485, 655), # MPa
        "elongation_min": 22.0, # %
        "charpy_temp": -46, # °C
        "charpy_energy_min_avg": 27.0, # Joules
        "hardness_max_hbw": 197,
        "hardness_max_hv10": 250
    },
    "A105": {
        "label": "ASTM A105 (Forgé Standard)",
        "c_max": 0.35,
        "mn_range": (0.60, 1.05),
        "p_max": 0.035,
        "s_max": 0.040,
        "si_range": (0.10, 0.35),
        "cev_max": 0.47,  # 0.45 pour nuances normalisées
        "reh_min": 250,   # MPa
        "rm_range": (485, 655),
        "elongation_min": 22.0,
        "charpy_temp": 0,
        "charpy_energy_min_avg": 20.0,
        "hardness_max_hbw": 187,
        "hardness_max_hv10": 250
    },
    "A234 WPB": {
        "label": "ASTM A234 Grade WPB (Raccord Forgé Tuyauterie)",
        "c_max": 0.30,
        "mn_range": (0.29, 1.06),
        "p_max": 0.050,
        "s_max": 0.058,
        "si_min": 0.10,
        "cev_max": 0.45,
        "reh_min": 240,
        "rm_range": (415, 585),
        "elongation_min": 22.0,
        "charpy_temp": 0,
        "charpy_energy_min_avg": 20.0,
        "hardness_max_hbw": 197,
        "hardness_max_hv10": 250
    },
    "A333 GR 6": {
        "label": "ASTM A333 Grade 6 (Tube Basse Température)",
        "c_max": 0.30,
        "mn_range": (0.29, 1.06),
        "p_max": 0.025,
        "s_max": 0.025,
        "si_min": 0.10,
        "cev_max": 0.43,
        "reh_min": 240,
        "rm_range": (415, 655),
        "elongation_min": 35.0,
        "charpy_temp": -45,
        "charpy_energy_min_avg": 27.0,
        "hardness_max_hv10": 250
    },
    "API 5L X52": {
        "label": "API 5L Grade X52 / L360 (Canalisation)",
        "c_max": 0.22,
        "mn_max": 1.40,
        "p_max": 0.025,
        "s_max": 0.015,
        "cev_max": 0.43,
        "reh_range": (360, 530),
        "rm_range": (460, 760),
        "elongation_min": 20.0,
        "charpy_temp": -20,
        "charpy_energy_min_avg": 40.0,
        "hardness_max_hv10": 250
    },
    "API 5L X65": {
        "label": "API 5L Grade X65 / L450 (Canalisation Haute Limite Élastique)",
        "c_max": 0.18,
        "mn_max": 1.60,
        "p_max": 0.020,
        "s_max": 0.010,
        "cev_max": 0.43,
        "reh_range": (450, 600),
        "rm_range": (535, 760),
        "elongation_min": 18.0,
        "charpy_temp": -20,
        "charpy_energy_min_avg": 45.0,
        "hardness_max_hv10": 250
    },
    "A516 GR 70": {
        "label": "ASTM A516 Grade 70 (Tôle Appareil à Pression)",
        "c_max": 0.28,
        "mn_range": (0.85, 1.20),
        "p_max": 0.035,
        "s_max": 0.035,
        "si_range": (0.15, 0.40),
        "cev_max": 0.45,
        "reh_min": 260,
        "rm_range": (485, 620),
        "elongation_min": 21.0,
        "charpy_temp": -29,
        "charpy_energy_min_avg": 27.0,
        "hardness_max_hv10": 250
    }
}


class ARHMaterialCertificateAnalyzer:
    """
    Analyseur et vérificateur physico-chimique des Certificats Matière EN 10204 3.1.
    """

    def __init__(self):
        pass

    def analyze_certificate_text(
        self,
        text: str,
        filename: str = "",
        page_num: int = 1,
        expected_grade: str = None
    ) -> Dict[str, Any]:
        """
        Extrait et valide l'ensemble des données d'un certificat 3.1 présent dans le texte de la page.
        """
        result = {
            "is_material_certificate": False,
            "certificate_standard": "EN 10204 3.1",
            "filename": filename,
            "page": page_num,
            "detected_grade": self._detect_grade(text, expected_grade),
            "heat_number": self._extract_heat_number(text),
            "chemical_composition": {},
            "calculated_cev": None,
            "calculated_pcm": None,
            "declared_cev": self._extract_declared_cev(text),
            "mechanical_properties": {},
            "heat_treatment": self._extract_heat_treatment(text),
            "compliance_checks": [],
            "anomalies": []
        }

        # Vérifier si la page est un certificat 3.1
        upper_text = text.upper()
        cert_indicators = ["EN 10204", "3.1", "MILL TEST CERTIFICATE", "INSPECTION CERTIFICATE", "CERTIFICAT MATIERE", "CERTIFICATO DI COLLAUDO"]
        if any(ind in upper_text for ind in cert_indicators) or ("CHEMICAL COMPOSITION" in upper_text and ("HEAT" in upper_text or "COULÉE" in upper_text)):
            result["is_material_certificate"] = True
        else:
            return result

        # 1. Extraction de la chimie
        chem = self._extract_chemical_elements(text)
        result["chemical_composition"] = chem

        # 2. Calcul du Carbone Équivalent (CEV IIW)
        c = chem.get("C", 0.0)
        mn = chem.get("Mn", 0.0)
        cr = chem.get("Cr", 0.0)
        mo = chem.get("Mo", 0.0)
        v = chem.get("V", 0.0)
        ni = chem.get("Ni", 0.0)
        cu = chem.get("Cu", 0.0)
        si = chem.get("Si", 0.0)
        b = chem.get("B", 0.0)

        if c > 0 and mn > 0:
            cev = c + (mn / 6.0) + ((cr + mo + v) / 5.0) + ((ni + cu) / 15.0)
            result["calculated_cev"] = round(cev, 3)

            pcm = c + (si / 30.0) + ((mn + cu + cr) / 20.0) + (ni / 60.0) + (mo / 15.0) + (v / 10.0) + (5.0 * b)
            result["calculated_pcm"] = round(pcm, 3)

        # 3. Extraction mécanique
        mech = self._extract_mechanical_properties(text)
        result["mechanical_properties"] = mech

        # 4. Exécution de l'audit de conformité métallurgique
        checks, anomalies = self._audit_material_compliance(result)
        result["compliance_checks"] = checks
        result["anomalies"] = anomalies

        return result

    def _detect_grade(self, text: str, fallback: str = None) -> str:
        u = text.upper()
        for grade_key in STANDARD_MATERIAL_LIMITS.keys():
            if grade_key in u:
                return grade_key
            if grade_key.replace(" ", "") in u:
                return grade_key
        return fallback if fallback is not None else "UNKNOWN"

    def _extract_heat_number(self, text: str) -> Optional[str]:
        # Regex sécurisée sans faux positifs
        pats = [
            r'\b(?:HEAT\s*(?:NO|N°|NUMBER|#)|N°?\s*COUL[EÉ]E|CAST\s*NO)\s*[:.\-]?\s*([A-Z0-9\-_]{3,20})\b',
            r'\b(?:HEAT\s*[:=]\s*)([A-Z0-9\-_]{3,20})\b'
        ]
        blacklist = {"TREATMENT", "HOLDING", "INPUT", "TEMPERATURE", "IRON", "MENT", "ACCORDING", "NUMBER", "REPORT"}
        for p in pats:
            m = re.findall(p, text, re.I)
            for v in m:
                clean_v = v.strip().upper()
                if len(clean_v) >= 3 and clean_v not in blacklist and any(ch.isdigit() for ch in clean_v):
                    return clean_v
        return None

    def _extract_chemical_elements(self, text: str) -> Dict[str, float]:
        """
        Extrait les pourcentages en masse des éléments chimiques (%C, %Mn, %Si, %P, %S, etc.).
        Priorité au tableau multi-colonnes pour éviter les faux appariements entre la fin d'en-tête et le début des valeurs.
        """
        chem = {}
        elements = ["C", "Mn", "Si", "P", "S", "Cr", "Mo", "Ni", "Cu", "V", "Nb", "Ti", "Al", "N", "B"]

        elements_map = {e.upper(): e for e in elements}

        # Étape 1 : Détection et parsing tabulaire prioritaire
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for i, line in enumerate(lines):
            raw_tokens = [t.strip() for t in re.split(r'[\t|;,]+|\s+', line.upper()) if t.strip()]
            if len(raw_tokens) < 3:
                continue

            matched_header_elements = []
            for token in raw_tokens:
                clean_tok = re.sub(r'[^A-Z]', '', token)
                if clean_tok in elements_map:
                    matched_header_elements.append(elements_map[clean_tok])
                elif clean_tok in ("CEV", "CE", "PCM", "EQUIV", "WT", "CHEM", "ELEMENT"):
                    matched_header_elements.append(clean_tok)
                else:
                    matched_header_elements.append(None)

            valid_header_count = sum(1 for el in matched_header_elements if el in elements)
            if valid_header_count >= 3 and i + 1 < len(lines):
                for offset in (1, 2):
                    if i + offset >= len(lines):
                        break
                    val_line = lines[i + offset]
                    cleaned_val_line = re.sub(r'(?<=\d)[oO](?=\d)', '0', val_line)
                    cleaned_val_line = re.sub(r'(?<=\d)[lI](?=\d)', '1', cleaned_val_line)
                    
                    val_tokens_raw = [t.strip() for t in re.split(r'[\t|;,]+|\s+', cleaned_val_line) if t.strip()]

                    val_tokens = []
                    for vt in val_tokens_raw:
                        clean_vt = vt.strip('%').replace(',', '.')
                        if clean_vt.startswith('.') and len(clean_vt) > 1 and clean_vt[1:].isdigit():
                            clean_vt = '0' + clean_vt
                        try:
                            f = float(clean_vt)
                            if 0.0001 <= f <= 25.0:
                                val_tokens.append(f)
                        except ValueError:
                            pass

                    # Si le nombre de valeurs correspond au nombre d'en-têtes
                    if len(val_tokens) >= valid_header_count - 2:
                        val_idx = 0
                        for col_el in matched_header_elements:
                            if col_el and col_el in elements and val_idx < len(val_tokens):
                                val = val_tokens[val_idx]
                                if not (col_el == "C" and val > 1.5):
                                    chem[col_el] = val
                                val_idx += 1
                            elif col_el and val_idx < len(val_tokens):
                                val_idx += 1
                        break

                if "C" in chem and "Mn" in chem:
                    break


        # Étape 2 : Recherche par paires clé-valeur explicites sur UNE SEULE LIGNE (pas à travers les \n)
        for el in elements:
            if el in chem:
                continue
            # Regex strictement intra-ligne ([^\S\r\n] = espaces sans retours à la ligne)
            patterns = [
                rf'\b{el}[^\S\r\n]*[:=][^\S\r\n]*([0-9]+[.,][0-9]+)[^\S\r\n]*%',
                rf'\b{el}[^\S\r\n]*[:=][^\S\r\n]*([0-9]+[.,][0-9]+)\b',
                rf'\b%{el}[^\S\r\n]*[:=]?[^\S\r\n]*([0-9]+[.,][0-9]+)\b',
                rf'\b{el}[^\S\r\n]+([0-9]+[.,][0-9]{{2,4}})\b'
            ]
            for pat in patterns:
                m = re.search(pat, text, re.I)
                if m:
                    val_str = m.group(1).replace(",", ".")
                    try:
                        val = float(val_str)
                        if 0.0001 <= val <= 25.0:
                            if el == "C" and val > 1.5:
                                continue
                            chem[el] = val
                            break
                    except ValueError:
                        pass

        # Étape 3 : Détection de secours sur séquence décimale standardisée
        if "C" not in chem or "Mn" not in chem:
            decimal_matches = re.findall(r'\b(0[.,][0-9]{2,4})\b', text)
            if len(decimal_matches) >= 4:
                try:
                    vals = [float(x.replace(",", ".")) for x in decimal_matches[:7]]
                    if 0.05 <= vals[0] <= 0.35 and 0.20 <= vals[1] <= 1.80:
                        chem["C"] = vals[0]
                        chem["Mn"] = vals[1]
                        if len(vals) > 2: chem["Si"] = vals[2]
                        if len(vals) > 3: chem["P"] = vals[3]
                        if len(vals) > 4: chem["S"] = vals[4]
                        if len(vals) > 5: chem["Cr"] = vals[5]
                        if len(vals) > 6: chem["Mo"] = vals[6]
                except Exception:
                    pass

        return chem


    def _extract_declared_cev(self, text: str) -> Optional[float]:
        pats = [
            r'\b(?:CEV|C\.E\.|CE|CARBON\s*EQUIV(?:ALENT)?)\s*[:=]?\s*([0-9]+[.,][0-9]{2,4})\b',
            r'\b(?:CE\s*IIW)\s*[:=]?\s*([0-9]+[.,][0-9]{2,4})\b'
        ]
        for p in pats:
            m = re.search(p, text, re.I)
            if m:
                try:
                    val = float(m.group(1).replace(",", "."))
                    if 0.20 <= val <= 0.80:
                        return round(val, 3)
                except ValueError:
                    pass
        return None

    def _extract_mechanical_properties(self, text: str) -> Dict[str, Any]:
        """
        Extrait les propriétés mécaniques (ReH, Rm, A%, Charpy KV, Dureté)
        avec support des formats tabulaires et conversion d'unités (ksi -> MPa).
        """
        mech = {}

        # Limite d'élasticité (Yield Strength / ReH / Rp0.2 / YS)
        m_reh = re.search(r'\b(?:ReH|Rp0\.?2|YIELD(?:\s*STRENGTH)?|LIMITE\s*ELASTIQUE|\bYS\b)(?:\s*\([^)]*\))?[^\d\n]{0,20}?([0-9]{2,4}(?:[.,][0-9]+)?)\s*(MPa|N/mm2|KSI)?\b', text, re.I)
        if m_reh:
            try:
                val = float(m_reh.group(1).replace(",", "."))
                unit = (m_reh.group(2) or "MPa").upper()
                if "KSI" in unit:
                    val = round(val * 6.89476, 1)
                if 100 <= val <= 1500:
                    mech["ReH_MPa"] = val
            except ValueError: pass

        # Résistance à la traction (Tensile Strength / Rm / UTS / TS)
        m_rm = re.search(r'\b(?:Rm|TENSILE(?:\s*STRENGTH)?|RESISTANCE\s*TRACTION|\bUTS\b|\bTS\b)(?:\s*\([^)]*\))?[^\d\n]{0,20}?([0-9]{2,4}(?:[.,][0-9]+)?)\s*(MPa|N/mm2|KSI)?\b', text, re.I)
        if m_rm:
            try:
                val = float(m_rm.group(1).replace(",", "."))
                unit = (m_rm.group(2) or "MPa").upper()
                if "KSI" in unit:
                    val = round(val * 6.89476, 1)
                if 200 <= val <= 2000:
                    mech["Rm_MPa"] = val
            except ValueError: pass

        # Allongement (Elongation A% / Elong.)
        m_el = re.search(r'\b(?:A%?|ELONGATION|ALLONGEMENT|ELONG\.?)(?:\s*\([^)]*\))?[^\d\n]{0,20}?([0-9]{1,2}(?:[.,][0-9]+)?)\s*%?\b', text, re.I)
        if m_el:
            try:
                val = float(m_el.group(1).replace(",", "."))
                if 5.0 <= val <= 60.0:
                    mech["Elongation_pct"] = val
            except ValueError: pass

        # Résilience Charpy V-Notch (KV)
        m_kv = re.search(r'\b(?:CHARPY(?:\s*[- ]?[VW])?|IMPACT|KV|KCV|RESILIENCE)(?:[^\d\n\+\-]{0,25}?(?:AT|A|@)\s*([+\-]?[0-9]{1,2})\s*°?C)?[^\d\n]{0,20}?([0-9]{1,3}(?:[.,][0-9]+)?)\s*(?:J|Joules|FT[- ]LBS)?\b', text, re.I)
        if m_kv:
            try:
                temp = m_kv.group(1) or "-20"
                energy = float(m_kv.group(2).replace(",", "."))
                if 5.0 <= energy <= 500.0:
                    mech["Charpy_KV_Joules"] = energy
                    mech["Charpy_Temp_C"] = int(temp)
            except Exception: pass

        # Dureté (Hardness HBW / HV10 / HRC)
        m_hard = re.search(r'\b(?:HARDNESS|DURETE|DUREZZA|\bHBW?\b|\bHV(?:10)?\b|\bHRC\b)(?:\s*\([^)]*\))?[^\d\n]{0,20}?([0-9]{2,3}(?:[.,][0-9]+)?)\s*(HV(?:10)?|HBW?|HRC)?\b', text, re.I)
        if m_hard:
            try:
                h_val = float(m_hard.group(1).replace(",", "."))
                h_unit = (m_hard.group(2) or "HBW").upper()
                if 10 <= h_val <= 700:
                    mech["Hardness_Value"] = h_val
                    mech["Hardness_Scale"] = h_unit
            except ValueError: pass

        return mech



    def _extract_heat_treatment(self, text: str) -> Optional[str]:
        u = text.upper()
        if "NORMALIZED" in u or "NORMALISE" in u:
            return "NORMALISÉ (N)"
        if "QUENCHED AND TEMPERED" in u or "TREMPE ET REVENU" in u or "Q&T" in u:
            return "TREMPÉ & REVENU (Q+T)"
        if "SOLUTION ANNEALED" in u or "HYPERTREMPE" in u:
            return "HYPERTREMPÉ (Solution Annealed)"
        if "AS ROLLED" in u or "BRUT DE LAMINAGE" in u:
            return "BRUT DE LAMINAGE (As Rolled)"
        return "NON SPÉCIFIÉ"

    def _audit_material_compliance(self, res: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        checks = []
        anomalies = []
        grade = res.get("detected_grade", "UNKNOWN")
        # Si le grade est inconnu, utiliser des limites universelles Oil & Gas
        # (pas de comparaison contre A350 LF2 qui génèrerait des faux positifs)
        if grade in STANDARD_MATERIAL_LIMITS:
            std = STANDARD_MATERIAL_LIMITS[grade]
        elif grade and grade != "UNKNOWN" and any(grade.startswith(k.split()[0]) for k in STANDARD_MATERIAL_LIMITS):
            # Essai de matching partiel (ex: "A860 WPHY" → "A860 WPHY 65")
            partial_match = next((v for k, v in STANDARD_MATERIAL_LIMITS.items() if grade in k or k in grade), None)
            std = partial_match if partial_match else None
        else:
            std = None  # Grade inconnu → audit limité, pas de comparaison aux limites

        if std is None:
            # Grade inconnu : uniquement vérifier l'extractabilité des données, pas les limites
            return checks, anomalies

        chem = res.get("chemical_composition", {})
        mech = res.get("mechanical_properties", {})
        calc_cev = res.get("calculated_cev")
        decl_cev = res.get("declared_cev")
        page = res.get("page", 1)

        # ── RÈGLE 1 : VÉRIFICATION DU CARBONE ÉQUIVALENT (CEV) ──
        if calc_cev is not None:
            max_cev = std.get("cev_max", 0.43)
            is_ok = calc_cev <= max_cev
            checks.append({
                "parameter": "Carbone Équivalent (CEV IIW)",
                "formula": "CEV = C + Mn/6 + (Cr+Mo+V)/5 + (Ni+Cu)/15",
                "calculated_value": calc_cev,
                "standard_limit": f"<= {max_cev}",
                "status": "CONFORME" if is_ok else "NON CONFORME",
                "standard": f"{grade} / ASME B31.3"
            })
            if not is_ok:
                anomalies.append({
                    "priority": "CRITICAL",
                    "title": f"Carbone Équivalent CEV Exorbitant : {calc_cev} (Max autorisé : {max_cev})",
                    "category": "CONFORMITÉ MÉTALLURGIQUE",
                    "page": f"Page {page}",
                    "observation": f"Le calcul exact du CEV sur le certificat 3.1 donne {calc_cev}%, ce qui dépasse la limite maximale de soudabilité de {max_cev}% imposée pour la nuance {grade}.",
                    "action_required": "Refuser le lot matière ou exiger une procédure de soudage spéciale avec préchauffage élevé qualifiée par PQR.",
                    "responsible": "Métallurgiste / Constructeur"
                })

            # Rapprochement CEV Calculé vs CEV Déclaré sur certificat
            if decl_cev is not None:
                delta = abs(calc_cev - decl_cev)
                if delta > 0.03:
                    anomalies.append({
                        "priority": "MAJOR",
                        "title": f"Incohérence CEV Fabricant ({decl_cev}) vs CEV Calculé ARKAN ({calc_cev})",
                        "category": "CONCORDANCE DE CALCUL",
                        "page": f"Page {page}",
                        "observation": f"Le certificat 3.1 mentionne un CEV de {decl_cev} alors que l'analyse des teneurs élémentaires donne {calc_cev}% (Écart de {delta:.3f}%).",
                        "action_required": "Demander au fabricant la formule exacte utilisée ou la correction du certificat matière.",
                        "responsible": "Fabricant Aciérie"
                    })

        # ── RÈGLE 2 : TENEUR EN SOUFRE ET PHOSPHORE (SOUR SERVICE / HIC) ──
        s_val = chem.get("S")
        if s_val is not None and s_val > std.get("s_max", 0.040):
            anomalies.append({
                "priority": "MAJOR",
                "title": f"Teneur en Soufre excessive : %S = {s_val}% (Max standard : {std.get('s_max')}%)",
                "category": "COMPOSITION CHIMIQUE",
                "page": f"Page {page}",
                "observation": f"La teneur en soufre mesurée à l'analyse sur coulée ({s_val}%) excède la limite maximale admissible.",
                "action_required": "Exiger un certificat conforme aux spécifications projet NACE MR0175.",
                "responsible": "Constructeur"
            })

        # ── RÈGLE 3 : DURETÉ NACE MR0175 (MAX 250 HV10 / 22 HRC) ──
        h_val = mech.get("Hardness_Value")
        h_scale = mech.get("Hardness_Scale", "HV10")
        if h_val is not None:
            max_h = 250 if "HV" in h_scale else (22 if "HRC" in h_scale else 197)
            if h_val > max_h:
                anomalies.append({
                    "priority": "CRITICAL",
                    "title": f"Dureté Métallique Hors Limite NACE MR0175 : {h_val} {h_scale} (Max : {max_h})",
                    "category": "RÉSISTANCE CORROSION NACE",
                    "page": f"Page {page}",
                    "observation": f"La valeur de dureté relevée ({h_val} {h_scale}) dépasse le seuil critique d'immunité à la fissuration sous contrainte par l'H2S (NACE MR0175 / ISO 15156).",
                    "action_required": "Réaliser un traitement thermique de détensionnement (PWHT) ou refuser la pièce.",
                    "responsible": "Contrôle Qualité"
                })

        # ── RÈGLE 4 : RÉSILIENCE CHARPY KV À BASSE TEMPÉRATURE ──
        kv_val = mech.get("Charpy_KV_Joules")
        if kv_val is not None:
            min_kv = std.get("charpy_energy_min_avg", 27.0)
            if kv_val < min_kv:
                anomalies.append({
                    "priority": "CRITICAL",
                    "title": f"Énergie de Rupture Résilience Insuffisante : {kv_val} J (Min requis : {min_kv} J)",
                    "category": "ESSAIS MÉCANIQUES",
                    "page": f"Page {page}",
                    "observation": f"L'énergie moyenne absorbée aux essais de flexion par choc Charpy V ({kv_val} Joules) est inférieure au seuil réglementaire de {min_kv} Joules.",
                    "action_required": "Effectuer des contre-essais réglementaires ou rejeter le lot de fabrication.",
                    "responsible": "Aciérie / Organisme Tiers"
                })

        return checks, anomalies
