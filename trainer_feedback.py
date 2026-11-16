#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trainer_feedback.py
===================
Auto-apprentissage depuis le feedback utilisateur.

Ce module analyse feedback_db.json et :
  1. Calcule les poids de sources (quelles sources donnent les meilleures réponses)
  2. Identifie les patterns de requêtes qui échouent
  3. Met à jour le vocabulaire avec les termes des bonnes réponses
  4. Génère des données d'entraînement supplémentaires depuis le feedback réel
  5. Crée un rapport d'apprentissage détaillé
"""

import json
import time
import random
import logging
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Confirm
from rich import box

logger = logging.getLogger("deerflow_trainer.feedback")


class FeedbackLearner:

    def __init__(self, base_dir: Path, models_dir: Path, console: Console):
        self.base_dir    = base_dir
        self.models_dir  = models_dir
        self.console     = console
        self.fb_path     = base_dir / "feedback_db.json"
        self.vocab_path  = base_dir / "vocabulary.json"
        self.kg_path     = base_dir / "knowledge_graph.json"
        self.kb_path     = base_dir / "knowledge_db.json"
        # Use canonical source weights path
        self.weights_path = Path("source_weights.json")

    def _load_feedback(self) -> list:
        if not self.fb_path.exists():
            self.console.print(
                "[yellow]feedback_db.json non trouvé.\n"
                "Utilisez le système quelques jours pour accumuler du feedback.[/yellow]"
            )
            return []
        with open(self.fb_path, encoding="utf-8") as f:
            return json.load(f)

    # ── 1. Calcul des poids de sources ───────────────────────

    def compute_source_weights(self, records: list) -> dict:
        """
        Calcule le poids de chaque source selon la qualité du feedback.

        Formule : weight(source) = (good_count + 1) / (bad_count + good_count + 2)
        Résultat entre 0.5 (source neutre) et 1.0 (source excellente).
        """
        source_good = Counter()
        source_bad  = Counter()
        source_by_type = defaultdict(lambda: defaultdict(Counter))

        for rec in records:
            rating = rec.get("rating", "pending")
            qt = rec.get("query_type", "general")

            for src in rec.get("sources", []):
                if rating == "good":
                    source_good[src] += 1
                    source_by_type[qt][src]["good"] += 1
                elif rating == "bad":
                    source_bad[src] += 1
                    source_by_type[qt][src]["bad"] += 1

        all_sources = set(source_good.keys()) | set(source_bad.keys())
        weights = {}
        for src in all_sources:
            g = source_good.get(src, 0)
            b = source_bad.get(src, 0)
            # Formule Laplace smoothed
            w = (g + 1) / (g + b + 2)
            weights[src] = {
                "weight":     round(w, 4),
                "good_count": g,
                "bad_count":  b,
                "total":      g + b,
                "by_type":    {qt: dict(v.get(src, {}))
                                for qt, v in source_by_type.items()
                                if src in v},
            }

        return weights

    # ── 2. Patterns d'échec ───────────────────────────────────

    def analyze_failure_patterns(self, records: list) -> dict:
        """Identifie les types de requêtes qui échouent régulièrement."""
        failures = defaultdict(list)
        successes = defaultdict(int)

        for rec in records:
            qt = rec.get("query_type", "general")
            if rec.get("rating") == "bad":
                failures[qt].append(rec.get("question", ""))
            elif rec.get("rating") == "good":
                successes[qt] += 1

        # Taux d'échec par type
        failure_rates = {}
        for qt in set(list(failures.keys()) + list(successes.keys())):
            nb_fail = len(failures.get(qt, []))
            nb_succ = successes.get(qt, 0)
            total = nb_fail + nb_succ
            if total > 0:
                failure_rates[qt] = {
                    "rate":     round(nb_fail / total, 3),
                    "failures": nb_fail,
                    "success":  nb_succ,
                    "examples": failures.get(qt, [])[:3],
                }

        # Mots-clés des questions qui échouent
        fail_words = Counter()
        for qs in failures.values():
            for q in qs:
                words = [w.lower() for w in q.split() if len(w) > 3]
                fail_words.update(words)

        return {
            "by_query_type": failure_rates,
            "common_fail_words": fail_words.most_common(20),
            "total_failures": sum(len(v) for v in failures.values()),
            "total_successes": sum(successes.values()),
        }

    # ── 3. Mise à jour du vocabulaire ────────────────────────

    def update_vocabulary(self, records: list) -> int:
        """
        Enrichit le vocabulaire avec les termes des bonnes réponses.
        Retourne le nombre de nouveaux termes ajoutés.
        """
        if not self.vocab_path.exists():
            return 0

        try:
            with open(self.vocab_path, encoding="utf-8") as f:
                vocab = json.load(f)
        except Exception:
            vocab = {"technical_terms": {}, "synonyms": [], "abbreviations": {}}

        technical_terms = vocab.get("technical_terms", {})
        new_terms = 0

        # Extraire les bigrams et trigrams des bonnes réponses
        import re
        for rec in records:
            if rec.get("rating") != "good":
                continue

            text = rec.get("answer", "") + " " + rec.get("question", "")
            tokens = re.findall(r"\b[\w\-\.]+\b", text.lower())
            tokens = [t for t in tokens if len(t) > 3]

            # Bigrams
            for i in range(len(tokens) - 1):
                bigram = f"{tokens[i]} {tokens[i+1]}"
                if bigram not in technical_terms:
                    technical_terms[bigram] = 1
                    new_terms += 1
                else:
                    technical_terms[bigram] = technical_terms[bigram] + 1

        vocab["technical_terms"] = technical_terms
        with open(self.vocab_path, "w", encoding="utf-8") as f:
            json.dump(vocab, f, ensure_ascii=False, indent=2)

        return new_terms

    # ── 4. Génération de données d'entraînement ───────────────

    def generate_training_data(self, records: list) -> dict:
        """
        Génère des triplets reranker et paires embedding depuis le feedback réel.
        Ces données enrichissent les données synthétiques pour les prochains fine-tunings.
        """
        good_records = [
            r for r in records
            if r.get("rating") == "good"
            and r.get("grounding_ratio", 0) > 0.8
            and r.get("question") and r.get("answer")
        ]

        bad_records = [
            r for r in records
            if r.get("rating") == "bad"
            and r.get("question")
        ]

        if not good_records:
            return {"reranker": 0, "embedding": 0}

        # Générer des triplets reranker depuis feedback réel
        reranker_triples = []
        for rec in good_records:
            # Positive = bonne réponse
            pos = rec["answer"]
            q = rec["question"]

            # Negative = réponse d'une mauvaise question similaire
            other_bad = [r for r in bad_records if r.get("question") != q]
            if other_bad:
                import random
                neg_rec = random.choice(other_bad)
                neg = neg_rec.get("answer", "Information non disponible dans les documents.")
            else:
                neg = "Le planning de maintenance est en cours d'élaboration."

            reranker_triples.append({
                "query":    q,
                "positive": pos,
                "negative": neg,
                "discipline": rec.get("query_type", "general"),
                "real_data": True,
            })

        # Embedding pairs
        embed_pairs = []
        for rec in good_records:
            # Generate a fresh negative for each embedding pair
            other_bad = [r for r in bad_records if r.get("question") != rec.get("question")]
            if other_bad:
                neg_rec = random.choice(other_bad)
                neg_text = neg_rec.get("answer", "Information non disponible dans les documents.")
            else:
                neg_text = "Le planning de maintenance est en cours d'elaboration."
            embed_pairs.append({
                "anchor": rec.get("question", ""),
                "positive": rec.get("answer", ""),
                "negative": neg_text,
                "discipline": rec.get("query_type", "general"),
                "real_data": True,
            })

        # Sauvegarder dans les fichiers de données
        data_dir = self.base_dir / "training_data"
        data_dir.mkdir(exist_ok=True)

        reranker_path = data_dir / "reranker_feedback.jsonl"
        with open(reranker_path, "w", encoding="utf-8") as f:
            for item in reranker_triples:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        embed_path = data_dir / "embedding_feedback.jsonl"
        with open(embed_path, "w", encoding="utf-8") as f:
            for item in embed_pairs:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        return {
            "reranker":  len(reranker_triples),
            "embedding": len(embed_pairs),
        }

    # ── 5. Mise à jour du Knowledge Graph ────────────────────

    def update_knowledge_graph(self, records: list) -> int:
        """
        Extrait les entités des bonnes réponses et les ajoute au graphe.
        """
        if not self.kg_path.exists():
            return 0

        try:
            with open(self.kg_path, encoding="utf-8") as f:
                graph = json.load(f)
        except Exception:
            graph = {"entities": {}, "relationships": [], "document_index": {}}

        import re
        TAG_PATTERN = r"\b([PVEKCTDFHRLMS]-\d{3,4}[A-Z]?)\b"
        added = 0

        for rec in records:
            if rec.get("rating") != "good":
                continue

            text = rec.get("answer", "")
            source = "feedback_learned"

            # Extraire les tags
            tags = re.findall(TAG_PATTERN, text)
            for tag in set(tags):
                if tag not in graph["entities"]:
                    graph["entities"][tag] = {
                        "type": "equipment",
                        "sources": [source],
                        "properties": {},
                        "subtype": "learned",
                    }
                    added += 1
                elif source not in graph["entities"][tag].get("sources", []):
                    graph["entities"][tag]["sources"].append(source)

        if added > 0:
            with open(self.kg_path, "w", encoding="utf-8") as f:
                json.dump(graph, f, ensure_ascii=False, indent=2)

        return added

    # ── Point d'entrée ────────────────────────────────────────

    def run(self):
        self.console.print(
            "\n[bold cyan]═══ Auto-Apprentissage depuis Feedback Utilisateur ═══[/bold cyan]\n"
        )

        records = self._load_feedback()
        if not records:
            return

        # Stats de base
        good    = sum(1 for r in records if r.get("rating") == "good")
        bad     = sum(1 for r in records if r.get("rating") == "bad")
        pending = sum(1 for r in records if r.get("rating") == "pending")

        self.console.print(Panel(
            f"[bold]Feedback chargé :[/bold] {len(records)} enregistrements\n"
            f"  ✓ Good   : [green]{good}[/green]\n"
            f"  ✗ Bad    : [red]{bad}[/red]\n"
            f"  ? Pending: [yellow]{pending}[/yellow]\n\n"
            f"Satisfaction actuelle : "
            f"[bold]{'%.0f%%' % (good/(good+bad)*100 if good+bad > 0 else 0)}[/bold]",
            title="Analyse Feedback", border_style="cyan"
        ))

        if good + bad < 5:
            self.console.print(
                "[yellow]Moins de 5 feedbacks évalués.\n"
                "Continuez à utiliser le système pour accumuler des retours.[/yellow]\n"
            )
            return

        if not Confirm.ask("Lancer l'auto-apprentissage ?"):
            return

        results = {}
        start = time.time()

        # 1. Poids des sources
        self.console.print("\n[dim]Calcul des poids de sources...[/dim]")
        weights = self.compute_source_weights(records)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        with open(self.weights_path, "w", encoding="utf-8") as f:
            json.dump(weights, f, ensure_ascii=False, indent=2)
        results["source_weights"] = len(weights)

        # Afficher top sources
        sorted_w = sorted(weights.items(), key=lambda x: x[1]["weight"], reverse=True)
        t = Table(title="Top Sources", box=box.SIMPLE)
        t.add_column("Source", style="cyan")
        t.add_column("Score", style="bold green", justify="right")
        t.add_column("Good", justify="right")
        t.add_column("Bad", justify="right")
        for src, info in sorted_w[:8]:
            w = info["weight"]
            color = "green" if w >= 0.7 else "yellow" if w >= 0.5 else "red"
            t.add_row(
                src[:50],
                f"[{color}]{w:.3f}[/{color}]",
                str(info["good_count"]),
                str(info["bad_count"]),
            )
        self.console.print(t)

        # 2. Analyse des échecs
        self.console.print("\n[dim]Analyse des patterns d'échec...[/dim]")
        failures = self.analyze_failure_patterns(records)
        results["failure_analysis"] = failures["total_failures"]

        if failures["total_failures"] > 0:
            t2 = Table(title="Taux d'échec par type", box=box.SIMPLE)
            t2.add_column("Type de requête", style="cyan")
            t2.add_column("Taux échec", justify="right")
            t2.add_column("Failures", justify="right")
            for qt, info in sorted(
                failures["by_query_type"].items(),
                key=lambda x: x[1]["rate"], reverse=True
            ):
                rate = info["rate"]
                color = "red" if rate >= 0.5 else "yellow" if rate >= 0.3 else "green"
                t2.add_row(
                    qt,
                    f"[{color}]{rate:.0%}[/{color}]",
                    str(info["failures"]),
                )
            self.console.print(t2)

            # Recommandations
            if failures["common_fail_words"]:
                top_fail = [w for w, _ in failures["common_fail_words"][:5]]
                self.console.print(
                    f"\n[yellow]Mots fréquents dans les échecs:[/yellow] "
                    f"{', '.join(top_fail)}\n"
                    f"[dim]→ Envisagez d'indexer plus de documents sur ces sujets.[/dim]"
                )

        # 3. Vocabulaire
        self.console.print("\n[dim]Mise à jour du vocabulaire...[/dim]")
        new_terms = self.update_vocabulary(records)
        results["vocabulary_new_terms"] = new_terms
        self.console.print(f"  +{new_terms} nouveaux termes techniques")

        # 4. Données d'entraînement
        self.console.print("\n[dim]Génération de données d'entraînement...[/dim]")
        train_data = self.generate_training_data(records)
        results["reranker_pairs"] = train_data["reranker"]
        results["embedding_pairs"] = train_data["embedding"]
        self.console.print(
            f"  +{train_data['reranker']} triplets reranker\n"
            f"  +{train_data['embedding']} paires embedding\n"
            f"  → Disponibles pour le prochain fine-tuning (modes 2 et 3)"
        )

        # 5. Knowledge Graph
        self.console.print("\n[dim]Mise à jour du Knowledge Graph...[/dim]")
        added_entities = self.update_knowledge_graph(records)
        results["kg_entities_added"] = added_entities
        self.console.print(f"  +{added_entities} entités ajoutées au graphe")

        # 6. Patch auto pour source weights
        self._patch_retriever_for_weights()

        elapsed = time.time() - start

        # Rapport final
        self.console.print(Panel(
            f"[bold green]✓ Auto-apprentissage terminé ({elapsed:.1f}s)[/bold green]\n\n"
            f"Poids sources calculés : {results['source_weights']}\n"
            f"Patterns d'échec analysés : {results['failure_analysis']}\n"
            f"Nouveaux termes vocabulaire : {results['vocabulary_new_terms']}\n"
            f"Nouveaux triplets reranker : {results['reranker_pairs']}\n"
            f"Nouvelles paires embedding : {results['embedding_pairs']}\n"
            f"Entités ajoutées au graphe : {results['kg_entities_added']}\n\n"
            f"[yellow]→ Relancez le fine-tuning (mode 2/3) pour intégrer ces améliorations[/yellow]",
            border_style="green"
        ))

        # Rapport JSON
        report = {
            "generated_at": datetime.now().isoformat(),
            "feedback_total": len(records),
            "feedback_good": good,
            "feedback_bad": bad,
            "satisfaction_rate": round(good/(good+bad), 3) if good+bad > 0 else 0,
            "results": results,
            "top_sources": [(s, i["weight"]) for s, i in sorted_w[:5]],
        }
        report_path = self.models_dir / "feedback_learning_report.json"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

    def _patch_retriever_for_weights(self):
        """
        Source weights sont désormais gérés nativement par HybridRetriever._reciprocal_rank_fusion().
        Le patch module-level est désactivé car il était incompatible avec list[RetrievalResult].
        Le fichier source_weights.json est chargé automatiquement via hot-reload dans retrieve().
        """
        self.console.print(
            "[dim]  Source weights: gérés nativement par HybridRetriever "
            "(hot-reload de source_weights.json) ✓[/dim]"
        )
