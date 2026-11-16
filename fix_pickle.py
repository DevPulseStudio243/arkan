# ============================================================
#  DEERFLOW - Fix pickle ChromaDB 1.5.8
#
#  PROBLEME REEL :
#  chroma_db/<uuid>/index_metadata.pickle contient un dict
#  (cree avec une ancienne version de ChromaDB).
#  ChromaDB 1.5.8 attend un objet PersistentData avec .dimensionality
#  → AttributeError 'dict' object has no attribute 'dimensionality'
#
#  CE SCRIPT :
#  Trouve tous les fichiers index_metadata.pickle sous chroma_db/
#  et les convertit du format dict → PersistentData.
#
#  IMPORTANT : arreter uvicorn AVANT de lancer ce script !
#  Lancer avec : python fix_pickle.py
# ============================================================

import os
import sys
import glob
import pickle
import shutil
from typing import Optional, Dict
from datetime import datetime

CHROMA_DIR = "chroma_db"

# ── Reproduire la classe PersistentData de ChromaDB 1.5.8 ──
# On doit l'importer depuis chromadb pour que le pickle soit compatible.
try:
    from chromadb.segment.impl.vector.local_persistent_hnsw import PersistentData
    print("PersistentData importee depuis chromadb")
except ImportError:
    print("ERREUR : chromadb non installe. Lance : pip install chromadb==1.5.8")
    sys.exit(1)

print("=" * 60)
print("  FIX PICKLE CHROMADB 1.5.8")
print("=" * 60)
print(f"Dossier : {CHROMA_DIR}\n")

# Chercher tous les fichiers index_metadata.pickle
pattern = os.path.join(CHROMA_DIR, "**", "index_metadata.pickle")
pickle_files = glob.glob(pattern, recursive=True)

if not pickle_files:
    print("Aucun fichier index_metadata.pickle trouve.")
    print(f"Verifie que CHROMA_DIR='{CHROMA_DIR}' est correct.")
    sys.exit(0)

print(f"Fichiers pickle trouves : {len(pickle_files)}")
for f in pickle_files:
    print(f"  {f}")

fixed = 0
already_ok = 0
errors = 0

for pickle_path in pickle_files:
    print(f"\n--- {pickle_path} ---")

    # Charger le pickle
    try:
        with open(pickle_path, "rb") as f:
            data = pickle.load(f)
    except Exception as e:
        print(f"  ERREUR lecture : {e}")
        errors += 1
        continue

    print(f"  Type charge : {type(data).__name__}")

    # Verifier si c'est deja un PersistentData
    if isinstance(data, PersistentData):
        print(f"  Deja au bon format (dimensionality={data.dimensionality})")
        already_ok += 1
        continue

    # C'est un dict — convertir
    if isinstance(data, dict):
        print(f"  Format dict detecte. Cles : {list(data.keys())}")

        dim     = data.get("dimensionality")
        total   = data.get("total_elements_added", 0)
        i2l     = data.get("id_to_label", {})
        l2i     = data.get("label_to_id", {})
        i2seq   = data.get("id_to_seq_id", {})

        print(f"  dimensionality        = {dim}")
        print(f"  total_elements_added  = {total}")
        print(f"  id_to_label entries   = {len(i2l)}")

        # Creer l'objet PersistentData
        new_data = PersistentData(
            dimensionality=dim,
            total_elements_added=total,
            id_to_label=i2l,
            label_to_id=l2i,
            id_to_seq_id=i2seq,
        )

        # Backup du fichier original
        backup_path = pickle_path + f".bak_{datetime.now().strftime('%H%M%S')}"
        shutil.copy2(pickle_path, backup_path)
        print(f"  Backup cree : {backup_path}")

        # Sauvegarder au nouveau format
        try:
            with open(pickle_path, "wb") as f:
                pickle.dump(new_data, f, pickle.HIGHEST_PROTOCOL)
            print(f"  CONVERTI avec succes")
            fixed += 1
        except Exception as e:
            print(f"  ERREUR ecriture : {e}")
            # Restaurer le backup
            shutil.copy2(backup_path, pickle_path)
            print(f"  Backup restaure")
            errors += 1
    else:
        print(f"  Type inconnu : {type(data)} — non traite")
        errors += 1

# ── Resultat ──────────────────────────────────────────────
print(f"\n{'=' * 60}")
print(f"  RESULTAT")
print(f"  Convertis   : {fixed}")
print(f"  Deja OK     : {already_ok}")
print(f"  Erreurs     : {errors}")

if fixed > 0:
    print(f"\n  Redemarre uvicorn — l'erreur dimensionality doit etre corrigee.")
elif already_ok > 0 and fixed == 0:
    print(f"\n  Les pickles sont deja au bon format.")
    print(f"  Le probleme vient d'ailleurs — envoie ce resultat.")
print(f"{'=' * 60}")
