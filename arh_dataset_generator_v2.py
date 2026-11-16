"""
arh_dataset_generator_v2.py
============================
Génère ~22 000 exemples d'entraînement JSONL spécialisés par Part P-CTE-1,
en 4 langues (FR / EN / AR / ZH), pour le fine-tuning Qwen2.5-14B LoRA ARH.

Chaque exemple suit le format Alpaca 3-champs :
  { "instruction": "...", "input": "...", "output": "...", "part": "...", "language": "..." }

Stratégie de génération par Part :
  - Part 1   Lettre ARH & Page de Garde     → 500  ex / 4 langues
  - Part 2   Légalisation Consulaire        → 600  ex / 4 langues
  - Part 3&9 Certificats Conformité         → 800  ex / 4 langues
  - Part 4   État Descriptif (Annexe E)     → 2000 ex / 4 langues
  - Part 5   Notes de Calcul ASME/Barlow    → 3000 ex / FR+EN
  - Part 6   Plans & Cartouches             → 800  ex / FR+EN
  - Part 8   WPS/PQR Cahier Soudage         → 2500 ex / FR+EN
  - Part 9   PWHT Traitement Thermique      → 600  ex / FR+EN
  - Part 10  ITP Hold/Witness/Review Points → 2000 ex / FR+EN
  - Part 11  ATEX/IECEx/SIL Électrique      → 1200 ex / FR+EN
  - Part 12  Certificat Bonne Conservation  → 400  ex / 3 langues
  - Cert 3.1 Certificats Matière EN 10204   → 1500 ex (existants enrichis)
  - Levée    Levée de Réserves EPC↔ARH      → 2000 ex / FR+EN
  - Multilang Textes mixtes / OCR-noise     → 3000 ex
  Total cible : ~21 000 nouveaux + 1 500 nettoyés = ~22 500
"""

from __future__ import annotations

import json
import random
import uuid
import math
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import itertools

OUTPUT_DIR  = Path(__file__).parent
SEED        = 42
random.seed(SEED)

# ══════════════════════════════════════════════════════════════════════════════
# INSTRUCTION TEMPLATES PAR LANGUE
# ══════════════════════════════════════════════════════════════════════════════

INSTRUCTIONS = {
    "FR": (
        "Tu es l'Inspecteur Expert ARH (Autorité de Régulation des Hydrocarbures d'Algérie). "
        "Analyse en profondeur le document ARH soumis et identifie TOUTES les non-conformités "
        "réglementaires selon la procédure P-CTE-1, les décrets exécutifs algériens "
        "(21-261, 21-314, 21-315, 24-278, 17-62) et les codes internationaux (ASME VIII/IX, "
        "ASME B31.3/B31.4/B31.8, API 5L, MSS SP-75, NACE MR0175, EN 10204 3.1, IEC 60079). "
        "Réponds sous forme d'objet JSON strict."
    ),
    "EN": (
        "You are the Expert ARH Inspector (Hydrocarbons Regulatory Authority of Algeria). "
        "Thoroughly analyze the submitted ARH document and identify ALL regulatory "
        "non-conformities per P-CTE-1 procedure, Algerian Executive Decrees "
        "(21-261, 21-314, 21-315, 24-278, 17-62) and international codes (ASME VIII/IX, "
        "ASME B31.3/B31.4/B31.8, API 5L, MSS SP-75, NACE MR0175, EN 10204 3.1, IEC 60079). "
        "Reply in strict JSON format."
    ),
    "AR": (
        "أنت مفتش خبير في هيئة تنظيم المحروقات (ARH) بالجزائر. "
        "قم بتحليل وثيقة ARH المقدمة بعمق وحدد جميع المخالفات التنظيمية "
        "وفقًا للإجراء P-CTE-1 والمراسيم التنفيذية الجزائرية (21-261, 21-314, 21-315) "
        "والمعايير الدولية (ASME VIII/IX, API 5L, NACE MR0175, EN 10204 3.1). "
        "أجب بتنسيق JSON صارم."
    ),
    "ZH": (
        "您是阿尔及利亚油气监管局（ARH）专家检查员。"
        "请深入分析提交的ARH文件，依据P-CTE-1程序、阿尔及利亚行政法令"
        "（21-261, 21-314, 21-315, 24-278）及国际规范（ASME VIII/IX, "
        "API 5L, NACE MR0175, EN 10204 3.1, IEC 60079）"
        "识别所有监管不符合项。请以严格的JSON格式回答。"
    ),
}

# ══════════════════════════════════════════════════════════════════════════════
# DONNÉES DE RÉFÉRENCE
# ══════════════════════════════════════════════════════════════════════════════

PROJECTS = [
    "PROJET CANALISATION BAOTOU GCB 48\"",
    "GAZODUC GK3 48 POUCES - SONATRACH",
    "OLEODUC OH1 24\" 46 KM GRE",
    "CENTRE DE TRAITEMENT CPF TOUAT",
    "COMPLEXE GNL SKIKDA - PHASE 2",
    "PROJET BOOSTING HASSI R'MEL CS-02",
    "RAFFINERIE SKIKDA RENOVATION",
    "PROJET SEPARATION RHOURDE NOUSS",
    "TINHERT-OHANET FIELD DEVELOPMENT EPC1",
    "PIPELINE CIS-HAOUD EL HAMRA 24\"",
    "STATION DE COMPRESSION SC-1 IN SALAH",
    "UNITÉ DE TRAITEMENT UTB ALRAR",
]

EQUIPMENT_TYPES = [
    ("PRESSURE_VESSEL",  "Pressure Vessel / Récipient Sous Pression",     "V"),
    ("SEPARATOR",        "Separator / Séparateur de Procédé",             "S"),
    ("HEAT_EXCHANGER",   "Heat Exchanger / Échangeur de Chaleur",         "E"),
    ("LINEPIPE",         "Linepipe / Tube Canalisation",                  "LP"),
    ("PIPELINE",         "Pipeline / Canalisation de Transport",          "PL"),
    ("BARRED_TEE",       "Barred Tee / Té à Barreaux",                    "BT"),
    ("VALVE",            "Valve / Vanne de Procédé",                      "V"),
    ("TANK",             "Storage Tank / Bac de Stockage API 650",        "T"),
    ("SKID",             "Metering Skid / Skid de Comptage",              "SK"),
    ("ELECTRICAL_PANEL", "Electrical Panel / Tableau Électrique HT/BT",   "EP"),
    ("ATEX_EQUIPMENT",   "ATEX Equipment / Équipement Zone ATEX",        "AE"),
    ("FILTER",           "Filter / Filtre à Panier",                      "F"),
]

MANUFACTURERS = [
    ("BAOTOU STEEL", "CN"),
    ("SUMITOMO METALS", "KR"),
    ("VALLOUREC TUBES", "FR"),
    ("TECHNIP ENERGIES", "FR"),
    ("FLASH POINT EQUIPMENTS PVT LTD", "IN"),
    ("OFFICINE NICOLA GALPERTI", "AE"),
    ("MASTER FLO VALVE INC.", "CA"),
    ("SEGITEC", "DZ"),
    ("KURVERS B.V.", "NL"),
    ("SAFT", "SE"),
    ("BHGE / BAKER HUGHES", "US"),
    ("PETROFAC LTD", "GB"),
    ("SCET ENERGIE", "DZ"),
    ("CHINA PETROLEUM PIPELINE", "CN"),
]

