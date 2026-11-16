import sys, os, time
sys.path.insert(0, 'd:/DATA BASE IA')
os.environ['ANONYMIZED_TELEMETRY'] = 'False'
os.environ['CHROMA_TELEMETRY'] = 'false'

print('=== RE-INDEXATION COMPLETE avec bge-m3 (1024 dim) ===')
print()

from pathlib import Path
from config import DATA_PATH, EXTENSIONS

files = [f for f in Path(DATA_PATH).rglob('*') if f.suffix.lower() in EXTENSIONS]
print('Fichiers trouves dans data/ :', len(files))
print()

from auto_indexer import AutoIndexer

indexer = AutoIndexer()
indexer.start()

print('Demarrage du scan complet (force=True)...')
start = time.time()

count = indexer.scan_all(force=True)

elapsed = round((time.time()-start)/60, 1)
status = indexer.get_status()

print()
print('=== SCAN TERMINE ===')
print('Indexes:', status.get('indexed', 0))
print('Re-indexes:', status.get('re_indexed', 0))
print('Erreurs:', status.get('errors', 0))
print('Temps:', elapsed, 'min')
print('Dernier evt:', status.get('last_event', ''))
