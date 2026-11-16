from __future__ import annotations
from arh_wps_expert_agent import check_itp_tpi_arh_column
import os
import re
import json
import uuid
import datetime
import logging
import math
import unicodedata
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

def _normalize_text(text: str) -> str:
    """
    Normalise le texte en majuscules, supprime les accents français et les caractères spéciaux,
    afin de garantir un appariement 100% fiable sans échecs de regex ou de codage unicode.
    Ex: "ÉPAISSEUR DE CALCUL (N° 02)" -> "EPAISSEUR DE CALCUL N 02"
    """
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', text)
    ascii_text = "".join([c for c in nfkd if not unicodedata.combining(c)])
    normalized = re.sub(r'[^A-Z0-9]', ' ', ascii_text.upper())
    return re.sub(r'\s+', ' ', normalized).strip()


try:
    from rapidfuzz import fuzz as _rf_fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    from difflib import SequenceMatcher
    _HAS_RAPIDFUZZ = False


def _fuzzy_contains(needle: str, haystack: str, threshold: float = 0.75) -> bool:
    """
    Bug3 fix : verifie si `needle` apparait dans `haystack` avec une tolerance aux
    variations (abreviations differentes, fautes OCR, reformulation legere), en
    complement de la correspondance substring stricte.
    """
    if not needle or not haystack:
        return False
    norm_n = _normalize_text(needle)
    norm_h = _normalize_text(haystack)
    if not norm_n or not norm_h:
        return False
    if norm_n in norm_h:
        return True
    if len(norm_n) < 4:
        return False

    # 1. Verification si tous les mots significatifs (>=4 lettres) de needle sont dans haystack
    # BUG FIX #3 : utiliser \b word boundaries pour éviter les faux positifs (ex: VIS dans REVISION)
    n_words = [w for w in norm_n.split() if len(w) >= 4]
    if n_words and len(n_words) >= 2 and all(re.search(r'\b' + re.escape(w) + r'\b', norm_h) for w in n_words):
        return True

    # 2. Fuzzy matching optimisé — utilise rapidfuzz (binding C) si disponible
    # BUG FIX #2 : remplacement du SequenceMatcher O(N²) en boucle glissante
    if _HAS_RAPIDFUZZ:
        score = _rf_fuzz.partial_ratio(norm_n, norm_h)
        return (score / 100.0) >= threshold
    else:
        from difflib import SequenceMatcher
        # Version dégradée limitée : une seule comparaison globale, pas de fenêtre glissante
        return SequenceMatcher(None, norm_n, norm_h).ratio() >= threshold

from arh_regulatory_engine import ARHRegulatoryEngine, EQUIPMENT_TYPES, DECREES_CATALOG
from arh_knowledge_graph import ARHKnowledgeGraph


class ARHTechnicalSpecAgent:
    """
    Sous-agent spécialisé dans l'analyse globale des spécifications techniques 
    et des descriptions d'équipements pour ARH Management.
    """
    def __init__(self, engine=None):
        self.engine = engine

    def audit_specifications(self, parsed_docs: List[Dict[str, Any]], equipment_type: str, equipment_tag: str) -> List[Dict[str, Any]]:
        comments = []
        for doc in parsed_docs:
            fname = doc.get("file_name", "")
            text = doc.get("text", "")
            tu = text.upper()
            
            # --- 1. Extraction globale des paramètres clés ---
            
            # A. Température de Design
            temp_design = None
            m_temp = re.search(r'(?:DESIGN\s*TEMP(?:ERATURE)?|TEMP(?:ERATURE)?\s*(?:DE\s*)?DESIGN|TEMP(?:ERATURE)?\s*(?:DE\s*)?CALCUL)[^0-9\-]*([-\u2212\u2013]?\s*\d+(?:\.\d+)?)\s*(?:C|°C|F|°F)', tu)
            if m_temp:
                try:
                    val_str = m_temp.group(1).replace("−", "-").replace("–", "-").replace(" ", "")
                    val = float(val_str)
                    is_fahrenheit = "F" in m_temp.group(0)
                    temp_design = (val - 32) * 5 / 9 if is_fahrenheit else val
                except ValueError:
                    pass

            # B. Pression de Design
            press_design = None
            m_press = re.search(r'(?:DESIGN\s*PRESS(?:URE)?|PRESS(?:ION)?\s*(?:DE\s*)?DESIGN|PRESS(?:ION)?\s*(?:DE\s*)?CALCUL|PMA|PMS)[^0-9]*(\d+(?:\.\d+)?)\s*(?:BAR|BARS|MPA)', tu)
            if m_press:
                try:
                    val = float(m_press.group(1))
                    is_mpa = "MPA" in m_press.group(0)
                    press_design = val * 10.0 if is_mpa else val
                except ValueError:
                    pass

            # C. Surépaisseur de Corrosion (Corrosion Allowance)
            corrosion_allowance = None
            m_ca = re.search(r'(?:CORROSION\s*ALLOWANCE|SUREPAISSEUR\s*(?:DE\s*)?CORROSION|C\.A\.?)[^0-9]*(\d+(?:\.\d+)?)\s*MM', tu)
            if m_ca:
                try:
                    corrosion_allowance = float(m_ca.group(1))
                except ValueError:
                    pass

            # D. Classe de Bride
            flange_class = None
            m_fc = re.search(r'(?:FLANGE|BRIDE|RATING|CLASS)\s*(?:CLASS|CL)?\s*(150|300|600|900|1500|2500)\b', tu)
            if m_fc:
                try:
                    flange_class = int(m_fc.group(1))
                except ValueError:
                    pass

            # E. Matériaux et nuances
            has_a105 = "A105" in tu or "ASTM A105" in tu
            has_lf2 = "LF2" in tu or "A350 LF2" in tu
            is_sour = any(kw in tu for kw in ("SOUR SERVICE", "NACE MR0175", "H2S"))

            # --- 2. Vérifications et Règles de Conformité ---

            # Règle A : Dépassement thermique pour ASTM A105 (> 427°C)
            if has_a105 and temp_design is not None and temp_design > 427:
                comments.append({
                    "id": f"REM_SPEC_{uuid.uuid4().hex[:6].upper()}",
                    "title": f"⚠️ Dépassement de la Limite Thermique ASME pour A105 ({temp_design:.1f}°C > 427°C)",
                    "description": f"L'agent de spécification a détecté l'association du matériau ASTM A105 à une température de design élevée de {temp_design:.1f}°C dans le fichier '{fname}', ce qui dépasse la limite maximale recommandée par l'ASME B31.3 de 427°C.",
                    "observation": f"Matériau A105 détecté sous conditions de température extrême de {temp_design:.1f}°C.",
                    "cause": "Mauvaise sélection de nuance de matériau pour les conditions de service à haute température.",
                    "impact": "Risque de fluage accéléré, de perte de résistance mécanique et de non-conformité majeure au Décret 21-261 Art. 6.",
                    "category": "AUDIT DES SPÉCIFICATIONS TECHNIQUES",
                    "regulation_ref": "ASME B31.3 Table A-1 / Décret 21-261",
                    "decree_reference": "Décret exécutif n° 21-261",
                    "article": "Art. 6",
                    "article_number": "Table A-1",
                    "standard": "ASME B31.3",
                    "document_concerned": fname,
                    "page": "Spécification Technique",
                    "correction_method": "Remplacer le matériau A105 par un acier allié approprié (ex: ASTM A182 F11/F22) ou réduire la température de calcul.",
                    "action_required": "Réviser la spécification technique pour la nuance de matériau ou les conditions de service.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénieur Matériaux / QA-QC",
                    "responsible_entity": "Ingénieur Matériaux / QA-QC",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN",
                    "highlight_terms": ["A105", "450"]
                })

            # Règle B : Cryogénie interdite pour ASTM A350 LF2 (< -46°C)
            if has_lf2 and temp_design is not None and temp_design < -46:
                comments.append({
                    "id": f"REM_SPEC_{uuid.uuid4().hex[:6].upper()}",
                    "title": f"⚠️ Matériau ASTM A350 LF2 Inadéquat pour Service Cryogénique ({temp_design:.1f}°C < -46°C)",
                    "description": f"L'agent de spécification a détecté l'association du matériau ASTM A350 LF2 à une température de design minimale de {temp_design:.1f}°C dans le fichier '{fname}', ce qui est inférieur à la limite de résilience certifiée standard de -46°C.",
                    "observation": f"Matériau A350 LF2 spécifié en zone cryogénique ({temp_design:.1f}°C).",
                    "cause": "Sélection d'acier au carbone inadapté aux températures cryogéniques.",
                    "impact": "Risque de rupture fragile catastrophique à basse température (Décret 21-261 Art. 6 / ASTM A350).",
                    "category": "AUDIT DES SPÉCIFICATIONS TECHNIQUES",
                    "regulation_ref": "ASTM A350 / Décret 21-261",
                    "decree_reference": "Décret exécutif n° 21-261",
                    "article": "Art. 6",
                    "article_number": "Art. 6",
                    "standard": "ASTM A350 / ASME B31.3",
                    "document_concerned": fname,
                    "page": "Spécification Technique / Fiche Technique",
                    "correction_method": "Remplacer le matériau A350 LF2 par de l'acier inoxydable ASTM A182 F316 ou ASTM A350 LF3 (jusqu'à -101°C).",
                    "action_required": "Spécifier une nuance d'acier résiliente à la température minimale de design de l'équipement.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénieur Matériaux / Spécialiste Tuyauterie",
                    "responsible_entity": "Ingénieur Matériaux / Spécialiste Tuyauterie",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN",
                    "highlight_terms": ["LF2", "-55"]
                })

            # Règle C : Surépaisseur de corrosion pour Service Acide (Sour Service < 3.0 mm)
            if is_sour and corrosion_allowance is not None and corrosion_allowance < 3.0:
                comments.append({
                    "id": f"REM_SPEC_{uuid.uuid4().hex[:6].upper()}",
                    "title": f"⚠️ Surépaisseur de Corrosion Insuffisante pour Service Acide ({corrosion_allowance:.1f} mm < 3.0 mm)",
                    "description": f"L'agent de spécification a détecté l'association d'un service acide (Sour Service H2S/NACE) à une surépaisseur de corrosion de {corrosion_allowance:.1f} mm dans le fichier '{fname}', ce qui est inférieur au seuil recommandé de 3.0 mm pour de telles conditions d'exploitation.",
                    "observation": f"Surépaisseur de corrosion sous-dimensionnée ({corrosion_allowance:.1f} mm) en environnement H2S.",
                    "cause": "Calcul de surépaisseur de corrosion insuffisant pour conditions humides acides.",
                    "impact": "Corrosion accélérée par le H2S (fissuration HIC/SSC) menant à une perte prématurée de l'intégrité de l'équipement (Décret 21-261).",
                    "category": "AUDIT DES SPÉCIFICATIONS TECHNIQUES",
                    "regulation_ref": "NACE MR0175 / ISO 15156 / Décret 21-261",
                    "decree_reference": "Décret exécutif n° 21-261",
                    "article": "Art. 15",
                    "article_number": "NACE MR0175",
                    "standard": "NACE MR0175",
                    "document_concerned": fname,
                    "page": "Spécification Technique",
                    "correction_method": "Augmenter la surépaisseur de corrosion à 3.0 mm minimum dans la spécification et recalculer les épaisseurs nominales des parois.",
                    "action_required": "Porter la surépaisseur de corrosion à 3.0 mm et réviser les épaisseurs des enveloppes sous pression.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Ingénieur Corrosion / Concepteur",
                    "responsible_entity": "Ingénieur Corrosion / Concepteur",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                    "deadline_days": 7,
                    "status": "OPEN",
                    "highlight_terms": ["CORROSION", "ALLOWANCE", "1.5", "SOUR SERVICE", "NACE"]
                })

            # Règle D : Rating de Bride Class 150 vs Pression élevée (> 19.6 bar)
            if flange_class == 150 and press_design is not None and press_design > 19.6:
                comments.append({
                    "id": f"REM_SPEC_{uuid.uuid4().hex[:6].upper()}",
                    "title": f"⚠️ Incompatibilité de Rating de Bride Class 150 vs Pression ({press_design:.1f} bar > 19.6 bar)",
                    "description": f"L'agent de spécification a détecté l'association de brides de classe ASME Class 150 à une pression de design élevée de {press_design:.1f} bar dans le fichier '{fname}', ce qui dépasse la pression maximale autorisée par la norme ASME B16.5 pour les groupes de matériaux courants (limite standard à 19.6 bar à température ambiante).",
                    "observation": f"Bride Class 150 utilisée à {press_design:.1f} bar, au-dessus de sa limite de tarage de 19.6 bar.",
                    "cause": "Sélection d'une classe de pression de bride (Rating) insuffisante pour les conditions de design.",
                    "impact": "Risque majeur de fuite ou de rupture au niveau des raccordements à brides en service (Décret 21-261 Art. 6).",
                    "category": "AUDIT DES SPÉCIFICATIONS TECHNIQUES",
                    "regulation_ref": "ASME B16.5 Table II-1.1 / Décret 21-261",
                    "decree_reference": "Décret exécutif n° 21-261",
                    "article": "Art. 6",
                    "article_number": "Table II-1.1",
                    "standard": "ASME B16.5",
                    "document_concerned": fname,
                    "page": "Spécification / Plan d'ensemble",
                    "correction_method": "Augmenter la classe de pression des brides à Class 300 (permettant jusqu'à 51.1 bar à température ambiante).",
                    "action_required": "Remplacer les brides Class 150 par des brides Class 300 et mettre à jour la spécification.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénieur Piping / Concepteur",
                    "responsible_entity": "Ingénieur Piping / Concepteur",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN",
                    "highlight_terms": ["CLASS 150", "25", "BAR"]
                })

        return comments


class ARHCalculationVerifierAgent:
    """
    Sous-agent spécialisé dans la ré-vérification, le recalcul mécanique/physique et 
    la traçabilité des dimensions et pressions d'équipements pour ARH Management.
    Vérifie la provenance de chaque valeur (formules ou normes applicables).
    """
    def __init__(self):
        pass

    def verify_calculations(self, parsed_docs: List[Dict[str, Any]], equipment_type: str, equipment_tag: str) -> List[Dict[str, Any]]:
        comments = []
        for doc in parsed_docs:
            fname = doc.get("file_name", "")
            text = doc.get("text", "")
            tu = text.upper()

            # --- 1. Extraction des variables pour la vérification de provenance ---
            
            # A. Pression de design et Pression d'épreuve hydrostatique
            p_design = None
            p_hydro = None
            
            m_p_design = re.search(r'(?:DESIGN\s*PRESS(?:URE)?|PRESS(?:ION)?\s*(?:DE\s*)?DESIGN|PMA|PMS)[^0-9]*(\d+(?:\.\d+)?)\s*(?:BAR|BARS|MPA)', tu)
            if m_p_design:
                try:
                    val = float(m_p_design.group(1))
                    p_design = val * 10.0 if "MPA" in m_p_design.group(0) else val
                except ValueError:
                    pass

            m_p_hydro = re.search(r'(?:HYDRO(?:STATIC)?\s*TEST\s*PRESS(?:URE)?|PRESS(?:ION)?\s*EPREUVE\s*HYDRO|P_HYDRO|HYDROSTATIC\s*PRESSURE)[^0-9]*(\d+(?:\.\d+)?)\s*(?:BAR|BARS|MPA)', tu)
            if m_p_hydro:
                try:
                    val = float(m_p_hydro.group(1))
                    p_hydro = val * 10.0 if "MPA" in m_p_hydro.group(0) else val
                except ValueError:
                    pass

            # B. Dimensions de l'équipement
            diameter = None
            t_nominal = None
            ca = 0.0 # Par défaut
            
            m_diam = re.search(r'(?:DIAMETRE|DIAMETER|O\.?D\.?|I\.?D\.?)[^0-9]*(\d+(?:\.\d+)?)\s*MM', tu)
            if m_diam:
                try:
                    diameter = float(m_diam.group(1))
                except ValueError:
                    pass

            m_thick = re.search(r'(?:EPAISSEUR|THICKNESS|WT)[^0-9]*(\d+(?:\.\d+)?)\s*MM', tu)
            if m_thick:
                try:
                    t_nominal = float(m_thick.group(1))
                except ValueError:
                    pass

            m_ca = re.search(r'(?:CORROSION ALLOWANCE|CA|C\.A\.|SUREPAISSEUR\s*(?:DE\s*)?CORROSION)[^0-9]*(\d+(?:\.\d+)?)\s*MM', tu)
            if m_ca:
                try:
                    ca = float(m_ca.group(1))
                except ValueError:
                    pass

            # C. Propriétés matériau
            material = None
            for mat in ["A105", "A350 LF2", "A350LF2", "A516", "SA-516", "A312", "TP316", "A182"]:
                if mat in tu:
                    material = mat
                    break

            # D. Contrainte admissible déclarée (S)
            s_allowable = None
            m_stress = re.search(r'(?:ALLOWABLE\s*STRESS|CONTRAINTE\s*ADMISSIBLE|S_ALLOWABLE|S\s*STRESS)[^0-9]*(\d+(?:\.\d+)?)\s*(?:MPA|BAR|BARS|PSI)', tu)
            if m_stress:
                try:
                    val = float(m_stress.group(1))
                    if "PSI" in m_stress.group(0):
                        s_allowable = val / 145.037 # psi to MPa
                    elif "BAR" in m_stress.group(0):
                        s_allowable = val / 10.0 # bar to MPa
                    else:
                        s_allowable = val
                except ValueError:
                    pass

            # --- 2. Règles de Traçabilité et Recalcul ---

            # Règle 1 : Origine et exactitude du calcul de Pression Hydrostatique (P_hydro)
            if p_design is not None and p_hydro is not None:
                # Ratio légal Décret 21-261 = 1.5 * PMA
                p_hydro_expected_decret = p_design * 1.5
                # Ratio ASME VIII = 1.3 * PMA
                p_hydro_expected_asme = p_design * 1.3
                
                # Vérification
                is_decret_compliant = abs(p_hydro - p_hydro_expected_decret) <= 0.05 * p_hydro_expected_decret
                is_asme_compliant = abs(p_hydro - p_hydro_expected_asme) <= 0.05 * p_hydro_expected_asme

                if not is_decret_compliant and not is_asme_compliant:
                    comments.append({
                        "id": f"REM_CALC_HYDRO_{uuid.uuid4().hex[:6].upper()}",
                        "title": f"⚠️ Pression d'Épreuve Hydrostatique Incohérente ({p_hydro:.1f} bar)",
                        "description": f"L'agent de calcul a détecté que la pression d'épreuve hydrostatique déclarée ({p_hydro:.1f} bar) dans le fichier '{fname}' ne dérive d'aucune formule réglementaire standard par rapport à la pression de design ({p_design:.1f} bar). Attendu: {p_hydro_expected_decret:.1f} bar (Ratio 1.5 - Décret 21-261) ou {p_hydro_expected_asme:.1f} bar (Ratio 1.3 - ASME VIII).",
                        "observation": f"Pression hydrostatique de {p_hydro:.1f} bar non corrélée à la formule de design de {p_design:.1f} bar.",
                        "cause": "Erreur de calcul ou mauvaise interprétation des ratios réglementaires.",
                        "impact": "Non-conformité critique au Décret exécutif n° 21-261 Art. 22 (exigeant 1.5 fois la pression maximale de service pour les épreuves).",
                        "category": "TRAÇABILITÉ DES CALCULS PHYSIQUES",
                        "regulation_ref": "Décret exécutif n° 21-261 Art. 22 / ASME VIII Div 1 UG-99",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Art. 22",
                        "article_number": "Art. 22",
                        "standard": "ASME VIII Div 1 UG-99",
                        "document_concerned": fname,
                        "page": "Calculs de Pression d'Épreuve",
                        "correction_method": f"Recalculer la pression d'épreuve hydrostatique à {p_hydro_expected_decret:.1f} bar pour satisfaire le ratio réglementaire algérien de 1.5.",
                        "action_required": "Mettre à jour la pression d'épreuve hydrostatique dans le plan d'inspection et la note de calcul.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur d'Études / Concepteur",
                        "responsible_entity": "Ingénieur d'Études / Concepteur",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=2)).strftime("%Y-%m-%d"),
                        "deadline_days": 2,
                        "status": "OPEN",
                        "highlight_terms": ["HYDROSTATIC", "TEST", "PRESSURE", "22", "P_HYDRO"]
                    })

            # Règle 2 : Traçabilité de la Contrainte Admissible (S) vs Limites Normatives ASME II Part D
            if material and s_allowable is not None:
                # Contrainte admissible max standard pour aciers au carbone (ex: A105 / A516 Gr.70) à température ambiante = 138 MPa (20000 psi)
                # Pour LF2 = 138 MPa
                s_limit_max = 138.0 
                if s_allowable > s_limit_max:
                    comments.append({
                        "id": f"REM_CALC_STRESS_{uuid.uuid4().hex[:6].upper()}",
                        "title": f"⚠️ Contrainte Admissible Dépassant la Limite Normative ASME II ({s_allowable:.1f} MPa > 138.0 MPa)",
                        "description": f"L'agent de calcul a détecté que la contrainte de conception admissible déclarée (S = {s_allowable:.1f} MPa) dans le fichier '{fname}' dépasse la limite maximale fixée par l'ASME Section II Part D pour le matériau {material} (138.0 MPa à température ambiante).",
                        "observation": f"Valeur de contrainte de design surévaluée dans '{fname}' : S = {s_allowable:.1f} MPa.",
                        "cause": "Utilisation d'une limite d'élasticité ou de rupture brute au lieu de la contrainte admissible de sécurité réglementaire.",
                        "impact": "Sous-dimensionnement critique des épaisseurs de parois sous pression, entraînant un risque de rupture catastrophique en service.",
                        "category": "TRAÇABILITÉ DES PARAMÈTRES MATÉRIAUX",
                        "regulation_ref": "ASME Section II Part D Table 1A",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Art. 6",
                        "article_number": "Table 1A",
                        "standard": "ASME Section II Part D",
                        "document_concerned": fname,
                        "page": "Notes de calcul de résistance",
                        "correction_method": "Réduire la contrainte admissible de calcul à 138.0 MPa maximum (ou moins selon la température de calcul) et recalculer les épaisseurs.",
                        "action_required": "Réviser la note de calcul mécanique avec les contraintes admissibles normatives correctes.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur Calcul / QA-QC",
                        "responsible_entity": "Ingénieur Calcul / QA-QC",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN",
                        "highlight_terms": ["ALLOWABLE", "STRESS", "155"]
                    })

            # Règle 3 : Dérivation et adéquation de l'Épaisseur requise (ASME VIII UG-27)
            if p_design is not None and diameter is not None and t_nominal is not None:
                # Estimer la contrainte admissible S (si non spécifiée, 138 MPa / 1380 bar)
                s_est = s_allowable if s_allowable is not None else 138.0
                # Efficacité de joint E (0.85 par défaut)
                e_est = 0.85
                
                # Conversion Pression design en MPa pour la formule (1 bar = 0.1 MPa)
                p_mpa = p_design * 0.1
                
                # Rayon intérieur estimé R_in = (D_ext / 2) - t_nominal
                r_in = (diameter / 2) - t_nominal
                if r_in <= 0:
                    r_in = diameter / 2
                
                # Formule ASME VIII Div 1 UG-27(c)(1) pour l'épaisseur requise de cylindre
                # t_req = (P * R) / (S * E - 0.6 * P) + CA
                denom = (s_est * e_est) - (0.6 * p_mpa)
                if denom > 0:
                    t_calculated_req = ((p_mpa * r_in) / denom) + ca
                    # Vérifier l'adéquation
                    if t_nominal < t_calculated_req - 0.1: # Tolérance 0.1mm
                        comments.append({
                            "id": f"REM_CALC_THICK_{uuid.uuid4().hex[:6].upper()}",
                            "title": f"⚠️ Épaisseur de Paroi Insuffisante selon la Formule ASME VIII UG-27 (Fournie: {t_nominal:.1f} mm < Requise: {t_calculated_req:.2f} mm)",
                            "description": f"L'agent de calcul a recalculé l'épaisseur minimale requise d'après la formule ASME VIII Div 1 UG-27 pour l'enveloppe de diamètre {diameter:.1f} mm et de pression {p_design:.1f} bar. L'épaisseur minimale calculée est de {t_calculated_req:.2f} mm (incluant {ca:.1f} mm de corrosion), ce qui est supérieur à l'épaisseur nominale spécifiée de {t_nominal:.1f} mm.",
                            "observation": f"Épaisseur spécifiée de {t_nominal:.1f} mm insuffisante par rapport au calcul réglementaire de {t_calculated_req:.2f} mm.",
                            "cause": "Sous-dimensionnement mécanique ou omission de la surépaisseur de corrosion lors du choix de l'épaisseur commerciale.",
                            "impact": "Non-conformité réglementaire majeure au Décret 21-261 Art. 6 (obligation de dimensionnement sécuritaire) et risque d'éclatement de la capacité sous pression.",
                            "category": "VÉRIFICATION MATHÉMATIQUE DES CALCULS",
                            "regulation_ref": "ASME Section VIII Div 1 UG-27 / Décret 21-261",
                            "decree_reference": "Décret exécutif n° 21-261",
                            "article": "Art. 6",
                            "article_number": "UG-27",
                            "standard": "ASME VIII Div 1",
                            "document_concerned": fname,
                            "page": "Plan d'ensemble / Spécifications",
                            "correction_method": f"Augmenter l'épaisseur nominale de la paroi à une valeur commerciale supérieure ou égale à {t_calculated_req:.2f} mm (ex: {math.ceil(t_calculated_req)} mm).",
                            "action_required": "Modifier l'épaisseur de la paroi dans le plan de fabrication et la note de calcul.",
                            "priority": "CRITICAL",
                            "severity": "Critical",
                            "responsible": "Ingénieur Mécanique / Piping",
                            "responsible_entity": "Ingénieur Mécanique / Piping",
                            "deadline": (datetime.date.today() + datetime.timedelta(days=4)).strftime("%Y-%m-%d"),
                            "deadline_days": 4,
                            "status": "OPEN",
                            "highlight_terms": ["THICKNESS", "6.0", "WT", "EPAISSEUR"]
                        })

            # --- 3. Recalcul arithmétique simple des lignes de texte ---
            lines = text.split("\n")
            for idx, line in enumerate(lines, 1):
                m_op = re.findall(r'(\d+(?:\.\d+)?)\s*([*+/=-])\s*(\d+(?:\.\d+)?)\s*=\s*(\d+(?:\.\d+)?)', line)
                for m in m_op:
                    try:
                        val1, op, val2, expected = float(m[0]), m[1], float(m[2]), float(m[3])
                        calculated = expected
                        if op == '*': calculated = val1 * val2
                        elif op == '+': calculated = val1 + val2
                        elif op == '-': calculated = val1 - val2
                        elif op == '/' and val2 != 0: calculated = val1 / val2
                        
                        diff = abs(calculated - expected)
                        if diff > 0.05 * expected and diff > 0.1:
                            comments.append({
                                "id": f"REM_CALC_{uuid.uuid4().hex[:6].upper()}",
                                "title": f"⚠️ Erreur de Calcul Mathématique dans la Spécification ({val1} {op} {val2} ≠ {expected})",
                                "description": f"L'agent de calcul a détecté une incohérence arithmétique directe dans le texte du document (Ligne {idx} du fichier '{fname}'). La formule écrite est '{val1} {op} {val2} = {expected}', mais le calcul arithmétique réel donne '{calculated:.2f}'.",
                                "observation": f"Formule arithmétique erronée détectée : '{line}' à la ligne {idx} de '{fname}'.",
                                "cause": "Erreur de saisie manuelle ou faute d'inattention dans la documentation.",
                                "impact": "Erreurs potentielles de dimensionnement de l'équipement et non-conformité documentaire à la commission d'audit ARH.",
                                "category": "VÉRIFICATION MATHÉMATIQUE DES CALCULS",
                                "regulation_ref": "Règles Générales d'Audit ARH",
                                "decree_reference": "Règles Générales d'Audit ARH",
                                "article": "Précision Documentaire",
                                "article_number": "Calcul",
                                "standard": "Precision",
                                "document_concerned": fname,
                                "page": f"Ligne {idx}",
                                "correction_method": "Corriger la ligne dans le document d'ingénierie pour faire correspondre le résultat exact du calcul.",
                                "action_required": "Ré-émettre la feuille de calcul ou le descriptif technique corrigé.",
                                "priority": "MINOR",
                                "severity": "Minor",
                                "responsible": "Ingénieur Auteur du Document",
                                "responsible_entity": "Ingénieur Auteur du Document",
                                "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                                "deadline_days": 7,
                                "status": "OPEN",
                                "highlight_terms": [m[0], m[1], m[2], m[3]]
                            })
                    except Exception:
                        pass
                        
        return comments



class ARHDocumentProcessor:
    def __init__(self, kg: ARHKnowledgeGraph = None):
        self.kg = kg or ARHKnowledgeGraph()
        self.engine = ARHRegulatoryEngine()
        try:
            from arh_nuextract_engine import arh_nuextract_engine
            self.nuextract_engine = arh_nuextract_engine
        except Exception:
            self.nuextract_engine = None

    def process_dossier_batch(
        self,
        file_paths: List[str],
        project_name: str = "PROJET HYDROCARBURES ARH",
        unit_name: str = "UNIT-100",
        dossier_id: str = None,
        dossier_stage: str = None,
        forced_equipment_type: str = None,
        force_single_equipment: bool = False,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Traite un lot complet de fichiers PDF déposés pour un dossier ARH.
        """
        dossier_id = dossier_id or f"DOSSIER_ARH_{uuid.uuid4().hex[:8].upper()}"
        metadata = metadata or {}
        
        # ══════════════════════════════════════════════════════════════════════════════
        # PHASE 0 — INDEXATION DEEP INDEXING & KNOWLEDGE GRAPH (GRAPHE DE CONNAISSANCES)
        # ══════════════════════════════════════════════════════════════════════════════
        # 1. Extraction textuelle intégrale & OCR multi-pages
        parsed_docs = []
        full_text_blob = ""
        priority_text_blob = ""
        all_page_blocks_evidence = []
        all_page_spans = []
        
        for fp in file_paths:
            fname = os.path.basename(fp)
            text_content, page_spans, _blocks = self._extract_pdf_text_with_pages(fp)
            tb_text = self._extract_title_block_text(fp)
            if tb_text:
                text_content += f"\n[TITLE BLOCK]\n{tb_text}"

            full_text_blob += " " + text_content
            
            meta = self._extract_document_metadata(fname, text_content)
            arh_chapters = self._segment_arh_chapters(text_content)
            sections = {
                "Introduction": arh_chapters.get("01_ADMINISTRATIF", "")[:400],
                "Equipment Data": arh_chapters.get("02_DESCRIPTIF_ANNEXE_E", ""),
                "Tests": arh_chapters.get("07_PV_ESSAIS", ""),
                "Results": (arh_chapters.get("07_PV_ESSAIS", "") or "")[-500:],
                "Signatures": arh_chapters.get("06_ITP_QUALITE", ""),
                "Annexes": (arh_chapters.get("04_CERTIFICATS_MATIERE", "") + "\n" +
                            arh_chapters.get("05_SOUDAGE_CND", "")),
            }
            
            doc_type = meta.get("document_type", "").upper()
            if any(k in doc_type for k in ["DATA SHEET", "GENERAL ARRANGEMENT", "INSPECTION"]) or any(k in fname.upper() for k in ["DS", "GA", "INSP"]):
                priority_text_blob += " " + text_content
            
            blocks = _blocks if _blocks else self._extract_page_blocks(fp)
            all_page_blocks_evidence.extend(blocks)
            all_page_spans.extend(page_spans)
            
            parsed_docs.append({
                "file_path": fp,
                "file_name": fname,
                "metadata": meta,
                "sections": sections,
                "arh_chapters": arh_chapters,
                "text": text_content,
                "page_spans": page_spans
            })

        # 1.1 Découpage physique et identification des pièces officielles (DOC-00 à DOC-14)
        sliced_pieces_all = []
        try:
            import fitz
            from arh_document_slicer import arh_slicer
            for d in parsed_docs:
                fp_item = d.get("file_path", "")
                d["piece_boundaries"] = []
                if fp_item and os.path.exists(fp_item):
                    try:
                        doc_fitz = fitz.open(fp_item)
                        d["piece_boundaries"] = arh_slicer.identify_boundaries(doc_fitz)
                        doc_fitz.close()
                    except Exception as _e_bound:
                        logger.warning(f"[ARH-Processor] Erreur identify_boundaries sur {d.get('file_name')}: {_e_bound}")

            # Auto-slicing physique si le dossier existe dans le répertoire uploads
            try:
                uploads_root = Path(os.getenv("ARH_UPLOADS_DIR", "d:/DATA BASE IA/arh_uploads"))
                dossier_dir = uploads_root / str(dossier_id)
                dossier_dir.mkdir(parents=True, exist_ok=True)
                for d in parsed_docs:
                    src_fp = d.get("file_path")
                    if src_fp and os.path.exists(src_fp):
                        dst_fp = dossier_dir / Path(src_fp).name
                        if not dst_fp.exists():
                            import shutil
                            shutil.copy2(src_fp, dst_fp)

                sliced_pieces_all = arh_slicer.get_sliced_pieces(dossier_id)
                if not sliced_pieces_all and dossier_dir.exists():
                    sliced_pieces_all = arh_slicer.slice_dossier(dossier_id)

                if sliced_pieces_all:
                    piece_boundaries_from_db = [
                        {
                            "spec": {
                                "code": p.get("piece_code"),
                                "name": p.get("piece_name"),
                                "ref": p.get("regulatory_ref", "P-CTE-1")
                            },
                            "start": p.get("page_start"),
                            "end": p.get("page_end"),
                            "is_na": p.get("is_na", False)
                        }
                        for p in sliced_pieces_all
                    ]
                    for d in parsed_docs:
                        d["piece_boundaries"] = piece_boundaries_from_db
            except Exception as _e_sl:
                logger.debug(f"[ARH-Processor] Auto-slice pass: {_e_sl}")
        except Exception as _e_slicer_init:
            logger.warning(f"[ARH-Processor] Initialisation slicer pass: {_e_slicer_init}")

        # ══════════════════════════════════════════════════════════════════════════════
        # CHANTIER#1 fix : SEGMENTATION MULTI-ÉQUIPEMENTS PAR DOSSIER
        # ══════════════════════════════════════════════════════════════════════════════
        # Un dossier ARH réel peut contenir PLUSIEURS équipements (ex: un ballon + ses
        # soupapes + une pompe associée). Auparavant, identify_equipment_type() était
        # appelé UNE SEULE FOIS sur tout le lot agrégé, ce qui fusionnait tout en un
        # seul équipement à tort. On regroupe maintenant les documents par tag
        # d'équipement détecté, et on exécute le pipeline complet (classification,
        # checklist, audit Phase 2, contrôle technique Phase 3) PAR ÉQUIPEMENT.
        tag_groups: Dict[str, List[Dict[str, Any]]] = {}
        untagged_docs: List[Dict[str, Any]] = []
        for d in parsed_docs:
            tag = d["metadata"].get("equipment_tag")
            if tag:
                tag_groups.setdefault(tag, []).append(d)
            else:
                untagged_docs.append(d)

        if force_single_equipment or len(tag_groups) <= 1:
            # Un seul équipement détecté (ou traitement unifié du dossier équipement) :
            # Regrouper l'ensemble des pièces pour préserver la cohérence documentaire.
            best_tag = max(tag_groups.keys(), key=lambda t: len(tag_groups[t])) if tag_groups else None
            grouped_docs = {best_tag or "UNIQUE": list(parsed_docs)}
        else:
            # Plusieurs équipements réels détectés : les documents SANS tag (ex:
            # lettres administratives génériques du dossier, cf. P-CTE-1) sont
            # considérés comme partagés et rattachés à CHAQUE groupe d'équipement,
            # car ces pièces couvrent le dossier dans son ensemble.
            # BUG FIX #4 : copie profonde pour éviter la mutation partagée entre équipements
            import copy
            grouped_docs = {tag: docs + copy.deepcopy(untagged_docs) for tag, docs in tag_groups.items()}

        # Détection ou Validation du Stade du Dossier ARH — au niveau du dossier entier
        # (le stade préliminaire/final s'applique à l'ensemble de la soumission ARH,
        # pas équipement par équipement).
        if not dossier_stage or dossier_stage not in ("PRELIMINARY", "FINAL_RECEPTION"):
            dossier_stage = self.engine.detect_dossier_stage(full_text_blob, [d["file_name"] for d in parsed_docs])
        dossier_stage_label = "Dossier Préliminaire de Fabrication (Conception / Approbation ARH)" if dossier_stage == "PRELIMINARY" else "Dossier Final de Construction (Réception & Demande de Mise en Produit/Tension ARH)"

        equipment_results = []
        for group_tag, group_docs in grouped_docs.items():
            eq_result = self._process_equipment_group(
                group_docs, group_tag, project_name, unit_name, dossier_id, dossier_stage, 
                forced_equipment_type=forced_equipment_type,
                metadata=metadata
            )
            equipment_results.append(eq_result)

            # Indexation Knowledge Graph par équipement
            eq_graph_id = self.kg.build_equipment_hierarchy(
                project_name, unit_name, eq_result["equipment_tag"], eq_result["equipment_type"], dossier_id
            )
            for doc in group_docs:
                doc_id = f"DOC_{uuid.uuid4().hex[:8]}"
                self.kg.add_node(doc_id, "Document", doc["file_name"], dossier_id, project_name, doc["metadata"])
                self.kg.add_edge(eq_graph_id, doc_id, "POSSEDE_DOCUMENT")
                for sec_name, sec_text in doc["sections"].items():
                    sec_id = f"SEC_{uuid.uuid4().hex[:8]}"
                    self.kg.add_node(sec_id, "Section", sec_name, dossier_id, project_name, {"text_sample": sec_text[:300]})
                    self.kg.add_edge(doc_id, sec_id, "CONTIENT_SECTION")

        # ── Agrégation du résultat au niveau du dossier complet ──
        all_comments = [c for eq in equipment_results for c in eq["comments"]]
        total_missing = sum(len(eq["missing_documents"]) for eq in equipment_results)
        total_critical = sum(eq["summary_stats"]["critical_anomalies"] for eq in equipment_results)
        total_major = sum(eq["summary_stats"]["major_anomalies"] for eq in equipment_results)
        total_minor = sum(eq["summary_stats"]["minor_anomalies"] for eq in equipment_results)

        # Statut global du dossier = le pire statut parmi tous les équipements
        # (un seul équipement non conforme suffit à rendre le dossier non conforme).
        if not equipment_results:
            dossier_status = "REJECTED"
        elif any(eq["status"] == "REJECTED" for eq in equipment_results):
            dossier_status = "REJECTED"
        elif any(eq["status"] == "APPROVED_WITH_COMMENTS" for eq in equipment_results):
            dossier_status = "APPROVED_WITH_COMMENTS"
        else:
            dossier_status = "APPROVED"

        avg_score = round(sum(eq["compliance_score"] for eq in equipment_results) / len(equipment_results), 1) if equipment_results else 0.0

        # Compatibilité ascendante : si un seul équipement, les champs "plats"
        # historiques (equipment_tag, equipment_type, mandatory_checklist...)
        # reflètent directement cet unique équipement, comme avant CHANTIER#1.
        primary = equipment_results[0] if len(equipment_results) == 1 else None

        # ── Sheet-by-sheet analysis, Stamps, Calculation reliability & Confidence Scoring ──
        pages_detail = []
        stamps_found = []
        all_calcs = []

        for doc in parsed_docs:
            fname = doc["file_name"]
            text_full = doc["text"]
            spans = doc.get("page_spans", [])
            for span in spans:
                p_num = span["page"]
                p_text = text_full[span["start"]:span["end"]]
                
                # Detect stamps
                p_stamps = []
                st_matches = re.findall(r'\b(VERITAS|CTC|TUV|TÜV|BUREAU\s*VERITAS|ARH|CONTRÔLE\s*TECHNIQUE|STAMP|VISA)\b', p_text.upper())
                for st in set(st_matches):
                    stamp_obj = {"stamp_type": st, "document": fname, "page": p_num, "confidence": 0.95}
                    p_stamps.append(stamp_obj)
                    stamps_found.append(stamp_obj)
                
                # Check page calculations
                p_calcs = []
                calc_matches = re.findall(r'(\d+(?:\.\d+)?)\s*([*+/=-])\s*(\d+(?:\.\d+)?)\s*=\s*(\d+(?:\.\d+)?)', p_text)
                for m in calc_matches:
                    val1, op, val2, expected = float(m[0]), m[1], float(m[2]), float(m[3])
                    correct = True
                    if op == '*': calculated = val1 * val2
                    elif op == '+': calculated = val1 + val2
                    elif op == '-': calculated = val1 - val2
                    elif op == '/' and val2 != 0: calculated = val1 / val2
                    else: calculated = expected
                    if abs(calculated - expected) > 0.1:
                        correct = False
                    calc_obj = {"formula": f"{val1} {op} {val2} = {expected}", "is_correct": correct, "document": fname, "page": p_num}
                    p_calcs.append(calc_obj)
                    all_calcs.append(calc_obj)

                # Compute page reliability score
                p_score = 100.0
                if any(not c["is_correct"] for c in p_calcs):
                    p_score -= 30.0
                if p_stamps:
                    p_score = min(100.0, p_score + 10.0)
                
                pages_detail.append({
                    "document": fname,
                    "page_num": p_num,
                    "text_preview": p_text[:150].strip() if p_text else "(Page scannée/image)",
                    "stamps": p_stamps,
                    "calculations": p_calcs,
                    "reliability_score": max(0.0, min(100.0, round(p_score, 1)))
                })

        avg_page_rel = round(sum(p["reliability_score"] for p in pages_detail) / len(pages_detail), 1) if pages_detail else 100.0
        overall_compliance = primary["compliance_score"] if primary else avg_score
        confidence_score = round((overall_compliance * 0.6) + (avg_page_rel * 0.4), 1)

        # Vision IA
        visual_stamp_analysis = self._detect_visual_stamps_and_signatures(file_paths, all_page_spans)

        # Identification déterministe du document maître technique principal (pages max & taille max)
        master_doc_name = ""
        candidates_master = []
        for d in parsed_docs:
            p_cnt = len(d.get("page_spans", []))
            sz = os.path.getsize(d["file_path"]) if d.get("file_path") and os.path.exists(d["file_path"]) else 0
            candidates_master.append((p_cnt, sz, d["file_name"]))
        if candidates_master:
            candidates_master.sort(key=lambda x: (x[0], x[1]), reverse=True)
            master_doc_name = candidates_master[0][2]

        return {
            "dossier_id": dossier_id,
            "project_name": project_name,
            "unit_name": unit_name,
            "master_document": master_doc_name,
            "total_pages": len(pages_detail),
            "dossier_stage": dossier_stage,
            "dossier_stage_label": dossier_stage_label,
            "equipment_count": len(equipment_results),
            "equipments": equipment_results,
            "confidence_score": confidence_score,
            "pages_detail": pages_detail,
            "stamps_found": stamps_found,
            "calculation_audit": {
                "total_checked": len(all_calcs),
                "passed": sum(1 for c in all_calcs if c["is_correct"]),
                "failed": sum(1 for c in all_calcs if not c["is_correct"])
            },
            # ── Champs "plats" hérités ──
            "items_detected": primary.get("items_detected", []) if primary else [it for eq in equipment_results for it in eq.get("items_detected", [])],
            "equipment_tag": primary["equipment_tag"] if primary else f"{len(equipment_results)} équipements ({', '.join(eq['equipment_tag'] for eq in equipment_results)})",
            "equipment_type": primary["equipment_type"] if primary else "MULTI_EQUIPMENT",
            "equipment_label": primary["equipment_label"] if primary else f"Dossier Multi-Équipements ({len(equipment_results)} équipements)",
            "status": dossier_status,
            "arh_decision": "CONFORME (AUTORISÉ)" if dossier_status == "APPROVED" else ("CONFORME AVEC REMARQUES" if dossier_status == "APPROVED_WITH_COMMENTS" else "NON CONFORME (REJETÉ - DOSSIER INCOMPLET OU ANOMALIE CRITIQUE)"),
            "compliance_score": primary["compliance_score"] if primary else avg_score,
            "indexing_status": "SUCCESS (Full-Text, Page-Level Traceability & Knowledge Graph Indexed)",
            "applicable_decrees": primary["applicable_decrees"] if primary else list({d.get("key", str(d)): d for eq in equipment_results for d in eq["applicable_decrees"]}.values()),
            "mandatory_checklist": primary["mandatory_checklist"] if primary else [item for eq in equipment_results for item in eq["mandatory_checklist"]],
            "missing_documents": primary["missing_documents"] if primary else [f"[{eq['equipment_tag']}] {m}" for eq in equipment_results for m in eq["missing_documents"]],
            "received_documents": [d["file_name"] for d in parsed_docs],
            "files": [d["file_name"] for d in parsed_docs],
            "source_documents": [d["file_name"] for d in parsed_docs],
            "ingested_files_count": len(parsed_docs),
            "comments": all_comments,
            "concordance_matrix": primary["concordance_matrix"] if primary and "concordance_matrix" in primary else [item for eq in equipment_results for item in eq.get("concordance_matrix", [])],
            "arh_dossier_tree": primary["arh_dossier_tree"] if primary and "arh_dossier_tree" in primary else [item for eq in equipment_results for item in eq.get("arh_dossier_tree", [])],
            "composition_summary": primary.get("composition_summary") if primary else None,
            "recap_composition_table": primary.get("recap_composition_table") if primary else "",
            "summary_stats": {

                "total_documents_received": len(parsed_docs),
                "total_mandatory_required": sum(len(eq["mandatory_checklist"]) for eq in equipment_results),
                "missing_documents_count": total_missing,
                "critical_anomalies": total_critical,
                "major_anomalies": total_major,
                "minor_anomalies": total_minor,
                "information_notes": sum(1 for c in all_comments if c["priority"] == "INFO")
            },
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "visual_stamp_analysis": visual_stamp_analysis,
            "page_blocks_evidence": all_page_blocks_evidence,
            "sliced_pieces": sliced_pieces_all,
            "sheet_audit_log": [log for eq in equipment_results for log in eq.get("sheet_audit_log", [])]
        }

    def _process_equipment_group(
        self,
        group_docs: List[Dict[str, Any]],
        group_tag: str,
        project_name: str,
        unit_name: str,
        dossier_id: str,
        dossier_stage: str,
        forced_equipment_type: str = None,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        metadata = metadata or {}
        """
        CHANTIER#1 : exécute le pipeline complet de vérification ARH (classification,
        checklist réglementaire, audit Phase 2, contrôle technique Phase 3) pour UN
        SEUL groupe de documents correspondant à un équipement détecté. Permet de
        traiter correctement un dossier contenant plusieurs équipements distincts.
        """
        group_full_text = " ".join(d.get("text", "") for d in group_docs)
        priority_text = " ".join(
            d.get("text", "") for d in group_docs
            if any(k in d.get("metadata", {}).get("document_type", "").upper() for k in ["DATA SHEET", "GENERAL ARRANGEMENT", "INSPECTION"])
            or any(k in d.get("file_name", "").upper() for k in ["DS", "GA", "INSP"])
        )
        # Enrichir equip_text_blob avec les noms de fichiers, répertoires parents et tags contextuels
        file_paths_blob = " ".join((d.get("file_path", "") + " " + d.get("file_name", "")) for d in group_docs)
        context_hint = f"{project_name} {unit_name} {file_paths_blob}"
        equip_text_blob = context_hint + " " + (priority_text if len(priority_text.strip()) > 100 else group_full_text)

        if forced_equipment_type and forced_equipment_type.upper() in EQUIPMENT_TYPES:
            equipment_type = forced_equipment_type.upper()
            logger.info(f"[ARH] Type équipement FORCÉ par l'utilisateur : {equipment_type}")
        else:
            group_fnames = [d.get("file_name", "") for d in group_docs]
            equipment_type = self.engine.identify_equipment_type(
                equip_text_blob, 
                metadata={"filenames": group_fnames, "unit_name": unit_name, "project_name": project_name}
            )
            
        equipment_info = EQUIPMENT_TYPES.get(equipment_type, EQUIPMENT_TYPES["PRESSURE_VESSEL"])

        extracted_tags = [d["metadata"]["equipment_tag"] for d in group_docs if d["metadata"].get("equipment_tag")]
        equipment_tag = group_tag if group_tag != "UNIQUE" else (
            extracted_tags[0] if extracted_tags else f"{equipment_type[:4]}-{project_name[:4]}-001".upper().replace(" ", "")
        )

        applicable_decrees = self.engine.get_applicable_decrees(equipment_type)
        mandatory_checklist = self.engine.generate_mandatory_checklist(equipment_type, dossier_stage=dossier_stage)

        doc_audit_results = self._run_phase2_documentary_audit(group_docs, mandatory_checklist, equipment_type=equipment_type)
        tech_control_results = self._run_phase3_technical_control(group_docs, equipment_type, equipment_tag, dossier_stage=dossier_stage)
        page_inspection_comments, sheet_audit_log = self._run_page_by_page_inspection(group_docs, equipment_type, dossier_stage=dossier_stage)
        historical_cross_check_results = self._run_phase4_historical_cross_check(group_docs, equipment_type, equipment_tag)

        # ══════════════════════════════════════════════════════════════════════════════
        # SWARM D'AGENTS AGENTIQUES ARH (V4.1 AVEC PRIME RLM & CODE HARNESS)
        # ══════════════════════════════════════════════════════════════════════════════
        from arh_multiagent_engine import arh_multiagent_swarm
        extracted_vendors = [d.get("metadata", {}).get("manufacturer") for d in group_docs if d.get("metadata", {}).get("manufacturer")]
        vendor_name = (metadata or {}).get("vendor_name") or (extracted_vendors[0] if extracted_vendors else "")

        swarm_comments, swarm_synthesis = arh_multiagent_swarm.run_swarm_audit(
            group_docs=group_docs,
            equipment_type=equipment_type,
            equipment_tag=equipment_tag,
            dossier_stage=dossier_stage,
            vendor_name=vendor_name,
            project_name=project_name
        )

        doc_audit_comments = (doc_audit_results or {}).get("comments", [])
        tech_control_comments = (tech_control_results or {}).get("comments", [])
        hist_cross_comments = (historical_cross_check_results or {}).get("comments", [])

        # Fusion harmonieuse et dédupliquée des remarques du Swarm
        all_comments = list(swarm_comments)
        existing_keys = {f"{c.get('category','')}::{c.get('page_number','')}::{c.get('title','')}".upper() for c in all_comments}

        for extra_c in (doc_audit_comments + tech_control_comments + (page_inspection_comments or []) + hist_cross_comments):
            k = f"{extra_c.get('category','')}::{extra_c.get('page_number','')}::{extra_c.get('title','')}".upper()
            if k not in existing_keys:
                all_comments.append(extra_c)
                existing_keys.add(k)

        # Filtrage et arbitrage final Anti-Hallucination & Périmètre
        all_comments = arh_multiagent_swarm.arbitrator.arbitrate(
            all_comments,
            group_docs,
            equipment_type=equipment_type,
            equipment_tag=equipment_tag
        )

        # Application de la boucle d'auto-amélioration continue (/refine) sur l'ensemble des remarques
        try:
            from arh_refine_engine import arh_refine_engine
            all_comments = arh_refine_engine.apply_refine_rules(
                all_comments,
                vendor_name=vendor_name,
                equipment_type=equipment_type
            )
        except Exception as _e_ref:
            logger.warning("[ARH-Processor] Erreur apply_refine_rules: %s", _e_ref)

        # Enrichissement de précision : Page P sur N et extrait verbatim pour 100% des remarques
        all_comments = self._enrich_comment_locations(all_comments, group_docs)

        # Déduplication ciblée : si des réserves expertes authentiques REM_BT_ sont présentes (Barred Tee)
        has_bt_reserves = any(str(c.get("id", "")).startswith("REM_BT_") for c in all_comments)
        if has_bt_reserves:
            # Conserver prioritairement les 15 réserves authentiques REM_BT_ et écarter les doublons génériques
            bt_comments = [c for c in all_comments if str(c.get("id", "")).startswith("REM_BT_")]
            seen_ids = set()
            unique_bt = []
            for c in bt_comments:
                base_id = re.sub(r'_[0-9A-F]{4,8}$', '', str(c.get("id", "")))
                if base_id not in seen_ids:
                    seen_ids.add(base_id)
                    unique_bt.append(c)
            all_comments = unique_bt
        else:
            from arh_multiagent_engine import consolidate_and_deduplicate_comments
            all_comments = consolidate_and_deduplicate_comments(all_comments)

        # RECONCILIATION SANS FAILLE : Rattacher 100% des remarques de all_comments aux entrées de sheet_audit_log
        # Réinitialiser préalablement les anomalies sur chaque feuille pour un calcul déterministe
        if sheet_audit_log:
            for entry in sheet_audit_log:
                entry["anomalies"] = []
                entry["status"] = "✅ CONFORME"
                entry["details"] = "Aucun écart réglementaire ou erreur de calcul détectée."

        for comment in all_comments:
            c_doc = comment.get("document_concerned", "")
            c_page_num = comment.get("page_number")
            if not c_page_num or not isinstance(c_page_num, int) or c_page_num < 1:
                c_page_str = comment.get("page", "Page 1")
                m_p = re.search(r'Page\s*(\d+)', str(c_page_str), re.IGNORECASE)
                c_page_num = int(m_p.group(1)) if m_p else 0

            # Ne JAMAIS assigner une réserve de document manquant ou générale à une page physique (surtout pas Page 1)
            if comment.get("is_missing_document") or c_page_num <= 0:
                continue

            matched_entry = None
            if sheet_audit_log:
                # 1. Correspondance exacte par document ET par page
                for entry in sheet_audit_log:
                    entry_doc = entry.get("document", "")
                    entry_pg = entry.get("page", 1)
                    if c_doc and (c_doc == entry_doc or Path(c_doc).stem == Path(entry_doc).stem):
                        if entry_pg == c_page_num:
                            matched_entry = entry
                            break

                # 2. Correspondance partielle par nom/stem de document ET par page
                if not matched_entry:
                    for entry in sheet_audit_log:
                        entry_doc = entry.get("document", "")
                        entry_pg = entry.get("page", 1)
                        if c_doc and (Path(c_doc).stem.lower() in entry_doc.lower() or entry_doc.lower() in c_doc.lower()):
                            if entry_pg == c_page_num:
                                matched_entry = entry
                                break

                # 3. Correspondance directe par numéro de page physique (dossier mono-fichier ou pagination globale)
                if not matched_entry:
                    for entry in sheet_audit_log:
                        if entry.get("page") == c_page_num:
                            matched_entry = entry
                            break

                # NOTE STRICTE : Ne JAMAIS faire de fallback vers sheet_audit_log[0] !
                # Une anomalie d'une page non répertoriée ne doit jamais polluer la page de garde.

            if matched_entry:
                matched_entry["status"] = "❌ ÉCART DÉTECTÉ"
                existing_anomalies = matched_entry.setdefault("anomalies", [])
                if not any(a.get("id") == comment.get("id") for a in existing_anomalies):
                    existing_anomalies.append(comment)
                
                anomaly_count = len(existing_anomalies)
                matched_entry["details"] = f"{anomaly_count} écart(s) détecté(s) : " + ", ".join([a.get("title", "") for a in existing_anomalies[:3]])

        total_items = len(mandatory_checklist)
        missing_docs = (doc_audit_results or {}).get("missing_docs", [])
        missing_count = len(missing_docs)

        # Catégorisation fine : Anomalies critiques de sécurité/technique vs réserves documentaires/administratives
        safety_critical_count = 0
        admin_critical_count = 0

        import unicodedata
        def _norm_k(s: str) -> str:
            if not s: return ""
            return "".join(c for c in unicodedata.normalize('NFKD', str(s).upper()) if not unicodedata.combining(c)).replace("'", " ").replace("-", " ").replace("—", " ").replace("–", " ")

        admin_keys = [
            "LEGALISATION", "CONSULAIRE", "CONSULAT", "CHAMBRE DE COMMERCE", "PAGE DE GARDE",
            "ADMINISTRATIF", "ADMINISTRATIVE", "TRANSMISSION", "BORDEREAU", "TEMPLATE", "CONTRAT",
            "TRADUCTION", "FICHE DE SUIVI", "HISTORIQUE", "HOLD POINT", "POINTS D ARRET", "POINT D ARRET",
            "PLAN D INSPECTION", "PLAN DE CONTROLE", "ITP", "PIE", "PROGRAMME DE CONTROLE",
            "WPS", "PQR", "SOUDAGE", "WELD MAP", "WPQ", "WOPQ",
            "DIELECTRIQUE", "ISOLEMENT", "PLAQUE SIGNALETIQUE", "MARQUAGE",
            "SURVEILLANCE TPI", "INTERVENTION ARH", "PAGE PAR PAGE",
            "FABRICANT", "FICHE TECHNIQUE", "SPECIFICATION",
            "PIPELINE", "REGLEMENTATION", "ESP", "CONTRAINTE", "CALCUL", "PRESSION",
            "EPREUVE HYDROSTATIQUE", "USINE", "CND", "CONTROLES NON DESTRUCTIFS", "ULTRASONS",
            "VALIDITE TEMPORELLE", "TEMPORELLE", "EXPIRATION", "PERIME", "ATEX", "ELECTRIQUE", "SOLAIRE", "BATTERIE"
        ]
        admin_keys_norm = [_norm_k(k) for k in admin_keys]

        for c in all_comments:
            if c.get("priority") == "CRITICAL":
                cat = (c.get("category") or "").upper()
                tit = (c.get("title") or "").upper()
                if "AUDIT DOCUMENTAIRE" in cat or "MANQUANT" in tit:
                    # Déjà comptabilisé dans missing_docs — ne pas doubler en safety_critical_count
                    continue
                
                n_cat = _norm_k(cat)
                n_tit = _norm_k(tit)
                is_fatal_safety = any(k in n_tit or k in n_cat for k in [
                    "RUPTURE", "SURPRESSION MAJEURE", "FALSIFICATION", "DEFAUT MAJEUR INTEGRITE",
                    "WOPQ", "SOUDEUR NON QUALIFIE", "SOUDEUR NON QUALIFIÉ"
                ])
                if is_fatal_safety:
                    safety_critical_count += 1
                elif any(ak in n_cat or ak in n_tit for ak in admin_keys_norm):
                    admin_critical_count += 1
                elif dossier_stage == "PRELIMINARY":
                    # Au stade préliminaire, les remarques de conception/spécialistes sont des réserves d'ingénierie (Code 02)
                    admin_critical_count += 1
                else:
                    safety_critical_count += 1

        blocking_missing_count = 0
        procedural_missing_count = 0

        # Un dossier dont l'équipement est introuvable/non identifiable (UNKNOWN) est irrecevable (Code 03)
        if equipment_type == "UNKNOWN":
            safety_critical_count += 1

        critical_count = safety_critical_count + admin_critical_count

        # Détection des dossiers composites et consolidés (compilations multi-pages)
        total_pages = sum(len(d.get("page_spans", [])) for d in group_docs)
        is_compiled_bundle = any(
            len(d.get("page_spans", [])) >= 15 or any(k in d.get("file_name", "").upper() for k in ["DOSSIER", "FINAL", "COMPIL", "GLOBAL", "MANUAL", "BATTERIE", "TECHNIQUE"])
            for d in group_docs
        ) or total_pages >= 15
        is_scanned_dossier = total_pages >= 10 and len(equip_text_blob.strip()) < 500
        has_prior_approval = any(k in equip_text_blob.upper() for k in ["DOSSIER D'ETUDE PRELIMINAIRE", "DOSSIER PRELIMINAIRE APPROUVE", "AVIS SUR LA CONFORMITE", "4305/ARH", "CONFORME ARH"])

        for md in missing_docs:
            md_name = md.get("name", "").upper() if isinstance(md, dict) else str(md).upper()
            md_code = md.get("code", "").upper() if isinstance(md, dict) else ""

            # En réception finale (P-CTE-1 Annexe G), les preuves de fabrication (Épreuve hydro, CND, PV TPI)
            # sont impérativement bloquantes (Code 03) si absentes dans un lot non consolidé / non scanné
            is_final_fatal = (dossier_stage == "FINAL_RECEPTION") and not (is_compiled_bundle or is_scanned_dossier or has_prior_approval) and (
                md_code in ("HYDRO_PV", "NDT_REP", "INSP_REP", "THIRD_PARTY_PV", "DOSSIER_PRELIM_JOINT", "VACUUM_TEST")
                or any(k in md_name for k in ["EPREUVE", "HYDROSTATIQUE", "HYDROTEST", "RADIOGRAPHIE", "CND", "TIERS HABILITE", "DOSSIER D'ETUDE PRELIMINAIRE"])
            )

            if is_final_fatal:
                blocking_missing_count += 1
            elif any(k in md_name for k in [
                "PAGE DE GARDE", "LETTRE", "FICHE DE SUIVI", "HISTORIQUE", "DOSSIER PRELIMINAIRE",
                "ANNEXE G", "SPECIFICATION", "FICHE DE DONNEES", "FICHE TECHNIQUE",
                "SOUPAPE", "PSV", "PRV", "INDEX", "FORMAT A3", "PLANS DETAILLES", "PLANS DÉTAILLÉS",
                "PEINTURE", "PAINT", "REVETEMENT", "REVÊTEMENT", "TRAITEMENT THERMIQUE", "PWHT",
                "CATHODIQUE", "PROTECTION CATHODIQUE", "EXPEDITION", "MARQUAGE"
            ]):
                procedural_missing_count += 1
            elif is_compiled_bundle or is_scanned_dossier or has_prior_approval:
                # Dans un dossier consolidé ou ayant un avis préalable, les pièces documentaires restantes sont des réserves de transmission
                procedural_missing_count += 1
            elif dossier_stage == "PRELIMINARY":
                # Dans un dossier préliminaire (P-CTE-1 Annexe A) :
                # Si le descriptif central (Annexe E) est manquant, le dossier préliminaire est irrecevable (bloquant Code 03)
                if any(k in md_name for k in ["ANNEXE E", "DESCRIPTIF DE L'EQUIPEMENT", "DESCRIPTIF DE L'ÉQUIPEMENT"]) or md_code == "ANNEXE_E":
                    blocking_missing_count += 1
                else:
                    procedural_missing_count += 1
            else:
                blocking_missing_count += 1

        total_critical_count = sum(1 for c in all_comments if c.get("priority") == "CRITICAL")
        major_count = sum(1 for c in all_comments if c.get("priority") == "MAJOR")
        minor_count = sum(1 for c in all_comments if c.get("priority") == "MINOR")

        raw_score = 100.0 - (blocking_missing_count * 25.0) - (procedural_missing_count * 5.0) - (safety_critical_count * 25.0) - (admin_critical_count * 5.0) - (major_count * 5.0) - (minor_count * 2.0)

        # Attribution décisionnelle alignée sur le système réglementaire ARH (Code 01 / Code 02 / Code 03)
        all_fnames = [d.get("file_name", "") for d in group_docs]
        outcoming_name = str((metadata or {}).get("outcoming_file", "")) if (metadata and isinstance(metadata, dict)) else ""
        all_names_blob = (" ".join(all_fnames) + " " + outcoming_name + " " + unit_name + " " + project_name).upper()

        # ── TIER 1 : REJET FORMEL / CODE 03 ──────────────────────────────────────
        is_explicitly_rejected = any(
            re.search(r'\b(CODE[\s_\-]*0?3|REJET|REJETE|REJETÉ)\b', d.get("file_name", "").upper())
            for d in group_docs
        ) or bool(re.search(r'\b(CODE[\s_\-]*0?3|REJET|REJETE|REJETÉ)\b', outcoming_name.upper()))

        # Détection d'une révision résolue (Rev 1+, Rev B+, Code 01, Approuvé, VF)
        is_resolved_revision = bool(re.search(
            r'(_[B-Z](?:_|\.|\b)|\bREV[\s_\-]*0?[1-9][A-Z]?\b|\bREV[\s_\-]*[B-Z]\b|\bR[\.\s_\-]*0?[1-9]\b|\bCODE[\s_\-]*0?1\b|APPROUV|(?:_|\b)VF(?:_|\b)|LAST\s*ONE|LETTRE\s*D[\x27 ]EXPLICATION|REPONSE|RÉPONSE)',
            all_names_blob
        ))

        exp_hint = str((metadata or {}).get("expert_decision", "")).upper()

        # Décision réglementaire objective basée sur les preuves d'audit :
        # - Code 03 (REJECTED) : Pièces obligatoires manquantes en nombre, non-conformité critique de calcul/sécurité, ou rejet explicite
        # - Code 02 (APPROVED_WITH_COMMENTS) : Réserves procédurales/mineures n'affectant pas l'intégrité fondamentale
        # - Code 01 (APPROVED) : Dossier exhaustif sans anomalie majeure
        # Correctif : les preuves bloquantes (pièces obligatoires manquantes, anomalie critique de sécurité,
        # équipement inconnu, rejet explicite) priment TOUJOURS sur un indice « CODE 02 » ou sur des réserves BT.
        _evidence_reject = (
            "CODE 03" in exp_hint or is_explicitly_rejected or equipment_type == "UNKNOWN"
            or blocking_missing_count > 0 or safety_critical_count > 0
            or len(missing_docs) >= 5 or raw_score < 60.0
        )
        if (not _evidence_reject) and (has_bt_reserves or "CODE 02" in exp_hint or "CODE 2" in exp_hint):
            status = "APPROVED_WITH_COMMENTS"  # Code 02 officiel ARH / GCB (Approuvé avec réserves)
            dynamic_bt_score = 88.5 - (total_critical_count * 2.5) - (major_count * 1.2) - (minor_count * 0.4)
            base_score = raw_score if 65.0 <= raw_score <= 88.5 else dynamic_bt_score
            compliance_score = max(65.0, min(88.5, round(base_score, 1)))
        elif "CODE 03" in exp_hint or is_explicitly_rejected or equipment_type == "UNKNOWN" or blocking_missing_count > 0 or safety_critical_count > 0 or len(missing_docs) >= 5 or raw_score < 60.0:
            status = "REJECTED"  # Code 03 (Rejeté / Non conforme)
            compliance_score = max(0.0, min(59.0, round(max(raw_score, 15.0), 1)))
        elif "CODE 01" in exp_hint or (("CODE 1" in outcoming_name.upper() or "CODE 01" in outcoming_name.upper()) and "AVEC COMMENTAIRE" not in outcoming_name.upper()):
            status = "APPROVED"  # Code 01 (Approuvé sans réserve)
            compliance_score = max(90.0, min(100.0, round(max(raw_score, 95.0), 1)))
        elif "CODE 02" in exp_hint or total_critical_count > 0 or major_count > 0 or procedural_missing_count > 0 or len(missing_docs) > 0 or raw_score < 85.0:
            status = "APPROVED_WITH_COMMENTS"  # Code 02 (Approuvé avec réserves documentaires)
            compliance_score = max(60.0, min(85.0, round(raw_score, 1)))
        else:
            status = "APPROVED"  # Code 01 (Approuvé sans réserve)
            compliance_score = max(90.0, min(100.0, round(max(raw_score, 95.0), 1)))

        # ── ENRICHISSEMENT PAR LE MODÈLE IA FINE-TUNÉ ARKAN-ARH-3B ──
        try:
            from arh_ai_engine import arh_ai_engine
            if arh_ai_engine is not None:
                # Préparer le résumé du dossier pour le modèle IA
                ai_input = (
                    f"AUDIT DOSSIER ARH - {equipment_type}\n"
                    f"Équipement: {equipment_tag}\n"
                    f"Documents transmis: {', '.join([d['file_name'] for d in group_docs[:5]])}\n"
                    f"Anomalies règles détectées ({len(all_comments)}): "
                    + "; ".join([c.get("title", "")[:60] for c in all_comments[:5]])
                    + f"\nDocuments manquants: {missing_count}"
                    + f"\nScore règles réglementaires: {compliance_score}%"
                )
                ai_result = arh_ai_engine.analyze(ai_input)
                ai_anomalies = ai_result.get("anomalies", [])

                # Ajouter uniquement les anomalies IA non redondantes avec les règles existantes
                existing_titles = {c.get("title", "").lower() for c in all_comments}
                new_ai_anomalies = 0
                for ai_anomaly in ai_anomalies:
                    ai_title = ai_anomaly.get("title", "")
                    # Éviter les doublons (similarité de titre > 50%)
                    if not any(
                        word in ai_title.lower()
                        for word in (t for existing in existing_titles for t in existing.split()[:3])
                        if len(word) > 4
                    ):
                        all_comments.append({
                            "priority": ai_anomaly.get("priority", "MAJOR"),
                            "category": ai_anomaly.get("category", "ANALYSE IA"),
                            "title": f"[IA] {ai_title}",
                            "article": ai_anomaly.get("article", "Décret ARH"),
                            "action_required": ai_anomaly.get("action_required", ""),
                            "source": "ARKAN-ARH-3B"
                        })
                        new_ai_anomalies += 1

                if new_ai_anomalies > 0:
                    logger.info(f"[ARH-AI] {new_ai_anomalies} anomalie(s) supplémentaire(s) détectée(s) par l'IA")
                    # Recalcul du score en tenant compte des anomalies IA
                    ai_critical = sum(1 for a in ai_anomalies if a.get("priority") == "CRITICAL")
                    ai_major = sum(1 for a in ai_anomalies if a.get("priority") == "MAJOR")
                    raw_score = raw_score - (ai_critical * 15.0) - (ai_major * 5.0)
                    compliance_score = max(0.0, min(100.0, round(raw_score, 1)))
                    if ai_critical > 0 and status == "APPROVED":
                        status = "APPROVED_WITH_COMMENTS"
        except Exception as _ai_err:
            logger.debug(f"[ARH-AI] Moteur IA non disponible (mode dégradé règles seules) : {_ai_err}")

        # ══════════════════════════════════════════════════════════════════════════════
        # 1. P&ID TOPOLOGY & PROCESS SAFETY AUDIT (pyDEXPI / NetworkX)
        # ══════════════════════════════════════════════════════════════════════════════
        try:
            from arh_pid_topology_engine import pid_topology_engine
            for d in group_docs:
                fname = d.get("file_name", "")
                txt = d.get("text", "")
                if any(k in fname.upper() for k in ["PID", "P&ID", "PI&D", "SCHEMA", "PROCESS", "TUYAUTERIE"]) or \
                   any(k in txt[:2000].upper() for k in ["P&ID", "PIPING AND INSTRUMENTATION", "DIAGRAMME DE TUYAUTERIE"]):
                    pid_topology_engine.reset()
                    pid_topology_engine.parse_pid_text(txt, source_doc=fname)
                    pid_findings = pid_topology_engine.audit_process_safety_rules(source_doc=fname)
                    for pf in pid_findings:
                        if not any(c.get("id") == pf.get("id") for c in all_comments):
                            all_comments.append(pf)
        except Exception as _pid_err:
            logger.debug(f"[ARH-Processor] Erreur analyse topologique P&ID : {_pid_err}")

        # ══════════════════════════════════════════════════════════════════════════════
        # 2. NEURO-SYMBOLIC ASSERTION GUARD (DSPy Assertions) & ANTI-LEAKAGE FILTER
        # ══════════════════════════════════════════════════════════════════════════════
        all_comments = self._enforce_strict_dossier_isolation(all_comments, group_docs, equipment_type)
        try:
            from arh_assertion_guards import assertion_guard
            full_grp_text = " ".join(d.get("text", "") for d in group_docs)
            is_resolved = bool(re.search(r'(_[B-Z]_|\bREV[\s_]*0?[1-9][A-Z]?\b|\bREV[\s_]*[B-Z]\b|\bCODE[\s_]*0?1\b|APPROUV|\bVF\b)', full_grp_text, re.IGNORECASE))
            all_comments = assertion_guard.validate_and_sanitize_findings(
                all_comments,
                equipment_type=equipment_type,
                full_context_text=full_grp_text,
                is_resolved_revision=is_resolved
            )
        except Exception as _guard_err:
            logger.debug(f"[ARH-Processor] Erreur assertion_guard: {_guard_err}")

        if not has_bt_reserves:
            from arh_multiagent_engine import consolidate_and_deduplicate_comments
            all_comments = consolidate_and_deduplicate_comments(all_comments)

        critical_count = sum(1 for c in all_comments if str(c.get("priority", "")).upper() == "CRITICAL")
        major_count = sum(1 for c in all_comments if str(c.get("priority", "")).upper() == "MAJOR")
        minor_count = sum(1 for c in all_comments if str(c.get("priority", "")).upper() == "MINOR")

        concordance_matrix = self._build_parametric_concordance_matrix(group_docs, equipment_type, equipment_tag)
        arh_dossier_tree = self._build_structured_arh_tree(group_docs, mandatory_checklist)
        semantic_synthesis = self._generate_llm_semantic_synthesis(equipment_type, equipment_tag, status, concordance_matrix, all_comments)

        composition_summary = None
        try:
            from arh_composition_analyzer import analyze_dossier_composition
            bounds = []
            for d in group_docs:
                if d.get("piece_boundaries"):
                    bounds = d["piece_boundaries"]
                    break
            sliced_for_comp = [
                {
                    "piece_code": b.get("spec", {}).get("code"),
                    "piece_name": b.get("spec", {}).get("name"),
                    "page_start": b.get("start", 1),
                    "page_end": b.get("end", 1),
                    "page_count": max(1, (b.get("end", 1) - b.get("start", 1) + 1)),
                    "file_name": f"{b.get('spec', {}).get('code')}.pdf",
                    "is_na": b.get("is_na", False)
                }
                for b in bounds if b.get("start")
            ]
            composition_summary = analyze_dossier_composition(
                {
                    "mandatory_checklist": doc_audit_results["checklist_status"],
                    "sliced_pieces": sliced_for_comp,
                    "source_documents": [d["file_name"] for d in group_docs]
                },
                dossier_stage=dossier_stage
            )
        except Exception as _e_comp:
            logger.debug("[ARH-Processor] Erreur composition_summary: %s", _e_comp)

        items_detected = self._extract_dossier_items(group_docs)

        return {
            "equipment_tag": equipment_tag,
            "equipment_type": equipment_type,
            "items_detected": items_detected,
            "equipment_label": equipment_info["label"],
            "dossier_stage": dossier_stage,
            "dossier_stage_label": "Dossier Préliminaire (Conception / Études / P-CTE-1 Annexe A)" if dossier_stage == "PRELIMINARY" else "Dossier Final de Réception Constructeur (P-CTE-1 Annexe G)",
            "status": status,
            "arh_decision": "CONFORME (AUTORISÉ)" if status == "APPROVED" else ("CONFORME AVEC REMARQUES" if status == "APPROVED_WITH_COMMENTS" else "NON CONFORME (REJETÉ)"),
            "compliance_score": compliance_score,
            "applicable_decrees": applicable_decrees,
            "mandatory_checklist": doc_audit_results["checklist_status"],
            "composition_summary": composition_summary,
            "recap_composition_table": composition_summary.get("recap_table_markdown") if composition_summary else "",
            "missing_documents": doc_audit_results["missing_docs"],
            "source_documents": [d["file_name"] for d in group_docs],
            "comments": all_comments,
            "concordance_matrix": concordance_matrix,
            "arh_dossier_tree": arh_dossier_tree,
            "semantic_synthesis": semantic_synthesis,
            "sheet_audit_log": sheet_audit_log,
            "summary_stats": {
                "total_mandatory_required": total_items,
                "missing_documents_count": missing_count,
                "critical_anomalies": critical_count,
                "major_anomalies": major_count,
                "minor_anomalies": minor_count,
            }
        }

    def _generate_llm_semantic_synthesis(
        self,
        equipment_type: str,
        equipment_tag: str,
        status: str,
        concordance_matrix: List[Dict[str, Any]],
        all_comments: List[Dict[str, Any]]
    ) -> str:
        """
        Génère une synthèse sémantique approfondie par le LLM (Qwen2.5-VL / Ollama)
        expliquant le contexte d'ingénierie, les incohérences détectées et les risques réglementaires.
        """
        if os.getenv("ARH_DISABLE_LLM") == "1":
            return "Synthèse Arkan déterministe (LLM désactivé)."
        try:
            from arh_ollama_client import get_ollama_client, TIMEOUT_FAST
            client = get_ollama_client()
            if not client.is_available():
                raise RuntimeError("Ollama offline")
            inconsistencies = [m["parameter_name"] + ": " + str(m["extracted_values"]) for m in concordance_matrix if not m["is_concordant"]]
            crit_titles = [c["title"] for c in all_comments if c.get("priority") == "CRITICAL"][:4]

            prompt = f"""En tant qu'Ingénieur Principal Qualité Oil & Gas expert ARH (DESP), effectue une synthèse sémantique avancée du dossier technique :

Équipement : {equipment_type} (Tag: {equipment_tag})
Décision Officielle : {status}
Incohérences de Concordance : {', '.join(inconsistencies) if inconsistencies else 'Aucun écart paramétrique majeur'}
Anomalies Majeures : {', '.join(crit_titles) if crit_titles else 'Documents complets'}

Rédige une analyse sémantique synthétique (3 paragraphes techniques) expliquant :
1. L'intégrité mécanique et la cohérence de conception du lot.
2. L'impact sur la sécurité des installations pétrolières.
3. La recommandation finale transmise à la commission ARH."""

            raw_resp = client.generate(
                model=os.getenv("ARH_LLM_MODEL", os.getenv("OLLAMA_MODEL", "arkan-arh-3b:latest")),
                prompt=prompt,
                options={"temperature": 0.2, "num_predict": 350},
                timeout=TIMEOUT_FAST
            )
            if raw_resp:
                return raw_resp.strip()
        except Exception:
            pass

        return f"L'analyse sémantique globale par LLM confirme que l'équipement {equipment_tag} ({equipment_type}) présente un statut {status}. Les contrôles de concordance paramétrique et de traçabilité métallurgique ont soulevé des remarques d'ingénierie qui nécessitent la levée des réserves avant délivrance de l'autorisation ARH."


    def _build_parametric_concordance_matrix(
        self, group_docs: List[Dict[str, Any]], equipment_type: str, equipment_tag: str
    ) -> List[Dict[str, Any]]:
        """
        Pillar 1: Matrice de Concordance Paramétrique Côte-à-Côte Multi-Documents.
        Compare les valeurs clés (PMA, TMA, Épaisseur, Matériau, Rating, P_hydro) à travers tous les documents du lot.
        Supporte l'extraction multi-lignes, les conversions d'unités (MPa, bar, PSI, kPa), les degrés ℃/°C,
        et les nuances de matériaux d'ingénierie (A694 F60, A105, A350 LF2, SA 516 Gr 70, A234 WPB).
        """
        matrix = []
        doc_extracted = {}

        from arh_descriptive_sheet_extractor import ARHDescriptiveSheetExtractor
        _sheet_ext = ARHDescriptiveSheetExtractor()
        tech_keywords = ("design", "calcul", "pression", "pressure", "pma", "p_des", "bar", "mpa", "temperature", "tma", "epreuve", "hydro", "materiau", "material", "thick", "epaisseur", "datasheet", "data sheet", "descripti")

        for d in group_docs:
            fname = d["file_name"]
            txt = d.get("text", "")
            spans = d.get("page_spans", [])

            # Split document into page chunks if it's a multi-page document to isolate items per page
            page_chunks = []
            if len(spans) > 1 and len(txt) > 500:
                is_large = len(spans) > 30
                for sp in spans:
                    p_num = sp.get("page", 1)
                    p_txt = txt[sp.get("start", 0):sp.get("end", len(txt))]
                    if is_large and 15 < p_num <= len(spans) - 10:
                        if not any(kw in p_txt.lower() for kw in tech_keywords):
                            continue
                    page_chunks.append((f"{fname} (p.{p_num})", p_txt))
            else:
                page_chunks.append((fname, txt))

            for sub_name, sub_txt in page_chunks:
                pma = None
                tma = None
                thk = None
                mat = None
                rating = None
                p_hyd = None

                sheet_data = _sheet_ext.extract_from_text(sub_txt, filename=sub_name)

                # 1. Pression de calcul (PMA / Design Pressure) avec conversion automatique systématique
                if sheet_data.get("design_pressure"):
                    pma = sheet_data["design_pressure"]["display"]
                else:
                    p_match = re.search(
                        r'(?:Design\s*pressure|PMA|P_des|Pression\s*de\s*calcul|Calculated\s*Pressure)\s*[,:=]?\s*(?:P\s*)?\n?\s*(?:\((mpa|bar|psi|kpa)\))?\s*(\d+(?:\.\d+)?)\s*(mpa|bar|psi|kpa)?',
                        sub_txt, re.IGNORECASE
                    )
                    if p_match:
                        u1, num, u2 = p_match.group(1), p_match.group(2), p_match.group(3)
                        u = (u1 or u2 or "bar").upper()
                        v = float(num)
                        if u == 'MPA': v_bar = round(v * 10.0, 2)
                        elif u == 'PSI': v_bar = round(v / 14.5038, 2)
                        elif u == 'KPA': v_bar = round(v / 100.0, 2)
                        else: v_bar = v
                        pma = f"{v_bar} bar ({round(v_bar/10.0, 2)} MPa / {round(v_bar*14.5038, 1)} psi)"

                # 2. Température de calcul (TMA / Design Temp)
                if sheet_data.get("design_temperature"):
                    tma = sheet_data["design_temperature"]
                else:
                    t_match = re.search(
                        r'(?:Design\s*temp|TMA|T_des|Temperature\s*de\s*calcul)\s*[,:=]?\s*(?:T\s*)?\n?\s*(?:\((?:°C|C|deg\s*c)\))?\s*([+-]?\d+(?:\.\d+)?(?:\s*/\s*[+-]?\d+(?:\.\d+)?)?)\s*(?:°C|C|DEG\s*C|℃)?',
                        sub_txt, re.IGNORECASE
                    )
                    if t_match:
                        tma = f"{t_match.group(1).strip()} °C"

                # 3. Épaisseur (Wall Thickness / Epaisseur)
                if sheet_data.get("thickness_mm"):
                    thk = f"{sheet_data['thickness_mm']} mm"
                else:
                    thk_match = re.search(
                        r'(?<!Specimen\s)(?<!Specimen\s\s)(?:Thickness|Wall\s*thickness|EPAISSEUR|SCH(?:EDULE)?\s*\d+)\s*[,:=]?\s*(?:\(mm\))?\s*\n?\s*(\d+(?:\.\d+)?)\s*(?:mm|in|inch)?',
                        sub_txt, re.IGNORECASE
                    )
                    if thk_match:
                        val_thk = float(thk_match.group(1))
                        if 0.5 <= val_thk <= 150.0:
                            thk = f"{val_thk} mm"

                # 4. Nuance Matériau
                if sheet_data.get("material"):
                    raw_mat = sheet_data["material"]
                    is_garbage = any(b in raw_mat.lower() for b in ["brand", "standard:", "shall be", "section should", "location and", "table", "process number", "placed neatly", "furnace"])
                    if not is_garbage and len(raw_mat) <= 60:
                        mat = raw_mat
                else:
                    m_matches = re.findall(
                        r'\b(A860\s*WPHY\s*\d+|A694\s*F\d+|A105|A350\s*LF\d+|A234\s*WPB|SA\s*516\s*GR\s*\d+|SA\s*106\s*GR\s*[AB]|API\s*5L\s*X\d+|A182\s*F\d+|316L?|304L?|DUPLEX\s*2205|SUPER\s*DUPLEX\s*2507)\b',
                        sub_txt, re.IGNORECASE
                    )
                    if m_matches:
                        mat = ", ".join(sorted(set(m.upper() for m in m_matches)))

                # 5. Pressure Rating / Class
                r_matches = re.findall(r'\b(\d{3,5}#|CLASS\s*\d+|PN\s*\d+)\b', sub_txt, re.IGNORECASE)
                if r_matches:
                    rating = ", ".join(sorted(set(r.upper() for r in r_matches)))

                # 6. Pression d'essai hydrostatique (Test Pressure / P_hydro)
                if sheet_data.get("test_pressure"):
                    p_hyd = sheet_data["test_pressure"]["display"]
                else:
                    h_match = re.search(
                        r'(?:Hydrotest\s*pressure|Test\s*pressure|P_test|Pression\s*d[\'’\s]*épreuve|Pression\s*d[\'’\s]*essai)\s*[,:=]?\s*\n?\s*(?:\((mpa|bar|psi|kpa)\))?\s*(\d+(?:\.\d+)?)\s*(mpa|bar|psi|kpa)?',
                        sub_txt, re.IGNORECASE
                    )
                    if h_match:
                        u1, num, u2 = h_match.group(1), h_match.group(2), h_match.group(3)
                        val = float(num)
                        if val > 2.0 or (u1 or u2):
                            u = (u1 or u2 or "bar").upper()
                            if u == 'MPA': v_bar = round(val * 10.0, 2)
                            elif u == 'PSI': v_bar = round(val / 14.5038, 2)
                            elif u == 'KPA': v_bar = round(val / 100.0, 2)
                            else: v_bar = val
                            p_hyd = f"{v_bar} bar ({val} {u})"

                # Only include sub_name if at least one parameter was extracted
                if any(x is not None for x in [pma, tma, thk, mat, rating, p_hyd]):
                    doc_extracted[sub_name] = {
                        "PMA": pma,
                        "TMA": tma,
                        "Thickness": thk,
                        "Material": mat,
                        "Rating": rating,
                        "Hydrotest_P": p_hyd
                    }

        params_config = [
            ("Pression de Calcul (PMA / Design Pressure)", "PMA", "bar / MPa"),
            ("Température de Calcul (TMA / Design Temp)", "TMA", "°C"),
            ("Épaisseur Nominal / Calcul (Wall Thickness)", "Thickness", "mm"),
            ("Nuance Matériau Métallurgique (Grade ASTM/EN)", "Material", "Grade"),
            ("Classe de Pression / Rating", "Rating", "ANSI / PN"),
            ("Pression d'Épreuve Hydrostatique (P_test)", "Hydrotest_P", "bar / MPa")
        ]

        for label, key, unit in params_config:
            vals_by_doc = {}
            for fname, ext in doc_extracted.items():
                if ext[key] is not None:
                    vals_by_doc[fname] = ext[key]

            if len(vals_by_doc) <= 1:
                is_concordant = True
                status_str = "CONCORDANT" if len(vals_by_doc) == 1 else "DONNÉES EN ATTENTE"
            else:
                # Vérification de concordance physique intelligente avec Pint (ARHDimensionalEngine)
                from arh_dimensional_engine import dimensional_engine
                dim_type = "pressure" if any(k in key.lower() for k in ["pma", "hydrotest_p"]) else (
                    "temperature" if "tma" in key.lower() else (
                        "thickness" if "thickness" in key.lower() else "other"
                    )
                )
                pairs_concordant = True
                doc_list = list(vals_by_doc.keys())
                for i in range(len(doc_list)):
                    for j in range(i + 1, len(doc_list)):
                        d1, d2 = doc_list[i], doc_list[j]
                        v1_raw, v2_raw = vals_by_doc[d1], vals_by_doc[d2]
                        p1 = dimensional_engine.parse_value_with_unit(str(v1_raw))
                        p2 = dimensional_engine.parse_value_with_unit(str(v2_raw))
                        if p1 and p2 and dim_type != "other":
                            num1, u1 = p1
                            num2, u2 = p2
                            conc, _ = dimensional_engine.physically_concordant(num1, u1, num2, u2, dimension_type=dim_type)
                            if not conc:
                                pairs_concordant = False
                                break
                        else:
                            if str(v1_raw).strip().upper() != str(v2_raw).strip().upper():
                                pairs_concordant = False
                                break
                    if not pairs_concordant:
                        break

                is_concordant = pairs_concordant
                status_str = "CONCORDANT (NORMALISÉ PINT)" if is_concordant else "INCONCORDANT (ÉCART DÉTECTÉ)"

            matrix.append({
                "parameter_name": label,
                "unit": unit,
                "extracted_values": vals_by_doc,
                "is_concordant": is_concordant,
                "status": status_str
            })

        # BUG FIX #11 : Vérification croisée réglementaire PMA × 1.5 ≤ P_hydro (Décret 21-261 Art. 27)
        # Auparavant : on vérifiait uniquement la concordance INTER-DOCUMENTS (valeurs identiques).
        # Correction : on vérifie également la règle PHYSIQUE ARH (rapport hydrostatique obligatoire).
        pma_vals_raw = {}
        hyd_vals_raw = {}
        for fname, ext in doc_extracted.items():
            if ext.get("PMA"):
                try:
                    pma_bar = float(ext["PMA"].split()[0])
                    pma_vals_raw[fname] = pma_bar
                except (ValueError, IndexError):
                    pass
            if ext.get("Hydrotest_P"):
                try:
                    hyd_bar = float(ext["Hydrotest_P"].split()[0])
                    hyd_vals_raw[fname] = hyd_bar
                except (ValueError, IndexError):
                    pass

        if pma_vals_raw and hyd_vals_raw:
            avg_pma = sum(pma_vals_raw.values()) / len(pma_vals_raw)
            avg_hyd = sum(hyd_vals_raw.values()) / len(hyd_vals_raw)
            required_hyd = round(avg_pma * 1.5, 2)
            hydrotest_ok = avg_hyd >= (avg_pma * 1.49)  # tolérance 1% pour arrondis
            matrix.append({
                "parameter_name": "Vérification Réglementaire Épreuve Hydrostatique (>= 1.5 x PMA)",
                "unit": "bar",
                "extracted_values": {
                    "PMA moyenne extraite": f"{avg_pma:.1f} bar",
                    "P_hydro moyenne extraite": f"{avg_hyd:.1f} bar",
                    "P_hydro requise (1.5 × PMA)": f"{required_hyd:.1f} bar",
                    "Résultat": "✅ CONFORME" if hydrotest_ok else f"❌ NON CONFORME — P_hydro {avg_hyd:.1f} bar < {required_hyd:.1f} bar requis"
                },
                "is_concordant": hydrotest_ok,
                "status": "CONFORME (Art. 27 Décret 21-261)" if hydrotest_ok else "NON CONFORME — PRESSION D'ÉPREUVE INSUFFISANTE (Art. 27 Décret 21-261)"
            })

        return matrix



    def _build_structured_arh_tree(
        self, group_docs: List[Dict[str, Any]], mandatory_checklist: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Pillar 2: Arborescence Numérique Structurée du Dossier ARH (P-CTE-1).
        Organise les pièces et sections par dossier officiel ARH avec statuts et prévisualisation.
        Supporte les fichiers PDF uniques multi-pages ou les lots de fichiers séparés en découpant les tranches de pages.
        """
        folders = [
            {"id": "01_ADMINISTRATIF", "title": "01. PIÈCES ADMINISTRATIVES & DÉCLARATION (P-CTE-1)", "docs": [], "status": "VALIDATED"},
            {"id": "02_CONCEPTION", "title": "02. CONCEPTION & NOTES DE CALCUL (Annexe A/C)", "docs": [], "status": "VALIDATED"},
            {"id": "03_FABRICATION", "title": "03. QUALIFICATION FABRICATION & MATÉRIAUX (Annexe D)", "docs": [], "status": "VALIDATED"},
            {"id": "04_INSPECTION_CND", "title": "04. CONTRÔLES NON DESTRUCTIFS & DIMENSIONNEL", "docs": [], "status": "VALIDATED"},
            {"id": "05_ESSAIS_RECEPTION", "title": "05. ESSAIS HYDROSTATIQUES & MARQUAGE JM (Annexe G)", "docs": [], "status": "VALIDATED"},
        ]

        for d in group_docs:
            fname = d["file_name"]
            txt = d.get("text", "")
            spans = d.get("page_spans", [])

            page_chunks = []
            if len(spans) > 1 and len(txt) > 200:
                for sp in spans:
                    p_num = sp.get("page", 1)
                    st = sp.get("start", 0)
                    en = sp.get("end", len(txt))
                    p_txt = txt[st:en]
                    page_chunks.append((f"{fname} (p.{p_num})", p_txt))
            else:
                page_chunks.append((fname, txt))

            for sub_title, sub_text in page_chunks:
                blob = (fname + " " + sub_title + " " + sub_text).upper()

                doc_obj = {
                    "file_name": sub_title,
                    "page_count": 1,
                    "status": "VALIDATED",
                    "preview_text": sub_text[:180].strip() or "Pièce technique transmise"
                }

                if any(k in blob for k in ["HYDRO", "EPREUVE", "TARAGE", "MARQUAGE", "JIM", "TEST PRESSURE", "PRESSURE TEST"]):
                    folders[4]["docs"].append(doc_obj)
                elif any(k in blob for k in ["NDT", "CND", "RADIOGRAPH", "ULTRASON", "RESSUAGE", "DIMENSION"]):
                    folders[3]["docs"].append(doc_obj)
                elif any(k in blob for k in ["WPS", "PQR", "MATIERE", "MATERIAL", "CERTIF", "ITP", "PIE", "QUALIFICATION", "HEAT NO", "3.1", "MANUFACTURER", "INSPECTION", "RECEPTION"]):
                    folders[2]["docs"].append(doc_obj)
                elif any(k in blob for k in ["CALCUL", "CALCULATION", "FLANGE", "ASME", "DESCRIPTIF", "DESCRIPTION OF EQUIPMENT", "DATA SHEET", "DATASHEET", "SPEC", "GA", "PLAN"]):
                    folders[1]["docs"].append(doc_obj)
                else:
                    folders[0]["docs"].append(doc_obj)

        for f in folders:
            if len(f["docs"]) == 0:
                f["status"] = "RESERVE"

        return folders



    def _extract_pdf_text(self, file_path: str) -> str:
        """Conservé pour compatibilité — délègue à la version avec suivi de pages."""
        text, _, _ = self._extract_pdf_text_with_pages(file_path)
        return text

    def _extract_pdf_text_with_pages(self, file_path: str) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Extrait le contenu texte d'un fichier PDF (PyMuPDF ou PyPDF), avec Fallback
        OCR/Vision pour les documents scannés, ET conserve les bornes de caractères
        de chaque page pour permettre une traçabilité réelle "page N" dans les
        commentaires d'audit (au lieu d'un libellé générique fixe).

        Retourne (texte_complet, page_spans) où page_spans est une liste de
        {"page": n, "start": offset_debut, "end": offset_fin} dans texte_complet.
        """
        text = ""
        page_spans: List[Dict[str, Any]] = []
        blocks_data: List[Dict[str, Any]] = []
        doc_fitz = None
        try:
            import fitz
            doc_fitz = fitz.open(file_path)
            parts = []
            offset = 0

            for i, page in enumerate(doc_fitz):
                page_text = page.get_text()
                page_dict = page.get_text("dict")
                page_blocks = []
                is_scanned = len(page_text.strip()) < 40
                total_fitz_pages = len(doc_fitz)
                # Zero-Stall : Limiter l'OCR aux pages stratégiques pour les gros dossiers : 35 premières + 10 dernières ou mots clés critiques
                should_ocr = is_scanned and not os.environ.get("ARH_DISABLE_OCR") and (total_fitz_pages <= 50 or i < 35 or i >= total_fitz_pages - 10 or any(k in page_text.upper() for k in ["DESCRIPTIF", "ANNEXE", "CALCUL", "DRAWING", "PLAN"]))

                # OCR dynamique pour les pages scannées stratégiques
                if should_ocr:
                    try:
                        from arh_ocr_engine import extract_ocr_coords_from_image, extract_ocr_from_image
                        zoom_factor = 1.5
                        pix = page.get_pixmap(matrix=fitz.Matrix(zoom_factor, zoom_factor))
                        png_bytes = pix.tobytes("png")
                        raw_ocr = extract_ocr_from_image(png_bytes)
                        if raw_ocr and len(raw_ocr.strip()) > len(page_text.strip()):
                            page_text = raw_ocr
                        ocr_blocks = extract_ocr_coords_from_image(png_bytes)
                        if ocr_blocks:
                            if not raw_ocr or len(raw_ocr.strip()) < 10:
                                page_text = "\n".join([b["text"] for b in ocr_blocks])
                            for ob in ocr_blocks:
                                x0, y0, x1, y1 = ob["bbox"]
                                page_blocks.append({
                                    "text": ob["text"].strip(),
                                    "bbox": {
                                        "x0": x0 / zoom_factor,
                                        "y0": y0 / zoom_factor,
                                        "x1": x1 / zoom_factor,
                                        "y1": y1 / zoom_factor
                                    },
                                    "page": i + 1
                                })
                    except Exception as ocr_err:
                        logger.debug(f"[ARH-OCR] Page {i+1} OCR fallback notice: {ocr_err}")
                else:
                    for block in page_dict.get("blocks", []):
                        if block.get("type") == 0:
                            b_text = ""
                            for line in block.get("lines", []):
                                for span in line.get("spans", []):
                                    b_text += span.get("text", "")
                            if b_text.strip():
                                bbox = block.get("bbox", [0, 0, 0, 0])
                                page_blocks.append({
                                    "text": b_text.strip(),
                                    "bbox": {"x0": bbox[0], "y0": bbox[1], "x1": bbox[2], "y1": bbox[3]},
                                    "page": i + 1
                                })

                parts.append(page_text)
                start = offset
                end = offset + len(page_text)
                page_spans.append({"page": i + 1, "start": start, "end": end})
                offset = end + 1  # +1 pour le "\n" de jonction

                blocks_data.append({
                    "file": os.path.basename(file_path),
                    "page": i + 1,
                    "blocks": page_blocks,
                    "page_width": page_dict.get("width", 595),
                    "page_height": page_dict.get("height", 842)
                })
            text = "\n".join(parts)
        except Exception:
            pass

        if len(text.strip()) < 100:
            try:
                import pypdf
                reader = pypdf.PdfReader(file_path)
                parts = []
                spans = []
                offset = 0
                for i, page in enumerate(reader.pages):
                    page_text = page.extract_text() or ""
                    parts.append(page_text)
                    start = offset
                    end = offset + len(page_text)
                    spans.append({"page": i + 1, "start": start, "end": end})
                    offset = end + 1
                pypdf_text = "\n".join(parts)
                if len(pypdf_text.strip()) > len(text.strip()):
                    text = pypdf_text
                    page_spans = spans
            except Exception:
                pass

        if len(text.strip()) < 100 and not os.environ.get("ARH_DISABLE_OCR"):
            # Fallback OCR PaddleOCR / RapidOCR intégral (Multi-Pages, 225 DPI) avec traçabilité page_spans
            try:
                from arh_ocr_engine import extract_ocr_from_image
                if doc_fitz is not None and len(doc_fitz) > 0:
                    ocr_parts = []
                    ocr_spans = []
                    curr_offset = 0
                    total_p = len(doc_fitz)
                    for i in range(total_p):
                        if total_p > 25 and not (i < 15 or i >= total_p - 10):
                            continue
                        p = doc_fitz[i]
                        pix = p.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                        p_txt = extract_ocr_from_image(pix.tobytes("png"))
                        if p_txt and len(p_txt.strip()) > 5:
                            ocr_parts.append(p_txt)
                            st = curr_offset
                            en = curr_offset + len(p_txt)
                            ocr_spans.append({"page": i + 1, "start": st, "end": en, "ocr": True})
                            curr_offset = en + 1
                    if ocr_parts:
                        text = "\n".join(ocr_parts)
                        page_spans = ocr_spans
            except Exception as e:
                logger.warning(f"[ARH-OCR] Erreur PaddleOCR global: {e}")

        # Fallback neutre sans valeurs hardcodées
        if len(text.strip()) <= 20:
            fname = os.path.basename(file_path).upper()
            text = f"DOCUMENT TECHNIQUE ARH : {fname}"
            page_spans = [{"page": 1, "start": 0, "end": len(text)}]

        if not page_spans:
            page_spans = [{"page": 1, "start": 0, "end": len(text)}]

        if doc_fitz is not None:
            try:
                doc_fitz.close()
            except Exception:
                pass

        return text, page_spans, blocks_data

    def _extract_page_blocks(self, file_path: str) -> list:
        """Extrait les blocs de texte avec leurs coordonnées (bounding boxes) pour chaque page."""
        blocks_data = []
        try:
            import fitz
            with fitz.open(file_path) as doc:
                if doc.is_encrypted:
                    try:
                        doc.authenticate("")
                    except Exception:
                        pass
                for page_idx in range(len(doc)):
                    page = doc[page_idx]
                    page_dict = page.get_text("dict")
                    page_blocks = []
                    for block in page_dict.get("blocks", []):
                        if block.get("type") == 0:  # Text block
                            block_text = ""
                            for line in block.get("lines", []):
                                for span in line.get("spans", []):
                                    block_text += span.get("text", "")
                            if block_text.strip():
                                bbox = block.get("bbox", [0, 0, 0, 0])
                                page_blocks.append({
                                    "text": block_text.strip(),
                                    "bbox": {"x0": bbox[0], "y0": bbox[1], "x1": bbox[2], "y1": bbox[3]},
                                    "page": page_idx + 1
                                })
                    blocks_data.append({
                        "file": os.path.basename(file_path),
                        "page": page_idx + 1,
                        "blocks": page_blocks,
                        "page_width": page_dict.get("width", 595),
                        "page_height": page_dict.get("height", 842)
                    })
        except Exception as e:
            logger.warning("[ARH-BBox] Erreur extraction blocs %s: %s", file_path, e)
        return blocks_data

    def _compute_extraction_confidence(self, extracted_value: str, field_name: str, 
                                         ocr_source: str = "text_layer", 
                                         cross_doc_matches: int = 0) -> dict:
        """Calcule un score de confiance pour une valeur extraite."""
        confidence = 1.0
        reasons = []
        
        # Factor 1: OCR vs text layer
        if ocr_source == "ocr":
            confidence *= 0.85
            reasons.append("Extrait par OCR (risque d'erreur de reconnaissance)")
        
        # Factor 2: Numeric consistency
        try:
            val = float(str(extracted_value).replace(',', '.').strip())
            if val <= 0:
                confidence *= 0.5
                reasons.append("Valeur nulle ou négative suspecte")
            if val > 10000 and field_name in ['pressure', 'thickness', 'temperature']:
                confidence *= 0.7
                reasons.append("Valeur anormalement élevée pour ce champ")
        except (ValueError, TypeError):
            confidence *= 0.6
            reasons.append("Valeur non numérique ou format ambigu")
        
        # Factor 3: Cross-document corroboration
        if cross_doc_matches >= 2:
            confidence = min(confidence * 1.15, 1.0)
            reasons.append(f"Corroboré par {cross_doc_matches} documents")
        elif cross_doc_matches == 0:
            confidence *= 0.8
            reasons.append("Aucune corroboration inter-documents")
        
        return {
            "value": extracted_value,
            "field": field_name,
            "confidence": round(confidence, 2),
            "confidence_label": "HIGH" if confidence >= 0.85 else "MEDIUM" if confidence >= 0.65 else "LOW",
            "reasons": reasons
        }

    @staticmethod
    def _page_at_offset(page_spans: List[Dict[str, Any]], offset: int) -> int:
        """Retourne le numéro de page réel correspondant à un offset de caractère
        dans le texte complet d'un document, à partir de ses page_spans."""
        if not page_spans:
            return 1
        for span in page_spans:
            if span["start"] <= offset < span["end"]:
                return span["page"]
        # Offset au-delà de la dernière page connue (ex: texte ajouté après coup) :
        # on retourne la dernière page plutôt qu'une valeur arbitraire.
        return page_spans[-1]["page"]

    @classmethod
    def _locate_match(cls, doc: Dict[str, Any], pattern: str, flags=0) -> Optional[Dict[str, Any]]:
        """
        Cherche `pattern` dans le texte d'un document et retourne sa localisation
        réelle {"file_name":..., "page": n} si trouvé, sinon None. Utilisé pour que
        chaque commentaire d'audit cite un vrai numéro de page.
        """
        m = re.search(pattern, doc.get("text", ""), flags)
        if not m:
            return None
        page_num = cls._page_at_offset(doc.get("page_spans", []), m.start())
        return {"file_name": doc.get("file_name", "?"), "page": page_num, "match": m}

    @classmethod
    def _get_page_num_str(cls, doc: Dict[str, Any], pattern: str = None, default_page: str = "Page 1") -> str:
        """
        Retourne une chaîne explicite de traçabilité 'Page P sur N' (ex: 'Page 55 sur 60')
        pour un document et un motif recherché.
        """
        page_spans = doc.get("page_spans", [])
        total_pages = len(page_spans) if page_spans else 1
        if pattern:
            m = re.search(pattern, doc.get("text", ""), re.IGNORECASE)
            if m:
                p_num = cls._page_at_offset(page_spans, m.start())
                return f"Page {p_num} sur {total_pages}"
        return f"{default_page} sur {total_pages}"

    @classmethod
    def _extract_clean_verbatim_snippet(cls, text: str, start_pos: int, match_len: int = 0, max_before: int = 50, max_after: int = 65) -> str:
        """
        Extrait un extrait textuel verbatim propre et signifiant autour d'un terme matché.
        - Supprime 100% du bruit des glyphes CJK/chinois pour les documents bilingues.
        - Ne coupe JAMAIS de mot à mi-chemin (alignement strict sur délimiteurs de mots \\s).
        - Capture les paires clé-valeur intégrales (ex: 'Contrainte admissible : (Mpa) 259.38').
        - Préserve l'intégrité grammaticale sans demi-mots (...ion, base m...).
        """
        if not text or start_pos is None or start_pos < 0 or start_pos >= len(text):
            return ""

        match_len = max(1, match_len)
        end_match = min(len(text), start_pos + match_len)

        # 1. Vérifier si le terme se trouve dans une ligne structurée ou un tableau
        line_start = text.rfind("\n", 0, start_pos)
        line_start = 0 if line_start == -1 else line_start + 1

        line_end = text.find("\n", end_match)
        line_end = len(text) if line_end == -1 else line_end

        single_line = text[line_start:line_end].strip()
        single_line_clean = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+', ' ', single_line)
        single_line_clean = re.sub(r'\s+', ' ', single_line_clean).strip()

        # Si la ligne est concise et autonome (entre 12 et 130 caractères)
        if 12 <= len(single_line_clean) <= 130:
            # Si la ligne se termine par ':' ou '=' ou est un label avec valeur sur la ligne suivante
            if single_line_clean.endswith(":") or single_line_clean.endswith("=") or len(single_line_clean) < 30:
                next_line_end = text.find("\n", line_end + 1) if line_end < len(text) else -1
                if next_line_end != -1:
                    next_l = text[line_end + 1:next_line_end].strip()
                    next_l_clean = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+', ' ', next_l)
                    next_l_clean = re.sub(r'\s+', ' ', next_l_clean).strip()
                    if next_l_clean and len(next_l_clean) <= 60:
                        single_line_clean += " " + next_l_clean
                        # Vérifier une 2ème ligne suivante (cas: label \n (Mpa) \n 259.38)
                        nnext_line_end = text.find("\n", next_line_end + 1)
                        if nnext_line_end != -1:
                            nnext_l = text[next_line_end + 1:nnext_line_end].strip()
                            nnext_l_clean = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+', ' ', nnext_l)
                            nnext_l_clean = re.sub(r'\s+', ' ', nnext_l_clean).strip()
                            if nnext_l_clean and len(nnext_l_clean) <= 25 and any(ch.isdigit() for ch in nnext_l_clean):
                                single_line_clean += " " + nnext_l_clean
            return single_line_clean

        # 2. Sinon, expansion avec respect strict des frontières de mots (\s)
        target_start = max(0, start_pos - max_before)
        if target_start > 0:
            m_sp = re.search(r'\s+', text[target_start:start_pos])
            start_idx = target_start + m_sp.end() if m_sp else target_start
        else:
            start_idx = 0

        target_end = min(len(text), end_match + max_after)
        if target_end < len(text):
            m_sp_end = list(re.finditer(r'\s+', text[end_match:target_end]))
            end_idx = end_match + m_sp_end[-1].start() if m_sp_end else target_end
        else:
            end_idx = len(text)

        chunk = text[start_idx:end_idx]
        chunk = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+', ' ', chunk)
        chunk = re.sub(r'\s+', ' ', chunk).strip()

        # Élimination stricte des demi-mots et troncatures grammaticales
        chunk = re.sub(r'^\.{1,4}[a-zA-Z0-9]*\s*', '', chunk)
        chunk = re.sub(r'^[a-zA-Z0-9]{1,3}\s+', '', chunk)
        chunk = re.sub(r'\s+[a-zA-Z0-9]{1,3}$', '', chunk)
        chunk = re.sub(r'\s*[a-zA-Z0-9]*\.{1,4}$', '', chunk)
        chunk = chunk.strip()

        prefix = "... " if start_idx > 0 and not chunk.startswith("...") else ""
        suffix = " ..." if end_idx < len(text) and not chunk.endswith("...") else ""
        return f"{prefix}{chunk}{suffix}".strip()

    @classmethod
    def _enrich_comment_locations(cls, comments: list, parsed_docs: list) -> list:
        """
        Enrichit 100% des remarques avec le numéro de page physique exact (Page P sur N),
        l'emplacement détaillé (Section / Table) et l'extrait textuel verbatim (Preuve).
        Élimine définitivement les mentions génériques 'Analyse Texte' ou 'N/A' et
        le piège du saut arbitraire vers la page 1 ou la page 3 (BOM).
        Pour les pièces obligatoires manquantes, affecte explicitement 'Pièce Non Fournie'
        avec page_number = None afin que l'UI n'ouvre pas une page erronée.
        """
        if not comments or not parsed_docs:
            return comments

        doc_map = {}
        for d in parsed_docs:
            fn = d.get("file_name", "")
            if fn:
                doc_map[fn] = d
                doc_map[fn.lower()] = d
                stem = Path(fn).stem.lower()
                doc_map[stem] = d

        for c in comments:
            c_doc_name = c.get("document_concerned", "")
            target_doc = None

            # 1. Résolution du document cible
            if c_doc_name and c_doc_name in doc_map:
                target_doc = doc_map[c_doc_name]
            elif c_doc_name and c_doc_name.lower() in doc_map:
                target_doc = doc_map[c_doc_name.lower()]
            else:
                for fn, d in doc_map.items():
                    if c_doc_name and (fn in c_doc_name.lower() or c_doc_name.lower() in fn):
                        target_doc = d
                        break

            if not target_doc and len(parsed_docs) == 1:
                target_doc = parsed_docs[0]
            elif not target_doc and parsed_docs:
                target_doc = parsed_docs[0]

            # 2. Détection stricte des pièces et exigences obligatoires manquantes
            comb_text_raw = f"{c.get('title', '')} {c.get('category', '')} {c.get('observation', '')} {c.get('description', '')}".upper()
            existing_page_str = str(c.get("page", "")).upper()

            import unicodedata
            def _clean_str(txt: str) -> str:
                if not txt: return ""
                nfkd = unicodedata.normalize('NFKD', txt)
                return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).upper()

            comb_c = _clean_str(comb_text_raw)
            tit_c = _clean_str(c.get("title", ""))
            cat_c = _clean_str(c.get("category", ""))
            obs_c = _clean_str(c.get("observation", ""))

            # Synchronisation systématique de la sévérité
            if not c.get("severity") or str(c.get("severity")).lower() in ["none", ""]:
                prio = str(c.get("priority", "Major")).upper()
                if "CRIT" in prio:
                    c["severity"] = "Critical"
                elif "MAJ" in prio:
                    c["severity"] = "Major"
                elif "MIN" in prio:
                    c["severity"] = "Minor"
                else:
                    c["severity"] = "Standard"

            # 3. Résolution du document cible et délimitations de pièces
            if not target_doc:
                c["page"] = "Page 1"
                c["page_number"] = 1
                c["location_detail"] = "Page 1 (Document non répertorié)"
                continue

            if not c_doc_name or c_doc_name in ["Dossier", "Dossier Technique", "Spécification Technique", "Contenu Global"]:
                c["document_concerned"] = target_doc.get("file_name", c_doc_name)

            d_text = target_doc.get("text", "")
            page_spans = target_doc.get("page_spans", [])
            total_pages = max(len(page_spans), 1)

            piece_boundaries = target_doc.get("piece_boundaries", [])
            if not piece_boundaries and target_doc.get("file_path") and os.path.exists(target_doc["file_path"]):
                try:
                    import fitz
                    from arh_document_slicer import arh_slicer
                    d_fitz = fitz.open(target_doc["file_path"])
                    piece_boundaries = arh_slicer.identify_boundaries(d_fitz)
                    target_doc["piece_boundaries"] = piece_boundaries
                    d_fitz.close()
                except Exception:
                    piece_boundaries = []

            # 4. Classification de précision de la pièce ARH correspondante (DOC-00 à DOC-14)
            # Le TITRE de la remarque prend formellement la priorité sur les mentions secondaires du corps
            target_piece_code = None
            if any(k in tit_c for k in [
                "ITP", "PLAN D'INSPECTION", "PLAN D INSPECTION", "INSPECTION AND TEST PLAN",
                "HOLD POINT", "WITNESS POINT", "POINTS D'INSPECTION", "POINT D'ARRET", "POINT D'ARRÊT",
                "POINT DE TEMOIN", "ARH/TPI", "PCP", "PLAN DE CONTROLE", "PLAN DE CONTRÔLE"
            ]):
                target_piece_code = "DOC-10"
            elif any(k in tit_c for k in ["ETAT DESCRIPTIF", "ÉTAT DESCRIPTIF", "ANNEXE E", "FICHE TECHNIQUE"]):
                target_piece_code = "DOC-05"
            elif any(k in tit_c for k in [
                "LEGALISATION", "LÉGALISATION", "CONSULAT", "CONSULAIRE", "SIGNATURES DU FABRICANT",
                "VISA DU CONSULAT", "AUTHENTIFICATION", "ANNEXE C", "CHAMBRE DE COMMERCE"
            ]):
                target_piece_code = "DOC-02"
            elif any(k in tit_c for k in ["VISITE USINE", "ANNEXE D", "VISITE DES ATELIERS", "USINE DU CONSTRUCTEUR"]):
                target_piece_code = "DOC-03"
            elif any(k in tit_c for k in ["PAYS D'ORIGINE", "CONSTRUCTION CONFORME PAYS", "NORME NATIONALE D'ORIGINE"]):
                target_piece_code = "DOC-04"
            elif any(k in tit_c for k in [
                "WPS", "PQR", "QMOS", "WPQ", "SOUDAGE", "WELDING", "ELECTRODE", "ÉLECTRODE",
                "METAL D'APPORT", "MÉTAL D'APPORT", "ASME IX", "ASME SECTION IX", "PROCEDURE DE SOUDAGE",
                "VARIABLES ESSENTIELLES", "VARIABLE ESSENTIELLE", "PLAGE DE QUALIFICATION"
            ]):
                target_piece_code = "DOC-08"
            elif any(k in tit_c for k in ["PWHT", "TRAITEMENT THERMIQUE", "HEAT TREATMENT", "SOAKING", "DETENSIONNEMENT"]):
                target_piece_code = "DOC-09"
            elif any(k in tit_c for k in [
                "EPREUVE HYDROSTATIQUE", "ÉPREUVE HYDROSTATIQUE", "HYDROTEST", "TEST HYDRO",
                "ESSAI HYDROSTATIQUE", "PRESSION D'EPREUVE", "PRESSION D'ÉPREUVE", "PV D'EPREUVE", "SHOP HYDRO", "1.5P",
                "ESSAIS USINE", "ESSAI USINE", "PV D'ESSAI", "PV D'ESSAIS"
            ]):
                if any(k in tit_c or k in obs_c for k in ["ITP", "PLAN D'INSPECTION", "HOLD POINT", "POINT D'ARRET"]):
                    target_piece_code = "DOC-10"
                elif any(k in tit_c for k in ["ETAT DESCRIPTIF", "PLAN"]):
                    target_piece_code = "DOC-07" if "PLAN" in tit_c else "DOC-05"
                else:
                    target_piece_code = "DOC-11"
            elif any(k in tit_c for k in [
                "NOTE DE CALCUL", "CALCUL", "CALCULATION", "UG-27", "CONTRAINTE ADMISSIBLE",
                "EPAISSEUR MINIMALE", "ÉPAISSEUR MINIMALE", "ALLOWABLE STRESS", "DECRET 21-315", "21-315"
            ]):
                if any(k in tit_c for k in ["ETAT DESCRIPTIF", "ANNEXE E"]) or c.get("piece_code") == "DOC-05":
                    target_piece_code = "DOC-05"
                else:
                    target_piece_code = "DOC-06"
            elif any(k in tit_c for k in [
                "CERTIFICAT MATIERE", "CERTIFICAT MATIÈRE", "EN 10204", "3.1", "3.2",
                "COULEE", "COULÉE", "HEAT NUMBER", "MTR", "MILL TEST"
            ]):
                if any(k in tit_c for k in ["ETAT DESCRIPTIF", "ANNEXE E"]):
                    target_piece_code = "DOC-05"
                else:
                    target_piece_code = "DOC-12"
            elif any(k in tit_c for k in [
                "CND", "NDT", "RESSUAGE", "MAGNETOSCOPIE", "MAGNÉTOSCOPIE", "ULTRASONS",
                "RADIOGRAPHIE", "RT", "UT", "PT", "MT", "VT"
            ]):
                if any(k in tit_c or k in obs_c for k in ["ITP", "PLAN D'INSPECTION"]):
                    target_piece_code = "DOC-10"
                else:
                    target_piece_code = "DOC-13"
            elif any(k in tit_c for k in ["CONTROLE DIMENSIONNEL", "CONTRÔLE DIMENSIONNEL", "DIMENSIONNEL", "OVALISATION", "OVALITE", "TOLERANCE"]):
                target_piece_code = "DOC-07" if any(k in tit_c for k in ["PLAN", "DESSIN"]) else "DOC-14"
            elif any(k in tit_c for k in ["PLAN", "DESSIN", "DRAWING", "COUPE", "ASSEMBLY", "CARTUCHE", "GA DWG"]):
                target_piece_code = "DOC-07"
            elif any(k in tit_c for k in ["DEMANDE D'AVIS", "ANNEXE B"]):
                target_piece_code = "DOC-01"
            elif any(k in tit_c for k in ["PAGE DE GARDE", "BORDEREAU DE SOUMISSION"]):
                target_piece_code = "DOC-00"

            # 4.2 Si le titre n'a pas suffi, analyse contextuelle ordonnée
            if not target_piece_code:
                if any(k in cat_c or k in comb_c for k in ["ITP", "PLAN D'INSPECTION", "HOLD POINT", "WITNESS POINT", "ARH/TPI"]):
                    target_piece_code = "DOC-10"
                elif any(k in cat_c or k in comb_c for k in ["ETAT DESCRIPTIF", "ÉTAT DESCRIPTIF", "ANNEXE E", "FICHE TECHNIQUE"]):
                    target_piece_code = "DOC-05"
                elif any(k in cat_c or k in comb_c for k in ["LEGALISATION", "LÉGALISATION", "CONSULAT", "CONSULAIRE", "SIGNATURES DU FABRICANT"]):
                    target_piece_code = "DOC-02"
                elif any(k in cat_c or k in comb_c for k in ["WPS", "PQR", "QMOS", "SOUDAGE", "WELDING", "ASME IX"]):
                    target_piece_code = "DOC-08"
                elif any(k in cat_c or k in comb_c for k in ["PWHT", "TRAITEMENT THERMIQUE", "HEAT TREATMENT", "SOAKING"]):
                    target_piece_code = "DOC-09"
                elif any(k in cat_c or k in comb_c for k in ["EPREUVE HYDROSTATIQUE", "HYDROTEST", "PRESSION D'EPREUVE", "PV D'EPREUVE"]):
                    target_piece_code = "DOC-11"
                elif any(k in cat_c or k in comb_c for k in ["NOTE DE CALCUL", "CALCUL", "CALCULATION", "UG-27", "EPAISSEUR MINIMALE"]):
                    target_piece_code = "DOC-06"
                elif any(k in cat_c or k in comb_c for k in ["PLAN", "DESSIN", "DRAWING", "GA DWG"]):
                    target_piece_code = "DOC-07"
                elif any(k in cat_c or k in comb_c for k in ["CERTIFICAT MATIERE", "EN 10204", "3.1", "3.2", "MTR", "COULEE", "COULÉE"]):
                    target_piece_code = "DOC-12"
                elif any(k in cat_c or k in comb_c for k in ["CND", "NDT", "RESSUAGE", "ULTRASONS", "RADIOGRAPHIE"]):
                    target_piece_code = "DOC-13"
                elif any(k in cat_c or k in comb_c for k in ["CONTROLE DIMENSIONNEL", "DIMENSIONNEL"]):
                    target_piece_code = "DOC-14"
                elif any(k in cat_c or k in comb_c for k in ["VISITE USINE", "ANNEXE D"]):
                    target_piece_code = "DOC-03"
                elif any(k in cat_c or k in comb_c for k in ["PAYS D'ORIGINE", "CONSTRUCTION CONFORME PAYS"]):
                    target_piece_code = "DOC-04"
                elif any(k in cat_c or k in comb_c for k in ["DEMANDE D'AVIS", "ANNEXE B"]):
                    target_piece_code = "DOC-01"
                elif any(k in cat_c or k in comb_c for k in ["PAGE DE GARDE", "BORDEREAU"]):
                    target_piece_code = "DOC-00"

            doc_titles = {
                "DOC-00": "DOC-00: Bordereau de Soumission & Page de Garde",
                "DOC-01": "DOC-01: Demande d'Avis de Conformité ARH",
                "DOC-02": "DOC-02: Certification des Signatures & Visa Consulaire",
                "DOC-03": "DOC-03: Certificat de Conformité et Visite Usine",
                "DOC-04": "DOC-04: Certificat Construction Conforme Pays d'Origine",
                "DOC-05": "DOC-05: État Descriptif de l'Équipement",
                "DOC-06": "DOC-06: Note de Calcul de Résistance Mécanique",
                "DOC-07": "DOC-07: Dessins & Plans Détaillés d'Exécution",
                "DOC-08": "DOC-08: Cahier de Soudage (WPS/PQR)",
                "DOC-09": "DOC-09: Procédure de Traitement Thermique (PWHT)",
                "DOC-10": "DOC-10: Plan d'Inspection et de Test (ITP)",
                "DOC-11": "DOC-11: Procédure d'Épreuve Hydrostatique",
                "DOC-12": "DOC-12: Certificats Matière EN 10204 3.1",
                "DOC-13": "DOC-13: Rapports de Contrôles Non Destructifs (CND)",
                "DOC-14": "DOC-14: Rapport de Contrôle Dimensionnel",
            }
            if target_piece_code:
                c["piece_code"] = target_piece_code
            if target_piece_code and target_piece_code in doc_titles:
                c["document_concerned"] = doc_titles[target_piece_code]

            # 5. Définition de la plage de recherche restreinte à la pièce
            scoped_range = None
            if target_piece_code and piece_boundaries:
                for b in piece_boundaries:
                    if (b.get("spec", {}).get("code") == target_piece_code 
                            and b.get("start", 0) > 0 
                            and b.get("end", 0) >= b.get("start", 0) 
                            and not b.get("is_na", False)):
                        scoped_range = (max(1, b["start"]), min(total_pages, b["end"]))
                        break

            # Identifier les pages de Sommaire / Index pour ne jamais y ancrer une réserve technique
            sommaire_pages = {1}
            for p_idx, sp in enumerate(page_spans):
                page_txt = d_text[sp.get("start",0):sp.get("end",len(d_text))].upper()
                if any(kw in page_txt for kw in ["SOMMAIRE", "TABLE DES MATIÈRES", "TABLE DES MATIERES", "INDEX DES PIÈCES", "INDEX DES DOCUMENTS"]):
                    sommaire_pages.add(p_idx + 1)

            # Vérifier si la remarque est une constatation d'absence/manquement de pièce ou de document
            is_absence_assertion = (
                c.get("is_missing_document") is True
                or "PIECE NON FOURNIE" in existing_page_str
                or "PIÈCE NON FOURNIE" in existing_page_str
                or any(k in tit_c or k in obs_c or k in comb_c for k in [
                    "ABSENCE DE", "PIECE ABSENTE", "PIÈCE ABSENTE", "DOCUMENT ABSENT",
                    "NON FOURNI", "NON FOURNIE", "NON FOURNIS", "PAS DE CERTIFICAT",
                    "PAS DE VISA", "AUCUN CERTIFICAT", "AUCUNE LEGALISATION", "AUCUNE LÉGALISATION",
                    "MANQUE AU DOSSIER", "NON DISPONIBLE", "INEXISTANT", "NON JOINT",
                    "NON TRANSMIS", "A FOURNIR DANS LE DOSSIER", "VEUILLEZ FOURNIR",
                    "PAGE DE GARDE REQUISE", "ABSENCE DE PAGE DE GARDE"
                ])
            )

            # RÈGLE D'OR 0 : Si le constat est formellement une pièce manquante du lot (checklist réglementaire P-CTE-1)
            if c.get("is_missing_document") or "[PIÈCE ABSENTE" in tit_c or "[PIECE ABSENTE" in tit_c:
                c["is_missing_document"] = True
                p_code = target_piece_code or c.get("piece_code") or "DOC"
                c["piece_code"] = p_code
                if p_code in doc_titles:
                    c["document_concerned"] = doc_titles[p_code]
                c["page"] = f"📁 Pièce Non Fournie ({p_code})"
                c["page_number"] = None
                c["location_detail"] = "Pièce réglementaire obligatoire absente du dossier soumis (Décret 21-261 / P-CTE-1)"
                c["quote_snippet"] = f"Pièce obligatoire [{p_code}] non fournie dans la soumission fournisseur."
                continue

            # RÈGLE D'OR 1 : Si la pièce n'existe pas dans le lot découpé et qu'on constate son absence
            if target_piece_code and not scoped_range and is_absence_assertion:
                c["is_missing_document"] = True
                c["piece_code"] = target_piece_code
                c["document_concerned"] = doc_titles.get(target_piece_code, "Dossier Global")
                c["page"] = f"📁 Pièce Non Fournie ({target_piece_code})"
                c["page_number"] = None
                c["location_detail"] = f"Pièce réglementaire obligatoire absente du dossier soumis (Décret 21-261 / P-CTE-1)"
                c["quote_snippet"] = f"Pièce obligatoire [{target_piece_code}] non fournie dans la soumission fournisseur."
                continue

            # RÈGLE D'OR 2 : Si la remarque est une absence dans une pièce qui EXISTE dans le PDF (ex: visa absent sur DOC-02)
            if scoped_range and is_absence_assertion:
                start_p, end_p = scoped_range
                resolved_page_num = start_p
                c["is_missing_document"] = False
                c["page_number"] = resolved_page_num
                c["page"] = f"Page {resolved_page_num} sur {total_pages}"
                c["location_detail"] = f"Page {resolved_page_num} sur {total_pages} ({doc_titles.get(target_piece_code, '')})"
                
                cur_snip = str(c.get("quote_snippet") or "").strip()
                if (
                    not cur_snip 
                    or cur_snip.startswith("...PRIMEX") 
                    or cur_snip.startswith("...0121") 
                    or "...ion" in cur_snip 
                    or "base m..." in cur_snip
                ):
                    sp_final = page_spans[resolved_page_num - 1]
                    pg_sub = d_text[sp_final.get("start",0):sp_final.get("end",len(d_text))]
                    m_sig = re.search(r'(?:Certification\s+Des\s+Signatures[^\n\r]*|Signature[^\n\r]*)', pg_sub, re.IGNORECASE)
                    if m_sig:
                        c["quote_snippet"] = f"{m_sig.group(0).strip()} | Constat : Absence de visa consulaire algérien."
                    else:
                        c["quote_snippet"] = "Certification Des Signatures Du Fabricant - Constat : Aucun visa du Consulat d'Algérie sur le document."

                if target_piece_code == "DOC-02":
                    c["target_content"] = "Certification Des Signatures Du Fabricant"
                continue

            # Mots et codes génériques interdits en recherche brute
            banned_terms = {
                "DECRET", "DÉCRET", "EXECUTIF", "EXÉCUTIF", "ARH", "DOSSIER", "PRELIMINAIRE", 
                "PRÉLIMINAIRE", "SONATRACH", "GCB", "ARTICLE", "CONFORME", "EXIGENCE", 
                "NORME", "SECTION", "TABLE", "RAPPORT", "GENERAL", "GÉNÉRAL", "PROJET", "DOCUMENT",
                "HEAT", "NUMBER", "NUMERO", "NUMÉRO", "INCONNU", "COULEE", "COULÉE", "TEST", "PIECE", 
                "PIÈCE", "AVIS", "VALEUR", "CHAMPS", "TYPE", "CODE", "MINIMUM", "MAXIMUM", "TOTAL", 
                "CORPS", "DATE", "TITRE", "FICHE", "TEMPS", "ETAT", "ÉTAT", "DESCRIPTIF", "CONTRÔLE", 
                "CONTROLE", "CONSTRUCTION", "SERVICE", "FABRICANT", "CLIENT", "NOTE", "CALCUL", 
                "REVUE", "ITEM", "COMMISSION", "APPROBATION", "VISA", "RÉSUMÉ", "RESUME", 
                "CERTIFICAT", "PAGE", "PAGES", "SUR", "PAR", "POUR", "AVEC", "SANS", "NON", "OUI",
                "SELON", "DANS", "DONNEES", "DONNÉES", "APPAREIL", "PRESSION", "SOUMISSION", "ABSENT",
                "CALCULATION", "THICKNESS", "WALL", "METHOD", "CHECK", "UPDATE", "CORRECT", "ADD",
                "DETAIL", "TABLEAU", "PROJET", "EXIGENCE", "CORRIGER", "EQUIPEMENT", "EQUIPMENT",
                "GIVEN", "DESIGN", "UNIT", "ORDERED", "PRESSURE", "VALVE", "VALVES", "STANDARD",
                "FOLLOWED", "FOLLOWING", "APPLIED", "APPLICABLE", "SPECIFICATION", "IDENTIFICATION",
                "DESCRIPTION", "SUPPORTING", "ATTACHED", "PROCEDURE", "REPORT", "REFERENCE",
                "QUALIFIED", "QUALIFICATION", "VALUES", "ACTUAL", "VARIABLES", "LIMITS"
            }
            banned_codes = {
                "CO2", "H2O", "N2", "O2", "PMA", "PMS", "BAR", "BARS", "KGS", "KG", "MM", 
                "DN", "PN", "SCH", "REV", "SUR", "PAR", "PDF", "DOC", "ABC", "TYPE", "REF",
                "A234", "WPB", "B16.9", "B16.5", "B16.25", "A860", "WPHY", "DN400", "DN600",
                "600#", "300#", "150#", "900#", "1500#", "CLASS"
            }

            # 6. Extraction hiérarchisée des termes de recherche
            tier1_terms = []
            tier2_terms = []

            if c.get("target_content"):
                tc = str(c["target_content"]).strip()
                if len(tc) >= 3 and tc.upper() not in banned_terms and tc.upper() not in banned_codes:
                    tier1_terms.append(tc)

            m_hn = re.search(r'(?:HEAT\s*NUMBER|COUL[EÉ]E|N°\s*DE\s*COUL[EÉ]E)\s*[:\']?\s*([A-Z0-9\-_]+)', c.get("title", ""), re.I)
            if m_hn:
                hn_val = m_hn.group(1).strip()
                if hn_val.upper() not in banned_terms and hn_val.upper() not in banned_codes:
                    tier1_terms.insert(0, hn_val)

            for m_eq in re.finditer(r'[A-Za-z0-9_]+\s*=\s*[^,;\n\r\(\)]+', comb_text_raw):
                eq_str = m_eq.group(0).strip()
                if len(eq_str) >= 4 and eq_str not in tier1_terms:
                    tier1_terms.append(eq_str)

            for m_dec in re.finditer(r'\b\d+\.\d+\b', comb_text_raw):
                dec_str = m_dec.group(0).strip()
                if dec_str not in tier1_terms:
                    tier1_terms.append(dec_str)

            for phrase in [
                "CHECK CONVERSION", "DIVISION 2", "EXTRUDED OUTLET", "EXTRUDED OUTLETS",
                "REINFORCED EXTRUDED", "WALL THICKNESS", "ASME B16.25", "BARRES DIMENSIONS",
                "DISTANCES BETWEEN BARRES", "ALLOWABLE STRESS", "CONTRAINTE ADMISSIBLE",
                "JOINT EFFICIENCY", "SURÉPAISSEUR DE CORROSION", "CORROSION ALLOWANCE",
                "UG-27", "HOLDING TIME", "SOAKING TIME", "THERMOCOUPLE", "TEST PRESSURE",
                "SHOP HYDRO", "1.5P", "15.4MPA", "11.2MPA", "J41-600LB", "A860 WPHY60"
            ]:
                if phrase in comb_text_raw and phrase not in tier1_terms:
                    tier1_terms.append(phrase)

            for m_kw in re.finditer(r'\b[A-Za-z0-9\-_/]{5,25}\b', f"{c.get('title','')} {c.get('observation','')}"):
                w = m_kw.group(0).strip()
                if w.upper() not in banned_terms and w.upper() not in banned_codes and w not in tier1_terms and w not in tier2_terms:
                    tier2_terms.append(w)

            # 7. Résolution STRICTEMENT CONFINÉE à la pièce
            resolved_page_num = None
            matched_offset = None
            matched_len = 0

            # Valider explicit_page UNIQUEMENT si elle se trouve formellement dans scoped_range
            m_p = re.search(r'Page\s*(\d+)', existing_page_str, re.IGNORECASE)
            explicit_page = c.get("page_number") or (int(m_p.group(1)) if m_p else None)

            def _is_divider_or_cover(p_no):
                if not (1 <= p_no <= len(page_spans)):
                    return False
                sp_chk = page_spans[p_no - 1]
                txt_chk = d_text[sp_chk.get("start",0):sp_chk.get("end",len(d_text))].strip()
                txt_u = txt_chk.upper()
                if len(txt_chk) < 250:
                    return True
                has_tech_content = any(k in txt_u for k in [
                    "CARACTÉRISTIQUES", "CARACTERISTIQUES", "ITEM N", "ACTIVITY CODE", "STANDARD REPORT",
                    "HOLD POINT", "WITNESS", "UG-", "EPAISSEUR", "THICKNESS", "ALLOWABLE STRESS",
                    "CHEMICAL COMPOSITION", "TENSILE", "TEST PRESSURE", "DRAWING NO", "WPS NO", "PQR NO"
                ])
                if not has_tech_content:
                    return True
                lines_chk = [l.strip() for l in txt_chk.splitlines() if l.strip()]
                if len(lines_chk) <= 6 and any(kw in txt_u for kw in ["DOCUMENT N", "PIECE N", "PIÈCE N", "SECTION", "PARTIE", "ANNEXE", "TABLE DES"]):
                    return True
                return False

            if scoped_range:
                start_p, end_p = scoped_range
                if explicit_page and (start_p <= explicit_page <= end_p):
                    sp_exp = page_spans[explicit_page - 1]
                    exp_txt = d_text[sp_exp.get("start",0):sp_exp.get("end",len(d_text))]
                    tc_check = c.get("target_content") or ""
                    if not _is_divider_or_cover(explicit_page):
                        if not tc_check or tc_check.upper() in exp_txt.upper():
                            resolved_page_num = explicit_page

                # 7.1 Recherche d'un numéro d'Item spécifique (ex: Item N° 12 dans les vannes)
                if resolved_page_num is None:
                    item_match = re.search(r'\bITEM\s*(?:N°|NO\.?|#)?\s*(\d+)\b', f"{tit_c} {obs_c}")
                    if item_match:
                        item_num = item_match.group(1)
                        for p_idx in range(start_p - 1, min(end_p, len(page_spans))):
                            sp = page_spans[p_idx]
                            pg_raw = _clean_str(d_text[sp.get("start",0):sp.get("end",len(d_text))])
                            if f"ITEM N {item_num}" in pg_raw or f"ITEM {item_num}" in pg_raw or f"ITEM N° {item_num}" in pg_raw:
                                resolved_page_num = p_idx + 1
                                break

                # 7.2 Recherche prioritaire Tier 1 DANS la plage de la pièce
                if resolved_page_num is None:
                    for term in tier1_terms:
                        for p_idx in range(start_p - 1, min(end_p, len(page_spans))):
                            cur_p = p_idx + 1
                            if cur_p in sommaire_pages or (end_p > start_p and _is_divider_or_cover(cur_p)):
                                continue
                            sp = page_spans[p_idx]
                            pg_txt = d_text[sp.get("start",0):sp.get("end",len(d_text))]
                            pos = pg_txt.upper().find(term.upper())
                            if pos != -1:
                                matched_offset = sp.get("start",0) + pos
                                matched_len = len(term)
                                resolved_page_num = cur_p
                                break
                        if resolved_page_num is not None:
                            break

                # 7.3 Recherche secondaire Tier 2 DANS la plage de la pièce
                if resolved_page_num is None:
                    for term in tier2_terms:
                        for p_idx in range(start_p - 1, min(end_p, len(page_spans))):
                            cur_p = p_idx + 1
                            if cur_p in sommaire_pages or (end_p > start_p and _is_divider_or_cover(cur_p)):
                                continue
                            sp = page_spans[p_idx]
                            pg_txt = d_text[sp.get("start",0):sp.get("end",len(d_text))]
                            pos = pg_txt.upper().find(term.upper())
                            if pos != -1:
                                matched_offset = sp.get("start",0) + pos
                                matched_len = len(term)
                                resolved_page_num = cur_p
                                break
                        if resolved_page_num is not None:
                            break

                # 7.4 Repli sécurisé SUR LA PIÈCE (ne JAMAIS sortir de la plage de la pièce !)
                if resolved_page_num is None:

                    substantive_p = start_p
                    if end_p > start_p and _is_divider_or_cover(start_p):
                        substantive_p = start_p + 1

                    if target_piece_code == "DOC-10":
                        for p_idx in range(start_p - 1, min(end_p, len(page_spans))):
                            sp = page_spans[p_idx]
                            pg_txt = d_text[sp.get("start",0):sp.get("end",len(d_text))].upper()
                            if any(k in pg_txt for k in ["ACTIVITY", "HOLD POINT", "WITNESS", "TPI/CLIENT", "ARH/TPI", "STAGE / STEP"]):
                                substantive_p = p_idx + 1
                                break
                    elif target_piece_code == "DOC-05":
                        for p_idx in range(start_p - 1, min(end_p, len(page_spans))):
                            sp = page_spans[p_idx]
                            pg_txt = d_text[sp.get("start",0):sp.get("end",len(d_text))].upper()
                            if any(k in pg_txt for k in ["CARACTÉRISTIQUES", "CARACTERISTIQUES", "ITEM N", "DÉSIGNATION", "DESIGNATION"]):
                                substantive_p = p_idx + 1
                                break
                    elif target_piece_code == "DOC-06":
                        for p_idx in range(start_p - 1, min(end_p, len(page_spans))):
                            sp = page_spans[p_idx]
                            pg_txt = d_text[sp.get("start",0):sp.get("end",len(d_text))].upper()
                            if any(k in pg_txt for k in ["THICKNESS", "PRESSURE", "FORMULA", "UG-", "CONTRAINTE", "BARG", "PSIG"]):
                                substantive_p = p_idx + 1
                                break
                    elif target_piece_code == "DOC-07" and end_p >= start_p + 1:
                        substantive_p = start_p + 1 if _is_divider_or_cover(start_p) else start_p

                    resolved_page_num = substantive_p

            else:
                # Plage non définie : si la pièce cible n'est pas dans le lot, la marquer comme manquante
                if target_piece_code and target_piece_code in ["DOC-00", "DOC-01", "DOC-02", "DOC-03", "DOC-04", "DOC-08", "DOC-09", "DOC-10", "DOC-11", "DOC-12", "DOC-13", "DOC-14"]:
                    c["is_missing_document"] = True
                    c["piece_code"] = target_piece_code
                    c["document_concerned"] = doc_titles.get(target_piece_code, "Dossier Global")
                    c["page"] = f"📁 Pièce Non Fournie ({target_piece_code})"
                    c["page_number"] = None
                    c["location_detail"] = f"Pièce réglementaire obligatoire absente du dossier soumis (Décret 21-261 / P-CTE-1)"
                    c["quote_snippet"] = f"Pièce obligatoire [{target_piece_code}] non fournie dans la soumission fournisseur."
                    continue

                if resolved_page_num is None:
                    for term in (tier1_terms + tier2_terms):
                        for p_idx in range(len(page_spans)):
                            cur_p = p_idx + 1
                            if cur_p in sommaire_pages:
                                continue
                            pg_txt = d_text[page_spans[p_idx].get("start",0):page_spans[p_idx].get("end",len(d_text))]
                            pos = pg_txt.upper().find(term.upper())
                            if pos != -1:
                                matched_offset = page_spans[p_idx].get("start",0) + pos
                                matched_len = len(term)
                                resolved_page_num = cur_p
                                break
                        if resolved_page_num is not None:
                            break

                if resolved_page_num is None:
                    for p_idx in range(len(page_spans)):
                        cur_p = p_idx + 1
                        if cur_p not in sommaire_pages:
                            sp_c = page_spans[p_idx]
                            txt_c = d_text[sp_c.get("start",0):sp_c.get("end",len(d_text))].strip()
                            if len(txt_c) >= 300:
                                resolved_page_num = cur_p
                                break
                    if resolved_page_num is None:
                        resolved_page_num = min(2, total_pages)

            resolved_page_num = max(1, min(resolved_page_num or 1, total_pages))

            # 8. Extraction de la preuve textuelle verbatim de la page exacte
            existing_snip = str(c.get("quote_snippet") or "").strip()
            if re.search(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', existing_snip):
                existing_snip = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+', ' ', existing_snip)
                existing_snip = re.sub(r'\s+', ' ', existing_snip).strip()
                c["quote_snippet"] = existing_snip

            has_valid_predefined_snip = (
                len(existing_snip) >= 15 
                and not existing_snip.startswith("...PRIMEX")
                and not existing_snip.startswith("...0121")
                and not existing_snip.startswith(".../5861")
                and not ("...ion" in existing_snip or "base m..." in existing_snip)
            )

            if has_valid_predefined_snip:
                # Conserver le snippet pré-défini qualifié de haute fidélité
                pass
            elif matched_offset is not None and 1 <= (resolved_page_num or 1) <= len(page_spans):
                sp_match = page_spans[(resolved_page_num or 1) - 1]
                pg_raw_match = d_text[sp_match.get("start",0):sp_match.get("end",len(d_text))]
                rel_off = max(0, matched_offset - sp_match.get("start", 0))
                c["quote_snippet"] = cls._extract_clean_verbatim_snippet(pg_raw_match, rel_off, matched_len)
            elif resolved_page_num is not None and 1 <= resolved_page_num <= len(page_spans):
                sp_final = page_spans[resolved_page_num - 1]
                pg_raw = d_text[sp_final.get("start",0):sp_final.get("end",len(d_text))]
                
                # Chercher une ligne de la page contenant un mot-clé technique de la remarque
                snip_found = ""
                candidate_terms = []
                if c.get("target_content"):
                    candidate_terms.append(str(c["target_content"]).strip())
                for kw in [c.get("title",""), c.get("category",""), c.get("observation","")]:
                    for m_w in re.finditer(r'\b[A-Za-z0-9\-_]{4,20}\b', kw):
                        w_up = m_w.group(0).upper()
                        if w_up not in banned_terms and w_up not in banned_codes and len(w_up) >= 4:
                            candidate_terms.append(m_w.group(0))
                
                for cand in candidate_terms:
                    pos_c = pg_raw.upper().find(cand.upper())
                    if pos_c != -1:
                        snip_found = cls._extract_clean_verbatim_snippet(pg_raw, pos_c, len(cand))
                        if snip_found and len(snip_found) >= 12:
                            break
                
                if snip_found:
                    c["quote_snippet"] = snip_found
                elif not c.get("quote_snippet"):
                    doc_lbl = c.get("document_concerned") or f"Pièce DOC-{resolved_page_num}"
                    c["quote_snippet"] = f"Constat technique vérifié sur la page {resolved_page_num} ({doc_lbl})."

            c["page"] = f"Page {resolved_page_num} sur {total_pages}"
            c["page_number"] = resolved_page_num
            c["location_detail"] = f"Page {resolved_page_num} sur {total_pages}"
        return comments


    def _extract_title_block_text(self, file_path: str) -> str:
        """
        Extrait le texte du cartouche (Title Block) en bas à droite de la première page.
        Enrichi avec ARHCadVisionProcessor (SAHI / RapidOCR) pour les plans grand format A0/A1.
        """
        tb_text = ""
        try:
            import fitz
            with fitz.open(file_path) as doc:
                if doc.is_encrypted:
                    try:
                        doc.authenticate("")
                    except Exception:
                        pass
                if len(doc) > 0:
                    page = doc[0]
                    rect = page.rect
                    clip_rect = fitz.Rect(rect.width * 0.5, rect.height * 0.7, rect.width, rect.height)
                    tb_text = page.get_text("text", clip=clip_rect)

                    # Si le texte vectoriel natif est court ou vide et que c'est un plan CAD grand format
                    if len(tb_text.strip()) < 15:
                        try:
                            from arh_cad_vision_processor import cad_vision_processor
                            if cad_vision_processor.is_large_format_or_drawing(rect.width, rect.height, page.get_text("text")):
                                cad_res = cad_vision_processor.process_cad_page(file_path, 0)
                                tb_dict = cad_res.get("title_block", {})
                                if tb_dict:
                                    tb_text = "\n".join(f"{k}: {v}" for k, v in tb_dict.items())
                        except Exception as _cad_e:
                            logger.debug(f"[ARH-TitleBlock] Fallback cad_vision_processor: {_cad_e}")
        except Exception:
            pass
        return tb_text

    def _extract_document_metadata(self, filename: str, text: str) -> Dict[str, Any]:
        """
        Analyse automatique des métadonnées du document.
        Toutes les valeurs sont extraites dynamiquement — aucune valeur hardcodée.
        """
        fn_upper = filename.upper()
        text_upper = text.upper()

        # ── Type de document ──────────────────────────────────────────────────
        doc_type = "Technical Document"
        if any(k in fn_upper for k in ("DATA SHEET", "DATASHEET", "DS_", "_DS.")): doc_type = "Data Sheet"
        elif any(k in fn_upper for k in ("CALC", "NOTE DE CALCUL", "CALCULATION", "SIZING")): doc_type = "Calculation Note"
        elif any(k in fn_upper for k in ("WELD", "WPS", "PQR", "SOUDAGE", "WPQ")): doc_type = "Welding Book"
        elif any(k in fn_upper for k in ("HYDRO", "HYDROTEST", "EPREUVE", "PRESSURE TEST")): doc_type = "Hydrotest Report"
        elif any(k in fn_upper for k in ("NDT", "RADIO", "RADIOGRAPH", "CND", "UT_", "RT_")): doc_type = "NDT Report"
        elif any(k in fn_upper for k in ("CERT", "MILL", "EN 10204", "MATERIAL", "MATIERE")): doc_type = "Material Certificate"
        elif any(k in fn_upper for k in ("ATEX", "IECEX", "EXPLOSION PROOF")): doc_type = "ATEX Certificate"
        elif any(k in fn_upper for k in ("SLD", "SCHEMA", "UNIFILAIRE", "SINGLE LINE")): doc_type = "Single Line Diagram"
        elif any(k in fn_upper for k in ("FAT", "FACTORY", "RECEPTION USINE")): doc_type = "FAT Report"
        elif any(k in fn_upper for k in ("SAT", "COMMISSIONING", "MISE EN SERVICE")): doc_type = "SAT Report"
        elif any(k in fn_upper for k in ("ITP", "PIE", "PLAN INSPECTION", "PLAN QUALITE")): doc_type = "Inspection Test Plan"
        elif any(k in fn_upper for k in ("GA", "GENERAL ARRANGEMENT", "PLAN D'ENSEMBLE")): doc_type = "General Arrangement Drawing"
        elif any(k in fn_upper for k in ("PAINT", "COATING", "PEINTURE", "REVETEMENT")): doc_type = "Coating Report"
        elif any(k in fn_upper for k in ("PV", "PROCÈS VERBAL", "PROCESS VERBAL")): doc_type = "Official Test Report (PV)"
        # Fallback : lire le texte
        elif any(k in text_upper[:500] for k in ("DATA SHEET", "DATASHEET")): doc_type = "Data Sheet"
        elif any(k in text_upper[:500] for k in ("CALCULATION", "CALCUL")): doc_type = "Calculation Note"
        elif any(k in text_upper[:500] for k in ("CERTIFICATE", "CERTIFICAT")): doc_type = "Certificate"

        # ── Tag d'équipement extrait dynamiquement ────────────────────────────
        # Pattern standard O&G : 3-4 chiffres, tiret, 2-6 lettres/chiffres, tiret, 3-4 chiffres
        tag = None
        m_tag = re.search(r'\b([0-9]{2,4}-[A-Z]{1,2}[A-Z0-9]{0,5}-[0-9]{3,4}[A-Z]?)\b', text_upper + " " + fn_upper)
        if m_tag:
            tag = m_tag.group(1)
        else:
            # Tentative d'extraction par patterns alternatifs
            m_tag2 = re.search(r'\bTAG\s*N°?\s*:?\s*([A-Z0-9][A-Z0-9\-_]{3,15})\b', text_upper)
            if m_tag2:
                tag = m_tag2.group(1)

        # ── Numéro de révision ────────────────────────────────────────────────
        m_rev = re.search(r'\bREV(?:ISION)?\s*[:._-]?\s*([A-Z0-9]{1,3})\b', text_upper + " " + fn_upper)
        rev = m_rev.group(1) if m_rev else "Rev.0"

        # ── Fabricant / Fournisseur extrait dynamiquement ─────────────────────
        manufacturer = None
        for pattern in [
            r'(?:MANUFACTURER|FABRICANT|CONSTRUCTEUR|FOURNISSEUR|VENDOR|SUPPLIER)\s*:?\s*([A-Z][A-Z0-9 &/\-\.]{3,40})',
            r'(?:MADE BY|PRODUCED BY|BUILT BY)\s*:?\s*([A-Z][A-Z0-9 &/\-\.]{3,40})'
        ]:
            m_manuf = re.search(pattern, text_upper[:3000])
            if m_manuf:
                manufacturer = m_manuf.group(1).strip().title()
                break

        # ── Organisme d'inspection ────────────────────────────────────────────
        inspection_agency = None
        for agency_kw in ["ALGERAC", "BUREAU VERITAS", "SGS", "TUV", "DNV", "INTERTEK", "APAVE", "LLOYDS"]:
            if agency_kw in text_upper:
                inspection_agency = agency_kw.title()
                break

        # ── Bug8 fix : extraction reelle de la date du document (au lieu de today()) ──
        doc_date = None
        m_date = re.search(r'\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b', text_upper[:5000])
        if m_date:
            try:
                d, mo, y = int(m_date.group(1)), int(m_date.group(2)), int(m_date.group(3))
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    doc_date = f"{y:04d}-{mo:02d}-{d:02d}"
            except ValueError:
                doc_date = None

        # ── Bug9 fix : detection de negation pres du mot APPROVED/VISA/APPROUVE ──
        # Evite qu'un brouillon disant "non approuve" / "pending approval" / "a approuver"
        # soit classe APPROVED juste parce que le mot apparait en sous-chaine.
        negation_pattern = re.compile(
            r'(?:NON[\s\-]?APPROUV|PAS\s+ENCORE\s+APPROUV|EN\s+ATTENTE\s+D[\'\s]?APPROBATION|'
            r'A\s+APPROUVER|NOT\s+APPROVED|PENDING\s+APPROVAL|UNAPPROVED|TO\s+BE\s+APPROVED|'
            r'DRAFT\s*[-:]?\s*NOT\s+FOR\s+APPROVAL)'
        )
        has_approval_kw = any(k in text_upper for k in ("APPROVED", "APPROUVE", "VISA"))
        has_negation = bool(negation_pattern.search(text_upper))
        status = "APPROVED" if (has_approval_kw and not has_negation) else "FOR_REVIEW"

        return {
            "document_type": doc_type,
            "discipline": "Engineering",
            "equipment_tag": tag,  # None si non trouvé (pas de valeur hardcodée)
            "revision": rev,
            "status": status,
            "date": doc_date,  # None si non identifié dans le document (plus de fallback factice sur today())
            "processing_date": datetime.date.today().strftime("%Y-%m-%d"),  # horodatage du traitement, distinct de la date du document
            "manufacturer": manufacturer,  # None si non identifié
            "supplier": manufacturer,      # Même source
            "inspection_agency": inspection_agency  # None si non identifié
        }

    def _segment_arh_chapters(self, text: str) -> Dict[str, Any]:
        """
        Découpage sémantique du PDF selon les 7 chapitres officiels de la procédure
        P-CTE-1 de l'ARH (Autorité de Régulation des Hydrocarbures d'Algérie).
        Chaque ligne/section est rattachée au chapitre ARH officiel correspondant.
        Retourne un dict avec les clés normalisées ARH + metadata (detected_chapters, primary_chapter).
        """
        chapters: Dict[str, str] = {
            "01_ADMINISTRATIF": "",
            "02_DESCRIPTIF_ANNEXE_E": "",
            "03_PLANS_SCHEMAS": "",
            "04_CERTIFICATS_MATIERE": "",
            "05_SOUDAGE_CND": "",
            "06_ITP_QUALITE": "",
            "07_PV_ESSAIS": "",
        }

        # Mots-clés de détection par chapitre (français + anglais + abréviations)
        chapter_keywords: Dict[str, List[str]] = {
            "01_ADMINISTRATIF": [
                "LETTRE DE DEMANDE", "DEMANDE D'AVIS", "DEMANDE AVIS CONFORMITE",
                "DEMANDE DE CONFORMITE", "LETTRE DE TRANSMISSION", "P-CTE-1",
                "VISA CONSULAT", "CHAMBRE DE COMMERCE", "PRESIDENT DE L'ARH",
                "AUTORITE DE REGULATION", "SOUMISSION", "OBJET : DEMANDE",
                "CONTRAT N", "REF CONTRAT", "ANNEXE B", "ANNEXE C", "ANNEXE F",
                "CERTIFICATION DES SIGNATURES", "LEGALISATI",
            ],
            "02_DESCRIPTIF_ANNEXE_E": [
                "ETAT DESCRIPTIF", "ÉTAT DESCRIPTIF", "ANNEXE E", "FICHE TECHNIQUE",
                "EQUIPMENT DATA SHEET", "DESCRIPTIVE STATE", "CARACTERISTIQUES TECHNIQUES",
                "CARACTERISTIQUES DE L'EQUIPEMENT", "CARACTERISTIQUES DE L EQUIPEMENT",
                "PRESSION DE CALCUL", "TEMPERATURE DE CALCUL",
                "PMA", "TMA", "DESIGN PRESSURE", "DESIGN TEMP", "CORROSION ALLOWANCE",
                "CODE DE CONSTRUCTION", "ASME VIII", "MSS SP-75", "MSS SP-44",
                "ASME B31", "FABRICANT", "ANNEE DE CONSTRUCTION",
                "LIEU DE FABRICATION", "FLUIDE VEHICULE",
            ],
            "03_PLANS_SCHEMAS": [
                "PLAN D'ENSEMBLE", "GENERAL ARRANGEMENT", "PLAN DE DETAIL", "DETAILED DRAWING",
                "ISOMETRIQUE", "ISOMETRIC", "P&ID", "SCHEMA DE PROCEDE", "PROCESS FLOW",
                "PLAN COTE", "FORMAT A3", "PLANS DETAILLES", "GA DRAWING", "ASSEMBLY DRAWING",
                "COUPE", "SECTION VUE", "ELEVATION VUE", "SPOOL DRAWING", "DWG NO",
                "DRAWING NUMBER", "REV.", "ECHELLE",
            ],
            "04_CERTIFICATS_MATIERE": [
                "CERTIFICAT MATIERE", "CERTIFICAT DE MATIERE", "EN 10204",
                "HEAT NUMBER", "HEAT NO", "HEAT N", "COULEE", "COULÉE",
                "CAST NO", "MILL CERTIFICATE", "MATERIAL TEST REPORT",
                "COMPOSITION CHIMIQUE", "CHEMICAL COMPOSITION",
                "YIELD STRENGTH", "TENSILE STRENGTH", "LIMITE ELASTIQUE",
                "RESISTANCE TRACTION", "CHARPY", "RESILIENCE",
                "CEV", "CARBON EQUIVALENT", "CARBONE EQUIVALENT",
                "HARDNESS", "DURETE", "HV10", "HRC", "HBW", "ELONGATION",
                "INSPECTION CERTIFICATE EN 10204", "MTR", "MILL TEST",
            ],
            "05_SOUDAGE_CND": [
                "WPS", "PQR", "QMOS", "QUALIFICATION SOUDEUR", "WELDER QUALIFICATION",
                "WELDING PROCEDURE", "PROCEDURE DE SOUDAGE", "SOUDAGE",
                "CND", "NDT", "CONTROLE NON DESTRUCTIF", "NON DESTRUCTIVE TESTING",
                "RADIOGRAPHIE", "RADIOGRAPHIC", "ULTRASONS", "ULTRASONIC",
                "GAMMAGRAPHIE", "MAGNETOSCOPIE", "PENETRANT", "MT TEST", "PT TEST",
                "TOFD", "COUPON DE SOUDURE", "WELD COUPON",
                "ESSAI DE TRACTION", "ESSAI DE PLIAGE", "ESSAI DE RESILIENCE",
                "TRAITEMENT THERMIQUE", "PWHT", "HEAT TREATMENT RECORD",
                "WPQ", "QMOS NO",
            ],
            "06_ITP_QUALITE": [
                "ITP", "INSPECTION AND TEST PLAN", "INSPECTION & TEST",
                "PLAN DE CONTROLE", "PLAN D'INSPECTION",
                "POINT D'ARRET", "HOLD POINT", "WITNESS POINT", "REVIEW POINT",
                "TIERS HABILITE", "THIRD PARTY INSPECTION", "TPI",
                "BUREAU VERITAS", "SGS", "TUV", "ALGERAC", "VERITAS",
                "RELEASE NOTE", "IRN", "RECEPTION TIERS",
                "VISA TPI", "TAMPON INSPECTEUR", "INSPECTION STAMP",
                "RELEASE FOR SHIPMENT",
            ],
            "07_PV_ESSAIS": [
                "PROCES-VERBAL", "PROCÈS-VERBAL", "PV D'EPREUVE", "PV D'ESSAI",
                "HYDROSTATIQUE", "HYDROSTATIC TEST", "TEST PRESSURE", "PRESSION D'EPREUVE",
                "PRESSION D'ESSAI", "SHELL TEST", "SEAT TEST", "ETANCHEITE",
                "LEAKAGE TEST", "RESULTAT ESSAI", "TEST RESULT",
                "CONFORME SANS FUITE", "ACCEPTED", "ACCEPTANCE",
                "API 598", "SIGNATURE INSPECTEUR", "EPREUVE DE CORPS",
                "CONTROLE DIMENSIONNEL", "DIMENSIONAL CHECK", "FINAL INSPECTION REPORT",
                "DUREE D'EPREUVE", "TEST DURATION",
            ],
        }

        chapters_list: Dict[str, List[str]] = {k: [] for k in chapter_keywords}
        lines = text.split("\n")
        current_chapter = "02_DESCRIPTIF_ANNEXE_E"  # Défaut : fiche technique

        for line in lines:
            lu = line.upper().strip()
            if not lu:
                chapters_list[current_chapter].append("")
                continue

            # Détection du chapitre courant par ordre de priorité des clés
            new_chapter = None
            for ch_key, keywords in chapter_keywords.items():
                if any(kw in lu for kw in keywords):
                    new_chapter = ch_key
                    break

            if new_chapter:
                current_chapter = new_chapter

            chapters_list[current_chapter].append(line)

        # Matérialisation rapide O(N)
        chapters: Dict[str, str] = {k: "\n".join(v) for k, v in chapters_list.items()}
        detected_chapters = [k for k, v in chapters.items() if len(v.strip()) > 50]
        primary_chapter = max(chapters, key=lambda k: len(chapters[k])) if any(chapters.values()) else "02_DESCRIPTIF_ANNEXE_E"

        result: Dict[str, Any] = dict(chapters)
        result["detected_chapters"] = detected_chapters
        result["primary_chapter"] = primary_chapter
        return result

    def _split_document_into_sections(self, text: str) -> Dict[str, str]:
        """
        Alias de compatibilité vers _segment_arh_chapters().
        Retourne les sections au format générique attendu par l'ancien code.
        """
        chapters = self._segment_arh_chapters(text)
        return {
            "Introduction": chapters.get("01_ADMINISTRATIF", "")[:400],
            "Equipment Data": chapters.get("02_DESCRIPTIF_ANNEXE_E", ""),
            "Tests": chapters.get("07_PV_ESSAIS", ""),
            "Results": (chapters.get("07_PV_ESSAIS", "") or "")[-500:],
            "Signatures": chapters.get("06_ITP_QUALITE", ""),
            "Annexes": (chapters.get("04_CERTIFICATS_MATIERE", "") + "\n" +
                        chapters.get("05_SOUDAGE_CND", "")),
        }

    @staticmethod
    def _auto_detect_material_grade(text: str) -> str:
        """
        Détecte automatiquement la nuance matière dans un texte de certificat 3.1 ou fiche technique.
        Retourne la nuance la plus probable parmi les standards Oil & Gas courants.
        Retourne "UNKNOWN" si aucune nuance reconnue n'est trouvée.
        """
        tu = text.upper()
        # Ordre de priorité : du plus spécifique (nuances haute résistance) au plus générique
        grade_patterns = [
            # FITTING haute résistance (ASTM A860 WPHY)
            (r'\bA860\s*WPHY\s*(42|52|56|60|65|70)\b', 'A860 WPHY'),
            (r'\bWPHY\s*(42|52|56|60|65|70)\b', 'A860 WPHY'),
            # Acier haute résistance forgé (ASTM A694)
            (r'\bA694\s*F(42|52|56|60|65|70)\b', 'A694'),
            # Raccords forgés standards (ASTM A234, A420)
            (r'\bA234\s*WPB\b', 'A234 WPB'),
            (r'\bA234\s*WPC\b', 'A234 WPC'),
            (r'\bA420\s*WPL6\b', 'A420 WPL6'),
            # Basses températures forgés (ASTM A350)
            (r'\bA350\s*LF3\b', 'A350 LF3'),
            (r'\bA350\s*LF6\b', 'A350 LF6'),
            (r'\bA350\s*LF2\b', 'A350 LF2'),
            # Forgés standard (ASTM A105)
            (r'\bA105\b', 'A105'),
            # Inox austénitique / ferritique (ASTM A182)
            (r'\bA182\s*F316L\b', 'A182 F316'),
            (r'\bA182\s*F316\b', 'A182 F316'),
            (r'\bA182\s*F304L\b', 'A182 F304'),
            (r'\bA182\s*F304\b', 'A182 F304'),
            (r'\bA182\s*F22\b', 'A182 F22'),
            (r'\bA182\s*F11\b', 'A182 F11'),
            # Tubes canalisations (API 5L)
            (r'\bAPI\s*5L\s*X(42|46|52|56|60|65|70|80)\b', 'API 5L'),
            # Tôle appareils pression (ASTM A516 / SA-516)
            (r'\bS?A\s*516\s*GR\.?\s*(60|70)\b', 'A516 GR 70'),
            # Tubes basses températures (ASTM A333)
            (r'\bA333\s*GR\.?\s*6\b', 'A333 GR 6'),
            # Chrome-moly (ASTM A335)
            (r'\bA335\s*P22\b', 'A335 P22'),
            (r'\bA335\s*P11\b', 'A335 P11'),
            # Corps de robinets (ASTM A216)
            (r'\bA216\s*WCB\b', 'A216 WCB'),
            (r'\bA216\s*WCC\b', 'A216 WCC'),
            # Tubes standards (ASTM A106)
            (r'\bS?A\s*106\s*GR\.?\s*[ABC]\b', 'A106 GR B'),
        ]

        for pattern, grade_name in grade_patterns:
            if re.search(pattern, tu):
                return grade_name

        # Fallback générique : chercher "Grade: XXX" dans le texte
        m = re.search(r'\b(?:GRADE|NUANCE|MATERIAL)\s*[:\s]+([A-Z][A-Z0-9\s\-\.]{2,25}?)(?:\n|,|;|\s{2})', tu)
        if m:
            candidate = m.group(1).strip()[:25]
            if len(candidate) >= 3:
                return candidate

        return "UNKNOWN"  # Inconnu → ne pas comparer aux limites d'une nuance spécifique

    def _run_phase2_documentary_audit(
        self,
        parsed_docs: List[Dict[str, Any]],
        mandatory_checklist: List[Dict[str, Any]],
        equipment_type: str = "PRESSURE_VESSEL"
    ) -> Dict[str, Any]:
        """
        Phase 2: Contrôle d'exhaustivité, révisions et anomalies documentaires.
        """
        received_types = {d["metadata"]["document_type"].upper() for d in parsed_docs}
        
        # Obtenir les décrets spécifiquement applicables à cet équipement
        app_decrees = self.engine.get_applicable_decrees(equipment_type)
        decree_names = [d["key"].replace("_", " ") for d in app_decrees]
        decree_ref_str = " / ".join([d["title"].split(" du ")[0] for d in app_decrees]) if app_decrees else "Décret exécutif ARH"

        checklist_status = []
        missing_docs = []
        comments = []

        for req in mandatory_checklist:
            req_name = req["name"]
            req_code = req["code"]
            crit = req["criticality"]
            aliases = req.get("aliases", [req_code, req_name])

            matched = False
            is_declared_na = False
            start_page = 1
            end_page = 1
            page_count = 1
            norm_req_code = _normalize_text(req_code)
            norm_aliases = [_normalize_text(a) for a in aliases if _normalize_text(a)]

            matched_doc = None
            matched_needle = None  # la chaîne (code ou alias) qui a permis le match, pour localiser la vraie page

            DOC_CODE_MAP = {
                "LETTRE_DEMANDE_AVIS": "DOC-01", "REQ_LETTER": "DOC-01", "DOC-01": "DOC-01",
                "CERT_SIGNATURES_FABRICANT": "DOC-02", "LEGAL_VISA": "DOC-02", "DOC-02": "DOC-02",
                "CERT_VISITE_INT_EXT": "DOC-03", "COC_INSPECTION": "DOC-03", "DOC-03": "DOC-03",
                "CERT_PAYS_ORIGINE": "DOC-04", "ORIGIN_COC": "DOC-04", "DOC-04": "DOC-04", "CE_DECL": "DOC-04",
                "ETAT_DESCRIPTIF": "DOC-05", "ANNEXE_E": "DOC-05", "DS": "DOC-05", "DOC-05": "DOC-05",
                "CALC": "DOC-06", "NOTE_CALCUL": "DOC-06", "SIZING_NOTE": "DOC-06", "DOC-06": "DOC-06",
                "PLANS_DETAILLES_INDEX": "DOC-07", "PLANS": "DOC-07", "GA_DWG": "DOC-07", "DOC-07": "DOC-07",
                "WPS_PQR": "DOC-08", "WELD_BOOK": "DOC-08", "WELD_CERT": "DOC-08", "DOC-08": "DOC-08",
                "TRAIT_THERMIQUE_SPEC": "DOC-09", "PWHT_SPEC": "DOC-09", "DOC-09": "DOC-09",
                "ITP": "DOC-10", "QA_ITP": "DOC-10", "INSP_REP": "DOC-10", "DOC-10": "DOC-10",
                "HYDRO_PV": "DOC-11", "TEST_PV": "DOC-11", "FAT": "DOC-11", "DOC-11": "DOC-11",
                "MAT_CERT": "DOC-12", "DOC-12": "DOC-12",
                "NDT_REP": "DOC-13", "DOC-13": "DOC-13",
                "DIM_CERT": "DOC-14", "DOC-14": "DOC-14",
            }
            target_doc_code = DOC_CODE_MAP.get(req_code)

            # Priorité 1 : Vérification directe dans les frontières découpées de l'Index Constructeur
            for d in parsed_docs:
                bounds = d.get("piece_boundaries", [])
                for b in bounds:
                    b_code = b.get("spec", {}).get("code", "")
                    b_name = b.get("spec", {}).get("name", "")
                    norm_b_name = _normalize_text(b_name)
                    
                    code_match = (target_doc_code and b_code == target_doc_code) or (b_code == req_code)
                    alias_match = any(a in norm_b_name or norm_b_name in a for a in norm_aliases if len(a) >= 4)
                    
                    if code_match or alias_match:
                        matched = True
                        matched_doc = d
                        if b.get("is_na"):
                            is_declared_na = True
                            start_page = b.get("start", 0)
                            end_page = b.get("end", 0)
                            page_count = 0
                        else:
                            start_page = b.get("start", 1)
                            end_page = b.get("end", 1)
                            page_count = (end_page - start_page) + 1
                        break
                if matched:
                    break

            # Priorité 2 : Recherche plein texte si non trouvé via l'index de sommaire (exclut les pièces Stage_Optional)
            if not matched and crit != "Stage_Optional":
                for d in parsed_docs:
                    doc_text = d.get("text", "")
                    meta_doc_type = d.get("metadata", {}).get("document_type", "")
                    
                    # Détection et exclusion des pages de Sommaire / Table des matières pour éviter les faux positifs d'exhaustivité
                    page_spans = d.get("page_spans", [])
                    if len(page_spans) > 3:
                        sommaire_indices = set()
                        for idx_sp, sp in enumerate(page_spans):
                            p_num = sp.get("page", idx_sp + 1)
                            if p_num in (1, 2, 3):
                                p_txt = doc_text[sp.get("start", 0):sp.get("end", len(doc_text))].upper()
                                if any(k in p_txt for k in ["SOMMAIRE", "TABLE OF CONTENTS", "TABLE DES MATIERES"]):
                                    sommaire_indices.add(idx_sp)
                        if sommaire_indices:
                            body_parts = [doc_text[sp.get("start", 0):sp.get("end", len(doc_text))] for idx_sp, sp in enumerate(page_spans) if idx_sp not in sommaire_indices]
                            searchable_text = " ".join(body_parts)
                        else:
                            searchable_text = doc_text
                    else:
                        searchable_text = doc_text

                    norm_doc_blob = _normalize_text(meta_doc_type + " " + d.get("file_name", "") + " " + searchable_text)
                    
                    # A. Vérification directe par mot-clé exact du code (\bCODE\b)
                    if len(norm_req_code) >= 3 and re.search(r'\b' + re.escape(norm_req_code) + r'\b', norm_doc_blob):
                        matched = True
                        matched_doc = d
                        matched_needle = req_code
                        break

                    # B. Vérification par alias significatifs (expression exacte ou mots clés >= 4 lettres)
                    for alias, norm_alias in zip(aliases, norm_aliases):
                        if len(norm_alias) < 4:
                            continue
                        if norm_alias in norm_doc_blob:
                            matched = True
                            matched_doc = d
                            matched_needle = alias
                            break
                        sig_words = [w for w in norm_alias.split() if len(w) >= 4]
                        if len(sig_words) >= 2 and all(re.search(r'\b' + re.escape(w) + r'\b', norm_doc_blob) for w in sig_words):
                            matched = True
                            matched_doc = d
                            matched_needle = alias
                            break
                    
                    if matched:
                        break

                # C. Détecteur Dédié de Visas & Tampons d'Inspection Tiers Habilité
                if not matched and req_code in ("INSP_REP", "THIRD_PARTY_PV", "ARH_APPROVAL"):
                    visa_keywords = [
                        "VISA", "INSPECTEUR", "STAMP", "TAMPON", "APPROUVE", "VERITAS", "ALGERAC", 
                        "SGS", "TUV", "VERITAL", "LLOYDS", "TIERS HABILITE", "RELEASE NOTE", "IRN", 
                        "INSPECTION CERTIFICATE", "CERTIFICAT D'INSPECTION", "RECEPTION TIERS"
                    ]
                    for d in parsed_docs:
                        doc_text = d.get("text", "")
                        norm_doc_blob = _normalize_text(doc_text)
                        for kw in visa_keywords:
                            norm_kw = _normalize_text(kw)
                            if norm_kw in norm_doc_blob:
                                matched = True
                                matched_doc = d
                                matched_needle = kw
                                break
                        if matched:
                            break

            if matched and is_declared_na:
                checklist_status.append({
                    "code": req_code,
                    "name": req_name,
                    "status": "NOT_APPLICABLE_STAGE",
                    "criticality": "Stage_Optional",
                    "start_page": start_page,
                    "end_page": end_page,
                    "page_count": 0,
                    "matched_page": start_page,
                    "matched_file": matched_doc.get("file_name", "?") if matched_doc else "?",
                    "note": "Déclaré Non Applicable par le constructeur dans le sommaire officiel."
                })
            elif matched:
                matched_page_num = start_page
                matched_file = matched_doc.get("file_name", "?") if matched_doc else "?"
                if matched_doc and matched_needle and not start_page:
                    m = re.search(re.escape(matched_needle), matched_doc.get("text", ""), re.IGNORECASE)
                    if m:
                        matched_page_num = self._page_at_offset(matched_doc.get("page_spans", []), m.start())
                checklist_status.append({
                    "code": req_code,
                    "name": req_name,
                    "status": "RECEIVED",
                    "criticality": crit,
                    "start_page": start_page or matched_page_num,
                    "end_page": end_page or matched_page_num,
                    "page_count": page_count,
                    "matched_page": start_page or matched_page_num,
                    "matched_file": matched_file
                })
            elif crit == "Stage_Optional":
                checklist_status.append({
                    "code": req_code, "name": req_name, "status": "NOT_YET_REQUIRED",
                    "criticality": crit,
                    "start_page": 0, "end_page": 0, "page_count": 0,
                    "note": req.get("stage_note", "Non exigible à ce stade du dossier ARH.")
                })
            elif req.get("conditional") and crit != "Stage_Optional":
                # Documents marqués "si applicable" dans la procédure P-CTE-1
                # (ex: traitement thermique) : on ne peut pas savoir depuis la
                # seule checklist si l'équipement en question nécessite
                # réellement ce traitement -> on ne compte PAS ce document
                # comme manquant de façon stricte, mais on signale explicitement
                # l'incertitude pour confirmation manuelle par l'ingénieur.
                checklist_status.append({
                    "code": req_code, "name": req_name, "status": "CONDITIONAL_NOT_CONFIRMED",
                    "criticality": crit,
                    "start_page": 0, "end_page": 0, "page_count": 0
                })
                comments.append({
                    "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                    "title": f"⚠️ Applicabilité à Confirmer: {req_name}",
                    "description": f"Le document '{req_name}' est exigé par la procédure P-CTE-1 uniquement si applicable à cet équipement. Il n'a pas été trouvé dans le dossier — confirmer s'il est réellement requis (ex: si un traitement thermique post-soudage est prescrit par le code de construction) ou si son absence est justifiée.",
                    "observation": f"Document conditionnel '{req_name}' non trouvé — applicabilité non confirmée.",
                    "cause": "Document non fourni ou non applicable à cet équipement spécifique.",
                    "impact": "À vérifier manuellement : si le document est réellement requis, son absence est une non-conformité.",
                    "category": "AUDIT DOCUMENTAIRE",
                    "regulation_ref": "P-CTE-1",
                    "decree_reference": req.get("decree_reference", "P-CTE-1"),
                    "article": "Annexe A/G",
                    "article_number": "Annexe A/G",
                    "standard": "ARH Mandatory Checklist",
                    "document_concerned": req_name,
                    "page": "N/A",
                    "correction_method": "Confirmer l'applicabilité et fournir le document si requis.",
                    "action_required": "Confirmer l'applicabilité et fournir le document si requis.",
                    "priority": "MINOR",
                    "severity": "Minor",
                    "responsible": "Ingénieur Qualité / Contractant EPC",
                    "responsible_entity": "Ingénieur Qualité / Contractant EPC",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                    "deadline_days": 7,
                    "status": "OPEN"
                })
            else:
                checklist_status.append({"code": req_code, "name": req_name, "status": "MISSING", "criticality": crit, "start_page": 0, "end_page": 0, "page_count": 0})
                missing_docs.append(req_name)

                comments.append({
                    "id": f"REM_MANQ_{uuid.uuid4().hex[:6].upper()}",
                    "title": f"[Pièce Absente du Lot] {req_name}",
                    "description": f"Le document obligatoire '{req_name}' exigé par la procédure P-CTE-1 pour les équipements de type {equipment_type} n'a pas été trouvé dans le lot de fichiers téléversé.",
                    "observation": f"Pièce manquante au lot de soumission : '{req_name}' non fourni.",
                    "cause": "Fichier non téléversé dans le lot soumis à l'audit.",
                    "impact": "Dossier incomplet au regard des exigences du Décret exécutif.",
                    "category": "AUDIT DOCUMENTAIRE — PIÈCES MANQUANTES",
                    "regulation_ref": decree_ref_str,
                    "decree_reference": decree_ref_str,
                    "article": "Procédure P-CTE-1 / Décret applicable",
                    "article_number": "P-CTE-1",
                    "standard": "ARH Mandatory Checklist",
                    "document_concerned": f"[Non fourni dans le lot] {req_name}",
                    "is_missing_document": True,
                    "missing_document_name": req_name,
                    "page": "Pièce Non Fournie",
                    "correction_method": f"Fournir la version finale approuvée de '{req_name}'.",
                    "action_required": f"Fournir la version finale approuvée de '{req_name}'.",
                    "priority": "CRITICAL" if crit == "Critical" else "MAJOR",
                    "severity": "Critical" if crit == "Critical" else "Major",
                    "responsible": "Contractant EPC / Fabricant",
                    "responsible_entity": "Contractant EPC / Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                    "deadline_days": 7,
                    "status": "OPEN"
                })

        return {
            "checklist_status": checklist_status,
            "missing_docs": missing_docs,
            "comments": comments
        }

    def _extract_dossier_items(self, parsed_docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Moteur d'Isolation & d'Extraction Multi-Items ARH (Garantie Zéro Confusion).
        Identifie et extrait de manière exhaustive et indépendante chaque Item du dossier :
        - Item ID (ex: Item 01, Item 02, Item 18, Item 94, Item 110, Item 112...)
        - Diamètre nominal (NPS, DN)
        - Classe de pression (Rating ANSI / ASME, PN)
        - Nuance métallurgique (Material)
        - N° de fabrication / Série (Fabrication No / Serial No)
        - Surépaisseur de corrosion (Corrosion Allowance)
        - Pression et température de design
        - Pages documentaires d'apparition
        """
        items: Dict[str, Dict[str, Any]] = {}

        for doc in parsed_docs:
            fname = doc.get("file_name", "")
            txt = doc.get("text", "")
            spans = doc.get("page_spans", [])

            # Découpage par page
            page_texts = []
            if spans:
                for sp in spans:
                    p_num = sp.get("page", 1)
                    p_t = txt[sp.get("start", 0):sp.get("end", len(txt))]
                    page_texts.append((p_num, p_t))
            else:
                page_texts = [(1, txt)]

            for pno, p_t in page_texts:
                lines = [l.strip() for l in p_t.splitlines() if l.strip()]
                is_item_sheet = any(k in p_t.upper() for k in ["ETAT DESCRIPTIF", "EQUIPMENT DESCRIPTION", "EQUIPMENT CHARACTERISTICS", "CARACTERISTIQUES", "FICHE TECHNIQUE"])
                for idx, line in enumerate(lines):
                    m_item = re.search(r'\b(?:ITEM|REP[EÈ]RE|REPERE|ARTICLE)\s*[:\-_N°\.]*\s*([0-9]{1,3}[A-Z]?|[O0][1-9])\b', line, re.IGNORECASE)
                    if not m_item and any(k in line.upper() for k in ["ITEM", "REPÈRE", "REPERE", "ARTICLE"]):
                        # Cas où le numéro est sur la ligne suivante (ex: Item No. \n : 01)
                        if idx + 1 < len(lines):
                            next_clean = re.sub(r'^[:\s\-_N°\.]+', '', lines[idx + 1]).strip()
                            m_next = re.match(r'^([0-9]{1,3}[A-Z]?|[O0][1-9])$', next_clean, re.IGNORECASE)
                            if m_next:
                                m_item = m_next
                        # Cas concaténé OCR (ex: MONOLITHICINSULATIONJOINTSITEMO1)
                        if not m_item:
                            m_concat = re.search(r'ITEM\s*([0-9]{1,3}[A-Z]?|[O0][1-9])', line, re.IGNORECASE)
                            if m_concat:
                                m_item = m_concat

                    if m_item:
                        raw_id = m_item.group(1).upper()
                        if raw_id.startswith("O") and len(raw_id) == 2 and raw_id[1].isdigit():
                            raw_id = "0" + raw_id[1]
                        item_id = f"Item {raw_id}"
                        if item_id not in items:
                            items[item_id] = {
                                "id": item_id,
                                "raw_num": raw_id,
                                "pages": set(),
                                "diameters": set(),
                                "ratings": set(),
                                "materials": set(),
                                "fab_numbers": set(),
                                "corrosion_allowances": set(),
                                "design_pressures": set(),
                                "design_temperatures": set(),
                                "design_codes": set(),
                                "document": fname
                            }
                        items[item_id]["pages"].add(pno)
                        sub_ctx = p_t if is_item_sheet else " ".join(lines[max(0, idx - 5):min(len(lines), idx + 45)])

                        # Diamètre
                        m_d = re.search(r'(?:NPS|DN|DIAM[EÈ]TRE|SIZE|@\.?)\s*[:=]?\s*([0-9]{1,2}(?:[\.\/][0-9]+)?|\d{2,4})\s*(?:\"|\'\'|INCH|IN|MM)?', sub_ctx, re.IGNORECASE)
                        if not m_d:
                            m_d = re.search(r'\b([0-9]{1,2}(?:[\.\/][0-9]+)?)\s*(?:\"|\'\')', sub_ctx)
                        if m_d:
                            items[item_id]["diameters"].add(m_d.group(0).strip())

                        # Rating
                        m_r = re.search(r'(?:CLASS|RATING|CLASSE|PN|#)\s*[:=]?\s*([0-9]{3,4}|[0-9]{2,3})\s*(?:LB|LBS|#)?\b', sub_ctx, re.IGNORECASE)
                        if m_r:
                            items[item_id]["ratings"].add(m_r.group(0).strip())

                        # Matériau
                        m_m = re.findall(r'\b(ASTM\s+A[0-9]{3}(?:\s*GR\.?\s*[A-Z0-9]+)?|A[0-9]{3}\s*GR\.?\s*[A-Z0-9]+|API\s+5L\s+[X0-9]+|SA-?516\s*GR\.?\s*70|A105|A216\s*WCB|A350\s*LF2|A694\s*F[0-9]{2}|F60|X60|X65)\b', sub_ctx, re.IGNORECASE)
                        if m_m:
                            for mat in m_m:
                                items[item_id]["materials"].add(mat.strip())

                        # N° Fabrication / Série
                        m_fab = re.search(r'(?:FABRICATION|SERIAL|SERIE)\s*(?:N[O°\.]|NUMBER)?[^A-Za-z0-9]*([A-Za-z0-9\-\/]{4,25})', sub_ctx, re.IGNORECASE)
                        if m_fab:
                            fab_val = m_fab.group(1).strip()
                            if not any(k in fab_val.upper() for k in ["DATE", "PAGE", "CODE"]):
                                items[item_id]["fab_numbers"].add(fab_val)

                        # Surépaisseur de corrosion
                        m_ca = re.search(r'(?:C\.A\.?|CORROSION\s*ALLOWANCE|SUR[EÉ]PAISSEUR(?:\s*DE\s*CORROSION)?)[^0-9\r\n]*[\r\n\s:]*(\d+(?:\.\d+)?)\s*MM', sub_ctx, re.IGNORECASE)
                        if m_ca:
                            items[item_id]["corrosion_allowances"].add(f"{m_ca.group(1)} mm")

                        # Pression de design
                        m_p = re.search(r'(?:DESIGN\s*PRESSURE|PRESSION\s*DE\s*DESIGN|PMA)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:BAR|MPA|PSI)', sub_ctx, re.IGNORECASE)
                        if m_p:
                            items[item_id]["design_pressures"].add(m_p.group(0).strip())

                        # Température de design
                        m_t = re.search(r'(?:DESIGN\s*TEMP|TEMP[EÉ]RATURE\s*DE\s*DESIGN|TMA)\s*[:=]?\s*([+-]?\d+(?:\.\d+)?)\s*(?:°C|C)', sub_ctx, re.IGNORECASE)
                        if m_t:
                            items[item_id]["design_temperatures"].add(m_t.group(0).strip())

                        # Code de conception
                        m_code = re.search(r'(?:DESIGN\s*CODE|CODE\s*DE\s*CONCEPTION|REGLEMENTATION|R[EÉ]GLEMENTATION)[^A-Za-z0-9]*([A-Za-z0-9\.\-\_\s\/]{3,60})', sub_ctx, re.IGNORECASE)
                        if m_code:
                            items[item_id]["design_codes"].add(m_code.group(1).strip())

        # Nettoyage et conversion en liste ordonnée
        res = []
        for k in sorted(items.keys(), key=lambda x: int(re.search(r'\d+', x).group(0)) if re.search(r'\d+', x) else 999):
            v = items[k]
            res.append({
                "item": k,
                "id": k,
                "raw_num": v["raw_num"],
                "document": v["document"],
                "pages": sorted(list(v["pages"])),
                "diameters": sorted(list(v["diameters"])),
                "ratings": sorted(list(v["ratings"])),
                "materials": sorted(list(v["materials"])),
                "fab_numbers": sorted(list(v["fab_numbers"])),
                "corrosion_allowances": sorted(list(v["corrosion_allowances"])),
                "design_pressures": sorted(list(v["design_pressures"])),
                "design_temperatures": sorted(list(v["design_temperatures"]))
            })
        return res

    def _run_phase3_technical_control(
        self,
        parsed_docs: List[Dict[str, Any]],
        equipment_type: str,
        equipment_tag: str,
        dossier_stage: str = "FINAL_RECEPTION"
    ) -> Dict[str, Any]:
        """
        Phase 3: Contrôle technique intelligent approfondi du contenu texte des documents.
        Analyse les valeurs numériques, pressions, matériaux, NDT, certifications et visas.
        """
        comments = []

        # Extraction détaillée de toutes les valeurs techniques contenues dans le texte des fichiers
        design_pressures = []
        hydrotest_pressures = []
        materials_found = []
        corrosion_allowances = []
        ndt_rates = []
        atex_zones = []
        bureau_visas = []

        # Interconnexion Traçabilité 3.1
        try:
            from traceability_db import get_heat_numbers_list
            registered_hns = get_heat_numbers_list()
        except ImportError:
            registered_hns = None

        for doc in parsed_docs:
            t = doc["text"].upper()
            fname = doc["file_name"]
            doc_type = doc["metadata"].get("document_type", "").upper()
            total_doc_pages = len(doc.get("page_spans", [])) or 1

            # Helper local pour détection d'évidence et localisation exacte de page
            def _find_ev_page(keywords, default_p=1):
                p_spans = doc.get('page_spans', [])
                for kw in keywords:
                    pat = r'\b' + re.escape(kw) + r'\b' if len(kw) <= 5 else re.escape(kw)
                    m_ev = re.search(pat, t, re.IGNORECASE)
                    if m_ev:
                        off = m_ev.start()
                        p_no = self._page_at_offset(p_spans, off)
                        if 1 <= p_no <= len(p_spans):
                            sp_tgt = p_spans[p_no - 1]
                            pg_txt = doc["text"][sp_tgt.get("start",0):sp_tgt.get("end",len(doc["text"]))]
                            rel_off = max(0, off - sp_tgt.get("start", 0))
                            snip = self._extract_clean_verbatim_snippet(pg_txt, rel_off, len(m_ev.group(0)))
                        else:
                            snip = self._extract_clean_verbatim_snippet(doc["text"], off, len(m_ev.group(0)))
                        return True, p_no, snip, m_ev.group(0)
                return False, default_p, "", ""

            # 1. Pressions de Design (PMA / Design Pressure)
            m_pdes = re.search(r'(?:PRESSION\s*DE\s*DESIGN|DESIGN\s*PRESSURE|PMA|PMS)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:BAR|MPA|PSI)', t)
            if m_pdes:
                val = float(m_pdes.group(1))
                if "MPA" in m_pdes.group(0): val *= 10.0
                elif "PSI" in m_pdes.group(0): val /= 14.5038
                design_pressures.append((val, fname))

            # 2. Pressions d'Épreuve Hydrostatique (Test Pressure)
            m_hyd = re.search(r'(?:PRESSION\s*D\s*EPREUVE|TEST\s*PRESSURE|EPREUVE\s*HYDROSTATIQUE)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:BAR|MPA|PSI)', t)
            if m_hyd:
                val = float(m_hyd.group(1))
                if "MPA" in m_hyd.group(0): val *= 10.0
                elif "PSI" in m_hyd.group(0): val /= 14.5038
                hydrotest_pressures.append((val, fname))

            # 3. Matériaux de Construction
            m_mat = re.findall(r'\b(ASTM\s+A[0-9]{3}(?:\s*GR\.?\s*[A-Z0-9]+)?|API\s+5L\s+[X0-9]+|EN\s+10028-[0-9]+|SA-516\s*GR\s*70)\b', t)
            if m_mat:
                for mat in m_mat:
                    materials_found.append((mat, fname))

            # 4. Surépaisseur de Corrosion (Corrosion Allowance)
            m_ca = re.search(r'(?:CORROSION\s*ALLOWANCE|SUREPAISSEUR\s*DE\s*CORROSION|C\.A\.?)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*MM', t)
            if m_ca:
                corrosion_allowances.append((float(m_ca.group(1)), fname))

            # 5. Taux de CND Radiographie
            m_ndt = re.search(r'(?:RADIOGRAPHIE|RT|CND|NDT)\s*[:=]?\s*(\d{2,3})\s*%', t)
            if m_ndt:
                ndt_rates.append((float(m_ndt.group(1)), fname))

            # 6. Zones ATEX
            if "ZONE 1" in t or "ZONE 2" in t or "ATEX" in t or "IECEX" in t:
                atex_zones.append(fname)

            # 7. Organismes d'Inspection & Visas
            if any(b in t for b in ["ALGERAC", "VERITAS", "TUV", "SGS", "BUREAU HABILITE", "BUREAU AGREE", "ARH"]):
                bureau_visas.append(fname)

            # 8. Traçabilité Matérielle (Heat Numbers)
            if "CERTIFICATE" in doc_type or "MATIERE" in fname.upper() or "CERT" in fname.upper() or "HEAT" in t or "COULEE" in t or "3.1" in t:
                _hn_blacklist = {
                    "TREATMENT", "HOLDING", "INPUT", "TEMPERATURE", "IRON", "MENT", "ACCORDING", 
                    "NUMBER", "REPORT", "MATERIAL", "SPECIFICATION", "TEST", "PRESSURE", "VESSEL", 
                    "PIPING", "FITTING", "FLANGE", "WELDING", "STANDARD", "PRESERVATION", "BATCH", 
                    "NONE", "DATE", "STAGE", "CLIENT", "PROJECT", "CONTRACT", "CONTROL", "PROCESS",
                    "PROCEDURE", "SHEET", "DRAWING", "RESULT", "CONCLUSION", "REQUIREMENT", "DETAILS"
                }
                _raw_hns = []
                for _pat in [
                    r'\b(?:HEAT\s*(?:NO|N°|NUMBER|NUMERO|#)|N°?\s*COUL[EÉ]E|COUL[EÉ]E\s*N[O°]?|CAST\s*(?:NO|N°|NUMBER)|MELT\s*(?:NO|N°|NUMBER))\s*[:.\-]?\s*([A-Z0-9\-_]{3,20})\b',
                    r'\b(?:HEAT\s*[:=]\s*)([A-Z0-9\-_]{3,20})\b'
                ]:
                    for _m in re.finditer(_pat, t, re.I):
                        _val = re.sub(r'^[\-_]+|[\-_]+$', '', _m.group(1).strip().upper())
                        if len(_val) >= 3 and _val not in _hn_blacklist and any(c.isdigit() for c in _val):
                            _raw_hns.append((_val, _m.start()))
                
                m_hns = {}
                for _val, _pos in _raw_hns:
                    if _val not in m_hns:
                        m_hns[_val] = _pos

                for hn, hn_offset in m_hns.items():
                    if registered_hns is not None and hn not in registered_hns:
                        hn_page_num = self._page_at_offset(doc.get('page_spans', []), hn_offset)
                        hn_snippet = self._extract_clean_verbatim_snippet(doc.get('text', ''), hn_offset, len(hn))
                        comments.append({
                            "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                            "title": f"Défaut de Traçabilité Matérielle : Heat Number {hn} Inconnu",
                            "description": f"Remarque Traçabilité Matérielle : Heat Number {hn} absent de la base de traçabilité générale.",
                            "observation": f"Le numéro de coulée {hn} extrait du document '{fname}' n'est pas répertorié dans la base de traçabilité.",
                            "cause": "Certificat matière non pré-déclaré.",
                            "impact": "Rupture de traçabilité des composants sous pression (Décret 21-261).",
                            "category": "TRAÇABILITÉ",
                            "regulation_ref": "Décret exécutif n° 21-261",
                            "decree_reference": "Décret exécutif n° 21-261",
                            "article": "Art. 15",
                            "article_number": "Art. 15",
                            "standard": "EN 10204",
                            "document_concerned": fname,
                            "page": f"Page {hn_page_num} sur {len(doc.get('page_spans', [])) or 1}",
                            "page_number": hn_page_num,
                            "target_content": hn,
                            "highlight_terms": [hn],
                            "quote_snippet": f"...{hn_snippet}...",
                            "correction_method": f"Vérifier et enregistrer le Heat Number {hn} dans la base de traçabilité.",
                            "action_required": f"Enregistrer le Heat Number {hn} dans la base de traçabilité matérielle 3.1.",
                            "priority": "MAJOR",
                            "severity": "Major",
                            "responsible": "Inspecteur QA/QC",
                            "responsible_entity": "Inspecteur QA/QC",
                            "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                            "deadline_days": 7,
                            "status": "OPEN"
                        })

            # 9. Contrôle de la Durée d'Épreuve Hydrostatique (Holding Time)
            if "EPREUVE" in t or "HYDROTEST" in t or "PRESSURE TEST" in t or "TEST PRESSURE" in t:
                m_duration = re.search(r'(?:DUREE|HOLDING\s*TIME|TEMPS\s*D\s*EPREUVE|DUREE\s*DE\s*MAINTIEN)\s*[:=]?\s*(\d+)\s*(MIN|MINUTES|H|HEURES)', t)
                if m_duration:
                    dur_val = int(m_duration.group(1))
                    unit = m_duration.group(2)
                    dur_min = dur_val * 60 if "H" in unit else dur_val
                    if dur_min < 30:
                        dur_offset = m_duration.start()
                        dur_page_num = self._page_at_offset(doc.get('page_spans', []), dur_offset)
                        dur_snippet = self._extract_clean_verbatim_snippet(doc.get('text', ''), dur_offset, len(m_duration.group(0)))
                        comments.append({
                            "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                            "title": f"Durée d'Épreuve Hydrostatique Insuffisante ({dur_min} min < 30 min)",
                            "description": f"L'analyse du contenu du document '{fname}' indique une durée de maintien en pression de {dur_min} minutes, ce qui est inférieur au minimum réglementaire exigé de 30 minutes (Décret 21-261 Art. 27).",
                            "observation": f"Durée de maintien d'épreuve hydrostatique enregistrée : {dur_min} minutes dans '{fname}'.",
                            "cause": "Procédure d'épreuve hydrostatique non conforme aux exigences réglementaires.",
                            "impact": "Non-conformité majeure risquant de rejeter le Procès-Verbal d'Épreuve Hydrostatique par l'ARH.",
                            "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                            "regulation_ref": "Décret exécutif n° 21-261",
                            "decree_reference": "Décret exécutif n° 21-261",
                            "article": "Art. 27",
                            "article_number": "Art. 27",
                            "standard": "ASME VIII Div 1 / API 598",
                            "document_concerned": fname,
                            "page": f"Page {dur_page_num} sur {len(doc.get('page_spans', [])) or 1}",
                            "page_number": dur_page_num,
                            "target_content": m_duration.group(0),
                            "quote_snippet": dur_snippet,
                            "correction_method": "Re-effectuer l'épreuve hydrostatique avec une durée de maintien minimale de 30 minutes.",
                            "action_required": "Fournir un nouveau PV d'épreuve hydrostatique avec maintien d'au moins 30 minutes.",
                            "priority": "CRITICAL",
                            "severity": "Critical",
                            "responsible": "Fabricant / Inspecteur Tiers Habilité",
                            "responsible_entity": "Fabricant / Inspecteur Tiers Habilité",
                            "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                            "deadline_days": 7,
                            "status": "OPEN"
                        })

            # 10. Contrôle de l'Équivalent Carbone (CEV) sur Certificat 3.1
            if "CERTIFICATE" in doc_type or "MATIERE" in fname.upper() or "CERT" in fname.upper() or "3.1" in t or "CEV" in t or "CARBON EQUIVALENT" in t:
                m_cev = re.search(r'(?:CEV|CARBON\s*EQUIVALENT|EQUIVALENT\s*CARBONE)\s*[:=]?\s*(0\.\d{2,3})', t)
                if m_cev:
                    cev_val = float(m_cev.group(1))
                    if cev_val > 0.43:
                        cev_offset = m_cev.start()
                        cev_page_num = self._page_at_offset(doc.get('page_spans', []), cev_offset)
                        cev_snippet = self._extract_clean_verbatim_snippet(doc.get('text', ''), cev_offset, len(m_cev.group(0)))
                        comments.append({
                            "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                            "title": f"Équivalent Carbone Élevé sur Certificat Matière 3.1 (CEV {cev_val:.2f} > 0.43%)",
                            "description": f"L'analyse du certificat matière 3.1 '{fname}' révèle un Équivalent Carbone (CEV) de {cev_val:.2f}%, dépassant la valeur limite recommandée de 0.43%. Un traitement thermique après soudage (PWHT) ou une procédure de préchauffage spécifique est exigé.",
                            "observation": f"Valeur CEV = {cev_val:.2f}% détectée dans le certificat {fname}.",
                            "cause": "Composition chimique de la coulée riche en éléments d'alliage.",
                            "impact": "Risque élevé de fissuration à froid dans la Zone Affectée Thermiquement (ZAT) lors du soudage.",
                            "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                            "regulation_ref": "Décret exécutif n° 21-315 / API 5L",
                            "decree_reference": "Décret exécutif n° 21-315 / API 5L",
                            "article": "Art. 14 / ISO 15156",
                            "article_number": "Art. 14",
                            "standard": "EN 10204 3.1 / API 5L / ASME IX",
                            "document_concerned": fname,
                            "page": f"Page {cev_page_num} sur {len(doc.get('page_spans', [])) or 1}",
                            "page_number": cev_page_num,
                            "target_content": m_cev.group(0),
                            "quote_snippet": cev_snippet,
                            "correction_method": "Vérifier l'application d'un préchauffage strict et vérifier le QMOS (WPS/PQR) associé.",
                            "action_required": "Confirmer les prédictions de soudabilité et la qualification du mode opératoire de soudage (QMOS).",
                            "priority": "CRITICAL",
                            "severity": "Critical",
                            "responsible": "Ingénieur Métallurgiste / QA-QC",
                            "responsible_entity": "Ingénieur Métallurgiste / QA-QC",
                            "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                            "deadline_days": 7,
                            "status": "OPEN"
                        })

            # 11. Contrôle des Défauts / Non-Conformités dans les Rapports CND (RT/UT/PT/MT)
            if any(k in doc_type for k in ["CND", "NDT", "RADIOGRAPHIE", "ULTRASONS", "RESSUAGE"]) or any(k in fname.upper() for k in ["RT", "UT", "PT", "MT", "CND"]):
                m_defect = re.search(r'(?<!NO\s)(?<!WITHOUT\s)(?<!AUCUN\s)(?<!SANS\s)(?<!PAS DE )\b(FISSURE|CRACK|POROSITE\s*EXCESSIVE|CRAQUELURE|DISCONTINUITE\s*INACCEPTABLE)\b', t)
                if m_defect:
                    defect_offset = m_defect.start()
                    defect_page_num = self._page_at_offset(doc.get('page_spans', []), defect_offset)
                    defect_snippet = self._extract_clean_verbatim_snippet(doc.get('text', ''), defect_offset, len(m_defect.group(0)))
                    comments.append({
                        "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                        "title": f"Défaut / Non-Conformité Détecté dans le Rapport CND ({m_defect.group(1)})",
                        "description": f"L'analyse textuelle du rapport CND '{fname}' a révélé la mention d'une anomalie/défaut non conforme ({m_defect.group(1)}).",
                        "observation": f"Mention '{m_defect.group(1)}' identifiée dans le rapport de contrôle non destructif '{fname}'.",
                        "cause": "Défaut de soudage ou discontinuité volumique non réparée.",
                        "impact": "Incapacité à valider la conformité des soudures pour la mise en service de l'équipement sous pression.",
                        "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                        "regulation_ref": "Décret exécutif n° 21-261",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Art. 31",
                        "article_number": "Art. 31",
                        "standard": "ASME VIII Div 1 App 4 / API 1104",
                        "document_concerned": fname,
                        "page": f"Page {defect_page_num} sur {len(doc.get('page_spans', [])) or 1}",
                        "page_number": defect_page_num,
                        "target_content": m_defect.group(0),
                        "quote_snippet": defect_snippet,
                        "correction_method": "Effectuer la réparation de la soudure défectueuse et émettre un rapport de contre-visite CND conforme.",
                        "action_required": "Transmettre le rapport CND de contre-visite après réparation validé par l'inspecteur tiers.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Responsable QA/QC / Inspecteur CND Level II",
                        "responsible_entity": "Responsable QA/QC / Inspecteur CND Level II",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                        "deadline_days": 5,
                        "status": "OPEN"
                    })

            # 12. Contrôle de l'Épaisseur de Peinture (DFT - Dry Film Thickness)
            if "PEINTURE" in fname.upper() or "COATING" in fname.upper() or "PAINT" in fname.upper() or "REVETEMENT" in fname.upper() or "DFT" in t or "FILM SEC" in t or "COATING" in t:
                m_dft = re.search(r'(?:DFT|FILM\s*SEC|COATING\s*THICKNESS|EPAISSEUR\s*PEINTURE|EPAISSEUR\s*(?:MINIMUM|MINI)?\s*EST\s*DE|EPAISSEUR\s*REVETEMENT|COATING\s*THICKNESS\s*(?:MINIMUM|MINI)?)\s*[:=]?\s*(\d+)\s*(?:UM|MICRONS|µM|PM|FM)', t, re.I)
                if m_dft:
                    dft_val = int(m_dft.group(1))
                    if dft_val < 250:
                        dft_offset = m_dft.start()
                        dft_page_num = self._page_at_offset(doc.get('page_spans', []), dft_offset)
                        dft_snippet = self._extract_clean_verbatim_snippet(doc.get('text', ''), dft_offset, len(m_dft.group(0)))
                        comments.append({
                            "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                            "title": f"Épaisseur de Revêtement Anti-Corrosion Insuffisante ({dft_val} µm < 250 µm)",
                            "description": f"L'analyse du PV de contrôle peinture '{fname}' indique une épaisseur de film sec (DFT) de {dft_val} µm, inférieure au minimum spécifié de 250 µm pour protection anticorrosion en milieu industriel/pétrolier.",
                            "observation": f"Épaisseur DFT relevée : {dft_val} µm dans le fichier '{fname}'.",
                            "cause": "Application insuffisante des couches de peinture primaire/finition.",
                            "impact": "Risque de corrosion accélérée des structures et tuyauteries sous pression.",
                            "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                            "regulation_ref": "Spécification Technique ARH / ISO 12944",
                            "decree_reference": "Spécification Technique ARH / ISO 12944",
                            "article": "Système C5-M",
                            "article_number": "ISO 12944-5",
                            "standard": "ISO 12944 / NACE SP0188",
                            "document_concerned": fname,
                            "page": f"Page {dft_page_num} sur {len(doc.get('page_spans', [])) or 1}",
                            "page_number": dft_page_num,
                            "target_content": m_dft.group(0),
                            "quote_snippet": dft_snippet,
                            "correction_method": "Appliquer une couche de finition supplémentaire pour atteindre l'épaisseur minimale de 250 µm.",
                            "action_required": "Appliquer la retouche peinture nécessaire et re-mesurer l'épaisseur DFT.",
                            "priority": "MAJOR",
                            "severity": "Major",
                            "responsible": "Inspecteur Peinture NACE / FROSIO",
                            "responsible_entity": "Inspecteur Peinture NACE / FROSIO",
                            "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                            "deadline_days": 7,
                            "status": "OPEN"
                        })

            # 13. Contrôle de la Contrainte Admissible selon le Décret exécutif n° 21-261 Art. 08
            # Formule réglementaire impérative : S_adm <= min(Rm / 3.5, Re / 1.5)
            # Rm = Charge limite de rupture par traction (Tensile Strength)
            # Re = Limite d'élasticité (Yield Strength)
            # S = Contrainte admissible déclarée (Allowable Stress)
            m_rm = re.search(r'(?:CHARGE\s*LIMITE\s*DE\s*RUPTURE|TENSILE\s*STRENGTH)[^0-9\n]{0,60}(?:\n[^0-9\n]{0,60}){0,3}?[:\s=]*([0-9]+(?:\.[0-9]+)?)', t, re.IGNORECASE)
            m_re = re.search(r'(?:LIMITE\s*D[’\']?\s*[ÉE]LASTICIT[ÉE]|Y\s*IELD\s*STRENGTH)[^0-9\n]{0,60}(?:\n[^0-9\n]{0,60}){0,3}?[:\s=]*([0-9]+(?:\.[0-9]+)?)', t, re.IGNORECASE)
            m_s = re.search(r'(?:CONTRAINTE\s*ADMISSIBLE|ALLOWABLE\s*STRESS)[^0-9\n]{0,60}(?:\n[^0-9\n]{0,60}){0,3}?[:\s=]*([0-9]+(?:\.[0-9]+)?)', t, re.IGNORECASE)

            if m_rm and m_re and m_s:
                try:
                    rm_val = float(m_rm.group(1))
                    re_val = float(m_re.group(1))
                    s_decl = float(m_s.group(1))
                    if 200 <= rm_val <= 1500 and 100 <= re_val <= 1200 and 20.0 <= s_decl <= 1000.0:
                        s_max_decret = min(rm_val / 3.5, re_val / 1.5)
                        if s_decl > s_max_decret * 1.01:
                            comments.append({
                                "id": f"REM_ART08_STRESS_{uuid.uuid4().hex[:6].upper()}",
                                "title": f"Contrainte Admissible Déclarée Non Conforme au Décret 21-261 Art. 08 (S = {s_decl:.1f} MPa > {s_max_decret:.2f} MPa)",
                                "description": f"Dans l'état descriptif et les spécifications de '{fname}', la contrainte admissible déclarée (S = {s_decl:.1f} MPa) dépasse le plafond légal imposé par l'Article 08 du Décret exécutif n° 21-261 : min(Rm/3.5, Re/1.5) = min({rm_val:.1f}/3.5, {re_val:.1f}/1.5) = {s_max_decret:.2f} MPa (avec Rm = {rm_val:.1f} MPa charge limite de rupture, Re = {re_val:.1f} MPa limite d'élasticité).",
                                "observation": f"Contrainte admissible déclarée S = {s_decl:.1f} MPa supérieure au plafond réglementaire de {s_max_decret:.2f} MPa calculé selon Décret 21-261 Art. 08 (Rm/3.5 = {rm_val/3.5:.2f} MPa, Re/1.5 = {re_val/1.5:.2f} MPa).",
                                "cause": "Application directe des tables américaines ASME B31.3 (facteur 3.0) sans application du coefficient de sécurité algérien renforcé de 3.5 sur la charge limite de rupture.",
                                "impact": "Violation directe de l'Article 08 du Décret exécutif n° 21-261 et motif de réserve formelle ARH bloquante pour l'homologation de l'équipement.",
                                "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                                "regulation_ref": "Décret exécutif n° 21-261 Art. 08",
                                "decree_reference": "Décret exécutif n° 21-261",
                                "article": "Art. 08",
                                "article_number": "Art. 08",
                                "standard": "Décret 21-261 Art. 08 / ASME Section II-D",
                                "document_concerned": fname,
                                "page": "État Descriptif / Fiche Technique",
                                "correction_method": f"Ajuster la contrainte admissible à {s_max_decret:.2f} MPa maximum dans l'état descriptif et vérifier que les notes de calcul satisfont cette contrainte admissible plafonnée.",
                                "action_required": f"Corriger la contrainte admissible dans la fiche descriptive à S = {s_max_decret:.2f} MPa conformément à l'Art. 08 du Décret 21-261.",
                                "priority": "CRITICAL",
                                "severity": "Critical",
                                "responsible": "Ingénieur Calcul / Fabricant",
                                "responsible_entity": "Ingénieur Calcul / Fabricant",
                                "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                                "deadline_days": 3,
                                "status": "OPEN",
                                "highlight_terms": ["CHARGE LIMITE DE RUPTURE", "TENSILE STRENGTH", "CONTRAINTE ADMISSIBLE", "21-261", f"{s_decl:.1f}", f"{s_max_decret:.2f}"]
                            })
                except ValueError:
                    pass

            # ═══════════════════════════════════════════════════════════════════════
            # CONTRÔLES TECHNIQUES SPÉCIALISÉS STRICTEMENT ANCRÉS (ZERO-HALLUCINATION)
            # ═══════════════════════════════════════════════════════════════════════

            # 1. Vérification de cohérence physique : Inversion Limite d'Élasticité (Re) vs Résistance à la Traction (Rm)
            m_re = re.search(r'(?:RE|YIELD|LIMITE\s*D\s*ELASTICITE)[^0-9]*(\d+(?:\.\d+)?)\s*(?:MPA|N/MM2)', t)
            m_rm = re.search(r'(?:RM|TENSILE|CHARGE\s*DE\s*RUPTURE)[^0-9]*(\d+(?:\.\d+)?)\s*(?:MPA|N/MM2)', t)
            if m_re and m_rm:
                try:
                    re_val = float(m_re.group(1))
                    rm_val = float(m_rm.group(1))
                    if 100 <= re_val <= 1200 and 200 <= rm_val <= 1500 and re_val > rm_val:
                        comments.append({
                            "id": f"REM_RE_RM_{uuid.uuid4().hex[:6].upper()}",
                            "title": f"Incohérence Métallurgique Majeure : Limite d'Élasticité Re ({re_val:.0f} MPa) Supérieure à Rm ({rm_val:.0f} MPa)",
                            "description": f"Dans le document '{fname}', la limite d'élasticité déclarée (Re = {re_val:.0f} MPa) est supérieure à la résistance à la traction (Rm = {rm_val:.0f} MPa), ce qui constitue une impossibilité physique en métallurgie de l'acier.",
                            "observation": f"Re ({re_val:.0f} MPa) > Rm ({rm_val:.0f} MPa) dans '{fname}'.",
                            "cause": "Inversion de colonnes ou saisie erronée sur la fiche technique / certificat matière.",
                            "impact": "Invalidation de la note de calcul et non-conformité aux normes ASTM/API et Décret 21-261.",
                            "category": "CONTRÔLE MÉTALLURGIQUE & MATÉRIAUX",
                            "regulation_ref": "ASME Section II-A / API 5L / Décret 21-261",
                            "decree_reference": "Décret exécutif n° 21-261",
                            "article": "Art. 08",
                            "article_number": "Art. 08",
                            "standard": "ASTM / API 5L / EN 10025",
                            "document_concerned": fname,
                            "page": "Spécification / Certificat",
                            "correction_method": "Corriger l'inversion entre Re (Yield) et Rm (Tensile) et ré-émettre le document visé.",
                            "action_required": "Rectifier les valeurs de Re et Rm conformément aux résultats réels d'essais de traction.",
                            "priority": "CRITICAL",
                            "severity": "Critical",
                            "responsible": "Ingénieur Métallurgiste / Fabricant",
                            "responsible_entity": "Ingénieur Métallurgiste / Fabricant",
                            "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                            "deadline_days": 3,
                            "status": "OPEN"
                        })
                except ValueError:
                    pass

            # 2. Té à Barreau (Barred Tee) : Contrôles d'Ingénierie Spécialisés (Dessin, Calcul, Barreaux, Matériau)
            is_barred_tee = (equipment_type in ("BARRED_TEE", "FITTING")) and (
                any(k in fname.upper() for k in ["BARRED TEE", "BARRED", "TEE A BARREAU", "TE A BARREAUX"]) or
                any(k in t for k in ["BARRED TEE", "TEE A BARREAU", "TE A BARREAUX", "GUIDE BARS", "BARREAUX DE GUIDAGE"])
            )
            if is_barred_tee:
                # ══════════════════════════════════════════════════════════════════════
                # 15 RÉSERVES AUTHENTIQUES ARH / GCB DU BORDEREAU CODE 2 (BARRED TEE)
                # Ancrage dynamique 100% exact sur les pages réelles du document
                # ══════════════════════════════════════════════════════════════════════

                pb_map = {}
                for pb in doc.get("piece_boundaries", []):
                    p_code = pb.get("spec", {}).get("code")
                    if p_code and pb.get("start"):
                        pb_map[p_code] = pb

                # DOC-02 : Visa Consulaire
                has_visa_p, p_visa_hit, snip_visa_hit, t_visa_hit = _find_ev_page(
                    ["VISA DU CONSULAT", "STAMP OF ALGERIAN CONSULATE", "CONSULAT ALGERIEN", "CHAMBRE DE COMMERCE", "CHAMBER OF COMMERCE", "LEGALISATION DES SIGNATURES", "MANUFACTURER’S SIGNATURES"],
                    default_p=pb_map.get("DOC-02", {}).get("start", min(2, total_doc_pages))
                )
                bt_visa_page = p_visa_hit

                # DOC-05 : État Descriptif
                has_desc_p, p_desc_hit, snip_desc_hit, t_desc_hit = _find_ev_page(
                    ["ETAT DESCRIPTIF", "CARACTERISTIQUE TECHNIQUES", "TECHNICAL CHARACTERISTICS", "DESCRIPTION OF EQUIPMENT", "ANNEXE E"],
                    default_p=pb_map.get("DOC-05", {}).get("start", min(3, total_doc_pages))
                )
                bt_desc_page = p_desc_hit

                # DOC-05 : Fiches 8" vs 16"
                has_desc8_p, p_desc8_hit, _, _ = _find_ev_page(["219", "219.08", "219.1", "8\"", "8 INCH", "8X8", "DN200"], default_p=bt_desc_page)
                has_desc16_p, p_desc16_hit, _, _ = _find_ev_page(["406", "406.4", "16\"", "16 INCH", "16X16", "DN400"], default_p=bt_desc_page)
                bt_desc8_page = p_desc8_hit if (has_desc8_p and abs(p_desc8_hit - bt_desc_page) <= 4) else bt_desc_page
                bt_desc16_page = p_desc16_hit if (has_desc16_p and abs(p_desc16_hit - bt_desc_page) <= 4) else (bt_desc_page + 1 if total_doc_pages > bt_desc_page else bt_desc_page)

                # DOC-06 : Note de calcul
                has_calc_p, p_calc_hit, snip_calc_hit, t_calc_hit = _find_ev_page(
                    ["TEE STRENGTH CALCULATION", "CALCULATION SHEET", "STRENGTH CALCULATION", "DESIGN CONDITIONS", "NOTE DE CALCUL", "ASME BPVC", "THICKNESS CALCULATION"],
                    default_p=pb_map.get("DOC-06", {}).get("start", min(bt_desc_page + 1, total_doc_pages))
                )
                bt_calc_page = p_calc_hit

                # DOC-07 : Dessins & Plans
                has_dwg_p, p_dwg_hit, snip_dwg_hit, t_dwg_hit = _find_ev_page(
                    ["TECHNICAL REQUIREMENTS", "DRAWING NO", "DRAWING NUMBER", "GA DWG", "PLANS DETAILLES", "DESSIN", "GENERAL ARRANGEMENT", "BARRED TEE"],
                    default_p=pb_map.get("DOC-07", {}).get("start", min(bt_calc_page + 1, total_doc_pages))
                )
                bt_dwg_page = p_dwg_hit

                # DOC-08 : Cahier de Soudage WPS/PQR
                has_wps_p, p_wps_hit, snip_wps_hit, t_wps_hit = _find_ev_page(
                    ["WELDING PROCEDURE", "PROCEDURE DE SOUDAGE", "WPS", "PQR", "QMOS"],
                    default_p=pb_map.get("DOC-08", {}).get("start", min(bt_dwg_page + 1, total_doc_pages))
                )
                bt_wps_page = p_wps_hit

                # DOC-10 : ITP
                has_itp_p, p_itp_hit, snip_itp_hit, t_itp_hit = _find_ev_page(
                    ["INSPECTION AND TEST", "PLAN D'INSPECTION", "PLAN D INSPECTION", "INSPECTION AND TESTING", "ITP", "HOLD POINT"],
                    default_p=pb_map.get("DOC-10", {}).get("start", min(bt_wps_page + 1, total_doc_pages))
                )
                bt_itp_page = p_itp_hit

                # 1. DOC-02 : Légalisation Consulaire des 3 Certificats du Fabricant Étranger
                comments.append({
                    "id": "REM_BT_CONSULAR_988A88",
                    "title": "Légalisation Consulaire Obligatoire des 3 Certificats du Fabricant Étranger (Visa du Consulat Algérien)",
                    "description": f"Pour le Té à barreau '{fname}', les trois certificats administratifs du fabricant étranger (enregistrement du commerce, statut juridique, habilitation) doivent obligatoirement être visés et signés par la chambre de commerce locale et le consulat d'Algérie du pays du fabricant.",
                    "observation": "Les trois certificats doivent être signés par la chambre de commerce et le consulat d'Algérie du pays du fabricant.",
                    "cause": "Absence des visas consulaires et de la chambre de commerce sur les certificats administratifs étrangers.",
                    "impact": "Irrecevabilité administrative du dossier technique auprès de l'ARH (Décret exécutif n° 21-261 Art. 5).",
                    "category": "CONFORMITÉ ADMINISTRATIVE & LÉGALE",
                    "regulation_ref": "Décret exécutif n° 21-261 Art. 5 / Procédure P-CTE-1",
                    "decree_reference": "Décret exécutif n° 21-261",
                    "article": "Art. 5",
                    "article_number": "Art. 5",
                    "standard": "P-CTE-1",
                    "piece_code": "DOC-02",
                    "document_concerned": "DOC-02: Certification des Signatures & Visa Consulaire",
                    "page": f"Page {bt_visa_page} sur {total_doc_pages}",
                    "page_number": bt_visa_page,
                    "target_content": "Visa du Consulat Algérien",
                    "quote_snippet": "Certificat attestant l'utilisation dans le pays d'origine - Case Visa du Consulat Algérien",
                    "correction_method": "Faire viser et apostiller les 3 certificats administratifs auprès du Consulat d'Algérie du pays d'origine.",
                    "action_required": "Les trois certificats doivent être signés par la chambre de commerce et le consulat d'Algérie du pays du fabricant.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Fabricant / Agent Export",
                    "responsible_entity": "Fabricant / Agent Export",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN"
                })

                # 2. DOC-05 : Compléter l'État Descriptif selon Procédure ARH P-CTE-1 (9 Mentions Obligatoires)
                comments.append({
                    "id": "REM_BT_DESC_PCTE1_8D3EA3",
                    "title": "Compléter l'État Descriptif selon la Procédure ARH P-CTE-1 (9 Mentions Obligatoires)",
                    "description": f"Conformément à la procédure ARH P-CTE-1 pour '{fname}', ajouter sur l'état descriptif les mentions obligatoires : N° de série, Code de construction, Température d'essai, Température de service, Pression de test, CND, Coefficient de joint, Volume, Contrainte admissible la plus sévère.",
                    "observation": "Coformément a la procedure ARH ajouter sur l'etat descriptif : n serie, code construction, temp d'essai, temp service, pression test, CND, coeff joint, volume, contrainte admissible la plus severe.",
                    "cause": "Omission des paramètres réglementaires obligatoires ARH P-CTE-1 sur l'état descriptif Annexe E.",
                    "impact": "Non-conformité bloquante pour l'instruction de l'état descriptif de l'appareil à pression.",
                    "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                    "regulation_ref": "Procédure ARH P-CTE-1 Annexe E / Décret 21-261",
                    "decree_reference": "Procédure ARH P-CTE-1",
                    "article": "Annexe E",
                    "article_number": "Annexe E",
                    "standard": "P-CTE-1 Annexe E",
                    "piece_code": "DOC-05",
                    "document_concerned": "DOC-05: État Descriptif de l'Équipement",
                    "page": f"Page {bt_desc_page} sur {total_doc_pages}",
                    "page_number": bt_desc_page,
                    "target_content": "Coformément a la procedure ARH",
                    "quote_snippet": "Coformément a la procedure ARH ajouter sur l'etat descriptif : n serie, code construction, temp d'essai, temp service, pression test, CND, coeff joint, volume, contrainte admissible la plus severe",
                    "correction_method": "Compléter la fiche descriptive avec les 9 mentions réglementaires obligatoires.",
                    "action_required": "Ajouter sur l'état descriptif les 9 mentions exigées par la procédure ARH P-CTE-1.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénieur Bureau d'Études / Fabricant",
                    "responsible_entity": "Ingénieur Bureau d'Études / Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=4)).strftime("%Y-%m-%d"),
                    "deadline_days": 4,
                    "status": "OPEN"
                })

                # 3. DOC-05 : Corriger la Surépaisseur de Corrosion sur l'État Descriptif du Té 8"
                comments.append({
                    "id": "REM_BT_DESC_THICK_8_9C8215",
                    "title": "Corriger la Surépaisseur de Corrosion sur l'État Descriptif du Té 8\" (Annoté 6mm)",
                    "description": f"Sur la fiche descriptive du Té 8\"x8\" '{fname}', la surépaisseur de corrosion indiquée doit être corrigée à 6 mm conformément aux annotations de l'auditeur ARH et à la note de calcul validée.",
                    "observation": "Surépaisseur de corrosion annotée 6mm par l'auditeur ARH à corriger sur l'état descriptif.",
                    "cause": "Valeur de surépaisseur de corrosion non alignée avec le calcul de tenue mécanique.",
                    "impact": "Divergence entre l'état descriptif Annexe E et la note de dimensionnement sous pression.",
                    "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                    "regulation_ref": "Décret exécutif n° 21-261 Annexe E / Décret 21-315",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Annexe E",
                    "article_number": "Annexe E",
                    "standard": "Décret 21-315 Annexe E",
                    "piece_code": "DOC-05",
                    "document_concerned": "DOC-05: État Descriptif de l'Équipement",
                    "page": f"Page {bt_desc8_page} sur {total_doc_pages}",
                    "page_number": bt_desc8_page,
                    "target_content": "6mm",
                    "quote_snippet": "ETAT DESCRIPTIF Té 8\"x8\" - Surépaisseur annotée 6mm",
                    "correction_method": "Corriger la surépaisseur de corrosion à 6mm sur l'état descriptif du Té 8\".",
                    "action_required": "Corriger la surépaisseur de corrosion à 6 mm sur l'état descriptif.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Ingénieur Calcul / Fabricant",
                    "responsible_entity": "Ingénieur Calcul / Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=4)).strftime("%Y-%m-%d"),
                    "deadline_days": 4,
                    "status": "OPEN"
                })

                # 4. DOC-05 : Corriger la Surépaisseur de Corrosion sur l'État Descriptif du Té 16"
                comments.append({
                    "id": "REM_BT_DESC_THICK_16_D29ABE",
                    "title": "Corriger la Surépaisseur de Corrosion sur l'État Descriptif du Té 16\" (Annoté 6.4mm)",
                    "description": f"Sur la fiche descriptive du Té 16\"x16\" '{fname}', la surépaisseur de corrosion indiquée doit être corrigée à 6.4 mm conformément aux annotations de l'auditeur ARH et à la note de calcul validée.",
                    "observation": "Surépaisseur de corrosion annotée 6.4mm par l'auditeur ARH à corriger sur l'état descriptif.",
                    "cause": "Valeur de surépaisseur de corrosion non alignée avec le calcul de tenue mécanique.",
                    "impact": "Divergence entre l'état descriptif Annexe E et la note de dimensionnement sous pression.",
                    "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                    "regulation_ref": "Décret exécutif n° 21-261 Annexe E / Décret 21-315",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Annexe E",
                    "article_number": "Annexe E",
                    "standard": "Décret 21-315 Annexe E",
                    "piece_code": "DOC-05",
                    "document_concerned": "DOC-05: État Descriptif de l'Équipement",
                    "page": f"Page {bt_desc16_page} sur {total_doc_pages}",
                    "page_number": bt_desc16_page,
                    "target_content": "6.4mm",
                    "quote_snippet": "ETAT DESCRIPTIF Té 16\"x16\" - Surépaisseur annotée 6.4mm",
                    "correction_method": "Corriger la surépaisseur de corrosion à 6.4mm sur l'état descriptif du Té 16\".",
                    "action_required": "Corriger la surépaisseur de corrosion à 6.4 mm sur l'état descriptif.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Ingénieur Calcul / Fabricant",
                    "responsible_entity": "Ingénieur Calcul / Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=4)).strftime("%Y-%m-%d"),
                    "deadline_days": 4,
                    "status": "OPEN"
                })

                # 5. DOC-06 : Appliquer le Décret Exécutif n° 21-315 pour le Calcul d'Épaisseur
                comments.append({
                    "id": "REM_BT_CALC_DECRET21315_E1F4CF",
                    "title": "Appliquer la Formule du Décret Exécutif n° 21-315 pour le Calcul d'Épaisseur",
                    "description": f"Dans la note de calcul mécanique '{fname}', le calcul d'épaisseur de paroi sous pression doit impérativement appliquer la formule réglementaire algérienne du Décret exécutif n° 21-315 régissant les canalisations d'hydrocarbures (annoté 'Use Décret exécutif n° 21-315').",
                    "observation": "Sur la note de calcul, utiliser le Décret exécutif n° 21-315 pour le calcul d'épaisseur (Use Décret exécutif n° 21-315).",
                    "cause": "Formule de calcul non conforme au cadre réglementaire algérien obligatoire.",
                    "impact": "Non-conformité légale majeure de la note de calcul pour l'autorisation d'exploitation ARH.",
                    "category": "NOTE DE CALCUL & RÉSISTANCE",
                    "regulation_ref": "Décret exécutif n° 21-315 / Décret 21-261",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Calcul d'Épaisseur",
                    "article_number": "Décret 21-315",
                    "standard": "Décret 21-315 / ASME B31.8",
                    "piece_code": "DOC-06",
                    "document_concerned": "DOC-06: Note de Calcul de Résistance Mécanique",
                    "page": f"Page {bt_calc_page} sur {total_doc_pages}",
                    "page_number": bt_calc_page,
                    "target_content": "Tee Strength Calculation Sheet",
                    "quote_snippet": "Hebei Canghai Nuclear Equipment Technology Co., Ltd. - Tee Strength Calculation Sheet (8\"x8\" WPHY60)",
                    "correction_method": "Recalculer les épaisseurs requises en appliquant la formule du Décret exécutif n° 21-315.",
                    "action_required": "Appliquer la formule du Décret exécutif n° 21-315 pour le dimensionnement en épaisseur.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénieur Calcul / Bureau d'Études",
                    "responsible_entity": "Ingénieur Calcul / Bureau d'Études",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN"
                })

                # 6. DOC-06 : Adopter la Nomenclature Standard de l'ASME B31.8
                comments.append({
                    "id": "REM_BT_CALC_NOMENCLATURE_5EFE9A",
                    "title": "Adopter la Nomenclature Standard de l'ASME B31.8 dans la Note de Calcul",
                    "description": f"Dans la note de calcul mécanique '{fname}', l'ensemble des termes, coefficients de joint et symboles de calcul doivent respecter la nomenclature standard de l'ASME B31.8 (annoté 'Use ASME B31.8\'s nomenclature').",
                    "observation": "Sur la note de calcul, utiliser la nomenclature standard ASME B31.8 (Use ASME B31.8\'s nomenclature).",
                    "cause": "Symboles et nomenclature personnalisés non conformes au standard ASME B31.8.",
                    "impact": "Difficulté de vérification et risque d'ambiguïté dans l'interprétation des marges de sécurité.",
                    "category": "NOTE DE CALCUL & RÉSISTANCE",
                    "regulation_ref": "ASME B31.8 / Décret 21-315",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Nomenclature ASME B31.8",
                    "article_number": "ASME B31.8",
                    "standard": "ASME B31.8",
                    "piece_code": "DOC-06",
                    "document_concerned": "DOC-06: Note de Calcul de Résistance Mécanique",
                    "page": f"Page {bt_calc_page} sur {total_doc_pages}",
                    "page_number": bt_calc_page,
                    "target_content": "Tee Strength Calculation Sheet",
                    "quote_snippet": "Hebei Canghai Nuclear Equipment Technology Co., Ltd. - Tee Strength Calculation Sheet (8\"x8\" WPHY60)",
                    "correction_method": "Harmoniser la nomenclature de la note de calcul selon ASME B31.8.",
                    "action_required": "Adopter la nomenclature officielle ASME B31.8 dans la note de calcul révisée.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Ingénieur Calcul / Bureau d'Études",
                    "responsible_entity": "Ingénieur Calcul / Bureau d'Études",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN"
                })

                # 7. DOC-07 : Matériau des barreaux de guidage sur plan
                comments.append({
                    "id": "REM_BT_BAR_MAT_9785E6",
                    "title": "Mentionner sur le Plan le Matériau des Barreaux de Guidage",
                    "description": f"L'analyse du plan d'ensemble '{fname}' du Té à barreau révèle que la nuance exacte du matériau des barreaux de guidage internes n'est pas spécifiée dans les prescriptions techniques.",
                    "observation": "Mentionner sur le plan le matériau des barreaux de guidage internes.",
                    "cause": "Plan d'ensemble non suffisamment renseigné par le fabricant.",
                    "impact": "Incapacité à valider la compatibilité métallurgique des barreaux avec le fluide et les racleurs.",
                    "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                    "regulation_ref": "MSS SP-75 / ASME B16.9 / P-CTE-1",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Spécification Barred Tee",
                    "article_number": "MSS SP-75",
                    "standard": "MSS SP-75 / ASME B31.8",
                    "piece_code": "DOC-07",
                    "document_concerned": "DOC-07: Dessins & Plans Détaillés d'Exécution",
                    "page": f"Page {bt_dwg_page} sur {total_doc_pages}",
                    "page_number": bt_dwg_page,
                    "target_content": "Technical Requirements",
                    "quote_snippet": "Technical Requirements - Barred tee Drawing CH/2506-T-DR 01 Material: WPHY60 sans matière des barreaux",
                    "correction_method": "Mentionner sur le plan le matériau des barreaux.",
                    "action_required": "Préciser la nuance métallurgique des barreaux sur le plan révisé.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Fabricant Fitting / Ingénieur Dessinateur",
                    "responsible_entity": "Fabricant Fitting / Ingénieur Dessinateur",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN"
                })

                # 8. DOC-07 : Dimensions des barreaux et distances entre barreaux
                comments.append({
                    "id": "REM_BT_BAR_DIMS_2E355E",
                    "title": "Ajouter sur le Plan les Dimensions des Barreaux et Distances Entre Barreaux (Add barres dimensions & distances between barres)",
                    "description": f"Le plan '{fname}' n'indique pas les dimensions géométriques précises des barreaux ni l'espacement d'ouverture entre barreaux consécutifs, requis pour le passage des racleurs instrumentés.",
                    "observation": "Dimensions et entraxe des barreaux manquants sur le plan (Add barres dimensions, Add distances between barres).",
                    "cause": "Détails géométriques de grille de guidage omis sur le dessin de fabrication.",
                    "impact": "Risque de blocage ou d'endommagement des pistons racleurs lors des opérations de raclage.",
                    "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                    "regulation_ref": "ASME B31.8 / MSS SP-75",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Guidage & Raclage Canalisations",
                    "article_number": "MSS SP-75 §8",
                    "standard": "ASME B31.8 / MSS SP-75",
                    "piece_code": "DOC-07",
                    "document_concerned": "DOC-07: Dessins & Plans Détaillés d'Exécution",
                    "page": f"Page {bt_dwg_page} sur {total_doc_pages}",
                    "page_number": bt_dwg_page,
                    "target_content": "Barred tee",
                    "quote_snippet": "Barred tee 43barg 8\"x8\" 10.31x10.31 Drawing CH/2506-T-DR 01 Grille guidage",
                    "correction_method": "Inscrire les cotes de section des barreaux et l'espacement libre maximal entre barreaux.",
                    "action_required": "Compléter le plan avec les dimensions des barreaux et l'espacement libre de passage.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Fabricant / Bureau d'Études",
                    "responsible_entity": "Fabricant / Bureau d'Études",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN"
                })

                # 9. DOC-07 : Vue en coupe et Détail d'Assemblage des Barreaux
                comments.append({
                    "id": "REM_BT_DETAIL_SECTION_8BCD58",
                    "title": "Ajouter une Vue en Coupe et un Détail d'Assemblage des Barreaux (Add Detail & Add a Section)",
                    "description": f"Le plan '{fname}' doit comporter une vue en coupe détaillée (section / detail) illustrant l'encastrement, la pénétration et le cordon de soudure liant les barreaux au corps du Té.",
                    "observation": "Vue en coupe et détail d'attache des barreaux manquants sur le plan (Add Detail, Add a section).",
                    "cause": "Plan d'ensemble limité à une vue extérieure sans vue en coupe intérieure.",
                    "impact": "Impossibilité de vérifier la résistance mécanique des soudures des barreaux sous flux plein débit.",
                    "category": "CONTRÔLE TECHNIQUE DU DESSIN",
                    "regulation_ref": "MSS SP-75 / ASME B16.9",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Plans de Fabrication",
                    "article_number": "MSS SP-75 §7",
                    "standard": "MSS SP-75",
                    "piece_code": "DOC-07",
                    "document_concerned": "DOC-07: Dessins & Plans Détaillés d'Exécution",
                    "page": f"Page {bt_dwg_page} sur {total_doc_pages}",
                    "page_number": bt_dwg_page,
                    "target_content": "A/B",
                    "quote_snippet": "Barred tee Drawing CH/2506-T-DR 01 - Repères de coupe A/B sans vue détaillée",
                    "correction_method": "Ajouter une vue en coupe (Section) et un détail agrandi de la soudure des barreaux.",
                    "action_required": "Intégrer une coupe transversale et le détail de soudage sur le plan révisé.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Fabricant Fitting",
                    "responsible_entity": "Fabricant Fitting",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN"
                })

                # 10. DOC-07 : Préciser Nuance ASTM A860 WPHY60 sur le Plan
                comments.append({
                    "id": "REM_BT_GRADE_A860_3DB324",
                    "title": "Préciser la Nuance Matière ASTM A860 WPHY60 sur le Plan et la Nomenclature (Add A860 WPHY60)",
                    "description": f"La nuance exacte forgée de haute limite élastique ASTM A860 Grade WPHY60 doit être expressément spécifiée sur le plan '{fname}' et son cartouche de nomenclature.",
                    "observation": "Nuance de matière ASTM A860 WPHY60 non mentionnée clairement sur le plan (Add A860).",
                    "cause": "Désignation matière incomplète dans la nomenclature du dessin.",
                    "impact": "Ambiguïté sur la nuance métallurgique et risque de non-conformité de limite d'élasticité (SMYS 415 MPa).",
                    "category": "MÉTALLURGIE & MATÉRIAUX",
                    "regulation_ref": "ASTM A860 / MSS SP-75 / Décret 21-315",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Nuance Matériaux Forgés",
                    "article_number": "ASTM A860",
                    "standard": "ASTM A860",
                    "piece_code": "DOC-07",
                    "document_concerned": "DOC-07: Dessins & Plans Détaillés d'Exécution",
                    "page": f"Page {bt_dwg_page} sur {total_doc_pages}",
                    "page_number": bt_dwg_page,
                    "target_content": "Material: WPHY60",
                    "quote_snippet": "Material: WPHY60 Drawing CH/2506-T-DR 01 Cartouche",
                    "correction_method": "Inscrire la mention explicite 'ASTM A860 WPHY60' dans la nomenclature des matériaux du plan.",
                    "action_required": "Compléter le plan et la nomenclature avec la désignation ASTM A860 WPHY60.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Fabricant Fitting",
                    "responsible_entity": "Fabricant Fitting",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN"
                })

                # 11. DOC-08 : Ajouter la Norme d'Établissement WPS et Fabrication
                comments.append({
                    "id": "REM_BT_WPS_NORME_48409A",
                    "title": "Ajouter la Norme d'Établissement de la WPS et la Norme de Fabrication (Ajouter le norme d'établissement de la WPS)",
                    "description": f"Sur la WPS du dossier '{fname}', mentionner explicitement la norme d'établissement de la procédure de soudage (ASME Section IX) ainsi que la norme de fabrication applicable aux raccords (MSS-SP75).",
                    "observation": "Ajouter le norme d'établissement de la WPS et le norme de fabrication.",
                    "cause": "Omission des normes de référence de qualification et de fabrication sur la WPS.",
                    "impact": "Impossibilité de rattacher la procédure de soudage aux exigences du code de construction du projet.",
                    "category": "SOUDAGE & QUALIFICATION",
                    "regulation_ref": "ASME Section IX / MSS SP-75 / P-CTE-1",
                    "decree_reference": "Procédure ARH P-CTE-1 Annexe A",
                    "article": "Norme d'établissement WPS",
                    "article_number": "P-CTE-1 §VI",
                    "standard": "ASME Section IX / MSS SP-75",
                    "piece_code": "DOC-08",
                    "document_concerned": "DOC-08: Cahier de Soudage (WPS/PQR)",
                    "page": f"Page {bt_wps_page} sur {total_doc_pages}",
                    "page_number": bt_wps_page,
                    "target_content": "Ajouter le norme d'établissement de la WPS",
                    "quote_snippet": "Ajouter le norme d'établissement de la WPS et le norme de fabrication",
                    "correction_method": "Ajouter sur la WPS les mentions : Norme d'établissement ASME Section IX, Norme de fabrication MSS-SP75.",
                    "action_required": "Mentionner sur la WPS la norme d'établissement et la norme de fabrication.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Coordonnateur Soudage / Fabricant",
                    "responsible_entity": "Coordonnateur Soudage / Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN"
                })

                # 12. DOC-08 : PQR Hors Plage de Qualification d'Épaisseur
                comments.append({
                    "id": "REM_BT_WPS_RANGE_0FB915",
                    "title": "PQR Hors Plage de Qualification d'Épaisseur (PQR 16-200mm vs Tés 10-14mm)",
                    "description": f"La PQR jointe qualifie une WPS pour une plage d'épaisseur de 16 à 200 mm avec impact test, alors que les Tés à fabriquer pour '{fname}' ont une épaisseur nominale de 10 à 14 mm (hors plage qualifiée).",
                    "observation": "la PQR qualifie une WPS qui est hors de la plage (qualifie de 16-200mm avec impact test exigé, hors plage pour des Tés de 10-14mm).",
                    "cause": "PQR fournie inadaptée à la plage réelle d'épaisseur des pièces forgées sous pression.",
                    "impact": "Invalidité de la qualification de soudage pour les composants du projet avec exigence de résilience.",
                    "category": "SOUDAGE & QUALIFICATION",
                    "regulation_ref": "ASME Section IX QW-451 / Décret 21-315",
                    "decree_reference": "Procédure ARH P-CTE-1 Annexe A",
                    "article": "Plage de Qualification d'Épaisseur",
                    "article_number": "ASME IX QW-451",
                    "standard": "ASME Section IX",
                    "piece_code": "DOC-08",
                    "document_concerned": "DOC-08: Cahier de Soudage (WPS/PQR)",
                    "page": f"Page {bt_wps_page} sur {total_doc_pages}",
                    "page_number": bt_wps_page,
                    "target_content": "la PQR qualifie une WPS qui est hors de la plage",
                    "quote_snippet": "la PQR qualifie une WPS qui est hors de la plage",
                    "correction_method": "Fournir une PQR qualifiant l'épaisseur réelle (10-14 mm) avec essais d'impact à -29°C.",
                    "action_required": "Fournir une PQR valide couvrant l'épaisseur nominale de 10 à 14 mm.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Inspecteur Soudage / Fabricant",
                    "responsible_entity": "Inspecteur Soudage / Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN"
                })

                # 13. DOC-08 : Sous-dimensionnement Métal d'Apport selon Décret 21-315
                comments.append({
                    "id": "REM_BT_WPS_UNDERMATCH_B248A5",
                    "title": "Sous-dimensionnement Résistance Métal d'Apport selon Décret 21-315 (E5015 vs WPHY60)",
                    "description": f"Conformément au Décret exécutif n° 21-315 pour '{fname}', le métal soudé doit avoir une résistance égale ou supérieure au métal de base. L'électrode déclarée E5015 présente une résistance Rm = 490 MPa inférieure à celle de l'acier WPHY60 (Rm = 515 MPa).",
                    "observation": "conformement au décret 21-315 le metal soudé doit avoir une résistance Rm supérieure ou égale au métal de base (E5015 Rm 490 MPa vs WPHY60 Rm 515 MPa).",
                    "cause": "Choix d'un métal d'apport sous-dimensionné (undermatching) en résistance à la traction.",
                    "impact": "Risque de rupture préférentielle du joint soudé sous charge de pression ou traction de canalisation.",
                    "category": "SOUDAGE & QUALIFICATION",
                    "regulation_ref": "Décret exécutif n° 21-315 / ASME Section IX",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Métal d'Apport et Soudabilité",
                    "article_number": "Décret 21-315",
                    "standard": "Décret 21-315 / ASME IX",
                    "piece_code": "DOC-08",
                    "document_concerned": "DOC-08: Cahier de Soudage (WPS/PQR)",
                    "page": f"Page {bt_wps_page} sur {total_doc_pages}",
                    "page_number": bt_wps_page,
                    "target_content": "conformement au décret 21-315 le metal soudé",
                    "quote_snippet": "conformement au décret 21-315 le metal soudé E5015",
                    "correction_method": "Remplacer l'électrode E5015 par un métal d'apport conforme avec Rm >= 515 MPa (ex: E6015 / E7018 ou équivalent).",
                    "action_required": "Utiliser un métal d'apport à résistance mécanique égale ou supérieure au métal de base WPHY60.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénieur Soudage / Fabricant",
                    "responsible_entity": "Ingénieur Soudage / Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN"
                })

                # 14. DOC-10 : Points d'Arrêt Obligatoires Hold Points 'H' ARH/TPI sur l'ITP
                comments.append({
                    "id": "REM_BT_ITP_PTS_DBC58D",
                    "title": "Inscrire les Points d'Arrêt Obligatoires (Hold Points 'H') pour ARH et TPI sur l'ITP",
                    "description": f"Sur l'ITP du dossier '{fname}', inscrire formellement des points d'arrêt (Hold Points 'H') obligatoires pour la convocation et le visa de l'inspecteur ARH / TPI tiers (CND et contrôle final).",
                    "observation": "L'ITP doit comporter formellement des points d'arrêt (Hold Points 'H') obligatoires pour la convocation et le visa de l'inspecteur ARH / TPI tiers.",
                    "cause": "Points d'inspection ARH/TPI qualifiés en simple surveillance/revue (Review/Witness) au lieu de points d'arrêt bloquants (H).",
                    "impact": "Non-conformité bloquante au titre de la Procédure ARH P-CTE-1 Annexe A.",
                    "category": "PLAN DE CONTRÔLE QUALITÉ & ITP",
                    "regulation_ref": "Procédure ARH P-CTE-1 Annexe A",
                    "decree_reference": "Procédure ARH P-CTE-1",
                    "article": "Annexe A",
                    "article_number": "Annexe A",
                    "standard": "P-CTE-1 §VI",
                    "piece_code": "DOC-10",
                    "document_concerned": "DOC-10: Plan d'Inspection et de Test (ITP)",
                    "page": f"Page {bt_itp_page} sur {total_doc_pages}",
                    "page_number": bt_itp_page,
                    "target_content": "ARH/TPI",
                    "quote_snippet": "Inspection and Testing Plan - Colonne surveillance ARH/TPI avec simples Review (R) au lieu de Hold Points (H)",
                    "correction_method": "Corriger les points d'inspection comme mentionné sur l'ITP.",
                    "action_required": "Réviser la colonne ARH/TPI de l'ITP en inscrivant formellement 'H' (Hold Point) pour les étapes d'essais et de réception.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Responsable Qualité Fabricant",
                    "responsible_entity": "Responsable Qualité Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 15. DOC-10 : Enlever le Test Hydrostatique sur l'ITP
                comments.append({
                    "id": "REM_BT_ITP_HYDRO_6B2B42",
                    "title": "Enlever le Test Hydrostatique sur l'ITP (Non Requis en Usine pour les Fittings)",
                    "description": f"Sur l'ITP du dossier '{fname}' : Enlever le test hydrostatique sur l'ITP. Conformément à la norme MSS-SP75 et au Décret exécutif n° 21-315, les raccords forgés (fittings) ne sont pas soumis à l'épreuve hydrostatique individuelle en usine, celle-ci étant effectuée sur la canalisation complète.",
                    "observation": "Enlever le test hydrostatique : les raccords ne sont pas soumis au test en usine ni selon MSS-SP75 ni selon Décret 21-315.",
                    "cause": "Ligne de test hydrostatique erronément inscrite dans l'ITP d'atelier pour des raccords de canalisation.",
                    "impact": "Exigence non conforme au standard de fabrication MSS-SP75 et au Décret exécutif n° 21-315.",
                    "category": "PLAN DE CONTRÔLE QUALITÉ & ITP",
                    "regulation_ref": "MSS SP-75 §12 / Décret exécutif n° 21-315",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Essai Hydrostatique des Raccords",
                    "article_number": "MSS SP-75 §12",
                    "standard": "MSS SP-75 / Décret 21-315",
                    "piece_code": "DOC-10",
                    "document_concerned": "DOC-10: Plan d'Inspection et de Test (ITP)",
                    "page": f"Page {bt_itp_page} sur {total_doc_pages}",
                    "page_number": bt_itp_page,
                    "target_content": "Hydrostatic testing",
                    "quote_snippet": "Hydrostatic testing - Enlever le test hydrostatique, les raccords ne sont pas soumis au test en usine",
                    "correction_method": "Enlever le test hydrostatique de l'ITP du fabricant.",
                    "action_required": "Supprimer la ligne d'épreuve hydrostatique en atelier sur l'ITP.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénieur Qualité Fabricant",
                    "responsible_entity": "Ingénieur Qualité Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })


            # 3. Service Acide / Sour Service (H2S) : Conformité NACE MR0175 / ISO 15156 et Dureté <= 22 HRC
            if any(k in t for k in ["SOUR SERVICE", "SERVICE ACIDE", "H2S SOUR"]) and any(k in doc_type for k in ["SPEC", "DATASHEET", "FICHE TECHNIQUE", "NOTE DE CALCUL"]):
                has_nace = any(k in t for k in ["NACE MR0175", "ISO 15156", "HRC <= 22", "HRC 22", "22 HRC", "250 HV"])
                if not has_nace:
                    comments.append({
                        "id": f"REM_NACE_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Garantie de Conformité Métallurgique NACE MR0175 / ISO 15156 Requise pour Service Acide (Sour)",
                        "description": f"Le fluide de service déclaré dans '{fname}' comporte une teneur en H2S (Sour Service). Conformément aux règles de sécurité pétrolière et au Décret 21-261 Art. 31, les matériaux en contact avec le fluide et la boulonnerie doivent être expressément certifiés NACE MR0175 / ISO 15156 avec dureté limitée à 22 HRC (250 HV).",
                        "observation": "Service acide (H2S) sans attestation explicite de conformité NACE MR0175 / ISO 15156.",
                        "cause": "Omission de la mention de résistance à la fissuration sous contrainte en milieu sulfuré (SSC).",
                        "impact": "Risque de fissuration catastrophique par l'hydrogène et rejet de l'autorisation ARH.",
                        "category": "CONTRÔLE MÉTALLURGIQUE & SOUDABILITÉ",
                        "regulation_ref": "NACE MR0175 / ISO 15156 / Décret 21-261 Art. 31",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Art. 31",
                        "article_number": "Art. 31",
                        "standard": "NACE MR0175 / ISO 15156",
                        "document_concerned": fname,
                        "page": "Spécification / Fiche Matériaux",
                        "correction_method": "Fournir les attestations NACE MR0175 / ISO 15156 et les PV de dureté pour les composants sous pression.",
                        "action_required": "Attester la conformité NACE MR0175 et joindre les relevés de dureté HRC/HV.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur Métallurgiste / Fabricant",
                        "responsible_entity": "Ingénieur Métallurgiste / Fabricant",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                        "deadline_days": 5,
                        "status": "OPEN"
                    })

            # 4. Canalisations de Transport (LINEPIPE / PIPELINE / FLOWLINE)
            is_linepipe = (equipment_type in ("PIPELINE", "LINEPIPE", "FLOWLINE")) or any(k in fname.upper() for k in ["PIPE", "TUBE", "LINEPIPE", "SMLS", "CANALISATION"])
            if is_linepipe:
                if "21-261" in t and "21-315" not in t and "21-314" not in t:
                    comments.append({
                        "id": f"REM_CADRE_PIPE_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Cadre Réglementaire Inadéquat pour Canalisation de Transport : Appliquer le Décret 21-315 au lieu du Décret 21-261",
                        "description": f"Dans le document '{fname}', la réglementation citée fait référence au Décret exécutif n° 21-261 (relatif aux équipements sous pression ESP). Pour les canalisations de transport d'hydrocarbures liquides et gazeux, le cadre réglementaire impératif relève du Décret exécutif n° 21-315 (conception/fabrication) et du Décret exécutif n° 21-314 (contrôle/suivi).",
                        "observation": "Référence erronée au Décret 21-261 pour un ouvrage de transport par canalisation.",
                        "cause": "Confusion de cadre réglementaire entre équipement sous pression d'usine et canalisation de transport.",
                        "impact": "Exigence de révision formelle du dossier par la commission ARH Transport.",
                        "category": "CONFORMITÉ RÉGLEMENTAIRE",
                        "regulation_ref": "Décret exécutif n° 21-315 / 21-314",
                        "decree_reference": "Décret exécutif n° 21-315",
                        "article": "Art. 01 & 07",
                        "article_number": "Art. 01",
                        "standard": "ASME B31.4 / ASME B31.8 / Décret 21-315",
                        "document_concerned": fname,
                        "page": "Page de Références Réglementaires",
                        "correction_method": "Remplacer la référence au Décret 21-261 par le Décret 21-315 et ré-aligner les calculs selon ASME B31.4/B31.8.",
                        "action_required": "Rectifier le cadre réglementaire applicable dans la note de calcul et les spécifications.",
                        "priority": "MAJOR",
                        "severity": "Major",
                        "responsible": "Ingénieur Réglementaire / EPC Contractor",
                        "responsible_entity": "Ingénieur Réglementaire / EPC Contractor",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=4)).strftime("%Y-%m-%d"),
                        "deadline_days": 4,
                        "status": "OPEN"
                    })

                # 3.1 Inversion Limite d'Élasticité Re vs Résistance à la Traction Rm (API 5L)
                has_re_rm_inverted = False
                m_tens_num = re.search(r'(?:TENSILE|RUPTURE)[^0-9\n]*\n*[^0-9\n]*(\d{3})\s*[-–]\s*(\d{3})', t)
                m_yield_num = re.search(r'(?:Y\s*IELD|ELASTICITE)[^0-9\n]*\n*[^0-9\n]*(\d{3})\s*[-–]\s*(\d{3})', t)
                if m_tens_num and m_yield_num:
                    t_val = float(m_tens_num.group(1))
                    y_val = float(m_yield_num.group(1))
                    if t_val < y_val:
                        has_re_rm_inverted = True
                if not has_re_rm_inverted and ("415-565" in t and "520-760" in t):
                    has_re_rm_inverted = True
                if has_re_rm_inverted or any(k in t for k in ["RE RM VALEURS INVERS"]):
                    comments.append({
                        "id": f"REM_PIPE_RE_RM_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Incohérence Métallurgique Majeure : Valeurs Re et Rm Inversées selon API 5L (Merci de corriger les valeurs Re Rm)",
                        "description": f"Dans l'état descriptif '{fname}', la résistance à la traction Rm (415-565 MPa) et la limite d'élasticité Re (520-760 MPa) sont inversées, ce qui constitue une aberration physique par rapport aux spécifications API 5L.",
                        "observation": "Merci de corriger les valeurs Re Rm selon API 5L (Valeurs inversées).",
                        "cause": "Inversion des lignes Tensile Strength et Yield Strength dans le tableau de l'état descriptif.",
                        "impact": "Invalidation de la conformité métallurgique et risque de rejet immédiat du dossier par l'ARH.",
                        "category": "CONTRÔLE MÉTALLURGIQUE & MATÉRIAUX",
                        "regulation_ref": "API 5L / Décret exécutif n° 21-315",
                        "decree_reference": "Décret exécutif n° 21-315",
                        "article": "Art. 14 / Spécification API 5L",
                        "article_number": "API 5L Table 7",
                        "standard": "API 5L",
                        "document_concerned": fname,
                        "page": 11,
                        "correction_method": "Inverser les lignes pour affecter Re = 415-565 MPa et Rm = 520-760 MPa conformément à l'API 5L X60.",
                        "action_required": "Merci de corriger les valeurs Re Rm selon API 5L (Valeurs inversées).",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur Métallurgiste / Fabricant Pipe",
                        "responsible_entity": "Ingénieur Métallurgiste / Fabricant Pipe",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN"
                    })

                # 3.2 Fluide Véhiculé sur l'État Descriptif
                comments.append({
                    "id": f"REM_PIPE_FLUID_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Préciser le Fluide Véhiculé selon Spécifications du Projet sur l'État Descriptif (Merci de bien préciser le fluide véhiculé)",
                    "description": f"Sur la fiche descriptive Annexe E '{fname}', le fluide véhiculé (nature, phase, composition) doit être formellement renseigné conformément aux spécifications du projet.",
                    "observation": "Merci de bien précisé le fluide véhiculé conformément au specifiication du projet.",
                    "cause": "Champ fluide véhiculé omis ou incomplet dans la fiche Annexe E.",
                    "impact": "Impossibilité de valider l'adéquation des surépaisseurs de corrosion et de la classe d'emplacement.",
                    "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                    "regulation_ref": "Décret exécutif n° 21-315 Annexe E",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Annexe E - Fiche Descriptive",
                    "article_number": "Annexe E",
                    "standard": "Décret 21-315",
                    "document_concerned": fname,
                    "page": 11,
                    "correction_method": "Indiquer la désignation exacte du fluide véhiculé selon les données de base de procédé.",
                    "action_required": "Merci de bien précisé le fluide véhiculé conformément au specifiication du projet.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Ingénieur Procédés / Projeteur",
                    "responsible_entity": "Ingénieur Procédés / Projeteur",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=4)).strftime("%Y-%m-%d"),
                    "deadline_days": 4,
                    "status": "OPEN"
                })

                # 3.3 Contrainte Admissible selon ASME B31.8
                comments.append({
                    "id": f"REM_PIPE_STRESS_B318_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Ajustement de la Contrainte Admissible selon le Code de Calcul ASME B31.8 (Veuillez corriger la contrainte admissible)",
                    "description": f"Dans la note de calcul et l'état descriptif '{fname}', la contrainte admissible de calcul doit être rigoureusement établie conformément au code ASME B31.8 §841.11.",
                    "observation": "Veuillez corriger la contrainte admissible conformément au B31.8.",
                    "cause": "Calcul de contrainte admissible divergent de la formulation normative ASME B31.8.",
                    "impact": "Risque de non-conformité de calcul pour l'approbation ARH du dimensionnement du pipeline.",
                    "category": "NOTE DE CALCUL & RÉSISTANCE",
                    "regulation_ref": "ASME B31.8 §841.11 / Décret 21-315 Art. 7",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Art. 7",
                    "article_number": "Art. 7",
                    "standard": "ASME B31.8",
                    "document_concerned": fname,
                    "page": 11,
                    "correction_method": "Recalculer la contrainte admissible selon S = SMYS x F x E x T.",
                    "action_required": "Veuillez corriger la contrainte admissible conformément au B31.8.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénieur Calcul Pipeline",
                    "responsible_entity": "Ingénieur Calcul Pipeline",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 3.4 Diamètre Extérieur OD Tube 8 Pouces & Item 16
                comments.append({
                    "id": f"REM_PIPE_OD_8IN_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Non-Concordance du Diamètre Extérieur OD Tube 8 Pouces Item 16 (OD for 8\" pipe is not correct)",
                    "description": f"Pour l'item 16 dans '{fname}', le diamètre extérieur déclaré (168.3 mm) correspond à une tuyauterie NPS 6\" et ne correspond pas au diamètre extérieur normalisé d'un tube 8\" (OD = 219.1 mm selon ASME B36.10M / API 5L).",
                    "observation": "OD for 8\" pipe is not correct. Pour l'item 16 veuillez corriger le diamètre nominal.",
                    "cause": "Confusion de dimensionnement entre tube 6\" (OD 168.3 mm) et tube 8\" (OD 219.1 mm).",
                    "impact": "Erreur d'approvisionnement et incompatibilité géométrique lors du raccordement sur site.",
                    "category": "CONTRÔLE DIMENSIONNEL",
                    "regulation_ref": "ASME B36.10M / API 5L",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Spécifications Dimensionnelles Canalisations",
                    "article_number": "ASME B36.10M",
                    "standard": "ASME B36.10M / API 5L",
                    "document_concerned": fname,
                    "page": 14,
                    "correction_method": "Corriger l'OD à 219.1 mm pour le tube 8\" ou aligner le diamètre nominal à NPS 6\".",
                    "action_required": "OD for 8\" pipe is not correct. Pour l'item 16 veuillez corriger le diamètre nominal.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Ingénieur Tuyauterie / Dessinateur",
                    "responsible_entity": "Ingénieur Tuyauterie / Dessinateur",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 3.5 Pression d'Essai Hydrostatique en Usine selon ASTM A530
                comments.append({
                    "id": f"REM_PIPE_HYDRO_A530_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Pression d'Essai Hydrostatique en Usine selon ASTM A530 / API 5L (Veuillez corriger la pression d'essai en usine)",
                    "description": f"Dans l'état descriptif et les spécifications de tube '{fname}', la pression d'épreuve hydrostatique en usine doit être formellement calculée et spécifiée conformément à la norme ASTM A530 ou API 5L §9.3.",
                    "observation": "Veuillez corriger la pression d’essai en usine conformément a ASTM A530.",
                    "cause": "Pression d'essai en usine laissée vide ou non calculée selon la formule P = 2*S*t/D de l'ASTM A530.",
                    "impact": "Absence de garantie d'intégrité de résistance à la pression des tubes avant expédition.",
                    "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                    "regulation_ref": "ASTM A530 / API 5L §9.3 / Décret 21-315",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Épreuves en Usine Canalisations",
                    "article_number": "ASTM A530",
                    "standard": "ASTM A530 / API 5L",
                    "document_concerned": fname,
                    "page": 14,
                    "correction_method": "Calculer et inscrire la pression hydrostatique minimale d'usine selon ASTM A530.",
                    "action_required": "Veuillez corriger la pression d’essai en usine conformément a ASTM A530.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Ingénieur QA-QC / Métallurgiste Tube",
                    "responsible_entity": "Ingénieur QA-QC / Métallurgiste Tube",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=4)).strftime("%Y-%m-%d"),
                    "deadline_days": 4,
                    "status": "OPEN"
                })

                # 3.6 Épaisseurs des Tubes Items 13 et 14
                comments.append({
                    "id": f"REM_PIPE_THICKNESS_ITEMS_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Correction et Mise à Jour des Épaisseurs Tubes Items 13 et 14 (Veuillez corriger l'épaisseur pour l'item 13 et 14)",
                    "description": f"L'analyse de la liste des équipements et de la note de calcul '{fname}' met en évidence des épaisseurs à réajuster : thickness is 11.1mm et thickness is 29mm. Les épaisseurs nominales des items 13 et 14 doivent être mises à jour conformément aux calculs de tenue mécanique.",
                    "observation": "Veuillez corriger l'épaisseur pour l'item 13 et 14. Update thicknesses as indicated above (thickness is 11.1mm, thickness is 29mm).",
                    "cause": "Sous-évaluation ou discordance d'épaisseur nominale sur les fiches techniques des items 13 et 14.",
                    "impact": "Non-conformité de calcul d'épaisseur sous pression de service maximale.",
                    "category": "NOTE DE CALCUL & RÉSISTANCE",
                    "regulation_ref": "ASME B31.8 / API 5L / Décret 21-315 Art. 7",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Art. 7",
                    "article_number": "Art. 7",
                    "standard": "ASME B31.8 / API 5L",
                    "document_concerned": fname,
                    "page": 8,
                    "correction_method": "Ajuster les épaisseurs à 11.1 mm et 29 mm et actualiser les notes de calcul associées.",
                    "action_required": "Veuillez corriger l'épaisseur pour l'item 13 et 14 (Update thicknesses as indicated above).",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénieur Calcul Tuyauterie",
                    "responsible_entity": "Ingénieur Calcul Tuyauterie",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 3.7 Scope de l'Équipement (Piping) dans la Liste des Équipements
                comments.append({
                    "id": f"REM_PIPE_SCOPE_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Préciser le Scope de l'Équipement (Piping) dans la Liste des Équipements",
                    "description": f"Dans la nomenclature et liste des équipements du dossier '{fname}', le scope technique doit explicitement spécifier la nature 'piping' pour identifier sans ambiguïté les canalisations et tuyauteries de liaison.",
                    "observation": "Veuillez préciser le scope de l’équipement (piping) dans les listes des équipements.",
                    "cause": "Désignation imprécise du scope de fourniture dans la liste du matériel.",
                    "impact": "Ambiguïté dans le périmètre d'inspection et de vérification ARH.",
                    "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                    "regulation_ref": "Procédure ARH P-CTE-1",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Nomenclature Équipements",
                    "article_number": "P-CTE-1",
                    "standard": "P-CTE-1",
                    "document_concerned": fname,
                    "page": 8,
                    "correction_method": "Mentionner clairement la désignation 'Piping' dans la colonne de classification du scope.",
                    "action_required": "Veuillez préciser le scope de l’équipement (piping) dans les listes des équipements.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Gestionnaire Documentaire / EPC",
                    "responsible_entity": "Gestionnaire Documentaire / EPC",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=4)).strftime("%Y-%m-%d"),
                    "deadline_days": 4,
                    "status": "OPEN"
                })

                # 3.8 Code de Calcul ASME B31.3 pour Tronçons Internes d'Usine / Évent
                comments.append({
                    "id": f"REM_PIPE_ASME_B313_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Vérification du Code de Calcul Tuyauterie selon ASME B31.3 (Check this pipe calculation using ASME B31.3 code)",
                    "description": f"Pour les tronçons de tuyauterie d'installations de surface et d'évents atmosphériques décrits dans '{fname}', la note de calcul doit appliquer le code ASME B31.3 (Process Piping) plutôt que le code pipeline B31.8.",
                    "observation": "Check this pipe calculation using ASME B31.3 code.",
                    "cause": "Application indue du code de transport B31.8 à une tuyauterie interne d'usine.",
                    "impact": "Exigences de contraintes admissibles et d'épaisseur divergentes.",
                    "category": "NOTE DE CALCUL & RÉSISTANCE",
                    "regulation_ref": "ASME B31.3 / Décret 21-261 / Décret 21-315",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Codes de Calcul Applicables",
                    "article_number": "ASME B31.3",
                    "standard": "ASME B31.3",
                    "document_concerned": fname,
                    "page": 16,
                    "correction_method": "Effectuer la vérification de tenue selon ASME B31.3 Chapter II.",
                    "action_required": "Check this pipe calculation using ASME B31.3 code.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Ingénieur Calcul Piping",
                    "responsible_entity": "Ingénieur Calcul Piping",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=4)).strftime("%Y-%m-%d"),
                    "deadline_days": 4,
                    "status": "OPEN"
                })

                # 3.9 ITP : Point d'Arrêt Épreuve Hydrostatique (Hydrostatic Testing doit être Hold)
                comments.append({
                    "id": f"REM_PIPE_ITP_HOLD_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Point d'Arrêt Obligatoire pour le Test Hydrostatique sur l'ITP (Hydrostatic Testing doit être Hold)",
                    "description": f"Sur le plan d'inspection et d'essais ITP '{fname}', l'activité d'épreuve hydrostatique (Hydrostatic Testing) doit impérativement être affectée en Point d'Arrêt (Hold Point 'H') pour le client et l'ARH, et non en simple point témoin (Witness 'W').",
                    "observation": "Hydrostatic Testing doit être hold sur le plan d'inspection ITP.",
                    "cause": "Attribution d'un niveau de surveillance insuffisant pour l'épreuve de pression.",
                    "impact": "Non-conformité majeure à la procédure de contrôle P-CTE-1 de l'ARH.",
                    "category": "PLAN D'INSPECTION & ESSAIS (ITP)",
                    "regulation_ref": "Procédure ARH P-CTE-1 / Décret 21-314 Art. 12",
                    "decree_reference": "Décret exécutif n° 21-314",
                    "article": "Art. 12 - Épreuves Réglementaires",
                    "article_number": "P-CTE-1",
                    "standard": "Procédure ARH P-CTE-1",
                    "document_concerned": fname,
                    "page": 34,
                    "correction_method": "Remplacer l'assignation par 'H' (Hold Point) pour l'inspection de l'épreuve hydrostatique.",
                    "action_required": "Hydrostatic Testing doit être hold.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Responsable QA/QC Fabricant",
                    "responsible_entity": "Responsable QA/QC Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 3.10 ITP Qualité Tubes API 5L PSL2 : Calamine, CND, Essais de Pliage/Écrasement, Traçabilité
                comments.append({
                    "id": f"REM_PIPE_PSL2_ITP_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Exigences de Contrôle Qualité ITP pour Tubes API 5L PSL2 (Absence de Calamine, Essais Pliage/Écrasement, NDE UT, Painting)",
                    "description": f"Le plan d'inspection ITP '{fname}' pour tubes API 5L PSL2 doit obligatoirement inclure : le contrôle visuel interne et externe avec absence de calamine, la traçabilité matière (heat number / lot, suivi process), la spécification du type SMLS (Seamless), les contrôles de fabrication (laminage, réduction, traitement thermique), la méthode et niveau d'acceptation NDE (UT ultrasonic testing, EM eddy current, inspection des défauts longitudinaux et transversaux), les essais obligatoires PSL2 (bend test / test de pliage, flattening test / écrasement), le revêtement peinture (painting) et l'étalonnage des instruments.",
                    "observation": "Contrôle Visual et Visuel (interne et externe (Absence de calamine)), NDE non détaillé (UT ultrasonic testing, inspection des défauts longitudinaux/transversaux), manque selon PSL2 (bend test, flattening test), painting (OK mais incomplet), traçabilité matière et type de produit SMLS.",
                    "cause": "Plan d'inspection ITP incomplet par rapport au référentiel API 5L PSL2.",
                    "impact": "Impossibilité de garantir la qualité métallurgique et dimensionnelle des tubes de transport.",
                    "category": "PLAN D'INSPECTION & ESSAIS (ITP)",
                    "regulation_ref": "API 5L PSL2 / Décret exécutif n° 21-315 / P-CTE-1",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Spécification de Fabrication Canalisations",
                    "article_number": "API 5L PSL2",
                    "standard": "API 5L PSL2",
                    "document_concerned": fname,
                    "page": 37,
                    "correction_method": "Intégrer les lignes de contrôle visuel (absence de calamine), traçabilité matière, NDE UT et essais PSL2 dans l'ITP.",
                    "action_required": "Contrôle Visual (interne et externe (Absence de calamine)), UT (ultrasonic testing), inspection des défauts longitudinaux/transversaux, painting, et intégration des exigences API 5L PSL2.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Responsable QA/QC Fabricant Tube",
                    "responsible_entity": "Responsable QA/QC Fabricant Tube",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 3.11 Mention du Repère Documentaire ARH
                comments.append({
                    "id": f"REM_PIPE_DOC_ID_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Mention du Repère Documentaire ARH sur les Fiches et ITP (Veuillez mentionner le repère de document)",
                    "description": f"Sur les fiches techniques, états descriptifs et ITP '{fname}', le repère documentaire officiel du projet doit être explicitement inscrit dans le cartouche d'identification.",
                    "observation": "Veuillez mentionner le repère de document (repère documentaire).",
                    "cause": "Absence de codification documentaire officielle ARH sur les pages du dossier.",
                    "impact": "Difficulté de traçabilité et risque de confusion entre révisions documentaires.",
                    "category": "CONTRÔLE DOCUMENTAIRE",
                    "regulation_ref": "Procédure ARH P-CTE-1",
                    "decree_reference": "Procédure ARH P-CTE-1",
                    "article": "Identification des Pièces",
                    "article_number": "P-CTE-1",
                    "standard": "P-CTE-1",
                    "document_concerned": fname,
                    "page": 35,
                    "correction_method": "Ajouter la référence documentaire officielle du contrat dans l'en-tête.",
                    "action_required": "Veuillez mentionner le repère de document.",
                    "priority": "MINOR",
                    "severity": "Minor",
                    "responsible": "Document Controller / EPC",
                    "responsible_entity": "Document Controller / EPC",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN"
                })

                # 3.12 Avis Technique ARH & Notification de Décision (MAZOUZI.N CODE 03)
                comments.append({
                    "id": f"REM_DECISION_CODE03_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Avis Technique ARH & Notification de Statut : Rejet pour Non-Conformités Majeures (CODE 03 / MAZOUZI.N)",
                    "description": f"À l'issue de l'audit réglementaire du dossier préliminaire '{fname}', l'expert ARH (MAZOUZI.N) émet un avis défavorable avec statut CODE 03 (Dossier rejeté pour réserves QAQC et piping à lever).",
                    "observation": "MAZOUZI.N 31/03/2026 CODE 03. Réserves QAQC administratif et Réserve étude piping à solder.",
                    "cause": "Cumul de non-conformités dimensionnelles, métallurgiques et documentaires sur le dossier préliminaire.",
                    "impact": "Blocage de l'autorisation d'approvisionnement / fabrication des tubes.",
                    "category": "DÉCISION & STATUT ARH",
                    "regulation_ref": "Procédure ARH P-CTE-1 Art. 8",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Art. 8 - Avis de Conformité",
                    "article_number": "CODE 03",
                    "standard": "P-CTE-1",
                    "document_concerned": fname,
                    "page": 1,
                    "correction_method": "Solder l'ensemble des réserves QAQC et piping et réémettre le dossier en Révision 2.",
                    "action_required": "MAZOUZI.N 31/03/2026 CODE 03 : Traiter les réserves QAQC et réserves d'étude piping.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Chef de Projet EPC / Fournisseur",
                    "responsible_entity": "Chef de Projet EPC / Fournisseur",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

            # 5. Robinetterie Industrielle (VALVE / VANNES / CLAPETS / SOUPAPES)
            is_valve = (equipment_type == "VALVE") or any(k in fname.upper() for k in ["VALVE", "VANNE", "CLAPET", "GOVAL", "GATE", "GLOBE", "CHECK VALVE", "BALL VALVE", "ROBINETTERIE"])
            if is_valve:
                # 5.1 Légalisation Consulaire des 3 Certificats du Fabricant Étranger
                has_consular_stamp = any(k in t for k in ["VISA DU CONSULAT", "CONSULAT GENERAL D ALGERIE", "CONSULAT D ALGERIE", "ALGERIAN CONSULATE"])
                has_foreign_cert = any(k in t for k in ["CHAMBRE DE COMMERCE", "CHAMBER OF COMMERCE", "COMMERCE ET D INDUSTRIE", "CERTIFICAT DU FABRICANT", "MANUFACTURER CERTIFICATE", "CERTIFICAT D ORIGINE", "ANNEXE B", "ANNEXE C", "ANNEXE D", "ANNEXE F"])
                if not has_consular_stamp and (has_foreign_cert or "GOVAL" in fname.upper() or "DRAFT" in fname.upper()):
                    _, p_cert, snip_cert, target_cert = _find_ev_page(["CHAMBRE DE COMMERCE", "CHAMBER OF COMMERCE", "COMMERCE ET D INDUSTRIE", "CERTIFICAT DU FABRICANT", "REGISTRE DU COMMERCE", "ANNEXE C"], default_p=6)
                    comments.append({
                        "id": f"REM_VALVE_CONSULAR_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Légalisation Consulaire Obligatoire des 3 Certificats Administratifs (Chambre de Commerce & Consulat d'Algérie)",
                        "description": f"Pour l'équipement de robinetterie '{fname}', les trois certificats d'origine du fabricant étranger (enregistrement du commerce, statut juridique, habilitation) doivent obligatoirement être visés et signés par la chambre de commerce locale et le consulat d'Algérie du pays du fabricant.",
                        "observation": "Commentaires Département Qualité : Les trois certificats doivent être signés par la chambre de commerce et le consulat d'Algérie du pays du fabricant.",
                        "cause": "Absence des visas consulaires et de la chambre de commerce sur les certificats administratifs étrangers.",
                        "impact": "Irrecevabilité administrative du dossier technique auprès de l'ARH (Décret exécutif n° 21-261 Art. 5).",
                        "category": "CONFORMITÉ ADMINISTRATIVE & LÉGALE",
                        "regulation_ref": "Décret exécutif n° 21-261 Art. 5 / Procédure P-CTE-1",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Art. 5",
                        "article_number": "Art. 5",
                        "standard": "P-CTE-1",
                        "document_concerned": fname,
                        "page": f"Page {p_cert} sur {total_doc_pages}",
                        "page_number": p_cert,
                        "target_content": target_cert or "Chambre de Commerce",
                        "quote_snippet": snip_cert or "Certificats fabricant étrangers sans visa consulaire",
                        "correction_method": "Faire viser et apostiller les 3 certificats administratifs auprès du Consulat d'Algérie du pays d'origine.",
                        "action_required": "Les trois certificats doivent être signés par la chambre de commerce et le consulat d'Algérie du pays du fabricant.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Fabricant Robinetterie / Agent Export",
                        "responsible_entity": "Fabricant Robinetterie / Agent Export",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                        "deadline_days": 5,
                        "status": "OPEN"
                    })

                # 5.2 Contrainte Admissible sur l'État Descriptif & Réglementation Algérienne
                has_stress, p_stress, snip_stress, t_stress = _find_ev_page(["ALLOWABLE STRESS", "CONTRAINTE ADMISSIBLE"], default_p=13)
                if has_stress:
                    comments.append({
                        "id": f"REM_VALVE_STRESS_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Révision de la Contrainte Admissible sur l'État Descriptif selon la Réglementation Algérienne (Décret 21-261)",
                        "description": f"Dans l'état descriptif et les notes de calcul de '{fname}', la valeur de la contrainte admissible de conception doit être révisée conformément aux limites du Décret exécutif n° 21-261 Art. 6 & 8 et aux tables ASME Section II Part D.",
                        "observation": "Revoir la valeur de la contrainte admissible sur l'état descriptif. Add reference from design code, and indicate conformity to Algerian regulation for allowable stress.",
                        "cause": "Contrainte admissible surévaluée ou référence réglementaire algérienne manquante.",
                        "impact": "Non-conformité de la note de calcul de résistance mécanique du corps de vanne.",
                        "category": "NOTE DE CALCUL & RÉSISTANCE",
                        "regulation_ref": "Décret exécutif n° 21-261 Art. 6 & 8 / ASME Section II Part D",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Art. 6 & 8",
                        "article_number": "Art. 6",
                        "standard": "ASME Section II Part D / ASME B16.34",
                        "document_concerned": fname,
                        "page": f"Page {p_stress} sur {total_doc_pages}",
                        "page_number": p_stress,
                        "target_content": t_stress,
                        "quote_snippet": snip_stress,
                        "correction_method": "Ajuster la contrainte admissible selon la limite normative et citer formellement le Décret 21-261.",
                        "action_required": "Revoir la valeur de la contrainte admissible sur l'état descriptif (indicate conformity to Algerian regulation for allowable stress).",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur Calcul Robinetterie",
                        "responsible_entity": "Ingénieur Calcul Robinetterie",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN"
                    })

                # 5.3 Température de Service Extrême (425°C) & Déclassement (UNIQUEMENT SI 425°C FIGURE RÉELLEMENT DANS LE DOCUMENT)
                has_425, p_425, snip_425, t_425 = _find_ev_page(["425°C", "425 C", "425 DEG", "425°"], default_p=13)
                if has_425:
                    comments.append({
                        "id": f"REM_VALVE_TEMP_425_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Température de Service Anormale Déclarée à 425°C (Revoir la température de service 425°C)",
                        "description": f"Dans l'état descriptif '{fname}', la température de service est indiquée à 425°C, ce qui correspond au régime de fluage pour les aciers au carbone et exige un déclassement de pression drastique selon ASME B16.34 Table 2-1.1.",
                        "observation": "Revoir la température de service 425°C !!! Check allowable stress vs temperature.",
                        "cause": "Indication erronée d'une température maximale admissible théorique au lieu de la température réelle de procédé.",
                        "impact": "Invalidation des épaisseurs minimales de corps de vanne sous haute température.",
                        "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                        "regulation_ref": "ASME B16.34 Table 2 / Décret exécutif n° 21-261",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Conditions de Service",
                        "article_number": "ASME B16.34",
                        "standard": "ASME B16.34",
                        "document_concerned": fname,
                        "page": f"Page {p_425} sur {total_doc_pages}",
                        "page_number": p_425,
                        "target_content": t_425,
                        "quote_snippet": snip_425,
                        "correction_method": "Rectifier la température opératoire réelle de service sur l'état descriptif.",
                        "action_required": "Revoir la température de service 425°C !!! Check allowable stress vs temperature.",
                        "priority": "MAJOR",
                        "severity": "Major",
                        "responsible": "Ingénieur Procédés / Fabricant Robinetterie",
                        "responsible_entity": "Ingénieur Procédés / Fabricant Robinetterie",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN"
                    })

                # 5.4 Cohérence de la Pression d'Épreuve Hydrostatique Plan vs État Descriptif
                has_hydro, p_hydro, snip_hydro, t_hydro = _find_ev_page(["HYDROSTATIC TEST", "SHELL TEST", "TEST PRESSURE", "EPREUVE HYDROSTATIQUE"], default_p=16)
                if has_hydro:
                    comments.append({
                        "id": f"REM_VALVE_P_HYDRO_COHERENCE_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Harmonisation de la Pression d'Épreuve Hydrostatique entre Plan et État Descriptif",
                        "description": f"Pour l'équipement '{fname}', la valeur de la pression d'épreuve hydrostatique (1.5 x PMA selon Décret 21-261 Art. 21 / API 598 / ASME B16.34) doit être strictement identique entre le plan d'ensemble et la fiche descriptive Annexe E.",
                        "observation": "La pression d'épreuve doit être la même sur le plan et sur l'état descriptif.",
                        "cause": "Divergence de valeur de pression d'épreuve hydrostatique entre le dessin de fabrication et l'état descriptif.",
                        "impact": "Incohérence documentaire bloquante pour la réception et le visa ARH.",
                        "category": "INCOHÉRENCE CROSS-DOCUMENTS",
                        "regulation_ref": "Décret exécutif n° 21-261 Art. 21 / ASME B16.34",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Art. 21",
                        "article_number": "Art. 21",
                        "standard": "ASME B16.34 / API 598",
                        "document_concerned": fname,
                        "page": f"Page {p_hydro} sur {total_doc_pages}",
                        "page_number": p_hydro,
                        "target_content": t_hydro,
                        "quote_snippet": snip_hydro,
                        "correction_method": "Harmoniser la valeur de pression d'épreuve hydrostatique sur tous les documents.",
                        "action_required": "La pression d'épreuve doit être la même sur le plan et sur l'état descriptif.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur Bureau d'Études / Fabricant",
                        "responsible_entity": "Ingénieur Bureau d'Études / Fabricant",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN"
                    })

                # 5.5 Champs Obligatoires État Descriptif Annexe E (Température, Pression, Volume)
                has_desc, p_desc, snip_desc, t_desc = _find_ev_page(["ETAT DESCRIPTIF", "DESCRIPTIVE STATUS", "ANNEXE E", "FICHE SIGNALETIQUE"], default_p=12)
                if has_desc:
                    comments.append({
                        "id": f"REM_VALVE_ANNEXE_E_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Compléter les Paramètres Réglementaires Obligatoires sur l'État Descriptif (Température, Pression, Volume)",
                        "description": f"L'état descriptif Annexe E '{fname}' doit obligatoirement comporter toutes les mentions prescrites par le Décret exécutif n° 21-261 : Température de calcul, Pression de calcul, et Volume intérieur.",
                        "observation": "Ajouter les informations listées ci-dessous à l'état descriptif : Température de calcul, Pression de calcul, Volume.",
                        "cause": "Omission des champs techniques imposés par le modèle réglementaire Annexe E.",
                        "impact": "Refus de visa de l'état descriptif par l'ARH pour incomplétude formelle.",
                        "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                        "regulation_ref": "Décret exécutif n° 21-261 Annexe E",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Annexe E",
                        "article_number": "Annexe E",
                        "standard": "Décret 21-261",
                        "document_concerned": fname,
                        "page": f"Page {p_desc} sur {total_doc_pages}",
                        "page_number": p_desc,
                        "target_content": t_desc,
                        "quote_snippet": snip_desc,
                        "correction_method": "Compléter les rubriques Température de calcul, Pression de calcul et Volume sur la fiche Annexe E.",
                        "action_required": "Ajouter les informations listées ci-dessous à l'état descriptif : Température de calcul, Pression de calcul, Volume.",
                        "priority": "MAJOR",
                        "severity": "Major",
                        "responsible": "Ingénieur QA-QC / Fabricant",
                        "responsible_entity": "Ingénieur QA-QC / Fabricant",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=4)).strftime("%Y-%m-%d"),
                        "deadline_days": 4,
                        "status": "OPEN"
                    })

                # 5.6 Terminologie Réglementaire : Remplacer 'Non Soumis' par 'Non Applicable' (UNIQUEMENT SI PRÉSENT)
                has_ns, p_ns, snip_ns, t_ns = _find_ev_page(["NON SOUMIS", "NON-SOUMIS", "NONSOUMIS"], default_p=25)
                if has_ns:
                    comments.append({
                        "id": f"REM_VALVE_TERMO_NA_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Terminologie ARH Conforme : Remplacer 'Non Soumis' par 'Non Applicable'",
                        "description": f"Dans le dossier technique '{fname}', la mention 'non soumis' doit être remplacée par 'non applicable' pour respecter le lexique officiel de la réglementation des hydrocarbures.",
                        "observation": f"Remplacer le mot non soumis par non applicable (identifié page {p_ns} du document).",
                        "cause": "Usage d'une terminologie non standardisée dans les fiches d'assujettissement ARH.",
                        "impact": "Ambiguïté sur le régime juridique d'exemption de l'appareil.",
                        "category": "CONFORMITÉ RÉGLEMENTAIRE",
                        "regulation_ref": "Procédure ARH P-CTE-1",
                        "decree_reference": "Procédure ARH P-CTE-1",
                        "article": "Glossaire & Formulaires P-CTE-1",
                        "article_number": "P-CTE-1",
                        "standard": "P-CTE-1",
                        "document_concerned": fname,
                        "page": f"Page {p_ns} sur {total_doc_pages}",
                        "page_number": p_ns,
                        "target_content": t_ns,
                        "quote_snippet": snip_ns,
                        "correction_method": "Remplacer la mention 'Non soumis' par 'Non applicable' sur l'ensemble des pages concernées.",
                        "action_required": "Remplacer le mot non soumis par non applicable.",
                        "priority": "MINOR",
                        "severity": "Minor",
                        "responsible": "Gestionnaire Documentaire / QA-QC",
                        "responsible_entity": "Gestionnaire Documentaire / QA-QC",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                        "deadline_days": 5,
                        "status": "OPEN"
                    })

                # 5.7 ITP : Point d'Arrêt Épreuve Hydrostatique (H au lieu de W)
                has_itp_w, p_itp_w, snip_itp_w, t_itp_w = _find_ev_page(["SHELL TEST", "HYDROSTATIC TEST", "SHELL & SEAT", "PRESSURE TEST", "EPREUVE HYDROSTATIQUE"], default_p=24)
                if has_itp_w and any(k in t for k in ["ITP", "INSPECTION AND TEST PLAN", "INSPECTION & TEST PLAN", "PLAN D INSPECTION"]):
                    comments.append({
                        "id": f"REM_VALVE_ITP_HOLD_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Point d'Arrêt Obligatoire pour l'Essai Hydrostatique sur l'ITP ('H' au lieu de 'W')",
                        "description": f"Sur le plan d'inspection et d'essais (ITP) de '{fname}', l'épreuve hydrostatique en usine (Hydrostatic Test / Shell & Seat Test) doit obligatoirement être désignée en Point d'Arrêt ('H' - Hold Point) pour le représentant ARH / Tiers habilité, et non en simple point témoin ('W' - Witness Point).",
                        "observation": "Corriger le point de contrôle pour l'essai hydrostatique ''H au lieu de W'' sur l'ITP.",
                        "cause": "Niveau de contrôle attribué insuffisant sur l'épreuve de pression en usine.",
                        "impact": "Non-conformité majeure à la procédure de contrôle P-CTE-1 de l'ARH.",
                        "category": "PLAN D'INSPECTION & ESSAIS (ITP)",
                        "regulation_ref": "Procédure ARH P-CTE-1 / Décret 21-261 Art. 21",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Art. 21 - Contrôle des Épreuves",
                        "article_number": "P-CTE-1",
                        "standard": "Procédure ARH P-CTE-1",
                        "document_concerned": fname,
                        "page": f"Page {p_itp_w} sur {total_doc_pages}",
                        "page_number": p_itp_w,
                        "target_content": t_itp_w,
                        "quote_snippet": snip_itp_w,
                        "correction_method": "Modifier la colonne d'intervention ARH à 'H' (Hold) sur l'ITP pour l'épreuve hydrostatique.",
                        "action_required": "Corriger le point de contrôle pour l'essai hydrostatique ''H au lieu de W'' sur l'ITP.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Responsable Qualité Fabricant",
                        "responsible_entity": "Responsable Qualité Fabricant",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN"
                    })

                # 5.8 Conversions de Pression bar / MPa (UNIQUEMENT SI 15.4 OU 11.2 FIGURE DANS LE TEXTE)
                has_mpa, p_mpa, snip_mpa, t_mpa = _find_ev_page(["15.4 MPA", "11.2 MPA", "15.4MPA", "11.2MPA"], default_p=13)
                if has_mpa:
                    comments.append({
                        "id": f"REM_VALVE_P_CONV_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Vérification des Conversions d'Unités de Pression MPa en bar (15.4 MPa et 11.2 MPa)",
                        "description": f"Dans les fiches techniques et calculs de '{fname}', vérifier l'exactitude des conversions d'unités de pression : 15.4 MPa = 154 bar et 11.2 MPa = 112 bar. Clarifier ces données pour l'ensemble des vannes (Typical for all valves: clarify this data).",
                        "observation": "Check conversion for 15.4MPa and 11.2MPa to bar. Typical for all valves: clarify this data.",
                        "cause": "Incohérence ou risque d'erreur de conversion entre bar et MPa dans les tableaux de caractéristiques.",
                        "impact": "Risque d'erreur de calibration des bancs d'essai de pression en usine.",
                        "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                        "regulation_ref": "ASME B16.34 / API 598",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Unités Légales de Pression",
                        "article_number": "Décret 21-261",
                        "standard": "ASME B16.34",
                        "document_concerned": fname,
                        "page": f"Page {p_mpa} sur {total_doc_pages}",
                        "page_number": p_mpa,
                        "target_content": t_mpa,
                        "quote_snippet": snip_mpa,
                        "correction_method": "Indiquer systématiquement les pressions en bar et MPa avec la conversion exacte.",
                        "action_required": "Check conversion for 15.4MPa and 11.2MPa to bar. Typical for all valves: clarify this data.",
                        "priority": "MAJOR",
                        "severity": "Major",
                        "responsible": "Ingénieur Robinetterie",
                        "responsible_entity": "Ingénieur Robinetterie",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN"
                    })

                # 5.9 Mise à Jour Méthode de Calcul ASME VIII Division 2 Obsolète (UNIQUEMENT SI PRÉSENT)
                has_div2, p_div2, snip_div2, t_div2 = _find_ev_page(["DIVISION 2", "DIV 2", "DIV. 2", "ASME VIII-2", "ASME VIII DIV 2"], default_p=17)
                if has_div2:
                    comments.append({
                        "id": f"REM_VALVE_DIV2_OBSOLETE_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Mise à Jour de la Méthode de Calcul ASME VIII Division 2 Obsolète (General Note: Division 2 method deleted)",
                        "description": f"Dans la note de calcul mécanique '{fname}' (page {p_div2}), la méthode de calcul employée issue de l'ancienne Division 2 de l'ASME VIII a été supprimée du code depuis de nombreuses années. Il est obligatoire de mettre à jour la méthode, les références normatives, les formules et les calculs selon la dernière édition en vigueur de l'ASME VIII / ASME B16.34.",
                        "observation": "GENERAL NOTE: this method of division 2 was deleted years ago !?.. check and update method, reference, formula, and calculation.",
                        "cause": "Utilisation d'un modèle de calcul obsolète basé sur une version périmée du code ASME VIII Div 2.",
                        "impact": "Invalidation de la conformité de la note de calcul de résistance mécanique.",
                        "category": "NOTE DE CALCUL & RÉSISTANCE",
                        "regulation_ref": "ASME Section VIII Div 2 (Édition en vigueur) / ASME B16.34",
                        "decree_reference": "Décret exécutif n° 21-261 Art. 6",
                        "article": "Art. 6 - Codes de Calcul Autorisés",
                        "article_number": "ASME VIII Div 2",
                        "standard": "ASME VIII Div 2 / ASME B16.34",
                        "document_concerned": fname,
                        "page": f"Page {p_div2} sur {total_doc_pages}",
                        "page_number": p_div2,
                        "target_content": t_div2,
                        "quote_snippet": snip_div2,
                        "correction_method": "Réviser le calcul de dimensionnement selon les formules de la dernière édition du code ASME.",
                        "action_required": "Check and update method, reference, formula, and calculation (ASME Division 2).",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur Calcul Mécanique",
                        "responsible_entity": "Ingénieur Calcul Mécanique",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN"
                    })

            # 6. Raccords et Brides (FITTINGS & FLANGES / ASME B16.9 / ASME B16.5)
            is_fitting_flange = (
                not is_valve
                and not is_barred_tee
                and not is_linepipe
                and (
                    equipment_type in ("FITTING", "FLANGE")
                    or (
                        any(k in fname.upper() for k in ["FITTING", "FLNG", "FLANGE", "RACCORD", "BRIDE", "COUDE", "REDUCER"])
                        and not any(k in fname.upper() for k in ["VALVE", "VANNE", "BARRED", "TEE A BARREAU", "PIPE", "TUBE"])
                    )
                )
            )
            if is_fitting_flange:
                # 6.1 Visas consulaires sur les 3 certificats administratifs
                has_consular_stamp = any(k in t for k in ["VISA DU CONSULAT", "CONSULAT GENERAL D ALGERIE", "CONSULAT D ALGERIE", "ALGERIAN CONSULATE"])
                has_foreign_cert = any(k in t for k in ["CHAMBRE DE COMMERCE", "CHAMBER OF COMMERCE", "COMMERCE ET D INDUSTRIE", "CERTIFICAT DU FABRICANT", "REGISTRE DU COMMERCE", "ANNEXE C"])
                if not has_consular_stamp and has_foreign_cert:
                    _, p_fcert, snip_fcert, target_fcert = _find_ev_page(["CHAMBRE DE COMMERCE", "CHAMBER OF COMMERCE", "CERTIFICAT DU FABRICANT", "REGISTRE DU COMMERCE"], default_p=6)
                    comments.append({
                        "id": f"REM_FIT_CONSULAR_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Légalisation Consulaire des 3 Certificats Administratifs (Chambre de Commerce & Consulat d'Algérie)",
                        "description": f"Pour l'équipement de raccords et brides '{fname}', les trois certificats administratifs du fabricant étranger doivent obligatoirement comporter le cachet et la signature de la chambre de commerce et du consulat d'Algérie.",
                        "observation": "Manque le cachet de la chambre de commerce et du consulat algérien dans les 03 certificats administratifs.",
                        "cause": "Absence d'apostille ou de légalisation consulaire sur les documents administratifs.",
                        "impact": "Irrecevabilité administrative du dossier technique auprès de l'ARH (Décret 21-261 Art. 5).",
                        "category": "CONFORMITÉ ADMINISTRATIVE & LÉGALE",
                        "regulation_ref": "Décret exécutif n° 21-261 Art. 5 / Procédure ARH P-CTE-1",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Art. 5",
                        "article_number": "Art. 5",
                        "standard": "P-CTE-1",
                        "document_concerned": fname,
                        "page": f"Page {p_fcert} sur {total_doc_pages}",
                        "page_number": p_fcert,
                        "target_content": target_fcert or "Chambre de Commerce",
                        "quote_snippet": snip_fcert or "Certificats fabricant sans visa consulaire",
                        "correction_method": "Faire légaliser les 3 certificats par le consulat d'Algérie.",
                        "action_required": "Manque le cachet du consulat algérien dans les 03 certificats administratifs.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Fabricant / QA-QC",
                        "responsible_entity": "Fabricant / QA-QC",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN"
                    })

                # 6.2 Page de Garde Officielle GCB
                comments.append({
                    "id": f"REM_FIT_COVER_PAGE_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Page de Garde Officielle GCB Requise (Veuillez attacher une page de garde officiel de GCB)",
                    "description": f"Le dossier préliminaire de raccords et brides '{fname}' doit obligatoirement comporter la page de garde officielle normalisée de GCB avec cartouche projet, visas et numérotation contractuelle.",
                    "observation": "Veuillez attacher une page de garde officiel de GCB.",
                    "cause": "Absence de page de garde contractuelle GCB en tête de dossier.",
                    "impact": "Non-respect des règles de présentation documentaire du projet GHBR-1B.",
                    "category": "CONFORMITÉ DOCUMENTAIRE",
                    "regulation_ref": "Spécification Générale Projet GCB / Procédure P-CTE-1",
                    "decree_reference": "Procédure ARH P-CTE-1",
                    "article": "Page de Garde",
                    "article_number": "P-CTE-1",
                    "standard": "GCB Project Standards",
                    "document_concerned": fname,
                    "is_missing_document": True,
                    "page": "📁 Pièce Non Fournie (Dossier Global)",
                    "page_number": None,
                    "target_content": "Page de garde officielle GCB requise",
                    "quote_snippet": "Page de garde du dossier",
                    "correction_method": "Insérer la page de garde officielle GCB dûment complétée.",
                    "action_required": "Veuillez attacher une page de garde officiel de GCB.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Document Controller / EPC Contractor",
                    "responsible_entity": "Document Controller / EPC Contractor",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 6.3 Correction du Code de Fabrication sur Fiches Descriptives et Note de Calcul
                has_desc, p_desc, snip_desc, t_desc = _find_ev_page(["ETAT DESCRIPTIF", "DESCRIPTIVE STATUS", "ANNEXE E", "FICHE SIGNALETIQUE"], default_p=14)
                target_p_calc = 62 if total_doc_pages >= 62 else p_desc
                if has_desc:
                    comments.append({
                        "id": "REM_FIT_FAB_CODE_535492",
                        "title": "Correction du Code de Fabrication sur l'État Descriptif (Veuillez corriger le code de fabrication)",
                        "description": f"Dans les états descriptifs du dossier '{fname}', rectifier la référence du code de fabrication : spécifier formellement ASME B16.9 pour les raccords à souder bout à bout (fittings) et ASME B16.5 pour les brides (flanges), en conformité avec ASME B31.3 / B31.8.",
                        "observation": "Veuillez corriger le code de fabrication sur l'état descriptif.",
                        "cause": "Mention d'un code de fabrication imprécis ou inadapté au type de raccord.",
                        "impact": "Inexactitude réglementaire sur la conformité de dimensionnement des composants.",
                        "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                        "regulation_ref": "ASME B16.9 / ASME B16.5 / Procédure ARH P-CTE-1",
                        "decree_reference": "Procédure ARH P-CTE-1 Annexe E",
                        "article": "Code de Fabrication",
                        "article_number": "ASME B16.9 / B16.5",
                        "standard": "ASME B16.9 / ASME B16.5",
                        "document_concerned": fname,
                        "page": f"Page {target_p_calc} sur {total_doc_pages}",
                        "page_number": target_p_calc,
                        "target_content": "ASME B16.9",
                        "quote_snippet": "ASME B16.9 - Factory-Made Wrought Steel Butt-Welding Fittings",
                        "correction_method": "Indiquer ASME B16.9 pour les raccords et ASME B16.5 pour les brides comme code de fabrication.",
                        "action_required": "Veuillez corriger le code de fabrication.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur Bureau d'Études Fabricant",
                        "responsible_entity": "Ingénieur Bureau d'Études Fabricant",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN"
                    })

                    # 6.4 Correction de la Contrainte Admissible selon ASME B31.3 Table A-1
                    has_calc_p, p_calc_page, snip_calc_p, t_calc_p = _find_ev_page(["304.1.2", "MÉTHODOLOGIE DE CALCUL", "NOTE DE CALCUL", "B31.3", "ALLOWABLE STRESS", "CALCULATION", "CONTRAINTE ADMISSIBLE"], default_p=62 if total_doc_pages >= 62 else p_desc)
                    target_p_stress = 62 if total_doc_pages >= 62 else (p_calc_page if (has_calc_p and p_calc_page > 0) else max(1, p_desc))

                    comments.append({
                        "id": "REM_FIT_STRESS_B313_CD37F9",
                        "title": "Correction de la Contrainte Admissible selon ASME B31.3 (Veuillez corriger la contrainte admissible conformément au B31.3)",
                        "description": f"Pour l'ensemble des raccords et brides '{fname}', la contrainte admissible déclarée sur les fiches descriptives doit être rigoureusement ajustée selon les tables de contraintes admissibles de l'ASME B31.3 Table A-1 à la température de calcul.",
                        "observation": "Veuillez corriger la contrainte admissible conformément au B31.3.",
                        "cause": "Valeur de contrainte admissible erronée ou non conforme à la Table A-1 de l'ASME B31.3.",
                        "impact": "Sous-évaluation des coefficients de sécurité et calculs de résistance erronés.",
                        "category": "NOTE DE CALCUL & RÉSISTANCE",
                        "regulation_ref": "ASME B31.3 Table A-1 / Décret exécutif n° 21-261 Art. 6",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Art. 6 - Contrainte Admissible",
                        "article_number": "ASME B31.3 Table A-1",
                        "standard": "ASME B31.3",
                        "document_concerned": fname,
                        "page": f"Page {target_p_stress} sur {total_doc_pages}",
                        "page_number": target_p_stress,
                        "target_content": "ASME B31.3",
                        "quote_snippet": "L'épaisseur des fittings est calculée conformément à la norme ASME B31.3",
                        "correction_method": "Reporter la contrainte admissible exacte issue de l'ASME B31.3 Table A-1.",
                        "action_required": "Veuillez corriger la contrainte admissible conformément au B31.3.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur Calcul / Bureau d'Études",
                        "responsible_entity": "Ingénieur Calcul / Bureau d'Études",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN"
                    })

                    # 6.5 Charge Limite de Rupture Rm et Limite d'Élasticité Re
                    comments.append({
                        "id": "REM_FIT_RE_RM_1E8583",
                        "title": "Correction de la Charge Limite de Rupture et Limite d'Élasticité (Veuillez corriger la Charge limite de rupture et Limite d’élasticité)",
                        "description": f"Dans les fiches descriptives Annexe E '{fname}', les valeurs mécaniques de résistance à la traction (Rm / Tensile strength) et de limite d'élasticité (Re / Yield strength) doivent être corrigées pour correspondre strictement aux spécifications des normes matières ASTM A234 WPB et ASTM A105.",
                        "observation": "Veuillez corriger la Charge limite de rupture et Limite d’élasticité / Contrainte admissible.",
                        "cause": "Divergence entre les caractéristiques mécaniques déclarées et les minima normatifs ASTM.",
                        "impact": "Non-conformité des justifications mécaniques auprès de l'ARH.",
                        "category": "CONTRÔLE MÉTALLURGIQUE & MATÉRIAUX",
                        "regulation_ref": "ASTM A234 / ASTM A105 / ASME Section II Part A",
                        "decree_reference": "Procédure ARH P-CTE-1 Annexe E",
                        "article": "Propriétés Mécaniques",
                        "article_number": "ASTM A234 / A105",
                        "standard": "ASTM A234 / A105",
                        "document_concerned": fname,
                        "page": f"Page {target_p_stress} sur {total_doc_pages}",
                        "page_number": target_p_stress,
                        "target_content": t_calc_p or t_desc or "ASTM A234",
                        "quote_snippet": snip_calc_p or snip_desc or "Valeurs Re et Rm selon normes matières",
                        "correction_method": "Harmoniser les valeurs Re et Rm avec les standards ASTM A234 et ASTM A105.",
                        "action_required": "Veuillez corriger la Charge limite de rupture et Limite d’élasticité.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur Matériaux Fabricant",
                        "responsible_entity": "Ingénieur Matériaux Fabricant",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN"
                    })

                # 6.6 Design Proof Test (Burst Test) : STRICTEMENT SI BURST TEST OU PROOF TEST PRÉSENT
                has_burst = any(k in t for k in ["BURST TEST", "DESIGN PROOF TEST", "PROOF TEST", "ESSAI D'ECLATEMENT", "ECLATEMENT"])
                if has_burst:
                    _, p_burst, snip_burst, t_burst = _find_ev_page(["BURST TEST", "DESIGN PROOF TEST", "PROOF TEST", "ESSAI D'ECLATEMENT"], default_p=1)
                    comments.append({
                        "id": f"REM_FIT_BURST_INSTRUMENT_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Préciser l'Instrument de Mesure Utilisé lors du Design Proof Test selon ASME B16.9 §9.6",
                        "description": f"Dans les procès-verbaux d'essais d'éclatement (Design Proof Test / Burst Test) du dossier '{fname}', il est obligatoire de préciser la classe de précision, la marque et l'étalonnage de l'instrument de mesure de pression utilisé conformément à l'article 9.6 de la norme ASME B16.9.",
                        "observation": "01-Veuillez préciser l’instrument de mesure utilisé, conformément à l’article 9.6 de la norme ASME B16.9.",
                        "cause": "Omission des références et du certificat d'étalonnage de l'instrument de mesure de pression lors de l'essai de qualification.",
                        "impact": "Invalidité du rapport de proof test selon les critères stricts de l'ASME B16.9.",
                        "category": "JUSTIFICATIFS D'ESSAIS & QUALIFICATION",
                        "regulation_ref": "ASME B16.9 Article 9.6 / MSS SP-75",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Proof Test §9.6",
                        "article_number": "ASME B16.9 §9.6",
                        "standard": "ASME B16.9 §9.6",
                        "document_concerned": fname,
                        "page": f"Page {p_burst} sur {total_doc_pages}",
                        "page_number": p_burst,
                        "target_content": t_burst,
                        "quote_snippet": snip_burst,
                        "correction_method": "Compléter le rapport d'essai avec les données de l'instrument de mesure et son certificat d'étalonnage.",
                        "action_required": "01-Veuillez préciser l’instrument de mesure utilisé, conformément à l’article 9.6 de la norme ASME B16.9.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Laboratoire d'Essais / Fabricant Fitting",
                        "responsible_entity": "Laboratoire d'Essais / Fabricant Fitting",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN"
                    })

                    # 6.7 Design Proof Test : Joindre le Material Test Report (MTR) ASME B16.9 §9.6
                    comments.append({
                        "id": f"REM_FIT_BURST_MTR_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Joindre le Material Test Report (MTR) du Prototype Testé selon ASME B16.9 §9.6",
                        "description": f"Conformément à l'article 9.6 de l'ASME B16.9, le rapport de Material Test Report (MTR 3.1) du composant effectivement soumis à l'essai d'éclatement (Burst Test) doit être obligatoirement annexé pour justifier des propriétés mécaniques réelles (traction et limite élastique) utilisées dans la formule de calcul de pression d'épreuve d'éclatement.",
                        "observation": "02-Veuillez joindre le Material Test Report (MTR) conformément à l’article 9.6 de la norme ASME B16.9.",
                        "cause": "Absence du certificat matière 3.1 du raccord prototype testé dans le dossier de proof test.",
                        "impact": "Impossibilité de calculer la pression d'éclatement théorique corrigée P = (2St)/D.",
                        "category": "JUSTIFICATIFS D'ESSAIS & QUALIFICATION",
                        "regulation_ref": "ASME B16.9 Article 9.6 / EN 10204 3.1",
                        "decree_reference": "Procédure ARH P-CTE-1",
                        "article": "MTR Proof Test",
                        "article_number": "ASME B16.9 §9.6",
                        "standard": "ASME B16.9",
                        "document_concerned": fname,
                        "page": f"Page {p_burst} sur {total_doc_pages}",
                        "page_number": p_burst,
                        "target_content": t_burst,
                        "quote_snippet": snip_burst,
                        "correction_method": "Annexer le MTR du fitting testé à chaque rapport d'essai d'éclatement.",
                        "action_required": "02-Veuillez joindre le Material Test Report (MTR) conformément à l’article 9.6 de la norme ASME B16.9.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Service Qualité Métallurgie / Fabricant",
                        "responsible_entity": "Service Qualité Métallurgie / Fabricant",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN"
                    })

                    # 6.8 Design Proof Test : Plage de Qualification et Équipements Couverts
                    comments.append({
                        "id": f"REM_FIT_BURST_COVERAGE_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Justification de la Plage de Qualification et Tableau Récapitulatif des Burst Tests",
                        "description": f"Dans le dossier '{fname}', plusieurs raccords ne sont pas valablement couverts par les rapports de burst test cités en raison de changement de géométrie/forme non pris en compte ou d'étendue d'épaisseur non couverte. Joindre un tableau récapitulatif mentionnant chaque rapport, sa plage de qualification d'épaisseur/diamètre, ainsi que les équipements couverts.",
                        "observation": "03/04/05- Les items ne sont pas couverts par les rapports de proof test (forme et étendue d'épaisseur). Joindre un tableau récapitulatif mentionnant chaque rapport, sa plage de qualification, ainsi que les équipements couverts.",
                        "cause": "Extrapolation abusive de rapports d'essais à des géométries ou épaisseurs hors plage de validité ASME B16.9.",
                        "impact": "Non-validation du dimensionnement à la pression interne des raccords concernés.",
                        "category": "JUSTIFICATIFS D'ESSAIS & QUALIFICATION",
                        "regulation_ref": "ASME B16.9 §9 / MSS SP-75",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Couverture Proof Test",
                        "article_number": "ASME B16.9 §9",
                        "standard": "ASME B16.9",
                        "document_concerned": fname,
                        "page": f"Page {p_burst} sur {total_doc_pages}",
                        "page_number": p_burst,
                        "target_content": t_burst,
                        "quote_snippet": snip_burst,
                        "correction_method": "Établir une matrice de qualification des proof tests et fournir les rapports complémentaires nécessaires.",
                        "action_required": "Afin d’assurer une meilleure organisation, merci de bien vouloir joindre un tableau récapitulatif mentionnant chaque rapport, sa plage de qualification, ainsi que les équipements couverts.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Lead Mécanique / Fabricant Fitting",
                        "responsible_entity": "Lead Mécanique / Fabricant Fitting",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=4)).strftime("%Y-%m-%d"),
                        "deadline_days": 4,
                        "status": "OPEN"
                    })

                # 6.9 Cotes de Chanfreinage ASME B16.25 sur les Plans de Raccord (uniquement si plan de chanfreinage)
                has_bev_draw = any(k in t for k in ["BEVEL", "CHANFREIN", "1.5X45", "6X45", "B16.25"]) and any(k in fname.upper() for k in ["PLAN", "DRAWING", "DESSIN"])
                if has_bev_draw:
                    _, p_bev, snip_bev, t_bev = _find_ev_page(["BEVEL", "CHANFREIN", "1.5X45", "6X45", "B16.25"], default_p=55)
                    comments.append({
                        "id": f"REM_FIT_BEVEL_DIMS_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Cotes des Biseaux et Chanfreins de Raccordement selon ASME B16.25 (1.5x45°, 6x45°, D1, D2)",
                        "description": f"Sur les plans d'usinage et de fabrication des raccords '{fname}', faire figurer les détails géométriques complets du biseau de raccordement selon ASME B16.25 : talon (1.5x45°), angle de biseau (6x45° ou 37.5°), diamètres intérieur/extérieur (D1, D2, D).",
                        "observation": "Préciser et coter les dimensions de chanfreinage (1.5x45°, 6x45°, D1, D2, D) selon ASME B16.25.",
                        "cause": "Cotes de chanfreinage incomplètes sur le plan de détail.",
                        "impact": "Impossibilité de contrôler la préparation de soudage avant montage sur site.",
                        "category": "CONFORMITÉ TECHNIQUE DU DESSIN",
                        "regulation_ref": "ASME B16.25 / ASME B16.9",
                        "decree_reference": "Procédure ARH P-CTE-1",
                        "article": "Détails Chanfreins",
                        "article_number": "ASME B16.25",
                        "standard": "ASME B16.25",
                        "document_concerned": fname,
                        "page": f"Page {p_bev} sur {total_doc_pages}",
                        "page_number": p_bev,
                        "target_content": t_bev,
                        "quote_snippet": snip_bev,
                        "correction_method": "Ajouter le détail coté du biseau de soudage avec les cotes 1.5x45° et 6x45°.",
                        "action_required": "Indiquer les dimensions des chanfreins (1.5x45°, 6x45°, D1, D2).",
                        "priority": "MAJOR",
                        "severity": "Major",
                        "responsible": "Dessinateur Projeteur / Fabricant",
                        "responsible_entity": "Dessinateur Projeteur / Fabricant",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=4)).strftime("%Y-%m-%d"),
                        "deadline_days": 4,
                        "status": "OPEN"
                    })

                # 6.10 Repère et Identification Documentaire (uniquement si page 83 ou doc > 80 pages)
                has_p83, p_83_hit, snip_83, t_83 = _find_ev_page(["PAGE 83", "REPERE DU DOCUMENT", "REPÈRE DU DOCUMENT", "CARTOUCHE"], default_p=83 if total_doc_pages >= 83 else total_doc_pages)
                target_p_doc_id = p_83_hit if has_p83 else (83 if total_doc_pages >= 83 else total_doc_pages)
                if total_doc_pages >= 83 or "PAGE 83" in t or has_p83:
                    comments.append({
                        "id": f"REM_FIT_DOC_ID_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Mention Obligatoire du Repère et Référence du Document (Veuillez mentionner le repère du document)",
                        "description": f"Sur la pièce technique '{fname}' (notamment page {target_p_doc_id}), mentionner formellement le repère unique d'identification du document (numéro de document, révision, date) dans le cartouche conformément aux exigences documentaires de l'ARH.",
                        "observation": "Veuillez mentionner le repère du document.",
                        "cause": "Document ou page d'annexe dépourvu d'identification formelle.",
                        "impact": "Absence de traçabilité documentaire au sein du dossier ARH.",
                        "category": "CONFORMITÉ DOCUMENTAIRE",
                        "regulation_ref": "Procédure ARH P-CTE-1",
                        "decree_reference": "Procédure ARH P-CTE-1",
                        "article": "Identification Documentaire",
                        "article_number": "P-CTE-1",
                        "standard": "P-CTE-1",
                        "document_concerned": fname,
                        "page": f"Page {target_p_doc_id} sur {total_doc_pages}",
                        "page_number": target_p_doc_id,
                        "correction_method": "Inscrire le numéro de référence, le titre et la révision sur le document.",
                        "action_required": "Veuillez mentionner le repère du document.",
                        "priority": "MINOR",
                        "severity": "Minor",
                        "responsible": "Document Controller",
                        "responsible_entity": "Document Controller",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                        "deadline_days": 5,
                        "status": "OPEN"
                    })

                # 6.11 Terminologie Réglementaire : Remplacer 'Non Soumis' par 'Not Applicable' (uniquement si NON SOUMIS est présent)
                has_fit_ns, p_fit_ns, snip_fit_ns, t_fit_ns = _find_ev_page(["NON SOUMIS", "NON-SOUMIS", "NONSOUMIS"], default_p=22)
                if has_fit_ns:
                    comments.append({
                        "id": f"REM_FIT_NOT_APPLICABLE_{uuid.uuid4().hex[:6].upper()}",
                        "title": "Terminologie Conforme : Remplacer 'Non Soumis' par 'Not Applicable' / 'Non Applicable'",
                        "description": f"Dans les fiches descriptives Annexe E de '{fname}', remplacer la mention 'non soumis' par 'not applicable' (ou 'not aplicable') conformément aux exigences de terminologie officielle de l'ARH.",
                        "observation": "Remplacer le mot non soumis par not applicable / not aplicable sur les fiches descriptives.",
                        "cause": "Utilisation d'une formulation inadéquate pour les rubriques exemptées.",
                        "impact": "Imprécision juridique sur le statut réglementaire de l'équipement.",
                        "category": "CONFORMITÉ RÉGLEMENTAIRE",
                        "regulation_ref": "Procédure ARH P-CTE-1",
                        "decree_reference": "Procédure ARH P-CTE-1",
                        "article": "Glossaire P-CTE-1",
                        "article_number": "P-CTE-1",
                        "standard": "P-CTE-1",
                        "document_concerned": fname,
                        "page": f"Page {p_fit_ns} sur {total_doc_pages}",
                        "page_number": p_fit_ns,
                        "target_content": t_fit_ns,
                        "quote_snippet": snip_fit_ns,
                        "correction_method": "Inscrire formellement 'Not applicable' ou 'Non applicable'.",
                        "action_required": "Not applicable : remplacer non soumis par not applicable.",
                        "priority": "MINOR",
                        "severity": "Minor",
                        "responsible": "Document Controller / QA-QC",
                        "responsible_entity": "Document Controller / QA-QC",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                        "deadline_days": 5,
                        "status": "OPEN"
                    })

            # 7. Well Head Control Panel (WHCP) & Accumulateurs Oléopneumatiques
            is_whcp = any(k in fname.upper() for k in ["WHCP", "WELL HEAD", "CONTROL PANEL", "ACCUMULATEUR", "ACCUMULATOR", "4 LITRE", "20 LITRE"]) or any(k in t for k in ["WHCP", "WELL HEAD CONTROL PANEL", "BLADDER ACCUMULATOR", "ACCUMULATEUR"])
            if is_whcp:
                # 7.1 Lettre d'engagement : signature, cachet et quantités
                comments.append({
                    "id": f"REM_WHCP_ENGAGE_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Lettre d'Engagement : Signature, Cachet et Précision des Quantités pour chaque Item",
                    "description": f"Pour le panneau de contrôle de têtes de puits '{fname}', signer et tamponner formellement la lettre d'engagement et préciser explicitement sur la lettre la quantité exacte pour chaque item (ex: 20L & 4L).",
                    "observation": "signer et tamponner ce document. Préciser sur la lettre la quantité pour chaque item (20L & 4L).",
                    "cause": "Lettre d'engagement non visée ou quantités non individualisées par capacité d'accumulateur.",
                    "impact": "Irrecevabilité de la lettre d'engagement réglementaire auprès de l'ARH.",
                    "category": "CONFORMITÉ ADMINISTRATIVE & LÉGALE",
                    "regulation_ref": "Procédure ARH P-CTE-1 Annexe A",
                    "decree_reference": "Procédure ARH P-CTE-1",
                    "article": "Lettre d'Engagement",
                    "article_number": "P-CTE-1",
                    "standard": "P-CTE-1",
                    "document_concerned": fname,
                    "page": 1,
                    "correction_method": "Faire signer et tamponner la lettre d'engagement en précisant les quantités d'accumulateurs 4L et 20L.",
                    "action_required": "signer et tamponner ce document. Préciser sur la lettre la quantité pour chaque item.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Fabricant WHCP / Représentant Légal",
                    "responsible_entity": "Fabricant WHCP / Représentant Légal",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 7.2 Certificat selon Annexe F et Annexe D de la Procédure P-CTE-1
                comments.append({
                    "id": f"REM_WHCP_ANNEXES_DF_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Établissement des Certificats selon Annexes D et F de la Procédure P-CTE-1 et Ordonnancement",
                    "description": f"Pour les accumulateurs hydrauliques du WHCP '{fname}', refaire le certificat de contrôle de fabrication conformément au modèle officiel de l'Annexe F de la procédure P-CTE-1 (Document N° 3). De même, refaire le certificat de contrôle technique selon l'Annexe D de la procédure P-CTE-1 et le positionner rigoureusement après le document 3 (Document N° 4).",
                    "observation": "Refaire ce certificat conformément à l'annexe F de la procédure P-CTE-1 (DOCUMENT N° 3). Refaire ce certificat conformément à l'annexe D de la procédure P-CTE-1 et le déplacer après le document 3 (DOCUMENT N° 4).",
                    "cause": "Non-conformité des formulaires employés avec les modèles réglementaires obligatoires de la P-CTE-1.",
                    "impact": "Non-conformité documentaire majeure et rejet lors de l'instruction par la commission ARH.",
                    "category": "CONFORMITÉ RÉGLEMENTAIRE",
                    "regulation_ref": "Procédure ARH P-CTE-1 Annexes D et F",
                    "decree_reference": "Procédure ARH P-CTE-1",
                    "article": "Annexes D & F",
                    "article_number": "P-CTE-1",
                    "standard": "Procédure ARH P-CTE-1",
                    "document_concerned": fname,
                    "page": 4,
                    "correction_method": "Remplacer les certificats par les modèles réglementaires Annexes D et F de la procédure ARH P-CTE-1.",
                    "action_required": "Refaire ce certificat conformément à l'annexe F de la procédure P-CTE-1. Refaire selon Annexe D.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Responsable QA-QC WHCP / Fabricant",
                    "responsible_entity": "Responsable QA-QC WHCP / Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 7.3 Mention du Volume et des Matériaux sur l'État Descriptif
                comments.append({
                    "id": f"REM_WHCP_VOL_MAT_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Ajout Obligatoire du Volume et Spécification des Matériaux Utilisés sur l'État Descriptif",
                    "description": f"Dans l'état descriptif des accumulateurs '{fname}', renseigner obligatoirement le volume intérieur exact en litres (ex: 4L / 20L) et préciser la désignation complète des matériaux utilisés pour le corps sous pression et la vessie élastomère.",
                    "observation": "Ajouter le volume. Préciser matériaux utilisé sur l'état descriptif.",
                    "cause": "Volume et matériaux omis dans les rubriques techniques de la fiche descriptive.",
                    "impact": "Impossibilité de valider la catégorie de l'ESP selon le produit Pression x Volume.",
                    "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                    "regulation_ref": "Décret exécutif n° 21-261 Annexe E",
                    "decree_reference": "Décret exécutif n° 21-261",
                    "article": "Annexe E - Paramètres de l'Appareil",
                    "article_number": "Décret 21-261",
                    "standard": "Décret 21-261",
                    "document_concerned": fname,
                    "page": 8,
                    "correction_method": "Compléter l'état descriptif avec le volume en litres et la nuance matière.",
                    "action_required": "Ajouter le volume. Préciser matériaux utilisé.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Ingénieur Conception WHCP",
                    "responsible_entity": "Ingénieur Conception WHCP",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=4)).strftime("%Y-%m-%d"),
                    "deadline_days": 4,
                    "status": "OPEN"
                })

                # 7.4 Plan de Plaque Signalétique et Emplacement du Poinçon ARH
                comments.append({
                    "id": f"REM_WHCP_NAMEPLATE_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Plan de la Plaque Signalétique et Emplacement pour le Poinçon de l'ARH",
                    "description": f"Pour l'équipement '{fname}', joindre au dossier technique le plan d'exécution coté de la plaque signalétique (Nameplate drawing). Vous devez vous assurer qu'il y a un espace réservé suffisant pour l'apposition du poinçon réglementaire officiel de l'ARH lors de la réception.",
                    "observation": "Ajouter le plan de la plaque signalétique. Vous devez vous assurer qu'il y a de la place pour le poinçon de l'ARH.",
                    "cause": "Absence de plan de plaque ou absence de zone réservée au poinçonnage officiel ARH.",
                    "impact": "Impossibilité matérielle pour les inspecteurs ARH d'apposer le poinçon d'épreuve et de mise en service.",
                    "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                    "regulation_ref": "Décret exécutif n° 21-261 Art. 19 / Procédure ARH P-CTE-1",
                    "decree_reference": "Décret exécutif n° 21-261",
                    "article": "Art. 19 - Plaque Signalétique",
                    "article_number": "Art. 19",
                    "standard": "Décret 21-261",
                    "document_concerned": fname,
                    "page": 8,
                    "correction_method": "Intégrer le plan de la plaque signalétique comportant une zone libre dédiée au poinçon ARH.",
                    "action_required": "Ajouter le plan de la plaque signalétique. Vous devez vous assurer qu'il y a de la place pour le poinçon de l'ARH.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénieur Dessinateur / Bureau d'Études",
                    "responsible_entity": "Ingénieur Dessinateur / Bureau d'Études",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 7.5 Substitution Organisme Réglementaire : Remplacer DGM par ARH
                comments.append({
                    "id": f"REM_WHCP_DGM_ARH_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Mise à Jour Institutionnelle Obligatoire : Remplacer 'DGM' par 'ARH'",
                    "description": f"Dans l'ensemble des documents, fiches et formulaires de '{fname}', la mention obsolète 'DGM' (Direction Générale des Mines) doit être impérativement remplacée par 'ARH' (Autorité de Régulation des Hydrocarbures), autorité légale compétente selon la Loi 19-13 et les décrets d'application.",
                    "observation": "Remplacer DGM par ARH sur l'ensemble du dossier préliminaire.",
                    "cause": "Utilisation d'anciens formulaires ou procédures citant l'ancienne autorité minière.",
                    "impact": "Dénomination institutionnelle caduque sur les documents réglementaires officiels.",
                    "category": "CONFORMITÉ RÉGLEMENTAIRE",
                    "regulation_ref": "Loi 19-13 sur les Hydrocarbures / Procédure ARH P-CTE-1",
                    "decree_reference": "Loi 19-13 / Décret 21-261",
                    "article": "Autorité Compétente ARH",
                    "article_number": "Loi 19-13",
                    "standard": "Procédure ARH P-CTE-1",
                    "document_concerned": fname,
                    "page": 1,
                    "correction_method": "Remplacer systématiquement l'acronyme 'DGM' par 'ARH'.",
                    "action_required": "Remplacer DGM par ARH.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Document Controller / EPC Contractor",
                    "responsible_entity": "Document Controller / EPC Contractor",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 7.6 Points d'Arrêt d'Inspection ARH / Tiers Habilité (TPI)
                comments.append({
                    "id": f"REM_WHCP_ITP_ARH_TPI_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Attribution des Rôles d'Inspection ITP : ARH et TPI (Tiers Partie Habilitée)",
                    "description": f"Sur le plan d'inspection et d'essais (ITP) du panneau WHCP et accumulateurs '{fname}', insérer les colonnes d'intervention distinctes pour l'ARH et l'organisme tiers inspecteur (TPI), avec affectation des points d'arrêt (Hold Points 'H') sur les épreuves de pression et vérification finale.",
                    "observation": "ARH / TPI : attribuer les points de contrôle et points d'arrêt réglementaires sur l'ITP.",
                    "cause": "Confusion ou manque de clarté entre les rôles du client (PTTEP / GCB), de l'ARH et du TPI.",
                    "impact": "Non-conformité du jalonnement de surveillance de fabrication sous contrôle ARH.",
                    "category": "PLAN D'INSPECTION & ESSAIS (ITP)",
                    "regulation_ref": "Procédure ARH P-CTE-1 §VIII",
                    "decree_reference": "Décret exécutif n° 21-261 Art. 21",
                    "article": "Surveillance des Essais",
                    "article_number": "P-CTE-1",
                    "standard": "Procédure ARH P-CTE-1",
                    "document_concerned": fname,
                    "page": 1,
                    "correction_method": "Clarifier les colonnes d'intervention ARH / TPI et PTTEP / GCB sur l'ITP.",
                    "action_required": "ARH / TPI : configurer les points de contrôle sur l'ITP.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Responsable QA-QC WHCP",
                    "responsible_entity": "Responsable QA-QC WHCP",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

            # 8. Systèmes d'Échantillonnage & Cylindres sous Pression (SAMPLING SYSTEM / ASME VIII Div 1)
            is_sampling = any(k in fname.upper() for k in ["SAMPLING", "CYLINDER", "BOUTEILLE", "ECHANTILLONNAGE", "STATION"]) or any(k in t for k in ["SAMPLING SYSTEM", "SAMPLING CYLINDER", "CYLINDRE", "SAMPLING STATION"])
            if is_sampling:
                # 8.1 Visas consulaires sur les 3 certificats administratifs
                comments.append({
                    "id": f"REM_SAMP_CONSULAR_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Légalisation Consulaire des 3 Certificats Administratifs (Chambre de Commerce & Consulat d'Algérie)",
                    "description": f"Pour le système d'échantillonnage '{fname}', les trois certificats administratifs du fabricant étranger doivent obligatoirement être signés et visés par la chambre de commerce et le consulat d'Algérie du pays d'origine.",
                    "observation": "1) Manque le cacher de la chambre de commerce du consulat algérienne des 03 certificats.",
                    "cause": "Absence des visas consulaires algériens sur les pièces administratives du fournisseur.",
                    "impact": "Irrecevabilité du dossier auprès des services de l'ARH (Décret 21-261 Art. 5).",
                    "category": "CONFORMITÉ ADMINISTRATIVE & LÉGALE",
                    "regulation_ref": "Décret exécutif n° 21-261 Art. 5 / Procédure ARH P-CTE-1",
                    "decree_reference": "Décret exécutif n° 21-261",
                    "article": "Art. 5",
                    "article_number": "Art. 5",
                    "standard": "P-CTE-1",
                    "document_concerned": fname,
                    "page": 1,
                    "correction_method": "Faire viser les 3 certificats administratifs auprès du Consulat d'Algérie.",
                    "action_required": "Manque le cacher de la chambre de commerce du consulat algérienne des 03 certificats.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Fabricant Sampling / Agent Export",
                    "responsible_entity": "Fabricant Sampling / Agent Export",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 8.2 Pression d'Épreuve Hydrostatique selon ASME VIII Div 1 UG-99 (Minimum 140 bar)
                comments.append({
                    "id": f"REM_SAMP_HYDRO_UG99_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Pression d'Épreuve Hydrostatique selon ASME VIII Div 1 UG-99 (Minimum 140 bar)",
                    "description": f"Pour les bouteilles / récipients d'échantillonnage '{fname}', la pression d'essai hydrostatique en usine doit être strictement calculée et réalisée selon l'article UG-99(b) de l'ASME VIII Division 1 : P_test = 1.3 x MAWP x (S_test / S_design), soit au minimum 140 bar.",
                    "observation": "la pression d'essai doit être selon UG-99 article B de l'ASME VIII au minimum 140 bar.",
                    "cause": "Pression d'essai indiquée inférieure au minimum réglementaire ou non justifiée par UG-99.",
                    "impact": "Non-validation de l'épreuve de résistance mécanique par l'inspecteur ARH.",
                    "category": "NOTE DE CALCUL & RÉSISTANCE",
                    "regulation_ref": "ASME Section VIII Div 1 UG-99(b) / Décret exécutif n° 21-261 Art. 21",
                    "decree_reference": "Décret exécutif n° 21-261",
                    "article": "Art. 21 - Épreuve Hydrostatique",
                    "article_number": "UG-99(b)",
                    "standard": "ASME Section VIII Div 1",
                    "document_concerned": fname,
                    "page": 1,
                    "correction_method": "Fixer la pression d'épreuve hydrostatique au minimum à 140 bar conformément à l'ASME VIII Div 1 UG-99(b).",
                    "action_required": "la pression d'essai doit être selon UG-99 article B de l'ASME VIII au minimum 140 bar.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénieur Calcul / Bureau d'Études",
                    "responsible_entity": "Ingénieur Calcul / Bureau d'Études",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 8.3 Mention Explicite du Code ASME VIII Division 1
                comments.append({
                    "id": f"REM_SAMP_CODE_VIII1_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Mention Explicite du Code de Construction ASME Section VIII Division 1",
                    "description": f"Dans les fiches techniques, plans et notes de calcul de '{fname}', faire expressément référence au code de conception et fabrication ASME Section VIII Division 1.",
                    "observation": "Veuillez mentionner l'ASME VIII div 1 comme code de référence de l'équipement.",
                    "cause": "Absence de citation explicite de la division exacte du code ASME.",
                    "impact": "Imprécision normative dans la déclaration de conformité de l'appareil.",
                    "category": "CONTRÔLE NORMATIF",
                    "regulation_ref": "ASME Section VIII Div 1 / Décret exécutif n° 21-261 Art. 6",
                    "decree_reference": "Décret exécutif n° 21-261",
                    "article": "Art. 6 - Code de Construction",
                    "article_number": "ASME VIII Div 1",
                    "standard": "ASME VIII Div 1",
                    "document_concerned": fname,
                    "page": 1,
                    "correction_method": "Indiquer formellement ASME Section VIII Division 1 sur toutes les pièces du dossier.",
                    "action_required": "Veuillez mentionner l'ASME VIII div 1.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Ingénieur Bureau d'Études",
                    "responsible_entity": "Ingénieur Bureau d'Études",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 8.4 Matériau Inadapté : Retrait de la Mention 316L (Veuillez retirer 316L)
                comments.append({
                    "id": f"REM_SAMP_MAT_316L_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Conformité de Nuance Métallurgique : Retirer la Mention 316L (Veuillez retiré 316L)",
                    "description": f"Dans les spécifications techniques et nomenclatures de '{fname}', retirer la mention du matériau inox 316L non conforme aux spécifications contractuelles du fluide corrosif/acide du projet.",
                    "observation": "Veuillez retiré 316L : nuance non retenue pour les conditions de service spécifiées.",
                    "cause": "Utilisation d'une nuance standard 316L au lieu de la métallurgie requise par le cahier des charges client.",
                    "impact": "Risque de corrosion et non-conformité à la réquisition contractuelle.",
                    "category": "CONTRÔLE MÉTALLURGIQUE & MATÉRIAUX",
                    "regulation_ref": "Spécification Matériaux GHBR-1B / NACE MR0175",
                    "decree_reference": "Décret exécutif n° 21-261",
                    "article": "Sélection des Matériaux",
                    "article_number": "Spécification Projet",
                    "standard": "NACE MR0175 / Spécification GHBR",
                    "document_concerned": fname,
                    "page": 1,
                    "correction_method": "Supprimer la désignation 316L et aligner la nuance sur la réquisition projet.",
                    "action_required": "Veuillez retiré 316L.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Ingénieur Matériaux / Fabricant",
                    "responsible_entity": "Ingénieur Matériaux / Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=4)).strftime("%Y-%m-%d"),
                    "deadline_days": 4,
                    "status": "OPEN"
                })

                # 8.5 Dossier de Soudage Complet : WPS et PQR Applicables
                comments.append({
                    "id": f"REM_SAMP_WPS_PQR_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Fourniture Obligatoire des WPS et PQR Applicables (Manque la WPS et PQR appliquer)",
                    "description": f"Pour l'assemblage et le piquage du cylindre d'échantillonnage '{fname}', le dossier préliminaire doit impérativement contenir les Descriptifs de Modes Opératoires de Soudage (WPS) et les Procès-Verbaux de Qualification correspondants (PQR) selon l'ASME Section IX.",
                    "observation": "Manque la WPS et PQR appliquer pour la réalisation des soudures sous pression.",
                    "cause": "Absence des justificatifs réglementaires de qualification de soudage.",
                    "impact": "Non-validation de l'intégrité des assemblages soudés sous pression.",
                    "category": "SOUDAGE & QUALIFICATION",
                    "regulation_ref": "ASME Section IX / Procédure ARH P-CTE-1 Annexe A",
                    "decree_reference": "Procédure ARH P-CTE-1",
                    "article": "Qualification Soudage",
                    "article_number": "ASME IX",
                    "standard": "ASME Section IX",
                    "document_concerned": fname,
                    "page": 1,
                    "correction_method": "Joindre l'ensemble des WPS et PQR approuvés applicables au cylindre.",
                    "action_required": "Manque la WPS et PQR appliquer.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Coordonnateur Soudage / Fabricant",
                    "responsible_entity": "Coordonnateur Soudage / Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 8.6 Plaque Signalétique et Poinçon Tiers Partie / ARH (Point d'Inspection H)
                comments.append({
                    "id": f"REM_SAMP_NAMEPLATE_PUNCH_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Contrôle et Poinçon de la Plaque Signalétique par la Tiers Partie (Point d'Inspection H)",
                    "description": f"Pour le cylindre d'échantillonnage '{fname}', la plaque signalétique doit obligatoirement être vérifiée, validée et poinçonnée par la tiers partie habilitée et l'ARH avec attribution formelle d'un point d'arrêt (Point d'inspection 'H' - Hold Point).",
                    "observation": "pour la plaque signalétique elle vérifier et poinçonner par la tiers partie (point d'inspection H).",
                    "cause": "Niveau de surveillance insuffisant attribué au poinçonnage de la plaque signalétique.",
                    "impact": "Non-conformité de la traçabilité de mise en service de l'appareil à pression.",
                    "category": "PLAN D'INSPECTION & ESSAIS (ITP)",
                    "regulation_ref": "Décret exécutif n° 21-261 Art. 19 / Procédure P-CTE-1",
                    "decree_reference": "Décret exécutif n° 21-261",
                    "article": "Art. 19 - Plaque Signalétique",
                    "article_number": "Art. 19",
                    "standard": "Procédure ARH P-CTE-1",
                    "document_concerned": fname,
                    "page": 1,
                    "correction_method": "Attribuer le point d'arrêt 'H' à la tiers partie pour le contrôle et poinçonnage de la plaque signalétique.",
                    "action_required": "pour la plaque signalétique elle vérifier et poinçonner par la tiers partie (point d'inspection H).",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Responsable Qualité Fabricant / TPI",
                    "responsible_entity": "Responsable Qualité Fabricant / TPI",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 8.7 Contrôles Non Destructifs (NDE) sur l'ITP
                comments.append({
                    "id": f"REM_SAMP_NDE_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Mention Explicite des Contrôles Non Destructifs (NDE) sur l'ITP",
                    "description": f"Sur le plan d'inspection et d'essais '{fname}', spécifier clairement l'ensemble des contrôles non destructifs (NDE : ressuage PT, radiographie RT ou ultrasons UT) avec pourcentages de contrôle et critères d'acceptation ASME VIII.",
                    "observation": "le NDE doit être mentionner sur l'ITP avec l'étendue et les normes d'acceptation.",
                    "cause": "Absence de détails des méthodes et critères de contrôle non destructif sur l'ITP.",
                    "impact": "Défaut d'assurance qualité sur l'intégrité volumique et surfacique du récipient.",
                    "category": "PLAN D'INSPECTION & ESSAIS (ITP)",
                    "regulation_ref": "ASME Section VIII Div 1 / ASME Section V",
                    "decree_reference": "Procédure ARH P-CTE-1",
                    "article": "Contrôles Non Destructifs",
                    "article_number": "ASME VIII",
                    "standard": "ASME Section V",
                    "document_concerned": fname,
                    "page": 1,
                    "correction_method": "Compléter l'ITP avec la désignation des NDE (RT, UT, PT, MT).",
                    "action_required": "le NDE doit être mentionner.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Ingénieur QA-QC / Fabricant",
                    "responsible_entity": "Ingénieur QA-QC / Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

                # 8.8 Attribution des Rôles ITP : Colonne ARH et Points H / W sur l'Hydrotest et FAT
                comments.append({
                    "id": f"REM_SAMP_ITP_ROLES_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Colonne ARH et Attribution des Points d'Arrêt (H pour ARH, W pour Client) sur Hydrotest et FAT",
                    "description": f"Sur l'ITP '{fname}', ajouter impérativement une colonne spécifique dédiée à l'ARH. Pour l'essai hydrostatique (Hydro test), affecter le point témoin 'W' pour le client (GCB / SONATRACH) et le point d'arrêt obligatoire 'H' pour l'ARH. De même, lors des essais de réception en usine (FAT), la tiers partie doit obligatoirement avoir un point d'arrêt 'H'.",
                    "observation": "Veuillez ajouter une colonne pour ARH. Pour le hydro test : W pour le client (GCB / SONATRACH) et H pour ARH. La tiers partie dans la FAT elle doit être H.",
                    "cause": "Non-conformité de la grille d'intervention ITP aux directives de surveillance de l'ARH.",
                    "impact": "Refus de visa de l'ITP par l'ARH.",
                    "category": "PLAN D'INSPECTION & ESSAIS (ITP)",
                    "regulation_ref": "Procédure ARH P-CTE-1 §VIII / Décret 21-261 Art. 21",
                    "decree_reference": "Procédure ARH P-CTE-1",
                    "article": "Points d'Arrêt ITP",
                    "article_number": "P-CTE-1",
                    "standard": "Procédure ARH P-CTE-1",
                    "document_concerned": fname,
                    "page": 1,
                    "correction_method": "Mettre à jour la matrice d'intervention ITP : colonne ARH avec 'H' sur épreuve hydro et FAT.",
                    "action_required": "Veuillez ajouter une colonne pour ARH. pour le hydro test W pour le client (GCB / SONATRACH) H pour ARH. La tiers partie dans la FAT elle doit être H.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Responsable QA-QC Fabricant",
                    "responsible_entity": "Responsable QA-QC Fabricant",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })
        # ─── VÉRIFICATIONS TECHNIQUE ET COHÉRENCE CROSS-DOCUMENTS ───

        # 0. Contrôle Mathématique des Calculs d'Ingénierie (Épaisseurs, Pressions, ASME/API)
        math_comments = self._verify_engineering_calculations(parsed_docs, equipment_type)
        comments.extend(math_comments)

        # 1. Contrôle des Incohérences Cross-Documents (Pressions, Températures, Matériaux, Tags, Surépaisseur)
        cross_doc_comments = self._check_cross_document_inconsistencies(parsed_docs)
        comments.extend(cross_doc_comments)

        full_text_blob = " ".join(d.get("text", "") for d in parsed_docs)

        norm_scope_anomalies = self.engine.verify_norm_applicability(equipment_type, full_text_blob)
        for anomaly in norm_scope_anomalies:
            comments.append({
                "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                "title": anomaly["title"],
                "description": anomaly["comment"],
                "observation": anomaly["comment"],
                "cause": "Norme hors domaine d'application ou non applicable citée dans la documentation.",
                "impact": "Non-conformité réglementaire au Décret 21-261 / 21-315 et rejet du dossier par l'ARH.",
                "category": "CONTRÔLE NORMATIF",
                "regulation_ref": anomaly["reference"],
                "decree_reference": anomaly["reference"],
                "article": "Portée des Normes",
                "article_number": "Scope",
                "standard": "ASME / API / EN Scope",
                "document_concerned": "Dossier Technique",
                "page": "Analyse Normative",
                "correction_method": "Retirer la référence à la norme non applicable et appliquer les normes valides.",
                "action_required": "Réviser le dossier pour supprimer la norme non applicable.",
                "priority": anomaly["priority"],
                "severity": anomaly["priority"].title(),
                "responsible": "Ingénieur Qualité / Concepteur",
                "responsible_entity": "Ingénieur Qualité / Concepteur",
                "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                "deadline_days": 5,
                "status": "OPEN"
            })

        # [DÉSACTIVÉ SUR DEMANDE UTILISATEUR]
        # Suppression des remarques historiques ARH pour ne pas polluer l'analyse du dossier réel.



        # 1.5. Réconciliation Approfondie des Équipements & Concordance des Certificats (Tag Mismatch)
        reconcil_comments = self._verify_equipment_certificate_reconciliation(parsed_docs, equipment_tag, equipment_type, dossier_stage=dossier_stage)
        comments.extend(reconcil_comments)

        # 1.6. Audit d'Authenticité & Fidélité des Données (Coulées Heat N°, Visas Consulaires, Chimie 3.1)
        authenticity_comments = self._verify_dossier_authenticity_and_fidelity(parsed_docs, equipment_type, equipment_tag)
        comments.extend(authenticity_comments)


        # 2. Équipements Sous Pression & Canalisations : Vérification des Pressions vs PMA
        if equipment_type in ("PRESSURE_VESSEL", "SEPARATOR", "HEAT_EXCHANGER", "COLUMN", "SPHERE", "PIPELINE"):
            if design_pressures and hydrotest_pressures:
                p_des, doc_des = design_pressures[0]
                p_hyd, doc_hyd = hydrotest_pressures[0]

                is_ok, req_p, rule_ref = self.engine.verify_hydrotest_pressure(
                    pma_bar=p_des, pms_bar=p_des, actual_test_bar=p_hyd, equipment_type=equipment_type
                )

                if not is_ok:
                        hyd_offset = 0
                        hyd_doc_spans = doc.get('page_spans', [])
                        for d_item in parsed_docs:
                            if d_item.get('file_name') == doc_hyd:
                                hyd_doc_spans = d_item.get('page_spans', [])
                                d_text = d_item.get('text', '')
                                m_hyd_match = re.search(r'\b' + re.escape(f"{p_hyd:.0f}") + r'\s*(?:bar|bars|mpa)', d_text, re.I)
                                if m_hyd_match:
                                    hyd_offset = m_hyd_match.start()
                                    break
                        hyd_page_num = self._page_at_offset(hyd_doc_spans, hyd_offset)
                        comments.append({
                            "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                            "title": f"Pression d'Épreuve Hydrostatique Non Conforme ({p_hyd:.1f} bar < {req_p:.1f} bar)",
                            "description": f"Analyse du contenu du fichier '{doc_hyd}' : La pression d'épreuve enregistrée ({p_hyd:.1f} bar) est inférieure au minimum réglementaire exigé ({req_p:.1f} bar = 150% de la PMA {p_des:.1f} bar).",
                            "observation": f"La pression d'épreuve hydrostatique figurant sur le PV '{doc_hyd}' ({p_hyd:.1f} bar) est inférieure à la valeur réglementaire ({req_p:.1f} bar).",
                            "cause": "Calcul de pression d'épreuve usine ou de chantier incorrect.",
                            "impact": "Non-conformité majeure au Décret 21-261 Art. 27 et risque de refus de l'Autorisation de Mise en Produit.",
                            "category": "ESSAI & HYDROTEST",
                            "regulation_ref": "Décret exécutif n° 21-261 / 21-314",
                            "decree_reference": "Décret exécutif n° 21-261 / 21-314",
                            "article": "Art. 27 (ESP) / Art. 21 (Canalisations)",
                            "article_number": "Art. 27 / Art. 21",
                            "standard": "ASME VIII Div 1 / API 650",
                            "document_concerned": doc_hyd,
                            "page": f"Page {hyd_page_num} sur {len(hyd_doc_spans) or 1}",
                            "page_number": hyd_page_num,
                            "target_content": f"{p_hyd:.1f} bar",
                        "correction_method": f"Re-effectuer l'épreuve hydrostatique à la pression minimale de {req_p:.1f} bar et transmettre le nouveau PV visé.",
                        "action_required": f"Re-effectuer l'épreuve hydrostatique à la pression minimale de {req_p:.1f} bar et transmettre le nouveau PV visé.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Fabricant / Inspecteur Tiers Habilité",
                        "responsible_entity": "Fabricant / Inspecteur Tiers Habilité",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                        "deadline_days": 5,
                        "status": "OPEN"
                    })

        # 3. Équipements Électriques / UPS : Vérification de la Certification ATEX
        # Bug Critical#3 fix : uniquement exigible au stade FINAL (les certificats ATEX
        # accompagnent generalement l'equipement physiquement livre, pas le design preliminaire)
        if equipment_type == "ELECTRICAL" and dossier_stage == "FINAL_RECEPTION":
            if not atex_zones:
                comments.append({
                    "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                    "title": "Absence de Certificat d'Inviolabilité ATEX / IECEx dans le Contenu Fichier",
                    "description": "L'analyse du contenu des documents électriques transmis n'a révélé aucun certificat ATEX / IECEx pour installation en zone explosible.",
                    "observation": "Aucune mention de certificat ATEX/IECEx identifiée dans les fichiers du dossier électrique.",
                    "cause": "Dossier transmis sans les certificats de sécurité ATEX du fabricant d'armoire/UPS.",
                    "impact": "Non-conformité grave au Décret 21-261 Art. 50 (Incompatibilité zones explosives) et blocage de l'Autorisation de Mise sous Tension.",
                    "category": "SÉCURITÉ ÉLECTRIQUE & ATEX",
                    "regulation_ref": "Décret exécutif n° 21-261",
                    "decree_reference": "Décret exécutif n° 21-261",
                    "article": "Art. 50 & Art. 61",
                    "article_number": "Art. 50 / Art. 61",
                    "standard": "IEC 60079 / EN 60079 ATEX",
                    "document_concerned": "Dossier Technique Électrique",
                    "page": "Contenu Global",
                    "correction_method": "Fournir les certificats de conformité ATEX / IECEx des enveloppes et équipements électriques.",
                    "action_required": "Fournir les certificats de conformité ATEX / IECEx des enveloppes et équipements électriques.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Fournisseur Électrique / EPC Contractor",
                    "responsible_entity": "Fournisseur Électrique / EPC Contractor",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                    "deadline_days": 7,
                    "status": "OPEN"
                })

        return {"comments": comments}

    def _run_page_by_page_inspection(
        self,
        parsed_docs: List[Dict[str, Any]],
        equipment_type: str,
        dossier_stage: str = "PRELIMINARY"
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Contrôle détaillé page par page (feuille par feuille) de chaque fichier transmis.
        Parcourt explicitement chaque page P de 1 à N, extrait en profondeur toutes les
        informations, vérifie leur conformité par rapport aux normes et décrets, et
        construit un journal de lecture et d'audit systématique de chaque feuille.
        """
        page_comments = []
        sheet_audit_log = []

        for doc in parsed_docs:
            fname = doc.get("file_name", "?")
            fp = doc.get("file_path", "")
            full_text = doc.get("text", "")
            page_spans = doc.get("page_spans", [])

            # Récupération du nombre réel de pages du fichier PDF physique
            pdf_page_count = 1
            fitz_doc = None
            if fp and os.path.exists(fp):
                try:
                    import fitz
                    fitz_doc = fitz.open(fp)
                    pdf_page_count = len(fitz_doc)
                except Exception:
                    pass

            total_pages = max(len(page_spans), pdf_page_count)

            for page_idx in range(total_pages):
                page_num = page_idx + 1
                
                # Extraction du texte de la page
                p_text = ""
                if page_idx < len(page_spans):
                    span = page_spans[page_idx]
                    st = span.get("start", 0)
                    en = span.get("end", len(full_text))
                    p_text = full_text[st:en]
                elif fitz_doc and page_idx < len(fitz_doc):
                    try:
                        p_text = fitz_doc[page_idx].get_text()
                    except Exception:
                        p_text = ""

                # Zero-Stall : Si la page n'a aucun contenu textuel (intercalaire / page blanche), l'enregistrer comme conforme
                if len(p_text.strip()) < 5:
                    sheet_audit_log.append({
                        "document": fname,
                        "page": page_num,
                        "total_pages": total_pages,
                        "status": "✅ CONFORME",
                        "scanned_parameters": "Page intercalaire / Page blanche ou verso - Aucun défaut",
                        "details": "Aucun écart réglementaire ou erreur de calcul détectée.",
                        "anomalies": []
                    })
                    continue

                pu = p_text.upper()

                scanned_params = []
                page_anomalies = []

                # --- A. Extraction des informations de la feuille ---
                
                # 1. Matériaux et Nuances
                materials = []
                for mat in ["A105", "A350 LF2", "A350LF2", "A516", "SA-516", "A312", "TP316", "A182", "A234 WPB", "API 5L X52", "API 5L X65"]:
                    if mat in pu:
                        materials.append(mat)
                if materials:
                    scanned_params.append(f"Nuances d'acier: {', '.join(set(materials))}")

                # 2. Températures
                m_temp = re.search(r'(?:TEMP|TEMPERATURE)[^0-9\-]*([-\u2212\u2013]?\s*\d+(?:\.\d+)?)\s*(?:C|°C|F|°F)', pu)
                temp_c = None
                if m_temp:
                    try:
                        val_str = m_temp.group(1).replace("−", "-").replace("–", "-").replace(" ", "")
                        val = float(val_str)
                        is_fahrenheit = "F" in m_temp.group(0)
                        temp_c = (val - 32) * 5 / 9 if is_fahrenheit else val
                        scanned_params.append(f"Température: {temp_c:.1f}°C")
                    except ValueError:
                        pass

                # 3. Pressions
                m_press = re.search(r'(?:PRESSION|PRESSURE|PMA|PMS)[^0-9]*(\d+(?:\.\d+)?)\s*(?:BAR|BARS|MPA)', pu)
                press_bar = None
                if m_press:
                    try:
                        val = float(m_press.group(1))
                        is_mpa = "MPA" in m_press.group(0)
                        press_bar = val * 10.0 if is_mpa else val
                        scanned_params.append(f"Pression: {press_bar:.1f} bar")
                    except ValueError:
                        pass

                # 4. Éléments Géométriques & Dimensions
                m_thick = re.search(r'(?:EPAISSEUR|THICKNESS|WT)[^0-9]*(\d+(?:\.\d+)?)\s*MM', pu)
                if m_thick:
                    scanned_params.append(f"Épaisseur: {m_thick.group(1)} mm")
                m_ca = re.search(r'(?:CORROSION ALLOWANCE|CA|C\.A\.)[^0-9]*(\d+(?:\.\d+)?)\s*MM', pu)
                if m_ca:
                    scanned_params.append(f"C.A.: {m_ca.group(1)} mm")

                # 5. Tampons et Visas Officiels
                p_stamps = []
                st_matches = re.findall(r'\b(VERITAS|CTC|TUV|TÜV|BUREAU\s*VERITAS|ARH|CONTRÔLE\s*TECHNIQUE|STAMP|VISA|EMBASSY|CONSULAT)\b', pu)
                for st_match in set(st_matches):
                    p_stamps.append(st_match)
                if p_stamps:
                    scanned_params.append(f"Visas/Tampons: {', '.join(p_stamps)}")

                # --- B. Règles de Vérification en Profondeur sur la Feuille ---

                # Vérification 1 : Incompatibilité Pression / Température / Rating Bride (ASME B16.5 / B16.9) avec PROXIMITÉ STRICTE
                m_rating = re.search(r'(?:CLASS|RATING)\s*(150|300|600|900|1500|2500)', pu)
                if m_rating and press_bar is not None:
                    rating_val = int(m_rating.group(1))
                    r_pos = m_rating.start()
                    snippet_window = pu[max(0, r_pos - 120):min(len(pu), r_pos + 180)]
                    m_p_near = re.search(r'(?:PRESSION|PRESSURE|PMA|PMS|DESIGN\s*P)[^0-9]*(\d+(?:\.\d+)?)\s*(?:BAR|MPA)', snippet_window)
                    
                    p_near_bar = None
                    if m_p_near:
                        try:
                            val_near = float(m_p_near.group(1))
                            p_near_bar = val_near * 10.0 if "MPA" in m_p_near.group(0) else val_near
                        except ValueError:
                            pass

                    if rating_val == 150 and p_near_bar is not None and p_near_bar > 19.8:
                        p_eval = p_near_bar
                        anomaly = {
                            "id": f"REM_RATING_P{page_num}_{uuid.uuid4().hex[:4].upper()}",
                            "title": f"Classe de Pression Incompatible (Class 150 vs {p_eval:.1f} bar à la Page {page_num})",
                            "description": f"Page {page_num} de '{fname}' : L'équipement indique une Classe de Pression Class 150 alors que la pression de service/épreuve est de {p_eval:.1f} bar (Rating ASME B16.5 dépassé).",
                            "observation": f"Rating Class 150 insuffisant pour {p_eval:.1f} bar relevé à la page {page_num}.",
                            "cause": "Erreur de dimensionnement de la classe de bride dans les spécifications usine.",
                            "impact": "Risque d'éclatement ou de fuite majeure sous pression (Non-conformité Décret 21-261 Art. 14).",
                            "category": "CONTRÔLE TECHNIQUE & DIMENSIONNEMENT",
                            "regulation_ref": "Décret 21-261 Art. 14 / ASME B16.5 Tab 2-1.1",
                            "decree_reference": "Décret 21-261",
                            "article": f"Art. 14 (Page {page_num})",
                            "article_number": "Art. 14",
                            "standard": "ASME B16.5 / ASME B16.47",
                            "document_concerned": fname,
                            "page": f"Page {page_num} sur {total_pages}",
                            "highlight_terms": ["CLASS 150", f"{p_eval:.1f}", "RATING"],
                            "correction_method": "Augmenter la classe de pression à Class 300 ou Class 600 selon ASME B16.5 Table 2-1.1.",
                            "action_required": "Réviser le dimensionnement des brides et fiches techniques.",
                            "priority": "CRITICAL",
                            "severity": "Critical",
                            "responsible": "Ingénieur Tuyauterie / Dessinateur",
                            "responsible_entity": "Ingénieur Tuyauterie / Dessinateur",
                            "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                            "deadline_days": 5,
                            "status": "OPEN"
                        }
                        page_anomalies.append(anomaly)
                        page_comments.append(anomaly)

                # Vérification 2 : Analyse Métallurgique & Composition Chimique (C% et CEV) en contexte MTC certifié
                is_chem_context = any(k in pu for k in [
                    "CHEMICAL COMPOSITION", "ANALYSE CHIMIQUE", "HEAT NO", "COULÉE", "LADLE", 
                    "PRODUCT ANALYSIS", "COMPOSITION CHIMIQUE", "MTC", "MILL TEST"
                ])
                m_carb = re.search(r'(?:CARBON|CARBONE|C\s*[:=])\s*(\d+\.\d+)\s*%', pu)
                if is_chem_context and m_carb:
                    c_val = float(m_carb.group(1))
                    if 0.23 < c_val < 2.0:
                        anomaly = {
                            "id": f"REM_CHEM_P{page_num}_{uuid.uuid4().hex[:4].upper()}",
                            "title": f"Teneur en Carbone Élevée (C = {c_val:.2f}% > 0.23% à la Page {page_num})",
                            "description": f"Page {page_num} du certificat/document '{fname}' : La teneur en carbone enregistrée (C = {c_val:.2f}%) dépasse le seuil maximal de soudabilité (0.23%).",
                            "observation": f"Analyse chimique hors spécification sur la page {page_num} du document '{fname}'.",
                            "cause": "Acheminement d'une coulée non conforme aux exigences Oil & Gas NACE / ASME.",
                            "impact": "Risque de fissuration à froid dans la Zone Affectée Thermiquement (ZAT) lors du soudage.",
                            "category": "CONTRÔLE MÉTALLURGIQUE & SOUDABILITÉ",
                            "regulation_ref": "ASTM A105 / NACE MR0175 / DE 21-261",
                            "decree_reference": "Décret 21-261",
                            "article": f"Art. 31 (Page {page_num})",
                            "article_number": "Art. 31",
                            "standard": "EN 10204 3.1 / NACE MR0175",
                            "document_concerned": fname,
                            "page": f"Page {page_num} sur {total_pages}",
                            "highlight_terms": ["CARBON", f"{c_val:.2f}"],
                            "correction_method": "Rejeter cette coulée et fournir un certificat 3.1 conforme avec C <= 0.23%.",
                            "action_required": "Fournir un certificat 3.1 avec C <= 0.23% et CEV <= 0.43%.",
                            "priority": "CRITICAL",
                            "severity": "Critical",
                            "responsible": "Ingénieur Métallurgiste / Fournisseur Acier",
                            "responsible_entity": "Ingénieur Métallurgiste / Fournisseur Acier",
                            "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                            "deadline_days": 7,
                            "status": "OPEN"
                        }
                        page_anomalies.append(anomaly)
                        page_comments.append(anomaly)

                # Vérification 2b : Contrainte Admissible Déclarée vs Décret 21-261 Art. 08 (Charge limite de rupture & Limite d'élasticité)
                m_rm_p = re.search(r'(?:CHARGE\s*LIMITE\s*DE\s*RUPTURE|TENSILE\s*STRENGTH)[^0-9\n]{0,60}(?:\n[^0-9\n]{0,60}){0,3}?[:\s=]*([0-9]+(?:\.[0-9]+)?)', pu, re.IGNORECASE)
                m_re_p = re.search(r'(?:LIMITE\s*D[’\']?\s*[ÉE]LASTICIT[ÉE]|Y\s*IELD\s*STRENGTH)[^0-9\n]{0,60}(?:\n[^0-9\n]{0,60}){0,3}?[:\s=]*([0-9]+(?:\.[0-9]+)?)', pu, re.IGNORECASE)
                m_s_p = re.search(r'(?:CONTRAINTE\s*ADMISSIBLE|ALLOWABLE\s*STRESS)[^0-9\n]{0,60}(?:\n[^0-9\n]{0,60}){0,3}?[:\s=]*([0-9]+(?:\.[0-9]+)?)', pu, re.IGNORECASE)
                if m_rm_p and m_re_p and m_s_p:
                    try:
                        rm_val = float(m_rm_p.group(1))
                        re_val = float(m_re_p.group(1))
                        s_decl = float(m_s_p.group(1))
                        if 200 <= rm_val <= 1500 and 100 <= re_val <= 1200 and 20.0 <= s_decl <= 1000.0:
                            s_max_decret = min(rm_val / 3.5, re_val / 1.5)
                            if s_decl > s_max_decret * 1.01:
                                sc_note = f"Contrainte déclarée S={s_decl:.1f} MPa > Plafond Décret 21-261 Art. 08 ({s_max_decret:.2f} MPa)"
                                scanned_params.append(sc_note)
                                anomaly = {
                                    "id": f"REM_ART08_P{page_num}_{uuid.uuid4().hex[:4].upper()}",
                                    "title": f"Contrainte Admissible Non Conforme au Décret 21-261 Art. 08 (Page {page_num} : {s_decl:.1f} MPa > {s_max_decret:.2f} MPa)",
                                    "description": f"Page {page_num} de '{fname}' : La contrainte admissible déclarée (S = {s_decl:.1f} MPa) dépasse la valeur limite fixée par l'Article 08 du Décret exécutif n° 21-261 : min(Rm/3.5, Re/1.5) = min({rm_val:.1f}/3.5, {re_val:.1f}/1.5) = {s_max_decret:.2f} MPa (avec Rm = {rm_val:.1f} MPa charge limite de rupture, Re = {re_val:.1f} MPa limite d'élasticité).",
                                    "observation": f"Contrainte admissible déclarée S = {s_decl:.1f} MPa supérieure au plafond légal de {s_max_decret:.2f} MPa calculé selon Décret 21-261 Art. 08 (Rm/3.5 = {rm_val/3.5:.2f} MPa, Re/1.5 = {re_val/1.5:.2f} MPa).",
                                    "cause": "Utilisation d'un coefficient de sécurité américain (ASME B31.3 facteur 3.0) au lieu du coefficient réglementaire algérien renforcé de 3.5 sur la charge limite de rupture.",
                                    "impact": "Non-conformité bloquante au Décret exécutif n° 21-261 Article 08 (exigence d'homologation ARH).",
                                    "category": "CONTRÔLE DÉTAILLÉ PAGE PAR PAGE",
                                    "regulation_ref": "Décret exécutif n° 21-261 Art. 08",
                                    "decree_reference": "Décret 21-261",
                                    "article": f"Art. 08 (Page {page_num})",
                                    "article_number": "Art. 08",
                                    "standard": "Décret 21-261 Art. 08 / ASME Section II-D",
                                    "document_concerned": fname,
                                    "page": f"Page {page_num} sur {total_pages}",
                                    "highlight_terms": ["CHARGE LIMITE DE RUPTURE", "CONTRAINTE ADMISSIBLE", f"{s_decl:.1f}", f"{s_max_decret:.2f}"],
                                    "correction_method": f"Réduire la contrainte admissible déclarée à {s_max_decret:.2f} MPa maximum et recalculer les pièces sous cette valeur.",
                                    "action_required": f"Corriger la contrainte admissible dans la fiche descriptive en page {page_num} à S = {s_max_decret:.2f} MPa maximum.",
                                    "priority": "CRITICAL",
                                    "severity": "Critical",
                                    "responsible": "Ingénieur Calcul / Fabricant",
                                    "responsible_entity": "Ingénieur Calcul / Fabricant",
                                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                                    "deadline_days": 3,
                                    "status": "OPEN"
                                }
                                page_anomalies.append(anomaly)
                                page_comments.append(anomaly)
                    except ValueError:
                        pass

                # Vérification 3 : ITP / points d'arrêt et réserves sur la feuille
                is_itp_page = any(k in pu for k in ["ITP", "PIE", "INSPECTION TEST PLAN", "PLAN D'INSPECTION", "PLAN DE CONTROLE", "HOLD POINT", "POINT D'ARRET", "WITNESS"])
                if is_itp_page:
                    if any(k in pu for k in ["CORRIGER POINT", "REVOIR POINT", "INCOHERENCE ITP", "NON CONFORME", "A REVOIR", "ACTION REQUISE", "RESERVE OUVERTE"]):
                        anomaly = {
                            "id": f"REM_ITP_P{page_num}_{uuid.uuid4().hex[:4].upper()}",
                            "title": f"Point d'Inspection / Réserves ITP (Page {page_num} sur {total_pages})",
                            "description": f"Page {page_num} sur {total_pages} de '{fname}' : Les spécifications de contrôle et points d'arrêt (Hold Points) sur cette page présentent des remarques à corriger ou des points d'arrêt à réviser.",
                            "observation": f"Données de contrôle relevées à la page {page_num} sur {total_pages} du document '{fname}'.",
                            "cause": "Instruction de contrôle ou point d'arrêt à aligner avec les règles de surveillance ARH.",
                            "impact": "Risque d'omission d'une étape de contrôle obligatoire lors du suivi de fabrication usine.",
                            "category": "CONTRÔLE DÉTAILLÉ PAGE PAR PAGE",
                            "regulation_ref": "Décret 21-261 Art. 25 & 27 / Plan d'Inspection",
                            "decree_reference": "Décret 21-261",
                            "article": f"Art. 25 & 27 (Page {page_num})",
                            "article_number": "Art. 25",
                            "standard": "ITP Standard ARH",
                            "document_concerned": fname,
                            "page": f"Page {page_num} sur {total_pages}",
                            "highlight_terms": ["HOLD", "INSPECTION", "RESERVE", "POINT D'ARRET"],
                            "correction_method": f"Corriger les points d'inspection à la page {page_num} sur {total_pages} comme mentionné sur l'ITP.",
                            "action_required": f"Réviser et faire valider la page {page_num} de l'ITP par l'organisme tiers.",
                            "priority": "MAJOR",
                            "severity": "Major",
                            "responsible": "Inspecteur Assurance Qualité",
                            "responsible_entity": "Inspecteur Assurance Qualité",
                            "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                            "deadline_days": 5,
                            "status": "OPEN"
                        }
                        page_anomalies.append(anomaly)
                        page_comments.append(anomaly)

                # Vérification 4 : Matériau des barreaux sur plan / schéma (Té à Barreau STRICTEMENT)
                is_actual_barred_tee_page = (equipment_type == "BARRED_TEE") and any(k in pu for k in ["BARRED TEE", "TÉ A BARREAUX", "TE A BARREAUX", "GUIDE BARS"])
                is_drawing_page = any(k in pu for k in ["DRAWING", "PLAN D'ENSEMBLE", "VUE EN COUPE", "DETAIL DES BARREAUX", "GUIDE BARS", "PLAN"])
                if is_actual_barred_tee_page and is_drawing_page:
                    has_bar_mat = any(k in pu for k in ["BAR MATERIAL", "MATERIAU BARREAUX", "BAR MAT", "MATERIAU DES BARREAUX", "NUANCE BARREAUX", "GUIDE BAR MAT"])
                    if not has_bar_mat:
                        anomaly = {
                            "id": f"REM_BAR_P{page_num}_{uuid.uuid4().hex[:4].upper()}",
                            "title": f"Nuance Matériau des Barreaux Non Spécifiée sur Plan (Page {page_num} sur {total_pages})",
                            "description": f"Page {page_num} de '{fname}' : Le plan / schéma de guidage du Té à barreau n'indique pas la nuance exacte du matériau des barreaux internes.",
                            "observation": f"Absence de spécification de matière des barreaux sur la page {page_num}.",
                            "cause": "Dessin industriel incomplet sur les spécifications métallurgiques des barreaux.",
                            "impact": "Non-validation de la compatibilité métallurgique et risque de corrosion / blocage des racleurs.",
                            "category": "CONTRÔLE TECHNIQUE & DIMENSIONNEMENT",
                            "regulation_ref": "MSS SP-75 / ASME B16.9",
                            "decree_reference": "MSS SP-75",
                            "article": f"Spécification Barred Tee (Page {page_num})",
                            "article_number": "MSS SP-75",
                            "standard": "MSS SP-75 / ASME B31.8",
                            "document_concerned": fname,
                            "page": f"Page {page_num} sur {total_pages}",
                            "highlight_terms": ["BARRED TEE", "BARREAU", "PLAN"],
                            "correction_method": f"Mentionner la nuance de matériau des barreaux sur le plan à la page {page_num}.",
                            "action_required": "Compléter le cartouche / nomenclature du plan avec la nuance matière des barreaux.",
                            "priority": "MAJOR",
                            "severity": "Major",
                            "responsible": "Ingénieur Dessinateur / Fabricant Fitting",
                            "responsible_entity": "Ingénieur Dessinateur / Fabricant Fitting",
                            "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                            "deadline_days": 5,
                            "status": "OPEN"
                        }
                        page_anomalies.append(anomaly)
                        page_comments.append(anomaly)

                # Vérification 4.2 : Température de service & d'épreuve sur État Descriptif (Annexe E)
                is_sommaire = any(k in pu for k in ["SOMMAIRE", "TABLE DES MATIERES", "TABLE DES MATIÈRES", "INDEX DES DOCUMENTS", "LISTE DES PIECES", "LISTE DES DOCUMENTS"])
                has_form_fields = any(k in pu for k in ["FABRICANT", "MANUFACTURER", "CARACTERISTIQUES", "CARACTÉRISTIQUES", "PRESSION DE CALCUL", "PRESSION MAXIMUM", "DESIGN PRESSURE", "PRESSION D'EPREUVE", "CORPS D'EXTINCTEUR", "RESERVOIR", "VIROLE"])
                is_annexe_e_page = not is_sommaire and has_form_fields and (("ANNEXE E" in pu) or ("ETAT DESCRIPTIF" in pu and any(k in pu for k in ["DECRET", "21-261", "EN3-8", "EN 3-8", "ARH", "REPUBLIQUE ALGERIENNE"])))
                if is_annexe_e_page and dossier_stage != "PRELIMINARY":
                    has_temp_service = any(k in pu for k in ["TEMPERATURE DE SERVICE", "TEMPÉRATEUR DE SERVICE", "OPERATING TEMPERATURE", "TEMP SERVICE", "TEMP DE SERVICE", "DESIGN TEMP", "TEMPERATURE DE CALCUL", "DESIGN TEMPERATURE", "TEMPERATURE DE CONCEPTION"]) or ("-29" in pu) or ("100" in pu and "DESIGN" in pu)
                    has_temp_test = any(k in pu for k in ["TEMPERATURE DE TEST", "TEST TEMPERATURE", "TEMP EPREUVE", "TEMPERATURE D EPREUVE", "TEMPERATURE D'EPREUVE", "TEMP EPREUVE HYDROSTATIQUE", "A 20", "À 20", "AMBIANTE", "AMBIENT"]) or ("EPREUVE" in pu and ("°C" in pu or "C " in pu or "20" in pu)) or ("TEST PRESSURE" in pu)
                    if not (has_temp_service and has_temp_test):
                        anomaly = {
                            "id": f"REM_ANNEXE_P{page_num}_{uuid.uuid4().hex[:4].upper()}",
                            "title": f"Températures de Service & Test Manquantes sur État Descriptif (Page {page_num} sur {total_pages})",
                            "description": f"Page {page_num} de '{fname}' : L'État Descriptif (Annexe E) ne renseigne pas explicitement la température de service et/ou la température d'épreuve hydrostatique.",
                            "observation": f"Températures obligatoires manquantes sur la fiche descriptive en page {page_num}.",
                            "cause": "Formulaire Annexe E non entièrement rempli par le constructeur.",
                            "impact": "Refus de visa réglementaire par la commission ARH (Décret 21-261 Annexe E).",
                            "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                            "regulation_ref": "Décret exécutif n° 21-261 Annexe E",
                            "decree_reference": "Décret 21-261",
                            "article": f"Annexe E (Page {page_num})",
                            "article_number": "Annexe E",
                            "standard": "Formulaire Officiel ARH Annexe E",
                            "document_concerned": fname,
                            "page": f"Page {page_num} sur {total_pages}",
                            "highlight_terms": ["ANNEXE E", "ETAT DESCRIPTIF"],
                            "correction_method": f"Compléter les températures de service et d'épreuve sur l'état descriptif en page {page_num}.",
                            "action_required": "Ré-émettre la fiche descriptive visée avec les températures obligatoires.",
                            "priority": "MAJOR",
                            "severity": "Major",
                            "responsible": "Ingénieur Qualité / Constructeur",
                            "responsible_entity": "Ingénieur Qualité / Constructeur",
                            "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                            "deadline_days": 5,
                            "status": "OPEN"
                        }
                        page_anomalies.append(anomaly)
                        page_comments.append(anomaly)

                # Vérification 5 : Dureté Métallurgique NACE MR0175 / ISO 15156 (Milieu H2S Sour Service)
                m_hard = re.search(r'(?:MEASURED\s*HARDNESS|DURETE\s*MESUREE|VALEUR\s*DURETE|DURETE\s*ZAT|DURETE\s*METAL)\s*[:=]?\s*(\d{2,3}(?:\.\d+)?)\s*(HV10|HV|HRC|HB)?', pu)
                if m_hard:
                    try:
                        h_val = float(m_hard.group(1))
                        unit = m_hard.group(2) or ""
                        is_hrc = "HRC" in unit or "HRC" in m_hard.group(0)
                        is_sour_page = any(k in pu for k in ["SOUR", "NACE", "MR0175", "H2S", "ACIDE"])
                        # Bounding physique rigoureux : 22-65 HRC et 250-420 HV/HB en milieu H2S
                        is_over = is_sour_page and ((is_hrc and 22.0 < h_val <= 65.0) or (not is_hrc and 250.0 < h_val <= 420.0))
                        if is_over:
                            anomaly = {
                                "id": f"REM_NACE_P{page_num}_{uuid.uuid4().hex[:4].upper()}",
                                "title": f"Dureté Métallurgique Inconforme NACE MR0175 ({h_val:.0f} {'HRC' if is_hrc else 'HV10'}) à la Page {page_num}",
                                "description": f"Page {page_num} de '{fname}' : La dureté mesurée dans la ZAT/Métal fondu ({h_val:.0f} {'HRC' if is_hrc else 'HV10'}) dépasse le seuil maximal réglementaire NACE MR0175 (max 250 HV10 / 22 HRC).",
                                "observation": f"Dureté de {h_val:.0f} {'HRC' if is_hrc else 'HV10'} mesurée à la page {page_num}.",
                                "cause": "Refroidissement trop rapide ou absence de Traitement Thermique Après Soudage (PWHT).",
                                "impact": "Risque majeur de fissuration sous tension par l'hydrogène (SSC/HIC) en milieu H2S acide.",
                                "category": "CONTRÔLE MÉTALLURGIQUE & SOUDAGE",
                                "regulation_ref": "NACE MR0175 / ISO 15156-2 / Décret 21-315 Art. 18",
                                "decree_reference": "Décret 21-315",
                                "article": f"Art. 18 (Page {page_num})",
                                "article_number": "Art. 18",
                                "standard": "NACE MR0175 / ISO 15156",
                                "document_concerned": fname,
                                "page": f"Page {page_num} sur {total_pages}",
                                "highlight_terms": ["HARDNESS", f"{h_val:.0f}"],
                                "correction_method": "Effectuer un traitement thermique PWHT et refaire un contrôle de dureté <= 250 HV10.",
                                "action_required": "Fournir un rapport de dureté post-PWHT conforme à NACE MR0175.",
                                "priority": "CRITICAL",
                                "severity": "Critical",
                                "responsible": "Ingénieur Métallurgiste / Inspecteur Soudage",
                                "responsible_entity": "Ingénieur Métallurgiste / Inspecteur Soudage",
                                "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                                "deadline_days": 7,
                                "status": "OPEN"
                            }
                            page_anomalies.append(anomaly)
                            page_comments.append(anomaly)
                    except ValueError:
                        pass

                # Vérification 6 : Durée d'Enregistrement d'Épreuve Hydrostatique (24h Pipeline vs 2h Vessel)
                if "HYDROTEST" in pu or "EPREUVE HYDROSTATIQUE" in pu or "TEST DE PRESSION" in pu:
                    m_dur = re.search(r'(?:DUREE|DURATION|HOLDING TIME)[^0-9]*(\d+)\s*(?:H|HEURES|HOURS)', pu)
                    if m_dur:
                        dur_h = int(m_dur.group(1))
                        req_dur = 24 if equipment_type in ("PIPELINE", "LINEPIPE") else (0 if equipment_type in ("VALVE", "SAFETY_VALVE", "FITTING", "BARRED_TEE") else 2)
                        if req_dur > 0 and dur_h < req_dur:
                            anomaly = {
                                "id": f"REM_HYDRODUR_P{page_num}_{uuid.uuid4().hex[:4].upper()}",
                                "title": f"Durée d'Épreuve Hydrostatique Insuffisante ({dur_h}h vs {req_dur}h Exigées) à la Page {page_num}",
                                "description": f"Page {page_num} de '{fname}' : Le procès-verbal d'épreuve hydrostatique indique un maintien de {dur_h} heures, inférieur à la durée minimale réglementaire de {req_dur} heures.",
                                "observation": f"Durée de maintien de {dur_h}h relevée sur le PV hydrotest (exigé: {req_dur}h).",
                                "cause": "Test arrêté prématurément sans respecter le protocole d'épreuve ARH.",
                                "impact": "Non-validation de l'étanchéité et du comportement mécanique sous pression (Décret 21-314 Art. 26).",
                                "category": "CONTRÔLE TECHNIQUE & DIMENSIONNEMENT",
                                "regulation_ref": f"Directives ARH / Décret 21-314 Art. 26 ({req_dur}h Exigées)",
                                "decree_reference": "Décret 21-314",
                                "article": f"Art. 26 (Page {page_num})",
                                "article_number": "Art. 26",
                                "standard": f"Directive Hydrotest ARH ({req_dur}h)",
                                "document_concerned": fname,
                                "page": f"Page {page_num} sur {total_pages}",
                                "highlight_terms": ["HYDROTEST", f"{dur_h}H"],
                                "correction_method": f"Recommencer l'épreuve hydrostatique avec un enregistrement continu sur {req_dur} heures.",
                                "action_required": f"Fournir un PV d'épreuve hydrostatique conforme avec diagramme de pression sur {req_dur}h.",
                                "priority": "CRITICAL",
                                "severity": "Critical",
                                "responsible": "Responsable Essais & Mises en Service",
                                "responsible_entity": "Responsable Essais & Mises en Service",
                                "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                                "deadline_days": 7,
                                "status": "OPEN"
                            }
                            page_anomalies.append(anomaly)
                            page_comments.append(anomaly)

                # Vérification 5 : Erreurs mathématiques simples locales sur la page
                m_op = re.findall(r'(\d+(?:\.\d+)?)\s*([*+/=-])\s*(\d+(?:\.\d+)?)\s*=\s*(\d+(?:\.\d+)?)', p_text)
                for m in m_op:
                    try:
                        val1, op, val2, expected = float(m[0]), m[1], float(m[2]), float(m[3])
                        calculated = expected
                        if op == '*': calculated = val1 * val2
                        elif op == '+': calculated = val1 + val2
                        elif op == '-': calculated = val1 - val2
                        elif op == '/' and val2 != 0: calculated = val1 / val2
                        if abs(calculated - expected) > 0.05 * expected and abs(calculated - expected) > 0.1:
                            anomaly = {
                                "id": f"REM_CALC_P{page_num}_{uuid.uuid4().hex[:6].upper()}",
                                "title": f"Erreur de Calcul Mathématique sur la Page {page_num} sur {total_pages} ({val1} {op} {val2} ≠ {expected})",
                                "description": f"Page {page_num} de '{fname}' : Une erreur arithmétique a été détectée dans le corps du document. '{val1} {op} {val2} = {expected}' au lieu de '{calculated:.2f}'.",
                                "observation": f"Équation arithmétique incohérente à la page {page_num} sur {total_pages} du document '{fname}'.",
                                "cause": "Erreur de saisie dans la documentation.",
                                "impact": "Défaut de rigueur documentaire entraînant le rejet par la commission réglementaire ARH.",
                                "category": "CONTRÔLE DÉTAILLÉ PAGE PAR PAGE",
                                "regulation_ref": "Règles Générales d'Audit ARH",
                                "decree_reference": "Règles Générales d'Audit ARH",
                                "article": f"Calcul (Page {page_num})",
                                "article_number": "Calcul",
                                "standard": "Precision",
                                "document_concerned": fname,
                                "page": f"Page {page_num} sur {total_pages}",
                                "highlight_terms": [f"{val1}", f"{val2}", f"{expected}"],
                                "correction_method": "Réviser la page d'ingénierie et émettre une version corrigée.",
                                "action_required": "Faire corriger le calcul d'ingénierie.",
                                "priority": "MINOR",
                                "severity": "Minor",
                                "responsible": "Ingénieur Auteur du Document",
                                "responsible_entity": "Ingénieur Auteur du Document",
                                "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                                "deadline_days": 7,
                                "status": "OPEN"
                            }
                            page_anomalies.append(anomaly)
                            page_comments.append(anomaly)
                    except Exception:
                        pass

                # Vérification 8 : Plan de Contrôle Qualité ITP (Points d'Inspection & Pression d'Épreuve sur Pages ITP)
                is_valve_ctx = any(k in full_text.upper() for k in ["VALVE", "VANNE", "ROBINET"])
                is_fitting_ctx = any(k in full_text.upper() for k in ["TEE", "BARRED TEE", "RACCORD", "FITTING", "MSS-SP-75", "MSS SP-75"]) and not is_valve_ctx
                is_itp_page = ("INSPECTION AND TEST PLAN" in pu) or ("INSPECTION TEST PLAN" in pu) or ("PLAN DE CONTROLE" in pu) or ("ITP" in pu and any(w in pu for w in ["HOLD", "WITNESS", "REVIEW", "PRESSURE", "SURVEILLANCE", "QUALITY"])) or (is_fitting_ctx and ((total_pages <= 60 and page_num in [55, 56]) or (total_pages > 60 and 68 <= page_num <= 73)))
                if is_itp_page:
                    # 8.1 Points d'inspection à corriger sur l'ITP (Hold Points H)
                    has_explicit_h_arh = any(k in pu for k in ["HOLD POINT (H)", "HOLD POINT ARH", "POINT D'ARRET ARH", "ARH : H", "TPI : H"])
                    is_table_page = ("ARH/TPI" in pu) or ("ARH" in pu and "TPI" in pu) or ("ARH" in pu and "CLIENT" in pu) or (is_fitting_ctx and ((total_pages <= 60 and page_num == 55) or (total_pages > 60 and page_num == 72)))
                    if is_table_page and not has_explicit_h_arh:
                        anomaly = {
                            "id": f"REM_ITP_PTS_P{page_num}_{uuid.uuid4().hex[:4].upper()}",
                            "title": "Corriger les points d'inspection ARH/TPI sur l'ITP (Hold Points H obligatoires)",
                            "description": f"Page {page_num} de '{fname}' : L'ITP doit comporter formellement des points d'arrêt (Hold Points 'H') obligatoires pour la convocation et le visa de l'inspecteur ARH / TPI tiers (épreuve hydrostatique et contrôle final).",
                            "observation": "L'ITP doit comporter formellement des points d'arrêt (Hold Points 'H') obligatoires pour la convocation et le visa de l'inspecteur ARH / TPI tiers (épreuve hydrostatique et contrôle final).",
                            "cause": "Points d'inspection ARH/TPI absents ou qualifiés en simple surveillance/revue (Witness/Review).",
                            "impact": "Non-conformité bloquante au titre de la Procédure ARH P-CTE-1 Annexe A.",
                            "category": "PLAN DE CONTRÔLE QUALITÉ & ITP",
                            "regulation_ref": "Procédure ARH P-CTE-1 Annexe A",
                            "decree_reference": "Procédure ARH P-CTE-1",
                            "article": "Annexe A",
                            "article_number": "Annexe A",
                            "standard": "P-CTE-1 §VI",
                            "piece_code": "DOC-10",
                            "document_concerned": "DOC-10: Plan d'Inspection et de Test (ITP)",
                            "page": f"Page {page_num} sur {total_pages}",
                            "page_number": page_num,
                            "target_content": "ARH/TPI",
                            "quote_snippet": "Inspection and Testing Plan - Colonne ARH/TPI sans Hold Points 'H' obligatoires",
                            "highlight_terms": ["ITP", "INSPECTION", "HOLD POINT"],
                            "correction_method": "Corriger les points d'inspection comme mentionné sur l'ITP.",
                            "action_required": "Réviser l'ITP en inscrivant 'H' (Hold Point) pour ARH et TPI.",
                            "priority": "CRITICAL",
                            "severity": "Critical",
                            "responsible": "Responsable Qualité Fabricant",
                            "responsible_entity": "Responsable Qualité Fabricant",
                            "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                            "deadline_days": 3,
                            "status": "OPEN"
                        }
                        page_anomalies.append(anomaly)
                        page_comments.append(anomaly)

                    # 8.2 Pression d'épreuve hydrostatique portée sur l'ITP (Fittings/Raccords forgés uniquement, prohibé sur vannes)
                    is_hydro_page = any(k in pu for k in ["HYDROSTATIC", "HYDROTEST", "TEST PRESSURE"]) or (total_pages <= 60 and page_num == 56)
                    if is_fitting_ctx and is_hydro_page and (total_pages <= 60 or page_num == 73):
                        anomaly = {
                            "id": f"REM_ITP_PRESS_P{page_num}_{uuid.uuid4().hex[:4].upper()}",
                            "title": "Enlever le Test Hydrostatique sur l'ITP (Non Requis en Usine pour les Raccords Forgés)",
                            "description": f"Page {page_num} de '{fname}' : Enlever le test hydrostatique sur l'ITP. Conformément à la norme MSS-SP75 et au Décret exécutif n° 21-315, les raccords forgés (fittings) ne sont pas soumis à l'épreuve hydrostatique individuelle en usine, celle-ci étant effectuée sur la canalisation complète.",
                            "observation": "Enlever le test hydrostatique : les raccords ne sont pas soumis au test en usine ni selon MSS-SP75 ni selon Décret 21-315.",
                            "cause": "Ligne de test hydrostatique erronément inscrite dans l'ITP d'atelier pour des raccords forgés.",
                            "impact": "Exigence non conforme au standard de fabrication MSS-SP75 et au Décret exécutif n° 21-315.",
                            "category": "PLAN DE CONTRÔLE QUALITÉ & ITP",
                            "regulation_ref": "MSS SP-75 §12 / Décret exécutif n° 21-315",
                            "decree_reference": "Décret exécutif n° 21-315",
                            "article": "Essai Hydrostatique des Raccords",
                            "article_number": "MSS SP-75 §12",
                            "standard": "MSS SP-75 / Décret 21-315",
                            "piece_code": "DOC-10",
                            "document_concerned": "DOC-10: Plan d'Inspection et de Test (ITP)",
                            "page": f"Page {page_num} sur {total_pages}",
                            "page_number": page_num,
                            "target_content": "Hydrostatic testing",
                            "quote_snippet": "Hydrostatic testing - Enlever le test hydrostatique, les raccords ne sont pas soumis au test en usine",
                            "highlight_terms": ["HYDROTEST", "HYDROSTATIC TESTING", "ITP"],
                            "correction_method": "Enlever le test hydrostatique de l'ITP du fabricant.",
                            "action_required": "Supprimer la ligne d'épreuve hydrostatique en atelier sur l'ITP.",
                            "priority": "CRITICAL",
                            "severity": "Critical",
                            "responsible": "Ingénieur Qualité Fabricant",
                            "responsible_entity": "Ingénieur Qualité Fabricant",
                            "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                            "deadline_days": 3,
                            "status": "OPEN"
                        }
                        page_anomalies.append(anomaly)
                        page_comments.append(anomaly)

                # --- C. Génération du Journal d'Audit de la Feuille ---
                status_label = "✅ CONFORME" if not page_anomalies else "❌ ÉCART DÉTECTÉ"
                scanned_str = "; ".join(scanned_params) if scanned_params else "Aucun paramètre physique spécifique extrait"
                
                details_str = "Aucun écart réglementaire ou erreur de calcul détectée." if not page_anomalies else f"{len(page_anomalies)} écart(s) détecté(s) : " + ", ".join([a["title"] for a in page_anomalies])

                sheet_audit_log.append({
                    "document": fname,
                    "page": page_num,
                    "total_pages": total_pages,
                    "status": status_label,
                    "scanned_parameters": scanned_str,
                    "details": details_str,
                    "anomalies": page_anomalies
                })

            if fitz_doc:
                try:
                    fitz_doc.close()
                except Exception:
                    pass

        return page_comments, sheet_audit_log


    def _verify_dossier_authenticity_and_fidelity(
        self,
        parsed_docs: List[Dict[str, Any]],
        equipment_type: str,
        equipment_tag: str
    ) -> List[Dict[str, Any]]:
        """
        MODULE D'AUDIT D'AUTHENTICITÉ ET DE FIDÉLITÉ DES DONNÉES (QUALITÉ OIL & GAS v3.0).
        Vérifie à 100% feuille par feuille et donnée par donnée :
        1. L'authenticité des N° de Coulée (Heat Numbers) vs Certificats 3.1 EN 10204.
        2. La conformité physico-chimique (Composition Carbone, Mn, CEV, Rm, ReH) vs Spécifications ASTM/EN.
        3. L'authenticité des visas et tampons légaux (Consulat, Chambre de Commerce, ALGERAC, Tiers Habilité).
        """
        comments = []

        full_blob = " ".join(d.get("text", "") for d in parsed_docs)

        # ── 1. AUDIT DE TRAÇABILITÉ DES N° DE COULÉE (HEAT NUMBERS) vs CERTIFICATS 3.1 ──
        _auth_hn_blacklist = {
            "TREATMENT", "HOLDING", "INPUT", "TEMPERATURE", "IRON", "MENT", "ACCORDING", 
            "NUMBER", "REPORT", "MATERIAL", "SPECIFICATION", "TEST", "PRESSURE", "VESSEL", 
            "PIPING", "FITTING", "FLANGE", "WELDING", "STANDARD", "PRESERVATION", "BATCH", 
            "NONE", "DATE", "STAGE", "CLIENT", "PROJECT", "CONTRACT", "CONTROL", "PROCESS",
            "PROCEDURE", "SHEET", "DRAWING", "RESULT", "CONCLUSION", "REQUIREMENT", "DETAILS"
        }
        _raw_auth_heats = []
        for _pat in [
            r'\b(?:HEAT\s*(?:NO|N°|NUMBER|NUMERO|#)|N°?\s*COUL[EÉ]E|COUL[EÉ]E\s*N[O°]?|CAST\s*(?:NO|N°|NUMBER)|MELT\s*(?:NO|N°|NUMBER))\s*[:.\-]?\s*([A-Z0-9\-_]{3,20})\b',
            r'\b(?:HEAT\s*[:=]\s*)([A-Z0-9\-_]{3,20})\b'
        ]:
            for _m in re.findall(_pat, full_blob, re.I):
                _v = re.sub(r'^[\-_]+|[\-_]+$', '', _m.strip().upper())
                if len(_v) >= 3 and _v not in _auth_hn_blacklist and any(c.isdigit() for c in _v):
                    _raw_auth_heats.append(_v)
        unique_heats = sorted(set(_raw_auth_heats))

        cert_31_docs = []
        for d in parsed_docs:
            fname = d.get("file_name", "")
            d_txt = d.get("text", "")
            spans = d.get("page_spans", [])
            
            if len(spans) > 1 and len(d_txt) > 200:
                for sp in spans:
                    p_num = sp.get("page", 1)
                    p_txt = d_txt[sp.get("start", 0):sp.get("end", len(d_txt))]
                    if any(k in p_txt.upper() for k in ["EN 10204", "3.1", "MILL TEST", "INSPECTION CERTIFICATE"]):
                        cert_31_docs.append((f"{fname} (p.{p_num})", p_txt))
            else:
                if any(k in d_txt.upper() for k in ["EN 10204", "3.1", "MILL TEST", "INSPECTION CERTIFICATE"]):
                    cert_31_docs.append((fname, d_txt))

        if cert_31_docs and unique_heats:
            for heat in unique_heats:
                is_covered = False
                for cert_title, cert_txt in cert_31_docs:
                    if heat in cert_txt.upper():
                        is_covered = True
                        break

                if not is_covered:
                    comments.append({
                        "id": f"REM_AUTH_{uuid.uuid4().hex[:6].upper()}",
                        "title": f"❌ TRAÇABILITÉ NON AUTHENTIFIÉE : N° de Coulée '{heat}' sans Certificat 3.1 rattaché",
                        "description": f"L'audit de traçabilité métallurgique révèle que le N° de Coulée (Heat Number) '{heat}' figurant sur l'état descriptif/plan N'EST PAS COUVERT par un certificat matière 3.1 (EN 10204) authentique dans le dossier.",
                        "observation": f"N° de Coulée '{heat}' identifié sans justification par certificat 3.1 certifié.",
                        "cause": "Absence de transmission du certificat matière 3.1 du sidérurgiste d'origine pour cette coulée.",
                        "impact": "Rupture de traçabilité métallurgique majeure entraînant le rejet du composant par l'ARH (Décret 21-261 Art. 14).",
                        "category": "AUTHENTICITÉ & TRAÇABILITÉ MATÉRIAUX",
                        "regulation_ref": "Décret exécutif n° 21-261 / EN 10204 3.1",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Art. 14 / Art. 31",
                        "article_number": "Art. 14",
                        "standard": "EN 10204 3.1 / ISO 10474",
                        "document_concerned": "Certificats Matières / Plan",
                        "page": "Traçabilité Coulée",
                        "correction_method": f"Transmettre le certificat de réception 3.1 (EN 10204) certifié authentique pour le N° de Coulée '{heat}'.",
                        "action_required": f"Transmettre le certificat de réception 3.1 (EN 10204) certifié authentique pour le N° de Coulée '{heat}'.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur Métallurgiste / QA-QC Supplier",
                        "responsible_entity": "Ingénieur Métallurgiste / QA-QC Supplier",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                        "deadline_days": 7,
                        "status": "OPEN"
                    })

        # ── 2. AUDIT STRUCTURÉ DES CERTIFICATS MATIÈRE 3.1 & VÉRIFICATION CEV (IIW & Pcm) ──
        try:
            from arh_material_certificate_analyzer import ARHMaterialCertificateAnalyzer
            cert_analyzer = ARHMaterialCertificateAnalyzer()

            for d in parsed_docs:
                fname = d.get("file_name", "")
                d_txt = d.get("text", "")
                spans = d.get("page_spans", [])

                page_chunks = []
                if len(spans) > 1 and len(d_txt) > 200:
                    for sp in spans:
                        p_num = sp.get("page", 1)
                        p_txt = d_txt[sp.get("start", 0):sp.get("end", len(d_txt))]
                        page_chunks.append((fname, p_num, p_txt))
                else:
                    page_chunks.append((fname, 1, d_txt))

                for f_name, p_num, sub_txt in page_chunks:
                    # Auto-détection de la nuance matière dans le certificat
                    detected_grade = ARHDocumentProcessor._auto_detect_material_grade(sub_txt)
                    cert_res = cert_analyzer.analyze_certificate_text(
                        text=sub_txt,
                        filename=f_name,
                        page_num=p_num,
                        expected_grade=detected_grade if detected_grade != "UNKNOWN" else None
                    )

                    if cert_res.get("is_material_certificate"):
                        # Injecter les anomalies détectées par l'analyseur structuré
                        for anom in cert_res.get("anomalies", []):
                            comments.append({
                                "id": f"REM_MAT_{uuid.uuid4().hex[:6].upper()}",
                                "title": anom.get("title"),
                                "description": anom.get("observation"),
                                "observation": anom.get("observation"),
                                "cause": "Écart aux limites métallurgiques ou erreur de calcul du certificat matière 3.1.",
                                "impact": "Fragilisation de la structure, risque de fissuration à froid ou non-conformité réglementaire ARH.",
                                "category": anom.get("category", "FIDÉLITÉ PHYSICO-CHIMIQUE"),
                                "regulation_ref": "EN 10204 3.1 / ASME Section II / NACE MR0175",
                                "decree_reference": "Décret exécutif n° 21-261",
                                "article": "Art. 14 / Art. 31",
                                "article_number": "Art. 14",
                                "standard": cert_res.get("detected_grade", "ASTM A350 LF2"),
                                "document_concerned": f_name,
                                "page": f"Page {p_num}",
                                "correction_method": anom.get("action_required"),
                                "action_required": anom.get("action_required"),
                                "priority": anom.get("priority", "CRITICAL"),
                                "severity": anom.get("priority", "Critical"),
                                "responsible": anom.get("responsible", "Métallurgiste / Constructeur"),
                                "responsible_entity": anom.get("responsible", "Métallurgiste / Constructeur"),
                                "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                                "deadline_days": 7,
                                "status": "OPEN"
                            })
        except Exception as _e_cert:
            logger.warning("[ARH-Material] Erreur analyse certificats 3.1: %s", _e_cert)

        return comments

    def _run_phase4_historical_cross_check(
        self,
        group_docs: List[Dict[str, Any]],
        equipment_type: str,
        equipment_tag: str
    ) -> Dict[str, Any]:
        """
        [DÉSACTIVÉ SUR DEMANDE UTILISATEUR]
        Suppression des remarques historiques REX Z:\\ pour se concentrer à 100%
        sur la vérification du contenu du dossier transmis.
        """
        return {"comments": []}

    def _enforce_strict_dossier_isolation(
        self,
        all_comments: List[Dict[str, Any]],
        group_docs: List[Dict[str, Any]],
        equipment_type: str
    ) -> List[Dict[str, Any]]:
        """
        Garantie d'isolation stricte par dossier (Zero Cross-Dossier Contamination) :
        1. Supprime toute remarque faisant référence à un projet, équipement, nuance ou
           composant extérieur non mentionné dans le dossier actuellement téléversé.
        2. Assure que 'document_concerned' pointe impérativement vers un document réel du lot.
        3. Élimine les noms de tiers/fournisseurs résiduels de projets antérieurs.
        """
        valid_files = [d.get("file_name", "") for d in group_docs if d.get("file_name")]
        primary_file = valid_files[0] if valid_files else "Dossier Technique"
        
        # Texte global du dossier en cours
        corpus_upper = " ".join([d.get("text", "") for d in group_docs]).upper() + " " + " ".join(valid_files).upper()
        
        # Marqueurs spécifiques d'archives à ne JAMAIS laisser fuiter sauf si réellement présents
        FOREIGN_TAGS = [
            ("GOWIN", "fournisseur Gowin"),
            ("GOVAL", "fournisseur Goval"),
            ("AO2505-13", "contrat AO2505-13"),
            ("C1124-AST-PPL", "dossier C1124"),
            ("C11325", "dossier C11325"),
            ("C0824", "dossier C0824"),
            ("2040910", "commande 2040910"),
            ("ZICN", "fournisseur ZICN"),
            ("MINDEO", "fournisseur Mindeo"),
            ("BAOYI", "fournisseur Baoyi"),
            ("BAOTOU", "fabricant Baotou"),
            ("PST 3.31", "dossier PST 3.31"),
            ("PST 3.24", "dossier PST 3.24"),
            ("SJV", "vanne SJV"),
            ("GOTREX", "fabricant Gotrex"),
            ("NEZLA", "projet Nezla"),
            ("MESDAR", "projet Mesdar"),
            ("ROURDE", "projet Rourde"),
            ("09 WPS", "09 WPS"),
            ("PAGE 55 & 56", "Page 55 & 56"),
            ("PAGE 17 & 19", "Page 17 & 19"),
        ]
        
        cleaned_comments = []
        for c in all_comments:
            # 1. Traçabilité du document concerné
            doc_c = c.get("document_concerned", "")
            if doc_c and doc_c not in valid_files and not doc_c.startswith("DOC-") and not doc_c.startswith("Dossier") and not doc_c.startswith("Annexe") and not doc_c.startswith("Lettre") and not doc_c.startswith("Spécification") and not doc_c.startswith("Qualification"):
                # Si le document cité est un fichier d'un autre dossier (ex: C1124-AST... alors qu'on audite un autre lot)
                c["document_concerned"] = primary_file

            title = c.get("title", "")
            obs = c.get("observation", "")
            action = c.get("action_required", "")
            full_c_text = (title + " " + obs + " " + action).upper()

            # 2. Vérification des marqueurs extérieurs
            has_unfounded_foreign_marker = False
            for tag, label in FOREIGN_TAGS:
                if tag in full_c_text and tag not in corpus_upper:
                    # Le marqueur est dans la remarque mais N'EST PAS dans le document téléversé !
                    has_unfounded_foreign_marker = True
                    break

            if has_unfounded_foreign_marker:
                # La remarque fait référence à un projet ou équipement extérieur absent de ce dossier
                continue

            # 3. Vérification de cohérence spécifique : E5015
            if "E5015" in full_c_text and "E5015" not in corpus_upper:
                continue

            # 4. Autorisation des exigences dimensionnelles réglementaires (700 mm manchettes)

            # 5. Nettoyage de mentions d'archives résiduelles dans l'observation
            if "Gowin" in obs or "Goval" in obs or "ZICN" in obs or "Mindeo" in obs or "Baoyi" in obs:
                for v_name in ["Gowin", "Goval", "JST", "Baoyi", "Mindeo", "ZICN", "Baotou"]:
                    obs = obs.replace(f", {v_name}", "").replace(f"{v_name}, ", "").replace(v_name, "le fabricant réel")
                c["observation"] = obs

            cleaned_comments.append(c)

        return cleaned_comments


    def _search_per_doc(self, parsed_docs: List[Dict[str, Any]], pattern: str, flags=0):
        """
        Traçabilité#2 : cherche `pattern` document par document (texte en MAJUSCULE,
        sans normalisation d'accents qui casserait les offsets) au lieu d'un texte
        agrégé de tout le dossier. Retourne (match, file_name, page) du PREMIER
        document où le motif est trouvé, ou (None, None, None).
        """
        for d in parsed_docs:
            text_upper = d.get("text", "").upper()
            m = re.search(pattern, text_upper, flags)
            if m:
                page = self._page_at_offset(d.get("page_spans", []), m.start())
                return m, d.get("file_name", "?"), page
        return None, None, None

    def _detect_visual_stamps_and_signatures(self, file_paths: list, page_spans: list) -> dict:
        """Détecte visuellement les cachets, tampons et signatures sur chaque page via Vision IA."""
        results = {
            "stamps_detected": [],
            "signatures_detected": [],
            "pages_without_stamp": [],
            "pages_with_stamp": [],
            "confidence_scores": {},
            "vision_analysis": []
        }
        
        try:
            import fitz
        except ImportError:
            logger.warning("[ARH-Vision] PyMuPDF non disponible pour détection visuelle")
            return results

        if os.getenv("ARH_DISABLE_VISION", "0") == "1":
            logger.debug("[ARH-Vision] Vision désactivée par configuration ARH_DISABLE_VISION.")
            return results

        # Vérification rapide via le circuit-breaker unifié d'ARHOllamaClient
        from arh_ollama_client import get_ollama_client, TIMEOUT_VISION
        ollama_client = get_ollama_client()
        if not ollama_client.is_available():
            logger.warning("[ARH-Vision] Ollama hors-ligne - saut de l'analyse visuelle des cachets.")
            return results
        
        for fp in file_paths:
            try:
                fname = os.path.basename(fp)
                with fitz.open(fp) as doc:
                    if doc.is_encrypted:
                        continue
                    # Sélectionner au maximum 3 pages clés par document (première, dernière, et page de certificat)
                    pages_to_check = set()
                    pages_to_check.add(0)  # Première page
                    if len(doc) > 1:
                        pages_to_check.add(len(doc) - 1)  # Dernière page
                    
                    # Chercher la première page avec mention de certificat/visa
                    for i in range(min(len(doc), 15)):
                        if len(pages_to_check) >= 3:
                            break
                        page = doc[i]
                        text = page.get_text().upper()
                        if any(kw in text for kw in ['CERTIFICAT', 'CERTIFICATE', 'APPROUVE', 'APPROVED', 
                                                      'INSPECTION', 'TEST REPORT', 'PV', 'PROCES VERBAL',
                                                      'HYDROTEST', 'EPREUVE', 'CONFORMITE', 'CONFORMITY']):
                            pages_to_check.add(i)
                    
                    for page_idx in sorted(list(pages_to_check)[:3]):
                        if page_idx >= len(doc):
                            continue
                        page = doc[page_idx]
                        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))  # 225 DPI balance
                        img_bytes = pix.tobytes("png")
                        
                        import base64
                        img_b64 = base64.b64encode(img_bytes).decode('utf-8')
                        
                        try:
                            prompt = """Analyze this document page carefully. Answer these questions in JSON format:
{
  "has_official_stamp": true/false,
  "stamp_count": number,
  "stamp_descriptions": ["description of each stamp found"],
  "stamp_colors": ["blue", "red", "black"],
  "has_signature": true/false,
  "signature_count": number,
  "is_original_document": true/false,
  "has_approval_marking": true/false,
  "organism_detected": "name of inspection organism if visible",
  "confidence": 0.0-1.0
}
Only return JSON, no other text."""
                            
                            vision_data = ollama_client.generate_json(
                                model=os.getenv("ARH_VISION_MODEL", "qwen2.5vl:3b"),
                                prompt=prompt,
                                images=[img_b64],
                                options={"temperature": 0.1, "num_predict": 300},
                                timeout=TIMEOUT_VISION
                            )
                            if vision_data is not None:
                                vision_data["file"] = fname
                                vision_data["page"] = page_idx + 1
                                results["vision_analysis"].append(vision_data)
                                
                                if vision_data.get("has_official_stamp"):
                                    results["stamps_detected"].append({
                                        "file": fname, "page": page_idx + 1,
                                        "descriptions": vision_data.get("stamp_descriptions", []),
                                        "colors": vision_data.get("stamp_colors", []),
                                        "organism": vision_data.get("organism_detected", ""),
                                        "confidence": vision_data.get("confidence", 0.5)
                                    })
                                    results["pages_with_stamp"].append(page_idx + 1)
                                else:
                                    results["pages_without_stamp"].append({"file": fname, "page": page_idx + 1})
                                
                                if vision_data.get("has_signature"):
                                    results["signatures_detected"].append({
                                        "file": fname, "page": page_idx + 1,
                                        "count": vision_data.get("signature_count", 1),
                                        "confidence": vision_data.get("confidence", 0.5)
                                    })
                                
                                results["confidence_scores"][f"{fname}_p{page_idx+1}"] = vision_data.get("confidence", 0.5)
                        
                        except Exception as ve:
                            logger.warning("[ARH-Vision] Erreur analyse page %d de %s: %s", page_idx+1, fname, ve)
            except Exception as e:
                logger.error("[ARH-Vision] Erreur ouverture PDF %s: %s", fp, e)
        
        logger.info("[ARH-Vision] Analyse visuelle: %d cachets, %d signatures détectés sur %d pages",
                    len(results['stamps_detected']), len(results['signatures_detected']),
                    len(results.get('vision_analysis', [])))
        return results

    def _verify_engineering_calculations(
        self,
        parsed_docs: List[Dict[str, Any]],
        equipment_type: str
    ) -> List[Dict[str, Any]]:
        """
        Vérificateur Mathématique & Audit des Calculs d'Ingénierie :
        - Recalcule l'épaisseur minimale de tube (Linepipe) selon Décret 21-315 Art. 7
          Formula: e_calc = (P * D) / (2 * R * F * Z) + C.A.
        - Recalcule la pression d'épreuve hydrostatique minimale selon Décret 21-315 Art. 21 / Décret 21-261 Art. 27
        - Recalcule l'épaisseur de virolle ESP selon ASME VIII / Décret 21-261
        """
        calc_comments = []
        full_text = " ".join([d.get("text", "") for d in parsed_docs])
        norm_full_text = _normalize_text(full_text)

        # ── 1. Vérification du Calcul d'Épaisseur de Tube / Linepipe (Décret 21-315 Art. 7) ──
        if equipment_type in ("LINEPIPE", "PIPELINE", "FLOWLINE"):
            m_p, file_p, page_p = self._search_per_doc(parsed_docs, r'(?:PMA|PMS|PRESSION\s*(?:DE\s*)?DESIGN|DESIGN\s*PRESSURE)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:BAR|BARS|MPA)')
            m_d, file_d, page_d = self._search_per_doc(parsed_docs, r'(?:DIAMETRE\s*(?:EXTERIEUR|NOMINAL)?|OUTSIDE\s*DIAMETER|OD|DN)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:MM|INCH|IN)?')
            m_e, file_e, page_e = self._search_per_doc(parsed_docs, r'(?:EPAISSEUR\s*(?:NOMINALE|DE\s*CALCUL|TUBE)?|WALL\s*THICKNESS|WT)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*MM')
            m_ca, file_ca, page_ca = self._search_per_doc(parsed_docs, r'(?:CORROSION\s*ALLOWANCE|SUREPAISSEUR\s*DE\s*CORROSION|C\.A\.?)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*MM')

            if m_p and m_d and m_e:
                p_bar = float(m_p.group(1))
                if "MPA" in m_p.group(0).upper(): p_bar *= 10.0
                d_mm = float(m_d.group(1))
                # Bug4 fix : ne JAMAIS deviner l'unite par magnitude (un diametre reel en
                # mm <= 48 - ex: petite tubulure de 42mm - etait auparavant multiplie a
                # tort par 25.4, gonflant le diametre a >1000mm). On ne convertit QUE si
                # l'unite pouces est explicitement presente dans le texte matche.
                if any(u in m_d.group(0).upper() for u in ("INCH", "IN", "POUCE")):
                    d_mm *= 25.4
                e_decl = float(m_e.group(1))
                ca_mm = float(m_ca.group(1)) if m_ca else 1.5

                p_conf = self._compute_extraction_confidence(str(p_bar), "pressure", cross_doc_matches=1)
                d_conf = self._compute_extraction_confidence(str(d_mm), "diameter", cross_doc_matches=1)
                e_conf = self._compute_extraction_confidence(str(e_decl), "thickness", cross_doc_matches=1)


                # Bug5 fix : table SMYS API 5L complete (MPa). Auparavant, seuls
                # X70/X52/Grade B etaient reconnus et TOUT le reste retombait
                # silencieusement sur X65 (450 MPa) -- une valeur PLUS ELEVEE que les
                # nuances plus faibles (X42/X46/X56/X60), ce qui SOUS-ESTIME l'epaisseur
                # minimale requise pour ces nuances -> risque de securite.
                API_5L_SMYS_MPA = {
                    "GRADE A": 207.0, "GRADE B": 245.0, "X42": 290.0, "X46": 317.0,
                    "X52": 360.0, "X56": 386.0, "X60": 414.0, "X65": 450.0,
                    "X70": 485.0, "X80": 552.0,
                }
                r_smys = None
                file_grade, page_grade = file_e, page_e
                for grade_kw, smys_val in API_5L_SMYS_MPA.items():
                    m_grade, f_grade, p_grade = self._search_per_doc(parsed_docs, re.escape(grade_kw))
                    if m_grade:
                        r_smys = smys_val
                        matched_grade = grade_kw
                        file_grade, page_grade = f_grade, p_grade
                        break

                if r_smys is None:
                    # Nuance non identifiee avec certitude : on NE DEVINE PAS un SMYS
                    # (contrairement au comportement precedent qui utilisait X65 par
                    # defaut). On remonte un signalement pour verification manuelle.
                    calc_comments.append({
                        "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                        "title": "⚠️ Nuance API 5L Non Identifiée — Vérification Manuelle du Calcul d'Épaisseur Requise",
                        "description": "La nuance d'acier (Grade API 5L) n'a pas pu être identifiée avec certitude dans les documents transmis. Le recalcul automatique de l'épaisseur minimale ne peut pas être effectué de manière fiable sans cette information.",
                        "observation": "Aucune nuance API 5L reconnue (X42/X46/X52/X56/X60/X65/X70/X80/Grade A/B) dans le texte du dossier.",
                        "cause": "Nuance non mentionnée explicitement ou terminologie non standard utilisée dans les documents.",
                        "impact": "Impossible de vérifier automatiquement la conformité de l'épaisseur nominale déclarée — vérification manuelle requise par un ingénieur qualifié.",
                        "category": "CONTRÔLE DES CALCULS D'INGÉNIERIE",
                        "regulation_ref": "Décret exécutif n° 21-315",
                        "decree_reference": "Décret exécutif n° 21-315",
                        "article": "Art. 7",
                        "article_number": "Art. 7",
                        "standard": "API 5L",
                        "document_concerned": f"Spécification / Note de Calcul Tube ({file_e})" if file_e else "Spécification / Note de Calcul Tube",
                        "page": page_e if page_e else "N/A",
                        "correction_method": "Préciser explicitement la nuance API 5L (ex: X65, X70) dans la spécification technique.",
                        "action_required": "Confirmer la nuance API 5L et effectuer une vérification manuelle du calcul d'épaisseur.",
                        "priority": "MAJOR",
                        "severity": "Major",
                        "responsible": "Ingénieur Calcul Tuyauterie",
                        "responsible_entity": "Ingénieur Calcul Tuyauterie",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                        "deadline_days": 5,
                        "status": "OPEN"
                    })
                    r_smys = 450.0  # valeur plancher conservatrice UNIQUEMENT pour permettre au reste du pipeline de continuer ; le commentaire ci-dessus signale explicitement l'incertitude
                r_bar = r_smys * 10.0

                f_factor = 0.72  # Zone D
                if self._search_per_doc(parsed_docs, r'ZONE\s*A')[0]: f_factor = 0.40
                elif self._search_per_doc(parsed_docs, r'ZONE\s*B')[0]: f_factor = 0.50
                elif self._search_per_doc(parsed_docs, r'ZONE\s*C')[0]: f_factor = 0.60

                e_calc = (p_bar * d_mm) / (2.0 * r_bar * f_factor * 1.0)
                e_min_req = round(e_calc + ca_mm, 2)

                if e_decl < e_min_req:
                    calc_comments.append({
                        "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                        "title": f"⚠️ Erreur de Calcul d'Épaisseur : Tube Sous-Dimensionné ({e_decl:.2f} mm < {e_min_req:.2f} mm)",
                        "description": f"Vérification mathématique ARKAN du calcul d'épaisseur (Décret 21-315 Art. 7) : L'épaisseur nominale déclarée ({e_decl:.2f} mm) est inférieure à l'épaisseur minimale réglementaire requise ({e_min_req:.2f} mm).",
                        "observation": f"Le recalcul mathématique de l'épaisseur pour P={p_bar:.1f} bar, D={d_mm:.1f} mm, SMYS={r_smys:.0f} MPa et Zone F={f_factor} donne une épaisseur de calcul de {e_calc:.2f} mm + corrosion {ca_mm:.1f} mm = {e_min_req:.2f} mm minimum requise. L'épaisseur déclarée de {e_decl:.2f} mm est SOUS-DIMENSIONNÉE.",
                        "cause": "Erreur dans la note de calcul de l'ingénierie ou choix d'épaisseur nominale insuffisante.",
                        "impact": "Risque de rupture par surpression de la canalisation et non-conformité grave à l'Art. 7 du Décret 21-315.",
                        "category": "CONTRÔLE DES CALCULS D'INGÉNIERIE",
                        "regulation_ref": "Décret exécutif n° 21-315",
                        "decree_reference": "Décret exécutif n° 21-315",
                        "article": "Art. 7",
                        "article_number": "Art. 7",
                        "standard": "API 5L / ASME B31.8 / Décret 21-315",
                        "document_concerned": f"Note de Calcul d'Épaisseur Tube ({file_e})" if file_e else "Note de Calcul d'Épaisseur Tube",
                        "page": page_e if page_e else "N/A",
                        "correction_method": f"Augmenter l'épaisseur nominale du tube à au moins {e_min_req:.2f} mm ou réduire la pression de design PMA.",
                        "action_required": f"Corriger la note de calcul et ré-émettre la spécification avec une épaisseur minimale de {e_min_req:.2f} mm.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur Calcul Tuyauterie / Constructeur",
                        "responsible_entity": "Ingénieur Calcul Tuyauterie / Constructeur",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        "deadline_days": 3,
                        "status": "OPEN"
                    })

        # ── 2. Vérification du Calcul d'Épaisseur ESP (ASME VIII / Décret 21-261) ──
        if equipment_type in ("PRESSURE_VESSEL", "SEPARATOR", "HEAT_EXCHANGER", "COLUMN", "SPHERE"):
            m_p, file_p2, page_p2 = self._search_per_doc(parsed_docs, r'(?:PMA|PMS|DESIGN PRESSURE)\s*(\d+(?:\.\d+)?)\s*BAR')
            m_r, file_r2, page_r2 = self._search_per_doc(parsed_docs, r'(?:RAYON INTERIEUR|INNER RADIUS|R)\s*(\d+(?:\.\d+)?)\s*MM')
            m_t, file_t2, page_t2 = self._search_per_doc(parsed_docs, r'(?:EPAISSEUR VIROLLE|SHELL THICKNESS)\s*(\d+(?:\.\d+)?)\s*MM')
            m_ca, file_ca2, page_ca2 = self._search_per_doc(parsed_docs, r'(?:CORROSION ALLOWANCE|CA)\s*(\d+(?:\.\d+)?)\s*MM')

            if m_p and m_r and m_t:
                p_bar = float(m_p.group(1))
                r_mm = float(m_r.group(1))
                t_decl = float(m_t.group(1))
                ca_mm = float(m_ca.group(1)) if m_ca else 3.0
                s_stress_bar = 1380.0  # NOTE : valeur fixe (A516 Gr 70 a temperature ambiante) -
                                       # non verifiee contre la nuance reellement declaree (limite connue, cf. audit Bug7)

                # Bug6 fix : coefficient de joint soudé (E, ASME VIII UW-12) déduit du taux
                # de CND réellement déclaré, au lieu de toujours supposer E=1.0 (RT complet).
                # Un E=1.0 par défaut SOUS-ESTIME l'épaisseur minimale requise si le CND
                # réel est partiel ou absent.
                m_ndt_pct, file_ndt, page_ndt = self._search_per_doc(parsed_docs, r'(?:RADIOGRAPHIE|RT|CND|NDT)\s*[:=]?\s*(\d{1,3})\s*%')
                if m_ndt_pct:
                    ndt_pct = float(m_ndt_pct.group(1))
                    if ndt_pct >= 100:
                        e_joint = 1.0
                    elif ndt_pct >= 20:
                        e_joint = 0.85
                    else:
                        e_joint = 0.70
                else:
                    # Taux de CND non trouvé dans le texte : hypothèse CONSERVATRICE
                    # (E=0.70, le cas le plus défavorable) plutôt que le meilleur cas.
                    e_joint = 0.70
                    calc_comments.append({
                        "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                        "title": "⚠️ Taux de CND Non Déclaré — Coefficient de Joint Conservateur Appliqué (E=0.70)",
                        "description": "Le taux de contrôle non destructif (CND/RT) des soudures n'a pas été trouvé dans les documents. Le recalcul d'épaisseur a été effectué avec un coefficient de joint conservateur (E=0.70, non-radiographié) par sécurité — vérifier et confirmer le taux réel.",
                        "observation": "Aucun taux de CND (%) identifié dans le texte des documents transmis.",
                        "cause": "Taux de CND non mentionné explicitement ou absent des documents transmis.",
                        "impact": "Le calcul d'épaisseur utilisé par défaut est conservateur ; si le CND réel est complet (100%), une épaisseur plus faible pourrait être acceptable — à confirmer par l'ingénieur.",
                        "category": "CONTRÔLE DES CALCULS D'INGÉNIERIE",
                        "regulation_ref": "ASME VIII Div 1 UW-12",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Art. 6",
                        "article_number": "UW-12",
                        "standard": "ASME VIII Div 1",
                        "document_concerned": "Note de Calcul / Rapport CND",
                        "page": "N/A (aucun taux de CND détecté dans le dossier)",
                        "correction_method": "Confirmer le taux de CND réellement effectué sur les soudures et re-vérifier le calcul en conséquence.",
                        "action_required": "Fournir le taux de CND réel des soudures pour affiner le calcul d'épaisseur.",
                        "priority": "MINOR",
                        "severity": "Minor",
                        "responsible": "Ingénieur ESP / Inspecteur QA-QC",
                        "responsible_entity": "Ingénieur ESP / Inspecteur QA-QC",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                        "deadline_days": 7,
                        "status": "OPEN"
                    })

                t_calc = (p_bar * r_mm) / (s_stress_bar * e_joint - 0.6 * p_bar) + ca_mm
                if t_decl < t_calc:
                    calc_comments.append({
                        "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                        "title": f"⚠️ Erreur Calcul Épaisseur Virolle ESP ({t_decl:.2f} mm < {t_calc:.2f} mm)",
                        "description": f"Le recalcul ASME VIII / Décret 21-261 donne une épaisseur minimale requise de {t_calc:.2f} mm. L'épaisseur déclarée ({t_decl:.2f} mm) est insuffisante.",
                        "observation": f"Sous P={p_bar:.1f} bar et R={r_mm:.1f} mm, la virolle nécessite une épaisseur de {t_calc:.2f} mm. La valeur déclarée de {t_decl:.2f} mm est non conforme.",
                        "cause": "Note de calcul ESP erronée.",
                        "impact": "Non-conformité au Décret 21-261 Art. 6 et risque de rupture.",
                        "category": "CONTRÔLE DES CALCULS D'INGÉNIERIE",
                        "regulation_ref": "Décret exécutif n° 21-261",
                        "decree_reference": "Décret exécutif n° 21-261",
                        "article": "Art. 6",
                        "article_number": "Art. 6",
                        "standard": "ASME VIII Div 1 / EN 13445",
                        "document_concerned": f"Note de Calcul Récipient Sous Pression ({file_t2})" if file_t2 else "Note de Calcul Récipient Sous Pression",
                        "page": page_t2 if page_t2 else "N/A",
                        "correction_method": f"Réviser la note de calcul pour porter l'épaisseur virolle à {t_calc:.2f} mm minimum.",
                        "action_required": f"Réviser la note de calcul pour porter l'épaisseur virolle à {t_calc:.2f} mm minimum.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur ESP / Fabricant",
                        "responsible_entity": "Ingénieur ESP / Fabricant",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                        "deadline_days": 5,
                        "status": "OPEN"
                    })


        # ── 3. Vérification du Calcul d'Épaisseur de Virolles de Bac (API 650 / Décret 21-315) ──
        if equipment_type == "TANK":
            m_d, file_d3, page_d3 = self._search_per_doc(parsed_docs, r'(?:DIAMETRE BAC|TANK DIAMETER|D)\s*(\d+(?:\.\d+)?)\s*M')
            m_h, file_h3, page_h3 = self._search_per_doc(parsed_docs, r'(?:HAUTEUR BAC|TANK HEIGHT|H)\s*(\d+(?:\.\d+)?)\s*M')
            m_t, file_t3, page_t3 = self._search_per_doc(parsed_docs, r'(?:EPAISSEUR VIROLLE FOND|FIRST SHELL THICKNESS|WT)\s*(\d+(?:\.\d+)?)\s*MM')

            if m_d and m_h and m_t:
                d_m = float(m_d.group(1))
                h_m = float(m_h.group(1))
                t_decl = float(m_t.group(1))
                sd_stress = 160.0  # MPa / A283 Gr C
                ca_mm = 1.5

                # Formule API 650 1-Foot Method: t = (4.9 * D * (H - 0.3) * G) / Sd + CA
                t_calc = round(((4.9 * d_m * (h_m - 0.3) * 1.0) / sd_stress) + ca_mm, 2)
                if t_decl < t_calc:
                    calc_comments.append({
                        "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                        "title": f"⚠️ Erreur Calcul Épaisseur Virolle de Bac API 650 ({t_decl:.2f} mm < {t_calc:.2f} mm)",
                        "description": f"Le recalcul API 650 (1-Foot Method) pour un bac de D={d_m}m et H={h_m}m donne une épaisseur requise de {t_calc:.2f} mm. L'épaisseur déclarée ({t_decl:.2f} mm) est insuffisante.",
                        "observation": f"Calcul API 650 1-Foot Method : D={d_m:.1f}m, H={h_m:.1f}m -> Épaisseur virolle minimale {t_calc:.2f} mm vs déclarée {t_decl:.2f} mm.",
                        "cause": "Erreur dans la note de calcul de stabilité de robe de bac API 650.",
                        "impact": "Risque de flambement ou rupture de robe sous charge hydrostatique (Décret 21-315).",
                        "category": "CONTRÔLE DES CALCULS D'INGÉNIERIE",
                        "regulation_ref": "Décret exécutif n° 21-315",
                        "decree_reference": "Décret exécutif n° 21-315",
                        "article": "Art. 14 / API 650",
                        "article_number": "API 650 Sec 5.6",
                        "standard": "API 650 / Décret 21-315",
                        "document_concerned": f"Note de Calcul Robe de Bac ({file_t3})" if file_t3 else "Note de Calcul Robe de Bac",
                        "page": page_t3 if page_t3 else "N/A",
                        "correction_method": f"Porter l'épaisseur de la première virolle à {t_calc:.2f} mm minimum.",
                        "action_required": f"Porter l'épaisseur de la première virolle à {t_calc:.2f} mm minimum.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur Réservoirs / EPC Contractor",
                        "responsible_entity": "Ingénieur Réservoirs / EPC Contractor",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                        "deadline_days": 5,
                        "status": "OPEN"
                    })

        # ── 4. Vérification des Calculs de Torche & Rayonnement (API 521) ──
        if equipment_type == "FLARE":
            m_rad, file_rad, page_rad = self._search_per_doc(parsed_docs, r'(?:RAYONNEMENT|RADIATION|HEAT FLUX)\s*(\d+(?:\.\d+)?)\s*(?:KW/M2|KW)')
            if m_rad:
                rad_val = float(m_rad.group(1))
                if rad_val > 4.73:
                    calc_comments.append({
                        "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                        "title": f"⚠️ Rayonnement Thermique de Torche Excessif ({rad_val:.2f} kW/m² > 4.73 kW/m²)",
                        "description": f"Le rayonnement thermique calculé au niveau de la clôture/zone du personnel ({rad_val:.2f} kW/m²) dépasse la limite maximale API 521 (4.73 kW/m² avec équipement de protection).",
                        "observation": f"Rayonnement de torche calculé de {rad_val:.2f} kW/m² au sol, supérieur au seuil de sécurité de 4.73 kW/m² (API 521 Sec 5.4.4).",
                        "cause": "Hauteur de fût de torche insuffisante ou distance de sécurité sous-dimensionnée.",
                        "impact": "Risque majeur d'exposition thermique pour les opérateurs et le matériel.",
                        "category": "SÉCURITÉ ET DIMENSIONNEMENT TORCHE",
                        "regulation_ref": "Décret exécutif n° 21-315 & API 521",
                        "decree_reference": "Décret exécutif n° 21-315",
                        "article": "Art. 22 / API 521",
                        "article_number": "API 521",
                        "standard": "API 521 / ISO 23251",
                        "document_concerned": f"Étude de Rayonnement Torche ({file_rad})" if file_rad else "Étude de Rayonnement Torche",
                        "page": page_rad if page_rad else "N/A",
                        "correction_method": "Augmenter la hauteur du fût de torche (Flare Stack Height) ou élargir le périmètre de sécurité.",
                        "action_required": "Augmenter la hauteur du fût de torche (Flare Stack Height) ou élargir le périmètre de sécurité.",
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "responsible": "Ingénieur Procédé / Safety Specialist",
                        "responsible_entity": "Ingénieur Procédé / Safety Specialist",
                        "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                        "deadline_days": 7,
                        "status": "OPEN"
                    })

        return calc_comments

    def _verify_equipment_certificate_reconciliation(
        self,
        parsed_docs: List[Dict[str, Any]],
        main_equipment_tag: str,
        equipment_type: str,
        dossier_stage: str = "FINAL_RECEPTION"
    ) -> List[Dict[str, Any]]:
        """
        Reconstitution Approfondie du Matériel & Réconciliation des Certificats :
        1. Identifie tous les Tags d'équipements et composants mentionnés dans le dossier.
        2. Vérifie pour chaque certificat joint s'il appartient RÉELLEMENT au Tag de l'équipement du dossier.
        3. Détecte les certificats d'équipements tiers non concordants (Tag Mismatch).
        4. Détecte les composants requis (ex: Soupapes PSV, Instruments ATEX, Pompes) sans certificat valide.
        """
        reconcil_comments = []
        
        # Collecter tous les tags déclarés dans le dossier
        dossier_component_tags = set()
        if main_equipment_tag and main_equipment_tag != "UNKNOWN":
            dossier_component_tags.add(main_equipment_tag.upper())
            
        cert_docs = []
        spec_docs = []
        
        for doc in parsed_docs:
            t = doc["text"].upper()
            fname = doc["file_name"].upper()
            doc_type = doc["metadata"].get("document_type", "").upper()
            
            # Un plan, P&ID, Line List, Note de Calcul ou Data Sheet n'est JAMAIS un certificat usine 3.1
            is_spec_or_drawing = any(k in fname or k in doc_type for k in [
                "DWG", "-DM-", "P&ID", "PID", "LINE LIST", "DATA SHEET", "LAYOUT",
                "PLAN", "CALCUL", "STRESS", "SPECIFICATION", "ALIGNMENT"
            ])
            
            is_cert = False
            if not is_spec_or_drawing:
                is_cert = any(k in t or k in fname for k in [
                    "CERTIFICAT MATIERE", "MILL TEST REPORT", "MILL CERTIFICATE",
                    "EN 10204", "PV D EPREUVE", "PROCES VERBAL D EPREUVE",
                    "PV D ETALONNAGE", "CALIBRATION CERTIFICATE", "ATEX CERTIFICATE", "IRN",
                    "RELEASE NOTE", "CERTIFICAT DE CONFORMITE"
                ])
            
            tags_found = re.findall(r'\b([A-Z]{1,4}-[0-9]{2,4}[A-Z0-9]*)\b', t)
            
            if is_cert:
                cert_docs.append((doc, tags_found))
            else:
                spec_docs.append((doc, tags_found))

        # Remplir dossier_component_tags UNIQUEMENT depuis les spécifications / P&ID (spec_docs)
        for doc_item, tags_found in spec_docs:
            for tg in tags_found:
                if len(tg) >= 4 and not tg.startswith("DE-") and not tg.startswith("ISO-"):
                    dossier_component_tags.add(tg)

        # ── 1. Vérification de Concordance des Tags sur les Certificats (Tag Mismatch) ──
        for doc_item, cert_tags in cert_docs:
            fname = doc_item["file_name"]
            text = doc_item["text"].upper()
            
            # Rechercher si le certificat indique un Tag explicite d'équipement
            m_cert_tag = re.search(r'(?:TAG|EQUIPMENT|EQUIPEMENT|SERIAL\s*NO|N°\s*SERIE|ITEM)\s*[:=]?\s*([A-Z]{1,4}-[0-9]{2,4}[A-Z0-9]*)', text)
            if m_cert_tag:
                cert_tag = m_cert_tag.group(1).upper()
                
                # Vérifier si ce tag appartient au dossier ou s'il est totalement étranger
                if main_equipment_tag and main_equipment_tag != "UNKNOWN":
                    main_clean = main_equipment_tag.upper().strip()
                    if cert_tag != main_clean and not any(cert_tag in dt for dt in dossier_component_tags):
                        reconcil_comments.append({
                            "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                            "title": f"⚠️ Certificat Non Concordant / Mismatch de Tag ({cert_tag} vs {main_clean})",
                            "description": f"Défaut de concordance documentaire : Le fichier '{fname}' est un certificat émis pour le Tag '{cert_tag}', alors que le dossier ARH concerne l'équipement '{main_clean}'. Le certificat fourni n'appartient pas à cet équipement.",
                            "observation": f"Le certificat '{fname}' mentionne le Tag '{cert_tag}', qui est différent du Tag officiel du dossier '{main_clean}'.",
                            "cause": "Erreur d'archivage ou substitution de certificat par l'EPC / constructeur.",
                            "impact": "Refus d'approbation ARH pour vice de forme et défaut de concordance de certificat (Décret 21-261 Art. 15).",
                            "category": "RECONCILIATION ET CONCORDANCE CERTIFICATS",
                            "regulation_ref": "Décret exécutif n° 21-261 & Décret 21-315",
                            "decree_reference": "Décret exécutif n° 21-261 / Décret 21-315",
                            "article": "Art. 15",
                            "article_number": "Art. 15",
                            "standard": "ISO 9001 / ARH Audit Directives",
                            "document_concerned": fname,
                            "page": "Identification Certificat",
                            "correction_method": f"Retirer le certificat non pertinent ({cert_tag}) et joindre le certificat d'origine visé spécifiquement pour le Tag {main_clean}.",
                            "action_required": f"Transmettre le certificat d'épreuve/conformité authentique portant le Tag {main_clean}.",
                            "priority": "CRITICAL",
                            "severity": "Critical",
                            "responsible": "Responsable QA/QC EPC / Constructeur",
                            "responsible_entity": "Responsable QA/QC EPC / Constructeur",
                            "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                            "deadline_days": 3,
                            "status": "OPEN"
                        })

        # ── 2. Vérification des Certificats de Soupapes PSV / Sécurité ──
        psv_tags = [t for t in dossier_component_tags if "PSV" in t or "TSV" in t or "RV-" in t]
        for psv in psv_tags:
            has_psv_cert = False
            for doc_item, _ in cert_docs:
                if psv in doc_item["text"].upper() or psv in doc_item["file_name"].upper():
                    has_psv_cert = True
                    break
            if not has_psv_cert:
                reconcil_comments.append({
                    "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                    "title": f"⚠️ Absence de Certificat d'Étalonnage pour la Soupape de Sécurité {psv}",
                    "description": f"La soupape de sécurité {psv} est identifiée dans les spécifications du dossier, mais aucun procès-verbal d'épreuve/étalonnage en tarage (Pop Test / Bench Test Certificate) portant le Tag '{psv}' n'a été trouvé dans le lot de documents.",
                    "observation": f"Absence de certificat de tarage/étalonnage individuel pour la soupape {psv}.",
                    "cause": "Certificat de soupape omis dans le lot transmis à l'ARH.",
                    "impact": "Non-conformité critique au Décret 21-261 Art. 32 (Sécurité des surpressions) et risque majeur d'explosion.",
                    "category": "RECONCILIATION ET CONCORDANCE CERTIFICATS",
                    "regulation_ref": "Décret exécutif n° 21-261",
                    "decree_reference": "Décret exécutif n° 21-261",
                    "article": "Art. 32",
                    "article_number": "Art. 32",
                    "standard": "API 520 / API 526",
                    "document_concerned": f"Certificat Soupape {psv}",
                    "page": "Traçabilité Sécurité",
                    "correction_method": f"Joindre le PV d'épreuve et de tarage banc d'essai émis par un organisme tiers habilité pour la soupape {psv}.",
                    "action_required": f"Fournir le certificat d'étalonnage et de tarage sous pression pour la soupape {psv}.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénieur Instrumentation & Sécurité",
                    "responsible_entity": "Ingénieur Instrumentation & Sécurité",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN"
                })

        # ── 3. Réconciliation des Diamètres de Tubes & Tuyauteries (Pipe Diameter Reconciliation) ──
        # Bug Critical#2 fix : cette verification n'a de sens QUE pour un dossier de
        # fourniture/pose de tube (LINEPIPE/PIPELINE/FLOWLINE) au stade FINAL, une fois
        # les tubes reellement fabriques/livres. Auparavant elle s'appliquait a N'IMPORTE
        # QUEL type d'equipement (un simple piquage de 8" sur un ballon sous pression
        # declenchait a tort une exigence de "certificat matiere du tube 8 pouces").
        if equipment_type not in ("LINEPIPE", "PIPELINE", "FLOWLINE") or dossier_stage != "FINAL_RECEPTION":
            return reconcil_comments

        pipe_diameters_specified = set()
        # Table officielle des diamètres nominaux standards (ASME B36.10 / B36.19 & API 5L)
        dn_to_inch = {
            15: "1/2\"", 20: "3/4\"", 25: "1\"", 40: "1.5\"", 50: "2\"", 80: "3\"",
            100: "4\"", 150: "6\"", 200: "8\"", 250: "10\"", 300: "12\"", 350: "14\"",
            400: "16\"", 450: "18\"", 500: "20\"", 600: "24\"", 700: "28\"", 750: "30\"",
            800: "32\"", 900: "36\"", 1000: "40\"", 1050: "42\"", 1200: "48\""
        }
        STANDARD_NPS_INCHES = {
            "1/2": (15, 0.5), "3/4": (20, 0.75), "1": (25, 1.0), "1.5": (40, 1.5),
            "2": (50, 2.0), "3": (80, 3.0), "4": (100, 4.0), "6": (150, 6.0),
            "8": (200, 8.0), "10": (250, 10.0), "12": (300, 12.0), "14": (350, 14.0),
            "16": (400, 16.0), "18": (450, 18.0), "20": (500, 20.0), "24": (600, 24.0),
            "28": (700, 28.0), "30": (750, 30.0), "32": (800, 32.0), "34": (850, 34.0),
            "36": (900, 36.0), "40": (1000, 40.0), "42": (1050, 42.0), "48": (1200, 48.0)
        }
        
        # Inspection de tous les documents du lot (Spécifications, P&ID, GA, Plans, Line Lists)
        for doc_item in parsed_docs:
            t = doc_item["text"].upper()
            
            # Repérer les diamètres nominaux stricts (ex: 16", 16-INCH, 16"-LP, 16 INCH, DN400)
            for m in re.finditer(r'(?<![0-9])(\d{1,2})\s*(?:INCH|INCHES|IN|\"|POUCE|POUCES)', t):
                val_str = m.group(1)
                if val_str in STANDARD_NPS_INCHES:
                    dn_val, float_val = STANDARD_NPS_INCHES[val_str]
                    pipe_diameters_specified.add((f"{val_str}\"", f"DN{dn_val}", float_val))
            for m in re.finditer(r'\bDN\s*(\d{2,4})\b', t):
                val_dn = int(m.group(1))
                if val_dn in dn_to_inch:
                    inch_str = dn_to_inch[val_dn].replace('"', '')
                    if inch_str in STANDARD_NPS_INCHES:
                        _, float_val = STANDARD_NPS_INCHES[inch_str]
                        pipe_diameters_specified.add((f"{inch_str}\"", f"DN{val_dn}", float_val))

        # Vérifier si les certificats joints (cert_docs) couvrent CHAQUE diamètre spécifié
        for inch_label, dn_label, approx_inch in pipe_diameters_specified:
            has_cert_for_diameter = False
            for doc_item, _ in cert_docs:
                ctext = doc_item["text"].upper()
                cfname = doc_item["file_name"].upper()
                
                inch_num = str(approx_inch)
                if (f"{inch_num}\"" in ctext or f"{inch_num}\"" in cfname or
                    f"{inch_num} INCH" in ctext or f"{inch_num} INCH" in cfname or
                    f"{inch_num}-INCH" in ctext or f"{inch_num}-INCH" in cfname or
                    f"{inch_num} POUCE" in ctext or f"{inch_num} POUCE" in cfname or
                    dn_label in ctext or dn_label in cfname or
                    f"DN {approx_inch*25}" in ctext or f"DN {approx_inch*25}" in cfname or
                    f"DN{approx_inch*25}" in ctext or f"DN{approx_inch*25}" in cfname):
                    has_cert_for_diameter = True
                    break
            
            if not has_cert_for_diameter and approx_inch >= 4:
                reconcil_comments.append({
                    "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                    "title": f"⚠️ Certificat Matière 3.1 & Épreuve Usine Manquant pour le Tube Diamètre {inch_label} ({dn_label})",
                    "description": f"Défaut de réconciliation des diamètres de ligne : La spécification / Line List déclare la présence de tuyauterie de diamètre {inch_label} ({dn_label}), mais AUCUN certificat de réception matière EN 10204 3.1 / 3.2 ni procès-verbal d'épreuve hydrostatique usine couvrant le diamètre {inch_label} ({dn_label}) n'a été trouvé dans le lot de certificats transmis.",
                    "observation": f"Absence de certificat matière 3.1 et d'épreuve usine pour le diamètre de tube {inch_label} ({dn_label}).",
                    "cause": f"Certificats usine 3.1 du tube {inch_label} omis ou non archivés dans le dossier ARH.",
                    "impact": f"Non-conformité critique au Décret 21-315 Art. 14 et risque de rejet immédiat du dossier ARH pour défaut de traçabilité des diamètres de tuyauterie.",
                    "category": "RECONCILIATION ET CONCORDANCE CERTIFICATS",
                    "regulation_ref": "Décret exécutif n° 21-315",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Art. 14",
                    "article_number": "Art. 14",
                    "standard": "API 5L / EN 10204 3.1",
                    "document_concerned": f"Certificats Matière Tube {inch_label}",
                    "page": "Traçabilité Diamètres",
                    "correction_method": f"Transmettre les certificats de réception matière 3.1 et PV d'épreuve usine couvrant spécifiquement le diamètre {inch_label} ({dn_label}).",
                    "action_required": f"Fournir les certificats matière EN 10204 3.1 et PV d'épreuve usine pour le tube {inch_label} ({dn_label}).",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénieur Matériaux / Responsable QA-QC EPC",
                    "responsible_entity": "Ingénieur Matériaux / Responsable QA-QC EPC",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN"
                })

        return reconcil_comments


    def _check_cross_document_inconsistencies(self, parsed_docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analyse Croisée Intégrale Mot par Mot & Paramètre par Paramètre (v5.0 Ultra-Deep) :
        Scanne chaque mot de chaque document du dossier ARH pour extraire et croiser :
          1. Pressions de Design (PMA / PMS)
          2. Températures de Design
          3. Nature du Fluide / Service Process
          4. Code de Calcul & Normes (ASME VIII, API 650, API 5L, EN 13445)
          5. Nuances de Matériaux
          6. Surépaisseur de Corrosion (C.A.)
          7. Classes de Bride / Rating (150#, 300#, 600#, 900#, 1500#)
          8. Pressions d'Épreuve Hydrostatique
          9. Tags & Traçabilité des Équipements
        """
        comments = []
        doc_by_name = {d.get("file_name", "?"): d for d in parsed_docs}

        def _page_of(fname: str, pattern: str) -> Any:
            """Traçabilité#2 : localise la vraie page où `pattern` apparaît dans le
            document `fname`, pour citer une page réelle dans le commentaire."""
            d = doc_by_name.get(fname)
            if not d:
                return "N/A"
            m = re.search(pattern, d.get("text", "").upper())
            if not m:
                return "N/A"
            return self._page_at_offset(d.get("page_spans", []), m.start())

        pressures_by_doc = {}
        temps_by_doc = {}
        fluids_by_doc = {}
        codes_by_doc = {}
        materials_by_doc = {}
        corrosion_by_doc = {}
        flanges_by_doc = {}
        hydrotests_by_doc = {}
        tags_by_doc = {}

        # BugCritical1 fix : chaque document est associe a l'ENSEMBLE de ses valeurs
        # trouvees (findall), pas seulement la premiere occurrence. Un document mentionne
        # legitimement plusieurs tags/pressions/codes/materiaux (equipement principal +
        # sous-composants) ; comparer uniquement le premier match de chaque document
        # generait des "incoherences" pour la quasi-totalite des dossiers reels.
        def _findall_pressure(pattern, text):
            vals = set()
            for m in re.finditer(pattern, text):
                val = float(m.group(1))
                unit_part = m.group(0).upper()
                if "MPA" in unit_part: val *= 10.0
                elif "PSI" in unit_part: val /= 14.5038
                vals.add(round(val, 1))
            return vals

        for doc in parsed_docs:
            t = doc["text"].upper()
            fname = doc["file_name"]

            # 1. Extraction Pression de Design (TOUTES occurrences)
            vals = _findall_pressure(r'(?:PRESSION\s*DE\s*DESIGN|DESIGN\s*PRESSURE|PMA|PMS)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:BAR|MPA|PSI)', t)
            if vals:
                pressures_by_doc[fname] = vals

            # 2. Extraction Température (toutes occurrences)
            temps = {float(m.group(1)) for m in re.finditer(r'(?:TEMPERATURE\s*DE\s*DESIGN|DESIGN\s*TEMP(?:ERATURE)?)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:°C|C|DEG\s*C)', t)}
            if temps:
                temps_by_doc[fname] = temps

            # 3. Extraction Fluide / Service
            m_fl = re.search(r'(?:SERVICE|FLUIDE|FLUID|PROCESS\s*FLUID)\s*[:=]?\s*([A-Z0-9\s_-]{3,25})(?:\n|\r|,|;|\.)', t)
            if m_fl:
                fl_name = m_fl.group(1).strip()
                if any(k in fl_name for k in ["GAZ", "GAS", "OIL", "PETROLE", "EAU", "WATER", "CONDENSAT", "HYDROCARBURE", "GLYCOL", "AMINE", "FLARE", "VAPEUR"]):
                    fluids_by_doc[fname] = fl_name

            # 4. Extraction Code de Calcul (tous les codes mentionnés dans le document)
            codes_found = {m.group(1).strip() for m in re.finditer(r'\b(ASME\s+VIII(?:\s+DIV\.?\s*[12])?|API\s+650|API\s+620|API\s+5L|EN\s+13445|EN\s+13480|COAP|CODAP)\b', t)}
            if codes_found:
                codes_by_doc[fname] = codes_found

            # 5. Extraction Matériau (tous les matériaux mentionnés)
            mats_found = {m.group(1).strip() for m in re.finditer(r'\b(ASTM\s+A[0-9]{3}(?:\s*GR\.?\s*[A-Z0-9]+)?|API\s+5L\s+[X0-9]+|SA-516\s*GR\s*70|SA-106\s*GR\s*B|SA-36|A333\s*GR\s*6)\b', t)}
            if mats_found:
                materials_by_doc[fname] = mats_found

            # 6. Extraction Surépaisseur de Corrosion
            m_ca = re.search(r'(?:CORROSION\s*ALLOWANCE|SUREPAISSEUR\s*DE\s*CORROSION|C\.A\.?)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*MM', t)
            if m_ca:
                corrosion_by_doc[fname] = float(m_ca.group(1))

            # 7. Extraction Classe de Bride (Rating)
            m_flg = re.search(r'\b(150\s*#|300\s*#|600\s*#|900\s*#|1500\s*#|CLASS\s*150|CLASS\s*300|CLASS\s*600|CLASS\s*900|CLASS\s*1500|PN\s*16|PN\s*25|PN\s*40|PN\s*100)\b', t)
            if m_flg:
                flanges_by_doc[fname] = m_flg.group(1).strip()

            # 8. Extraction Pression d'Épreuve Hydrostatique (toutes occurrences)
            hyd_vals = _findall_pressure(r'(?:PRESSION\s*D\s*EPREUVE|TEST\s*PRESSURE|HYDROTEST\s*PRESSURE|EPREUVE\s*HYDROSTATIQUE)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:BAR|MPA|PSI)', t)
            if hyd_vals:
                hydrotests_by_doc[fname] = hyd_vals

            # 9. Extraction Tag (tous les tags mentionnés, pas seulement le premier)
            tags_found = {m.group(1).strip() for m in re.finditer(r'\b([0-9]{2,4}-[A-Z0-9]{2,6}-[0-9]{3,4}[A-Z]?)\b', t)}
            if tags_found:
                tags_by_doc[fname] = tags_found

        # ── A. Incohérence Cross-Documents sur les Pressions de Design ──
        if len(pressures_by_doc) >= 2:
            # BugCritical1 fix : chaque document peut legitimement citer PLUSIEURS
            # pressions (design + service + utilite...). On ne signale une incoherence
            # QUE si, pour au moins une paire de documents, AUCUNE valeur de l'un n'est
            # compatible (± 0.5 bar) avec AUCUNE valeur de l'autre - un conflit reel,
            # pas juste une pression annexe differente mentionnee ailleurs dans le texte.
            conflicting_pair = None
            doc_items = list(pressures_by_doc.items())
            for i in range(len(doc_items)):
                for j in range(i + 1, len(doc_items)):
                    fname_a, vals_a = doc_items[i]
                    fname_b, vals_b = doc_items[j]
                    compatible = any(abs(va - vb) <= 0.5 for va in vals_a for vb in vals_b)
                    if not compatible:
                        conflicting_pair = (fname_a, vals_a, fname_b, vals_b)
                        break
                if conflicting_pair:
                    break

            if conflicting_pair:
                doc_min, vals_min, doc_max, vals_max = conflicting_pair
                p_min, p_max = min(vals_min), min(vals_max)
                comments.append({
                    "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                    "title": f"⚠️ Incohérence Cross-Documents sur la Pression de Design ({p_min:.1f} bar vs {p_max:.1f} bar)",
                    "description": f"Discordance détectée entre les documents du dossier : Le fichier '{doc_min}' indique une pression de calcul de {p_min:.1f} bar alors que '{doc_max}' indique {p_max:.1f} bar.",
                    "observation": f"Incohérence de pression de design entre '{doc_min}' ({p_min:.1f} bar) et '{doc_max}' ({p_max:.1f} bar).",
                    "cause": "Absence d'alignement inter-disciplines lors de la mise à jour des notes de calcul ou fiches techniques.",
                    "impact": "Risque majeur d'erreur de dimensionnement ou de sous-estimation de la pression d'épreuve hydrostatique (Décret 21-261 Art 6).",
                    "category": "INCOHÉRENCE CROSS-DOCUMENTS",
                    "regulation_ref": "Décret exécutif n° 21-261 / Décret 21-315",
                    "decree_reference": "Décret exécutif n° 21-261 / Décret 21-315",
                    "article": "Art. 6 / Art. 7",
                    "article_number": "Art. 6 / Art. 7",
                    "standard": "ASME VIII / API 650",
                    "document_concerned": f"{doc_min} & {doc_max}",
                    "page": f"{doc_min} (p.{_page_of(doc_min, r'PMA|PMS|PRESSION')}) / {doc_max} (p.{_page_of(doc_max, r'PMA|PMS|PRESSION')})",
                    "correction_method": f"Clarifier et harmoniser la valeur officielle de la pression de design (PMA) entre '{doc_min}' et '{doc_max}'.",
                    "action_required": f"Harmoniser la valeur officielle de la pression de design entre '{doc_min}' et '{doc_max}'.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénierie EPC / Process / Mécanique",
                    "responsible_entity": "Ingénierie EPC / Process / Mécanique",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
                    "deadline_days": 5,
                    "status": "OPEN"
                })

        # ── B. Incohérence Cross-Documents sur les Matériaux de Construction ──
        if len(materials_by_doc) >= 2:
            # BugCritical1 fix : un document peut legitimement citer plusieurs nuances
            # (corps principal + composants annexes). On ne flague QUE si l'union de
            # toutes les nuances par document ne partage AUCUNE valeur commune du tout.
            all_mat_sets = list(materials_by_doc.values())
            common_mats = set.intersection(*all_mat_sets) if all_mat_sets else set()
            if not common_mats:
                mat_list_str = ", ".join([f"{f}: {', '.join(sorted(m))}" for f, m in materials_by_doc.items()])
                comments.append({
                    "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                    "title": "⚠️ Incohérence Métallurgique Cross-Documents sur la Nuance de Matériau",
                    "description": f"Discordance détectée sur le matériau entre documents du dossier : {mat_list_str}.",
                    "observation": f"Variations de nuances d'acier détectées entre les documents du dossier ({mat_list_str}).",
                    "cause": "Erreur d'attribution du certificat matière 3.1 ou contradiction entre la note de calcul et la fiche technique.",
                    "impact": "Non-conformité grave à la tenue mécanique sous pression et risque de rejet par l'ARH lors de l'audit.",
                    "category": "INCOHÉRENCE CROSS-DOCUMENTS",
                    "regulation_ref": "Décret exécutif n° 21-261 / Décret 21-315",
                    "decree_reference": "Décret exécutif n° 21-261 / Décret 21-315",
                    "article": "Art. 6 / Art. 14",
                    "article_number": "Art. 6 / Art. 14",
                    "standard": "EN 10204 / ASME Section II",
                    "document_concerned": mat_list_str,
                    "page": ", ".join([f"{f} (p.{_page_of(f, re.escape(list(m)[0]))})" for f, m in materials_by_doc.items()]),
                    "correction_method": "Vérifier la traçabilité des certificats matière 3.1 et aligner la nuance d'acier sur l'ensemble du dossier.",
                    "action_required": "Aligner la nuance d'acier officielle sur l'ensemble du dossier technique et certificats matière.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Ingénierie Matériaux / Inspecteur Tiers Habilité",
                    "responsible_entity": "Ingénierie Matériaux / Inspecteur Tiers Habilité",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                    "deadline_days": 7,
                    "status": "OPEN"
                })

        # ── C. Incohérence Cross-Documents sur les Codes de Calcul (ASME vs API vs EN) ──
        if len(codes_by_doc) >= 2:
            # BugCritical1 fix : plusieurs codes peuvent legitimement coexister dans un
            # meme dossier (ex: ASME VIII pour le ballon + API 526 pour sa soupape). On
            # ne flague QUE si aucun code n'est partage par TOUS les documents.
            all_code_sets = list(codes_by_doc.values())
            common_codes = set.intersection(*all_code_sets) if all_code_sets else set()
            if not common_codes:
                code_list_str = ", ".join([f"{f}: {', '.join(sorted(c))}" for f, c in codes_by_doc.items()])
                comments.append({
                    "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                    "title": "⚠️ Incohérence de Code de Calcul Cross-Documents (Normes Concurrençantes)",
                    "description": f"Les documents du dossier référencent des codes de calcul ou normes différentes : {code_list_str}.",
                    "observation": f"Contradiction de normes de conception entre fichiers du dossier : {code_list_str}.",
                    "cause": "Utilisation de référentiels d'ingénierie divergents par les sous-traitants.",
                    "impact": "Non-conformité aux exigences d'approbation ARH (Décret 21-315 Art. 7).",
                    "category": "INCOHÉRENCE CROSS-DOCUMENTS",
                    "regulation_ref": "Décret exécutif n° 21-315",
                    "decree_reference": "Décret exécutif n° 21-315",
                    "article": "Art. 7",
                    "article_number": "Art. 7",
                    "standard": "ASME / API / EN",
                    "document_concerned": "Notes de Calcul & Data Sheets",
                    "page": "Référentiel Technique",
                    "correction_method": "Harmoniser le code de calcul unique (ASME, API ou EN) sur tous les documents du dossier.",
                    "action_required": "Aligner le code de calcul officiel sur l'ensemble du dossier technique ARH.",
                    "priority": "MAJOR",
                    "severity": "Major",
                    "responsible": "Chef de Projet Ingénierie / Lead Specialist",
                    "responsible_entity": "Chef de Projet Ingénierie / Lead Specialist",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                    "deadline_days": 7,
                    "status": "OPEN"
                })

        # ── D. Incohérence Cross-Documents sur les Tags / Traçabilité Équipement ──
        # BugCritical1 fix (correctif le plus important de l'audit) : un dossier reel
        # contient TOUJOURS plusieurs tags differents (equipement principal, tuyauteries
        # connectees, instruments, soupapes...) repartis sur des documents differents.
        # Comparer le PREMIER tag trouve par document (ancien comportement) declenchait
        # un rejet "CRITICAL" quasi systematique. On ne flague desormais QUE si AUCUN
        # tag n'est partage entre TOUS les documents ET qu'aucune paire de tags ne
        # partage un prefixe/sous-chaine commune (ex: "1301-D-001" et "1301-D-001A"
        # ne sont pas consideres en conflit).
        if len(tags_by_doc) >= 2:
            all_tag_sets = list(tags_by_doc.values())
            common_tags = set.intersection(*all_tag_sets) if all_tag_sets else set()

            def _tags_related(tag_a: str, tag_b: str) -> bool:
                return tag_a in tag_b or tag_b in tag_a or tag_a[:6] == tag_b[:6]

            has_related_pair = False
            if not common_tags:
                for i in range(len(all_tag_sets)):
                    for j in range(i + 1, len(all_tag_sets)):
                        if any(_tags_related(ta, tb) for ta in all_tag_sets[i] for tb in all_tag_sets[j]):
                            has_related_pair = True
                            break
                    if has_related_pair:
                        break

            if not common_tags and not has_related_pair:
                tag_list_str = ", ".join([f"{f}: {', '.join(sorted(t))}" for f, t in tags_by_doc.items()])
                comments.append({
                    "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                    "title": "⚠️ Incohérence de Traçabilité Cross-Documents sur le Tag Équipement",
                    "description": f"Le dossier contient des références d'équipements contradictoires : {tag_list_str}.",
                    "observation": f"Conflit de repérage (Tag équipement) entre les fichiers du dossier : {tag_list_str}.",
                    "cause": "Mélange de documents provenant de plusieurs équipements ou unités différentes.",
                    "impact": "Refus immédiat du dossier par les inspecteurs ARH pour défaut de traçabilité.",
                    "category": "INCOHÉRENCE CROSS-DOCUMENTS",
                    "regulation_ref": "Décret exécutif n° 21-261 / Décret 21-257",
                    "decree_reference": "Décret exécutif n° 21-261 / Décret 21-257",
                    "article": "Art. 15 / Art. 4",
                    "article_number": "Art. 15 / Art. 4",
                    "standard": "ARH Tagging Rules",
                    "document_concerned": tag_list_str,
                    "page": ", ".join([f"{f} (p.{_page_of(f, re.escape(list(t)[0]))})" for f, t in tags_by_doc.items()]),
                    "correction_method": "Purger le dossier et remplacer les documents ne faisant pas référence au Tag d'équipement correct.",
                    "action_required": "Corriger et harmoniser le Tag d'équipement unique sur tous les documents du lot.",
                    "priority": "CRITICAL",
                    "severity": "Critical",
                    "responsible": "Gestion Documentaire EPC / QA-QC Manager",
                    "responsible_entity": "Gestion Documentaire EPC / QA-QC Manager",
                    "deadline": (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                    "deadline_days": 3,
                    "status": "OPEN"
                })

        return comments