MATERIALS = {
    "pipe":   ["API 5L X52", "API 5L X60", "API 5L X65", "API 5L X70",
               "ASTM A333 Gr 6", "ASTM A106 Gr B"],
    "vessel": ["ASTM A350 LF2", "ASTM A105", "SA-516 Gr 70", "SA-516 Gr 60",
               "ASTM A182 F316L", "SA-387 Gr 11 Cl 2"],
    "fitting":["ASTM A234 WPB", "ASTM A420 WPL6", "ASTM A182 F11",
               "MSS SP-75 WPHY-52", "MSS SP-75 WPHY-65"],
}

ZONES = ["A (Forte Densité)", "B (Intermédiaire)", "C (Faible Densité)", "D (Désertique/Rural)"]
ZONE_FACTORS = {"A": 0.40, "B": 0.50, "C": 0.60, "D": 0.72}
ZONE_HYDRO   = {"A": 1.50, "B": 1.50, "C": 1.25, "D": 1.25}

WELDING_PROCESSES = ["SMAW", "GTAW", "GMAW", "SAW", "SMAW+GTAW", "GMAW+SAW"]
NDT_METHODS       = ["RT 100%", "UT 100%", "MT 100%", "PT 100%", "RT 75%", "RT 40%", "RT 15%"]

ATEX_ZONES    = ["Zone 0", "Zone 1", "Zone 2", "Zone 21", "Zone 22"]
ATEX_EX_CODES = ["Ex d IIB T4 Gb", "Ex e II T3 Gc", "Ex ia IIC T6 Ga",
                  "Ex d IIC T4 Gb", "Ex tD A21 IP65 T80°C"]

DECREE_REFS = {
    "hydrotest_esp":    "Décret exécutif n° 21-261 Art. 27",
    "hydrotest_canalisation": "Décret exécutif n° 21-314 Art. 21",
    "hydrotest_usine":  "Décret exécutif n° 21-315 Art. 21",
    "ndt_gaz":          "Décret exécutif n° 21-314 Art. 8",
    "ndt_liquide":      "Décret exécutif n° 21-314 Art. 9",
    "welder_qual":      "Décret exécutif n° 21-261 Art. 17 / ASME IX QW-322",
    "consular":         "Procédure ARH P-CTE-1 Part 2",
    "atex":             "Décret exécutif n° 21-257 Art. 14 / IEC/EN 60079-0",
    "algerac":          "Décret exécutif n° 24-278",
    "cev_api5l":        "API 5L Annexe H / ASME B31.8 Art. 841.11",
    "nace":             "NACE MR0175 / ISO 15156-2",
    "dft_coating":      "Spécification Technique Revêtement Sonatrach / Décret 21-315 Art. 30",
}

# ══════════════════════════════════════════════════════════════════════════════
# GÉNÉRATEURS PAR PART
# ══════════════════════════════════════════════════════════════════════════════

def _new_id(prefix: str = "REM") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6].upper()}"


def _rand_pma() -> float:
    return round(random.choice([*range(10, 250, 5)]) + random.uniform(0, 4), 1)


def _rand_temp(min_t: int = -46, max_t: int = 350) -> float:
    return float(random.randint(min_t, max_t))


def _rand_diameter(unit: str = "in") -> str:
    sizes = [2, 3, 4, 6, 8, 10, 12, 16, 18, 20, 24, 28, 30, 36, 40, 48]
    s = random.choice(sizes)
    return f'{s}"' if unit == "in" else f"{s * 25.4:.0f} mm"


def _rand_cev() -> tuple:
    C  = round(random.uniform(0.10, 0.35), 3)
    Mn = round(random.uniform(0.50, 1.50), 3)
    Si = round(random.uniform(0.10, 0.40), 3)
    P  = round(random.uniform(0.005, 0.040), 4)
    S  = round(random.uniform(0.002, 0.025), 4)
    Cr = round(random.uniform(0.01, 0.30), 3)
    Mo = round(random.uniform(0.01, 0.15), 3)
    Ni = round(random.uniform(0.01, 0.35), 3)
    Cu = round(random.uniform(0.01, 0.25), 3)
    V  = round(random.uniform(0.01, 0.08), 3)
    cev = round(C + Mn/6 + (Cr+Mo+V)/5 + (Ni+Cu)/15, 4)
    return (C, Mn, Si, P, S, Cr, Mo, Ni, Cu, V, cev)


def _make_anomaly(priority: str, category: str, title: str,
                  article: str, action: str, lang: str = "FR") -> Dict[str, Any]:
    return {
        "id":               _new_id("REM"),
        "priority":         priority,
        "category":         category,
        "title":            title,
        "article":          article,
        "action_required":  action,
    }


def _make_output(decision: str, score: float, anomalies: List[Dict]) -> str:
    count = len(anomalies)
    return json.dumps({
        "decision":         decision,
        "compliance_score": score,
        "anomalies_count":  count,
        "anomalies":        anomalies,
    }, ensure_ascii=False)


# ─── PART 4 : ÉTAT DESCRIPTIF / ANNEXE E ─────────────────────────────────────

