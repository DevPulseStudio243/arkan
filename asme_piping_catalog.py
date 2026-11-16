"""
ARKAN Engineering Intelligence — Module de Référence Métallurgique ASME
Normes intégrées :
- ASME B36.10M (Tubes acier carbone et alliés soudés et sans soudure)
- ASME B36.19M (Tubes acier inoxydable)
- ASME B16.9 (Raccords à souder bout à bout forgés en usine)
- ASME B16.5 (Brides de tuyauteries et raccords à brides NPS 1/2 à 24)
- ASME B16.10 (Dimensions face-à-face de robinetterie)
"""

from typing import Dict, Optional, Tuple, Any
import re
import logging

logger = logging.getLogger(__name__)

# ── 1. Dictionnaire de conversion et normalisation des fractions NPS / DN ──
NPS_MAP: Dict[str, str] = {
    "1/8": "1/8\"", "1/8\"": "1/8\"", "6": "1/8\"", "DN6": "1/8\"",
    "1/4": "1/4\"", "1/4\"": "1/4\"", "8": "1/4\"", "DN8": "1/4\"",
    "3/8": "3/8\"", "3/8\"": "3/8\"", "10": "3/8\"", "DN10": "3/8\"",
    "1/2": "1/2\"", "1/2\"": "1/2\"", "0.5": "1/2\"", "15": "1/2\"", "DN15": "1/2\"",
    "3/4": "3/4\"", "3/4\"": "3/4\"", "0.75": "3/4\"", "20": "3/4\"", "DN20": "3/4\"",
    "1": "1\"", "1\"": "1\"", "1.0": "1\"", "25": "1\"", "DN25": "1\"",
    "1-1/4": "1-1/4\"", "1 1/4": "1-1/4\"", "1-1/4\"": "1-1/4\"", "1.25": "1-1/4\"", "32": "1-1/4\"", "DN32": "1-1/4\"",
    "1-1/2": "1-1/2\"", "1 1/2": "1-1/2\"", "1-1/2\"": "1-1/2\"", "1.5": "1-1/2\"", "40": "1-1/2\"", "DN40": "1-1/2\"",
    "2": "2\"", "2\"": "2\"", "2.0": "2\"", "50": "2\"", "DN50": "2\"",
    "2-1/2": "2-1/2\"", "2 1/2": "2-1/2\"", "2-1/2\"": "2-1/2\"", "2.5": "2-1/2\"", "65": "2-1/2\"", "DN65": "2-1/2\"",
    "3": "3\"", "3\"": "3\"", "3.0": "3\"", "80": "3\"", "DN80": "3\"",
    "3-1/2": "3-1/2\"", "3 1/2": "3-1/2\"", "3-1/2\"": "3-1/2\"", "3.5": "3-1/2\"", "90": "3-1/2\"", "DN90": "3-1/2\"",
    "4": "4\"", "4\"": "4\"", "4.0": "4\"", "100": "4\"", "DN100": "4\"",
    "5": "5\"", "5\"": "5\"", "5.0": "5\"", "125": "5\"", "DN125": "5\"",
    "6": "6\"", "6\"": "6\"", "6.0": "6\"", "150": "6\"", "DN150": "6\"",
    "8": "8\"", "8\"": "8\"", "8.0": "8\"", "200": "8\"", "DN200": "8\"",
    "10": "10\"", "10\"": "10\"", "10.0": "10\"", "250": "10\"", "DN250": "10\"",
    "12": "12\"", "12\"": "12\"", "12.0": "12\"", "300": "12\"", "DN300": "12\"",
    "14": "14\"", "14\"": "14\"", "14.0": "14\"", "350": "14\"", "DN350": "14\"",
    "16": "16\"", "16\"": "16\"", "16.0": "16\"", "400": "16\"", "DN400": "16\"",
    "18": "18\"", "18\"": "18\"", "18.0": "18\"", "450": "18\"", "DN450": "18\"",
    "20": "20\"", "20\"": "20\"", "20.0": "20\"", "500": "20\"", "DN500": "20\"",
    "24": "24\"", "24\"": "24\"", "24.0": "24\"", "600": "24\"", "DN600": "24\"",
    "28": "28\"", "28\"": "28\"", "700": "28\"", "DN700": "28\"",
    "30": "30\"", "30\"": "30\"", "750": "30\"", "DN750": "30\"",
    "32": "32\"", "32\"": "32\"", "800": "32\"", "DN800": "32\"",
    "36": "36\"", "36\"": "36\"", "900": "36\"", "DN900": "36\"",
}

