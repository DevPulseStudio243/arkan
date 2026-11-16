"""
arh_dataset_merger.py
======================
Fusionne tous les datasets ARH disponibles en un seul fichier JSONL
prêt pour l'upload sur Kaggle et l'entraînement fine-tuning.

Sources fusionnées :
  1. dataset_arh_1500_cleaned.jsonl     — Dataset nettoyé (1 500 ex)
  2. dataset_arh_new_22000.jsonl        — Dataset généré v2 (~22 000 ex)
  3. dataset_arh_ground_truth.jsonl     — Ground truth réels GCB (Gold, x3)
  4. arh_quality_comments_db.json       — Commentaires qualité réels GCB

Sortie :
  dataset_arh_kaggle_full.jsonl         — Dataset complet pour Kaggle
  dataset_arh_stats.json                — Statistiques détaillées

Usage :
  python arh_dataset_merger.py

Puis uploader dataset_arh_kaggle_full.jsonl sur Kaggle comme Dataset.
"""

from __future__ import annotations

import json
import random
import logging
from pathlib import Path
from typing import Dict, List, Any
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("ARH-Merger")

DATA_DIR    = Path(__file__).parent
OUTPUT_FILE = DATA_DIR / "dataset_arh_kaggle_full.jsonl"
STATS_FILE  = DATA_DIR / "dataset_arh_stats.json"
SEED        = 42
random.seed(SEED)

# ══════════════════════════════════════════════════════════════════════════════
# CHARGEURS DE SOURCES
# ══════════════════════════════════════════════════════════════════════════════

def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Charge un fichier JSONL."""
    examples = []
    if not path.exists():
        logger.warning("Fichier introuvable : %s", path)
        return examples
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                examples.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.debug("Ligne %d invalide dans %s : %s", line_num, path.name, e)
    return examples


def load_quality_comments(path: Path) -> List[Dict[str, Any]]:
    """
    Charge arh_quality_comments_db.json et convertit en exemples JSONL.
    Ce fichier contient de vraies remarques ARH de GCB.
    """
    if not path.exists():
        logger.warning("Fichier introuvable : %s", path)
        return []

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    examples = []
    INSTRUCTION = (
        "Tu es l'Inspecteur Expert ARH. Analyse ce dossier constructeur et "
        "identifie les non-conformités réglementaires selon P-CTE-1. Réponds en JSON strict."
    )

    # Adapter selon la structure réelle du fichier
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = list(raw.values()) if isinstance(list(raw.values())[0], dict) else [raw]
    else:
        return []

    for item in items:
        # Tenter différentes structures possibles du fichier
        input_text = (
            item.get("document_text") or
            item.get("content") or
            item.get("text") or
            item.get("input") or
            json.dumps(item.get("metadata", {}), ensure_ascii=False)
        )[:3000]

        anomalies_raw = (
            item.get("comments") or item.get("reserves") or
            item.get("remarques") or item.get("anomalies") or []
        )

        if not input_text or len(input_text) < 20:
            continue

        # Convertir en anomalies structurées
        structured_anomalies = []
        for a in (anomalies_raw if isinstance(anomalies_raw, list) else [anomalies_raw]):
            if isinstance(a, str) and len(a) > 5:
                structured_anomalies.append({
                    "priority": "MAJOR",
                    "category": "NON-CONFORMITÉ ARH",
                    "title": a[:200],
                    "article": "Procédure P-CTE-1",
                    "action_required": "Corriger conformément aux exigences ARH.",
                    "source": "QUALITY_COMMENTS_DB"
                })
            elif isinstance(a, dict):
                structured_anomalies.append(a)

        n_anom = len(structured_anomalies)
        score  = max(10.0, 100.0 - n_anom * 20.0) if n_anom else 100.0
        decision = "NON CONFORME" if n_anom > 0 else "CONFORME"

        output_data = {
            "decision":         decision,
            "compliance_score": score,
            "anomalies_count":  n_anom,
            "anomalies":        structured_anomalies,
        }

        examples.append({
            "instruction": INSTRUCTION,
            "input":       input_text,
            "output":      json.dumps(output_data, ensure_ascii=False),
            "part":        "GENERAL",
            "language":    "FR",
            "quality":     "GOLD",
            "source":      "QUALITY_COMMENTS_DB",
        })

    logger.info("Chargé %d exemples depuis quality_comments_db", len(examples))
    return examples


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION DES EXEMPLES
# ══════════════════════════════════════════════════════════════════════════════

def validate_example(ex: Dict[str, Any]) -> bool:
    """Valide qu'un exemple est exploitable pour l'entraînement."""
    instruction = ex.get("instruction", "").strip()
    inp         = ex.get("input", "").strip()
    output      = ex.get("output", "").strip()

    # Vérifications de base
    if len(instruction) < 20:
        return False
    if len(output) < 10:
        return False
    if len(inp) < 10:
        return False

    # Vérifier que l'output est du JSON valide
    try:
        parsed = json.loads(output)
        # Vérifier les champs obligatoires
        if "decision" not in parsed:
            return False
        score = parsed.get("compliance_score", -1)
        if score is None or float(score) < 0 or float(score) > 100:
            return False
    except (json.JSONDecodeError, ValueError, TypeError):
        return False

    return True


def sanitize_example(ex: Dict[str, Any]) -> Dict[str, Any]:
    """Nettoie et normalise un exemple pour l'entraînement."""
    # S'assurer que tous les champs requis sont présents
    clean = {
        "instruction": ex.get("instruction", "").strip(),
        "input":       ex.get("input", "").strip()[:4096],  # Tronquer si trop long
        "output":      ex.get("output", "").strip(),
        "part":        ex.get("part", "GENERAL"),
        "language":    ex.get("language", "FR"),
        "quality":     ex.get("quality", "STANDARD"),
    }

    # Supprimer les champs internes de debug
    for key in list(ex.keys()):
        if key.startswith("_"):
            pass  # Ne pas inclure

    return clean


