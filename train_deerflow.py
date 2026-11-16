#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║     DEERFLOW LITE — MOTEUR D'ENTRAÎNEMENT & AUTO-APPRENTISSAGE  ║
║     Version 1.0 — Oil & Gas RAG Training Suite                  ║
║                                                                  ║
║  Modules :                                                       ║
║   1. Générateur de données synthétiques Oil & Gas               ║
║   2. Fine-tuning du reranker (cross-encoder)                     ║
║   3. Fine-tuning des embeddings (sentence-transformers)          ║
║   4. Entraînement du classifieur de documents                   ║
║   5. Auto-apprentissage depuis le feedback utilisateur           ║
║   6. Évaluation et benchmarking du système complet              ║
║   7. Dashboard de suivi (terminal)                               ║
╚══════════════════════════════════════════════════════════════════╝

Usage :
    python train_deerflow.py                        # Menu interactif
    python train_deerflow.py --mode synthetic       # Génère données synth.
    python train_deerflow.py --mode reranker        # Fine-tune reranker
    python train_deerflow.py --mode embeddings      # Fine-tune embeddings
    python train_deerflow.py --mode classifier      # Entraîne classifieur
    python train_deerflow.py --mode feedback        # Apprend du feedback
    python train_deerflow.py --mode eval            # Évaluation complète
    python train_deerflow.py --mode all             # Tout enchaîner

Prérequis :
    pip install sentence-transformers torch scikit-learn tqdm rich colorama
    Ollama en cours avec : llama3.1:8b + nomic-embed-text