# ── 2. Table ASME B36.10M / B36.19M des poids linéaires de tubes (kg / mètre) ──
# Clé: (NPS_normalisé, Schedule_normalisé) -> Poids en kg/mètre
PIPE_WEIGHT_TABLE: Dict[Tuple[str, str], float] = {
    # 1/2" (DN 15, OD = 21.3 mm)
    ("1/2\"", "SCH 10"): 0.85, ("1/2\"", "SCH 40"): 1.27, ("1/2\"", "STD"): 1.27,
    ("1/2\"", "SCH 80"): 1.62, ("1/2\"", "XS"): 1.62, ("1/2\"", "SCH 160"): 2.55, ("1/2\"", "XXS"): 3.00,
    
    # 3/4" (DN 20, OD = 26.7 mm)
    ("3/4\"", "SCH 10"): 1.13, ("3/4\"", "SCH 40"): 1.69, ("3/4\"", "STD"): 1.69,
    ("3/4\"", "SCH 80"): 2.20, ("3/4\"", "XS"): 2.20, ("3/4\"", "SCH 160"): 3.64, ("3/4\"", "XXS"): 4.12,
    
    # 1" (DN 25, OD = 33.4 mm)
    ("1\"", "SCH 10"): 1.69, ("1\"", "SCH 40"): 2.50, ("1\"", "STD"): 2.50,
    ("1\"", "SCH 80"): 3.24, ("1\"", "XS"): 3.24, ("1\"", "SCH 160"): 4.24, ("1\"", "XXS"): 5.90,
    
    # 1-1/4" (DN 32, OD = 42.2 mm)
    ("1-1/4\"", "SCH 10"): 2.43, ("1-1/4\"", "SCH 40"): 3.39, ("1-1/4\"", "STD"): 3.39,
    ("1-1/4\"", "SCH 80"): 4.47, ("1-1/4\"", "XS"): 4.47, ("1-1/4\"", "SCH 160"): 6.01, ("1-1/4\"", "XXS"): 8.44,
    
    # 1-1/2" (DN 40, OD = 48.3 mm)
    ("1-1/2\"", "SCH 10"): 2.83, ("1-1/2\"", "SCH 40"): 4.05, ("1-1/2\"", "STD"): 4.05,
    ("1-1/2\"", "SCH 80"): 5.41, ("1-1/2\"", "XS"): 5.41, ("1-1/2\"", "SCH 160"): 7.25, ("1-1/2\"", "XXS"): 10.15,
    
    # 2" (DN 50, OD = 60.3 mm)
    ("2\"", "SCH 10"): 3.99, ("2\"", "SCH 40"): 5.44, ("2\"", "STD"): 5.44,
    ("2\"", "SCH 80"): 7.48, ("2\"", "XS"): 7.48, ("2\"", "SCH 160"): 11.11, ("2\"", "XXS"): 13.44,
    
    # 2-1/2" (DN 65, OD = 73.0 mm)
    ("2-1/2\"", "SCH 10"): 5.26, ("2-1/2\"", "SCH 40"): 8.63, ("2-1/2\"", "STD"): 8.63,
    ("2-1/2\"", "SCH 80"): 11.41, ("2-1/2\"", "XS"): 11.41, ("2-1/2\"", "SCH 160"): 14.92, ("2-1/2\"", "XXS"): 20.39,
    
    # 3" (DN 80, OD = 88.9 mm)
    ("3\"", "SCH 10"): 6.56, ("3\"", "SCH 40"): 11.29, ("3\"", "STD"): 11.29,
    ("3\"", "SCH 80"): 15.27, ("3\"", "XS"): 15.27, ("3\"", "SCH 160"): 21.35, ("3\"", "XXS"): 27.68,
    
    # 4" (DN 100, OD = 114.3 mm)
    ("4\"", "SCH 10"): 8.49, ("4\"", "SCH 40"): 16.07, ("4\"", "STD"): 16.07,
    ("4\"", "SCH 80"): 22.32, ("4\"", "XS"): 22.32, ("4\"", "SCH 120"): 28.32, ("4\"", "SCH 160"): 33.54, ("4\"", "XXS"): 41.03,
    
    # 6" (DN 150, OD = 168.3 mm)
    ("6\"", "SCH 10"): 12.50, ("6\"", "SCH 40"): 28.26, ("6\"", "STD"): 28.26,
    ("6\"", "SCH 80"): 42.56, ("6\"", "XS"): 42.56, ("6\"", "SCH 120"): 54.20, ("6\"", "SCH 160"): 67.56, ("6\"", "XXS"): 79.22,
    
    # 8" (DN 200, OD = 219.1 mm)
    ("8\"", "SCH 10"): 19.33, ("8\"", "SCH 20"): 28.22, ("8\"", "SCH 30"): 36.31,
    ("8\"", "SCH 40"): 42.55, ("8\"", "STD"): 42.55, ("8\"", "SCH 80"): 64.64, ("8\"", "XS"): 64.64,
    ("8\"", "SCH 120"): 90.44, ("8\"", "SCH 160"): 111.27, ("8\"", "XXS"): 124.97,
    
    # 10" (DN 250, OD = 273.0 mm)
    ("10\"", "SCH 10"): 24.12, ("10\"", "SCH 20"): 41.77, ("10\"", "SCH 40"): 60.31, ("10\"", "STD"): 60.31,
    ("10\"", "SCH 80"): 95.97, ("10\"", "XS"): 95.97, ("10\"", "SCH 120"): 137.96, ("10\"", "SCH 160"): 172.33,
    
    # 12" (DN 300, OD = 323.8 mm)
    ("12\"", "SCH 10"): 28.64, ("12\"", "SCH 20"): 49.71, ("12\"", "SCH 40"): 73.86, ("12\"", "STD"): 73.86,
    ("12\"", "SCH 80"): 132.04, ("12\"", "XS"): 132.04, ("12\"", "SCH 120"): 187.00, ("12\"", "SCH 160"): 238.00,
    
    # 14" (DN 350, OD = 355.6 mm)
    ("14\"", "SCH 10"): 39.06, ("14\"", "SCH 30"): 70.08, ("14\"", "SCH 40"): 81.44, ("14\"", "STD"): 81.44,
    ("14\"", "SCH 80"): 150.79, ("14\"", "XS"): 150.79,
    
    # 16" (DN 400, OD = 406.4 mm)
    ("16\"", "SCH 10"): 44.75, ("16\"", "SCH 30"): 80.42, ("16\"", "SCH 40"): 93.27, ("16\"", "STD"): 93.27,
    ("16\"", "SCH 80"): 184.20, ("16\"", "XS"): 184.20,
    
    # 18" (DN 450, OD = 457.0 mm)
    ("18\"", "SCH 10"): 50.41, ("18\"", "SCH 40"): 105.10, ("18\"", "STD"): 105.10, ("18\"", "SCH 80"): 220.00,
    
    # 20" (DN 500, OD = 508.0 mm)
    ("20\"", "SCH 10"): 56.07, ("20\"", "SCH 40"): 117.00, ("20\"", "STD"): 117.00, ("20\"", "SCH 80"): 258.00,
    
    # 24" (DN 600, OD = 610.0 mm)
    ("24\"", "SCH 10"): 67.40, ("24\"", "SCH 40"): 140.70, ("24\"", "STD"): 140.70, ("24\"", "SCH 80"): 337.00,
}

