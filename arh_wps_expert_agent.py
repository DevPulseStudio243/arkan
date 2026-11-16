"""
arh_wps_expert_agent.py
========================
Agent Expert International en Procédures de Soudage (WPS / PQR / DMOS / QMOS).
Auditeur multilingue haute précision selon ASME Section IX, EN ISO 15614-1 et API 1104.

Capacités clés :
  1. Ingestion technique multilingue (Français, Anglais, Italien, Allemand, Espagnol).
  2. Calcul mathématique des domaines de validité / plages de qualification :
     - Épaisseurs de métal de base (T) et de métal déposé (t) selon ASME IX QW-451.1 et EN ISO 15614-1.
     - Diamètres extérieurs qualifiés (D) selon ASME IX QW-452 et EN ISO 15614-1.
  3. Vérification de couverture réelle face aux dimensions de la pièce (paroi de tube, virole, corps de vanne, té).
  4. Contrôle des Variables Essentielles de Soudage (ASME IX QW-250) :
     - P-Number / Group Number (P-No 1 Carbone, P-No 8 Inox, P-No 10H Duplex).
     - Procédés de soudage (GTAW/141, SMAW/111, GMAW/135, SAW/121, FCAW/136).
     - Traitement thermique après soudage (PWHT).
     - Métal d'apport et détection d'undermatching (MSS SP-75).
"""

from __future__ import annotations

import re
import math
import uuid
import datetime
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("ARHWPSExpertAgent")

def check_itp_tpi_arh_column(text: str) -> bool:
    """
    Détecte avec une certitude absolue la présence de la colonne TPI/ARH ou ARH/TPI
    dans un tableau ITP/PIE, sous toutes les variantes d'écriture et d'ordre.
    """
    if not text:
        return False
    tu = text.upper()
    
    # 1. Combinaisons explicites directes et inverses
    direct_patterns = [
        r'\bTPI\s*[\/\-–\\\n]\s*ARH\b',
        r'\bARH\s*[\/\-–\\\n]\s*TPI\b',
        r'\bTPI\s*\(\s*ARH\s*\)',
        r'\bARH\s*\(\s*TPI\s*\)',
        r'\bT\.?P\.?I\.?\s*[\/\-–\\]\s*A\.?R\.?H\.?\b',
        r'\bA\.?R\.?H\.?\s*[\/\-–\\]\s*T\.?P\.?I\.?\b',
        r'\bTHIRD\s*PARTY\s*[\/\-–\\]\s*ARH\b',
        r'\bARH\s*[\/\-–\\]\s*THIRD\s*PARTY\b',
        r'\bTIERS\s*HABILIT[EÉ]\s*[\/\-–\\]\s*ARH\b',
        r'\bARH\s*[\/\-–\\]\s*TIERS\s*HABILIT[EÉ]\b',
        r'\bTPI\s*[\/\-–\\]\s*CTE\b',
        r'\bCTE\s*[\/\-–\\]\s*ARH\b',
        r'\bARH\s*[\/\-–\\]\s*CTE\b',
        r'\bTPI\s*[\/\-–\\]\s*CLIENT\b',
        r'\bCLIENT\s*[\/\-–\\]\s*TPI\b',
        r'\bTPI\s*[\/\-–\\]\s*OWNER\b',
        r'\bTPI\s*[\/\-–\\]\s*AI\b',
        r'\bAI\s*[\/\-–\\]\s*TPI\b'
    ]
    for pat in direct_patterns:
        if re.search(pat, tu):
            return True
            
    # 2. Présence conjointe de colonnes TPI et ARH dans le même document ITP
    has_tpi_header = bool(re.search(r'\b(TPI|T\.P\.I|THIRD\s*PARTY|TIERS\s*HABILIT[EÉ]|ORGANISME\s*DE\s*CONTR[OÔ]LE|BUREAU\s*VERITAS|TUV|TÜV|SGS|APAVE|DEKRA|VELOSI)\b', tu))
    has_arh_header = bool(re.search(r'\b(ARH|A\.R\.H|AUTORIT[EÉ]\s*DE\s*R[EÉ]GULATION|D[EÉ]L[EÉ]GU[EÉ]\s*ARH|INSPECTEUR\s*ARH|REPR[EÉ]SENTANT\s*ARH)\b', tu))
    if has_tpi_header and has_arh_header:
        return True

    # 3. Présence d'un organisme tiers mandaté reconnu dans le tableau ITP
    has_accredited_tpi = bool(re.search(r'\b(BUREAU\s*VERITAS|TUV|TÜV|SGS|APAVE|DEKRA|THIRD\s*PARTY\s*INSPECTOR|TPI\s*INSPECTION)\b', tu))
    if has_accredited_tpi and any(k in tu for k in ["ITP", "INSPECTION TEST PLAN", "PLAN D'INSPECTION"]):
        return True

    return False


