#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trainer_embeddings.py
=====================
Fine-tune nomic-embed-text sur le vocabulaire Oil & Gas.

Technique : Contrastive Learning (triplet loss) avec hard negatives.
Durée estimée : 10-25 min CPU, 5-10 min RTX 3050.
"""

import json
import time
import logging
from pathlib import Path

import torch
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.progress import Progress, SpinnerColumn, TextColumn

logger = logging.getLogger("deerflow_trainer.embeddings")


class EmbeddingTrainer:

    # Modèle plus léger et compatible CPU/GPU entry-level
    BASE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
    # Alternative si connexion OK: "nomic-ai/nomic-embed-text-v1"

    def __init__(self, data_dir: Path, models_dir: Path,
                 checkpoints_dir: Path, console: Console):
        self.data_dir        = data_dir
        self.models_dir      = models_dir
        self.checkpoints_dir = checkpoints_dir
        self.console         = console
        self.output_dir      = models_dir / "embeddings_oil_gas"

    def _load_data(self) -> tuple:
        path = self.data_dir / "embedding_pairs.jsonl"
        if not path.exists():
            raise FileNotFoundError(
                f"Données manquantes: {path}\n"
                "Lancez d'abord la génération (mode 1)."
            )
        pairs = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                pairs.append(json.loads(line))

        split = int(len(pairs) * 0.85)
        return pairs[:split], pairs[split:]

    def _augment_with_feedback(self, train_data: list) -> list:
        """Ajoute les paires de feedback réelles à l'entraînement."""
        fb_path = Path("feedback_db.json")
        if not fb_path.exists():
            return train_data

        try:
            with open(fb_path, encoding="utf-8") as f:
                records = json.load(f)

            good = [r for r in records
                    if r.get("rating") == "good"
                    and r.get("grounding_ratio", 0) > 0.8
                    and r.get("question") and r.get("answer")]

            extra = []
            for rec in good:
                # Anchor = question, Positive = réponse, Negative = négatif aléatoire
                import random
                neg_idx = random.randint(0, len(train_data) - 1)
                # Avoid using same discipline as positive
                attempts = 0
                while train_data[neg_idx].get("discipline") == rec.get("discipline", "") and attempts < 5:
                    neg_idx = random.randint(0, len(train_data) - 1)
                    attempts += 1
                neg = train_data[neg_idx]
                extra.append({
                    "anchor":   rec["question"],
                    "positive": rec["answer"],
                    "negative": neg["negative"],
                    "discipline": "feedback",
                })

            if extra:
                self.console.print(
                    f"  [dim]+{len(extra)} exemples depuis feedback utilisateur[/dim]"
                )
            return train_data + extra

        except Exception as e:
            logger.warning("Erreur augmentation feedback: %s", e)
            return train_data

    def run(self):
        self.console.print(
            "\n[bold cyan]═══ Fine-tuning Embeddings Oil & Gas ═══[/bold cyan]\n"
        )

        try:
            from sentence_transformers import (
                SentenceTransformer, InputExample, losses,
                evaluation
            )
            from torch.utils.data import DataLoader
        except ImportError:
            self.console.print(
                "[red]sentence-transformers requis.\n"
                "pip install sentence-transformers[/red]"
            )
            return

        device = "cuda" if torch.cuda.is_available() else "cpu"

        self.console.print(Panel(
            f"[bold]Modèle base   :[/bold] {self.BASE_MODEL}\n"
            f"[bold]Sortie        :[/bold] {self.output_dir}\n"
            f"[bold]Device        :[/bold] {device.upper()}\n"
            f"[bold]Technique     :[/bold] Triplet Loss (anchor/positive/negative)\n"
            f"[bold]Durée estimée :[/bold] 10-25 min CPU / 5-10 min GPU",
            title="Configuration Embeddings", border_style="blue"
        ))

        epochs     = int(Prompt.ask("Epochs", default="4"))
        batch_size = int(Prompt.ask("Batch size", default="32"))

        if not Confirm.ask("Lancer le fine-tuning embeddings ?"):
            return

        # Chargement données
        self.console.print("\n[dim]Chargement données...[/dim]")
        train_data, val_data = self._load_data()
        train_data = self._augment_with_feedback(train_data)
        self.console.print(
            f"  Train: {len(train_data)} triplets | Val: {len(val_data)} triplets"
        )

        # Conversion InputExample
        train_examples = [
            InputExample(
                texts=[item["anchor"], item["positive"], item["negative"]]
            )
            for item in train_data
        ]

        # Évaluateur sur validation
        val_anchors   = [item["anchor"]   for item in val_data]
        val_positives = [item["positive"] for item in val_data]

        # Chargement modèle
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console
        ) as p:
            t = p.add_task(f"Chargement {self.BASE_MODEL}...", total=None)
            try:
                model = SentenceTransformer(self.BASE_MODEL, device=device)
                p.update(t, description="[green]Modèle chargé ✓[/green]")
            except Exception as e:
                self.console.print(f"[red]Erreur: {e}[/red]")
                self.console.print(
                    "[yellow]Essayez: pip install sentence-transformers --upgrade[/yellow]"
                )
                return

        train_loader = DataLoader(
            train_examples, shuffle=True, batch_size=batch_size
        )

        # Triplet loss avec margin adapté au domaine technique
        loss_fn = losses.TripletLoss(
            model=model,
            distance_metric=losses.TripletDistanceMetric.COSINE,
            triplet_margin=0.2,  # Margin plus strict pour termes techniques proches
        )

        # Évaluateur : Information Retrieval (MAP / MRR)
        ir_evaluator = evaluation.InformationRetrievalEvaluator(
            queries={str(i): q for i, q in enumerate(val_anchors[:100])},
            corpus={str(i): p for i, p in enumerate(val_positives[:100])},
            relevant_docs={str(i): {str(i)} for i in range(min(100, len(val_anchors)))},
            name="oil_gas_ir",
            map_at_k=[1, 3, 5, 10],
            mrr_at_k=[5, 10],
        )

        # Warmup
        warmup_steps = max(10, len(train_loader) * epochs // 10)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.console.print(
            f"\n[bold]Entraînement[/bold]: {len(train_examples)} triplets "
            f"× {epochs} epochs (warmup: {warmup_steps} steps)\n"
        )

        start = time.time()

        try:
            model.fit(
                train_objectives=[(train_loader, loss_fn)],
                evaluator=ir_evaluator,
                epochs=epochs,
                warmup_steps=warmup_steps,
                output_path=str(self.output_dir),
                save_best_model=True,
                show_progress_bar=True,
                checkpoint_path=str(self.checkpoints_dir / "embeddings"),
                checkpoint_save_steps=len(train_loader) * 2,
            )
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Interrompu — sauvegarde checkpoint...[/yellow]")
            model.save(str(self.output_dir / "checkpoint_interrupted"))

        elapsed = time.time() - start

        # Résumé
        self.console.print(Panel(
            f"[bold green]✓ Embeddings fine-tunés[/bold green]\n\n"
            f"Durée         : {elapsed/60:.1f} min\n"
            f"Modèle sauvé  : {self.output_dir}\n"
            f"Triplets train: {len(train_examples)}\n\n"
            f"[yellow]Utilisation dans indexer.py :[/yellow]\n"
            f"[dim]Remplacez OLLAMA_EMBED_MODEL par le chemin local\n"
            f'ou utilisez la SentenceTransformer("{self.output_dir}")[/dim]',
            border_style="green"
        ))

        # Patch de config.py pour utiliser le nouveau modèle local
        self._propose_config_patch()

        # Méta-données
        meta = {
            "trained_at":    time.strftime("%Y-%m-%dT%H:%M:%S"),
            "base_model":    self.BASE_MODEL,
            "output_dir":    str(self.output_dir),
            "epochs":        epochs,
            "batch_size":    batch_size,
            "train_triplets": len(train_examples),
            "elapsed_seconds": int(elapsed),
        }
        with open(self.output_dir / "training_meta.json", "w") as f:
            json.dump(meta, f, indent=2)

    def _propose_config_patch(self):
        """Propose d'ajouter l'embedding local dans indexer.py."""
        indexer_path = Path("indexer.py")
        if not indexer_path.exists():
            return

        if not Confirm.ask(
            "\nAjouter l'embedding local comme fallback dans indexer.py ?",
            default=True
        ):
            return

        patch_code = f'''

# ── Embedding local fine-tuné Oil & Gas (ajout automatique) ──
_LOCAL_EMBED_MODEL = None
_LOCAL_EMBED_PATH = r"{self.output_dir}"

def get_local_embedding(text: str) -> list:
    """Utilise l'embedding fine-tuné Oil & Gas si disponible."""
    global _LOCAL_EMBED_MODEL
    if _LOCAL_EMBED_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            _LOCAL_EMBED_MODEL = SentenceTransformer(_LOCAL_EMBED_PATH)
            logger.info("Embedding local O&G chargé")
        except Exception as e:
            logger.warning("Embedding local non disponible: %s", e)
            return []
    try:
        vec = _LOCAL_EMBED_MODEL.encode(text[:512], normalize_embeddings=True)
        return vec.tolist()
    except Exception as e:
        logger.warning("Erreur embedding local: %s", e)
        return []
'''
        with open(indexer_path, encoding="utf-8") as f:
            content = f.read()

        if "_LOCAL_EMBED_PATH" not in content:
            content = content + patch_code
            with open(indexer_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.console.print(
                "[green]  ✓ indexer.py patché — get_local_embedding() ajouté[/green]"
            )