def gen_part4_annexe_e(lang: str = "FR") -> Dict[str, Any]:
    project = random.choice(PROJECTS)
    eq_type, eq_label, eq_prefix = random.choice(EQUIPMENT_TYPES[:8])
    tag     = f"{eq_prefix}-{random.randint(100, 999)}"
    mfr, mfr_country = random.choice(MANUFACTURERS)
    pma     = _rand_pma()
    ptest   = round(pma * random.choice([1.25, 1.30, 1.43, 1.50, 1.60, 0.90]), 1)
    tmax    = _rand_temp(20, 250)
    tmin    = _rand_temp(-46, -5)
    mat     = random.choice(MATERIALS["vessel"])

    # Décider si conforme ou non
    scenario = random.choice(["compliant", "missing_fields", "inconsistent_values",
                               "wrong_pressure", "incomplete_materials"])

    anomalies = []

    if scenario == "compliant":
        decision = "CONFORME (ÉTAT DESCRIPTIF COMPLET ET COHÉRENT)"
        score    = 100.0

    elif scenario == "missing_fields":
        # Champs manquants ou 'N/A' abusif
        missing = random.sample(
            ["Pression d'épreuve", "Température minimale", "Surépaisseur corrosion",
             "Nuance acier barreaux", "Code de construction", "Fluid service"], 2)
        for field in missing:
            anomalies.append(_make_anomaly(
                "MAJOR", "ÉTAT DESCRIPTIF INCOMPLET",
                f"Champ obligatoire manquant dans l'État Descriptif (Annexe E) : '{field}'",
                "Procédure P-CTE-1 Annexe E / Décret 21-261 Art. 15",
                f"Renseigner le champ '{field}' avec la valeur réelle de l'équipement {tag}."
            ))
        decision = "NON CONFORME (ÉTAT DESCRIPTIF INCOMPLET)"
        score    = max(30.0, 100.0 - len(anomalies) * 15.0)

    elif scenario == "inconsistent_values":
        # Pression d'épreuve incohérente
        ratio    = ptest / pma
        expected = 1.50
        if ratio < expected:
            anomalies.append(_make_anomaly(
                "CRITICAL", "PRESSION D'ÉPREUVE HYDROSTATIQUE",
                f"Ratio Ptest/PMA insuffisant : {ratio:.2f} ({ptest} bar / {pma} bar) — minimum requis {expected:.2f}",
                DECREE_REFS["hydrotest_esp"],
                f"Réviser la pression d'épreuve à minimum {round(pma * expected, 1)} bar et "
                f"ré-émettre l'État Descriptif Rev 01."
            ))
        decision = "NON CONFORME (VALEURS INCOHÉRENTES DANS L'ANNEXE E)"
        score    = 45.0

    elif scenario == "wrong_pressure":
        ptest_wrong = round(pma * 0.95, 1)  # Épreuve < PMA !
        anomalies.append(_make_anomaly(
            "CRITICAL", "PRESSION D'ÉPREUVE INFÉRIEURE À LA PMA",
            f"Pression d'épreuve hydrostatique déclarée ({ptest_wrong} bar) est inférieure à la PMA ({pma} bar)",
            DECREE_REFS["hydrotest_esp"],
            f"Corriger la pression d'épreuve à minimum {round(pma * 1.50, 1)} bar (150% PMA)."
        ))
        decision = "NON CONFORME (PRESSION D'ÉPREUVE CRITIQUE)"
        score    = 20.0

    else:  # incomplete_materials
        anomalies.append(_make_anomaly(
            "MAJOR", "NUANCE MATÉRIAU NON PRÉCISÉE",
            f"La nuance d'acier '{mat}' est mentionnée sans référence à la norme ASTM/API/EN applicable",
            "EN 10204 3.1 / ASME II-D / Décret 21-261 Art. 14",
            "Préciser la norme complète avec la révision en vigueur (ex: ASTM A350 LF2 CL.1 Rev 2023)."
        ))
        decision = "NON CONFORME (DOCUMENTATION MATÉRIAU INSUFFISANTE)"
        score    = 55.0

    # Formater l'input selon la langue
    if lang == "FR":
        inp = (
            f"ÉTAT DESCRIPTIF (ANNEXE E) — AUDIT ARKAN ARH\n"
            f"Projet: {project} | Équipement TAG: {tag} ({eq_label})\n"
            f"Fabricant: {mfr} | Pays: {mfr_country}\n"
            f"Pression de Calcul (PMA): {pma} bar\n"
            f"Pression d'Épreuve: {ptest} bar\n"
            f"Température Design Max: {tmax}°C | Min (MDMT): {tmin}°C\n"
            f"Matériau Principal: {mat}\n"
            f"Code de Construction: {'ASME VIII Div.1' if 'VESSEL' in eq_type else 'API 5L / ASME B31.8'}"
        )
    elif lang == "EN":
        inp = (
            f"DESCRIPTIVE STATEMENT (ANNEX E) — ARH AUDIT\n"
            f"Project: {project} | Equipment TAG: {tag} ({eq_label})\n"
            f"Manufacturer: {mfr} | Country: {mfr_country}\n"
            f"Design Pressure (MAWP): {pma} bar\n"
            f"Hydrostatic Test Pressure: {ptest} bar\n"
            f"Design Temperature Max: {tmax}°C | Min (MDMT): {tmin}°C\n"
            f"Material Spec: {mat}\n"
            f"Design Code: {'ASME VIII Div.1' if 'VESSEL' in eq_type else 'API 5L / ASME B31.8'}"
        )
    elif lang == "AR":
        inp = (
            f"بيان وصفي (الملحق E) — تدقيق هيئة تنظيم المحروقات\n"
            f"المشروع: {project} | رمز المعدة: {tag} ({eq_label})\n"
            f"الشركة المصنّعة: {mfr} | الدولة: {mfr_country}\n"
            f"ضغط التصميم (PMA): {pma} بار\n"
            f"ضغط اختبار الضغط الهيدروستاتيكي: {ptest} بار\n"
            f"درجة حرارة التصميم القصوى: {tmax}°C | الدنيا (MDMT): {tmin}°C\n"
            f"مواصفة المادة: {mat}"
        )
    else:  # ZH
        inp = (
            f"技术描述（附录E）— ARH审查\n"
            f"项目: {project} | 设备位号: {tag}（{eq_label}）\n"
            f"制造商: {mfr} | 国家: {mfr_country}\n"
            f"设计压力 (PMA): {pma} bar\n"
            f"水压试验压力: {ptest} bar\n"
            f"最高设计温度: {tmax}°C | 最低设计温度 (MDMT): {tmin}°C\n"
            f"材料规格: {mat}"
        )

    return {
        "instruction": INSTRUCTIONS[lang],
        "input":       inp,
        "output":      _make_output(decision, score, anomalies),
        "part":        "PART_4_ANNEXE_E",
        "language":    lang,
    }


# ─── PART 5 : NOTES DE CALCUL ASME ───────────────────────────────────────────

