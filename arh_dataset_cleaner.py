"""
arh_dataset_cleaner.py
======================
Nettoie et enrichit le dataset ARH existant (dataset_arh_1500.jsonl) :

  1. Détecte et corrige les INCOHÉRENCES LOGIQUES :
       - decision = NON CONFORME  +  compliance_score = 100.0  +  anomalies = []
       - decision = CONFORME      +  compliance_score < 50.0
       - anomalies_count > 0      +  anomalies = []

  2. LABELING AUTOMATIQUE par Part P-CTE-1 :
       Chaque exemple reçoit un champ "part" indiquant la partie du dossier ARH traitée.

  3. LABELING DE LANGUE :
       Chaque exemple reçoit un champ "language" (FR / EN / AR / ZH).

  4. Génère le dataset nettoyé : dataset_arh_1500_cleaned.jsonl
     + un rapport JSON des corrections effectuées.
"""

from __future__ import annotations

import json
import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("ARH-DatasetCleaner")

INPUT_FILE  = Path(__file__).parent / "dataset_arh_1500.jsonl"
OUTPUT_FILE = Path(__file__).parent / "dataset_arh_1500_cleaned.jsonl"
REPORT_FILE = Path(__file__).parent / "arh_dataset_cleaning_report.json"

# ══════════════════════════════════════════════════════════════════════════════
# RÈGLES DE CLASSIFICATION PAR PART P-CTE-1
# ══════════════════════════════════════════════════════════════════════════════

PART_RULES: List[Tuple[str, List[str]]] = [
    ("PART_1_LETTRE",     ["LETTRE DE DEMANDE", "DEMANDE D'AVIS", "AVIS DE CONFORMITÉ",
                           "LETTER REQUESTING", "DEMANDE D AVIS", "PAGE DE GARDE",
                           "COVER PAGE", "طلب موافقة", "请求函"]),
    ("PART_2_CONSULAIRE", ["LÉGALISATION CONSULAIRE", "CONSULAT", "CHAMBRE DE COMMERCE",
                           "VISA CONSULAIRE", "CONSULAR", "LEGALIZATION",
                           "SIGNATURES DU FABRICANT", "LEGALISATION",
                           "التوثيق القنصلي", "领事认证"]),
    ("PART_3_CERTS",      ["CERTIFICAT DE CONFORMITÉ", "CERTIFICAT DE VISITE",
                           "CERTIFICATE OF CONFORMITY", "CERTIFICAT D'ORIGINE",
                           "COUNTRY OF ORIGIN", "BONNE CONSERVATION",
                           "شهادة المطابقة", "合格证书"]),
    ("PART_4_ANNEXE_E",   ["ÉTAT DESCRIPTIF", "ETAT DESCRIPTIF", "ANNEXE E",
                           "FICHE DESCRIPTIVE", "DESCRIPTIVE STATEMENT",
                           "DESIGN PRESSURE", "PRESSION DE CALCUL", "PMA", "PMS",
                           "MATÉRIAU ENVELOPPE", "MATERIAL SPECIFICATION",
                           "الوصف الفني", "技术描述"]),
    ("PART_5_CALCS",      ["NOTE DE CALCUL", "NOTES DE CALCUL", "CALCULATION",
                           "CALCUL D'ÉPAISSEUR", "ASME VIII", "UG-27", "BARLOW",
                           "ÉPAISSEUR MINIMALE", "WALL THICKNESS", "CONTRAINTE",
                           "STRESS ALLOWABLE", "حساب السماكة", "壁厚计算"]),
    ("PART_6_PLANS",      ["PLAN DÉTAILLÉ", "PLANS DÉTAILLÉS", "CARTOUCHE",
                           "GENERAL ARRANGEMENT", "GA DRAWING", "PLAN D'ENSEMBLE",
                           "INDEX DES PLANS", "DRAWING LIST", "المخططات"]),
    ("PART_8_SOUDAGE",    ["WPS", "PQR", "CAHIER DE SOUDAGE", "WELDING PROCEDURE",
                           "QUALIFICATION SOUDEUR", "WOPQ", "WQPQ", "ASME IX",
                           "ISO 9606", "PROCÉDÉ DE SOUDAGE", "TIG", "SMAW", "GMAW", "SAW",
                           "إجراء اللحام", "焊接程序"]),
    ("PART_9_PWHT",       ["TRAITEMENT THERMIQUE", "HEAT TREATMENT", "PWHT",
                           "NORMALISATION", "RECUIT", "TREMPE", "REVENU",
                           "POST WELD HEAT", "المعالجة الحرارية", "热处理"]),
    ("PART_10_ITP",       ["ITP", "PLAN D'INSPECTION", "INSPECTION AND TEST PLAN",
                           "HOLD POINT", "WITNESS POINT", "REVIEW POINT",
                           "POINT D'ARRÊT", "POINT TÉMOIN", "TPI", "ARH",
                           "خطة التفتيش", "检验测试计划"]),
    ("PART_11_ELEC",      ["ATEX", "IECEX", "IEC 60079", "ZONE EXPLOSIVE",
                           "TABLEAU HT", "TABLEAU BT", "SIL", "IEC 61439",
                           "ÉLECTRIQUE", "ELECTRICAL", "INSTRUMENTATION",
                           "الكهرباء", "电气设备"]),
    ("PART_12_CONSERV",   ["BONNE CONSERVATION", "GOOD CONSERVATION", "STOCKAGE",
                           "HUMIDITY", "AZOTE", "NITROGEN PURGE",
                           "TRANSPORT ET STOCKAGE", "التخزين"]),
    ("CERT_MATERIAU",     ["CERTIFICAT MATIÈRE", "EN 10204", "3.1", "HEAT NUMBER",
                           "NUMÉRO DE COULÉE", "COMPOSITION CHIMIQUE", "CEV",
                           "CHARPY", "RÉSILIENCE", "DURETÉ HV10",
                           "شهادة المواد", "材质证书"]),
    ("ADMIN_GLOBAL",      ["AUDIT ADMINISTRATIF", "CONTRÔLE D'AUTHENTICITÉ",
                           "DOSSIER COMPLET", "ADMINISTRATIVE AUDIT",
                           "المراجعة الإدارية"]),
    ("LEVEE_RESERVES",    ["LEVÉE DE RÉSERVES", "LEVER DE RÉSERVES", "RESERVE LIFTED",
                           "RÉPONSE EPC", "رفع التحفظات", "解除保留意见"]),
]