# ── 3. Table ASME B16.5 des brides (Poids unitaire WN / Blind en kg) ──
# Clé: (NPS, Rating, Flange_Type) -> Poids en kg
FLANGE_WEIGHT_TABLE: Dict[Tuple[str, str, str], float] = {
    # 1/2"
    ("1/2\"", "150#", "WN"): 0.9, ("1/2\"", "150#", "BLIND"): 0.8, ("1/2\"", "300#", "WN"): 1.4, ("1/2\"", "300#", "BLIND"): 1.2,
    ("1/2\"", "600#", "WN"): 1.8, ("1/2\"", "600#", "BLIND"): 1.5,
    # 3/4"
    ("3/4\"", "150#", "WN"): 1.2, ("3/4\"", "150#", "BLIND"): 1.1, ("3/4\"", "300#", "WN"): 2.3, ("3/4\"", "300#", "BLIND"): 2.0,
    ("3/4\"", "600#", "WN"): 2.7, ("3/4\"", "600#", "BLIND"): 2.3,
    # 1"
    ("1\"", "150#", "WN"): 1.4, ("1\"", "150#", "BLIND"): 1.3, ("1\"", "300#", "WN"): 3.0, ("1\"", "300#", "BLIND"): 2.7,
    ("1\"", "600#", "WN"): 3.6, ("1\"", "600#", "BLIND"): 3.2,
    # 1-1/2"
    ("1-1/2\"", "150#", "WN"): 2.0, ("1-1/2\"", "150#", "BLIND"): 1.8, ("1-1/2\"", "300#", "WN"): 4.5, ("1-1/2\"", "300#", "BLIND"): 4.1,
    ("1-1/2\"", "600#", "WN"): 6.0, ("1-1/2\"", "600#", "BLIND"): 5.5,
    # 2"
    ("2\"", "150#", "WN"): 3.0, ("2\"", "150#", "BLIND"): 2.7, ("2\"", "300#", "WN"): 5.5, ("2\"", "300#", "BLIND"): 5.0,
    ("2\"", "600#", "WN"): 8.5, ("2\"", "600#", "BLIND"): 7.7, ("2\"", "900#", "WN"): 15.0,
    # 3"
    ("3\"", "150#", "WN"): 5.2, ("3\"", "150#", "BLIND"): 4.8, ("3\"", "300#", "WN"): 9.0, ("3\"", "300#", "BLIND"): 8.2,
    ("3\"", "600#", "WN"): 14.5, ("3\"", "600#", "BLIND"): 13.0, ("3\"", "900#", "WN"): 22.0,
    # 4"
    ("4\"", "150#", "WN"): 7.5, ("4\"", "150#", "BLIND"): 7.0, ("4\"", "300#", "WN"): 16.0, ("4\"", "300#", "BLIND"): 14.5,
    ("4\"", "600#", "WN"): 26.0, ("4\"", "600#", "BLIND"): 24.0, ("4\"", "900#", "WN"): 35.0,
    # 6"
    ("6\"", "150#", "WN"): 12.0, ("6\"", "150#", "BLIND"): 11.0, ("6\"", "300#", "WN"): 28.0, ("6\"", "300#", "BLIND"): 26.0,
    ("6\"", "600#", "WN"): 55.0, ("6\"", "600#", "BLIND"): 50.0, ("6\"", "900#", "WN"): 75.0,
    # 8"
    ("8\"", "150#", "WN"): 18.0, ("8\"", "150#", "BLIND"): 17.0, ("8\"", "300#", "WN"): 42.0, ("8\"", "300#", "BLIND"): 39.0,
    ("8\"", "600#", "WN"): 92.0, ("8\"", "600#", "BLIND"): 85.0, ("8\"", "900#", "WN"): 120.0,
    # 10"
    ("10\"", "150#", "WN"): 25.0, ("10\"", "150#", "BLIND"): 23.0, ("10\"", "300#", "WN"): 62.0, ("10\"", "300#", "BLIND"): 58.0,
    ("10\"", "600#", "WN"): 155.0, ("10\"", "600#", "BLIND"): 140.0,
    # 12"
    ("12\"", "150#", "WN"): 38.0, ("12\"", "150#", "BLIND"): 35.0, ("12\"", "300#", "WN"): 95.0, ("12\"", "300#", "BLIND"): 88.0,
    ("12\"", "600#", "WN"): 205.0, ("12\"", "600#", "BLIND"): 190.0,
}

