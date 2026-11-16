#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trainer_dashboard.py
====================
Dashboard de suivi en temps réel des métriques d'entraînement.
Lit les logs et fichiers JSON produits par les autres modules.
"""

import json
import time
import os
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich.align import Align
from rich import box


class TrainingDashboard:

    def __init__(self, logs_dir: Path):
        self.logs_dir   = logs_dir
        self.models_dir = logs_dir.parent / "models"
        self.data_dir   = logs_dir.parent / "training_data"
        self.base_dir   = logs_dir.parent

    def _load_json(self, path: Path) -> dict:
        try:
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _count_jsonl(self, path: Path) -> int:
        try:
            if path.exists():
                return sum(1 for _ in open(path, encoding="utf-8"))
        except Exception:
            pass
        return 0

    def _build_dashboard(self) -> Panel:
        """Construit l'affichage du dashboard."""

        # ── Section 1: État des modèles ───────────────────────
        t_models = Table(
            title="Modèles entraînés", box=box.ROUNDED,
            border_style="cyan", title_style="bold cyan"
        )
        t_models.add_column("Modèle", style="cyan", min_width=25)
        t_models.add_column("État", justify="center")
        t_models.add_column("Date", style="dim")
        t_models.add_column("Score", justify="right")

        models = [
            ("Reranker neural",   self.models_dir / "reranker_oil_gas"),
            ("Embeddings O&G",    self.models_dir / "embeddings_oil_gas"),
            ("Classifieur ML",    self.models_dir / "classifier_oil_gas"),
        ]

        for name, path in models:
            meta_path = path / "training_meta.json"
            meta = self._load_json(meta_path)
            if meta:
                date = meta.get("trained_at", "?")[:16]
                score = meta.get("accuracy", meta.get("cv_mean", "?"))
                score_str = f"{score:.3f}" if isinstance(score, float) else str(score)
                t_models.add_row(name, "[green]✓ Entraîné[/green]", date, score_str)
            else:
                t_models.add_row(name, "[red]✗ Non entraîné[/red]", "-", "-")

        # ── Section 2: Données d'entraînement ─────────────────
        t_data = Table(
            title="Données disponibles", box=box.ROUNDED,
            border_style="blue", title_style="bold blue"
        )
        t_data.add_column("Fichier", style="blue")
        t_data.add_column("Exemples", justify="right", style="bold green")
        t_data.add_column("Source", style="dim")

        data_files = [
            ("reranker_pairs.jsonl",     "Synthétique"),
            ("embedding_pairs.jsonl",    "Synthétique"),
            ("classifier_samples.jsonl", "Synthétique"),
            ("qa_pairs.jsonl",           "Synthétique"),
            ("reranker_feedback.jsonl",  "Feedback réel"),
            ("embedding_feedback.jsonl", "Feedback réel"),
        ]

        for fname, source in data_files:
            count = self._count_jsonl(self.data_dir / fname)
            if count > 0:
                t_data.add_row(fname, str(count), source)
            else:
                t_data.add_row(fname, "[dim]0[/dim]", f"[dim]{source}[/dim]")

        # ── Section 3: Feedback stats ─────────────────────────
        fb = self._load_json(self.base_dir / "feedback_db.json")
        records = fb if isinstance(fb, list) else []

        good    = sum(1 for r in records if r.get("rating") == "good")
        bad     = sum(1 for r in records if r.get("rating") == "bad")
        pending = sum(1 for r in records if r.get("rating") == "pending")
        total   = len(records)

        satisfaction = f"{good/(good+bad)*100:.0f}%" if (good+bad) > 0 else "N/A"

        t_fb = Table(
            title="Feedback utilisateur", box=box.ROUNDED,
            border_style="yellow", title_style="bold yellow"
        )
        t_fb.add_column("Métrique", style="yellow")
        t_fb.add_column("Valeur", style="bold", justify="right")
        t_fb.add_row("Total interactions", str(total))
        t_fb.add_row("✓ Good",  f"[green]{good}[/green]")
        t_fb.add_row("✗ Bad",   f"[red]{bad}[/red]")
        t_fb.add_row("? Pending", str(pending))
        t_fb.add_row("Satisfaction", f"[bold green]{satisfaction}[/bold green]")

        # ── Section 4: Dernière évaluation ────────────────────
        eval_report = self._load_json(self.models_dir / "eval_report.json")

        t_eval = Table(
            title="Dernière évaluation", box=box.ROUNDED,
            border_style="green", title_style="bold green"
        )
        t_eval.add_column("Métrique", style="green")
        t_eval.add_column("Score", justify="right")

        if eval_report:
            date = eval_report.get("evaluated_at", "?")[:16]
            t_eval.add_row("[dim]Date[/dim]", f"[dim]{date}[/dim]")

            gr = eval_report.get("grounding", {})
            if "avg_grounding" in gr:
                v = gr["avg_grounding"]
                color = "green" if v >= 0.9 else "yellow" if v >= 0.7 else "red"
                t_eval.add_row("Grounding moyen", f"[{color}]{v:.1%}[/{color}]")

            ret = eval_report.get("retrieval", {})
            if "MRR@10" in ret:
                v = ret["MRR@10"]
                color = "green" if v >= 0.7 else "yellow" if v >= 0.5 else "red"
                t_eval.add_row("MRR@10", f"[{color}]{v:.4f}[/{color}]")

            clf = eval_report.get("classifier", {})
            ml_acc = clf.get("ml_classifier", {}).get("accuracy")
            if ml_acc:
                color = "green" if ml_acc >= 0.8 else "yellow"
                t_eval.add_row("Classifieur ML", f"[{color}]{ml_acc:.1%}[/{color}]")

            rr = eval_report.get("reranker", {})
            nn_acc = rr.get("neural", {}).get("accuracy")
            if nn_acc:
                color = "green" if nn_acc >= 0.8 else "yellow"
                t_eval.add_row("Reranker neural", f"[{color}]{nn_acc:.1%}[/{color}]")
        else:
            t_eval.add_row("[dim]Aucune évaluation[/dim]", "[dim]Lancez le mode 6[/dim]")

        # ── Assemblage ────────────────────────────────────────
        now = datetime.now().strftime("%H:%M:%S")
        header = Text.from_markup(
            f"[bold cyan]DEERFLOW LITE — Training Dashboard[/bold cyan]  "
            f"[dim]Mis à jour: {now}  |  Ctrl+C pour quitter[/dim]"
        )

        from rich.columns import Columns

        layout_content = (
            Align.center(header) ,
            "",
            Columns([t_models, t_fb], equal=False, expand=True),
            "",
            Columns([t_data, t_eval], equal=False, expand=True),
        )

        lines = []
        for item in layout_content:
            lines.append(item)

        return lines

    def run(self):
        """Affiche le dashboard et le rafraîchit toutes les 5 secondes."""
        console = Console()

        console.print(
            Panel(
                "[bold]Dashboard en temps réel[/bold]\n"
                "[dim]Rafraîchissement automatique toutes les 5 secondes\n"
                "Ctrl+C pour quitter[/dim]",
                border_style="cyan"
            )
        )

        try:
            with Live(console=console, refresh_per_second=0.2) as live:
                while True:
                    items = self._build_dashboard()
                    from rich.console import Group
                    live.update(Group(*items))
                    time.sleep(5)
        except KeyboardInterrupt:
            console.print("\n[dim]Dashboard fermé.[/dim]\n")
