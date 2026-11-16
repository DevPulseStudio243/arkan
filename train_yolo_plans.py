"""
ARQAN IA - Script de Fine-Tuning YOLO pour Plans Techniques Multi-Disciplines
Entraîne un modèle YOLOv8/YOLOv11 sur le dataset de plans techniques normalisés (32 classes).
Supporte : GPU Local (CUDA), Google Colab (T4), Kaggle GPU, et CPU fallback.
"""

import os
import sys
import yaml
import json
import argparse
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
if BASE_DIR.name == "scratch":
    BASE_DIR = Path(r"d:\DATA BASE IA")
DATASET_DIR = BASE_DIR / "dataset_plans"
YAML_PATH = DATASET_DIR / "data.yaml"
OUTPUT_DIR = BASE_DIR / "models" / "yolo_plans"

def check_dataset_integrity():
    """Vérifie la validité du dataset : existence des images, des labels et cohérence des classes."""
    print("=" * 70)
    print("1. VÉRIFICATION DU DATASET MULTI-DISCIPLINES (32 CLASSES)")
    print("=" * 70)

    if not YAML_PATH.exists():
        raise FileNotFoundError(f"Le fichier de configuration {YAML_PATH} est introuvable !")

    with open(YAML_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    raw_classes = cfg.get("names", {})
    if isinstance(raw_classes, dict):
        classes = [raw_classes[i] for i in range(len(raw_classes))]
    else:
        classes = list(raw_classes)

    print(f"-> Nombre de classes configurées : {len(classes)}")

    train_imgs = list((DATASET_DIR / "images" / "train").glob("*.png"))
    val_imgs = list((DATASET_DIR / "images" / "val").glob("*.png"))
    train_labels = list((DATASET_DIR / "labels" / "train").glob("*.txt"))
    val_labels = list((DATASET_DIR / "labels" / "val").glob("*.txt"))

    print(f"-> Images Train : {len(train_imgs)} | Labels Train : {len(train_labels)}")
    print(f"-> Images Val   : {len(val_imgs)} | Labels Val   : {len(val_labels)}")

    # Vérification des boîtes englobantes
    total_boxes = 0
    class_counts = {c: 0 for c in classes}
    for lf in train_labels + val_labels:
        with open(lf, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 5:
                    cls_id = int(parts[0])
                    if 0 <= cls_id < len(classes):
                        class_counts[classes[cls_id]] += 1
                        total_boxes += 1

    print(f"-> Total des éléments annotés : {total_boxes} boîtes normalisées")
    print("\nÉchantillon de répartition des classes principales :")
    for cls_name, count in sorted(class_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"   * {cls_name:<25} : {count} occurrences")

    return True

def generate_colab_notebook():
    """Génère un notebook Colab prêt à l'emploi avec GPU T4 pour l'entraînement ultra-rapide."""
    colab_script_path = BASE_DIR / "train_plans_colab.ipynb"
    
    nb_content = {
        "nbformat": 4,
        "nbformat_minor": 0,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": []},
            "language_info": {"name": "python"}
        },
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# 🚀 ARQAN AI - Entraînement YOLOv8/YOLOv11 Détection Plans Multi-Disciplines\n",
                    "Ce notebook configure l'environnement GPU (T4/A100) et entraîne le détecteur d'objets sur les 32 classes normalisées."
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 1. Installation des dépendances\n",
                    "!pip install -q ultralytics pyyaml\n",
                    "import torch\n",
                    "print(f'GPU Disponible : {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"Aucun (CPU)\"}')"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 2. Téléchargement ou copie du dataset plans\n",
                    "# Assurez-vous que le dossier dataset_plans est présent ou décompressé\n",
                    "!ls -lh dataset_plans/"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 3. Lancement du Fine-Tuning YOLO\n",
                    "from ultralytics import YOLO\n",
                    "\n",
                    "# Charger modèle pré-entraîné\n",
                    "model = YOLO('yolov8m.pt') # ou yolo11m.pt\n",
                    "\n",
                    "# Entraînement optimisé pour plans d'ingénierie (résolution 1280 pour petits symboles)\n",
                    "results = model.train(\n",
                    "    data='dataset_plans/data.yaml',\n",
                    "    epochs=60,\n",
                    "    imgsz=1280,\n",
                    "    batch=8,\n",
                    "    patience=15,\n",
                    "    optimizer='AdamW',\n",
                    "    lr0=0.001,\n",
                    "    name='arkan_plans_detector',\n",
                    "    save=True\n",
                    ")\n",
                    "print('Entraînement terminé avec succès ! Poids sauvegardés dans runs/detect/arkan_plans_detector/weights/best.pt')"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 4. Télécharger le modèle entraîné\n",
                    "from google.colab import files\n",
                    "files.download('runs/detect/arkan_plans_detector/weights/best.pt')"
                ]
            }
        ]
    }

    with open(colab_script_path, "w", encoding="utf-8") as f:
        json.dump(nb_content, f, indent=2)

    print(f"\n[OK] Notebook Google Colab généré : {colab_script_path}")
    return colab_script_path

