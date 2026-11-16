# 🚀 ARKAN EPC COPILOT — Guide de Déploiement & Portabilité Clé en Main

Ce dossier `DATA BASE IA` est **100% autonome et portable**. Vous pouvez le copier sur n'importe quel PC Windows (10 / 11) et l'exécuter immédiatement sans configuration manuelle.

---

## 💻 Comment lancer ARKAN sur un nouveau PC Windows ?

1. **Copiez l'intégralité du dossier `DATA BASE IA`** sur votre nouveau PC (ex: sur votre Bureau, `C:\ARKAN` ou un disque externe).
2. **Double-cliquez sur `ARKAN_Setup.exe`** (ou `Start_ARKAN.bat`).
3. **C'est tout !** L'auto-configurateur s'occupe de tout :
   - Initialise les configurations et secrets `.env`
   - Démarre Neo4j et ChromaDB (via Docker ou local)
   - Vérifie Ollama et charge automatiquement le modèle `arkan-planning`
   - Crée le raccourci **"ARKAN EPC Copilot"** sur votre Bureau
   - Ouvre automatiquement votre navigateur Web sur `http://localhost:8000`

---

## 💾 Sauvegarde & Migration en 1 Clic (Depuis l'Interface)

Vous pouvez sauvegarder ou restaurer toutes vos données directement depuis l'API / interface Web :

- **Sauvegarder** : Téléchargez l'archive complète de vos plannings, dossiers ARH et graphes via :
  👉 `http://localhost:8000/api/system/export-backup`
- **Restaurer** : Restaurez n'importe quelle archive `.zip` précédente via l'endpoint :
  👉 `POST http://localhost:8000/api/system/import-backup`

---

## 🔧 Architecture des Services & Ports

| Service | Port | Rôle |
|---|---|---|
| **Interface Web ARKAN** | `8000` | Application principale & Swagger API (`/docs`) |
| **Graphe Neo4j** | `7474` (Web) / `7687` (Bolt) | Topologie des installations, P&ID et équipements |
| **Base Vectorielle ChromaDB** | `8001` (ou local) | Recherche sémantique RAG & normes |
| **Moteur IA Ollama** | `11434` | Modèle fine-tuné EPC `arkan-planning` |

---

## ❓ En cas de question sur le nouveau PC

- **Si Docker Desktop n'est pas installé** : `ARKAN_Setup.exe` bascule automatiquement en mode direct local pour que l'application démarre sans interruption.
- **Pour arrêter l'application** : Fermez simplement la fenêtre console ouverte lors du lancement ou appuyez sur `Ctrl+C`.
