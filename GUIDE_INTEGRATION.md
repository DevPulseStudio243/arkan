# Guide d'Integration — Deerflow Lite v3.0 Enhanced

> Systeme RAG agentic pour projets Oil & Gas avec multi-agents, entrainement continu, comprehension de projet et traitement de fichiers avance.

---

## Table des matieres

1. [Architecture du systeme](#1-architecture-du-systeme)
2. [Installation](#2-installation)
3. [Systeme Multi-Agents](#3-systeme-multi-agents)
4. [Entrainement de l'IA](#4-entrainement-de-lia)
5. [Comprehension de projet](#5-comprehension-de-projet)
6. [Traitement des fichiers](#6-traitement-des-fichiers)
7. [API Reference](#7-api-reference)
8. [Configuration avancee](#8-configuration-avancee)
9. [Depannage](#9-depannage)

---

## 1. Architecture du systeme

### 1.1 Diagramme d'architecture

```
                           ┌─────────────────────────────┐
                           │       Client / UI            │
                           │   (navigateur, curl, app)    │
                           └──────────┬──────────────────┘
                                      │ HTTP/JSON
                                      ▼
                     ┌────────────────────────────────────┐
                     │      API FastAPI (api_enhanced.py)  │
                     │         Port 8000 — /docs           │
                     │                                     │
                     │  Endpoints:                         │
                     │   /question   /index   /agents      │
                     │   /training/* /project/* /health     │
                     └──┬───┬───┬───┬───┬───┬────────────┘
                        │   │   │   │   │   │
           ┌────────────┘   │   │   │   │   └────────────┐
           ▼                ▼   │   ▼   ▼                ▼
  ┌────────────────┐ ┌─────────┐│┌──────────┐  ┌──────────────┐
  │ Agent          │ │ RAG     │││ Training  │  │ File         │
  │ Orchestrator   │ │ Pipeline│││ Pipeline  │  │ Processor    │
  │ (agents.py)    │ │         │││(training. │  │(file_        │
  │                │ │ query   │││  py)      │  │ processor.py)│
  │ 7 disciplines: │ │ planner │││           │  │              │
  │ - Process      │ │ retriev.│││ - Data    │  │ - PDF        │
  │ - Mechanical   │ │ rerank  │││   Gen     │  │ - DOCX       │
  │ - Piping       │ │ prompt  │││ - Vocab   │  │ - XLSX       │
  │ - Instrument.  │ │ guardr. │││   Learn   │  │ - PPTX       │
  │ - Electrical   │ │         │││ - Optim.  │  │ - CSV/JSON   │
  │ - Civil        │ └────┬────┘││ - Metrics │  │ - Images     │
  │ - Safety       │      │     ││           │  │ - HTML/XML   │
  └───────┬────────┘      │     │└─────┬─────┘  └──────┬───────┘
          │               │     │      │               │
          │               ▼     ▼      │               │
          │      ┌──────────────────┐  │               │
          │      │  Project         │  │               │
          │      │  Understanding   │  │               │
          │      │  (project_       │  │               │
          │      │   understanding. │  │               │
          │      │   py)            │  │               │
          │      │                  │  │               │
          │      │  - Analyzer      │  │               │
          │      │  - Semantic QU   │  │               │
          │      │  - Enricher      │  │               │
          │      │  - Completeness  │  │               │
          │      └────────┬─────────┘  │               │
          │               │            │               │
          ▼               ▼            ▼               ▼
  ┌──────────────────────────────────────────────────────────┐
  │                  Couche de Persistance                    │
  │                                                          │
  │  ChromaDB          JSON Files             Ollama         │
  │  (vecteurs)        - knowledge_db.json    (LLM local)    │
  │                    - knowledge_graph.json  - llama3.1:8b  │
  │                    - feedback_db.json      - nomic-embed  │
  │                    - vocabulary.json       - llava:7b     │
  │                    - project_model.json                   │
  │                    - training_log.json                    │
  │                    - agent_state.json                     │
  └──────────────────────────────────────────────────────────┘
```

### 1.2 Description des composants

| Composant | Fichier | Role |
|-----------|---------|------|
| **API Enhanced** | `api_enhanced.py` | Point d'entree unique. Expose tous les endpoints REST. Orchestre les sous-systemes. |
| **Agent Orchestrator** | `agents.py` | 7 agents disciplinaires Oil & Gas avec ontologie, raisonnement semantique et routage automatique. |
| **RAG Pipeline** | `query_planner.py`, `retriever.py`, `reranker.py`, `prompts.py`, `guardrails.py` | Pipeline de recherche hybride BM25 + vecteurs, reranking, generation avec anti-hallucination. |
| **Training Pipeline** | `training.py` | Entrainement continu : generation de donnees, apprentissage du vocabulaire, optimisation des poids de recherche. |
| **Project Understanding** | `project_understanding.py` | Analyse semantique des projets : modele de projet, comprehension des requetes, enrichissement du contexte. |
| **File Processor** | `file_processor.py` | Extraction multi-format (PDF, DOCX, XLSX, images, etc.) avec scoring de qualite et degradation gracieuse. |
| **Knowledge Graph** | `knowledge_graph.py` | Graphe de connaissances pour les relations entre documents, equipements et concepts. |
| **Auto-Indexer** | `auto_indexer.py` | Surveillance automatique d'un repertoire et indexation des nouveaux documents. |
| **Configuration** | `config_enhanced.py` | Toutes les variables de configuration centralisees avec support des variables d'environnement. |

### 1.3 Flux de donnees

**Flux d'une requete utilisateur :**

1. L'utilisateur envoie une question via `POST /question`
2. Le **SemanticQueryUnderstanding** analyse l'intention et les entites
3. L'**Agent Orchestrator** identifie les disciplines concernees
4. Le **ContextEnricher** enrichit la requete avec le contexte du projet
5. Le **Query Planner** planifie la strategie de recherche
6. Le **Retriever** execute la recherche hybride (BM25 + vecteurs) dans ChromaDB
7. Le **Reranker** re-ordonne les resultats par pertinence
8. Le **Prompt Builder** construit le prompt avec contexte, regles et garde-fous
9. Le LLM Ollama genere la reponse
10. Les **Guardrails** verifient l'absence d'hallucinations
11. La reponse est renvoyee avec score de confiance et sources

**Flux d'indexation de document :**

1. Le fichier est recu via `POST /index/upload`
2. Le **File Processor** extrait le texte structure avec scoring de qualite
3. Le **Classifier** identifie la discipline et le type de document
4. Le texte est decoupe en chunks avec overlap
5. Les chunks sont indexes dans ChromaDB (vecteurs via Ollama)
6. Le **Knowledge Graph** enregistre les relations entre entites
7. Le **Project Analyzer** met a jour le modele de projet
8. Le **Training Pipeline** note les nouvelles donnees pour le prochain cycle

---

## 2. Installation

### 2.1 Prerequis

| Prerequis | Version minimale | Verification |
|-----------|-----------------|--------------|
| **Systeme d'exploitation** | Linux (Ubuntu 20.04+) ou macOS 12+ | `uname -s` |
| **Python** | 3.10+ | `python3 --version` |
| **Ollama** | derniere version | `ollama --version` |
| **RAM** | 16 Go minimum (32 Go recommande) | `free -h` (Linux) |
| **Disque** | 20 Go libres (modeles IA) | `df -h` |
| **curl** | toute version recente | `curl --version` |

**Optionnel :**
- GPU NVIDIA avec CUDA 12.x pour acceleration du LLM
- Tesseract OCR pour extraction d'images (`apt install tesseract-ocr`)

### 2.2 Installation automatique

Le script `install_and_run_enhanced.sh` automatise toute l'installation :

```bash
# Installation et demarrage standard
chmod +x install_and_run_enhanced.sh
./install_and_run_enhanced.sh

# Avec entrainement initial
./install_and_run_enhanced.sh --training

# Sur un port specifique, sans tests
./install_and_run_enhanced.sh --port=9000 --skip-tests

# Aide
./install_and_run_enhanced.sh --help
```

Le script effectue automatiquement :
1. Detection et installation de Python 3.10+
2. Creation de l'environnement virtuel et installation des dependances (`requirements_enhanced.txt`)
3. Creation de tous les repertoires de persistance (`chroma_db/`, `training_data/`, etc.)
4. Installation et demarrage d'Ollama
5. Telechargement des modeles : `llama3.1:8b`, `nomic-embed-text`, `llava:7b`
6. Tests de validation de tous les modules
7. (Optionnel) Cycle d'entrainement initial
8. Demarrage de l'API sur le port choisi

### 2.3 Installation manuelle

```bash
# 1. Environnement virtuel
python3 -m venv .venv
source .venv/bin/activate

# 2. Dependances
pip install -r requirements_enhanced.txt

# 3. Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &

# 4. Modeles
ollama pull nomic-embed-text
ollama pull llama3.1:8b
ollama pull llava:7b

# 5. Repertoires
mkdir -p chroma_db training_data training_exports fine_tuned_models uploads logs backups

# 6. Demarrage
uvicorn api_enhanced:app --host 0.0.0.0 --port 8000 --reload
```

### 2.4 Verification de l'installation

```bash
# Verifier que l'API repond
curl http://localhost:8000/health

# Reponse attendue :
# {"status": "healthy", "ollama": true, "chroma": true, ...}

# Verifier les agents
curl http://localhost:8000/agents

# Verifier la documentation interactive
# Ouvrir dans un navigateur : http://localhost:8000/docs
```

---

## 3. Systeme Multi-Agents

Le systeme multi-agents est le coeur de l'intelligence metier de Deerflow Lite. Chaque agent possede une **ontologie** (concepts, relations), des **regles de raisonnement** et la capacite de comprendre le contexte semantique d'une requete — pas seulement des mots-cles.

### 3.1 Les 7 agents disciplinaires

#### Agent Process

- **Discipline :** Genie des procedes
- **Domaine :** PFD, P&ID, bilans matiere/energie, simulations HYSYS/Aspen, conditions operatoires
- **Concepts cles :** Pression, temperature, debit, composition, flash drum, colonne de distillation, echangeur de chaleur, reacteur, compresseur
- **Exemple de comprehension :**
  - Requete : *"Quel est le point de rosee du gaz en entree du TEG contactor ?"*
  - L'agent identifie : sujet = TEG contactor, propriete = point de rosee, phase = gaz, position = entree
  - Il sait chercher dans les bilans matiere, les datasheets de deshydratation et les simulations thermodynamiques

#### Agent Mechanical

- **Discipline :** Genie mecanique
- **Domaine :** Equipements sous pression, datasheets, calculs ASME, materiaux, plans mecaniques
- **Concepts cles :** Pression de calcul, temperature de calcul, surepaissseur de corrosion, ASME VIII, epaisseur requise, PWHT, bride, joint
- **Exemple de comprehension :**
  - Requete : *"Le V-301 est-il conforme ASME VIII Div.1 ?"*
  - L'agent identifie le tag equipement V-301 (vessel), la norme ASME VIII Div.1, et cherche les datasheets, rapports de calcul et certificats materiaux

#### Agent Piping

- **Discipline :** Tuyauterie
- **Domaine :** Specs tuyauterie, isometriques, contraintes, supports, P&ID (partie tuyauterie)
- **Concepts cles :** Pipe class, spec break, diametre nominal, schedule, materiau, stress analysis, flexibility, support
- **Exemple de comprehension :**
  - Requete : *"Quels sont les piege specs pour les lignes haute pression en acier inox ?"*
  - L'agent comprend qu'il faut chercher les specifications tuyauterie filtrees par classe de pression et materiau

#### Agent Instrumentation

- **Discipline :** Instrumentation et controle
- **Domaine :** Boucles de controle, SIS, datasheets instruments, logique de securite, P&ID (partie instrumentation)
- **Concepts cles :** Tag instrument (PT, FT, LT, TT, PSV, SDV), SIL, SIF, boucle de regulation, cause & effet
- **Exemple de comprehension :**
  - Requete : *"Quelle est la pression de tarage de la PSV-101 ?"*
  - L'agent identifie le tag PSV-101 (soupape de securite), la propriete = pression de tarage, et cherche dans les datasheets PSV et les etudes HAZOP

#### Agent Electrical

- **Discipline :** Electricite
- **Domaine :** Unifilaires, bilans de charge, classification de zones, dimensionnement cables, MCC
- **Concepts cles :** Tension, puissance, facteur de charge, court-circuit, transformateur, MCC, zone ATEX/NEC
- **Exemple de comprehension :**
  - Requete : *"Quel est le bilan de charge du MCC-01 ?"*
  - L'agent identifie MCC-01 (Motor Control Center), cherche les unifilaires et les listes de charges associees

#### Agent Civil

- **Discipline :** Genie civil et structure
- **Domaine :** Fondations, structures metalliques, plans d'implantation, charges, etudes geotechniques
- **Concepts cles :** Fondation, pieu, charge admissible, portique, surface au sol, etude de sol, tassement
- **Exemple de comprehension :**
  - Requete : *"Quel type de fondation pour le compresseur K-201 ?"*
  - L'agent fait le lien entre l'equipement K-201, ses charges dynamiques (vibration de compresseur), et les etudes geotechniques

#### Agent Safety

- **Discipline :** Securite et environnement
- **Domaine :** HAZOP, SIL, classification de zones, etudes de risques, plans d'urgence, normes HSE
- **Concepts cles :** HAZOP, LOPA, SIL, zone ATEX, scenario de fuite, consequence, barriere de securite, detecteur gaz
- **Exemple de comprehension :**
  - Requete : *"Quelles sont les barrieres de securite identifiees pour le scenario de fuite sur V-301 ?"*
  - L'agent comprend : equipement = V-301, type d'analyse = HAZOP/LOPA, cherche les scenarios de fuite et barrieres associees

### 3.2 Comprehension semantique (pas juste des mots-cles)

Chaque agent utilise trois niveaux de comprehension :

**Niveau 1 — Ontologie**
Chaque discipline possede un graphe de concepts et relations. Par exemple, l'agent Process sait que :
- Un "echangeur de chaleur" est un type d'"equipement statique"
- La "pression de service" est liee a la "pression de calcul" par un facteur de securite
- Un "flash drum" est en amont d'un "compresseur" dans une chaine de traitement de gaz

**Niveau 2 — Detection d'intention**
Le systeme detecte automatiquement le type de requete :
- `LOOKUP` : recherche d'une valeur specifique ("pression de P-101")
- `COMPARISON` : comparaison entre elements ("difference entre V-301 et V-302")
- `CALCULATION` : demande de calcul ("epaisseur requise selon ASME VIII")
- `LISTING` : enumeration ("liste des PSV du systeme de compression")
- `TROUBLESHOOTING` : diagnostic ("pourquoi le debit de FT-201 est instable")
- `DESIGN_CHECK` : verification de conformite ("le V-301 est-il conforme NACE MR0175")
- `SPECIFICATION` : recherche de specification ("spec tuyauterie classe 600#")

**Niveau 3 — Extraction d'entites**
Les entites sont extraites avec leur role dans la requete :
- `SUBJECT` : l'objet principal ("V-301")
- `TARGET` : la propriete recherchee ("pression de calcul")
- `CONSTRAINT` : condition de filtrage ("haute pression", "acier inox")
- `REFERENCE` : norme ou document de reference ("ASME VIII", "API 520")

### 3.3 Orchestration multi-agents

Quand une requete concerne plusieurs disciplines, l'orchestrateur :

1. **Analyse** la requete et identifie les disciplines impliquees
2. **Selectionne** un agent principal et des agents secondaires
3. **Enrichit** la requete avec le contexte de chaque discipline
4. **Fusionne** les resultats avec deduplication et scoring
5. **Genere** une reponse coherente multi-disciplinaire

Exemple : *"Les conditions operatoires du V-301 sont-elles compatibles avec le materiau selectionne ?"*
- Agent principal : **Process** (conditions operatoires)
- Agents secondaires : **Mechanical** (materiau, limites) + **Safety** (NACE, corrosion)

### 3.4 Exemples de requetes et traitement

| Requete | Agent(s) | Traitement |
|---------|----------|------------|
| "Pression de calcul du V-301" | Mechanical | Lookup direct dans datasheets |
| "Debit massique total en entree de l'unite de traitement" | Process | Recherche dans bilans matiere, PFD |
| "Le materiau du V-301 est-il compatible NACE MR0175 ?" | Mechanical + Safety | Verification croisee materiau/norme corrosion |
| "Liste de tous les instruments SIL 2" | Instrumentation + Safety | Croisement listes instruments et classification SIL |
| "Charge du transformateur TR-01 avec le nouveau compresseur K-202" | Electrical + Process | Bilan de charge + donnees process du compresseur |
| "Type de fondation recommande pour K-201 en zone sismique 3" | Civil + Mechanical | Charges dynamiques + etude geotechnique |

---

## 4. Entrainement de l'IA

Le module `training.py` implemente un pipeline d'entrainement continu qui ameliore la qualite du systeme au fil du temps sans necessiter d'intervention humaine.

### 4.1 Pipeline d'entrainement continu

Le cycle d'entrainement s'execute automatiquement (configurable via `TRAINING_CYCLE_INTERVAL`, defaut : 3600 secondes) et comprend quatre phases :

```
 Phase 1            Phase 2             Phase 3             Phase 4
 Generation         Apprentissage       Optimisation        Metriques
 de donnees         du vocabulaire      de la recherche     & rapport
 ┌──────────┐      ┌──────────┐        ┌──────────┐       ┌──────────┐
 │ Feedback  │─────>│ Termes   │───────>│ Poids    │──────>│ Stats    │
 │ Knowledge │      │ Frequence│        │ BM25 vs  │       │ Qualite  │
 │ Graph     │      │ Synonymes│        │ Vecteurs │       │ Log JSON │
 │ Documents │      │ Domaine  │        │ Reranking│       │          │
 └──────────┘      └──────────┘        └──────────┘       └──────────┘
```

### 4.2 Phase 1 : Generation de donnees d'entrainement

Le `TrainingDataGenerator` cree automatiquement des paires question-reponse a partir de :
- **Feedback utilisateur** : les questions notees positivement deviennent des exemples d'entrainement
- **Knowledge Graph** : les relations entre entites generent des questions synthetiques
- **Documents indexes** : les chunks de documents sont transformes en paires Q&A

Templates de generation par discipline (exemples) :
- Process : *"Quel est le {propriete} de {equipement} dans les conditions {condition} ?"*
- Mechanical : *"Quelle est la {specification} du {equipement} selon {norme} ?"*
- Piping : *"Quelle est la classe de tuyauterie pour {service} a {pression} ?"*

### 4.3 Phase 2 : Apprentissage du vocabulaire

Le `VocabularyLearner` enrichit continuellement le dictionnaire de termes du domaine :
- **Extraction de termes** depuis les nouveaux documents indexes
- **Calcul de frequences** pour identifier les termes importants du projet
- **Detection de synonymes** (ex: "heat exchanger" = "echangeur de chaleur")
- **Expansion de requetes** : quand un utilisateur cherche "HX", le systeme sait aussi chercher "echangeur", "heat exchanger", "E-xxx"

Le vocabulaire est persiste dans `vocabulary.json` et utilise pour l'expansion automatique des requetes.

### 4.4 Phase 3 : Optimisation de la recherche

Le `RetrievalOptimizer` ajuste automatiquement :
- **Poids BM25 vs. Vecteurs** : si les recherches par mots-cles donnent de meilleurs resultats que les vecteurs (ou inversement), les poids sont ajustes
- **Parametres de reranking** : nombre de documents rerankques, seuil de pertinence
- **Top-K** : nombre de resultats a recuperer avant reranking

L'optimisation se base sur les metriques de feedback : taux de reponses satisfaisantes, precision des sources citees, couverture des requetes.

### 4.5 Phase 4 : Metriques et rapports

Chaque cycle produit un rapport stocke dans `training_log.json` :

```json
{
  "cycle_id": "train_20260422_143022",
  "timestamp": "2026-04-22T14:30:22",
  "duration_seconds": 45.2,
  "phases": {
    "data_generation": {"pairs_created": 128, "from_feedback": 45, "from_graph": 83},
    "vocabulary": {"new_terms": 34, "total_terms": 1523},
    "retrieval_optimization": {"bm25_weight": 0.38, "vector_weight": 0.62, "improvement": "+3.2%"},
    "metrics": {"avg_confidence": 0.72, "feedback_positive_rate": 0.85}
  }
}
```

### 4.6 Lancer un cycle d'entrainement

**Au demarrage (via le script) :**

```bash
./install_and_run_enhanced.sh --training
```

**Via l'API (systeme en cours d'execution) :**

```bash
# Cycle complet
curl -X POST http://localhost:8000/training/cycle

# Cycle incremental (plus rapide, donnees recentes uniquement)
curl -X POST http://localhost:8000/training/incremental

# Verifier le statut
curl http://localhost:8000/training/status
```

**Programmatiquement (Python) :**

```python
from training import ContinuousTrainer

trainer = ContinuousTrainer()
results = trainer.run_training_cycle()
print(f"Paires generees: {results.get('data_generation', {}).get('pairs_created', 0)}")
print(f"Nouveaux termes: {results.get('vocabulary', {}).get('new_terms', 0)}")
```

---

## 5. Comprehension de projet

Le module `project_understanding.py` depasse la simple recherche par mots-cles en construisant un **modele semantique du projet** Oil & Gas.

### 5.1 Modele de projet (ProjectModel)

Le `ProjectAnalyzer` maintient un modele structure du projet contenant :

- **Equipements** (`EquipmentInfo`) : tag, type, description, systeme, specifications, connexions
- **Systemes** (`System`) : nom, description, equipements, conditions operatoires, flux entree/sortie
- **Documents** (`DocumentInfo`) : source, discipline, type, references equipements, references normes
- **Phases** (`ProjectPhase`) : nom, statut, documents associes, jalons
- **Relations** (`Relationship`) : liens entre entites (equipement-document, equipement-systeme, etc.)

Exemple de modele pour un projet de traitement de gaz :

```
Projet: Unite de Traitement de Gaz - Phase FEED
│
├── Systeme: Compression
│   ├── K-201 (Compresseur centrifuge, 1er etage)
│   │   ├── Datasheet mecanique: DS-K-201-R02.pdf
│   │   ├── Bilan matiere: HMB-SYS-200-R01.xlsx
│   │   └── Connecte a: V-201 (scrubber amont), E-201 (aftercooler aval)
│   └── K-202 (Compresseur centrifuge, 2eme etage)
│       └── ...
│
├── Systeme: Deshydratation (TEG)
│   ├── T-301 (Contacteur TEG)
│   ├── V-301 (Flash drum TEG)
│   └── E-301 (Reboiler TEG)
│
└── Systeme: Separation
    ├── V-101 (Separateur d'entree)
    └── V-102 (Separateur basse pression)
```

### 5.2 Analyse semantique des requetes

Le `SemanticQueryUnderstanding` analyse chaque requete en profondeur :

```python
# Exemple d'analyse interne
requete = "Quelle est la pression maximale admissible du V-301 en tenant compte de la corrosion ?"

analyse = {
    "intention": "SPECIFICATION",
    "discipline_principale": "mechanical",
    "disciplines_secondaires": ["process", "safety"],
    "entites": [
        {"texte": "V-301", "type": "equipement", "role": "SUBJECT"},
        {"texte": "pression maximale admissible", "type": "propriete", "role": "TARGET"},
        {"texte": "corrosion", "type": "contrainte", "role": "CONSTRAINT"}
    ],
    "contexte_implicite": [
        "MAWP (Maximum Allowable Working Pressure)",
        "Surepaissseur de corrosion",
        "ASME VIII",
        "Conditions hydrostatiques"
    ]
}
```

### 5.3 Enrichissement du contexte

Le `ContextEnricher` augmente automatiquement la requete avec des informations pertinentes du modele de projet :

1. **Resolution d'equipement** : "V-301" est enrichi avec son systeme (deshydratation TEG), ses documents associes, ses connexions
2. **Ajout de normes pertinentes** : si la requete mentionne un vessel, les references ASME VIII et API sont ajoutees
3. **Contexte operatoire** : les conditions de process (pression, temperature, composition) sont ajoutees si pertinentes
4. **Documents connexes** : les documents les plus pertinents du modele de projet sont priorises dans la recherche

### 5.4 Evaluation de completude

Le `CompletenessAssessment` evalue si le modele de projet a suffisamment d'informations :

```bash
curl http://localhost:8000/project/completeness
```

Reponse typique :

```json
{
  "overall_score": 0.72,
  "disciplines": {
    "process": {"score": 0.85, "documents": 23, "missing": ["Bilan energetique systeme 400"]},
    "mechanical": {"score": 0.78, "documents": 15, "missing": ["Datasheet V-102"]},
    "piping": {"score": 0.45, "documents": 5, "missing": ["Specs tuyauterie classe 900#", "Stress analysis"]},
    "instrumentation": {"score": 0.82, "documents": 18, "missing": []},
    "electrical": {"score": 0.60, "documents": 8, "missing": ["Unifilaire MCC-02"]},
    "civil": {"score": 0.35, "documents": 3, "missing": ["Etude geotechnique", "Plan d'implantation"]},
    "safety": {"score": 0.90, "documents": 12, "missing": []}
  },
  "recommendations": [
    "Priorite haute: ajouter les specs tuyauterie manquantes (piping: 0.45)",
    "Priorite haute: ajouter l'etude geotechnique et le plan d'implantation (civil: 0.35)",
    "Priorite moyenne: completer le unifilaire MCC-02 (electrical: 0.60)"
  ]
}
```

---

## 6. Traitement des fichiers

Le module `file_processor.py` est un pipeline d'extraction multi-format concu pour les documents d'ingenierie Oil & Gas.

### 6.1 Formats supportes

| Format | Extensions | Methode d'extraction | Notes |
|--------|-----------|---------------------|-------|
| **PDF** | `.pdf` | PyPDF2 + Ollama Vision (fallback OCR) | Gere les PDF scannes via OCR |
| **Word** | `.docx` | python-docx | Extrait texte, tableaux, en-tetes |
| **Excel** | `.xlsx`, `.xls` | openpyxl | Toutes les feuilles, detection de tableaux structures |
| **PowerPoint** | `.pptx` | python-pptx | Texte des diapositives et notes |
| **CSV** | `.csv` | csv (stdlib) | Detection automatique du delimiteur |
| **JSON** | `.json` | json (stdlib) | Aplatissement de structures imbriquees |
| **YAML** | `.yaml`, `.yml` | PyYAML | Fichiers de configuration, specs |
| **HTML** | `.html`, `.htm` | BeautifulSoup | Nettoyage des balises, extraction du contenu |
| **XML** | `.xml` | lxml / ElementTree | Documents structures, metadata |
| **Texte brut** | `.txt`, `.md`, `.rtf` | Lecture directe | Detection d'encodage automatique |
| **Images** | `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`, `.gif` | Ollama Vision (llava) | Lecture de P&ID, datasheets scannes |

### 6.2 Extraction structuree

Le `FileProcessor` ne se contente pas d'extraire du texte brut. Il produit un `ExtractionResult` structure :

```python
@dataclass
class ExtractionResult:
    text: str                          # Texte extrait
    structured_data: Dict[str, Any]    # Donnees structurees (tableaux, metadata)
    tables: List[Dict[str, Any]]       # Tableaux detectes
    metadata: Dict[str, Any]           # Metadonnees du fichier
    extraction_quality: float          # Score de qualite 0.0 - 1.0
    format: str                        # Format detecte
    warnings: List[str]                # Avertissements
    page_count: int                    # Nombre de pages (si applicable)
    has_images: bool                   # Contient des images
    language: str                      # Langue detectee
    source: str                        # Chemin du fichier source
    error: Optional[str]              # Erreur (si echec partiel)
```

Exemple pour un datasheet equipement en Excel :

```json
{
  "text": "Datasheet - Pressure Vessel V-301\nDesign Pressure: 45 barg\nDesign Temperature: 150 C...",
  "structured_data": {
    "sheets": ["General", "Nozzle Schedule", "Materials"],
    "key_values": {
      "Design Pressure": "45 barg",
      "Design Temperature": "150 C",
      "Corrosion Allowance": "3.0 mm",
      "Material Shell": "SA-516 Gr.70"
    }
  },
  "tables": [
    {
      "name": "Nozzle Schedule",
      "headers": ["Mark", "Size", "Rating", "Facing", "Service"],
      "rows": [
        ["N1", "6\"", "300#", "RF", "Inlet"],
        ["N2", "4\"", "300#", "RF", "Outlet"]
      ]
    }
  ],
  "extraction_quality": 0.92,
  "format": "xlsx",
  "page_count": 3,
  "language": "en"
}
```

### 6.3 Qualite d'extraction

Le score `extraction_quality` (0.0 a 1.0) est calcule en fonction de :
- **Volume de texte extrait** par rapport a la taille du fichier
- **Presence de structures** (tableaux, en-tetes, metadata)
- **Coherence linguistique** du texte extrait
- **Absence d'artefacts** OCR (caracteres parasites)

| Score | Signification | Action |
|-------|--------------|--------|
| 0.8 - 1.0 | Extraction de haute qualite | Aucune action requise |
| 0.5 - 0.8 | Extraction acceptable | Verification recommandee |
| 0.3 - 0.5 | Extraction partielle | Fichier peut necesiter un traitement manuel |
| 0.0 - 0.3 | Extraction echouee ou tres faible | Revoir le fichier source |

### 6.4 Gestion des erreurs

Le `FileProcessor` implemente une **degradation gracieuse** :

1. **Tentative principale** : extraction native (PyPDF2 pour PDF, openpyxl pour Excel, etc.)
2. **Fallback OCR** : si l'extraction native echoue ou donne peu de texte, passage a Ollama Vision (llava)
3. **Fallback texte brut** : en dernier recours, lecture binaire avec detection d'encodage
4. **Rapport d'erreur** : le champ `error` et `warnings` documentent les problemes rencontres

Erreurs courantes et comportement :
- **Fichier protege par mot de passe** : erreur retournee, extraction impossible
- **PDF scanne sans OCR** : fallback sur Ollama Vision, qualite variable
- **Excel avec macros** : macros ignorees, seules les donnees sont extraites
- **Fichier corrompu** : extraction partielle si possible, erreur documentee
- **Taille excessive** (> 100 Mo par defaut) : rejet avec message explicatif

---

## 7. API Reference

Base URL : `http://localhost:8000`

Documentation interactive Swagger : `http://localhost:8000/docs`

### 7.1 Endpoints originaux

#### `POST /question` — Poser une question

```bash
curl -X POST http://localhost:8000/question \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Quelle est la pression de calcul du V-301 ?",
    "top_k": 10,
    "discipline": "mechanical"
  }'
```

Reponse :

```json
{
  "answer": "La pression de calcul du V-301 est de 45 barg selon le datasheet mecanique DS-V-301-R02.",
  "confidence": 0.87,
  "confidence_level": "high",
  "sources": [
    {"document": "DS-V-301-R02.pdf", "chunk": "Design Pressure: 45 barg...", "score": 0.92}
  ],
  "discipline": "mechanical",
  "entities_found": ["V-301"],
  "processing_time": 2.3
}
```

#### `POST /index` — Indexer un document (par chemin)

```bash
curl -X POST http://localhost:8000/index \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "/data/documents/DS-V-301-R02.pdf",
    "discipline": "mechanical",
    "project": "GTG-Phase2"
  }'
```

#### `POST /index/upload` — Indexer un fichier (upload)

```bash
curl -X POST http://localhost:8000/index/upload \
  -F "file=@DS-V-301-R02.pdf" \
  -F "discipline=mechanical"
```

#### `GET /health` — Sante du systeme

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "healthy",
  "ollama": true,
  "chroma": true,
  "documents_indexed": 156,
  "uptime_seconds": 3600
}
```

#### `GET /stats` — Statistiques

```bash
curl http://localhost:8000/stats
```

```json
{
  "total_documents": 156,
  "total_chunks": 2340,
  "disciplines": {"process": 45, "mechanical": 32, "piping": 18, "instrumentation": 28, "electrical": 12, "civil": 8, "safety": 13},
  "avg_confidence": 0.74,
  "total_queries": 523,
  "vocabulary_size": 1523
}
```

#### `POST /feedback` — Envoyer un retour

```bash
curl -X POST http://localhost:8000/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Pression de calcul du V-301 ?",
    "answer": "45 barg",
    "rating": 5,
    "comment": "Reponse exacte"
  }'
```

#### `GET /graph/{entity}` — Interroger le graphe de connaissances

```bash
curl http://localhost:8000/graph/V-301
```

#### `GET /graph/document/{filename}` — Reseau d'un document

```bash
curl http://localhost:8000/graph/document/DS-V-301-R02.pdf
```

#### `GET /vocabulary/expand` — Expansion de requete

```bash
curl "http://localhost:8000/vocabulary/expand?query=heat+exchanger"
```

#### `GET /learning/stats` — Statistiques d'apprentissage

```bash
curl http://localhost:8000/learning/stats
```

#### `POST /learning/rebuild` — Reconstruire le vocabulaire

```bash
curl -X POST http://localhost:8000/learning/rebuild
```

#### `GET /auto-indexer/status` — Statut de l'auto-indexeur

```bash
curl http://localhost:8000/auto-indexer/status
```

#### `GET /` — Page d'accueil

```bash
curl http://localhost:8000/
```

### 7.2 Nouveaux endpoints (Enhanced)

#### `GET /agents` — Lister tous les agents

```bash
curl http://localhost:8000/agents
```

```json
{
  "agents": [
    {
      "discipline": "process",
      "description": "Agent specialise en genie des procedes Oil & Gas",
      "concepts_count": 45,
      "rules_count": 12,
      "status": "active"
    },
    {
      "discipline": "mechanical",
      "description": "Agent specialise en genie mecanique et equipements sous pression",
      "concepts_count": 38,
      "rules_count": 10,
      "status": "active"
    }
  ],
  "total": 7,
  "coordination_mode": "sequential"
}
```

#### `GET /agents/{discipline}` — Details d'un agent

```bash
curl http://localhost:8000/agents/process
```

```json
{
  "discipline": "process",
  "ontology": {
    "concepts": ["pressure_vessel", "heat_exchanger", "compressor", "separator", "column"],
    "relations": [
      {"from": "flash_drum", "relation": "upstream_of", "to": "compressor"},
      {"from": "heat_exchanger", "relation": "is_a", "to": "static_equipment"}
    ]
  },
  "reasoning_rules": [
    {"id": "PR-001", "description": "Verifier les conditions de design vs operating"}
  ]
}
```

#### `POST /training/cycle` — Lancer un cycle d'entrainement complet

```bash
curl -X POST http://localhost:8000/training/cycle
```

```json
{
  "cycle_id": "train_20260422_143022",
  "status": "completed",
  "duration_seconds": 45.2,
  "data_generated": 128,
  "vocabulary_updated": 34,
  "retrieval_optimized": true
}
```

#### `POST /training/incremental` — Entrainement incremental

```bash
curl -X POST http://localhost:8000/training/incremental
```

#### `GET /training/status` — Statut de l'entrainement

```bash
curl http://localhost:8000/training/status
```

```json
{
  "last_cycle": "2026-04-22T14:30:22",
  "total_cycles": 15,
  "auto_training_enabled": true,
  "next_scheduled": "2026-04-22T15:30:22",
  "training_data_pairs": 1856,
  "vocabulary_size": 1523
}
```

#### `GET /project/summary` — Resume du projet

```bash
curl http://localhost:8000/project/summary
```

```json
{
  "project_name": "Unite de Traitement de Gaz - Phase FEED",
  "total_documents": 156,
  "total_equipment": 47,
  "systems": ["Compression", "Deshydratation TEG", "Separation", "Utilities"],
  "disciplines_coverage": {"process": 0.85, "mechanical": 0.78, "piping": 0.45},
  "last_updated": "2026-04-22T12:00:00"
}
```

#### `GET /project/equipment/{tag}` — Informations sur un equipement

```bash
curl http://localhost:8000/project/equipment/V-301
```

```json
{
  "tag": "V-301",
  "type": "pressure_vessel",
  "description": "Flash Drum TEG",
  "system": "Deshydratation TEG",
  "specifications": {
    "design_pressure": "45 barg",
    "design_temperature": "150 C",
    "material": "SA-516 Gr.70"
  },
  "related_documents": ["DS-V-301-R02.pdf", "HMB-SYS-300-R01.xlsx"],
  "connected_to": ["T-301", "E-301", "P-301"]
}
```

#### `GET /project/systems` — Lister les systemes

```bash
curl http://localhost:8000/project/systems
```

#### `POST /project/question` — Question contextuelle projet

```bash
curl -X POST http://localhost:8000/project/question \
  -H "Content-Type: application/json" \
  -d '{"question": "Quels equipements manquent dans le systeme de compression ?"}'
```

#### `GET /project/completeness` — Evaluation de completude

```bash
curl http://localhost:8000/project/completeness
```

---

## 8. Configuration avancee

Toutes les variables sont definies dans `config_enhanced.py` et peuvent etre surchargees par des variables d'environnement.

### 8.1 Variables d'environnement

#### Ollama / LLM

| Variable | Defaut | Description |
|----------|--------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL du serveur Ollama |
| `OLLAMA_MODEL` | `llama3.1:8b` | Modele LLM principal |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Modele d'embedding |
| `OLLAMA_VISION_MODEL` | `llava:7b` | Modele de vision (OCR images) |
| `LLM_TEMPERATURE` | `0.1` | Temperature de generation (0.0 = deterministe, 1.0 = creatif) |
| `LLM_MAX_TOKENS` | `4096` | Nombre maximum de tokens en sortie |
| `LLM_TIMEOUT` | `120` | Timeout en secondes pour les appels LLM |

#### ChromaDB / Recherche

| Variable | Defaut | Description |
|----------|--------|-------------|
| `CHROMA_PERSIST_DIR` | `./chroma_db` | Repertoire de persistance ChromaDB |
| `CHROMA_COLLECTION` | `oil_gas_docs` | Nom de la collection de vecteurs |
| `CHUNK_SIZE` | `1000` | Taille des chunks (caracteres) |
| `CHUNK_OVERLAP` | `200` | Chevauchement entre chunks |
| `TOP_K` | `20` | Nombre de resultats a recuperer |
| `BM25_WEIGHT` | `0.4` | Poids de la recherche BM25 |
| `VECTOR_WEIGHT` | `0.6` | Poids de la recherche vectorielle |
| `RERANK_TOP_N` | `12` | Nombre de resultats apres reranking |
| `CONTEXT_MAX_CHARS` | `15000` | Taille maximale du contexte envoye au LLM |

#### Anti-hallucination

| Variable | Defaut | Description |
|----------|--------|-------------|
| `HALLUCINATION_THRESHOLD` | `0.3` | Seuil en dessous duquel la reponse est rejetee |
| `GROUNDING_CHECK` | `True` | Activer la verification d'ancrage factuel |
| `MAX_CLAIMS_UNGROUNDED` | `0` | Nombre maximal d'affirmations non fondees tolerees |

### 8.2 Parametres des agents

| Variable | Defaut | Description |
|----------|--------|-------------|
| `AGENT_TIMEOUT` | `300` | Timeout par tache d'agent (secondes) |
| `MAX_SECONDARY_AGENTS` | `5` | Nombre maximal d'agents secondaires simultanees |
| `AGENT_RETRY_LIMIT` | `3` | Nombre de tentatives en cas d'echec transitoire |
| `AGENT_HEARTBEAT_INTERVAL` | `30` | Intervalle de heartbeat (secondes) |
| `AGENT_MESSAGE_QUEUE_SIZE` | `100` | Taille de la file de messages inter-agents |
| `AGENT_COORDINATION_MODE` | `sequential` | Mode de coordination : `sequential`, `parallel`, `hybrid` |

### 8.3 Parametres d'entrainement

| Variable | Defaut | Description |
|----------|--------|-------------|
| `TRAINING_CYCLE_INTERVAL` | `3600` | Intervalle entre cycles automatiques (secondes) |
| `MIN_FEEDBACK_FOR_TRAINING` | `10` | Feedback minimum pour declencher un entrainement |
| `TRAINING_BATCH_SIZE` | `32` | Taille de lot pour l'entrainement |
| `TRAINING_EPOCHS` | `3` | Nombre d'epoques par cycle |
| `TRAINING_LEARNING_RATE` | `2e-5` | Taux d'apprentissage |
| `TRAINING_DATA_DIR` | `./training_data` | Repertoire des donnees d'entrainement |
| `TRAINING_EXPORT_DIR` | `./training_exports` | Repertoire d'export des modeles |
| `AUTO_TRAINING_ENABLED` | `True` | Activer l'entrainement automatique |

### 8.4 Parametres projet

| Variable | Defaut | Description |
|----------|--------|-------------|
| `PROJECT_MODEL_PATH` | `project_model.json` | Chemin du modele de projet |
| `AUTO_PROJECT_ANALYSIS` | `True` | Analyser automatiquement les documents a l'indexation |
| `PROJECT_SUMMARY_MAX_CHARS` | `5000` | Longueur maximale du resume de projet |
| `PROJECT_CONTEXT_WINDOW` | `8192` | Fenetre de contexte projet (tokens) |
| `PROJECT_ANALYSIS_DEPTH` | `standard` | Profondeur d'analyse : `light`, `standard`, `deep` |

### 8.5 Parametres traitement de fichiers

| Variable | Defaut | Description |
|----------|--------|-------------|
| `MAX_FILE_SIZE` | `104857600` (100 Mo) | Taille maximale de fichier acceptee |
| `OCR_ENABLED` | `True` | Activer l'OCR pour les images et PDF scannes |
| `OCR_LANGUAGE` | `fra+eng` | Langues Tesseract pour l'OCR |
| `OCR_DPI` | `300` | Resolution pour l'OCR |
| `OCR_CONFIDENCE_THRESHOLD` | `0.6` | Seuil de confiance OCR |
| `ENCODING_DETECTION_ENABLED` | `True` | Detection automatique d'encodage |
| `DEFAULT_ENCODING` | `utf-8` | Encodage par defaut |

### 8.6 Exemple de fichier `.env`

```bash
# .env - Configuration Deerflow Lite Enhanced
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
OLLAMA_EMBED_MODEL=nomic-embed-text
OLLAMA_VISION_MODEL=llava:7b

# Recherche
TOP_K=25
BM25_WEIGHT=0.35
VECTOR_WEIGHT=0.65
CONTEXT_MAX_CHARS=20000

# Agents
AGENT_COORDINATION_MODE=hybrid
AGENT_TIMEOUT=600
MAX_SECONDARY_AGENTS=3

# Entrainement
TRAINING_CYCLE_INTERVAL=7200
AUTO_TRAINING_ENABLED=True

# Projet
PROJECT_ANALYSIS_DEPTH=deep

# Fichiers
MAX_FILE_SIZE=209715200
OCR_LANGUAGE=fra+eng

# Logging
LOG_LEVEL=INFO
```

---

## 9. Depannage

### 9.1 Problemes courants et solutions

#### Ollama ne demarre pas

**Symptome :** `[ERREUR] Ollama ne demarre pas`

**Solutions :**
1. Verifier qu'Ollama n'est pas deja en cours : `ps aux | grep ollama`
2. Verifier le port : `curl http://localhost:11434/api/tags`
3. Redemarrer : `killall ollama && ollama serve`
4. Verifier les logs : `journalctl -u ollama` (Linux avec systemd)
5. Si GPU NVIDIA : verifier les drivers CUDA avec `nvidia-smi`

#### Reponses de faible confiance

**Symptome :** Toutes les reponses ont un score de confiance < 0.4

**Solutions :**
1. Verifier le nombre de documents indexes : `curl http://localhost:8000/stats`
2. Si peu de documents : indexer plus de documentation technique
3. Verifier l'embedding : `curl -X POST http://localhost:11434/api/embeddings -d '{"model":"nomic-embed-text","prompt":"test"}'`
4. Lancer un cycle d'entrainement : `curl -X POST http://localhost:8000/training/cycle`
5. Verifier le vocabulaire : `curl http://localhost:8000/vocabulary/expand?query=votre+terme`

#### Erreurs d'import des modules

**Symptome :** `ModuleNotFoundError: No module named 'agents'`

**Solutions :**
1. Verifier que le virtualenv est active : `which python` (doit pointer vers `.venv/`)
2. Reinstaller les dependances : `pip install -r requirements_enhanced.txt`
3. Verifier que les fichiers sont presents : `ls agents.py training.py project_understanding.py file_processor.py`
4. Verifier le repertoire de travail du serveur

#### ChromaDB corrompue

**Symptome :** Erreurs `sqlite3.DatabaseError` ou `chroma` au demarrage

**Solutions :**
1. Sauvegarder : `cp -r chroma_db chroma_db_backup`
2. Supprimer et reconstruire : `rm -rf chroma_db && mkdir chroma_db`
3. Reindexer les documents : utiliser `POST /index` ou `POST /learning/rebuild`

#### Extraction de fichier echouee

**Symptome :** `extraction_quality: 0.0` ou erreur lors de l'upload

**Solutions :**
1. Verifier la taille du fichier (< 100 Mo par defaut)
2. Pour les PDF scannes : verifier qu'Ollama Vision fonctionne (`ollama pull llava:7b`)
3. Pour les fichiers proteges : retirer la protection avant l'upload
4. Verifier le format : `file votre_document.pdf`
5. Pour les images : verifier le format (PNG, JPG, TIFF supportes)

#### L'entrainement ne se declenche pas

**Symptome :** `training/status` montre que le dernier cycle est ancien

**Solutions :**
1. Verifier que l'entrainement auto est active : `AUTO_TRAINING_ENABLED=True`
2. Verifier le seuil de feedback : si moins de 10 feedbacks (`MIN_FEEDBACK_FOR_TRAINING`), l'entrainement ne se declenche pas
3. Declencher manuellement : `curl -X POST http://localhost:8000/training/cycle`
4. Verifier les logs pour des erreurs : `LOG_LEVEL=DEBUG`

#### Performance lente

**Symptome :** Les requetes prennent plus de 10 secondes

**Solutions :**
1. Utiliser un modele LLM plus petit : `OLLAMA_MODEL=llama3.2:3b`
2. Reduire TOP_K : `TOP_K=10`
3. Reduire le contexte : `CONTEXT_MAX_CHARS=8000`
4. Activer le mode GPU si disponible (verifier `nvidia-smi`)
5. Reduire le nombre d'agents secondaires : `MAX_SECONDARY_AGENTS=2`
6. Passer en mode sequentiel : `AGENT_COORDINATION_MODE=sequential`

#### Port deja utilise

**Symptome :** `[ERROR] Address already in use`

**Solutions :**
1. Trouver le processus : `lsof -i :8000` (ou `ss -tlnp | grep 8000`)
2. Arreter le processus : `kill <PID>`
3. Utiliser un autre port : `./install_and_run_enhanced.sh --port=9000`

#### Problemes de memoire

**Symptome :** `MemoryError` ou le systeme plante

**Solutions :**
1. Verifier la RAM disponible : `free -h`
2. Utiliser un modele plus petit : `OLLAMA_MODEL=llama3.2:3b` (necessite environ 4 Go RAM)
3. Reduire la taille de lot d'entrainement : `TRAINING_BATCH_SIZE=8`
4. Reduire le nombre de chunks en memoire : `TOP_K=10`

### 9.2 Logs et diagnostic

```bash
# Activer les logs detailles
export LOG_LEVEL=DEBUG
uvicorn api_enhanced:app --host 0.0.0.0 --port 8000 --reload

# Verifier la sante complete
curl http://localhost:8000/health | python3 -m json.tool

# Diagnostiquer un agent specifique
curl http://localhost:8000/agents/process | python3 -m json.tool

# Verifier les metriques d'entrainement
curl http://localhost:8000/training/status | python3 -m json.tool

# Verifier la completude du projet
curl http://localhost:8000/project/completeness | python3 -m json.tool
```

### 9.3 Reinitialisation complete

En dernier recours, pour repartir de zero :

```bash
# Sauvegarder les donnees importantes
cp -r chroma_db chroma_db_backup_$(date +%Y%m%d)
cp knowledge_db.json knowledge_db_backup.json
cp feedback_db.json feedback_db_backup.json

# Reinitialiser
rm -rf chroma_db .venv
rm -f knowledge_db.json vocabulary.json project_model.json training_log.json
rm -f agent_state.json agent_history.json metrics.json

# Relancer l'installation
./install_and_run_enhanced.sh --training
```

---

*Deerflow Lite Enhanced v3.0 — Systeme RAG agentic pour projets Oil & Gas*