# ── 4. Table ASME B16.9 des raccords (Coude 90 LR, Té égal, Réduction en kg) ──
FITTING_WEIGHT_TABLE: Dict[Tuple[str, str, str], float] = {
    # 1/2"
    ("1/2\"", "SCH 40", "ELBOW_90"): 0.08, ("1/2\"", "SCH 40", "TEE"): 0.12, ("1/2\"", "SCH 40", "REDUCER"): 0.08,
    ("1/2\"", "SCH 80", "ELBOW_90"): 0.12, ("1/2\"", "SCH 80", "TEE"): 0.16,
    # 3/4"
    ("3/4\"", "SCH 40", "ELBOW_90"): 0.13, ("3/4\"", "SCH 40", "TEE"): 0.18, ("3/4\"", "SCH 40", "REDUCER"): 0.11,
    ("3/4\"", "SCH 80", "ELBOW_90"): 0.18, ("3/4\"", "SCH 80", "TEE"): 0.24,
    # 1"
    ("1\"", "SCH 40", "ELBOW_90"): 0.23, ("1\"", "SCH 40", "TEE"): 0.35, ("1\"", "SCH 40", "REDUCER"): 0.20,
    ("1\"", "SCH 80", "ELBOW_90"): 0.32, ("1\"", "SCH 80", "TEE"): 0.45,
    # 1-1/2"
    ("1-1/2\"", "SCH 40", "ELBOW_90"): 0.55, ("1-1/2\"", "SCH 40", "TEE"): 0.82, ("1-1/2\"", "SCH 40", "REDUCER"): 0.45,
    ("1-1/2\"", "SCH 80", "ELBOW_90"): 0.85, ("1-1/2\"", "SCH 80", "TEE"): 1.15,
    # 2"
    ("2\"", "SCH 40", "ELBOW_90"): 0.95, ("2\"", "SCH 40", "TEE"): 1.45, ("2\"", "SCH 40", "REDUCER"): 0.80,
    ("2\"", "SCH 80", "ELBOW_90"): 1.50, ("2\"", "SCH 80", "TEE"): 2.20,
    # 3"
    ("3\"", "SCH 40", "ELBOW_90"): 2.70, ("3\"", "SCH 40", "TEE"): 3.80, ("3\"", "SCH 40", "REDUCER"): 1.90,
    ("3\"", "SCH 80", "ELBOW_90"): 4.10, ("3\"", "SCH 80", "TEE"): 5.60,
    # 4"
    ("4\"", "SCH 40", "ELBOW_90"): 5.20, ("4\"", "SCH 40", "TEE"): 7.20, ("4\"", "SCH 40", "REDUCER"): 3.50,
    ("4\"", "SCH 80", "ELBOW_90"): 8.50, ("4\"", "SCH 80", "TEE"): 11.50,
    # 6"
    ("6\"", "SCH 40", "ELBOW_90"): 14.50, ("6\"", "SCH 40", "TEE"): 19.50, ("6\"", "SCH 40", "REDUCER"): 9.00,
    ("6\"", "SCH 80", "ELBOW_90"): 25.00, ("6\"", "SCH 80", "TEE"): 32.00,
    # 8"
    ("8\"", "SCH 40", "ELBOW_90"): 30.50, ("8\"", "SCH 40", "TEE"): 38.00, ("8\"", "SCH 40", "REDUCER"): 18.00,
    ("8\"", "SCH 80", "ELBOW_90"): 52.00, ("8\"", "SCH 80", "TEE"): 64.00,
    # 10"
    ("10\"", "SCH 40", "ELBOW_90"): 55.00, ("10\"", "SCH 40", "TEE"): 68.00, ("10\"", "SCH 40", "REDUCER"): 32.00,
    ("10\"", "SCH 80", "ELBOW_90"): 95.00, ("10\"", "SCH 80", "TEE"): 115.00,
    # 12"
    ("12\"", "SCH 40", "ELBOW_90"): 88.00, ("12\"", "SCH 40", "TEE"): 105.00, ("12\"", "SCH 40", "REDUCER"): 48.00,
    ("12\"", "SCH 80", "ELBOW_90"): 155.00, ("12\"", "SCH 80", "TEE"): 185.00,
}