# ══════════════════════════════════════════════════════════════════════════════
# RÈGLES DE DÉTECTION DE LANGUE
# ══════════════════════════════════════════════════════════════════════════════

LANG_PATTERNS = {
    "AR": re.compile(r"[\u0600-\u06FF]{4,}", re.UNICODE),
    "ZH": re.compile(r"[\u4E00-\u9FFF]{3,}", re.UNICODE),
    "EN": re.compile(r"\b(PRESSURE|VESSEL|CERTIFICATE|WELDING|INSPECTION|CALCULATION|DRAWING|THICKNESS|APPROVAL|HYDROSTATIC|TEST PLAN)\b", re.IGNORECASE),
}


def detect_language(text: str) -> str:
    """Détecte la langue dominante de l'entrée."""
    if LANG_PATTERNS["AR"].search(text):
        return "AR"
    if LANG_PATTERNS["ZH"].search(text):
        return "ZH"
    en_matches = len(LANG_PATTERNS["EN"].findall(text))
    # FR est la langue par défaut si pas de signal clair EN
    if en_matches >= 3:
        return "EN"
    return "FR"


def classify_part(text: str) -> str:
    """Identifie la Part P-CTE-1 de l'exemple."""
    text_upper = text.upper()
    for part_name, keywords in PART_RULES:
        if any(kw.upper() in text_upper for kw in keywords):
            return part_name
    return "GENERAL"