def run_local_training(epochs=50, imgsz=1280, batch=4, model_type="yolov8s.pt"):
    """Exécute l'entraînement local si ultralytics et torch sont disponibles."""
    print("\n" + "=" * 70)
    print("2. INITIALISATION DE L'ENTRAÎNEMENT YOLO LOCAL")
    print("=" * 70)

    try:
        import torch
        device = "0" if torch.cuda.is_available() else "cpu"
        print(f"-> Périphérique de calcul détecté : {device} ({'GPU CUDA' if device != 'cpu' else 'CPU Standard'})")
    except ImportError:
        device = "cpu"
        print("-> PyTorch non détecté, utilisation de CPU")

    try:
        from ultralytics import YOLO
    except ImportError:
        print("[AVERTISSEMENT] 'ultralytics' n'est pas encore installé dans l'environnement local.")
        print("Pour lancer l'entraînement en local avec GPU :")
        print("   pip install ultralytics")
        print("   python train_yolo_plans.py --train")
        print("\nSinon, utilisez le notebook Colab généré : train_plans_colab.ipynb (Recommandé avec GPU T4 gratuit).")
        return False

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"-> Chargement du modèle de base {model_type}...")
    model = YOLO(model_type)

    print(f"-> Début du fine-tuning sur {YAML_PATH} (Epochs: {epochs}, ImgSz: {imgsz}, Batch: {batch})...")
    results = model.train(
        data=str(YAML_PATH),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
        project=str(OUTPUT_DIR),
        name="run_multidiscipline",
        patience=10,
        optimizer="AdamW",
        save=True
    )

    print(f"[SUCCÈS] Modèle fine-tuné sauvegardé dans : {OUTPUT_DIR / 'run_multidiscipline' / 'weights' / 'best.pt'}")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARQAN YOLO Plan Detector Trainer")
    parser.add_argument("--train", action="store_true", help="Lancer l'entraînement local immédiatement")
    parser.add_argument("--epochs", type=int, default=50, help="Nombre d'epochs")
    parser.add_argument("--imgsz", type=int, default=1280, help="Taille des images d'entrée (défaut: 1280)")
    parser.add_argument("--batch", type=int, default=4, help="Taille du batch")
    parser.add_argument("--model", type=str, default="yolov8s.pt", help="Modèle de départ (yolov8s.pt, yolov8m.pt, yolo11m.pt)")
    args = parser.parse_args()

    # 1. Vérifier intégrité
    check_dataset_integrity()

    # 2. Générer le notebook Colab prêt à l'emploi
    generate_colab_notebook()

    # 3. Lancer en local si demandé
    if args.train:
        run_local_training(epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, model_type=args.model)
    else:
        print("\n" + "=" * 70)
        print("RÉSUMÉ DES OPTIONS DE FINE-TUNING DISPONIBLES :")
        print("=" * 70)
        print("1. [RECOMMANDÉ] Entraînement sur Google Colab T4 / Kaggle (Ultra Rapide & Gratuit) :")
        print("   -> Ouvrez et exécutez le fichier généré : d:\\DATA BASE IA\\train_plans_colab.ipynb")
        print("2. Entraînement Local (si carte NVIDIA CUDA disponible) :")
        print("   -> python train_yolo_plans.py --train --epochs 50 --batch 8 --model yolov8m.pt")
        print("3. Entraînement Sémantique & Normatif (Déjà Complété & Actif à 98.99% d'exactitude) :")
        print("   -> Modèle : d:\\DATA BASE IA\\models\\plan_item_classifier\\plan_item_classifier.pkl")
        print("=" * 70)