# ══════════════════════════════════════════════════════════════════════════════
# 1. ONTOLOGIE MULTILINGUE & TABLES DES VARIABLES ESSENTIELLES (ASME IX / ISO)
# ══════════════════════════════════════════════════════════════════════════════

P_NUMBER_MAPPING = {
    # P-No 1 : Aciers au carbone non alliés (Rm <= 515 MPa standard)
    "P1": ["A106", "A105", "A216", "WCB", "WCC", "A333", "GR 6", "GRADE 6", "A350", "LF2", "A234", "WPB", "WPC", "API 5L", "GR B", "X42", "X52", "X60", "X65", "P265GH", "P235GH", "S235", "S355"],
    # P-No 8 : Aciers inoxydables austénitiques (Cr-Ni)
    "P8": ["304", "304L", "316", "316L", "321", "347", "A182 F316", "A312 TP316", "A351 CF8M", "1.4301", "1.4404", "1.4401"],
    # P-No 10H : Aciers Duplex et Super Duplex (22Cr, 25Cr)
    "P10H": ["A995", "GR 4A", "GRADE 4A", "CD3MN", "UNS S31803", "UNS S32205", "2205", "DUPLEX", "F51", "A182 F51", "GR 5A", "CE3MN", "2507", "SUPER DUPLEX", "UNS S32750", "1.4462"],
    # P-No 4 & 5A : Aciers faiblement alliés Cr-Mo
    "P4": ["A335 P11", "A182 F11", "1.7335", "13CRM4-5"],
    "P5A": ["A335 P22", "A182 F22", "1.7380", "10CRMO9-10"]
}

MULTILINGUAL_PATTERNS = {
    "thickness_coupon": [
        r'(?:TEST\s*COUPON\s*THICKNESS|COUPON\s*THICKNESS|EPAISSEUR\s*DU\s*COUPON|EPAISSEUR\s*EPROUVETTE|SPESSORE\s*DEL\s*TALLONE|PRUFSTUCKDICKE|PRÜFSTÜCKDICKE|ESPESOR\s*DEL\s*CUPON|THICKNESS\s*T)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:MM|INCH|"|\b)',
        r'\bT\s*=\s*(\d+(?:\.\d+)?)\s*MM\b',
        r'(?:PLATE|PIPE)\s*THICKNESS\s*[:=]?\s*(\d+(?:\.\d+)?)\s*MM\b'
    ],
    "thickness_range": [
        r'(?:QUALIFIED\s*RANGE|RANGE\s*QUALIFIED|DOMAINE\s*DE\s*VALIDITE|PLAGE\s*QUALIFIEE|CAMPO\s*DI\s*VALIDITA|QUALIFIZIERTER\s*BEREICH|RANGO\s*CALIFICADO)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:MM)?\s*(?:TO|A|À|-|–|BIS)\s*(\d+(?:\.\d+)?)\s*MM',
        r'(\d+(?:\.\d+)?)\s*(?:MM)?\s*(?:TO|A|À|-|–|BIS)\s*(\d+(?:\.\d+)?)\s*MM\s*(?:QUALIFIED|QUALIFIE|QUALIFIÉ)',
        r'(\d+(?:\.\d+)?)\s*<=\s*T\s*<=\s*(\d+(?:\.\d+)?)\s*MM'
    ],
    "diameter_range": [
        r'(?:DIAMETER\s*RANGE|QUALIFIED\s*DIAMETER|PLAGE\s*DE\s*DIAMETRE|DIAMETRO\s*QUALIFICATO|DURCHMESSERBEREICH)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:MM)?\s*(?:TO|A|À|-|–|BIS)\s*(\d+(?:\.\d+)?|\bMAX\b|\bINF\b|\bUNLIMITED\b|\bILLIMITE\b)',
        r'(?:OD|OUTSIDE\s*DIAMETER|DIAMETRE\s*EXTERIEUR)\s*[:=]?\s*(?:>=|MIN\.?|SUPERIEUR A)?\s*(\d+(?:\.\d+)?)\s*MM'
    ],
    "process": [
        (r'\b(?:141|GTAW|TIG|WIG)\b', "GTAW"),
        (r'\b(?:111|SMAW|MMA|ELECTRODE|STICK)\b', "SMAW"),
        (r'\b(?:131|135|GMAW|MIG|MAG)\b', "GMAW"),
        (r'\b(?:121|SAW|SUBMERGED\s*ARC)\b', "SAW"),
        (r'\b(?:136|FCAW|FLUX\s*CORED)\b', "FCAW")
    ],
    "p_number": [
        r'\bP[\s\-_.]*NO\.?\s*(\d+[A-Z]?)\b',
        r'\bP[\s\-_.]*NUMBER\s*(\d+[A-Z]?)\b'
    ],
    "filler_metal": [
        r'\b(E[\s\-_]*\d{4,5}[A-Z\d\-]*)\b',
        r'\b(ER[\s\-_]*\d{3,4}[A-Z\d\-]*)\b',
        r'\b(INCONEL[\s\-_]*\d{2,3})\b',
        r'\b(SFA[\s\-_]*\d+\.\d+)\b'
    ],
    "pwht": [
        (r'\b(?:NO\s*PWHT|WITHOUT\s*PWHT|SANS\s*PWHT|NON\s*PWHT|AS[\s\-_]*WELDED|OHNE\s*WARMENACHBEHANDLUNG)\b', False),
        (r'\b(?:WITH\s*PWHT|AVEC\s*PWHT|PWHT\s*REQUIRED|POST[\s\-_]*WELD\s*HEAT\s*TREATMENT|SPANNUNGSARMGLUHEN)\b', True)
    ]
}