# ══════════════════════════════════════════════════════════════════════════════
# ÉQUILIBRAGE DU DATASET
# ══════════════════════════════════════════════════════════════════════════════

def balance_dataset(examples: List[Dict[str, Any]], max_per_part: int = 3000) -> List[Dict[str, Any]]:
    """
    Équilibre le dataset par Part pour éviter les déséquilibres.
    Les exemples GOLD sont conservés en priorité.
    """
    by_part: Dict[str, List] = {}
    for ex in examples:
        part = ex.get("part", "GENERAL")
        by_part.setdefault(part, []).append(ex)

    balanced = []
    for part, part_examples in by_part.items():
        # Trier : GOLD en premier
        gold     = [e for e in part_examples if e.get("quality") == "GOLD"]
        standard = [e for e in part_examples if e.get("quality") != "GOLD"]

        # Mélanger
        random.shuffle(standard)

        # Prendre max_per_part exemples (Gold en priorité)
        selected = gold[:max_per_part] + standard[:max(0, max_per_part - len(gold))]
        balanced.extend(selected)

        logger.info("  Part %-25s : %5d ex (%d gold, %d standard)",
                    part, len(selected), min(len(gold), max_per_part), len(selected) - min(len(gold), max_per_part))

    return balanced


# ══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def merge_all() -> Dict[str, Any]:
    """
    Fusionne toutes les sources de données et génère le dataset Kaggle.
    """
    logger.info("=" * 60)
    logger.info("FUSION DES DATASETS ARH")
    logger.info("=" * 60)

    all_examples = []

    # ── Source 1 : Dataset nettoyé existant ────────────────────────────────────
    cleaned = load_jsonl(DATA_DIR / "dataset_arh_1500_cleaned.jsonl")
    logger.info("[1] Dataset nettoyé      : %d exemples", len(cleaned))
    all_examples.extend(cleaned)

    # ── Source 2 : Dataset généré v2 ──────────────────────────────────────────
    generated = load_jsonl(DATA_DIR / "dataset_arh_new_22000.jsonl")
    logger.info("[2] Dataset généré v2    : %d exemples", len(generated))
    all_examples.extend(generated)

    # ── Source 3 : Ground Truth réels (x3 pour upsampling) ────────────────────
    ground_truth = load_jsonl(DATA_DIR / "dataset_arh_ground_truth.jsonl")
    logger.info("[3] Ground Truth réels   : %d exemples (x3 upsampling)", len(ground_truth))
    all_examples.extend(ground_truth * 3)  # Répéter les exemples Gold

    # ── Source 4 : Commentaires Qualité DB ────────────────────────────────────
    quality_comments = load_quality_comments(DATA_DIR / "arh_quality_comments_db.json")
    logger.info("[4] Quality Comments DB  : %d exemples (x3)", len(quality_comments))
    all_examples.extend(quality_comments * 3)

    logger.info("\n[TOTAL] %d exemples avant validation", len(all_examples))

    # ── Validation ─────────────────────────────────────────────────────────────
    valid_examples = []
    invalid_count  = 0
    for ex in all_examples:
        if validate_example(ex):
            valid_examples.append(sanitize_example(ex))
        else:
            invalid_count += 1

    logger.info("[VALIDATION] %d valides, %d invalides ignorés", len(valid_examples), invalid_count)

    # ── Équilibrage par Part ────────────────────────────────────────────────────
    logger.info("\n[ÉQUILIBRAGE] Par Part (max 3000/part) :")
    balanced = balance_dataset(valid_examples, max_per_part=3000)

    # ── Mélange final ───────────────────────────────────────────────────────────
    random.shuffle(balanced)
    logger.info("\n[FINAL] %d exemples prêts pour l'entraînement", len(balanced))

    # ── Statistiques finales ────────────────────────────────────────────────────
    part_counts = Counter(ex.get("part", "UNKNOWN")     for ex in balanced)
    lang_counts = Counter(ex.get("language", "UNKNOWN") for ex in balanced)
    qual_counts = Counter(ex.get("quality", "UNKNOWN")  for ex in balanced)

    # ── Écriture du dataset Kaggle ──────────────────────────────────────────────
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for ex in balanced:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    logger.info("[OUTPUT] %s (%d exemples)", OUTPUT_FILE, len(balanced))

    # ── Rapport ────────────────────────────────────────────────────────────────
    stats = {
        "total_examples": len(balanced),
        "sources": {
            "cleaned_dataset":  len(cleaned),
            "generated_v2":     len(generated),
            "ground_truth_gold": len(ground_truth),
            "quality_comments": len(quality_comments),
        },
        "part_distribution":     dict(sorted(part_counts.items(), key=lambda x: -x[1])),
        "language_distribution": dict(sorted(lang_counts.items(), key=lambda x: -x[1])),
        "quality_distribution":  dict(sorted(qual_counts.items(), key=lambda x: -x[1])),
        "output_file": str(OUTPUT_FILE),
        "invalid_examples_skipped": invalid_count,
    }

    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    logger.info("\n" + "=" * 60)
    logger.info("RÉSUMÉ FINAL :")
    logger.info("  Total exemples     : %d", len(balanced))
    logger.info("  Langue FR          : %d", lang_counts.get("FR", 0))
    logger.info("  Langue EN          : %d", lang_counts.get("EN", 0))
    logger.info("  Langue AR          : %d", lang_counts.get("AR", 0))
    logger.info("  Langue ZH          : %d", lang_counts.get("ZH", 0))
    logger.info("  Qualité GOLD       : %d", qual_counts.get("GOLD", 0))
    logger.info("  Qualité STANDARD   : %d", qual_counts.get("STANDARD", 0))
    logger.info("  Output             : %s", OUTPUT_FILE)
    logger.info("=" * 60)
    logger.info("\n[PROCHAINE ETAPE] : Uploader '%s' sur Kaggle", OUTPUT_FILE.name)
    logger.info("   -> https://www.kaggle.com/datasets/add")

    return stats


if __name__ == "__main__":
    stats = merge_all()
    print("\n[DISTRIBUTION PAR PART] :")
    for part, count in stats["part_distribution"].items():
        bar = "#" * (count // 50)
        print(f"  {part:30s} {count:6,} {bar}")
