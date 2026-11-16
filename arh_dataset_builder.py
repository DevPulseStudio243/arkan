"""
arh_dataset_builder.py — v1.0
=============================
Générateur de Datasets de Fine-Tuning & Adaptation de Modèles ARH (Étape 04).
Produit des jeux de données d'instruction au format JSONL (ChatML / Alpaca)
pour adapter les LLMs locaux (arkan-arh-3b, arkan-arh-14b, qwen2.5vl:3b).
"""

from __future__ import annotations
import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class ARHDatasetBuilder:
    def __init__(self, output_dir: Optional[Path] = None):
        base = Path(__file__).parent
        self.output_dir = output_dir or (base / "arh_training_data")
        self.output_dir.mkdir(exist_ok=True)

    def generate_instruction_sample(self, piece_code: str, raw_text: str, expected_contract: Dict[str, Any], decree_ref: str) -> Dict[str, Any]:
        """Génère un exemple d'entraînement ChatML / Instruction pour le fine-tuning."""
        system_prompt = (
            "Tu es ARKAN ARH Expert, agent d'inspection réglementaire de l'Autorité de Régulation "
            "des Hydrocarbures (ARH) en Algérie. Tu analyses les pièces techniques selon les Décrets 21-261, "
            "21-314 et la procédure P-CTE-1 pour extraire les métadonnées certifiées et déceler les non-conformités."
        )
        user_prompt = (
            f"Analyse l'extrait suivant de la pièce {piece_code} sous le référentiel {decree_ref}.\n"
            f"Extrais les paramètres techniques typés et valide la conformité réglementaire :\n\n"
            f"--- EXTRAIT DU DOCUMENT ---\n{raw_text[:1500]}\n--- FIN ---"
        )
        assistant_response = json.dumps(expected_contract, ensure_ascii=False, indent=2)

        return {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": assistant_response}
            ]
        }

    def build_dataset_from_dossier(self, dossier_id: str, output_filename: str = "arh_finetune_dataset.jsonl") -> str:
        """Construit un fichier JSONL d'entraînement à partir d'un dossier découpé et vérifié."""
        from arh_document_slicer import arh_slicer
        pieces = arh_slicer.get_sliced_pieces(dossier_id)
        if not pieces:
            pieces = arh_slicer.slice_dossier(dossier_id)

        target_file = self.output_dir / output_filename
        samples_count = 0

        with open(target_file, "w", encoding="utf-8") as f:
            for p in pieces:
                code = p["piece_code"]
                fields = p.get("extracted_fields", {})
                ref = p.get("regulatory_ref", "P-CTE-1")
                
                # Lire un échantillon du texte
                p_file = p["file_path"]
                text_sample = ""
                if os.path.exists(p_file):
                    try:
                        import fitz
                        with fitz.open(p_file) as doc:
                            text_sample = doc[0].get_text().strip() if len(doc) > 0 else ""
                    except Exception:
                        pass
                if not text_sample:
                    text_sample = f"Pièce réglementaire {code} : {p['piece_name']} pour projet hydrocarbures ARH."

                sample = self.generate_instruction_sample(code, text_sample, fields, ref)
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                samples_count += 1

        logger.info("[ARH-DATASET] Dataset JSONL généré : %s (%d exemples)", target_file, samples_count)
        return str(target_file)

arh_dataset_builder = ARHDatasetBuilder()
