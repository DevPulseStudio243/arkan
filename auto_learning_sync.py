"""
ARKAN — Continuous Auto-Learning & Kaggle/Colab Sync Pipeline
Module: auto_learning_sync.py
Description: Extrait automatiquement les interactions de haute qualité et retours utilisateurs
depuis feedback_db.json et le moteur d'apprentissage local pour générer des jeux de données
formatés (Alpaca Instruct & ShareGPT) prêts pour le fine-tuning continu sur Kaggle et Google Colab.
"""

import os
import json
import logging
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger("arkan.auto_learning")

BASE_DIR = Path(__file__).parent.resolve()
FEEDBACK_DB_PATH = BASE_DIR / "feedback_db.json"
DISTILLATION_DATASET_PATH = BASE_DIR / "data" / "learning" / "local_distillation_dataset.json"
EXPORT_DIR = BASE_DIR / "kaggle_dataset_feedback_export"


class ContinuousLearningSync:
    """Gestionnaire de synchronisation continue et d'export de données d'entraînement."""

    def __init__(self, export_dir: Path = EXPORT_DIR):
        self.export_dir = export_dir
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def extract_validated_records(
        self,
        min_confidence: float = 0.75,
        min_grounding: float = 0.80,
        include_corrections: bool = True
    ) -> List[Dict[str, Any]]:
        """Extrait les interactions validées et positives du feedback."""
        records: List[Dict[str, Any]] = []

        if not FEEDBACK_DB_PATH.exists():
            logger.warning(f"[AutoLearning] feedback_db.json introuvable à {FEEDBACK_DB_PATH}")
            return records

        try:
            with open(FEEDBACK_DB_PATH, "r", encoding="utf-8") as f:
                fb_data = json.load(f)
                if not isinstance(fb_data, list):
                    fb_data = []
        except Exception as e:
            logger.error(f"[AutoLearning] Erreur lecture feedback_db.json: {e}")
            return records

        for item in fb_data:
            q = (item.get("question") or "").strip()
            a = (item.get("answer") or "").strip()
            corr = (item.get("user_correction") or item.get("correction") or "").strip()
            rating = item.get("rating", "pending")
            conf = float(item.get("confidence", 0.0) or 0.0)
            grounding = float(item.get("grounding_ratio", 0.0) or 0.0)

            if not q:
                continue

            # Priorité 1 : Correction explicite de l'utilisateur / expert
            if corr and include_corrections:
                records.append({
                    "id": item.get("id", f"corr_{len(records)}"),
                    "question": q,
                    "target_answer": corr,
                    "sources": item.get("sources", []),
                    "type": "user_correction",
                    "discipline": item.get("query_type", "general"),
                    "confidence": 1.0,
                    "timestamp": item.get("timestamp", datetime.now().isoformat())
                })
                continue

            # Priorité 2 : Notation positive explicite ('good')
            if rating == "good" and a:
                records.append({
                    "id": item.get("id", f"good_{len(records)}"),
                    "question": q,
                    "target_answer": a,
                    "sources": item.get("sources", []),
                    "type": "positive_rating",
                    "discipline": item.get("query_type", "general"),
                    "confidence": max(conf, 0.95),
                    "timestamp": item.get("timestamp", datetime.now().isoformat())
                })
                continue

            # Priorité 3 : Haute confiance et ancrage documentaire élevé sans note 'bad'
            if rating != "bad" and a and (conf >= min_confidence or grounding >= min_grounding):
                records.append({
                    "id": item.get("id", f"highconf_{len(records)}"),
                    "question": q,
                    "target_answer": a,
                    "sources": item.get("sources", []),
                    "type": "high_confidence_auto",
                    "discipline": item.get("query_type", "general"),
                    "confidence": conf,
                    "timestamp": item.get("timestamp", datetime.now().isoformat())
                })

        # Enrichissement optionnel avec distillation locale si présente
        if DISTILLATION_DATASET_PATH.exists():
            try:
                with open(DISTILLATION_DATASET_PATH, "r", encoding="utf-8") as f:
                    distill_items = json.load(f)
                    if isinstance(distill_items, list):
                        for di in distill_items:
                            if "question" in di and "answer" in di:
                                records.append({
                                    "id": f"distill_{len(records)}",
                                    "question": di["question"],
                                    "target_answer": di["answer"],
                                    "sources": di.get("sources", ["Distillation"]),
                                    "type": "teacher_distillation",
                                    "discipline": di.get("discipline", "general"),
                                    "confidence": 0.90,
                                    "timestamp": datetime.now().isoformat()
                                })
            except Exception as e_dist:
                logger.warning(f"[AutoLearning] Impossible de charger la distillation locale: {e_dist}")

        logger.info(f"[AutoLearning] {len(records)} enregistrements de haute qualité extraits.")
        return records

    def export_datasets(self) -> Dict[str, Any]:
        """Génère et sauvegarde les jeux de données formatés pour Kaggle & Colab."""
        records = self.extract_validated_records()

        # Format 1 : Alpaca Instruct
        alpaca_dataset = []
        for r in records:
            sources_str = ", ".join(r.get("sources", [])[:3])
            input_context = f"Contexte & Sources : {sources_str}" if sources_str else ""
            alpaca_dataset.append({
                "instruction": r["question"],
                "input": input_context,
                "output": r["target_answer"],
                "metadata": {
                    "id": r["id"],
                    "provenance": r["type"],
                    "confidence": r["confidence"],
                    "discipline": r["discipline"]
                }
            })

        # Format 2 : ShareGPT multi-turn / instruct
        sharegpt_dataset = []
        for r in records:
            sharegpt_dataset.append({
                "id": f"arkan-{r['id']}",
                "conversations": [
                    {
                        "from": "system",
                        "value": "Tu es ARKAN, l'assistant expert en ingénierie EPC, pétrole, gaz et réglementation industrielle algérienne (ARH)."
                    },
                    {
                        "from": "human",
                        "value": r["question"]
                    },
                    {
                        "from": "gpt",
                        "value": r["target_answer"]
                    }
                ]
            })

        # Format 3 : Métadonnées pour Dataset Kaggle
        dataset_metadata = {
            "title": "ARKAN EPC Continuous Fine-Tuning Dataset",
            "id": "arkan-intelligence/arkan-epc-feedback-dataset",
            "licenses": [{"name": "CC-BY-4.0"}],
            "description": f"Ensemble de données continuellement mis à jour à partir des interactions expertes et validations de terrain du système ARKAN EPC (export du {datetime.now().strftime('%Y-%m-%d %H:%M')}).",
            "keywords": ["oil-and-gas", "epc", "fine-tuning", "algeria", "sonatrach", "qwen2-5"]
        }

        # Écriture des fichiers
        instruct_file = self.export_dir / "feedback_instruct_dataset.json"
        sharegpt_file = self.export_dir / "feedback_sharegpt_dataset.json"
        metadata_file = self.export_dir / "dataset-metadata.json"

        with open(instruct_file, "w", encoding="utf-8") as f:
            json.dump(alpaca_dataset, f, ensure_ascii=False, indent=2)

        with open(sharegpt_file, "w", encoding="utf-8") as f:
            json.dump(sharegpt_dataset, f, ensure_ascii=False, indent=2)

        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(dataset_metadata, f, ensure_ascii=False, indent=2)

        result_summary = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "total_extracted": len(records),
            "breakdown": {
                "user_corrections": sum(1 for r in records if r["type"] == "user_correction"),
                "positive_ratings": sum(1 for r in records if r["type"] == "positive_rating"),
                "high_confidence_auto": sum(1 for r in records if r["type"] == "high_confidence_auto"),
                "teacher_distillation": sum(1 for r in records if r["type"] == "teacher_distillation"),
            },
            "exported_files": {
                "alpaca_instruct": str(instruct_file),
                "sharegpt": str(sharegpt_file),
                "kaggle_metadata": str(metadata_file)
            },
            "file_sizes_bytes": {
                "instruct": instruct_file.stat().st_size if instruct_file.exists() else 0,
                "sharegpt": sharegpt_file.stat().st_size if sharegpt_file.exists() else 0
            },
            "kaggle_colab_ready": True
        }

        logger.info(f"[AutoLearning] Export terminé : {result_summary['total_extracted']} exemples générés.")
        return result_summary

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les métriques actuelles sur le jeu de données d'apprentissage."""
        total_fb = 0
        good_fb = 0
        bad_fb = 0
        pending_fb = 0

        if FEEDBACK_DB_PATH.exists():
            try:
                with open(FEEDBACK_DB_PATH, "r", encoding="utf-8") as f:
                    fb = json.load(f)
                    if isinstance(fb, list):
                        total_fb = len(fb)
                        good_fb = sum(1 for i in fb if i.get("rating") == "good")
                        bad_fb = sum(1 for i in fb if i.get("rating") == "bad")
                        pending_fb = sum(1 for i in fb if i.get("rating") == "pending")
            except Exception:
                pass

        instruct_path = self.export_dir / "feedback_instruct_dataset.json"
        exported_samples = 0
        last_export = None
        if instruct_path.exists():
            try:
                with open(instruct_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    exported_samples = len(data)
                last_export = datetime.fromtimestamp(instruct_path.stat().st_mtime).isoformat()
            except Exception:
                pass

        hot_reloaded = False
        try:
            import sys
            import importlib
            if "auto_indexer" in sys.modules:
                sys.modules["auto_indexer"]._EXCLUDED_DIRS.add("procurement_contracts")
            if "procurement_db" in sys.modules:
                importlib.reload(sys.modules["procurement_db"])
            if "arh_nuextract_engine" in sys.modules:
                mod_nu = importlib.reload(sys.modules["arh_nuextract_engine"])
                if "routes.procurement_router" in sys.modules:
                    mod_pr = importlib.reload(sys.modules["routes.procurement_router"])
                    mod_pr.arh_nuextract_engine = mod_nu.arh_nuextract_engine
                    if "api_enhanced" in sys.modules and hasattr(sys.modules["api_enhanced"], "app"):
                        app_inst = sys.modules["api_enhanced"].app
                        existing_paths = {getattr(r, "path", "") for r in app_inst.routes}
                        if "/procurement/projects" not in existing_paths:
                            app_inst.include_router(mod_pr.router)
                hot_reloaded = True
        except Exception as e_hr:
            logger.warning(f"[AutoLearning] Hot-reload warning: {e_hr}")

        return {
            "feedback_db_total": total_fb,
            "feedback_good": good_fb,
            "feedback_bad": bad_fb,
            "feedback_pending": pending_fb,
            "exported_samples_ready": exported_samples,
            "last_export_timestamp": last_export,
            "export_directory": str(self.export_dir),
            "engine_hot_reloaded": hot_reloaded
        }


auto_learning_manager = ContinuousLearningSync()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = auto_learning_manager.export_datasets()
    print("\n=== RÉSULTAT DE L'EXPORT AUTO-LEARNING ===")
    print(json.dumps(res, indent=2, ensure_ascii=False))
