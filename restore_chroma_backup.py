import json
import chromadb
import sys

CHROMA_DIR = "chroma_db"
COLLECTION = "oil_gas_docs"
BACKUP_FILE = "chroma_backup.json"
BATCH_SIZE = 200

print("=" * 60)
print("  RESTORE CHROMADB FROM BACKUP")
print("=" * 60)

try:
    with open(BACKUP_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
except Exception as e:
    print(f"Failed to load backup: {e}")
    sys.exit(1)

all_ids = data.get("ids", [])
all_docs = data.get("documents", [])
all_metas = data.get("metadatas", [])
all_embeds = data.get("embeddings", [])
dim = data.get("dim", 768)

print(f"Loaded {len(all_ids)} chunks from backup.")
print(f"Embedding dimension: {dim}")

client = chromadb.PersistentClient(path=CHROMA_DIR)

# Drop collection if it exists
try:
    client.delete_collection(name=COLLECTION)
    print("Deleted existing collection.")
except Exception:
    pass

class _OllamaEmbeddingFunction:
    def __init__(self, dim=768):
        self.dimensionality = dim
    def __call__(self, input):
        raise RuntimeError("Ne pas appeler directement")

ef = _OllamaEmbeddingFunction(dim=dim)

new_col = client.create_collection(
    name=COLLECTION,
    metadata={"hnsw:space": "cosine"},
    embedding_function=ef,
)
print("Created collection.")

print("Restoring chunks in batches...")
success = 0
errors = 0
skipped = 0

for start in range(0, len(all_ids), BATCH_SIZE):
    end = min(start + BATCH_SIZE, len(all_ids))
    b_ids = all_ids[start:end]
    b_docs = all_docs[start:end]
    b_metas = all_metas[start:end]
    b_embs = all_embeds[start:end]
    
    clean_ids = []
    clean_docs = []
    clean_metas = []
    clean_embs = []
    
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
        new_col.upsert(
            ids=clean_ids,
            embeddings=clean_embs,
            documents=clean_docs,
            metadatas=clean_metas
        )
        success += len(clean_ids)
    except Exception as e:
        errors += len(clean_ids)
        print(f"\nError in batch {start}-{end}: {e}")
        
    print(f"Progress: {end}/{len(all_ids)} - Restored: {success}, Errors: {errors}, Skipped: {skipped}", end="\r")

print(f"\nRestore finished. Count in DB: {new_col.count()}")
