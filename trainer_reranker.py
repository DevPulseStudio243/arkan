#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trainer_reranker.py
===================
Fine-tune un cross-encoder pour le re-ranking Oil & Gas.

Modèle base : cross-encoder/ms-marco-MiniLM-L-6-v2  (~80 MB)
Sortie      : models/reranker_oil_gas/

Ce modèle remplace le reranker algorithmique dans reranker.py.
Gain attendu : +15 à +25% de précision sur les questions techniques.

Hardware requis : CPU suffit (8 Go RAM), RTX 3050 accélère x3-5.
Durée estimée  : 5-15 min sur CPU, 2-5 min avec CUDA.
"""

import json
import logging
import os
import time
from pathlib import Path

import torch
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich import box
from rich.prompt import Confirm, Prompt

logger = logging.getLogger("deerflow_trainer.reranker")


class ReplayBuffer:
    """
    Tampon de rejeu (Replay Buffer) pour le Reranker.
    Stocke et échantillonne les retours d'ingénieurs (feedbacks)
    et les distillations de manière équilibrée pour éviter l'oubli catastrophique.
    """
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.buffer = []

    def add(self, item: dict):
        """Ajoute un élément au tampon, avec limitation de taille (FIFO)."""
        # Éviter les doublons exacts sur la question
        if any(x["query"] == item["query"] for x in self.buffer):
            return
        
        self.buffer.append(item)
        
        # Si le buffer dépasse la taille max, on retire les plus anciens (FIFO)
        if len(self.buffer) > self.max_size:
            self.buffer.pop(0)

    def sample(self, sample_size: int = None) -> list:
        """Échantillonne des éléments depuis le buffer."""
        import random
        if not self.buffer:
            return []
        if sample_size is None or sample_size >= len(self.buffer):
            return self.buffer
        return random.sample(self.buffer, sample_size)

    def get_stats(self) -> dict:
        counts = {"feedback": 0, "distillation": 0}
        for item in self.buffer:
            src = item.get("source", "feedback")
            counts[src] = counts.get(src, 0) + 1
        return {"total": len(self.buffer), **counts}


class RerankerTrainer:

    BASE_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self, data_dir: Path, models_dir: Path,
                 checkpoints_dir: Path, console: Console):
        self.data_dir        = data_dir
        self.models_dir      = models_dir
        self.checkpoints_dir = checkpoints_dir
        self.console         = console
        self.output_dir      = models_dir / "reranker_oil_gas"

    def _load_training_data(self) -> tuple:
        """Charge les triplets reranker depuis le JSONL."""
        path = self.data_dir / "reranker_pairs.jsonl"
        if not path.exists():
            raise FileNotFoundError(
                f"Données manquantes: {path}\n"
                "Lancez d'abord la génération de données synthétiques (mode 1)."
            )

        pairs = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                pairs.append(json.loads(line))

        # Split train / val
        split = int(len(pairs) * 0.85)
        return pairs[:split], pairs[split:]

    def _check_distillation_data(self) -> list:
        """Charge les données distillées par DeepSeek-R1 (Professeur)."""
        distill_path = Path("data/learning/local_distillation_dataset.json")
        if not distill_path.exists():
            return []

        try:
            with open(distill_path, encoding="utf-8") as f:
                records = json.load(f)
            # Les données distillées sont des dicts avec {query, answer, thought}
            # On les convertit en triplets (query, positive, negative)
            # Note: pour le négatif, on utilisera un passage aléatoire d'une autre discipline
            return records
        except Exception as e:
            logger.warning("Impossible de charger distillation dataset: %s", e)
            return []

    def _augment_with_feedback(self, train_data: list, feedback_records: list, 
                               distill_records: list = None) -> list:
        """Augmente les données d'entraînement avec le Replay Buffer (anti-oubli catastrophique)."""
        buffer = ReplayBuffer(max_size=1000)
        
        # 1. Alimenter le Replay Buffer avec les feedbacks
        for rec in (feedback_records or []):
            buffer.add({
                "query": rec["question"],
                "positive": rec["answer"],
                "source": "feedback"
            })
            
        # 2. Alimenter le Replay Buffer avec les distillations
        for rec in (distill_records or []):
            buffer.add({
                "query": rec["query"],
                "positive": rec["answer"],
                "source": "distillation"
            })
            
        # 3. Échantillonner depuis le Replay Buffer
        # Pour éviter que les retours n'écrasent le dataset principal,
        # on limite la taille de l'échantillon de rejeu à maximum 30% du dataset train d'origine
        max_samples = int(len(train_data) * 0.30)
        sampled_items = buffer.sample(sample_size=max_samples)
        
        extra = []
        import random
        for item in sampled_items:
            # Récupérer un négatif aléatoire depuis le jeu d'entraînement principal
            neg_record = train_data[random.randint(0, len(train_data) - 1)]
            extra.append({
                "query": item["query"],
                "positive": item["positive"],
                "negative": neg_record["negative"],
                "source": item["source"],
                "real_data": True,
            })
            
        augmented = train_data + extra
        
        # Affichage riche du statut du Replay Buffer
        stats = buffer.get_stats()
        self.console.print(
            f"  [green]Replay Buffer activé (Anti-oubli) :[/green] "
            f"Taille={stats['total']} | Rejeu={len(extra)} exemples mélangés (limite max: {max_samples})"
        )
        return augmented

    def run(self):
        self.console.print(
            "\n[bold cyan]═══ Fine-tuning Reranker Cross-Encoder ═══[/bold cyan]\n"
        )

        # ── Vérification dépendances ──────────────────────────
        try:
            from sentence_transformers import CrossEncoder
            from sentence_transformers.cross_encoder.evaluation import (
                CEBinaryClassificationEvaluator,
            )
            from torch.utils.data import DataLoader
        except ImportError:
            self.console.print(
                "[red]sentence-transformers non installé.\n"
                "pip install sentence-transformers[/red]"
            )
            return

        # ── Paramètres ────────────────────────────────────────
        self.console.print(Panel(
            f"[bold]Modèle base :[/bold] {self.BASE_MODEL}\n"
            f"[bold]Sortie      :[/bold] {self.output_dir}\n"
            f"[bold]CUDA        :[/bold] {'Oui (' + torch.cuda.get_device_name(0) + ')' if torch.cuda.is_available() else 'Non (CPU mode)'}\n"
            f"[bold]Durée estimée:[/bold] 5-15 min CPU / 2-5 min GPU",
            title="Configuration", border_style="blue"
        ))

        epochs     = int(Prompt.ask("Nombre d'epochs", default="5"))
        batch_size = int(Prompt.ask("Batch size", default="16"))
        max_len    = int(Prompt.ask("Longueur max tokens", default="256"))

        if not Confirm.ask("Lancer le fine-tuning ?"):
            return

        # ── Chargement données ────────────────────────────────
        self.console.print("\n[dim]Chargement des données...[/dim]")
        train_data, val_data = self._load_training_data()

        # 1. Charger feedback (via helper recréé ou direct)
        feedback_records = []
        feedback_path = Path("feedback_db.json")
        if feedback_path.exists():
            try:
                with open(feedback_path, encoding="utf-8") as f:
                    records = json.load(f)
                feedback_records = [r for r in records
                        if r.get("rating") == "good"
                        and r.get("grounding_ratio", 0) > 0.8
                        and r.get("question") and r.get("answer")]
            except Exception: pass

        # 2. Charger distillation (NIVEAU 4)
        distill_records = self._check_distillation_data()

        # Augmentation combinée
        if feedback_records or distill_records:
            train_data = self._augment_with_feedback(train_data, feedback_records, distill_records)

        self.console.print(
            f"  Train: {len(train_data)} exemples | Val: {len(val_data)} exemples"
        )

        # ── Conversion format sentence-transformers ───────────
        # Format: [(query + passage, label)] où label=1 (pertinent) ou 0 (non pertinent)
        train_samples = []
        for item in train_data:
            # Positif → label 1
            train_samples.append((
                [item["query"], item["positive"]], 1
            ))
            # Négatif → label 0
            train_samples.append((
                [item["query"], item["negative"]], 0
            ))

        val_samples = []
        for item in val_data:
            val_samples.append(([item["query"], item["positive"]], 1))
            val_samples.append(([item["query"], item["negative"]], 0))

        self.console.print(
            f"  Total paires d'entraînement: {len(train_samples)}\n"
        )

        # ── Chargement modèle ─────────────────────────────────
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console
        ) as p:
            t = p.add_task(f"Chargement {self.BASE_MODEL}...", total=None)
            try:
                model = CrossEncoder(
                    self.BASE_MODEL,
                    max_length=max_len,
                    device="cuda" if torch.cuda.is_available() else "cpu",
                )
                p.update(t, description="[green]Modèle chargé ✓[/green]")
            except Exception as e:
                self.console.print(f"[red]Erreur chargement modèle: {e}[/red]")
                self.console.print(
                    "[yellow]Vérifiez votre connexion internet (téléchargement ~80 MB)[/yellow]"
                )
                return

        # ── Préparation données ───────────────────────────────
        # Sentence-transformers CrossEncoder attend des InputExample
        from sentence_transformers import InputExample

        train_examples = [
            InputExample(texts=texts, label=float(label))
            for texts, label in train_samples
        ]

        train_loader = DataLoader(
            train_examples,
            shuffle=True,
            batch_size=batch_size,
        )

        # Évaluateur sur le jeu de validation
        val_texts  = [s[0] for s in val_samples]
        val_labels = [s[1] for s in val_samples]

        evaluator = CEBinaryClassificationEvaluator(
            sentence_pairs=val_texts,
            labels=val_labels,
            name="oil_gas_val",
        )

        # ── Entraînement ──────────────────────────────────────
        self.console.print(
            f"\n[bold]Démarrage entraînement[/bold] "
            f"({len(train_examples)} exemples × {epochs} epochs)\n"
        )

        warmup_steps = max(10, len(train_loader) // 4)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        start = time.time()

        try:
            model.fit(
                train_dataloader=train_loader,
                evaluator=evaluator,
                epochs=epochs,
                warmup_steps=warmup_steps,
                output_path=str(self.output_dir),
                show_progress_bar=True,
                save_best_model=True,
            )
            # FORCE SAVING : sentence-transformers >= 3.0 requires explicit save
            model.save(str(self.output_dir))
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Entraînement interrompu — sauvegarde du checkpoint...[/yellow]")
            model.save(str(self.output_dir / "checkpoint_interrupted"))

        elapsed = time.time() - start

        # ── Évaluation finale ─────────────────────────────────
        self.console.print(f"\n[dim]Évaluation finale...[/dim]")
        try:
            score = evaluator(model, output_path=str(self.output_dir))
            self.console.print(f"  Score validation: [bold green]{score:.4f}[/bold green]")
        except Exception as e:
            self.console.print(f"[yellow]Évaluation: {e}[/yellow]")

        # ── Résultat ──────────────────────────────────────────
        self.console.print(Panel(
            f"[bold green]✓ Reranker fine-tuné avec succès[/bold green]\n\n"
            f"Durée         : {elapsed/60:.1f} minutes\n"
            f"Modèle sauvé  : {self.output_dir}\n"
            f"Exemples train: {len(train_examples)}\n\n"
            f"[yellow]Pour utiliser ce modèle dans reranker.py :[/yellow]\n"
            f'[dim]model = CrossEncoder("{self.output_dir}")[/dim]',
            border_style="green"
        ))

        # Sauvegarder les méta-données
        meta = {
            "trained_at":     time.strftime("%Y-%m-%dT%H:%M:%S"),
            "base_model":     self.BASE_MODEL,
            "output_dir":     str(self.output_dir),
            "epochs":         epochs,
            "batch_size":     batch_size,
            "train_examples": len(train_examples),
            "val_examples":   len(val_samples),
            "elapsed_seconds": int(elapsed),
            "cuda": torch.cuda.is_available(),
        }
        with open(self.output_dir / "training_meta.json", "w") as f:
            json.dump(meta, f, indent=2)

        # ── Patch automatique de reranker.py ─────────────────
        self._patch_reranker_py()

    def _patch_reranker_py(self):
        """
        Propose de patcher reranker.py pour utiliser le nouveau modèle.
        """
        reranker_path = Path("reranker.py")
        if not reranker_path.exists():
            return

        self.console.print("\n[dim]Mise à jour de reranker.py...[/dim]")

        if not Confirm.ask(
            f"Patcher reranker.py pour utiliser le modèle fine-tuné ?",
            default=True
        ):
            return

        with open(reranker_path, encoding="utf-8") as f:
            content = f.read()

        # Ajouter l'import et la fonction neurale en haut du fichier
        neural_code = f'''
# ── Reranker neuronal fine-tuné (ajout automatique) ──────────
_NEURAL_RERANKER = None
_NEURAL_RERANKER_PATH = r"{self.output_dir}"

def get_neural_reranker():
    """Charge le cross-encoder fine-tuné sur données Oil & Gas."""
    global _NEURAL_RERANKER
    if _NEURAL_RERANKER is None:
        try:
            from sentence_transformers import CrossEncoder
            _NEURAL_RERANKER = CrossEncoder(_NEURAL_RERANKER_PATH, max_length=256)
            logger.info("Reranker neuronal chargé: %s", _NEURAL_RERANKER_PATH)
        except Exception as e:
            logger.warning("Reranker neuronal non disponible: %s", e)
    return _NEURAL_RERANKER

def neural_rerank(query: str, results: list, top_n: int = 8) -> list:
    """Reranking neuronal Oil & Gas (cross-encoder fine-tuné)."""
    if not results:
        return results
    model = get_neural_reranker()
    if model is None:
        return cross_rerank(query, results, top_n=top_n)  # fallback
    pairs = [(query, r.get("document", "")[:400]) for r in results]
    try:
        scores = model.predict(pairs)
        for i, r in enumerate(results):
            r["neural_score"] = float(scores[i])
        return sorted(results, key=lambda x: x.get("neural_score", 0), reverse=True)[:top_n]
    except Exception as e:
        logger.warning("Erreur reranker neuronal: %s", e)
        return cross_rerank(query, results, top_n=top_n)
'''

        # Ajouter après les imports / constantes du module
        if "neural_rerank" not in content:
            # Chercher plusieurs ancres connues dans reranker.py, dans l'ordre de préférence
            anchors = [
                "\ndef semantic_rerank",      # fonction principale du module
                "\ndef _lexical_rerank",       # ancien nom interne
                "\ndef cross_rerank",          # alias possible
                "\ndef rerank_by_keyword_overlap",  # nom original (peut exister dans une autre version)
                "\nclass ",                    # première classe définie
                "\ndef ",                      # première fonction définie
            ]
            insert_pos = -1
            for anchor in anchors:
                pos = content.find(anchor)
                if pos > 0:
                    insert_pos = pos
                    break

            if insert_pos > 0:
                content = content[:insert_pos] + "\n" + neural_code + "\n" + content[insert_pos:]
                with open(reranker_path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.console.print("[green]  ✓ reranker.py patché — neural_rerank() ajouté[/green]")
            else:
                # Dernier recours : ajouter à la fin du fichier
                with open(reranker_path, "a", encoding="utf-8") as f:
                    f.write("\n" + neural_code)
                self.console.print("[green]  ✓ reranker.py patché (append) — neural_rerank() ajouté[/green]")
        else:
            self.console.print("[dim]  reranker.py déjà patché[/dim]")
