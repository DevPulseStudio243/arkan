# ARKAN — Plateforme IA pour Ingénierie de Tuyauterie & P&ID

**ARKAN** est un copilote d'ingénierie EPC intelligent dédié à l'analyse, l'extraction et la vérification des plans d'ingénierie industrielle (P&ID, plans isométriques, schémas tuyauterie).

---

## 🎯 Fonctionnalités Clés

- **Extraction P&ID & Isométriques** : Détection et reconnaissance universelle des composants (tuyauterie, vannes, instruments, raccords, BOM).
- **Conformité Normative** : Validation automatique selon les normes internationales (ASME B31.3 / B16.5 / B16.9, ISA-5.1, IEC/CEI, NFPA).
- **Vérification Graph-Native** : Représentation de la topologie réseau et cohérence des lignes via Knowledge Graph et Neo4j.
- **RAG Hybride & LLM Spécialisé** : Moteur hybride combinant recherche sémantique vectorielle (ChromaDB), lexicale (BM25) et fine-tuning de modèles d'ingénierie (Qwen / Ollama).
- **Interface & API Complètes** : Backend FastAPI haute performance couplé à une interface Electron / Web pour les ingénieurs d'études.

---

## 🚀 Démarrage Rapide

### Prérequis

- Python 3.10+
- Node.js & npm (pour l'application Electron)
- (Optionnel) Ollama, Neo4j, ChromaDB

### Installation

1. Cloner le dépôt :
   ```bash
   git clone <repo_url>
   cd "DATA BASE IA"
   ```

2. Configurer l'environnement :
   ```bash
   cp .env.example .env
   # Éditer .env avec vos configurations locales et clés API
   ```

3. Installer les dépendances Python :
   ```bash
   pip install -r requirements.txt
   ```

4. Démarrer le serveur API :
   ```bash
   python -m uvicorn api_enhanced:app --reload --port 8000
   ```

---

## 🔒 Confidentialité & Données

Les données propriétaires de projets (`01-Reglementaire/`, `03-Projets-Ref/`, `data/`, bases de données locales et modèles fine-tunés) sont exclues du contrôle de version via `.gitignore`.
