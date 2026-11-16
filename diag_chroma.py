# ============================================================
#  DEERFLOW - Diagnostic ChromaDB 1.5.x
#  Lancer avec : python diag_chroma.py
# ============================================================
import chromadb
import json, sys

CHROMA_DIR = "chroma_db"
COLLECTION  = "oil_gas_docs"

print("=" * 60)
print("  DIAGNOSTIC CHROMADB")
print("=" * 60)
print(f"ChromaDB version : {chromadb.__version__}")

client = chromadb.PersistentClient(path=CHROMA_DIR)

# Liste toutes les collections
cols = client.list_collections()
print(f"\nCollections présentes : {[c.name for c in cols]}")

# Ouvre la collection SANS embedding_function
try:
    col = client.get_collection(name=COLLECTION)
    print(f"\nCollection '{COLLECTION}' ouverte")
    print(f"  Nombre de chunks : {col.count()}")

    # Récupère l'embedding_function stockée
    ef = col._embedding_function
    print(f"\n  embedding_function stockée : {type(ef)}")
    print(f"  Valeur                     : {ef}")

    # Vérifie si elle a dimensionality
    if hasattr(ef, 'dimensionality'):
        print(f"  .dimensionality            : {ef.dimensionality}")
    else:
        print(f"  .dimensionality            : ABSENT (cause de l'erreur !)")

    # Récupère 1 embedding pour voir la dimension réelle
    sample = col.get(limit=1, include=["embeddings"])
    if sample and sample.get("embeddings"):
        emb = sample["embeddings"][0]
        print(f"\n  Dimension des embeddings stockés : {len(emb)}")
    else:
        print("\n  Impossible de lire les embeddings stockés")

except Exception as e:
    print(f"\nErreur ouverture collection : {e}")

# Test upsert minimal
print("\n--- Test upsert direct ---")
try:
    col2 = client.get_or_create_collection(name="__test_dim__")
    col2.upsert(
        ids=["test1"],
        embeddings=[[0.1] * 768],
        documents=["test document"],
        metadatas=[{"src": "test"}],
    )
    print("upsert 768-dim : OK")
    client.delete_collection("__test_dim__")
except Exception as e:
    print(f"upsert 768-dim echoue : {e}")

print("\n" + "=" * 60)
print("Copie ce résultat et envoie-le.")
print("=" * 60)