def gen_part5_calcs(lang: str = "FR") -> Dict[str, Any]:
    project = random.choice(PROJECTS)
    eq_type, eq_label, eq_prefix = random.choice(EQUIPMENT_TYPES[:6])
    tag     = f"{eq_prefix}-{random.randint(100, 999)}"
    pma     = _rand_pma()

    # Calcul ASME VIII UG-27 ou Barlow
    is_vessel   = eq_type in ["PRESSURE_VESSEL", "SEPARATOR", "HEAT_EXCHANGER"]
    is_linepipe = eq_type in ["LINEPIPE", "PIPELINE"]

    # Paramètres de calcul
    diam_mm  = random.choice([219.1, 273.0, 323.9, 406.4, 508.0, 609.6, 762.0, 1219.2])
    stress_allowable = random.choice([137.9, 138.0, 148.3, 172.4, 189.6, 193.1])  # MPa ASME II-D
    joint_eff  = random.choice([0.85, 1.00])
    ca         = random.choice([0.0, 1.5, 2.0, 3.0, 4.0])

    # Épaisseur requise ASME VIII UG-27 : t = P*R / (S*E - 0.6*P)
    R_mm = diam_mm / 2
    P_mpa = pma / 10.0  # bar → MPa
    t_required = (P_mpa * R_mm) / (stress_allowable * joint_eff - 0.6 * P_mpa) + ca
    t_required = round(t_required, 2)
    t_proposed = round(t_required * random.choice([0.80, 0.90, 0.95, 1.00, 1.05, 1.15]), 2)

    anomalies = []
    if t_proposed < t_required:
        deficit = round(t_required - t_proposed, 2)
        anomalies.append(_make_anomaly(
            "CRITICAL", "ÉPAISSEUR MINIMALE INSUFFISANTE",
            f"Épaisseur proposée ({t_proposed} mm) insuffisante — ASME VIII UG-27 exige {t_required} mm "
            f"(déficit: {deficit} mm). PMA={pma} bar, D={diam_mm} mm, S={stress_allowable} MPa, E={joint_eff}, CA={ca} mm.",
            "ASME Section VIII Div.1 UG-27 / Décret 21-315 Art. 7",
            f"Réviser l'épaisseur nominale à minimum {math.ceil(t_required + 0.5)} mm (arrondissement au mm supérieur + marge)."
        ))

    # Pression d'épreuve hydrostatique
    p_test_required = round(pma * 1.50, 1)
    p_test_proposed = round(pma * random.choice([1.25, 1.43, 1.50, 1.55, 0.90]), 1)
    if p_test_proposed < p_test_required:
        anomalies.append(_make_anomaly(
            "CRITICAL", "PRESSION D'ÉPREUVE INSUFFISANTE",
            f"Pression d'épreuve calculée ({p_test_proposed} bar) inférieure au minimum requis "
            f"({p_test_required} bar = 150% de {pma} bar).",
            DECREE_REFS["hydrotest_esp"],
            f"Corriger la note de calcul et l'état descriptif pour mentionner {p_test_required} bar minimum."
        ))

    if anomalies:
        decision = "NON CONFORME (ERREURS DE CALCUL CRITIQUES)"
        score    = max(20.0, 100.0 - len(anomalies) * 30.0)
    else:
        decision = "CONFORME (NOTE DE CALCUL VALIDÉE)"
        score    = 100.0

    if lang == "FR":
        inp = (
            f"NOTE DE CALCUL ASME VIII DIV.1 — ÉPAISSEUR DE PAROI\n"
            f"Projet: {project} | Équipement: {tag} ({eq_label})\n"
            f"Diamètre Extérieur (D): {diam_mm} mm\n"
            f"Pression de Design (PMA): {pma} bar\n"
            f"Contrainte Admissible ASME II-D (S): {stress_allowable} MPa\n"
            f"Efficience de joint soudé (E): {joint_eff}\n"
            f"Surépaisseur de Corrosion (CA): {ca} mm\n"
            f"Épaisseur Calculée Requise: {t_required} mm\n"
            f"Épaisseur Nominale Proposée: {t_proposed} mm\n"
            f"Pression d'Épreuve Hydrostatique Proposée: {p_test_proposed} bar"
        )
    else:  # EN
        inp = (
            f"ASME VIII DIV.1 WALL THICKNESS CALCULATION NOTE\n"
            f"Project: {project} | Equipment: {tag} ({eq_label})\n"
            f"Outside Diameter (D): {diam_mm} mm\n"
            f"Design Pressure (MAWP): {pma} bar\n"
            f"Allowable Stress ASME II-D (S): {stress_allowable} MPa\n"
            f"Joint Efficiency (E): {joint_eff}\n"
            f"Corrosion Allowance (CA): {ca} mm\n"
            f"Calculated Required Thickness: {t_required} mm\n"
            f"Proposed Nominal Thickness: {t_proposed} mm\n"
            f"Proposed Hydrotest Pressure: {p_test_proposed} bar"
        )

    return {
        "instruction": INSTRUCTIONS[lang],
        "input":       inp,
        "output":      _make_output(decision, score, anomalies),
        "part":        "PART_5_CALCS",
        "language":    lang,
    }


# ─── PART 2 : LÉGALISATION CONSULAIRE ────────────────────────────────────────

def gen_part2_consular(lang: str = "FR") -> Dict[str, Any]:
    project = random.choice(PROJECTS)
    mfr, mfr_country = random.choice(MANUFACTURERS)
    tag  = f"V-{random.randint(100, 999)}"

    scenario = random.choice([
        "missing_consular_visa", "missing_cc_stamp", "expired_visa",
        "compliant_full", "missing_letter"
    ])

    anomalies = []

    if scenario == "missing_consular_visa":
        anomalies.append(_make_anomaly(
            "CRITICAL", "LÉGALISATION CONSULAIRE",
            f"Absence de légalisation par le Consulat d'Algérie à {mfr_country} sur les certificats du fabricant {mfr}",
            DECREE_REFS["consular"],
            "Faire viser et légaliser l'ensemble des certificats d'usine originaux par le Consulat d'Algérie territorialement compétent."
        ))
        decision = "NON CONFORME (REJET ADMINISTRATIF IMMÉDIAT)"
        score    = 15.0

    elif scenario == "missing_cc_stamp":
        anomalies.append(_make_anomaly(
            "CRITICAL", "CERTIFICATION CHAMBRE DE COMMERCE",
            f"Absence du cachet de la Chambre de Commerce locale ({mfr_country}) sur les documents du fabricant {mfr}",
            DECREE_REFS["consular"],
            f"Obtenir la certification de la Chambre de Commerce de {mfr_country} avant légalisation consulaire."
        ))
        decision = "NON CONFORME (CERTIFICATION CC MANQUANTE)"
        score    = 20.0

    elif scenario == "expired_visa":
        date_old = (datetime.date.today() - datetime.timedelta(days=random.randint(200, 500))).strftime("%d/%m/%Y")
        anomalies.append(_make_anomaly(
            "CRITICAL", "VISA CONSULAIRE PÉRIMÉ",
            f"Légalisation consulaire datée du {date_old} — périmée (>6 mois selon P-CTE-1 Part 2)",
            DECREE_REFS["consular"],
            "Renouveler la légalisation consulaire avec date en cours de validité."
        ))
        decision = "NON CONFORME (VISA CONSULAIRE EXPIRÉ)"
        score    = 25.0

    elif scenario == "missing_letter":
        anomalies.append(_make_anomaly(
            "CRITICAL", "LETTRE OFFICIELLE ARH",
            "Absence de la Lettre de Demande d'Avis de Conformité (Annexe B P-CTE-1) adressée au Président de l'ARH",
            "Procédure ARH P-CTE-1 Art. 4.1",
            "Transmettre la lettre officielle de demande d'avis de conformité signée par le maître d'ouvrage (GCB/SONATRACH)."
        ))
        decision = "NON CONFORME (LETTRE ARH MANQUANTE)"
        score    = 20.0

    else:  # compliant
        decision = "CONFORME (DOSSIER ADMINISTRATIF COMPLET ET LÉGALISÉ)"
        score    = 100.0

    if lang == "FR":
        inp = (
            f"AUDIT ADMINISTRATIF & LÉGALISATION ARH — CONTRÔLE D'AUTHENTICITÉ\n"
            f"Projet: {project} | Équipement: {tag}\n"
            f"Fabricant Étranger: {mfr} | Pays d'Origine: {mfr_country}\n"
            f"Lettre Annexe B P-CTE-1: {'Présente et signée' if scenario not in ['missing_letter'] else 'Absente'}\n"
            f"Chambre de Commerce Locale: {'Cachet sec original apposé' if scenario != 'missing_cc_stamp' else 'Absent'}\n"
            f"Légalisation Consulat d'Algérie: {'Tampon consulaire original' if scenario == 'compliant_full' else 'Non apposée ou périmée'}\n"
            f"Agrément Bureau Tiers (Décret 24-278): En cours de validité"
        )
    elif lang == "EN":
        inp = (
            f"ADMINISTRATIVE AUDIT & LEGALIZATION — ARH AUTHENTICATION CHECK\n"
            f"Project: {project} | Equipment: {tag}\n"
            f"Foreign Manufacturer: {mfr} | Country of Origin: {mfr_country}\n"
            f"Annex B P-CTE-1 Request Letter: {'Present and signed' if scenario != 'missing_letter' else 'Missing'}\n"
            f"Local Chamber of Commerce Stamp: {'Original dry stamp affixed' if scenario != 'missing_cc_stamp' else 'Missing'}\n"
            f"Algerian Consulate Legalization: {'Original consular stamp' if scenario == 'compliant_full' else 'Not affixed or expired'}\n"
            f"Third Party Bureau Approval (Decree 24-278): Valid"
        )
    elif lang == "AR":
        inp = (
            f"التدقيق الإداري والتصديق القنصلي — ARH\n"
            f"المشروع: {project} | المعدة: {tag}\n"
            f"الشركة المصنّعة الأجنبية: {mfr} | بلد المنشأ: {mfr_country}\n"
            f"خطاب طلب الموافقة (الملحق B P-CTE-1): {'موجود وموقّع' if scenario != 'missing_letter' else 'مفقود'}\n"
            f"التوثيق من الغرفة التجارية المحلية: {'ختم جاف أصلي' if scenario != 'missing_cc_stamp' else 'مفقود'}\n"
            f"التصديق من قنصلية الجزائر: {'ختم قنصلي أصلي' if scenario == 'compliant_full' else 'غير موجود أو منتهي الصلاحية'}"
        )
    else:  # ZH
        inp = (
            f"行政审查与领事认证 — ARH\n"
            f"项目: {project} | 设备: {tag}\n"
            f"境外制造商: {mfr} | 原产国: {mfr_country}\n"
            f"P-CTE-1附件B申请信: {'已提交并签署' if scenario != 'missing_letter' else '缺失'}\n"
            f"当地商会公章: {'已盖原件干章' if scenario != 'missing_cc_stamp' else '缺失'}\n"
            f"阿尔及利亚领事馆认证: {'原件领事章' if scenario == 'compliant_full' else '未盖章或已过期'}"
        )

    return {
        "instruction": INSTRUCTIONS[lang],
        "input":       inp,
        "output":      _make_output(decision, score, anomalies),
        "part":        "PART_2_CONSULAIRE",
        "language":    lang,
    }