def extract_output_data(output_str: str) -> Dict[str, Any]:
    """Parse le JSON de l'output."""
    try:
        return json.loads(output_str)
    except json.JSONDecodeError:
        # Tenter d'extraire le JSON même si l'output est mal formé
        match = re.search(r'\{.*\}', output_str, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def fix_inconsistency(data: Dict[str, Any], original_output: str) -> Tuple[Dict[str, Any], List[str]]:
    """
    Corrige les incohérences logiques dans l'output d'un exemple.
    Retourne (data_corrigée, [liste_des_corrections_appliquées]).
    """
    corrections = []
    decision    = data.get("decision", "").upper()
    score       = float(data.get("compliance_score", -1))
    anomalies   = data.get("anomalies", [])
    anom_count  = int(data.get("anomalies_count", len(anomalies)))

    is_conforme     = any(kw in decision for kw in ["CONFORME", "APPROVED", "APPROUVÉ"])
    is_non_conforme = any(kw in decision for kw in ["NON CONFORME", "REJECTED", "REJETÉ", "REFUS"])

    # ── Règle 1 : NON_CONFORME + score=100.0 + anomalies=[] → INCOHÉRENT ──────
    if is_non_conforme and score >= 95.0 and len(anomalies) == 0:
        data["compliance_score"] = 40.0  # Score cohérent avec NON CONFORME sans détails
        data["anomalies_count"]  = 0
        corrections.append(
            f"FIXED: NON_CONFORME + score={score} → score forcé à 40.0 (cohérence logique)"
        )

    # ── Règle 2 : CONFORME + score < 50.0 → INCOHÉRENT ───────────────────────
    elif is_conforme and score < 50.0 and score >= 0:
        data["compliance_score"] = 100.0
        data["anomalies_count"]  = 0
        data["anomalies"]        = []
        corrections.append(
            f"FIXED: CONFORME + score={score} → score forcé à 100.0 (cohérence logique)"
        )

    # ── Règle 3 : anomalies_count > 0 mais anomalies=[] → Corriger le count ──
    elif anom_count > 0 and len(anomalies) == 0:
        data["anomalies_count"] = 0
        corrections.append(
            f"FIXED: anomalies_count={anom_count} mais anomalies=[] → count forcé à 0"
        )

    # ── Règle 4 : anomalies_count != len(anomalies) ────────────────────────────
    elif anom_count != len(anomalies):
        data["anomalies_count"] = len(anomalies)
        corrections.append(
            f"FIXED: anomalies_count={anom_count} ≠ len(anomalies)={len(anomalies)} → count recalculé"
        )

    # ── Règle 5 : Score NON_CONFORME > 80.0 avec anomalies présentes → ajuster ─
    if is_non_conforme and score > 80.0 and len(anomalies) > 0:
        critical_count = sum(1 for a in anomalies if a.get("priority") == "CRITICAL")
        major_count    = sum(1 for a in anomalies if a.get("priority") == "MAJOR")
        new_score = max(0.0, 100.0 - (critical_count * 25.0) - (major_count * 10.0))
        if new_score != score:
            data["compliance_score"] = round(new_score, 1)
            corrections.append(
                f"FIXED: score={score} pour NON_CONFORME avec {critical_count} CRITICAL → score recalculé={new_score}"
            )

    return data, corrections


def clean_dataset() -> Dict[str, Any]:
    """Point d'entrée principal : nettoie le dataset et génère les fichiers de sortie."""
    if not INPUT_FILE.exists():
        logger.error("Fichier d'entrée introuvable : %s", INPUT_FILE)
        return {}

    examples = []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                examples.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning("Ligne %d : JSON invalide — %s", line_num, e)

    logger.info("Chargé %d exemples depuis %s", len(examples), INPUT_FILE)

    total_corrections  = 0
    total_labeled_part = 0
    total_labeled_lang = 0
    report_corrections = []

    cleaned_examples = []
    for idx, ex in enumerate(examples):
        instruction = ex.get("instruction", "")
        inp         = ex.get("input", "")
        output_str  = ex.get("output", "{}")
        full_text   = f"{instruction} {inp}"

        # ── 1. Classifier la Part ──────────────────────────────────────────────
        if "part" not in ex:
            ex["part"] = classify_part(full_text)
            total_labeled_part += 1

        # ── 2. Détecter la langue ──────────────────────────────────────────────
        if "language" not in ex:
            ex["language"] = detect_language(full_text)
            total_labeled_lang += 1

        # ── 3. Corriger les incohérences ──────────────────────────────────────
        output_data = extract_output_data(output_str)
        if output_data:
            fixed_data, corrections = fix_inconsistency(output_data, output_str)
            if corrections:
                ex["output"]    = json.dumps(fixed_data, ensure_ascii=False)
                ex["_fixed"]    = corrections
                total_corrections += len(corrections)
                report_corrections.append({
                    "index":       idx + 1,
                    "part":        ex.get("part"),
                    "language":    ex.get("language"),
                    "corrections": corrections,
                    "input_snippet": inp[:100] + "..." if len(inp) > 100 else inp
                })
                logger.debug("Exemple %d corrigé : %s", idx + 1, corrections)

        cleaned_examples.append(ex)

    # ── Écriture du dataset nettoyé ────────────────────────────────────────────
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for ex in cleaned_examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    # ── Statistiques par Part et par Langue ───────────────────────────────────
    part_stats: Dict[str, int] = {}
    lang_stats: Dict[str, int] = {}
    for ex in cleaned_examples:
        part = ex.get("part", "UNKNOWN")
        lang = ex.get("language", "UNKNOWN")
        part_stats[part] = part_stats.get(part, 0) + 1
        lang_stats[lang] = lang_stats.get(lang, 0) + 1

    # ── Rapport JSON ───────────────────────────────────────────────────────────
    report = {
        "summary": {
            "total_examples":        len(cleaned_examples),
            "total_corrections":     total_corrections,
            "total_labeled_part":    total_labeled_part,
            "total_labeled_lang":    total_labeled_lang,
            "output_file":           str(OUTPUT_FILE),
        },
        "part_distribution":  part_stats,
        "language_distribution": lang_stats,
        "corrections_detail": report_corrections
    }

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info("=" * 60)
    logger.info("RÉSUMÉ DU NETTOYAGE :")
    logger.info("  Total exemples     : %d", len(cleaned_examples))
    logger.info("  Corrections        : %d", total_corrections)
    logger.info("  Part labelisés     : %d", total_labeled_part)
    logger.info("  Langue labelisés   : %d", total_labeled_lang)
    logger.info("  Output             : %s", OUTPUT_FILE)
    logger.info("  Rapport            : %s", REPORT_FILE)
    logger.info("=" * 60)
    logger.info("Distribution par Part :")
    for p, n in sorted(part_stats.items(), key=lambda x: -x[1]):
        logger.info("    %-25s : %d", p, n)
    logger.info("Distribution par Langue :")
    for l, n in sorted(lang_stats.items(), key=lambda x: -x[1]):
        logger.info("    %-6s : %d", l, n)

    return report


if __name__ == "__main__":
    clean_dataset()
