# Guide Complet de Délocalisation & Migration d'ARKAN sur un Nouveau PC

Ce document explique pas à pas comment migrer l'intégralité du système **ARKAN EPC Intelligence & ARH Management** (`DATA BASE IA`) d'un PC vers un autre sous Windows, et contient le **Prompt Autonome Ultra-Détaillé pour Antigravity** à exécuter sur la machine de destination.

---

## 1. Ce qu'il faut copier & précautions

### A. Dossiers et fichiers à copier
Vous pouvez copier l'intégralité du répertoire `DATA BASE IA` sur un disque externe ou via le réseau local :
- Tous les scripts Python (`api_enhanced.py`, `arh_document_processor.py`, `arh_equipment_specialists.py`, `arh_pid_topology_engine.py`, etc.).
- Les bases de données SQLite : `arh_dossiers.db`, `procurement.db`, `test_quick.db`.
- La base vectorielle ChromaDB : dossier `chroma_db/`.
- Les modèles et mémoires d'ingénierie : `project_model.json`, `knowledge_graph.json`, `data/`, `arh_uploads/`.
- Les interfaces web : `arkan-ui.html`, `deerflow-lite-ui-enhanced.html`.
- Les fichiers de configuration : `.env`, `config.py`, `Modelfile_ARH`.
- Les fichiers de dépendances : `requirements_core.txt`, `requirements_full.txt`.

