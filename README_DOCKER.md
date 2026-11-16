# README_DOCKER.md — DeerFlow Lite · Guide de démarrage Docker

## Stack
| Service | Image | Port | Rôle |
|---|---|---|---|
| `deerflow-api` | python:3.11-slim | 8000 | API FastAPI RAG |
| `neo4j` | neo4j:5.15-community | 7474 / 7687 | Knowledge Graph |
| `chromadb` | chromadb/chroma:latest | 8001 | Vector Store |
| `ollama` | ollama/ollama:latest | 11434 | LLM + Embeddings GPU |

---

## Pré-requis

- Docker Desktop ≥ 4.25 (avec GPU support NVIDIA activé)
- NVIDIA Container Toolkit installé
- RTX 3050 (4 GB VRAM) + 32 GB RAM
- Les modèles Ollama déjà téléchargés localement

---

## 5 étapes pour démarrer

### Étape 1 — Installer le driver neo4j Python

```powershell
cd "D:\DATA BASE IA"
C:\Users\BOULAISA.ADLENE\AppData\Local\Programs\Python\Python311\python.exe -m pip install neo4j>=5.14.0
```

### Étape 2 — Lancer les conteneurs Docker

```powershell
cd "D:\DATA BASE IA"
docker compose up -d neo4j chromadb ollama
```

Attendre que Neo4j soit prêt (~60s) :
```powershell
docker compose logs -f neo4j
# Chercher la ligne : "Remote interface available at http://localhost:7474/"
```

### Étape 3 — Initialiser Neo4j (schéma + migration JSON)

```powershell
C:\Users\BOULAISA.ADLENE\AppData\Local\Programs\Python\Python311\python.exe neo4j_init.py
```

Sortie attendue :
```
[neo4j_init] INFO Neo4j prêt après 1 tentative(s) ✓
[neo4j_init] INFO Schéma Neo4j créé.
[neo4j_init] INFO Projet LDBP5 créé/vérifié dans Neo4j.
[neo4j_init] INFO Migration terminée : N entités insérées.
```

### Étape 4 — Lancer l'API DeerFlow

**Mode développement (sans Docker) :**
```powershell
cd "D:\DATA BASE IA"
C:\Users\BOULAISA.ADLENE\AppData\Local\Programs\Python\Python311\python.exe deerflow_start.py
```

**Mode Docker complet :**
```powershell
docker compose up -d
```

### Étape 5 — Valider l'intégration

```powershell
cd "D:\DATA BASE IA"
.\run_all_tests.ps1
```

Résultat attendu :
```
RESULTAT FINAL : 7/7 tests passes
0 ERREUR -- Integration validee !
```

---

## Vérifications utiles

### Neo4j Browser
Ouvrir dans le navigateur : http://localhost:7474
- Login : `neo4j` / `deerflow_oilgas_2025`
- Requête de test : `MATCH (n) RETURN n LIMIT 25`

### API Health
```powershell
Invoke-WebRequest -Uri http://localhost:8000/health | Select-Object StatusCode, Content
```

### Statut Neo4j depuis l'API
```powershell
Invoke-WebRequest -Uri http://localhost:8000/system/health | Select-Object Content
```

---

## Variables d'environnement clés (.env)

| Variable | Valeur Docker | Description |
|---|---|---|
| `NEO4J_URI` | `bolt://neo4j:7687` | Connexion Bolt inter-conteneurs |
| `NEO4J_ENABLED` | `true` | Activer Neo4j (false = fallback JSON) |
| `CHROMA_MODE` | `server` | Mode serveur ChromaDB |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama inter-conteneurs |
| `EMBEDDING_DIM` | `768` | Dimension nomic-embed-text |

---

## Dépannage

### Neo4j ne démarre pas
```powershell
docker compose logs neo4j --tail=50
# Augmenter la mémoire si nécessaire dans docker-compose.yml :
# NEO4J_dbms_memory_heap_max__size: "4G"
```

### Rollback vers JSON (sans Docker)
Mettre dans `.env` :
```
NEO4J_ENABLED=false
CHROMA_MODE=local
OLLAMA_BASE_URL=http://localhost:11434
```
L'API continue de fonctionner avec le fallback JSON automatique.

### Supprimer api.py manuellement
```powershell
Remove-Item "D:\DATA BASE IA\api.py.DISABLED" -Force
```

---

## Roadmap Autonomie Niveau 4

| Phase | Semaine | Action |
|---|---|---|
| 1 | S1 | CRAG auto-rating (grounding ≥ 0.8 → good auto) |
| 2 | S2 | trainer_synthetic nocturne → Q&A LDBP5 |
| 3 | S3 | Fine-tune nomic-embed-text sur corpus LDBP5 |
| 4 | S4 | Boucle nocturne complète + rebuild Neo4j auto |
