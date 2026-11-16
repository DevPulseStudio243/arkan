#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trainer_classifier.py
=====================
Entraîne un classifieur de documents Oil & Gas (TF-IDF + LinearSVC).

Classes : process, mechanical, piping, instrumentation,
          electrical, safety, planning

Avantages vs classifieur par règles (classifier.py) :
  - Apprend les patterns implicites du corpus réel
  - Moins de faux positifs sur les documents mixtes
  - Se ré-entraîne automatiquement avec de nouvelles données

Durée : 30s - 2 min (CPU, pas de GPU requis)
"""

import json
import time
import logging
import pickle
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Confirm, Prompt
from rich import box

logger = logging.getLogger("deerflow_trainer.classifier")


class ClassifierTrainer:

    def __init__(self, data_dir: Path, models_dir: Path, console: Console):
        self.data_dir   = data_dir
        self.models_dir = models_dir
        self.console    = console
        self.output_dir = models_dir / "classifier_oil_gas"

    def _load_data(self) -> tuple:
        """Charge les exemples pour le classifieur."""
        path = self.data_dir / "classifier_samples.jsonl"
        if not path.exists():
            raise FileNotFoundError(
                f"Données manquantes: {path}\n"
                "Lancez d'abord la génération (mode 1)."
            )

        texts, labels = [], []
        with open(path, encoding="utf-8") as f:
            for line in f:
                item = json.loads(line)
                texts.append(item["text"])
                labels.append(item["label"])

        # Augmenter avec les données ChromaDB réelles si disponibles
        texts, labels = self._augment_with_real_docs(texts, labels)

        return texts, labels

    def _augment_with_real_docs(self, texts: list, labels: list) -> tuple:
        """Charge les documents réels indexés dans ChromaDB pour enrichir."""
        try:
            import chromadb
            from config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION

            client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
            collection = client.get_collection(CHROMA_COLLECTION)
            all_data = collection.get(
                include=["documents", "metadatas"],
                limit=2000
            )

            docs = all_data.get("documents", [])
            metas = all_data.get("metadatas", [])

            added = 0
            for doc, meta in zip(docs, metas):
                disc = meta.get("discipline", "")
                if doc and disc and disc in [
                    "process","mechanical","piping","instrumentation",
                    "electrical","safety","planning","general"
                ]:
                    texts.append(doc[:1000])
                    labels.append(disc)
                    added += 1

            if added > 0:
                self.console.print(
                    f"  [dim]+{added} exemples réels depuis ChromaDB[/dim]"
                )

        except Exception as e:
            logger.debug("ChromaDB non disponible pour augmentation: %s", e)

        return texts, labels

    def run(self):
        self.console.print(
            "\n[bold cyan]═══ Entraînement Classifieur de Documents ═══[/bold cyan]\n"
        )

        try:
            from sklearn.pipeline import Pipeline
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.svm import LinearSVC
            from sklearn.linear_model import LogisticRegression
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.model_selection import train_test_split, cross_val_score
            from sklearn.metrics import (
                classification_report, confusion_matrix, accuracy_score
            )
            import numpy as np
        except ImportError:
            self.console.print("[red]scikit-learn requis: pip install scikit-learn[/red]")
            return

        self.console.print(Panel(
            "[bold]Algorithme :[/bold] TF-IDF + LinearSVC (optimal pour texte technique)\n"
            "[bold]Fallback   :[/bold] Logistic Regression (plus stable, moins rapide)\n"
            "[bold]Validation :[/bold] 15% hold-out + cross-validation 5-fold\n"
            "[bold]Durée      :[/bold] 30 secondes — 2 minutes",
            title="Configuration Classifieur", border_style="blue"
        ))

        model_choice = Prompt.ask(
            "Algorithme",
            choices=["svm", "logreg", "both"],
            default="both"
        )

        if not Confirm.ask("Lancer l'entraînement du classifieur ?"):
            return

        # Chargement
        self.console.print("\n[dim]Chargement données...[/dim]")
        texts, labels = self._load_data()

        # Stats par classe
        from collections import Counter
        label_counts = Counter(labels)
        table = Table(title="Distribution des classes", box=box.SIMPLE)
        table.add_column("Discipline", style="cyan")
        table.add_column("Exemples", style="bold green", justify="right")
        for disc, count in sorted(label_counts.items()):
            table.add_row(disc, str(count))
        table.add_row("[bold]TOTAL[/bold]", f"[bold]{len(labels)}[/bold]")
        self.console.print(table)

        # Split
        X_train, X_test, y_train, y_test = train_test_split(
            texts, labels, test_size=0.15, random_state=42, stratify=labels
        )
        self.console.print(
            f"\n  Train: {len(X_train)} | Test: {len(X_test)}\n"
        )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        results = {}

        # ── Pipeline TF-IDF ───────────────────────────────────
        # Paramètres optimisés pour texte technique Oil & Gas
        tfidf_params = dict(
            sublinear_tf=True,       # Normalisation logarithmique
            min_df=2,                # Ignorer les termes très rares
            max_df=0.9,              # Ignorer les termes trop communs
            ngram_range=(1, 3),      # Unigrammes + bigrammes + trigrammes
            analyzer="word",
            max_features=50000,      # Limite pour performance
            # Conserver les tags techniques (P-101, API 610, etc.)
            token_pattern=r"(?u)\b[\w\-\.&\/]+\b",
        )

        models_to_train = []
        if model_choice in ("svm", "both"):
            models_to_train.append((
                "SVM (LinearSVC)",
                Pipeline([
                    ("tfidf", TfidfVectorizer(**tfidf_params)),
                    ("clf", LinearSVC(
                        C=1.0,
                        max_iter=2000,
                        class_weight="balanced",  # Gère les classes déséquilibrées
                    )),
                ])
            ))

        if model_choice in ("logreg", "both"):
            models_to_train.append((
                "Logistic Regression",
                Pipeline([
                    ("tfidf", TfidfVectorizer(**tfidf_params)),
                    ("clf", LogisticRegression(
                        C=1.0,
                        max_iter=1000,
                        class_weight="balanced",
                        solver="saga",

                    )),
                ])
            ))

        best_model = None
        best_score = 0.0
        best_name  = ""

        for name, pipeline in models_to_train:
            self.console.print(f"\n[bold]Entraînement : {name}[/bold]")

            start = time.time()
            pipeline.fit(X_train, y_train)
            train_time = time.time() - start

            # Prédictions test
            y_pred = pipeline.predict(X_test)
            acc = accuracy_score(y_test, y_pred)

            # Cross-validation
            cv_scores = cross_val_score(
                pipeline, X_train, y_train, cv=5, scoring="accuracy", n_jobs=-1
            )

            results[name] = {
                "accuracy":   acc,
                "cv_mean":    cv_scores.mean(),
                "cv_std":     cv_scores.std(),
                "train_time": train_time,
            }

            # Rapport détaillé
            self.console.print(f"  Accuracy test  : [bold green]{acc:.3f}[/bold green]")
            self.console.print(
                f"  CV 5-fold      : {cv_scores.mean():.3f} ± {cv_scores.std():.3f}"
            )
            self.console.print(f"  Temps train    : {train_time:.1f}s")

            # Classification report
            report = classification_report(y_test, y_pred, output_dict=True)
            t2 = Table(box=box.SIMPLE)
            t2.add_column("Discipline", style="cyan")
            t2.add_column("Précision", justify="right")
            t2.add_column("Rappel",    justify="right")
            t2.add_column("F1",        justify="right")
            for disc in sorted(label_counts.keys()):
                if disc in report:
                    r = report[disc]
                    color = "green" if r["f1-score"] >= 0.8 else "yellow" if r["f1-score"] >= 0.6 else "red"
                    t2.add_row(
                        disc,
                        f"{r['precision']:.3f}",
                        f"{r['recall']:.3f}",
                        f"[{color}]{r['f1-score']:.3f}[/{color}]",
                    )
            self.console.print(t2)

            if acc > best_score:
                best_score = acc
                best_model = pipeline
                best_name  = name

        # Sauvegarder le meilleur modèle
        if best_model:
            model_path = self.output_dir / "classifier_model.pkl"
            with open(model_path, "wb") as f:
                pickle.dump(best_model, f)

            self.console.print(Panel(
                f"[bold green]✓ Meilleur classifieur sauvegardé[/bold green]\n\n"
                f"Modèle  : {best_name}\n"
                f"Accuracy: [bold green]{best_score:.3f}[/bold green]\n"
                f"Fichier : {model_path}\n\n"
                f"[yellow]Pour utiliser dans classifier.py :[/yellow]\n"
                f"[dim]import pickle\n"
                f'model = pickle.load(open("{model_path}", "rb"))\n'
                f"disc = model.predict([text])[0][/dim]",
                border_style="green"
            ))

            # Méta-données
            meta = {
                "trained_at":   datetime.now().isoformat(),
                "best_model":   best_name,
                "accuracy":     best_score,
                "train_size":   len(X_train),
                "test_size":    len(X_test),
                "classes":      sorted(label_counts.keys()),
                "results":      results,
            }
            with open(self.output_dir / "training_meta.json", "w") as f:
                json.dump(meta, f, indent=2, default=str)

            # Patch classifier.py
            self._patch_classifier(model_path, list(label_counts.keys()))

    def _patch_classifier(self, model_path: Path, classes: list):
        """Ajoute le classifieur ML comme priorité dans classifier.py."""
        clf_path = Path("classifier.py")
        if not clf_path.exists():
            return

        if not Confirm.ask(
            "\nPatcher classifier.py pour utiliser le modèle ML en priorité ?",
            default=True
        ):
            return

        patch = f'''

# ── Classifieur ML fine-tuné (ajout automatique) ─────────────
import pickle as _pickle
_ML_CLASSIFIER = None
_ML_CLASSIFIER_PATH = r"{model_path}"

def _load_ml_classifier():
    global _ML_CLASSIFIER
    if _ML_CLASSIFIER is None:
        try:
            with open(_ML_CLASSIFIER_PATH, "rb") as _f:
                _ML_CLASSIFIER = _pickle.load(_f)
            logger.info("Classifieur ML Oil & Gas chargé")
        except Exception as _e:
            logger.warning("Classifieur ML non disponible: %s", _e)
    return _ML_CLASSIFIER

def classify_document_ml(text: str, filename: str = "") -> dict:
    """Classifieur ML Oil & Gas (prioritaire sur les règles)."""
    clf = _load_ml_classifier()
    if clf is None:
        return classify_document(text, filename)  # Fallback règles

    try:
        label = clf.predict([text[:2000]])[0]
        try:
            if hasattr(clf, "predict_proba"):
                proba = clf.predict_proba([text[:2000]])[0]
                confidence = float(max(proba))
            elif hasattr(clf, "decision_function"):
                import numpy as np
                decision = clf.decision_function([text[:2000]])[0]
                if isinstance(decision, (list, np.ndarray)):
                    confidence = float(1.0 / (1.0 + np.exp(-max(decision))))
                else:
                    confidence = float(1.0 / (1.0 + np.exp(-decision)))
            else:
                confidence = 0.75
        except Exception:
            confidence = 0.75
        return {{
            "discipline": label,
            "confidence": round(confidence, 2),
            "matched_keywords": [],
            "method": "ml_classifier",
        }}
    except Exception as e:
        logger.warning("Erreur classifieur ML: %s", e)
        return classify_document(text, filename)
'''

        with open(clf_path, encoding="utf-8") as f:
            content = f.read()

        if "_ML_CLASSIFIER_PATH" not in content:
            content = content + patch
            with open(clf_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.console.print("[green]  ✓ classifier.py patché[/green]")