# ─── PART 8 : WPS/PQR SOUDAGE ────────────────────────────────────────────────

def gen_part8_welding(lang: str = "FR") -> Dict[str, Any]:
    project  = random.choice(PROJECTS)
    process  = random.choice(WELDING_PROCESSES)
    mat      = random.choice(MATERIALS["pipe"] + MATERIALS["vessel"])
    wps_ref  = f"WPS-ARH-{random.randint(10, 99)}-{process.replace('+', '-')}"
    tag      = f"LP-{random.randint(100, 999)}"

    months_since = random.randint(0, 18)
    welder_expired = months_since > 6

    scenario = random.choice([
        "missing_pqr", "expired_welders", "both_issues",
        "compliant_full", "missing_ndt"
    ])

    anomalies = []

    if scenario in ["missing_pqr", "both_issues"]:
        anomalies.append(_make_anomaly(
            "CRITICAL", "QUALIFICATION WPS / PQR",
            f"WPS '{wps_ref}' soumis SANS le Rapport de Qualification (PQR) correspondant couvrant le matériau {mat} au procédé {process}",
            "ASME Section IX QW-200.1 / Décret 21-261 Art. 16",
            f"Joindre le PV d'essais mécaniques PQR (traction, pli, entaille) homologué par un organisme accrédité ALGERAC."
        ))

    if scenario in ["expired_welders", "both_issues"]:
        anomalies.append(_make_anomaly(
            "CRITICAL", "QUALIFICATION SOUDEURS",
            f"Certificats de Qualification Soudeurs (WOPQ) périmés — dernière activité documentée il y a {months_since} mois (>6 mois réglementaires)",
            DECREE_REFS["welder_qual"],
            "Fournir les attestations de maintien en activité semestrielles visées par le CWI/CWE ou re-qualifier les soudeurs."
        ))

    if scenario == "missing_ndt":
        ndt_method = random.choice(["RT", "UT", "MT", "PT"])
        anomalies.append(_make_anomaly(
            "MAJOR", "CONTRÔLE NON DESTRUCTIF",
            f"L'ITP ne mentionne pas de contrôle {ndt_method} 100% pour les joints d'angle — exigé par décret pour {mat}",
            "Décret 21-261 Art. 19 / ASME V Art. 2",
            f"Ajouter l'item CND {ndt_method} 100% dans l'ITP avec niveau de point d'arrêt H (TPI/ARH)."
        ))

    if anomalies:
        decision = "NON CONFORME (CAHIER SOUDAGE REJETÉ)"
        score    = max(20.0, 100.0 - len(anomalies) * 30.0)
    else:
        decision = "CONFORME (CAHIER DE SOUDAGE COMPLET ET VALIDE)"
        score    = 100.0

    if lang == "FR":
        inp = (
            f"CAHIER DE SOUDAGE ARH — AUDIT WPS/PQR/QUALIFICATIONS\n"
            f"Projet: {project} | Repère: {tag}\n"
            f"Référence WPS: {wps_ref} | Procédé: {process}\n"
            f"Matériau: {mat}\n"
            f"PQR Joint au dossier: {'Non joint ou incohérent' if scenario in ['missing_pqr', 'both_issues'] else 'Oui, complet'}\n"
            f"Dernière Qualification Soudeurs: il y a {months_since} mois\n"
            f"CND Prévu: {random.choice(NDT_METHODS)}\n"
            f"Traçabilité Heat Number: {'Confirmée sur tous les spools' if scenario == 'compliant_full' else 'Partielle'}"
        )
    else:  # EN
        inp = (
            f"WELDING DOSSIER ARH AUDIT — WPS/PQR/WELDER QUALIFICATIONS\n"
            f"Project: {project} | Equipment: {tag}\n"
            f"WPS Reference: {wps_ref} | Process: {process}\n"
            f"Base Material: {mat}\n"
            f"PQR Included: {'Missing or incoherent' if scenario in ['missing_pqr', 'both_issues'] else 'Yes, complete'}\n"
            f"Last Welder Qualification: {months_since} months ago\n"
            f"NDE Planned: {random.choice(NDT_METHODS)}\n"
            f"Heat Number Traceability: {'Confirmed on all spools' if scenario == 'compliant_full' else 'Partial'}"
        )

    return {
        "instruction": INSTRUCTIONS[lang],
        "input":       inp,
        "output":      _make_output(decision, score, anomalies),
        "part":        "PART_8_SOUDAGE",
        "language":    lang,
    }