"""

import os
import sys
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime

# ── Vérification des dépendances ─────────────────────────────
def check_deps():
    missing = []
    for pkg in ["sentence_transformers", "torch", "sklearn", "tqdm", "rich"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"\n  [ERREUR] Packages manquants: {', '.join(missing)}")
        print("  Installez avec:")
        print("  pip install sentence-transformers torch scikit-learn tqdm rich colorama\n")
        sys.exit(1)

check_deps()

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich import box
import torch

console = Console()

# ── Configuration chemins ────────────────────────────────────
BASE_DIR        = Path(__file__).parent
MODELS_DIR      = BASE_DIR / "models"
DATA_DIR        = BASE_DIR / "training_data"
LOGS_DIR        = BASE_DIR / "training_logs"
CHECKPOINTS_DIR = BASE_DIR / "checkpoints"

for d in [MODELS_DIR, DATA_DIR, LOGS_DIR, CHECKPOINTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Logging ──────────────────────────────────────────────────
log_file = LOGS_DIR / f"training_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("deerflow_trainer")

# ── Import des modules d'entraînement ────────────────────────
from trainer_synthetic  import SyntheticDataGenerator
from trainer_reranker   import RerankerTrainer
from trainer_embeddings import EmbeddingTrainer
from trainer_classifier import ClassifierTrainer
from trainer_feedback   import FeedbackLearner
from trainer_eval       import SystemEvaluator
from trainer_dashboard  import TrainingDashboard


# ╔══════════════════════════════════════════════════════════════╗
# ║                    MENU PRINCIPAL                            ║
# ╚══════════════════════════════════════════════════════════════╝

def print_banner():
    console.print()
    console.print(Panel.fit(
        Text.from_markup(
            "[bold cyan]DEERFLOW LITE[/bold cyan] [dim]v1.0[/dim]\n"
            "[yellow]Moteur d'Entraînement & Auto-Apprentissage[/yellow]\n"
            "[dim]Oil & Gas RAG — Intelligence Artificielle Spécialisée[/dim]"
        ),
        border_style="cyan",
        padding=(1, 4),
    ))
    console.print()

    # Statut hardware
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU only"
    ram = "32 GB"  # Votre config
    t = Table(show_header=False, box=box.SIMPLE, padding=(0,1))
    t.add_column(style="dim")
    t.add_column(style="bold green")
    t.add_row("GPU détecté :", gpu)
    t.add_row("CUDA disponible :", "Oui" if torch.cuda.is_available() else "Non (CPU mode)")
    t.add_row("Modèle LLM :", "llama3.1:8b (via Ollama)")
    t.add_row("Embedding :", "nomic-embed-text")
    t.add_row("Reranker base :", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    console.print(t)
    console.print()


def interactive_menu():
    """Menu interactif complet."""
    print_banner()

    options = {
        "1": ("Générer données synthétiques Oil & Gas",  "synthetic"),
        "2": ("Fine-tuner le Reranker (cross-encoder)",  "reranker"),
        "3": ("Fine-tuner les Embeddings",               "embeddings"),
        "4": ("Entraîner le Classifieur de documents",   "classifier"),
        "5": ("Apprendre depuis le Feedback utilisateur","feedback"),
        "6": ("Évaluation complète du système",          "eval"),
        "7": ("Dashboard de suivi en temps réel",        "dashboard"),
        "8": ("Pipeline complet (tout enchaîner)",       "all"),
        "0": ("Quitter",                                  "quit"),
    }

    table = Table(title="Actions disponibles", box=box.ROUNDED, border_style="cyan")
    table.add_column("N°", style="bold yellow", width=4)
    table.add_column("Action", style="white")
    table.add_column("Description rapide", style="dim")

    descriptions = {
        "1": "Crée ~2000 exemples Q/R annotés en Oil & Gas",
        "2": "Améliore la précision de classement des passages",
        "3": "Spécialise les vecteurs sur le vocabulaire O&G",
        "4": "Améliore la classification P&ID/Spec/Planning",
        "5": "Intègre les retours utilisateurs dans le modèle",
        "6": "Mesure MRR, NDCG, précision anti-hallucination",
        "7": "Suivi live des métriques d'entraînement",
        "8": "Exécute toutes les étapes dans l'ordre optimal",
        "0": "",
    }

    for key, (label, _) in options.items():
        table.add_row(key, label, descriptions.get(key, ""))

    console.print(table)
    console.print()

    choice = Prompt.ask(
        "[bold yellow]Votre choix[/bold yellow]",
        choices=list(options.keys()),
        default="1"
    )

    _, mode = options[choice]
    return mode


def run_mode(mode: str, args=None):
    """Exécute un mode d'entraînement."""

    if mode == "quit":
        console.print("\n[dim]Au revoir.[/dim]\n")
        sys.exit(0)

    if mode == "dashboard":
        dash = TrainingDashboard(LOGS_DIR)
        dash.run()
        return

    if mode == "all":
        modes = ["synthetic", "classifier", "reranker", "embeddings", "feedback", "eval"]
        console.print(Panel(
            f"[bold]Pipeline complet[/bold]\n"
            f"Étapes: {' → '.join(modes)}",
            border_style="green"
        ))
        if not args.auto:
            if not Confirm.ask("Lancer le pipeline complet ? (30-90 min)"):
                return
        for m in modes:
            console.rule(f"[cyan]Étape : {m.upper()}[/cyan]")
            run_mode(m, args)
        return

    # ── Modules individuels ───────────────────────────────────

    if mode == "synthetic":
        gen = SyntheticDataGenerator(DATA_DIR, console)
        gen.run()

    elif mode == "reranker":
        trainer = RerankerTrainer(DATA_DIR, MODELS_DIR, CHECKPOINTS_DIR, console)
        trainer.run()

    elif mode == "embeddings":
        trainer = EmbeddingTrainer(DATA_DIR, MODELS_DIR, CHECKPOINTS_DIR, console)
        trainer.run()

    elif mode == "classifier":
        trainer = ClassifierTrainer(DATA_DIR, MODELS_DIR, console)
        trainer.run()

    elif mode == "feedback":
        learner = FeedbackLearner(BASE_DIR, MODELS_DIR, console)
        learner.run()

    elif mode == "eval":
        evaluator = SystemEvaluator(BASE_DIR, MODELS_DIR, DATA_DIR, console)
        evaluator.run()


# ╔══════════════════════════════════════════════════════════════╗
# ║                     POINT D'ENTRÉE                          ║
# ╚══════════════════════════════════════════════════════════════╝

def main():
    global args
    parser = argparse.ArgumentParser(
        description="DEERFLOW LITE — Moteur d'Entraînement Oil & Gas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode",
        choices=["synthetic","reranker","embeddings","classifier",
                 "feedback","eval","dashboard","all"],
        help="Mode d'entraînement (sans argument = menu interactif)",
    )
    parser.add_argument("--auto", action="store_true",
                        help="Non-interactive mode: use defaults, skip confirmations")
    args = parser.parse_args()

    if args.mode:
        print_banner()
        run_mode(args.mode, args)
    elif args.auto:
        print_banner()
        run_mode("all", args)
    else:
        while True:
            mode = interactive_menu()
            run_mode(mode, args)
            console.print()
            if not args.auto:
                if not Confirm.ask("[dim]Retourner au menu ?[/dim]", default=True):
                    break
            else:
                break

    console.print(f"\n[dim]Logs sauvegardés dans : {log_file}[/dim]\n")


if __name__ == "__main__":
    main()
