# ============================================================
#  DEERFLOW - Migration ChromaDB 1.5.8
#  IMPORTANT : arrêter uvicorn AVANT de lancer ce script !
#  Lancer avec : python migrate_chroma.py
# ============================================================
import chromadb
import json, sys

CHROMA_DIR  = "chroma_db"
COLLECTION  = "oil_gas_docs"
BACKUP_FILE = "chroma_backup.json"
BATCH_SIZE  = 200

print("=" * 60)
print("  MIGRATION CHROMADB 1.5.8 - DEERFLOW")
print("=" * 60)
print(f"ChromaDB : {chromadb.__version__}")

client = chromadb.PersistentClient(path=CHROMA_DIR)

class _OllamaEmbeddingFunction:
    def __init__(self, dim=768):
        self.dimensionality = dim
    def __call__(self, input):
        raise RuntimeError("Ne pas appeler directement")

print("\nETAPE 1 - Lecture de la collection existante...")
try:
    old_col = client.get_collection(name=COLLECTION)
    total = old_col.count()
    print(f"  {total} chunks trouves")
except Exception as e:
    print(f"  Erreur : {e}")
    sys.exit(1)

print("  Recuperation (peut prendre 1-2 minutes)...")
try:
    result = old_col.get(include=["documents", "metadatas", "embeddings"])
    all_ids    = result.get("ids", [])
    all_docs   = result.get("documents", [])
    all_metas  = result.get("metadatas", [])
    all_embeds = []
    for emb in result.get("embeddings", []):
        if emb is None:
            all_embeds.append(None)
        elif hasattr(emb, 'tolist'):
            all_embeds.append(emb.tolist())
        else:
            all_embeds.append([float(x) for x in emb])
    print(f"  OK : {len(all_ids)} chunks recuperes")
except Exception as e:
    print(f"  Erreur : {e}")
    sys.exit(1)

valid_embs = [e for e in all_embeds if e and len(e) > 0]
dim = len(valid_embs[0]) if valid_embs else 768
print(f"  Dimension : {dim}")
ef = _OllamaEmbeddingFunction(dim=dim)

print(f"\n  Sauvegarde dans {BACKUP_FILE}...")
with open(BACKUP_FILE, "w", encoding="utf-8") as f:
    json.dump({"ids": all_ids, "documents": all_docs,
               "metadatas": all_metas, "embeddings": all_embeds,
               "dim": dim}, f, ensure_ascii=False)
print(f"  OK - Backup cree")

print("\nETAPE 2 - Suppression ancienne collection...")
client.delete_collection(name=COLLECTION)
print("  OK")

print("\nETAPE 3 - Recreation avec dimensionality correct...")
new_col = client.create_collection(
    name=COLLECTION,
    metadata={"hnsw:space": "cosine"},
    embedding_function=ef,
)
print("  OK")

# Test
new_col.upsert(ids=["migtest1"], embeddings=[[0.0]*dim],
               documents=["test"], metadatas=[{"src":"test"}])
new_col.delete(ids=["migtest1"])
print(f"  Test upsert {dim}-dim : OK")

print(f"\nETAPE 4 - Reindexation de {len(all_ids)} chunks...")
success = errors = skipped = 0

for start in range(0, len(all_ids), BATCH_SIZE):
    end = min(start + BATCH_SIZE, len(all_ids))
    b_ids, b_docs, b_metas, b_embs = (
        all_ids[start:end], all_docs[start:end],
        all_metas[start:end], all_embeds[start:end]
    )
    clean_ids, clean_docs, clean_metas, clean_embs = [], [], [], []
    for i, emb in enumerate(b_embs):
        if emb and len(emb) == dim:
            clean_embs.append([float(x) for x in emb])
            clean_ids.append(b_ids[i])
            clean_docs.append(b_docs[i])
            clean_metas.append(b_metas[i] if b_metas[i] else {})
        else:
            skipped += 1
    if not clean_ids:
        continue
    try:
        new_col.upsert(ids=clean_ids, embeddings=clean_embs,
                       documents=clean_docs, metadatas=clean_metas)
        success += len(clean_ids)
    except Exception as e:
        errors += len(clean_ids)
        print(f"\n  Erreur batch {start}-{end} : {e}")
    print(f"  {end}/{len(all_ids)} - OK:{success} ERR:{errors}", end="\r")

final = new_col.count()
print(f"\n\n{'='*60}")
print(f"  MIGRATION TERMINEE")
print(f"  Avant: {total}  Apres: {final}  Ignores: {skipped}")
if errors == 0:
    print(f"  Succes total - tu peux supprimer {BACKUP_FILE}")
print(f"\n  1. Remplace indexer.py par la version corrigee")
print(f"  2. Redemarre uvicorn")
print(f"{'='*60}")