### B. Attention au dossier `venv` (Environnement Virtuel)
> [!WARNING]
> Sous Windows, un dossier `venv` contient des chemins absolus vers l'interpréteur Python du PC d'origine (dans `venv\pyvenv.cfg` et dans les scripts `.exe` de `venv\Scripts\`).
> **Ne tentez pas d'exécuter directement le `venv` copié**. Sur le nouveau PC, il doit être recréé proprement. L'agent Antigravity s'en chargera automatiquement grâce au prompt ci-dessous.

---

## 2. Prérequis sur le Nouveau PC

Avant de lancer Antigravity ou l'installation, assurez-vous d'avoir installé sur le nouveau PC :

1. **Python** (version 3.10, 3.11, 3.12 ou supérieure) :
   - Téléchargeable sur [python.org](https://www.python.org/downloads/).
   - ⚠️ **Cocher impérativement la case "Add python.exe to PATH"** lors de l'installation.
2. **Ollama pour Windows** :
   - Téléchargeable sur [ollama.com/download/windows](https://ollama.com/download/windows).
   - L'application doit être lancée (icône visible dans la barre des tâches près de l'horloge).
3. **Google Antigravity** :
   - Installé et ouvert sur le dossier copié (`DATA BASE IA`).

---

## 3. Modèles Ollama Recommandés sur le Nouveau PC

Ouvrez une invite de commande PowerShell sur le nouveau PC et exécutez les téléchargements des modèles de base :

```powershell
# 1. Modèle d'embedding vectoriel RAG (Obligatoire pour ChromaDB)
ollama pull nomic-embed-text

# 2. Modèle de raisonnement rapide & extraction sémantique ARH (Recommandé)
ollama pull llama3.2:3b

# 3. Modèle de vision pour les plans CAD, cartouches et P&ID (Recommandé)
ollama pull qwen2.5vl:3b

# 4. Modèle de raisonnement approfondi (Optionnel si >= 16 Go RAM)
ollama pull llama3.1:8b
# ou
ollama pull qwen2.5:14b
```

*Pour recréer le modèle personnalisé ARH 14B (si votre machine dispose d'au moins 16 Go de RAM / 8 Go VRAM) :*
```powershell
ollama create arkan-arh-14b -f Modelfile_ARH
```

---

## 4. Prompt Ultra-Détaillé pour Antigravity sur le Nouveau PC

Copiez l'intégralité du bloc ci-dessous et collez-le directement dans le chat d'**Antigravity** sur le nouveau PC après avoir ouvert le dossier du projet :

```markdown
Tu es Antigravity, l'agent IA d'ingénierie en charge du déploiement, de la configuration et de la validation opérationnelle d'ARKAN EPC Intelligence & ARH Management sur cette nouvelle machine.

Ce dossier provient d'une migration depuis un autre PC. Ta mission est d'automatiser 100% de la réinstallation, de vérifier chaque composant logiciel et matériel, de lancer les tests de régression et de démarrer le serveur de production.

Exécute les étapes suivantes de manière proactive, autonome et sans attendre de confirmation pour les commandes harmless :

### ÉTAPE 1 : AUDIT DE L'ENVIRONNEMENT LOCAL
1. Détecte la version de l'OS Windows, l'emplacement de python.exe système (`python --version`, `where python`).
2. Vérifie la présence d'un GPU NVIDIA (via `nvidia-smi`) ou si l'inférence tourne sur CPU.
3. Vérifie l'état du dossier `venv` existant :
   - Si `venv` pointe vers un ancien chemin absolu ou échoue à s'exécuter, supprime l'ancien `venv` (ou sauvegarde-le) et recrée un environnement virtuel neuf :
     `python -m venv venv`
   - Active-le et mets à jour pip :
     `.\venv\Scripts\python.exe -m pip install --upgrade pip`

### ÉTAPE 2 : INSTALLATION DES DÉPENDANCES PYTHON
1. Installe l'intégralité des dépendances nécessaires via :
   `.\venv\Scripts\python.exe -m pip install -r requirements_core.txt`
2. Si certains packages avancés manquent, vérifie la présence de :
   - `fastapi`, `uvicorn`, `pydantic`, `httpx`
   - `PyMuPDF` (fitz), `pdfplumber`, `ezdxf`, `Pillow`
   - `chromadb`, `networkx`, `lightrag-hku`
   - `pint` (normalisation physique), `dspy` (assertions neuro-symboliques)
   - `sahi`, `rapidocr-onnxruntime`, `opencv-python` (vision CAD grand format)
   - `ollama`, `sentence-transformers`, `scikit-learn`
3. Valide par un script Python one-liner que TOUS ces modules s'importent sans aucune ImportError.

### ÉTAPE 3 : VÉRIFICATION DU SERVICE OLLAMA & DES MODÈLES LOCAUX
1. Teste si le démon Ollama répond sur `http://localhost:11434/api/tags`.
   - Si Ollama n'est pas démarré, lance-le ou avertis l'utilisateur avec la commande de démarrage.
2. Liste les modèles disponibles via `ollama list`.
3. Vérifie au minimum la présence de :
   - `nomic-embed-text` (obligatoire pour ChromaDB)
   - `llama3.2:3b` ou `qwen2.5:3b` (moteur sémantique ARH)
   - `qwen2.5vl:3b` (moteur vision CAD / P&ID)
   Si un modèle essentiel manque, lance son téléchargement via `ollama pull <model>`.

### ÉTAPE 4 : CONTRÔLE D'INTÉGRITÉ DES DONNÉES & BASES
1. Vérifie la présence des bases SQLite et fichiers JSON critiques :
   - `arh_dossiers.db`
   - `procurement.db`
   - `project_model.json`
   - `chroma_db/`
2. Vérifie la cohérence du fichier `.env` local (chemins relatifs, clés API, port 8000).

### ÉTAPE 5 : EXÉCUTION DE LA SUITE DE TESTS COMPLÈTE
Exécute les suites de validation officielles avec `.\venv\Scripts\python.exe` :
1. `test_modernized_arh_pipeline.py` (valide Pint, DSPy Assertions, MultiDocumentConcordanceGraph, SAHI/RapidOCR et P&ID Topology).
2. `test_pipeline_connectivity.py` (valide les règles de transport Décret 21-315, gares de racleurs et vannes MLV).
3. Confirme que tous les tests affichent "OK" (0 échec).

### ÉTAPE 6 : DÉMARRAGE DU BACKEND FASTAPI & TESTS D'ENDPOINTS
1. Démarre le serveur FastAPI en tâche de fond (daemon) :
   `.\venv\Scripts\python.exe -m uvicorn api_enhanced:app --host 127.0.0.1 --port 8000 --log-level info`
2. Attends l'initialisation et teste les endpoints via requête HTTP locale :
   - `GET http://127.0.0.1:8000/docs` -> Attendu : 200 OK
   - `GET http://127.0.0.1:8000/api/health` ou endpoint équivalent
   - `GET http://127.0.0.1:8000/api/arh/dossiers` -> Attendu : 200 OK
3. Vérifie que l'interface utilisateur `arkan-ui.html` est servie correctement.

### RAPPORT FINAL ATTENDU
À la fin de ton intervention, dresse un tableau de bord récapitulatif clair :
- Statut de l'environnement virtuel Python
- Statut du serveur Ollama et liste des modèles actifs
- Statut des bases de données et collections ChromaDB
- Résultats des tests unitaires et d'intégration
- URL d'accès direct au système : `http://127.0.0.1:8000` et `http://127.0.0.1:8000/docs`
```

---

## 5. Démarrage Manuel Sans Agent (Procédure de Secours)

Si vous souhaitez démarrer manuellement sans passer par Antigravity :

```powershell
# 1. Se placer dans le dossier
cd "D:\DATA BASE IA"

# 2. Créer l'environnement virtuel
python -m venv venv

# 3. L'activer
.\venv\Scripts\Activate.ps1

# 4. Installer les dépendances
pip install --upgrade pip
pip install -r requirements_core.txt

# 5. Démarrer le serveur
python -m uvicorn api_enhanced:app --host 127.0.0.1 --port 8000

# 6. Accéder à l'application
# Ouvrez votre navigateur sur : http://localhost:8000
```