# ── 5. Fonctions d'Interrogation & Normalisation ──

def normalize_nps(raw_val: Any) -> str:
    """Normalise n'importe quelle représentation de diamètre (fractions, DN, pouces) en notation NPS standard."""
    if raw_val is None:
        return "4\""
    s = str(raw_val).strip().replace("''", "\"").replace("“", "\"").replace("”", "\"")
    # Supprimer les zéros non significatifs
    s = re.sub(r'(\d+)\.0+(\b|\")', r'\1\2', s)
    if s in NPS_MAP:
        return NPS_MAP[s]
    # Essayer avec DN préfixé ou suffixes
    clean = s.replace("\"", "").strip()
    if clean in NPS_MAP:
        return NPS_MAP[clean]
    # Fallback : rajouter les guillemets si chiffre pur
    if re.match(r'^\d+(?:[-/ ]\d+)?$', s):
        candidate = s.replace(" ", "-") + "\""
        if candidate in NPS_MAP:
            return NPS_MAP[candidate]
        return s + "\""
    return s


def normalize_schedule(raw_sch: Any) -> str:
    """Normalise les désignations de schedule (SCH 40, STD, XS, SCH 80)."""
    if not raw_sch:
        return "SCH 40"
    s = str(raw_sch).upper().strip()
    s = re.sub(r'^(SCHEDULE|SCHED|SCH)\.?\s*', 'SCH ', s)
    if not s.startswith("SCH ") and s.isdigit():
        s = f"SCH {s}"
    if s in ("STD", "STANDARD"):
        return "SCH 40"
    if s in ("XS", "EXTRA STRONG"):
        return "SCH 80"
    if s in ("XXS", "DOUBLE EXTRA STRONG"):
        return "XXS"
    return s


