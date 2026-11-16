"""
arh_ground_truth_extractor.py
==============================
Extracteur de Ground Truth depuis les dossiers ARH réels GCB/SONATRACH.

Scanne le chemin Z:\\Department\\Qualité\\02.ARH\\00-TECHNIQUE et :
  1. Découvre les paires (Dossier Incoming ← → Lettre/Remarques ARH Outgoing)
  2. Extrait les RÉSERVES OFFICIELLES ARH (texte rouge, annotations PDF, Excel Follow-Up)
  3. Formate chaque paire en exemple d'entraînement JSONL supervisé de haute qualité
  4. Génère dataset_arh_ground_truth.jsonl — les meilleurs exemples d'entraînement possible

Ces exemples sont de GOLD QUALITY car basés sur de vrais documents audités par l'ARH.
"""

from __future__ import annotations

import os
import re
import json
import uuid
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("ARH-GroundTruth")
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

# ── Chemins ────────────────────────────────────────────────────────────────────
ARH_ROOT   = Path(r"Z:\Department\Qualité\02.ARH\00-TECHNIQUE")
OUTPUT_GT  = Path(__file__).parent / "dataset_arh_ground_truth.jsonl"
REPORT_GT  = Path(__file__).parent / "ground_truth_extraction_report.json"

# ── Imports optionnels ─────────────────────────────────────────────────────────
try:
    import fitz  # PyMuPDF
    _HAS_FITZ = True
except ImportError:
    _HAS_FITZ = False
    logger.warning("PyMuPDF non disponible — extraction PDF désactivée.")

try:
    import pandas as pd
    _HAS_PANDAS = True
except ImportError:
    _HAS_PANDAS = False
    logger.warning("pandas non disponible — extraction Excel désactivée.")

# ══════════════════════════════════════════════════════════════════════════════
# INSTRUCTION TEMPLATE (FR + EN)
# ══════════════════════════════════════════════════════════════════════════════

INSTRUCTION_FR = (
    "Tu es l'Inspecteur Expert ARH (Autorité de Régulation des Hydrocarbures d'Algérie). "
    "Analyse ce document ARH réel et identifie TOUTES les non-conformités réglementaires "
    "selon la procédure P-CTE-1, les décrets exécutifs algériens "
    "(21-261, 21-314, 21-315, 24-278, 17-62) et les codes internationaux. "
    "Réponds sous forme d'objet JSON strict avec la décision ARH, le score et les remarques."
)

# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTION DES RÉSERVES DEPUIS LES PDFs COMMENTÉS
# ══════════════════════════════════════════════════════════════════════════════

def extract_text_from_pdf(pdf_path: Path, max_pages: int = 50) -> str:
    """Extrait le texte brut d'un PDF (limité à max_pages pour les grands dossiers)."""
    if not _HAS_FITZ:
        return ""
    try:
        doc   = fitz.open(str(pdf_path))
        pages = min(len(doc), max_pages)
        text  = "\n".join(doc[i].get_text() for i in range(pages))
        doc.close()
        return text[:12000]  # Limiter à 12k chars pour ne pas dépasser context window
    except Exception as e:
        logger.debug("Erreur PDF %s : %s", pdf_path.name, e)
        return ""


def extract_reserves_from_pdf(pdf_path: Path) -> List[str]:
    """
    Extrait les réserves ARH depuis un PDF commenté :
    - Annotations PDF (commentaires en rouge des auditeurs)
    - Textes en couleur rouge (R > 0.55, G < 0.40)
    - Mots-clés ARH: RÉSERVE, NON CONFORME, FOURNIR, ABSENCE, CORRIGER
    """
    reserves = []
    if not _HAS_FITZ:
        return reserves
    try:
        doc = fitz.open(str(pdf_path))
        for page_idx, page in enumerate(doc, 1):
            # 1. Annotations (notes, surlignages commentés)
            for annot in page.annots():
                content = (annot.info or {}).get("content", "").strip()
                if content and len(content) > 5:
                    reserves.append(f"[P{page_idx}] {content}")

            # 2. Textes en rouge (commentaires visuels des auditeurs)
            d = page.get_text("dict")
            for block in d.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        c_int = span.get("color", 0)
                        r = ((c_int >> 16) & 0xFF) / 255.0
                        g = ((c_int >> 8)  & 0xFF) / 255.0
                        b = (c_int & 0xFF) / 255.0
                        txt = span.get("text", "").strip()
                        if r > 0.55 and g < 0.40 and b < 0.40 and len(txt) > 5:
                            reserves.append(f"[P{page_idx}] {txt}")
                        elif len(txt) > 10 and any(
                            kw in txt.upper() for kw in [
                                "RÉSERVE", "RESERVE", "NON CONFORME", "FOURNIR",
                                "ABSENCE", "CORRIGER", "MANQUE", "INCOMPATIBLE",
                                "VEUILLEZ", "À PRÉCISER", "À REVOIR", "À FOURNIR",
                            ]
                        ):
                            reserves.append(f"[P{page_idx}] {txt}")
        doc.close()
    except Exception as e:
        logger.debug("Erreur extraction réserves %s : %s", pdf_path.name, e)

    # Déduplique et nettoie
    seen = set()
    clean = []
    for r in reserves:
        key = r.lower().strip()
        if key not in seen and len(key) > 10:
            seen.add(key)
            clean.append(r.strip())
    return clean