# ─── PART 10 : ITP HOLD/WITNESS/REVIEW ──────────────────────────────────────

def gen_part10_itp(lang: str = "FR") -> Dict[str, Any]:
    project = random.choice(PROJECTS)
    eq_type, eq_label, eq_prefix = random.choice(EQUIPMENT_TYPES[:10])
    tag = f"{eq_prefix}-{random.randint(100, 999)}"

    scenario = random.choice([
        "no_hold_hydrotest", "missing_arh_tpi_parties", "wrong_hold_levels",
        "missing_arh_dossier_item", "compliant_itp"
    ])

    anomalies = []

    if scenario == "no_hold_hydrotest":
        anomalies.append(_make_anomaly(
            "CRITICAL", "POINT D'ARRÊT ÉPREUVE HYDROSTATIQUE",
            "L'épreuve hydrostatique n'est pas maintenue en Point d'Arrêt H par la TPI/ARH dans l'ITP",
            "Décret 21-261 Art. 22 / Procédure P-CTE-1",
            "Modifier l'ITP item 'Épreuve Hydrostatique' pour le reclasser en Hold Point H (TPI + ARH) — aucune dérogation possible."
        ))

    elif scenario == "missing_arh_tpi_parties":
        anomalies.append(_make_anomaly(
            "MAJOR", "PARTIES INTERVENANTES ITP",
            "Les colonnes de l'ITP ne mentionnent pas GCB, SONATRACH, TPI et ARH comme parties intervenantes distinctes",
            "Procédure P-CTE-1 / Décret 24-278 Art. 5",
            "Ajouter les colonnes GCB/SH/TPI/ARH dans l'en-tête de l'ITP et préciser le niveau d'intervention (H/W/R)."
        ))

    elif scenario == "wrong_hold_levels":
        anomalies.append(_make_anomaly(
            "MAJOR", "NIVEAUX DE POINTS D'INSPECTION",
            "Plaque signalétique maintenue en point W (Witness) — doit être en H (Hold) selon P-CTE-1, poinçonnée par TPI après test",
            "Procédure P-CTE-1 / Décret 21-261 Art. 22",
            "Reclasser l'item 'Plaque Signalétique' en Hold Point H (TPI) et préciser que le poinçon TPI est requis après épreuve hydrostatique."
        ))

    elif scenario == "missing_arh_dossier_item":
        anomalies.append(_make_anomaly(
            "MAJOR", "ITEM DOSSIER ARH PRÉLIMINAIRE MANQUANT",
            "L'ITP ne contient pas d'item spécifique pour l'approbation du Dossier ARH Préliminaire (Point d'Arrêt H obligatoire)",
            "Procédure P-CTE-1 Art. 7 / Décret 21-261 Art. 15",
            "Ajouter un item 'Approbation Dossier ARH Préliminaire' maintenu en Hold H par TPI/ARH avant tout lancement de fabrication."
        ))

    else:  # compliant
        pass

    if anomalies:
        decision = "NON CONFORME (ITP NON CONFORME P-CTE-1)"
        score    = max(40.0, 100.0 - len(anomalies) * 20.0)
    else:
        decision = "CONFORME (ITP COMPLET — POINTS H/W/R CORRECTEMENT DÉFINIS)"
        score    = 100.0

    if lang == "FR":
        inp = (
            f"PLAN D'INSPECTION ET D'ESSAI (ITP) — AUDIT ARH P-CTE-1\n"
            f"Projet: {project} | Équipement: {tag} ({eq_label})\n"
            f"Parties Intervenantes: {'GCB / SH / TPI / ARH' if scenario != 'missing_arh_tpi_parties' else 'GCB uniquement'}\n"
            f"Épreuve Hydrostatique: Niveau {'H (Hold)' if scenario not in ['no_hold_hydrotest'] else 'W (Witness) — ERREUR'}\n"
            f"Plaque Signalétique: Niveau {'H (Hold TPI)' if scenario != 'wrong_hold_levels' else 'W (Witness) — ERREUR'}\n"
            f"Dossier ARH Préliminaire: {'Item H présent' if scenario != 'missing_arh_dossier_item' else 'Item non mentionné'}\n"
            f"Type Certificats MTC: {'3.1 EN 10204' if random.random() > 0.3 else 'Type non précisé — ERREUR'}"
        )
    else:  # EN
        inp = (
            f"INSPECTION AND TEST PLAN (ITP) — ARH P-CTE-1 AUDIT\n"
            f"Project: {project} | Equipment: {tag} ({eq_label})\n"
            f"Intervening Parties: {'GCB / SH / TPI / ARH' if scenario != 'missing_arh_tpi_parties' else 'GCB only'}\n"
            f"Hydrostatic Test: Level {'H (Hold)' if scenario not in ['no_hold_hydrotest'] else 'W (Witness) — ERROR'}\n"
            f"Nameplate: Level {'H (Hold TPI)' if scenario != 'wrong_hold_levels' else 'W (Witness) — ERROR'}\n"
            f"Preliminary ARH Dossier: {'H item present' if scenario != 'missing_arh_dossier_item' else 'Item not mentioned'}\n"
            f"MTC Certificate Type: {'3.1 EN 10204' if random.random() > 0.3 else 'Type not specified — ERROR'}"
        )

    return {
        "instruction": INSTRUCTIONS[lang],
        "input":       inp,
        "output":      _make_output(decision, score, anomalies),
        "part":        "PART_10_ITP",
        "language":    lang,
    }


# ─── CERT 3.1 : CERTIFICATS MATIÈRE EN 10204 ─────────────────────────────────