def normalize_rating(raw_rating: Any) -> str:
    """Normalise les séries de pression de brides et vannes (150#, 300#, 600#)."""
    if not raw_rating:
        return "150#"
    s = str(raw_rating).upper().strip()
    match = re.search(r'(\d{3,4})', s)
    if match:
        val = match.group(1)
        if val in ("150", "300", "600", "900", "1500", "2500"):
            return f"{val}#"
    return "150#"


def get_pipe_unit_weight(nps: str, schedule: str = "SCH 40") -> float:
    """Retourne le poids unitaire d'un tube en kg par mètre linéaire selon ASME B36.10M."""
    norm_nps = normalize_nps(nps)
    norm_sch = normalize_schedule(schedule)
    
    # 1. Recherche exacte
    if (norm_nps, norm_sch) in PIPE_WEIGHT_TABLE:
        return PIPE_WEIGHT_TABLE[(norm_nps, norm_sch)]
        
    # 2. Fallback avec Sch 40
    if (norm_nps, "SCH 40") in PIPE_WEIGHT_TABLE:
        return PIPE_WEIGHT_TABLE[(norm_nps, "SCH 40")]
        
    # 3. Fallback approximatif pour diamètres hors table
    try:
        val_str = norm_nps.replace("\"", "").replace("-", " ")
        parts = val_str.split()
        if len(parts) == 2:
            num, den = parts[1].split("/")
            numeric_dia = float(parts[0]) + float(num)/float(den)
        elif "/" in val_str:
            num, den = val_str.split("/")
            numeric_dia = float(num)/float(den)
        else:
            numeric_dia = float(val_str)
        # Formule de Barlow approximative pour Sch 40 : ~ 1.0 * Dia(inch)^1.5 * 2.5
        return round(numeric_dia * numeric_dia * 1.05 + numeric_dia * 2.5, 2)
    except Exception:
        return 16.07  # Poids 4" Sch 40 par défaut