def extract_reserves_from_excel(xlsx_path: Path) -> List[str]:
    """Extrait les remarques depuis les fichiers Excel de Follow-Up ARH."""
    reserves = []
    if not _HAS_PANDAS:
        return reserves
    try:
        xl = pd.ExcelFile(str(xlsx_path))
        for sheet in xl.sheet_names:
            df = xl.parse(sheet)
            for col in df.columns:
                col_str = str(col).lower()
                if any(k in col_str for k in [
                    "comment", "remarque", "observation", "reserve",
                    "statut", "avis", "action", "description"
                ]):
                    for val in df[col].dropna().astype(str).tolist():
                        v = val.strip()
                        if len(v) > 10 and not v.startswith("http") and v.upper() != "NAN":
                            reserves.append(v)
    except Exception as e:
        logger.debug("Erreur Excel %s : %s", xlsx_path.name, e)
    return reserves


# ══════════════════════════════════════════════════════════════════════════════
# DÉCOUVERTE DES PAIRES DOSSIER / REMARQUES
# ══════════════════════════════════════════════════════════════════════════════

def _is_commented_file(name: str) -> bool:
    keywords = ["comment", "cmt", "avis", "lettre", "remarque", "reserve",
                 "retour arh", "réponse", "levee"]
    return any(k in name.lower() for k in keywords)


def discover_pairs() -> List[Dict[str, Any]]:
    """
    Parcourt Z:\\Department\\Qualité\\02.ARH\\00-TECHNIQUE et
    associe chaque dossier incoming avec ses fichiers de retour ARH.
    """
    if not ARH_ROOT.exists():
        logger.error("Chemin ARH introuvable : %s", ARH_ROOT)
        return []

    pairs = []
    projects_found = 0

    for proj_dir in sorted(ARH_ROOT.iterdir()):
        if not proj_dir.is_dir():
            continue
        projects_found += 1
        proj_name = proj_dir.name
        logger.info("[GT] Exploration : %s", proj_name)

        # Chercher tous les PDFs du dossier (max 3 niveaux)
        all_pdfs: List[Path] = []
        for root, dirs, files in os.walk(proj_dir):
            depth = len(Path(root).relative_to(proj_dir).parts)
            if depth > 4:
                dirs.clear()
                continue
            for fname in files:
                fpath = Path(root) / fname
                if fname.lower().endswith(".pdf"):
                    all_pdfs.append(fpath)

        # Séparer incoming et commentés
        incoming_pdfs = [p for p in all_pdfs if not _is_commented_file(p.name)]
        commented_pdfs = [p for p in all_pdfs if _is_commented_file(p.name)]

        # Fichiers Excel de Follow-Up
        followup_excels: List[Path] = []
        for root, _, files in os.walk(proj_dir):
            for fname in files:
                if "follow" in fname.lower() and fname.lower().endswith(".xlsx"):
                    followup_excels.append(Path(root) / fname)
            if len(followup_excels) > 10:
                break

        # Lettre ARH officielle (PDFs avec "lettre" ou "ARH" dans le nom)
        arh_letters = [
            p for p in all_pdfs
            if any(k in p.name.lower() for k in ["lettre arh", "letter arh", "avis arh"])
        ]

        for inc_pdf in incoming_pdfs[:30]:  # Limiter à 30 par projet
            pairs.append({
                "project":         proj_name,
                "incoming_pdf":    str(inc_pdf),
                "commented_pdfs":  [str(p) for p in commented_pdfs[:5]],
                "arh_letters":     [str(p) for p in arh_letters[:3]],
                "followup_excels": [str(p) for p in followup_excels[:3]],
            })

    logger.info("[GT] %d projets explorés → %d paires potentielles", projects_found, len(pairs))
    return pairs


# ══════════════════════════════════════════════════════════════════════════════
# FORMATEUR D'EXEMPLES JSONL
# ══════════════════════════════════════════════════════════════════════════════