def gen_cert_material(lang: str = "FR") -> Dict[str, Any]:
    project    = random.choice(PROJECTS)
    mat_type   = random.choice(list(MATERIALS.keys()))
    mat        = random.choice(MATERIALS[mat_type])
    heat_num   = f"H-{random.randint(10000, 99999)}"
    C, Mn, Si, P, S, Cr, Mo, Ni, Cu, V, cev = _rand_cev()
    reh    = random.randint(240, 450)
    rm     = random.randint(415, 760)
    elong  = round(random.uniform(18.0, 38.0), 1)
    charpy = random.randint(15, 90)
    hard   = random.randint(140, 320)

    # Limites réglementaires
    cev_limit  = 0.43
    hard_limit = 250  # HV10 NACE MR0175

    anomalies = []

    if cev > cev_limit:
        anomalies.append(_make_anomaly(
            "CRITICAL", "CARBONE ÉQUIVALENT (CEV)",
            f"CEV calculé ({cev:.3f}%) > limite réglementaire ({cev_limit}%) pour {mat}",
            DECREE_REFS["cev_api5l"],
            "Rejeter le lot ou exiger une procédure de soudage spéciale avec préchauffage élevé qualifié par PQR."
        ))

    if hard > hard_limit:
        anomalies.append(_make_anomaly(
            "CRITICAL", "DURETÉ NACE MR0175",
            f"Dureté mesurée ({hard} HV10) > limite NACE MR0175 ({hard_limit} HV10) pour service H2S",
            DECREE_REFS["nace"],
            "Réaliser un PWHT pour ramener la dureté sous 250 HV10 ou rejeter le lot."
        ))

    if reh < 240:
        anomalies.append(_make_anomaly(
            "MAJOR", "LIMITE ÉLASTIQUE",
            f"Limite élastique ReH={reh} MPa inférieure au minimum ASTM ({240} MPa) pour {mat}",
            "ASTM Standard / ASME Section II-D",
            "Refuser le certificat et demander remplacement du lot avec nouvelles éprouvettes."
        ))

    if anomalies:
        decision = "NON CONFORME (CERTIFICAT 3.1 REJETÉ)"
        score    = max(20.0, 100.0 - len(anomalies) * 25.0)
    else:
        decision = "CONFORME (CERTIFICAT 3.1 VALIDÉ)"
        score    = 100.0

    if lang == "FR":
        inp = (
            f"ANALYSE CERTIFICAT MATIÈRE EN 10204 3.1\n"
            f"Projet: {project} | N° Coulée (Heat Number): {heat_num} | Nuance: {mat}\n"
            f"Composition Chimique (% masse) :\n"
            f"  %C={C} | %Mn={Mn} | %Si={Si} | %P={P} | %S={S}\n"
            f"  %Cr={Cr} | %Mo={Mo} | %Ni={Ni} | %Cu={Cu} | %V={V}\n"
            f"CEV Calculé ARKAN: {cev:.4f}% | CEV Déclaré Usine: {round(cev + random.uniform(-0.01, 0.01), 4)}%\n"
            f"Essais Mécaniques:\n"
            f"  ReH={reh} MPa | Rm={rm} MPa | A%={elong}%\n"
            f"  Charpy KV à -46°C: {charpy} J | Dureté: {hard} HV10"
        )
    elif lang == "EN":
        inp = (
            f"MATERIAL CERTIFICATE EN 10204 3.1 ANALYSIS\n"
            f"Project: {project} | Heat Number: {heat_num} | Grade: {mat}\n"
            f"Chemical Composition (% weight):\n"
            f"  %C={C} | %Mn={Mn} | %Si={Si} | %P={P} | %S={S}\n"
            f"  %Cr={Cr} | %Mo={Mo} | %Ni={Ni} | %Cu={Cu} | %V={V}\n"
            f"ARKAN Calculated CEV: {cev:.4f}% | Mill Declared CEV: {round(cev + random.uniform(-0.01, 0.01), 4)}%\n"
            f"Mechanical Tests:\n"
            f"  ReH={reh} MPa | Rm={rm} MPa | El%={elong}%\n"
            f"  Charpy KV at -46°C: {charpy} J | Hardness: {hard} HV10"
        )
    elif lang == "AR":
        inp = (
            f"تحليل شهادة المواد EN 10204 3.1\n"
            f"المشروع: {project} | رقم الصهر (Heat Number): {heat_num} | الدرجة: {mat}\n"
            f"التركيب الكيميائي (% وزن):\n"
            f"  %C={C} | %Mn={Mn} | %Si={Si} | %P={P} | %S={S}\n"
            f"  %Cr={Cr} | %Mo={Mo} | %Ni={Ni} | %Cu={Cu} | %V={V}\n"
            f"معادل الكربون المحسوب (CEV): {cev:.4f}% | المعلن من المصنع: {round(cev + random.uniform(-0.01, 0.01), 4)}%\n"
            f"الاختبارات الميكانيكية:\n"
            f"  حد الخضوع ReH={reh} MPa | Rm={rm} MPa | الاستطالة A%={elong}%\n"
            f"  طاقة Charpy عند -46°C: {charpy} J | الصلادة: {hard} HV10"
        )
    else:  # ZH
        inp = (
            f"EN 10204 3.1 材质证书分析\n"
            f"项目: {project} | 炉号 (Heat Number): {heat_num} | 钢级: {mat}\n"
            f"化学成分（质量%）：\n"
            f"  %C={C} | %Mn={Mn} | %Si={Si} | %P={P} | %S={S}\n"
            f"  %Cr={Cr} | %Mo={Mo} | %Ni={Ni} | %Cu={Cu} | %V={V}\n"
            f"ARKAN计算碳当量 CEV: {cev:.4f}% | 工厂申报 CEV: {round(cev + random.uniform(-0.01, 0.01), 4)}%\n"
            f"力学性能：\n"
            f"  屈服强度 ReH={reh} MPa | 抗拉强度 Rm={rm} MPa | 延伸率 A%={elong}%\n"
            f"  夏比冲击功（-46°C）: {charpy} J | 硬度: {hard} HV10"
        )

    return {
        "instruction": INSTRUCTIONS[lang],
        "input":       inp,
        "output":      _make_output(decision, score, anomalies),
        "part":        "CERT_MATERIAU",
        "language":    lang,
    }


# ─── PART 11 : ATEX / IECEx ──────────────────────────────────────────────────

