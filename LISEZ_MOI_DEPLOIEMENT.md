# 🦌 DeerFlow Lite - Guide de Déploiement

Ce dossier contient l'ensemble du projet prêt à être déployé sur votre nouvelle machine (32 Go RAM, GPU 6 Go VRAM).

## 🚀 Étape 1 : Transférer les fichiers
Copiez l'intégralité du dossier `D:\DATA BASE IA` sur votre nouveau PC (sur une clé USB, un disque dur externe, ou via le réseau). **N'emportez que les fichiers de code et les scripts `.bat`**, vous n'êtes pas obligé de copier le dossier `venv/` s'il est trop lourd, car le script d'installation va le recréer au propre.

## ⚙️ Étape 2 : Prérequis sur le nouveau PC
Assurez-vous d'avoir installé sur votre nouvelle machine :
1. **Python 3.10 ou 3.11** : (Télécharger sur python.org). ⚠️ Lors de l'installation, n'oubliez pas de cocher la case **"Add Python to PATH"**.
2. **Ollama** : (Télécharger sur ollama.com/download/windows).

## 🛠️ Étape 3 : Installation automatisée
Double-cliquez sur le fichier **`Install_DeerFlow.bat`**. 
Ce script va automatiquement :
- Créer un environnement virtuel propre au nouveau PC.
- Installer toutes les bibliothèques Python nécessaires (FastAPI, ChromaDB, Scikit-learn, etc.).
- Télécharger le modèle IA `qwen2.5:14b` (qui fonctionnera parfaitement sur vos 6 Go de VRAM et 32 Go de RAM).
- Télécharger le modèle de vectorisation `nomic-embed-text`.

## ▶️ Étape 4 : Lancer l'application
Une fois l'installation terminée, double-cliquez simplement sur **`Start_DeerFlow.bat`**.
Ce script va :
- Lancer votre base de données et l'API Python en arrière-plan.
- Ouvrir automatiquement votre navigateur sur le Dashboard de DeerFlow Lite (`http://127.0.0.1:8000/ui`).

**Vous êtes prêt ! L'IA est prête à analyser vos documents Oil & Gas.**