def _classify_part_from_path(path: str) -> str:
    """Déduit la Part P-CTE-1 depuis le chemin du fichier."""
    path_upper = path.upper()
    if "WPS" in path_upper or "PQR" in path_upper or "SOUDAGE" in path_upper:
        return "PART_8_SOUDAGE"
    if "ITP" in path_upper or "INSPECTION" in path_upper:
        return "PART_10_ITP"
    if "CALCUL" in path_upper or "CALC" in path_upper or "NOTE" in path_upper:
        return "PART_5_CALCS"
    if "ATEX" in path_upper or "ELECTR" in path_upper or "IEC" in path_upper:
        return "PART_11_ELEC"
    if "DESCRIPTIF" in path_upper or "ANNEXE" in path_upper or "ETAT" in path_upper:
        return "PART_4_ANNEXE_E"
    if "CONSULAT" in path_upper or "CHAMBRE" in path_upper or "LEGAL" in path_upper:
        return "PART_2_CONSULAIRE"
    if "CERTIFICAT" in path_upper or "MATIERE" in path_upper or "EN 10204" in path_upper:
        return "CERT_MATERIAU"
    if "LEVEE" in path_upper or "LEVER" in path_upper or "RESERVE" in path_upper:
        return "LEVEE_RESERVES"
    return "GENERAL"


def reserves_to_anomalies(reserves: List[str]) -> List[Dict[str, Any]]:
    """Convertit des textes de réserves ARH en objets anomaly structurés."""
    anomalies = []
    for res in reserves:
        # Heuristique : détecter la priorité
        text_up = res.upper()
        if any(k in text_up for k in ["CRITIQUE", "CRITICAL", "REJET", "INTERDIT", "OBLIGATOIRE"]):
            priority = "CRITICAL"
        elif any(k in text_up for k in ["MAJOR", "REQUIS", "FOURNIR", "CORRIGER", "ABSENCE"]):
            priority = "MAJOR"
        else:
            priority = "MINOR"

        # Détecter la catégorie
        if "CONSULAR" in text_up or "CONSULAT" in text_up or "CHAMBRE" in text_up:
            category = "LÉGALISATION CONSULAIRE"
            article  = "Procédure ARH P-CTE-1 Part 2"
        elif "HYDROSTAT" in text_up or "ÉPREUVE" in text_up or "EPREUVE" in text_up:
            category = "ÉPREUVE HYDROSTATIQUE"
            article  = "Décret exécutif n° 21-261 Art. 27 / 21-314 Art. 21"
        elif "WPS" in text_up or "PQR" in text_up or "SOUDEUR" in text_up:
            category = "QUALIFICATION SOUDAGE"
            article  = "ASME Section IX / Décret 21-261 Art. 16-17"
        elif "ITP" in text_up or "HOLD" in text_up or "POINT D'ARRÊT" in text_up:
            category = "PLAN INSPECTION ITP"
            article  = "Procédure P-CTE-1 / Décret 21-261 Art. 22"
        elif "MATÉRIAU" in text_up or "MATERIAL" in text_up or "NUANCE" in text_up:
            category = "CERTIFICAT MATIÈRE"
            article  = "EN 10204 3.1 / ASME II-D"
        elif "ATEX" in text_up or "IEC" in text_up:
            category = "CERTIFICATION ATEX"
            article  = "IEC/EN 60079-0 / Décret 21-257 Art. 14"
        elif "PLAQUE" in text_up or "SIGNALÉTIQUE" in text_up:
            category = "PLAQUE SIGNALÉTIQUE"
            article  = "Décret 21-261 Art. 18 / EN 13445"
        else:
            category = "NON-CONFORMITÉ RÉGLEMENTAIRE"
            article  = "Procédure ARH P-CTE-1 / Décrets 21-261 / 21-314"

        # Nettoyer le texte de la réserve
        title = re.sub(r'^\[P\d+\]\s*', '', res).strip()
        if len(title) > 200:
            title = title[:200] + "..."

        anomalies.append({
            "id":              f"GT_{uuid.uuid4().hex[:6].upper()}",
            "priority":        priority,
            "category":        category,
            "title":           title,
            "article":         article,
            "action_required": "Corriger conformément aux exigences ARH P-CTE-1.",
            "source":          "GROUND_TRUTH_ARH_REAL",
        })

    return anomalies