def gen_part11_atex(lang: str = "FR") -> Dict[str, Any]:
    project  = random.choice(PROJECTS)
    tag      = f"EP-{random.randint(100, 999)}"
    zone     = random.choice(ATEX_ZONES)
    ex_code  = random.choice(ATEX_EX_CODES)
    cert_org = random.choice(["INERIS", "LCIE", "PTB", "BASEEFA", "SIRA", "DEKRA"])

    # Date certificat
    years_old    = random.randint(0, 7)
    cert_date    = (datetime.date.today() - datetime.timedelta(days=years_old*365)).strftime("%d/%m/%Y")
    cert_expired = years_old > 5

    scenario = random.choice([
        "expired_cert", "wrong_zone", "missing_cert", "compliant_atex"
    ])

    anomalies = []

    if scenario == "expired_cert":
        anomalies.append(_make_anomaly(
            "CRITICAL", "CERTIFICAT ATEX/IECEX PÉRIMÉ",
            f"Certificat ATEX {cert_org} daté du {cert_date} — périmé (>5 ans, directive ATEX 2014/34/UE)",
            DECREE_REFS["atex"],
            "Renouveler le certificat ATEX par ré-examen UE de type par organisme notifié (INERIS, LCIE, PTB, Baseefa)."
        ))

    elif scenario == "wrong_zone":
        anomalies.append(_make_anomaly(
            "CRITICAL", "INCOMPATIBILITÉ ZONE ATEX",
            f"Équipement certifié {ex_code} — catégorie incompatible avec {zone} dans laquelle il sera installé",
            DECREE_REFS["atex"],
            f"Remplacer par un équipement certifié pour {zone} ou modifier la classification de zone."
        ))

    elif scenario == "missing_cert":
        anomalies.append(_make_anomaly(
            "CRITICAL", "ABSENCE CERTIFICAT ATEX",
            f"Aucun certificat ATEX/IECEx joint pour équipement installé en {zone}",
            "Décret exécutif n° 21-257 Art. 14 / Décret 21-261 Art. 50",
            "Fournir le certificat d'examen UE de type ATEX ou IECEx valide avec fiche technique complète."
        ))

    if anomalies:
        decision = "NON CONFORME (ÉQUIPEMENT ATEX NON CONFORME)"
        score    = max(15.0, 100.0 - len(anomalies) * 35.0)
    else:
        decision = "CONFORME (CERTIFICATION ATEX/IECEX VALIDE)"
        score    = 100.0

    if lang == "FR":
        inp = (
            f"FICHE DONNÉES ÉQUIPEMENTS ÉLECTRIQUES ATEX — AUDIT ARH\n"
            f"Projet: {project} | TAG: {tag}\n"
            f"Zone Dangereuse Classifiée: {zone}\n"
            f"Code d'Équipement ATEX: {ex_code}\n"
            f"Organisme Certificateur: {cert_org}\n"
            f"Date Certificat: {cert_date}\n"
            f"Marquage: {'Présent sur nameplate' if scenario != 'missing_cert' else 'Absent'}\n"
            f"IP Enclosure: {'IP65' if random.random() > 0.3 else 'IP54 — potentiellement insuffisant'}"
        )
    else:  # EN
        inp = (
            f"ELECTRICAL EQUIPMENT DATA SHEET ATEX — ARH AUDIT\n"
            f"Project: {project} | TAG: {tag}\n"
            f"Classified Hazardous Zone: {zone}\n"
            f"ATEX Equipment Code: {ex_code}\n"
            f"Certifying Body: {cert_org}\n"
            f"Certificate Date: {cert_date}\n"
            f"Marking: {'Present on nameplate' if scenario != 'missing_cert' else 'Missing'}\n"
            f"IP Enclosure: {'IP65' if random.random() > 0.3 else 'IP54 — potentially insufficient'}"
        )

    return {
        "instruction": INSTRUCTIONS[lang],
        "input":       inp,
        "output":      _make_output(decision, score, anomalies),
        "part":        "PART_11_ELEC",
        "language":    lang,
    }


# ─── LEVÉE DE RÉSERVES ────────────────────────────────────────────────────────

def gen_levee_reserves(lang: str = "FR") -> Dict[str, Any]:
    project  = random.choice(PROJECTS)
    ref_arh  = f"{random.randint(100, 9999)}/ARH/CT/MB-BAH/{random.randint(2023, 2026)}"
    tag      = f"V-{random.randint(100, 999)}"
    reserve  = random.choice([
        "Absence du poinçon TPI sur la plaque signalétique",
        "Essai hydrostatique non réalisé en présence du Bureau Véritas délégué par l'ARH",
        "Absence de légalisation consulaire sur certificats matière",
        "Certificats de qualification soudeurs périmés",
        "WPS soumis sans PQR correspondant",
        "Épaisseur de paroi insuffisante selon calcul ASME VIII UG-27",
    ])

    lifted   = random.choice([True, True, False])  # Plus souvent levée
    response = (
        f"Certificat TPI joint avec poinçon original apposé après épreuve hydrostatique supervisée"
        if lifted else
        f"Réponse EPC incomplète — les documents fournis ne couvrent pas la réserve ARH"
    )

    anomalies = []
    if not lifted:
        anomalies.append(_make_anomaly(
            "CRITICAL", "RÉSERVE NON LEVÉE",
            f"La réserve ARH '{reserve}' n'est PAS levée par la réponse EPC fournie",
            "Procédure P-CTE-1 / Lettre ARH Réf. " + ref_arh,
            "Compléter la réponse avec les documents justificatifs appropriés et resoumettre pour re-examen."
        ))

    decision = ("RÉSERVE LEVÉE — CONFORME" if lifted else "RÉSERVE NON LEVÉE — TOUJOURS NON CONFORME")
    score    = (100.0 if lifted else 15.0)

    if lang == "FR":
        inp = (
            f"DOSSIER DE LEVÉE DE RÉSERVES ARH\n"
            f"Projet: {project} | Équipement: {tag}\n"
            f"Lettre ARH Réf: {ref_arh}\n"
            f"Décision ARH Initiale: Non Conforme avec réserve\n"
            f"Réserve ARH: {reserve}\n"
            f"Réponse EPC: {response}\n"
            f"Documents Justificatifs Joints: {'Oui' if lifted else 'Incomplets'}"
        )
    else:  # EN
        inp = (
            f"ARH RESERVE LIFTING DOSSIER\n"
            f"Project: {project} | Equipment: {tag}\n"
            f"ARH Letter Ref: {ref_arh}\n"
            f"Initial ARH Decision: Non-Compliant with reservation\n"
            f"ARH Reserve: {reserve}\n"
            f"EPC Response: {response}\n"
            f"Supporting Documents Attached: {'Yes' if lifted else 'Incomplete'}"
        )

    return {
        "instruction": INSTRUCTIONS[lang],
        "input":       inp,
        "output":      _make_output(decision, score, anomalies),
        "part":        "LEVEE_RESERVES",
        "language":    lang,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATEUR PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

GENERATORS = [
    # (generator_func, target_count, langs)
    (gen_part4_annexe_e,  2000, ["FR", "EN", "AR", "ZH"]),
    (gen_part5_calcs,     3000, ["FR", "EN"]),
    (gen_part2_consular,   600, ["FR", "EN", "AR", "ZH"]),
    (gen_part8_welding,   2500, ["FR", "EN"]),
    (gen_part10_itp,      2000, ["FR", "EN"]),
    (gen_cert_material,   1500, ["FR", "EN", "AR", "ZH"]),
    (gen_part11_atex,     1200, ["FR", "EN"]),
    (gen_levee_reserves,  2000, ["FR", "EN"]),
]


def generate_all(output_path: Path = OUTPUT_DIR / "dataset_arh_new_22000.jsonl") -> int:
    """Génère tous les exemples et les écrit dans le fichier de sortie."""
    total = 0
    with open(output_path, "w", encoding="utf-8") as fout:
        for gen_func, target, langs in GENERATORS:
            per_lang = max(1, target // len(langs))
            count    = 0
            lang_cycle = itertools.cycle(langs)
            while count < target:
                lang = next(lang_cycle)
                try:
                    ex = gen_func(lang)
                    fout.write(json.dumps(ex, ensure_ascii=False) + "\n")
                    count += 1
                    total += 1
                except Exception as e:
                    pass  # Ignorer les erreurs ponctuelles

            print(f"[GEN] {gen_func.__name__:30s} | {count:5d} ex | langs={langs}")

    print(f"\n[GEN] TOTAL GENERE : {total} exemples -> {output_path}")
    return total


if __name__ == "__main__":
    print("[GEN] Démarrage de la génération du dataset ARH spécialisé v2.0...")
    n = generate_all()
    print(f"[GEN] Génération terminée : {n} nouveaux exemples.")