def get_fitting_unit_weight(category: str, nps: str, schedule: str = "SCH 40") -> float:
    """Retourne le poids unitaire d'un raccord en kg selon ASME B16.9."""
    norm_nps = normalize_nps(nps)
    norm_sch = normalize_schedule(schedule)
    cat_upper = category.upper()

    fit_type = "ELBOW_90"
    if "TEE" in cat_upper or "TE" in cat_upper:
        fit_type = "TEE"
    elif "RED" in cat_upper:
        fit_type = "REDUCER"

    if (norm_nps, norm_sch, fit_type) in FITTING_WEIGHT_TABLE:
        return FITTING_WEIGHT_TABLE[(norm_nps, norm_sch, fit_type)]
    if (norm_nps, "SCH 40", fit_type) in FITTING_WEIGHT_TABLE:
        return FITTING_WEIGHT_TABLE[(norm_nps, "SCH 40", fit_type)]
    
    # Fallback proportionnel au tube
    pipe_w = get_pipe_unit_weight(norm_nps, norm_sch)
    if fit_type == "ELBOW_90":
        return round(pipe_w * 0.35, 2)
    elif fit_type == "TEE":
        return round(pipe_w * 0.48, 2)
    return round(pipe_w * 0.25, 2)


def get_flange_unit_weight(nps: str, rating: str = "150#", flange_type: str = "WN") -> float:
    """Retourne le poids unitaire d'une bride forgée en kg selon ASME B16.5."""
    norm_nps = normalize_nps(nps)
    norm_rat = normalize_rating(rating)
    flg_type = "BLIND" if "BLIND" in flange_type.upper() else "WN"

    if (norm_nps, norm_rat, flg_type) in FLANGE_WEIGHT_TABLE:
        return FLANGE_WEIGHT_TABLE[(norm_nps, norm_rat, flg_type)]
    if (norm_nps, "150#", flg_type) in FLANGE_WEIGHT_TABLE:
        return FLANGE_WEIGHT_TABLE[(norm_nps, "150#", flg_type)]

    pipe_w = get_pipe_unit_weight(norm_nps, "SCH 40")
    factor = 1.0 if norm_rat == "150#" else (1.8 if norm_rat == "300#" else 2.8)
    return round(pipe_w * 0.5 * factor, 2)


def get_valve_unit_weight(nps: str, rating: str = "150#", valve_type: str = "BALL") -> float:
    """Retourne une estimation industrielle du poids d'une vanne en kg (face-à-face ASME B16.10)."""
    norm_nps = normalize_nps(nps)
    norm_rat = normalize_rating(rating)
    flange_w = get_flange_unit_weight(norm_nps, norm_rat, "WN")
    
    # Une vanne standard à brides pèse environ 2.2 à 3 fois le poids de deux brides
    mult = 2.4
    if "GATE" in valve_type.upper() or "GLOBE" in valve_type.upper():
        mult = 3.2
    elif "CHECK" in valve_type.upper():
        mult = 1.8
    elif "BALL" in valve_type.upper():
        mult = 2.5
    return round(flange_w * 2 * mult, 2)


# ── 6. Encombrements Standards pour Take-Offs ASME B16.9 / B16.5 / B16.10 (en mm) ──
TAKEOFF_DIMENSIONS: Dict[str, Dict[str, float]] = {
    # Coude 90° LR Center-to-End (ASME B16.9)
    "ELBOW_90_LR": {
        "1/2\"": 38.1, "3/4\"": 38.1, "1\"": 38.1, "1-1/4\"": 47.6, "1-1/2\"": 57.2,
        "2\"": 76.2, "2-1/2\"": 95.3, "3\"": 114.3, "4\"": 152.4, "6\"": 228.6,
        "8\"": 304.8, "10\"": 381.0, "12\"": 457.2, "14\"": 533.4, "16\"": 609.6
    },
    # Té égal Center-to-End (ASME B16.9)
    "TEE_EQUAL": {
        "1/2\"": 25.4, "3/4\"": 28.6, "1\"": 38.1, "1-1/4\"": 47.6, "1-1/2\"": 57.2,
        "2\"": 63.5, "2-1/2\"": 76.2, "3\"": 85.7, "4\"": 104.8, "6\"": 143.0,
        "8\"": 177.8, "10\"": 215.9, "12\"": 254.0, "14\"": 279.4, "16\"": 304.8
    },
    # Bride WN longueur au moyeu 150# (ASME B16.5)
    "FLANGE_WN_150": {
        "1/2\"": 47.6, "3/4\"": 52.4, "1\"": 55.6, "1-1/4\"": 57.2, "1-1/2\"": 62.0,
        "2\"": 63.5, "2-1/2\"": 69.9, "3\"": 69.9, "4\"": 76.2, "6\"": 88.9,
        "8\"": 101.6, "10\"": 101.6, "12\"": 114.3, "14\"": 127.0, "16\"": 127.0
    },
    # Vanne à opercule BW 150# longueur bout à bout (ASME B16.10)
    "VALVE_GATE_150": {
        "1/2\"": 108.0, "3/4\"": 117.0, "1\"": 127.0, "1-1/2\"": 165.0,
        "2\"": 178.0, "2-1/2\"": 190.0, "3\"": 203.0, "4\"": 229.0, "6\"": 267.0,
        "8\"": 292.0, "10\"": 330.0, "12\"": 356.0, "14\"": 381.0, "16\"": 406.0
    }
}