def format_as_training_example(pair: Dict[str, Any],
                                 incoming_text: str,
                                 reserves: List[str]) -> Optional[Dict[str, Any]]:
    """
    Formate une paire (dossier_incoming + réserves ARH) en exemple JSONL.
    Retourne None si le contenu est insuffisant.
    """
    if not incoming_text.strip() or len(incoming_text) < 100:
        return None
    if not reserves:
        # Exemple CONFORME si pas de réserves et dossier non vide
        decision  = "CONFORME (DOSSIER VALIDÉ — AUCUNE RÉSERVE ARH)"
        score     = 100.0
        anomalies = []
    else:
        anomalies = reserves_to_anomalies(reserves)
        n_crit    = sum(1 for a in anomalies if a["priority"] == "CRITICAL")
        n_major   = sum(1 for a in anomalies if a["priority"] == "MAJOR")
        score     = max(5.0, round(100.0 - n_crit * 25.0 - n_major * 10.0, 1))
        if score < 60:
            decision = "NON CONFORME (RÉSERVES CRITIQUES ARH)"
        elif score < 80:
            decision = "APPROUVÉ SOUS RÉSERVES (RÉSERVES MAJEURES À LEVER)"
        else:
            decision = "APPROUVÉ AVEC COMMENTAIRES MINEURS"

    part = _classify_part_from_path(pair["incoming_pdf"])

    output_data = {
        "decision":         decision,
        "compliance_score": score,
        "anomalies_count":  len(anomalies),
        "anomalies":        anomalies,
        "source_type":      "GROUND_TRUTH_REAL_ARH_GCB",
    }

    # Tronquer l'input à 3000 chars pour rester dans le context window
    input_text = incoming_text[:3000].strip()

    return {
        "instruction": INSTRUCTION_FR,
        "input":       f"[Projet: {pair['project']}]\n\n{input_text}",
        "output":      json.dumps(output_data, ensure_ascii=False),
        "part":        part,
        "language":    "FR",
        "quality":     "GOLD",  # Marqueur qualité supérieure
        "project":     pair["project"],
    }


# ══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def extract_ground_truth() -> Dict[str, Any]:
    """
    Extrait tous les exemples Ground Truth depuis Z:\\ et génère le dataset JSONL.
    """
    pairs   = discover_pairs()
    if not pairs:
        logger.error("[GT] Aucune paire trouvée. Vérifier l'accès à %s", ARH_ROOT)
        return {"error": "no_pairs", "path": str(ARH_ROOT)}

    total_examples     = 0
    total_with_reserves = 0
    total_conforme     = 0
    errors             = 0
    part_stats: Dict[str, int] = {}

    with open(OUTPUT_GT, "w", encoding="utf-8") as fout:
        for idx, pair in enumerate(pairs):
            try:
                # 1. Extraire le texte du dossier incoming
                incoming_text = extract_text_from_pdf(Path(pair["incoming_pdf"]))

                # 2. Extraire les réserves depuis les PDFs commentés + Excel
                reserves = []
                for commented_pdf in pair.get("commented_pdfs", []):
                    reserves.extend(extract_reserves_from_pdf(Path(commented_pdf)))
                for arh_letter in pair.get("arh_letters", []):
                    reserves.extend(extract_reserves_from_pdf(Path(arh_letter)))
                for xl_path in pair.get("followup_excels", []):
                    reserves.extend(extract_reserves_from_excel(Path(xl_path)))

                # Dédupliquer
                seen = set()
                dedup_reserves = []
                for r in reserves:
                    if r.lower() not in seen:
                        seen.add(r.lower())
                        dedup_reserves.append(r)

                # 3. Formater en exemple JSONL
                ex = format_as_training_example(pair, incoming_text, dedup_reserves)
                if ex is None:
                    continue

                fout.write(json.dumps(ex, ensure_ascii=False) + "\n")
                total_examples += 1

                if dedup_reserves:
                    total_with_reserves += 1
                else:
                    total_conforme += 1

                part = ex.get("part", "UNKNOWN")
                part_stats[part] = part_stats.get(part, 0) + 1

                if (idx + 1) % 50 == 0:
                    logger.info("[GT] Traité %d/%d paires → %d exemples", idx+1, len(pairs), total_examples)

            except Exception as e:
                errors += 1
                logger.debug("[GT] Erreur paire %s : %s", pair.get("project"), e)

    report = {
        "summary": {
            "total_pairs_discovered":      len(pairs),
            "total_examples_generated":    total_examples,
            "examples_with_reserves":      total_with_reserves,
            "examples_conforme":           total_conforme,
            "errors":                      errors,
            "output_file":                 str(OUTPUT_GT),
        },
        "part_distribution": part_stats,
    }

    with open(REPORT_GT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info("=" * 60)
    logger.info("[GT] EXTRACTION TERMINÉE :")
    logger.info("  Paires explorées    : %d", len(pairs))
    logger.info("  Exemples générés    : %d", total_examples)
    logger.info("  Avec réserves ARH   : %d", total_with_reserves)
    logger.info("  Conformes (0 réserve): %d", total_conforme)
    logger.info("  Erreurs             : %d", errors)
    logger.info("  Output              : %s", OUTPUT_GT)
    logger.info("=" * 60)

    return report


if __name__ == "__main__":
    logger.info("[GT] Démarrage de l'extraction Ground Truth depuis %s ...", ARH_ROOT)
    report = extract_ground_truth()
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False))