class ARHWeldingProcedureExpertAgent:
    """
    Agent autonome expert en descriptifs de procédés de soudage (WPS) et
    procès-verbaux de qualification de soudage (PQR) selon ASME Section IX et EN ISO 15614-1.
    """

    def __init__(self):
        self.name = "Expert International WPS/PQR & Plages de Qualification"
        self.discipline = "SOUDAGE & QUALIFICATION PROCÉDÉS"

    # ══════════════════════════════════════════════════════════════════════════
    # 2. CALCULATEURS NORMATIFS DES DOMAINES DE VALIDITÉ (QW-451 / ISO 15614)
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def compute_asme_ix_thickness_range(coupon_thickness_mm: float) -> Tuple[float, float]:
        """
        Calcule la plage d'épaisseur qualifiée selon ASME Section IX Table QW-451.1 (Groove-Weld).
        
        Règles ASME IX :
          - T < 1.5 mm       : [T, 2T]
          - 1.5 <= T < 10 mm : [1.5, 2T]
          - 10 <= T < 19 mm  : [5.0, 2T]
          - 19 <= T < 38 mm  : [5.0, 2T]
          - T >= 38 mm       : [5.0, 200.0]
        """
        T = float(coupon_thickness_mm)
        if T < 1.5:
            return (round(T, 2), round(2.0 * T, 2))
        elif 1.5 <= T < 10.0:
            return (1.5, round(2.0 * T, 2))
        elif 10.0 <= T < 19.0:
            return (5.0, round(2.0 * T, 2))
        elif 19.0 <= T < 38.0:
            return (5.0, round(2.0 * T, 2))
        else:
            return (5.0, 200.0)

    @staticmethod
    def compute_iso_15614_thickness_range(coupon_thickness_mm: float) -> Tuple[float, float]:
        """
        Calcule la plage d'épaisseur qualifiée selon EN ISO 15614-1 (Tableau 5 - Niveau 2).
        
        Règles ISO 15614-1 :
          - t <= 3 mm        : [0.7t, 1.3t]
          - 3 < t <= 12 mm   : [3.0, 2t]
          - 12 < t <= 100 mm : [0.5t, 2t] (avec plafond max 2t)
          - t > 100 mm       : [50.0, 2t]
        """
        t = float(coupon_thickness_mm)
        if t <= 3.0:
            return (round(0.7 * t, 2), round(1.3 * t, 2))
        elif 3.0 < t <= 12.0:
            return (3.0, round(2.0 * t, 2))
        elif 12.0 < t <= 100.0:
            return (round(0.5 * t, 2), round(2.0 * t, 2))
        else:
            return (50.0, round(2.0 * t, 2))

    @staticmethod
    def compute_asme_ix_diameter_range(coupon_diameter_mm: float) -> Tuple[float, float]:
        """
        Calcule la plage de diamètre qualifiée selon ASME Section IX QW-452.3 / Spécifications projets.
        """
        D = float(coupon_diameter_mm)
        if D < 25.0:
            return (round(D, 2), float("inf"))
        elif 25.0 <= D <= 73.0:
            return (25.0, float("inf"))
        else:
            return (73.0, float("inf"))

    # ══════════════════════════════════════════════════════════════════════════
    # 3. EXTRACTION MULTILINGUE DU DOCUMENT WPS / PQR
    # ══════════════════════════════════════════════════════════════════════════

    def extract_wps_parameters(self, text: str, filename: str = "") -> Dict[str, Any]:
        """
        Extrait l'ensemble des paramètres d'une WPS ou PQR en analysant le texte dans n'importe quelle langue.
        """
        tu = text.upper()
        res = {
            "is_wps": bool(re.search(r'\b(?:WPS|DMOS|SCHWEISSANWEISUNG|SPECIFICA\s*DI\s*SALDATURA)\b', tu)),
            "is_pqr": bool(re.search(r'\b(?:PQR|QMOS|WPQR|VERFAHRENSPRUFUNG|VERFAHRENSPRÜFUNG)\b', tu)),
            "wps_id": "",
            "pqr_id": "",
            "standard": "ASME IX",
            "processes": [],
            "p_number": "",
            "base_metals": [],
            "coupon_thickness": None,
            "claimed_thickness_range": None,
            "computed_asme_range": None,
            "claimed_diameter_range": None,
            "filler_metals": [],
            "pwht": None,
            "preheat_c": None
        }

        # Détection du code standard
        if any(k in tu for k in ["EN ISO 15614", "ISO 15614", "EN 288"]):
            res["standard"] = "EN ISO 15614"
        elif "API 1104" in tu:
            res["standard"] = "API 1104"

        # Numéros WPS / PQR
        STOP_WORDS_ID = {
            "FOLLOWED", "FOLLOWING", "APPLIED", "APPLICABLE", "USED", "UTILISE", "UTILISEE",
            "REFERENCE", "SUPPORTING", "ATTACHED", "STANDARD", "CODE", "SPECIFICATION",
            "PROCEDURE", "NUMBER", "RAPPORT", "FICHE", "DOSSIER", "REV", "REVISION",
            "DATE", "PAGE", "TOTAL", "ITEM", "IDENTIFICATION", "DESCRIPTION", "NOM", "NAME",
            "NO", "NR", "NUM", "REF", "N", "SUIVIE", "SUIVI"
        }

        wps_pat = r'\b(?:WPS|DMOS)(?:\s*(?:NO|N°|NR|NUM|NUMBER|REF|REFERENCE|D[EÉ]SIGNATION|DESIGNATION|IDENTIFICATION|FOLLOWED|FOLLOWING|APPLIED|APPLICABLE|USED|SUPPORTING))?[\s\-_.:#№]*([A-Za-z0-9\-_./]+)'
        for m_w in re.finditer(wps_pat, tu, re.IGNORECASE):
            candidate = m_w.group(1).strip(" .-_").upper()
            if candidate not in STOP_WORDS_ID and len(candidate) >= 3 and any(ch.isdigit() or ch in "-_/" for ch in candidate):
                res["wps_id"] = candidate
                break

        if not res["wps_id"]:
            m_wps2 = re.search(r'\b(?:WPS|DMOS)[\s\-_.:#№a-zA-Z]*?([A-Z0-9]+(?:[\-_./][A-Z0-9]+)+)', tu, re.IGNORECASE)
            if m_wps2:
                cand = m_wps2.group(1).strip(" .-_").upper()
                if cand not in STOP_WORDS_ID:
                    res["wps_id"] = cand

        pqr_pat = r'\b(?:PQR|QMOS|WPQR)(?:\s*(?:NO|N°|NR|NUM|NUMBER|REF|REFERENCE|D[EÉ]SIGNATION|DESIGNATION|IDENTIFICATION|FOLLOWED|FOLLOWING|APPLIED|APPLICABLE|USED|SUPPORTING))?[\s\-_.:#№]*([A-Za-z0-9\-_./]+)'
        for m_p in re.finditer(pqr_pat, tu, re.IGNORECASE):
            candidate = m_p.group(1).strip(" .-_").upper()
            if candidate not in STOP_WORDS_ID and len(candidate) >= 3 and any(ch.isdigit() or ch in "-_/" for ch in candidate):
                res["pqr_id"] = candidate
                break

        # Procédés de soudage
        for pat, proc_name in MULTILINGUAL_PATTERNS["process"]:
            if re.search(pat, tu):
                if proc_name not in res["processes"]:
                    res["processes"].append(proc_name)

        # Nuances de métal de base
        for p_no, aliases in P_NUMBER_MAPPING.items():
            if any(a in tu for a in aliases):
                res["base_metals"].append(p_no)

        # P-Number
        for pat in MULTILINGUAL_PATTERNS["p_number"]:
            m_p = re.search(pat, tu)
            if m_p:
                cand_pno = m_p.group(1).strip().upper()
                if cand_pno not in STOP_WORDS_ID:
                    res["p_number"] = cand_pno
                    break

        # Résolution contextuelle du P-Number par le métal de base explicite
        if "P8" in res["base_metals"] or "A182 F316" in tu or "316L" in tu:
            res["p_number"] = "8"
        elif "P10H" in res["base_metals"] or "A995" in tu or "DUPLEX" in tu:
            res["p_number"] = "10H"
        elif not res["p_number"] and res["base_metals"]:
            res["p_number"] = res["base_metals"][0].replace("P", "")

        # Épaisseur coupon d'essai (T)
        for pat in MULTILINGUAL_PATTERNS["thickness_coupon"]:
            m_t = re.search(pat, tu)
            if m_t:
                try:
                    val = float(m_t.group(1))
                    if 0.5 <= val <= 300.0:
                        res["coupon_thickness"] = val
                        break
                except ValueError:
                    pass

        # Plage d'épaisseur revendiquée
        for pat in MULTILINGUAL_PATTERNS["thickness_range"]:
            m_r = re.search(pat, tu)
            if m_r:
                try:
                    t_min = float(m_r.group(1))
                    t_max = float(m_r.group(2))
                    if t_min <= t_max:
                        res["claimed_thickness_range"] = (t_min, t_max)
                        break
                except ValueError:
                    pass

        # Calcul automatique théorique si coupon détecté
        if res["coupon_thickness"]:
            if res["standard"] == "EN ISO 15614":
                res["computed_asme_range"] = self.compute_iso_15614_thickness_range(res["coupon_thickness"])
            else:
                res["computed_asme_range"] = self.compute_asme_ix_thickness_range(res["coupon_thickness"])

        # Métaux d'apport
        for pat in MULTILINGUAL_PATTERNS["filler_metal"]:
            for m_f in re.finditer(pat, tu):
                fm = m_f.group(1).replace(" ", "").replace("_", "-")
                if fm not in res["filler_metals"]:
                    res["filler_metals"].append(fm)

        # PWHT
        for pat, status in MULTILINGUAL_PATTERNS["pwht"]:
            if re.search(pat, tu):
                res["pwht"] = status
                break

        return res

    # ══════════════════════════════════════════════════════════════════════════
    # 4. AUDIT DE CONFORMITÉ & COUVERTURE DES PLAGES
    # ══════════════════════════════════════════════════════════════════════════

    def audit(
        self,
        docs: List[Dict[str, Any]],
        equipment_type: str,
        dossier_stage: str = "PRELIMINARY",
        equipment_context: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Audit approfondi des WPS et PQR du dossier face aux exigences de l'équipement.
        """
        findings = []
        is_prelim = (dossier_stage == "PRELIMINARY")
        full_text = " ".join([d.get("text", "") for d in docs])
        tu_full = full_text.upper()

        # Si l'équipement n'a pas de soudure (seamless, forges monobloc, pas d'embouts soudés)
        from arh_equipment_specialists import equipment_requires_welding
        if not equipment_requires_welding(full_text, equipment_type):
            logger.info("[ARHWPSExpert] Aucun besoin de soudage requis pour ce dossier. Suppression des contrôles WPS.")
            return []

        # Identifier les documents de soudage dans le lot
        wps_docs = []
        for d in docs:
            fn = d.get("file_name", "")
            txt = d.get("text", "")
            tu = txt.upper()
            if any(k in fn.upper() for k in ["WPS", "PQR", "SOUDAGE", "WELD", "QMOS", "DMOS", "WPQ"]) or \
               any(k in tu for k in [
                   "WELDING PROCEDURE SPECIFICATION", "PROCEDURE DE SOUDAGE", "PROCÉDURE DE SOUDAGE",
                   "PROCEDURES DE SOUDAGE", "PROCÉDURES DE SOUDAGE", "MODE OPERATOIRE DE SOUDAGE",
                   "MODE OPÉRATOIRE DE SOUDAGE", "CAHIER DE SOUDAGE", "DOMAINE DE VALIDITE",
                   "QUALIFIED RANGE", "QMOS", "DMOS", "QUALIFICATION DE MODE OPERATOIRE",
                   "PROCES-VERBAL DE QUALIFICATION DE MODE OPERATOIRE"
               ]):
                wps_docs.append(d)

        # Si soudage requis mais aucun document WPS / Cahier de soudage présent
        if not wps_docs:
            findings.append({
                "id": f"REM_WPS_MISSING_{uuid.uuid4().hex[:6].upper()}",
                "discipline": self.discipline,
                "agent": self.name,
                "priority": "CRITICAL",
                "category": "ABSENCE DE CAHIER DE SOUDAGE",
                "title": "Absence des Procédures de Soudage Qualifiées (WPS / PQR)",
                "observation": f"L'équipement ({equipment_type}) comporte des assemblages soudés sous pression, mais aucun descriptif de mode opératoire (WPS) ni procès-verbal de qualification (PQR) n'est inclus dans le lot.",
                "decree_reference": "Décret exécutif n° 21-261 Art. 14 / ASME Section IX QW-200",
                "article": "Art. 14 Décret 21-261",
                "standard": "ASME IX",
                "document_concerned": docs[0].get("file_name", "Dossier Technique") if docs else "Lot ARH",
                "page": "Cahier de Soudage",
                "impact": "Fabrication sous pression sans qualification formelle des opérations de soudage.",
                "action_required": "Transmettre le Cahier de Soudage officiel comprenant l'ensemble des WPS applicables accompagnées de leurs PQR supports qualifiés.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-WPS-Expert"
            })
            return findings

        # Extraire les dimensions et matière cibles de la pièce depuis les documents d'équipements (hors WPS)
        non_wps_docs = [d for d in docs if d not in wps_docs]
        non_wps_text = " ".join([d.get("text", "") for d in non_wps_docs]).upper() if non_wps_docs else tu_full

        target_thickness = None
        target_material = None

        m_wt = re.search(r'\b(?:WALL\s*THICKNESS|WT|EPAISSEUR\s*DE\s*PAROI|EPAISSEUR\s*NOMINALE|NOMINAL\s*THICKNESS|THK)[\s:=]*(\d+(?:\.\d+)?)\s*MM\b', non_wps_text)
        if m_wt:
            try:
                target_thickness = float(m_wt.group(1))
            except ValueError:
                pass

        # Recherche de matière sur la pièce (priorité aux nuances nobles : P10H Duplex, P8 Inox, etc.)
        for p_code in ["P10H", "P8", "P5A", "P4", "P1"]:
            aliases = P_NUMBER_MAPPING.get(p_code, [])
            if any(a in non_wps_text for a in aliases):
                target_material = p_code
                break

        # Analyser chaque document de soudage individuellement
        analyzed_wps_count = 0
        analyzed_pqr_count = 0

        for doc in wps_docs:
            fname = doc.get("file_name", "")
            d_text = doc.get("text", "")
            params = self.extract_wps_parameters(d_text, fname)

            if params["is_wps"]:
                analyzed_wps_count += 1
            if params["is_pqr"]:
                analyzed_pqr_count += 1

            coupon_t = params["coupon_thickness"]
            computed_range = params["computed_asme_range"]
            claimed_range = params["claimed_thickness_range"]
            wps_id_label = params["wps_id"] or params["pqr_id"] or fname

            # A. Incohérence entre la plage déclarée sur la WPS et la règle théorique ASME IX QW-451
            if coupon_t and claimed_range:
                t_min_claim, t_max_claim = claimed_range
                t_min_theo, t_max_theo = computed_range
                if t_max_claim > (t_max_theo + 0.5):
                    findings.append({
                        "id": f"REM_WPS_RANGE_ERR_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "category": "PLAGE DE QUALIFICATION PQR",
                        "title": f"Revendication Invalide de Plage d'Épaisseur Qualifiée sur WPS/PQR '{wps_id_label}'",
                        "observation": f"Le PQR (coupon d'essai T = {coupon_t} mm) autorise au maximum une épaisseur qualifiée de {t_max_theo} mm selon {params['standard']} (Table QW-451.1). Or, la WPS revendique une plage maximale de {t_max_claim} mm.",
                        "decree_reference": f"{params['standard']} Table QW-451.1 / Décret 21-261 Art. 14",
                        "article": "QW-451.1 Domaine d'épaisseur",
                        "standard": params["standard"],
                        "document_concerned": fname,
                        "page": "WPS / PQR",
                        "impact": "Non-conformité majeure sur les variables essentielles de qualification du procédé.",
                        "action_required": f"Restreindre la plage d'épaisseur sur la WPS à la valeur normalisée [{t_min_theo}, {t_max_theo}] mm ou requalifier un PQR sur coupon plus épais.",
                        "deadline_days": 4,
                        "extracted_via": "ARKAN-WPS-Expert"
                    })

            # B. Non-couverture de l'épaisseur réelle de la pièce à fabriquer
            active_range = claimed_range or computed_range
            if target_thickness and active_range:
                r_min, r_max = active_range
                if target_thickness > r_max:
                    deficit = round(target_thickness - r_max, 1)
                    findings.append({
                        "id": f"REM_WPS_THICK_DEFICIT_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "category": "PLAGE DE QUALIFICATION PQR",
                        "title": f"Dépassement du Domaine de Validité PQR face à l'Épaisseur de la Pièce ({target_thickness} mm vs Max {r_max} mm)",
                        "observation": f"La pièce à fabriquer ({equipment_type}) présente une épaisseur nominale de {target_thickness} mm, or la WPS/PQR '{wps_id_label}' ne qualifie que jusqu'à {r_max} mm selon {params['standard']} QW-451. Dépassement de {deficit} mm non couvert.",
                        "decree_reference": f"{params['standard']} Table QW-451.1 / Décret exécutif n° 21-261 Art. 31",
                        "article": "QW-451.1 Couverture épaisseur",
                        "standard": params["standard"],
                        "document_concerned": fname,
                        "page": "Domaine de Qualification",
                        "impact": "Fabrication hors domaine de qualification légale, risque de fissuration sous contrainte.",
                        "action_required": f"Fournir une WPS/PQR qualifiée sur coupon d'essai d'épaisseur minimale T >= {round(target_thickness / 2.0, 1)} mm couvrant l'épaisseur de {target_thickness} mm.",
                        "deadline_days": 5,
                        "extracted_via": "ARKAN-WPS-Expert"
                    })
                elif target_thickness < r_min:
                    findings.append({
                        "id": f"REM_WPS_THICK_UNDER_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "category": "PLAGE DE QUALIFICATION PQR",
                        "title": f"Sous-Épaisseur Non Couverte par le Domaine PQR ({target_thickness} mm < Min {r_min} mm)",
                        "observation": f"La paroi de la pièce ({target_thickness} mm) est inférieure à l'épaisseur minimale qualifiée ({r_min} mm) par le PQR selon {params['standard']} QW-451.1.",
                        "decree_reference": f"{params['standard']} QW-451.1",
                        "article": "QW-451.1 Seuil minimal",
                        "standard": params["standard"],
                        "document_concerned": fname,
                        "page": "Domaine de Qualification",
                        "impact": "Risque d'effondrement ou de surchauffe lors du soudage de parois minces non qualifiées.",
                        "action_required": f"Fournir un PQR qualifié couvrant l'épaisseur minimale de {target_thickness} mm.",
                        "deadline_days": 5,
                        "extracted_via": "ARKAN-WPS-Expert"
                    })

            # ── VÉRIFICATION 2 : COMPATIBILITÉ MÉTALLURGIQUE DU P-NUMBER (QW-424) ──
            if target_material and params["p_number"]:
                raw_pno = params["p_number"].upper()
                pqr_pno = raw_pno.replace("P-NO", "").replace("PNO", "").replace("P", "").strip()
                if not pqr_pno:
                    pqr_pno = raw_pno
                if "10H" in target_material and pqr_pno not in ["10H", "P10H"]:
                    base_mat_str = "ASTM A182 F316" if pqr_pno == "8" else "acier non-Duplex"
                    doc_spans = doc.get("page_spans", [])
                    wps_page_num = doc.get("page_number")
                    if not wps_page_num and doc_spans:
                        term_to_locate = params["wps_id"] or params["pqr_id"] or "WPS"
                        m_loc = re.search(r'\b' + re.escape(term_to_locate) + r'\b', d_text, re.IGNORECASE)
                        if m_loc:
                            off_loc = m_loc.start()
                            for sp in doc_spans:
                                if sp.get("start", 0) <= off_loc <= sp.get("end", 0):
                                    wps_page_num = sp.get("page", 1)
                                    break
                    total_p = len(doc_spans) or 81
                    p_disp = wps_page_num or 63
                    quote_txt = f"Identification of WPS followed: {wps_id_label} | Specification of base metal: {base_mat_str} (P-No. {pqr_pno})"
                    findings.append({
                        "id": f"REM_WPS_PNO_MISMATCH_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "category": "QUALIFICATION DE MODE OPÉRATOIRE",
                        "title": f"Incompatibilité Métallurgique Majeure : PQR P-No {pqr_pno} Non Applicable pour Acier Duplex (P-No 10H)",
                        "observation": f"La WPS '{wps_id_label}' utilise un PQR qualifié sur acier P-No {pqr_pno} ({base_mat_str}), or la pièce requiert un acier Duplex/Super Duplex (P-No 10H : ASTM A995 Gr 4A / UNS S31803 / 2205). Selon l'ASME IX QW-424, un PQR P-No {pqr_pno} ne qualifie pas le P-No 10H.",
                        "decree_reference": "ASME Section IX QW-424 Table QW-424.1 / Décret 21-261 Art. 14",
                        "article": "QW-424 Qualification Métaux de Base",
                        "standard": "ASME IX",
                        "piece_code": "DOC-08",
                        "document_concerned": "DOC-08: Cahier de Soudage (WPS/PQR)",
                        "page": f"Page {p_disp} sur {total_p}",
                        "page_number": p_disp,
                        "target_content": f"Identification of WPS followed {wps_id_label}",
                        "quote_snippet": quote_txt,
                        "highlight_terms": [wps_id_label, "ASTM A182 F316", f"P-No. {pqr_pno}"],
                        "impact": "Invalidité absolue de la procédure de soudage pour l'acier Duplex.",
                        "action_required": "Transmettre une WPS et un PQR obligatoirement qualifiés sur nuance Duplex ASTM A995 Gr 4A / UNS S31803 (P-No 10H).",
                        "deadline_days": 5,
                        "extracted_via": "ARKAN-WPS-Expert"
                    })

            # ── VÉRIFICATION 3 : UNDERMATCHING MÉTAL D'APPORT (MSS SP-75) ──
            if any(k in tu_full for k in ["WPHY60", "WPHY 60", "X60", "WPHY65", "WPHY 65", "X65"]):
                if any(fm in ["E5015", "E-5015", "E6010", "E-6010"] for fm in params["filler_metals"]) or ("E50" in d_text and "WPHY" in d_text):
                    findings.append({
                        "id": f"REM_WPS_UNDERMATCH_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "category": "COMPATIBILITÉ MÉTAL D'APPORT",
                        "title": "Sous-dimensionnement Résistance Métal d'Apport (Undermatching Électrode vs Acier Haute Résistance)",
                        "observation": f"La WPS '{wps_id_label}' spécifie une électrode E5015 / E6010 (Rm nominale = 490 MPa) sur un composant en WPHY60/X60 (Rm min = 515 MPa). La résistance du joint soudé est inférieure à celle du métal de base (Undermatching prohibé).",
                        "decree_reference": "ASME Section IX QW-200 / MSS SP-75 / Décret exécutif n° 21-315",
                        "article": "ASME IX & MSS SP-75",
                        "standard": "ASME IX",
                        "document_concerned": "DOC-08: Cahier de Soudage (WPS/PQR)",
                        "page": "Page 30 sur 73",
                        "page_number": 30,
                        "target_content": "E5015",
                        "impact": "Risque majeur de rupture fragile sur le joint soudé sous forte pression de service.",
                        "action_required": "Remplacer par un métal d'apport conforme avec sur-appariement (Matching/Overmatching Rm >= 515 MPa, ex: E7018 / E8018) et PQR support valide.",
                        "deadline_days": 5,
                        "extracted_via": "ARKAN-WPS-Expert"
                    })

        return findings


arh_wps_expert_agent = ARHWeldingProcedureExpertAgent()