def calculate_piping_takeoffs(nps: str, callout_counts: Dict[str, int], rating: str = "150#") -> Tuple[float, Dict[str, float]]:
    """
    Calcule la déduction totale des encombrements de raccords (Take-offs) en mètres
    pour passer des cotes d'axe en axe (centerline) à la longueur nette de coupe (cut length)
    selon ASME B16.9, B16.5 et B16.10.
    """
    norm_nps = normalize_nps(nps)
    total_takeoff_mm = 0.0
    details: Dict[str, float] = {}

    # 1. Coudes 90° LR (2 branches déduites par coude)
    elbow_c2e = TAKEOFF_DIMENSIONS["ELBOW_90_LR"].get(norm_nps, 228.6)
    for desc, count in callout_counts.items():
        du = desc.upper()
        if "COUDE" in du or "ELBOW" in du:
            deduct = count * (2 * elbow_c2e)
            total_takeoff_mm += deduct
            details[f"{count}x Coude 90° LR (2x{elbow_c2e:.1f}mm)"] = deduct

    # 2. Tés égaux (3 branches déduites)
    tee_c2e = TAKEOFF_DIMENSIONS["TEE_EQUAL"].get(norm_nps, 143.0)
    for desc, count in callout_counts.items():
        du = desc.upper()
        if bool(re.search(r'\b(T[EÉ](\s+[EÉ]GAL)?|TEE)\b', du)):
            deduct = count * (3 * tee_c2e)
            total_takeoff_mm += deduct
            details[f"{count}x Té égal (3x{tee_c2e:.1f}mm)"] = deduct

    # 3. Vannes (longueur bout à bout déduite)
    valve_len = TAKEOFF_DIMENSIONS["VALVE_GATE_150"].get(norm_nps, 267.0)
    for desc, count in callout_counts.items():
        du = desc.upper()
        if "VANNE" in du or "VALVE" in du:
            deduct = count * valve_len
            total_takeoff_mm += deduct
            details[f"{count}x Vanne ({valve_len:.1f}mm)"] = deduct

    # 4. Brides de raccordement et jeux de racine (Welding root gaps)
    flange_hub = TAKEOFF_DIMENSIONS["FLANGE_WN_150"].get(norm_nps, 88.9)
    flange_count = sum(c for d, c in callout_counts.items() if "BRIDE" in d.upper() or "FLANGE" in d.upper())
    if flange_count > 0:
        # Déduction pour 2 brides terminales débouchantes + gaps de soudage
        terminal_flanges = min(flange_count, 2)
        flange_deduct = terminal_flanges * flange_hub
        # Root gaps ASME B31.3 : environ 1.6 mm à 3.2 mm par soudure bout-à-bout
        root_gaps = 15.8  # ~5 soudures x 3.16 mm
        flange_and_gaps = flange_deduct + root_gaps
        total_takeoff_mm += flange_and_gaps
        details[f"{terminal_flanges}x Brides WN ({flange_hub:.1f}mm) + Gaps soudure"] = flange_and_gaps

    total_takeoff_m = round(total_takeoff_mm / 1000.0, 3)
    return total_takeoff_m, details

