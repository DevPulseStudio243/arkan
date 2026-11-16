"""
DeerFlow - Script de reparation du demarrage
Fixe :
  1. Le schema SQLite ChromaDB (colonne 'topic' manquante)
  2. Le cache d'embeddings corrompu
  3. Les fichiers partiels orphelins
"""
import sqlite3
import json
import os
import shutil
from pathlib import Path

BASE = Path(__file__).parent
CHROMA_DB = BASE / "chroma_db"
SQLITE_FILE = CHROMA_DB / "chroma.sqlite3"

print("=" * 60)
print("  DeerFlow - Reparation demarrage")
print("=" * 60)

# ─────────────────────────────────────────────
# 1. Diagnostic du schema SQLite
# ─────────────────────────────────────────────
print("\n[1] Analyse du schema ChromaDB SQLite...")
if not SQLITE_FILE.exists():
    print(f"  ERREUR: {SQLITE_FILE} introuvable !")
else:
    con = sqlite3.connect(str(SQLITE_FILE))
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f"  Tables presentes: {tables}")

    col_info = {}
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        col_info[t] = [r[1] for r in cur.fetchall()]
        print(f"  {t}: {col_info[t]}")

    # ─── Fix: ajouter la colonne 'topic' si absente ───
    if "collections" in col_info:
        if "topic" not in col_info["collections"]:
            print("\n  [FIX] Colonne 'topic' manquante dans 'collections' → ajout...")
            try:
                cur.execute("ALTER TABLE collections ADD COLUMN topic TEXT")
                con.commit()
                print("  [OK] Colonne 'topic' ajoutee.")
            except Exception as e:
                print(f"  [WARN] ALTER TABLE echoue: {e}")
        else:
            print("  [OK] Colonne 'topic' deja presente.")

    # ─── Fix: ajouter colonne 'dimension' si absente ───
    if "segments" in col_info:
        if "dimension" not in col_info["segments"]:
            print("\n  [FIX] Colonne 'dimension' manquante dans 'segments' -> ajout...")
            try:
                cur.execute("ALTER TABLE segments ADD COLUMN dimension INTEGER")
                con.commit()
                print("  [OK] Colonne 'dimension' ajoutee.")
            except Exception as e:
                print(f"  [WARN] ALTER TABLE echoue: {e}")

    con.close()

# ─────────────────────────────────────────────
# 2. Verifier le nombre de documents
# ─────────────────────────────────────────────
print("\n[2] Verification ChromaDB via Python 3.11...")
try:
    import chromadb
    print(f"  ChromaDB version: {chromadb.__version__}")
    client = chromadb.PersistentClient(path=str(CHROMA_DB))
    col = client.get_or_create_collection("oil_gas_docs")
    total = col.count()
    print(f"  [OK] Collection 'oil_gas_docs': {total} documents")
except Exception as e:
    print(f"  [ERREUR] ChromaDB toujours inaccessible: {e}")
    print("  -> La collection devra etre reindexee.")
    total = 0

# ─────────────────────────────────────────────
# 3. Nettoyer le cache d'embeddings corrompu
# ─────────────────────────────────────────────
print("\n[3] Nettoyage du cache d'embeddings...")

cache_files = {
    "embedding_cache.npy": BASE / "embedding_cache.npy",
    "embedding_cache_ids.json": BASE / "embedding_cache_ids.json",
    "embedding_cache_partial.npy": BASE / "embedding_cache_partial.npy",
    "embedding_cache_partial_meta.json": BASE / "embedding_cache_partial_meta.json",
}

for name, path in cache_files.items():
    if path.exists():
        size = path.stat().st_size
        if name.endswith(".npy") and size < 1000:
            print(f"  [SUPPRIME] {name} ({size} bytes — corrompu)")
            path.unlink()
        elif name.endswith("_ids.json"):
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
                count = meta.get("count", 0) if isinstance(meta, dict) else len(meta)
                if count == 0:
                    print(f"  [SUPPRIME] {name} (count=0 — corrompu)")
                    path.unlink()
                else:
                    print(f"  [OK] {name} (count={count})")
            except Exception:
                print(f"  [SUPPRIME] {name} (JSON invalide)")
                path.unlink()
        elif "partial" in name:
            print(f"  [SUPPRIME] {name} (fichier partiel orphelin)")
            path.unlink()
        else:
            print(f"  [OK] {name} ({size} bytes)")
    else:
        print(f"  [ABSENT] {name}")

# ─────────────────────────────────────────────
# 4. Nettoyer le log geant (>10MB)
# ─────────────────────────────────────────────
print("\n[4] Gestion du log DeerFlow...")
log_file = BASE / "deerflow.log"
if log_file.exists():
    size_mb = log_file.stat().st_size / (1024 * 1024)
    print(f"  Taille actuelle: {size_mb:.1f} MB")
    if size_mb > 5:
        # Garder les 500 dernieres lignes
        lines = log_file.read_bytes().split(b"\n")
        kept = b"\n".join(lines[-500:])
        backup = BASE / "deerflow.log.bak"
        shutil.copy(str(log_file), str(backup))
        log_file.write_bytes(kept)
        print(f"  [OK] Log tronque (500 dernieres lignes). Backup: deerflow.log.bak")
    else:
        print(f"  [OK] Taille acceptable.")

print("\n" + "=" * 60)
print("  Reparation terminee.")
if total > 0:
    print(f"  ChromaDB: {total} documents disponibles.")
    print("  Vous pouvez lancer Start_DeerFlow.bat")
else:
    print("  ATTENTION: ChromaDB vide ou inaccessible.")
    print("  Lancez le serveur puis POST /admin/scan pour reindexer.")
print("=" * 60)
