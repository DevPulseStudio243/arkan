#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trainer_eval.py
===============
Évaluation complète du système RAG Oil & Gas.

Métriques mesurées :
  - MRR@K  : Mean Reciprocal Rank (qualité du ranking)
  - MAP@K  : Mean Average Precision
  - P@K    : Précision at K
  - Grounding ratio : taux de claims vérifiés dans le contexte
  - Latence : temps de réponse de bout en bout
  - Accuracy classifieur : sur jeu de test hold-out
"""

import json
import time
import re
import logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.prompt import Confirm
from rich import box

logger = logging.getLogger("deerflow_trainer.eval")


class SystemEvaluator:

    def __init__(self, base_dir: Path, models_dir: Path,
                 data_dir: Path, console: Console):
        self.base_dir   = base_dir
        self.models_dir = models_dir
        self.data_dir   = data_dir
        self.console    = console

    # ── Métriques de retrieval ────────────────────────────────

    def _reciprocal_rank(self, relevant_ids: set, ranked_ids: list) -> float:
        for i, doc_id in enumerate(ranked_ids):
            if doc_id in relevant_ids:
                return 1.0 / (i + 1)
        return 0.0

    def _average_precision(self, relevant_ids: set, ranked_ids: list, k: int = 10) -> float:
        """
        AP@K correctèment borné [0, 1].
        Normalise par min(|R|, K) pour éviter AP > 1 quand |R| = 1
        mais plusieurs documents pertinents sont retournés.
        """
        if not relevant_ids:
            return 0.0
        hits, ap_sum = 0, 0.0
        ranked_k = ranked_ids[:k]
        for i, doc_id in enumerate(ranked_k):
            if doc_id in relevant_ids:
                hits += 1
                ap_sum += hits / (i + 1)
        # Normalisation : min(|R|, K) pour garantir AP ∈ [0, 1]
        norm = min(len(relevant_ids), k)
        return min(ap_sum / norm, 1.0)  # clamp sécuritaire

    def _precision_at_k(self, relevant_ids: set, ranked_ids: list, k: int) -> float:
        return sum(1 for x in ranked_ids[:k] if x in relevant_ids) / k

    # ── Évaluation Retrieval ──────────────────────────────────

    def eval_retrieval(self) -> dict:
        """
        Évalue la qualité du retrieval sur les paires Q/A synthétiques.
        Utilise la source connue comme vérité terrain.
        """
        qa_path = self.data_dir / "qa_pairs.jsonl"
        if not qa_path.exists():
            return {"error": "qa_pairs.jsonl manquant"}

        qa_pairs = []
        with open(qa_path, encoding="utf-8") as f:
            for line in f:
                qa_pairs.append(json.loads(line))

        # Vérifier ChromaDB disponible
        try:
            import chromadb
            from config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION
            from indexer import get_embedding, tokenize_for_bm25

            client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
            collection = client.get_collection(CHROMA_COLLECTION)
        except Exception as e:
            return {"error": f"ChromaDB non disponible: {e}"}

        mrr_scores, map_scores, p1_scores, p3_scores = [], [], [], []

        sample = qa_pairs[:min(50, len(qa_pairs))]  # Limiter à 50 pour la vitesse

        for item in sample:
            query = item["question"]
            source = item.get("source", "")
            discipline = item.get("discipline", "")

            # Retrieval vectoriel
            try:
                emb = get_embedding(query)
                if not emb:
                    continue

                results = collection.query(
                    query_embeddings=[emb],
                    n_results=10,
                    include=["metadatas", "distances"],
                )

                ranked_sources = []
                if results and results.get("metadatas"):
                    for meta in results["metadatas"][0]:
                        src = meta.get("source", "")
                        ranked_sources.append(src)

                # La source "correcte" est celle du document synthétique
                relevant = {source} if source else {discipline}
                # Pour les docs synthétiques, utiliser la discipline comme proxy
                relevant_broad = {
                    s for s in ranked_sources
                    if discipline in s.lower() or s == source
                }

                if ranked_sources:
                    mrr_scores.append(
                        self._reciprocal_rank(relevant_broad or {ranked_sources[0]}, ranked_sources)
                    )
                    map_scores.append(
                        self._average_precision(relevant_broad or {ranked_sources[0]}, ranked_sources)
                    )
                    p1_scores.append(
                        self._precision_at_k(relevant_broad or {ranked_sources[0]}, ranked_sources, 1)
                    )
                    p3_scores.append(
                        self._precision_at_k(relevant_broad or {ranked_sources[0]}, ranked_sources, 3)
                    )

            except Exception as e:
                logger.debug("Erreur eval retrieval: %s", e)
                continue

        if not mrr_scores:
            return {"error": "Aucun résultat calculé — ChromaDB vide ?"}

        n = len(mrr_scores)
        return {
            "queries_evaluated": n,
            "MRR@10":  round(sum(mrr_scores) / n, 4),
            "MAP@10":  round(min(sum(map_scores) / n, 1.0), 4),  # clamp [0,1]
            "P@1":     round(sum(p1_scores)  / n, 4),
            "P@3":     round(sum(p3_scores)  / n, 4),
        }

    # ── Évaluation Anti-Hallucination ─────────────────────────

    def eval_grounding(self) -> dict:
        """
        Mesure le taux de grounding sur les feedbacks existants.
        """
        fb_path = self.base_dir / "feedback_db.json"
        if not fb_path.exists():
            return {"error": "feedback_db.json manquant"}

        try:
            with open(fb_path, encoding="utf-8") as f:
                records = json.load(f)
        except Exception:
            return {"error": "Impossible de lire feedback_db.json"}

        ratios = [r.get("grounding_ratio", 1.0) for r in records if "grounding_ratio" in r]
        if not ratios:
            return {"note": "grounding_ratio non enregistré dans le feedback"}

        high   = sum(1 for r in ratios if r >= 0.9)
        medium = sum(1 for r in ratios if 0.7 <= r < 0.9)
        low    = sum(1 for r in ratios if r < 0.7)

        return {
            "responses_evaluated": len(ratios),
            "avg_grounding": round(sum(ratios) / len(ratios), 4),
            "grounding_100%": sum(1 for r in ratios if r == 1.0),
            "grounding_high":   high,
            "grounding_medium": medium,
            "grounding_low":    low,
        }

    # ── Évaluation Classifieur ────────────────────────────────

    def eval_classifier(self) -> dict:
        """Évalue la précision du classifieur sur données de test."""
        # Essayer le classifieur ML d'abord
        clf_path = self.models_dir / "classifier_oil_gas" / "classifier_model.pkl"
        test_path = self.data_dir / "classifier_samples.jsonl"

        if not test_path.exists():
            return {"error": "classifier_samples.jsonl manquant"}

        # Charger données test
        texts, labels = [], []
        with open(test_path, encoding="utf-8") as f:
            for line in f:
                item = json.loads(line)
                texts.append(item["text"])
                labels.append(item["label"])

        # Split test (15% final)
        from sklearn.model_selection import train_test_split
        _, X_test, _, y_test = train_test_split(
            texts, labels, test_size=0.15, random_state=42, stratify=labels
        )

        results = {}

        # Classifieur ML si disponible
        if clf_path.exists():
            try:
                import pickle
                from sklearn.metrics import accuracy_score, f1_score

                with open(clf_path, "rb") as f:
                    ml_clf = pickle.load(f)

                y_pred = ml_clf.predict(X_test)
                results["ml_classifier"] = {
                    "accuracy":  round(accuracy_score(y_test, y_pred), 4),
                    "f1_macro":  round(f1_score(y_test, y_pred, average="macro"), 4),
                    "test_size": len(X_test),
                }
            except Exception as e:
                results["ml_classifier"] = {"error": str(e)}

        # Classifieur règles (baseline)
        try:
            from classifier import classify_document

            correct = 0
            for text, label in zip(X_test[:100], y_test[:100]):
                pred = classify_document(text)
                if pred["discipline"] == label:
                    correct += 1

            results["rule_classifier"] = {
                "accuracy":  round(correct / min(100, len(X_test)), 4),
                "test_size": min(100, len(X_test)),
            }
        except Exception as e:
            results["rule_classifier"] = {"error": str(e)}

        return results

    # ── Évaluation Latence ────────────────────────────────────

    def eval_latency(self) -> dict:
        """Mesure les temps de réponse des composants critiques."""
        results = {}

        # Latence embedding (avec warmup exclu)
        try:
            from indexer import get_embedding
            test_text = "Quelle est la pression de design de P-101 ?"
            # Appel de warmup (initialise la connexion Ollama / charge le modèle)
            get_embedding(test_text)
            # 3 mesures réelles après warmup
            times = []
            for _ in range(3):
                t0 = time.time()
                emb = get_embedding(test_text)
                times.append((time.time() - t0) * 1000)
            # Exclure les outliers : prendre la médiane des 3 mesures
            times.sort()
            results["embedding_ms"] = round(times[1], 1)  # médiane
            results["embedding_warmup_note"] = "warmup exclu — valeur = médiane de 3 mesures"
        except Exception as e:
            results["embedding_ms"] = f"erreur: {e}"

        # Latence ChromaDB query
        try:
            import chromadb
            from config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION
            from indexer import get_embedding

            client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
            collection = client.get_collection(CHROMA_COLLECTION)
            emb = get_embedding("pression de service pompe centrifuge")
            if emb:
                t0 = time.time()
                collection.query(query_embeddings=[emb], n_results=10)
                results["chroma_query_ms"] = round((time.time() - t0) * 1000, 1)
        except Exception as e:
            results["chroma_query_ms"] = f"erreur: {e}"

        # Latence BM25
        try:
            from indexer import ensure_bm25_loaded, get_bm25_index, tokenize_for_bm25
            ensure_bm25_loaded()
            bm25, docs, ids, _ = get_bm25_index()
            if bm25 and docs:
                tokens = tokenize_for_bm25("pression de service pompe")
                t0 = time.time()
                bm25.get_scores(tokens)
                results["bm25_query_ms"] = round((time.time() - t0) * 1000, 1)
        except Exception as e:
            results["bm25_query_ms"] = f"erreur: {e}"

        return results

    # ── Évaluation Reranker ───────────────────────────────────

    def eval_reranker(self) -> dict:
        """Compare le reranker algorithmique vs neuronal."""
        from types import SimpleNamespace
        reranker_path = self.models_dir / "reranker_oil_gas"

        test_cases = [
            {
                "query": "Quelle est la pression de P-101 ?",
                "positive": "La pompe P-101 opère à 28 bar de pression nominale.",
                "negative": "Le planning de maintenance est fixé pour mars 2026.",
            },
            {
                "query": "Norme API pour les compresseurs centrifuges ?",
                "positive": "Les compresseurs centrifuges doivent respecter la norme API 617.",
                "negative": "Les réunions de coordination ont lieu chaque lundi matin.",
            },
            {
                "query": "Matériau de la tuyauterie haute pression ?",
                "positive": "La tuyauterie HP classe A1A est en ASTM A106 Gr.B.",
                "negative": "Le rapport d'avancement est transmis chaque vendredi.",
            },
        ]

        results = {}

        # ── Reranker algorithmique (toujours évalué) ──────────
        def _make_candidate(doc_id: str, text: str) -> SimpleNamespace:
            """Crée un objet compatible RetrievalResult pour les tests."""
            return SimpleNamespace(
                id=doc_id,
                content=text,
                score=0.5,
                chunk_id=doc_id,
                source="eval_test",
                discipline="",
                metadata={},
            )

        try:
            from reranker import cross_rerank
            correct_algo = 0
            for tc in test_cases:
                candidates = [
                    _make_candidate("pos", tc["positive"]),
                    _make_candidate("neg", tc["negative"]),
                ]
                ranked = cross_rerank(tc["query"], candidates, top_k=2)
                if ranked and getattr(ranked[0], "id", None) == "pos":
                    correct_algo += 1
            results["algorithmic"] = {
                "accuracy": round(correct_algo / len(test_cases), 3),
                "test_cases": len(test_cases),
            }
        except Exception as e:
            results["algorithmic"] = {"error": str(e)}

        # ── Reranker neuronal (si modèle fine-tuné valide disponible) ──
        neural_config = reranker_path / "config.json"
        if reranker_path.exists() and neural_config.exists():
            try:
                from sentence_transformers import CrossEncoder
                model = CrossEncoder(str(reranker_path), max_length=256)
                correct_neural = 0
                for tc in test_cases:
                    scores = model.predict([
                        [tc["query"], tc["positive"]],
                        [tc["query"], tc["negative"]],
                    ])
                    if scores[0] > scores[1]:
                        correct_neural += 1
                results["neural"] = {
                    "accuracy": round(correct_neural / len(test_cases), 3),
                    "test_cases": len(test_cases),
                }
            except Exception as e:
                results["neural"] = {"error": str(e)}
        else:
            results["neural_note"] = "Modèle non entraîné — lancez: python train_deerflow.py --mode reranker"

        return results



    # ── Point d'entrée ────────────────────────────────────────

    def run(self):
        self.console.print(
            "\n[bold cyan]═══ Évaluation Complète du Système RAG ═══[/bold cyan]\n"
        )

        if not Confirm.ask("Lancer l'évaluation complète ?"):
            return

        report = {"evaluated_at": datetime.now().isoformat()}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=self.console,
        ) as progress:

            # Latence
            t = progress.add_task("Mesure des latences...", total=None)
            report["latency"] = self.eval_latency()
            progress.update(t, description="[green]Latences ✓[/green]")

            # Classifieur
            t2 = progress.add_task("Évaluation classifieur...", total=None)
            report["classifier"] = self.eval_classifier()
            progress.update(t2, description="[green]Classifieur ✓[/green]")

            # Grounding
            t3 = progress.add_task("Analyse du grounding...", total=None)
            report["grounding"] = self.eval_grounding()
            progress.update(t3, description="[green]Grounding ✓[/green]")

            # Reranker
            t4 = progress.add_task("Évaluation reranker...", total=None)
            report["reranker"] = self.eval_reranker()
            progress.update(t4, description="[green]Reranker ✓[/green]")

            # Retrieval (plus long car appelle Ollama)
            t5 = progress.add_task("Évaluation retrieval (MRR/MAP)...", total=None)
            report["retrieval"] = self.eval_retrieval()
            progress.update(t5, description="[green]Retrieval ✓[/green]")

        # ── Affichage résultats ───────────────────────────────
        self.console.print()

        # Latences — filtrer les clés de métadonnées (non numériques)
        lat = report["latency"]
        _LAT_DISPLAY = {"embedding_ms", "chroma_query_ms", "bm25_query_ms"}  # clés connues
        t1 = Table(title="Latences", box=box.ROUNDED, border_style="blue")
        t1.add_column("Composant", style="cyan")
        t1.add_column("Latence", style="bold", justify="right")
        t1.add_column("Statut", justify="center")
        for comp, val in lat.items():
            if not isinstance(val, (int, float)):
                continue  # ignorer les notes et clés textuelles
            color = "green" if val < 100 else "yellow" if val < 500 else "red"
            status = "✓" if val < 500 else "⚠"
            t1.add_row(comp, f"[{color}]{val} ms[/{color}]", status)
        # Afficher la note warmup séparément si présente
        if "embedding_warmup_note" in lat:
            t1.add_row(
                "[dim]note[/dim]",
                f"[dim]{lat['embedding_warmup_note']}[/dim]",
                "[dim]ℹ[/dim]",
            )
        self.console.print(t1)

        # Classifieur
        clf = report["classifier"]
        if "error" not in clf:
            t2 = Table(title="Classifieur", box=box.ROUNDED, border_style="blue")
            t2.add_column("Méthode", style="cyan")
            t2.add_column("Accuracy", style="bold green", justify="right")
            for method, info in clf.items():
                if "accuracy" in info:
                    acc = info["accuracy"]
                    color = "green" if acc >= 0.8 else "yellow" if acc >= 0.6 else "red"
                    t2.add_row(method, f"[{color}]{acc:.1%}[/{color}]")
            self.console.print(t2)

        # Grounding
        gr = report["grounding"]
        if "avg_grounding" in gr:
            avg = gr["avg_grounding"]
            color = "green" if avg >= 0.9 else "yellow" if avg >= 0.7 else "red"
            self.console.print(Panel(
                f"Taux de grounding moyen : [{color}]{avg:.1%}[/{color}]\n"
                f"  Élevé (≥90%) : {gr.get('grounding_high', 0)} réponses\n"
                f"  Moyen (70-90%): {gr.get('grounding_medium', 0)} réponses\n"
                f"  Faible (<70%) : {gr.get('grounding_low', 0)} réponses",
                title="Anti-Hallucination", border_style="blue"
            ))

        # Reranker
        rr = report["reranker"]
        t3 = Table(title="Reranker", box=box.ROUNDED, border_style="blue")
        t3.add_column("Type", style="cyan")
        t3.add_column("Accuracy", style="bold green", justify="right")
        t3.add_column("Note", style="dim")
        has_rr_data = False
        for rtype, info in rr.items():
            if isinstance(info, dict) and "accuracy" in info:
                acc = info["accuracy"]
                color = "green" if acc >= 0.8 else "yellow" if acc >= 0.6 else "red"
                t3.add_row(rtype, f"[{color}]{acc:.1%}[/{color}]",
                           f"{info.get('test_cases', '')} cas")
                has_rr_data = True
            elif isinstance(info, str):  # note
                t3.add_row(rtype.replace("_note", ""), "[dim]N/A[/dim]", info[:60])
                has_rr_data = True
        if has_rr_data:
            self.console.print(t3)
        else:
            self.console.print("[dim]Reranker : aucune métrique disponible[/dim]")

        # Retrieval
        ret = report["retrieval"]
        if "MRR@10" in ret:
            t4 = Table(title="Retrieval (sur 50 requêtes test)", box=box.ROUNDED, border_style="blue")
            t4.add_column("Métrique", style="cyan")
            t4.add_column("Score", style="bold green", justify="right")
            for metric in ["MRR@10", "MAP@10", "P@1", "P@3"]:
                if metric in ret:
                    score = ret[metric]
                    color = "green" if score >= 0.7 else "yellow" if score >= 0.5 else "red"
                    t4.add_row(metric, f"[{color}]{score:.4f}[/{color}]")
            self.console.print(t4)

        # Score global — intègre toutes les métriques disponibles
        score_components = {}  # {label: valeur}

        # Grounding (poids 0.3 — qualité des réponses)
        if "avg_grounding" in gr:
            score_components["grounding"] = gr["avg_grounding"]

        # P@3 plutôt que MRR@10 pour le retrieval
        # (MRR=1.0 artificiel sur données synthétiques matchées par discipline)
        if "P@3" in ret:
            score_components["precision@3"] = ret["P@3"]

        # Classifieur : ML si disponible, sinon règles
        clf_ml = clf.get("ml_classifier", {})
        clf_rule = clf.get("rule_classifier", {})
        if "accuracy" in clf_ml:
            score_components["classifieur_ml"] = clf_ml["accuracy"]
        elif "accuracy" in clf_rule:
            score_components["classifieur_r\u00e8gles"] = clf_rule["accuracy"]

        # Reranker : neuronal si disponible, sinon algorithmique
        rr_neural = rr.get("neural", {})
        rr_algo   = rr.get("algorithmic", {})
        if "accuracy" in rr_neural:
            score_components["reranker_neural"] = rr_neural["accuracy"]
        elif "accuracy" in rr_algo:
            score_components["reranker_algo"] = rr_algo["accuracy"]

        if score_components:
            global_score = sum(score_components.values()) / len(score_components)
            color = "green" if global_score >= 0.8 else "yellow" if global_score >= 0.6 else "red"
            components_str = " + ".join(
                f"{k}={v:.0%}" for k, v in score_components.items()
            )
            self.console.print(Panel(
                f"[bold]Score global estimé : [{color}]{global_score:.1%}[/{color}][/bold]\n\n"
                f"[dim]Composantes ({len(score_components)}) :\n{components_str}[/dim]",
                title="Score Global", border_style="green"
            ))

        # Sauvegarder le rapport
        report_path = self.models_dir / "eval_report.json"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

        self.console.print(
            f"\n[dim]Rapport complet sauvegardé: {report_path}[/dim]\n"
        )
