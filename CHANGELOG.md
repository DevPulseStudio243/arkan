# CHANGELOG - DeerFlow Lite Oil & Gas AI

## Revision 01 (2026-04-22)

### Refonte complète du système

#### Corrections critiques
- **[SÉCURITÉ]** Suppression de la clé API DeepSeek exposée dans `.env` → remplacé par `.env.example`
- **[BUG]** Corrigé la fuite de variable `neg` dans `trainer_feedback.py` (ligne 238) qui causait des négatifs identiques pour tous les pairs d'embeddings
- **[BUG]** Corrigé l'incompatibilité test/code : `classify_query` et `QueryType.EQUIPMENT`/`PLANNING` sont maintenant dans le module
- **[BUG]** Corrigé `build_prompt` : les tests attendaient un string, le code retournait un dict → harmonisé (dict avec marqueurs corrects)
- **[BUG]** Corrigé la formule IDF non-standard dans `vocabulary.py` → utilise maintenant `log(N/df)`
- **[PERF]** Corrigé le rechargement disque du vocabulaire à chaque requête → cache mémoire avec invalidation par mtime

#### Nouveau moteur de recherche sémantique
- **Reciprocal Rank Fusion (RRF)** remplace la fusion additive naïve des scores vectoriels et BM25
- **Cross-encoder reranker** (semantic) avec fallback lexical amélioré (Jaccard + entity matching borné)
- **Évaluation de suffisance sémantique** par similarité cosinus au lieu de l'overlap de mots
- **Poids de sources** intégrés au retriever (les sources fiables sont boostées automatiquement)

#### Système d'agents multi-disciplines
- 7 agents spécialisés : Piping, Process, Instrumentation, Mécanique, Électrique, HSE, Génie Civil
- Chaque agent connaît ses normes (API, ASME, IEC, EN, etc.), son vocabulaire, et ses unités
- **Routage automatique** des requêtes vers le(s) agent(s) pertinent(s)
- **Enrichissement de requête** avec mots-clés et normes spécifiques à la discipline
- **Validation post-réponse** : détection de mélanges d'unités, vérification de cohérence
- **Collaboration multi-agents** pour les requêtes cross-discipline

#### Auto-apprentissage réel
- **Poids de sources Bayésiens** avec lissage de Laplace et momentum exponentiel
- **Apprentissage de vocabulaire** avec validation domaine Oil & Gas (rejette `float64`, `copyright`, etc.)
- **Évolution du knowledge graph** avec déduplication, validation d'entités, et élagage du bruit
- **Apprentissage de patterns de requêtes** : identifie les structures de questions qui échouent
- **Active learning** : les requêtes à faible confiance sont mises en file d'attente pour révision expert
- **Apprentissage par correction** : quand l'utilisateur corrige une réponse, le système apprend les termes manquants
- **Consolidation périodique** automatique toutes les 50 interactions

#### Guardrails améliorés
- Extraction de claims vérifiables (numériques, normes, tags, matériaux)
- Vérification d'ancrage (grounding) de chaque claim dans le contexte source
- Sanitization des réponses avec marquage des informations non vérifiées
- Détection de fuites de chemins fichiers et d'informations sensibles

#### Prompts restructurés
- Instructions anti-hallucination renforcées en français
- 8 types d'instructions spécifiques (recherche, comparaison, calcul, procédure, vérification, diagnostic, équipement, planning)
- Chaîne de raisonnement interne (IDENTIFIER → EXTRAIRE → FORMULER → VÉRIFIER → ALERTER) non affichée à l'utilisateur
- Injection de contexte knowledge graph et alertes agents

#### Pipeline intégré
- Orchestration complète en 12 étapes (query planning → vocabulary expansion → agent enrichment → retrieval → reranking → sufficiency → KB → prompt → LLM → validation → learning)
- Point d'entrée unifié : `pipeline.ask("question")`
- Gestion d'erreurs robuste à chaque étape
- Feedback automatique et explicite

#### Configuration
- Module `config.py` centralisé avec variables d'environnement
- `.env.example` sécurisé (pas de clés en clair)
- Tous les paramètres configurables sans modifier le code

#### Tests
- Suite de tests complète couvrant tous les modules
- Tests de classification, expansion, agents, guardrails, learning
- Isolation des tests avec répertoires temporaires

### Fichiers

| Fichier | Description |
|---------|-------------|
| `config.py` | Configuration centralisée |
| `pipeline.py` | Pipeline principal (12 étapes) |
| `retriever.py` | Recherche hybride avec RRF |
| `reranker.py` | Reranking sémantique cross-encoder |
| `query_planner.py` | Classification et décomposition de requêtes |
| `vocabulary.py` | Vocabulaire technique avec cache |
| `agents.py` | 7 agents multi-disciplines |
| `learning.py` | Moteur d'auto-apprentissage |
| `prompts.py` | Construction de prompts anti-hallucination |
| `guardrails.py` | Vérification et sécurité des réponses |
| `training.py` | Entraînement continu |
| `test_system.py` | Suite de tests |
| `.env.example` | Template de configuration |
| `CHANGELOG.md` | Ce fichier |
