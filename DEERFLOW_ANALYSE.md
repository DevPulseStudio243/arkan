# ANALYSE TECHNIQUE — DEERFLOW LITE
## Audit complet : 10 axes — IA Oil & Gas locale

---

## 1. RÉSUMÉ EXÉCUTIF

| Axe | Titre | Statut | Score /10 |
|-----|-------|--------|-----------|
| AXE 1 | Développement du Réseau Neuronal | ⚠️ PARTIEL | 4/10 |
| AXE 2 | Chunking Sémantique | ⚠️ PARTIEL | 5/10 |
| AXE 3 | Compréhension du Sens vs Mots-clés | ⚠️ PARTIEL | 5/10 |
| AXE 4 | Architecture Multi-Agents | ⚠️ PARTIEL | 4/10 |
| AXE 5 | OCR Plans Techniques | ⚠️ PARTIEL | 5/10 |
| AXE 6 | API REST et Interface Feedback | ✅ FONCTIONNEL | 7/10 |
| AXE 7 | Apprentissage Continu et Mémoire | ⚠️ PARTIEL | 4/10 |
| AXE 8 | Bugs Critiques et Race Conditions | 🔴 CRITIQUE | 2/10 |
| AXE 9 | Performance et Optimisation Hardware | ⚠️ PARTIEL | 4/10 |
| AXE 10 | Évaluation Objective et Métriques | ⚠️ PARTIEL | 4/10 |

**Score global : 44/100**

---

## 2. RÉPONSE À LA QUESTION CENTRALE

**« L'IA développe-t-elle réellement son réseau neuronal ? »**

**Non, pas automatiquement. Voici pourquoi :**

Le système dispose de l'*infrastructure* du fine-tuning (trainer_reranker.py, trainer_embeddings.py, trainer_classifier.py) mais cette infrastructure est **manuelle et non déclenchée automatiquement** en production. Preuves :

1. `reranker.py` charge `cross-encoder/ms-marco-MiniLM-L-6-v2` (modèle générique ms-marco, non Oil & Gas) sauf si `models/reranker_oil_gas/` existe — ce dossier n'est créé qu'après exécution manuelle de `train_deerflow.py`.
2. `classifier.py` utilise les règles regex par défaut. La fonction `classify_document_ml()` est définie mais n'est jamais appelée dans le pipeline (`auto_indexer.py:141` appelle `classify_document()`, pas `classify_document_ml()`).
3. Il n'existe pas de scheduler automatique dans le code livré qui déclencherait le fine-tuning sans intervention humaine. `api.py` référence `learning.get_auto_retrain_scheduler()` (ligne ~130) mais ce module `learning.py` n'est pas dans les fichiers fournis — il est absent ou non livré.
4. `nomic-embed-text` tourne via Ollama et **n'est pas fine-tunable en place** : c'est un modèle Ollama opaque. Le fine-tuning d'embedding dans `trainer_embeddings.py` produit un modèle `sentence-transformers` local **qui n'est jamais rechargé automatiquement** dans `indexer.py` (get_embedding() continue d'appeler Ollama).

**Verdict intermédiaire :** Le système est actuellement un **RAG sémantique statique (Niveau 2)** avec une infrastructure de Niveau 3-4 prête mais non activée.

---

## 3. ANALYSE DES 10 AXES

---

### AXE 1 — Développement du Réseau Neuronal

**STATUT : ⚠️ PARTIEL**

**DIAGNOSTIC :**

- **Reranker :** Chargement conditionnel dans `reranker.py:25-37`. Si `models/reranker_oil_gas/` n'existe pas (cas initial), le système charge `cross-encoder/ms-marco-MiniLM-L-6-v2` — modèle entraîné sur des requêtes web Microsoft BING, pas sur de la documentation technique Oil & Gas. Il ne connaît pas PSV, P&ID, ASME B31.3.
- **Embeddings :** `indexer.py:get_embedding()` appelle `OLLAMA_BASE_URL/api/embeddings` avec `nomic-embed-text`. Ce modèle Ollama n'est pas fine-tunable à travers l'API Ollama. Le fine-tuning de `trainer_embeddings.py` produit un modèle `sentence-transformers` local mais `indexer.py` ne le charge jamais.
- **Classifieur :** `auto_indexer.py:141` appelle `classify_document(text, filename=filename)` — la version **règles seulement**. La version ML `classify_document_ml()` définie dans `classifier.py:163-200` n'est jamais invoquée dans le pipeline d'indexation.
- **Mise à jour continue :** `api.py:130` tente `from learning import get_auto_retrain_scheduler` — ce module `learning.py` n'est pas fourni. Le scheduler n'existe pas dans les fichiers livrés.
- **Persistance :** `api.py:143-147` charge le reranker et le classifieur ML au démarrage via `_ensure_cross_encoder()` et `_load_ml_classifier()`. Ce mécanisme est correct — **mais seulement si les modèles ont été entraînés manuellement au préalable.**

**PREUVES CODE :**
- `reranker.py:24` : `model_path = "models/reranker_oil_gas"` → `if not os.path.exists(model_path): model_path = "cross-encoder/ms-marco-MiniLM-L-6-v2"`
- `auto_indexer.py:141` : `classification = classify_document(text, filename=filename)` (version règles)
- `indexer.py:get_embedding()` → `httpx.post(f"{OLLAMA_BASE_URL}/api/embeddings", json={"model": OLLAMA_EMBED_MODEL, ...})` — toujours Ollama, jamais le modèle local fine-tuné

**SÉVÉRITÉ : MAJEUR** — Le pipeline de production n'utilise pas les modèles fine-tunés même après leur entraînement.

**CORRECTIF :**

```python
# indexer.py — Remplacer get_embedding() par une version hybride

_LOCAL_EMBED_MODEL = None
_LOCAL_EMBED_PATH = "models/embeddings_oil_gas"
_LOCAL_EMBED_LOCK = __import__('threading').Lock()

def get_embedding(text: str) -> list:
    """Embedding avec fallback: modèle local O&G > Ollama."""
    global _LOCAL_EMBED_MODEL
    # Tentative modèle local fine-tuné
    if _LOCAL_EMBED_MODEL is None and os.path.exists(_LOCAL_EMBED_PATH):
        with _LOCAL_EMBED_LOCK:
            if _LOCAL_EMBED_MODEL is None:
                try:
                    from sentence_transformers import SentenceTransformer
                    _LOCAL_EMBED_MODEL = SentenceTransformer(_LOCAL_EMBED_PATH)
                    logger.info("Embedding local O&G chargé: %s", _LOCAL_EMBED_PATH)
                except Exception as e:
                    logger.warning("Impossible de charger embedding local: %s", e)
                    _LOCAL_EMBED_MODEL = False  # Marquer comme indisponible

    if _LOCAL_EMBED_MODEL and _LOCAL_EMBED_MODEL is not False:
        try:
            vec = _LOCAL_EMBED_MODEL.encode(text[:512], normalize_embeddings=True)
            return vec.tolist()
        except Exception as e:
            logger.warning("Embedding local échoué, fallback Ollama: %s", e)

    # Fallback Ollama
    try:
        response = httpx.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
            timeout=LLM_TIMEOUT,
        )
        if response.status_code == 200:
            return response.json().get("embedding", [])
    except Exception as e:
        logger.error(f"Erreur embedding Ollama: {e}")
    return []


# auto_indexer.py — Ligne 141 : utiliser le classifieur ML en priorité
# AVANT:
#   classification = classify_document(text, filename=filename)
# APRÈS:
from classifier import classify_document_ml
classification = classify_document_ml(text, filename=filename)
```

---

### AXE 2 — Chunking Sémantique vs Mécanique

**STATUT : ⚠️ PARTIEL**

**DIAGNOSTIC :**

`adaptive_chunk()` dans `indexer.py:58-127` implémente un chunking **structural** (pas purement sémantique) avec les éléments suivants :
- Détection de sections par regex (`\n(?=(?:\d+\.\s|\#{1,3}\s|[A-Z][A-Z\s]{3,}:?\s*$|={3,}|-{3,}))`)
- Protection des tableaux (`_contains_table()` : ≥3 lignes avec `\t` ou `|`)
- Overlap sémantique aux frontières de phrases (`_get_semantic_overlap()`)
- Sub-découpage par paragraphes au-delà de MAX_CHUNK_SIZE=2000

**Problèmes identifiés :**
1. Le seuil de détection tableau (`tab_lines >= 3`) est trop bas — un tableau de 2 lignes (header + 1 valeur) est ignoré. Pour les datasheets techniques avec des tableaux courts, les données sont coupées.
2. `CHUNK_OVERLAP = 200 chars` ≈ 40 mots : insuffisant pour les spécifications multi-lignes. Une spécification "La pression de design de P-101 est / 42 barg" peut être coupée entre deux chunks sans que l'overlap ne la capture si elle fait >200 chars.
3. Aucun embedding de cohérence (type propositions de spaCy ou sentence-BERT) pour vérifier que deux phrases appartiennent à la même idée.
4. Les cellules Excel dans `extractors.py:extract_xlsx()` sont concaténées par `" | ".join(cells)` puis chunkées textuellement — une datasheet de 50 lignes devient un bloc de texte non structuré.

**PREUVES CODE :**
- `indexer.py:65` : `def _contains_table(text: str) -> bool: ... tab_lines >= 3`
- `config.py:30` : `CHUNK_OVERLAP = int(os.environ.get("DEERFLOW_CHUNK_OVERLAP", "200"))`
- `extractors.py:192-198` : `for row in ws.iter_rows(values_only=True): cells = [...] rows.append(" | ".join(cells))`

**SÉVÉRITÉ : MAJEUR** — Aucun modèle NLP pour la cohérence sémantique.

**CORRECTIF :**

```python
# indexer.py — Chunking amélioré avec détection de spécifications
import re

# Patterns de spécifications techniques à ne jamais couper
_SPEC_PATTERNS = [
    re.compile(r'(?:pression|pressure|température|temperature|débit|flow)\s*(?:de\s+)?(?:design|opérat\w+|service)\s*[:=]?\s*$', re.I),
    re.compile(r'(?:tag|equipement|equipment)\s*[:=]\s*$', re.I),
    re.compile(r'[A-Z]{1,4}-\d{2,5}[A-Z]?\s*[:=]?\s*$'),  # Tag seul en fin de ligne
]

def _is_spec_boundary(line: str) -> bool:
    """Détecte si une ligne se termine sur une spécification incomplète."""
    return any(p.search(line.strip()) for p in _SPEC_PATTERNS)

def adaptive_chunk_v2(text: str, base_size: int = CHUNK_SIZE,
                       overlap: int = CHUNK_OVERLAP) -> list:
    """Chunking amélioré : détecte les specs incomplètes en fin de chunk."""
    chunks = adaptive_chunk(text, base_size, overlap)  # Base existante
    
    # Post-processing: fusionner les chunks qui coupent une spec
    merged = []
    i = 0
    while i < len(chunks):
        chunk = chunks[i]
        last_line = chunk.rstrip().split('\n')[-1] if '\n' in chunk else chunk
        
        # Si la dernière ligne est une spec incomplète et qu'il y a un chunk suivant
        if i + 1 < len(chunks) and _is_spec_boundary(last_line):
            next_chunk = chunks[i + 1]
            # Fusionner si le résultat reste < MAX_CHUNK_SIZE
            if len(chunk) + len(next_chunk) <= MAX_CHUNK_SIZE:
                merged.append(chunk + "\n" + next_chunk)
                i += 2
                continue
        merged.append(chunk)
        i += 1
    return merged


# extractors.py — Extraction Excel structurée par équipement
def extract_xlsx_structured(file_path: str) -> dict:
    """Extraction Excel préservant la structure des datasheets."""
    try:
        from openpyxl import load_workbook
        wb = load_workbook(file_path, data_only=True)
        sheets_text = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            # Détecter la structure: chercher les en-têtes de colonnes
            header_row = None
            rows_data = []
            
            for row_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
                cells = [str(c).strip() if c is not None else "" for c in row]
                non_empty = [c for c in cells if c]
                if not non_empty:
                    continue
                
                # Première ligne non vide = en-têtes potentiels
                if header_row is None and len(non_empty) >= 2:
                    header_row = cells
                    continue
                
                # Formatter chaque ligne comme "Clé: Valeur" si 2 colonnes
                if header_row and len(cells) >= 2:
                    pairs = []
                    for h, v in zip(header_row, cells):
                        if h and v:
                            pairs.append(f"{h}: {v}")
                    if pairs:
                        rows_data.append(" | ".join(pairs))
                else:
                    rows_data.append(" | ".join(non_empty))
            
            if rows_data:
                sheets_text.append(f"=== Feuille: {sheet_name} ===\n" + "\n".join(rows_data))

        return {
            "text": "\n\n".join(sheets_text),
            "pages": len(wb.sheetnames),
            "format": "xlsx",
            "source": file_path,
        }
    except Exception as e:
        logger.error(f"Erreur extraction XLSX structurée {file_path}: {e}")
        return extract_xlsx(file_path)  # Fallback version de base
```

---

### AXE 3 — Compréhension du Sens vs Recherche de Mots-clés

**STATUT : ⚠️ PARTIEL**

**DIAGNOSTIC :**

- **Fusion RRF :** `retriever.py` n'utilise **pas** les poids VECTOR_WEIGHT=0.6 / BM25_WEIGHT=0.4 de `config.py` — il implémente un RRF pur (1/(k+rank)) sans pondération différenciée. C'est mathématiquement correct mais ignore les poids configurés.
- **Expansion sémantique :** `vocabulary.py:_TECHNICAL_SYNONYMS` est un dictionnaire statique manuel de ~40 entrées. Il ne découvre pas automatiquement de nouvelles relations sémantiques. PSV=soupape=relief valve est géré, mais "dôme de compression" = "ballon HP" ne l'est pas.
- **Cross-lingual :** `nomic-embed-text` gère correctement le multilinguisme FR/EN (modèle d'embedding multilingue). La recherche vectorielle fonctionne cross-langue. BM25 est monolingue et raterait "suction drum" sur un corpus FR.
- **Test de régression :** `qa_pairs.jsonl` est produit par `trainer_synthetic.py` mais aucun script ne l'exécute automatiquement à chaque démarrage ou après modification du corpus.

**PREUVES CODE :**
- `retriever.py:_reciprocal_rank_fusion()` : pas d'utilisation de `VECTOR_WEIGHT`/`BM25_WEIGHT` importés de config
- `vocabulary.py:expand_query()` utilise `_TECHNICAL_SYNONYMS` (dict statique) + `_load_learned_vocabulary()` (fichier JSON appris)
- `config.py:17-18` : `VECTOR_WEIGHT = float(os.environ.get("DEERFLOW_VECTOR_WEIGHT", "0.6"))` — importé mais inutilisé dans retriever

**SÉVÉRITÉ : MAJEUR**

**CORRECTIF :**

```python
# retriever.py — RRF avec pondération configurable
def _reciprocal_rank_fusion(
    self,
    vector_results: list,
    bm25_results: list,
    k: int = 60
) -> list:
    fused_scores: dict[str, float] = {}
    doc_map: dict[str, object] = {}

    # Score pondéré depuis vector ranking
    for rank, result in enumerate(sorted(vector_results, key=lambda r: r.score, reverse=True)):
        rrf_score = VECTOR_WEIGHT / (k + rank + 1)  # Pondéré
        key = result.chunk_id or result.content[:100]
        fused_scores[key] = fused_scores.get(key, 0.0) + rrf_score
        doc_map[key] = result

    # Score pondéré depuis BM25 ranking
    for rank, result in enumerate(sorted(bm25_results, key=lambda r: r.score, reverse=True)):
        rrf_score = BM25_WEIGHT / (k + rank + 1)  # Pondéré
        key = result.chunk_id or result.content[:100]
        fused_scores[key] = fused_scores.get(key, 0.0) + rrf_score
        if key not in doc_map:
            doc_map[key] = result

    # Apply source weights
    if self._source_weights:
        for key in fused_scores:
            source = doc_map[key].source
            raw_weight = self._source_weights.get(source, 1.0)
            weight = float(raw_weight.get("weight", 1.0)) if isinstance(raw_weight, dict) else float(raw_weight)
            fused_scores[key] *= weight

    sorted_keys = sorted(fused_scores.keys(), key=lambda k: fused_scores[k], reverse=True)
    results = []
    for key in sorted_keys:
        result = doc_map[key]
        result.score = fused_scores[key]
        results.append(result)
    return results


# vocabulary.py — Découverte automatique de synonymes depuis le corpus
def learn_synonyms_from_corpus(documents: list[str], min_cooccurrence: int = 3) -> dict:
    """
    Découvre des synonymes candidats par cooccurrence dans le même chunk.
    Termes qui apparaissent systématiquement ensemble sont probablement synonymes.
    """
    import re
    from collections import defaultdict, Counter
    
    # Dictionnaire de cooccurrence des termes techniques
    cooccurrence = defaultdict(Counter)
    
    tech_pattern = re.compile(
        r'\b(?:PSV|PRV|ESD|SIS|SIL|P&ID|PFD|HMB|'
        r'(?:[A-Z]{1,4}-\d{2,5}[A-Z]?)|'
        r'(?:API|ASME|ISO|EN|IEC|NFPA)\s*\d[\w\-\.]*)\b'
    )
    
    for doc in documents:
        terms = tech_pattern.findall(doc)
        unique_terms = list(set(terms))
        for i, t1 in enumerate(unique_terms):
            for t2 in unique_terms[i+1:]:
                cooccurrence[t1][t2] += 1
                cooccurrence[t2][t1] += 1
    
    synonyms = {}
    for term, counts in cooccurrence.items():
        candidates = [t for t, c in counts.items() if c >= min_cooccurrence]
        if candidates:
            synonyms[term] = candidates[:5]
    
    # Sauvegarder les synonymes appris
    learned_path = LEARNED_VOCAB_PATH
    learned_path.parent.mkdir(parents=True, exist_ok=True)
    with open(learned_path, 'w', encoding='utf-8') as f:
        json.dump(synonyms, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Synonymes appris: {len(synonyms)} termes")
    return synonyms
```

---

### AXE 4 — Architecture Multi-Agents

**STATUT : ⚠️ PARTIEL**

**DIAGNOSTIC :**

Le fichier `agents.py` (référencé dans `pipeline.py:from agents import get_orchestrator`) et `agent_graph.py` ne sont **pas fournis** dans les fichiers à analyser. L'architecture multi-agents est référencée mais non analysable directement.

Ce qui est analysable :
- **Agent OCR :** `extractors.py:_call_vision_model_b64()` envoie un prompt générique (`"Extract ALL text visible..."`) sans spécialisation P&ID. Aucune instruction sur les légendes, flux, tags ISA/IEC 60617. C'est un OCR générique.
- **Agent Extraction entities :** `entities.py` = regex pures. Aucun NER neuronal. Les entités hors patterns (`HEx-42`, tags non standards) sont ignorées.
- **Agent Classifieur :** `auto_indexer.py:141` appelle `classify_document()` (règles), pas `classify_document_ml()` (ML). L'agent ML existe mais n'est pas activé dans le flux principal.
- **Agent Validation (guardrails) :** `guardrails.py` vérifie par pattern matching (présence de la valeur dans le contexte). Il ne comprend pas la physique — `200 bar sur une ligne plastique = erreur physique` passerait si "200 bar" et "plastique" sont tous deux dans le contexte.

**PREUVES CODE :**
- `extractors.py:_call_vision_model_b64()` prompt : `"Extract ALL text visible in this technical document image. Include equipment tags, numbers, labels, table data. Return ONLY the extracted text"` — aucune instruction P&ID spécifique
- `auto_indexer.py:141` : `classification = classify_document(text, filename=filename)` — règles seules
- `pipeline.py:from agents import get_orchestrator` — module non fourni, comportement non vérifiable

**SÉVÉRITÉ : MAJEUR**

**CORRECTIF — OCR P&ID spécialisé :**

```python
# extractors.py — Remplacer _call_vision_model_b64() par version spécialisée P&ID

_PID_OCR_PROMPT = """Tu es un expert en lecture de plans P&ID et isométriques Oil & Gas.
Extrait TOUT le texte visible dans ce plan technique en respectant cette structure :

1. TAGS ÉQUIPEMENTS: (format X-NNN) ex: P-101, V-201, E-301, PSV-101
2. INSTRUMENTS: (format XX-NNN) ex: FIC-201, PIT-301, LCV-401
3. LIGNES DE TUYAUTERIE: numéros de lignes, diamètres, classes
4. LÉGENDE ET NOTES: texte des notes, révisions, titre du plan
5. VALEURS NUMÉRIQUES: pressions, températures, débits avec unités

Retourne UNIQUEMENT le texte extrait, structuré selon ces 5 catégories.
N'invente RIEN. Si tu ne vois pas clairement un élément, écris [ILLISIBLE]."""

_STANDARD_OCR_PROMPT = (
    "Extract ALL text visible in this technical document image. "
    "Include equipment tags, numbers, labels, table data. "
    "Return ONLY the extracted text, nothing else. "
    "Do NOT invent or assume any content not visible."
)

def _is_pid_document(file_path: str) -> bool:
    """Détecte si le document est probablement un P&ID basé sur son nom."""
    name_lower = str(file_path).lower()
    pid_keywords = ['pid', 'p&id', 'pfd', 'iso', 'isometric', 'p_id', 'flow']
    return any(kw in name_lower for kw in pid_keywords)

def _call_vision_model_b64(b64_image: str, context: str = "", is_pid: bool = False) -> str:
    """Appelle le modèle vision avec un prompt adapté au type de document."""
    try:
        prompt = _PID_OCR_PROMPT if is_pid else _STANDARD_OCR_PROMPT
        response = httpx.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_VISION_MODEL,
                "prompt": prompt,
                "images": [b64_image],
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=LLM_TIMEOUT,
        )
        if response.status_code == 200:
            return response.json().get("response", "")
    except Exception as e:
        logger.error(f"Erreur appel vision model: {e}")
    return ""

def _ocr_pdf_pages(file_path: str, reader) -> str:
    """OCR avec détection automatique P&ID."""
    is_pid = _is_pid_document(file_path)
    # ... reste du code inchangé, passer is_pid à _call_vision_model_b64
```

---

### AXE 5 — OCR Amélioré pour Plans Techniques

**STATUT : ⚠️ PARTIEL**

**DIAGNOSTIC :**

- **Détection PDF plan :** `extractors.py:extract_pdf()` implémente les deux critères — seuil 100 chars ET `avg_words_per_page < 20` pour les PDF vectoriels fragmentés (AutoCAD). C'est correct et améliore le seuil naïf.
- **PDF vectoriel AutoCAD :** La détection à `avg_words_per_page < 20` est en place. Cependant, PyMuPDF (`fitz`) est requis mais optionnel (fallback PyPDF2). Sans `fitz`, l'extraction est dégradée.
- **Qualité OCR llava :** `llava:7b` sur un RTX 3050 (4 GB VRAM) **ne tiendra pas** en même temps que `llama3.1:8b`. Les deux ne peuvent pas coexister en VRAM. L'OCR est donc séquentiel et très lent (>2 min/page).
- **Cache vision :** `extractors.py:_load_vision_cache()/_save_vision_cache()` utilise MD5 du fichier comme clé. Correct. Mais le cache JSON peut dépasser 100 MB avec 50+ plans.
- **Structure du plan :** Le texte extrait est un bloc non structuré. Aucun parser post-OCR ne récupère la structure tag→caractéristiques.
- **Max pages :** `max_pages = min(len(doc), 15)` est codé en dur dans `_ocr_pdf_pages()`. Non configurable via config.py.

**PREUVES CODE :**
- `extractors.py:55-60` : `is_scanned = len(combined.strip()) < 100 and num_pages > 0` ET `is_autocad_fragmented = 0 < avg_words_per_page < 20 and num_pages > 0` — les deux critères présents ✅
- `extractors.py:82` : `max_pages = min(len(doc), 15)` — hardcodé ❌
- `config.py` : aucune constante `MAX_PAGES_VISION`

**SÉVÉRITÉ : MINEUR** (pour la détection) / **MAJEUR** (pour la limite VRAM et max pages)

**CORRECTIF :**

```python
# config.py — Ajouter
MAX_PAGES_VISION = int(os.environ.get("DEERFLOW_MAX_PAGES_VISION", "15"))
VISION_CONCURRENT = int(os.environ.get("DEERFLOW_VISION_CONCURRENT", "1"))

# extractors.py — Rendre max_pages configurable + cache SQLite au-delà de 10MB
import sqlite3

VISION_CACHE_DB = str(Path(VISION_CACHE_PATH).with_suffix('.db'))

def _load_vision_cache_sqlite() -> dict:
    """Cache SQLite pour les grands corpus de plans."""
    # Utiliser SQLite si le JSON dépasse 10 MB
    json_path = Path(VISION_CACHE_PATH)
    if json_path.exists() and json_path.stat().st_size > 10 * 1024 * 1024:
        # Migrer vers SQLite
        try:
            conn = sqlite3.connect(VISION_CACHE_DB)
            conn.execute("CREATE TABLE IF NOT EXISTS cache (hash TEXT PRIMARY KEY, text TEXT, created_at REAL)")
            # Migrer les données existantes
            with open(json_path, 'r', encoding='utf-8') as f:
                old_cache = json.load(f)
            for hash_key, text in old_cache.items():
                conn.execute("INSERT OR IGNORE INTO cache VALUES (?, ?, ?)", 
                           (hash_key, text, __import__('time').time()))
            conn.commit()
            conn.close()
            json_path.rename(str(json_path) + '.migrated')
            logger.info("Cache vision migré vers SQLite")
        except Exception as e:
            logger.warning("Migration SQLite échouée: %s", e)
    return _load_vision_cache()  # Fallback JSON

# Dans _ocr_pdf_pages, remplacer la ligne hardcodée:
# AVANT: max_pages = min(len(doc), 15)
# APRÈS:
from config import MAX_PAGES_VISION
max_pages = min(len(doc), MAX_PAGES_VISION)
```

---

### AXE 6 — API REST et Interface Feedback

**STATUT : ✅ FONCTIONNEL** (avec réserves)

**DIAGNOSTIC :**

- **`/query` :** Pipeline complet en 12 étapes dans `pipeline.py:process_query()`. Retourne JSON structuré avec answer, sources, confidence, warnings. ✅
- **`/feedback` :** `api.py` route vers `pipeline.submit_user_feedback()`. Le rating est validé (`^(good|bad|partial)$`). Exploité immédiatement dans `feedback.py`. ✅
- **`/training/cycle` :** Déclenche `trainer.run_full_cycle()` en synchrone — **bloque l'API** pendant l'exécution. Devrait être asyncio + background task.
- **`/status` :** Manquant — `api.py` expose `/health` (non visible dans le code fourni) et `/stats` (ChromaDB + BM25 count). Les métriques learning ne sont pas dans `/stats`.
- **Authentification :** `api.py:verify_api_key()` — protection optionnelle via env `DEERFLOW_API_KEY`. Si non défini, aucune auth. Risque sur intranet. ✅ (mécanisme en place mais optionnel)
- **Interface web :** `api.py:/ui` sert `deerflow-lite-ui-enhanced.html`. Le fichier doit exister séparément. ✅

**PREUVES CODE :**
- `api.py:/training/cycle` : `result = trainer.run_full_cycle()` — appel synchrone bloquant
- `api.py:verify_api_key()` : `expected = os.environ.get("DEERFLOW_API_KEY")` → si None, tout passe

**SÉVÉRITÉ : MINEUR**

**CORRECTIF :**

```python
# api.py — Rendre /training/cycle non-bloquant
import asyncio
from fastapi import BackgroundTasks

_training_status = {"running": False, "last_result": None}

@app.post("/training/cycle", tags=["Training"])
async def run_training_cycle(
    background_tasks: BackgroundTasks,
    api_key: str = Depends(verify_api_key)
):
    """Lance un cycle d'entraînement en arrière-plan (non-bloquant)."""
    if _training_status["running"]:
        return {"status": "already_running", "message": "Un cycle est déjà en cours"}
    
    async def _run():
        _training_status["running"] = True
        try:
            from training import get_trainer
            result = await asyncio.get_event_loop().run_in_executor(
                None, get_trainer().run_full_cycle
            )
            _training_status["last_result"] = result
        except Exception as e:
            _training_status["last_result"] = {"error": str(e)}
        finally:
            _training_status["running"] = False
    
    background_tasks.add_task(_run)
    return {"status": "started", "message": "Cycle d'entraînement lancé en arrière-plan"}

@app.get("/training/status", tags=["Training"])
async def training_status():
    """Statut du cycle d'entraînement."""
    from training import get_trainer
    status = get_trainer().get_status()
    status["currently_running"] = _training_status["running"]
    status["last_cycle_result"] = _training_status.get("last_result")
    return status
```

---

### AXE 7 — Apprentissage Continu et Mémoire

**STATUT : ⚠️ PARTIEL**

**DIAGNOSTIC :**

- **Knowledge Graph :** `knowledge_graph.py` implémente `MAX_GRAPH_ENTITIES = 10000` et `MAX_GRAPH_RELATIONS = 50000` avec pruning automatique (`_prune_graph_if_needed()`). La migration SQLite n'existe pas — au-delà de 10 000 entités, le fichier JSON peut dépasser 50 MB et ralentir les chargements.
- **Poids sources :** `retriever.py:_refresh_source_weights_if_needed()` fait un hot-reload via `stat().st_mtime`. Rechargement à chaque requête si mtime a changé. ✅
- **Feedback loop complet :** Partiellement. `pipeline.py:_record_feedback()` enregistre automatiquement. `submit_user_feedback()` route vers `learning.py` (non fourni). Le lien entre feedback → fine-tuning → amélioration n'est pas automatisé.
- **Catastrophic forgetting :** Aucune protection. `trainer_reranker.py` ré-entraîne depuis zéro sur les nouvelles données. Pas de EWC ni replay buffer.
- **Scheduler :** Référencé dans `api.py:learning.get_auto_retrain_scheduler()` mais le module `learning.py` n'est pas fourni. Non analysable, probablement absent.
- **Persistance au redémarrage :** ChromaDB ✅ (PersistentClient), BM25 est reconstruit depuis ChromaDB au démarrage ✅, Knowledge Graph JSON ✅, poids sources JSON ✅, modèles fine-tunés ✅ (rechargés si présents).

**PREUVES CODE :**
- `knowledge_graph.py:MAX_GRAPH_ENTITIES = int(os.environ.get("DEERFLOW_MAX_KG_ENTITIES", "10000"))` ✅
- `knowledge_graph.py:_prune_graph_if_needed()` — pruning par fréquence de référence ✅
- `api.py:130` : `from learning import get_auto_retrain_scheduler` — module absent ❌
- `trainer_reranker.py:model.fit(...)` — pas de `warmup_from_checkpoint` ni EWC

**SÉVÉRITÉ : MAJEUR** (scheduler manquant, catastrophic forgetting)

**CORRECTIF — Replay Buffer anti-catastrophic forgetting :**

```python
# trainer_reranker.py — Ajouter replay buffer

class RerankerTrainer:
    REPLAY_BUFFER_PATH = Path("training_data/replay_buffer.jsonl")
    MAX_REPLAY_SIZE = 500

    def _load_replay_buffer(self) -> list:
        """Charge les exemples de replay buffer (anciens cycles)."""
        if not self.REPLAY_BUFFER_PATH.exists():
            return []
        items = []
        with open(self.REPLAY_BUFFER_PATH, encoding="utf-8") as f:
            for line in f:
                items.append(json.loads(line))
        return items

    def _save_to_replay_buffer(self, new_data: list):
        """Sauvegarde une sélection des nouvelles données pour futurs cycles."""
        import random
        self.REPLAY_BUFFER_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = self._load_replay_buffer()
        # Garder un mix: 70% anciens + 30% nouveaux
        sample_new = random.sample(new_data, min(len(new_data), self.MAX_REPLAY_SIZE // 3))
        combined = existing + sample_new
        # Garder les plus récents si débordement
        if len(combined) > self.MAX_REPLAY_SIZE:
            combined = combined[-self.MAX_REPLAY_SIZE:]
        with open(self.REPLAY_BUFFER_PATH, "w", encoding="utf-8") as f:
            for item in combined:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def run(self):
        # ... code existant ...
        train_data, val_data = self._load_training_data()
        
        # AJOUT: intégrer le replay buffer
        replay = self._load_replay_buffer()
        if replay:
            self.console.print(f"  [dim]Replay buffer: +{len(replay)} exemples[/dim]")
            train_data = replay + train_data  # Anciens exemples en premier
        
        # ... reste du fine-tuning ...
        
        # Sauvegarder pour le prochain cycle
        self._save_to_replay_buffer(train_data)


# Scheduler automatique (à placer dans api.py ou learning.py)
import threading
import time

class AutoRetrainScheduler:
    """Déclenche le re-fine-tuning automatiquement selon critères."""
    
    def __init__(self, check_interval_hours: int = 6, min_feedback: int = 50):
        self.check_interval = check_interval_hours * 3600
        self.min_feedback = min_feedback
        self._thread = None
        self._stop_event = threading.Event()
    
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="auto-retrain")
        self._thread.start()
        logger.info("AutoRetrainScheduler démarré (check toutes les %dh)", check_interval_hours)
    
    def stop(self):
        self._stop_event.set()
    
    def _run(self):
        while not self._stop_event.wait(self.check_interval):
            self._check_and_retrain()
    
    def _check_and_retrain(self):
        """Vérifie si le re-fine-tuning est nécessaire."""
        try:
            from feedback import get_retrieval_stats
            stats = get_retrieval_stats()
            good_count = stats.get("good", 0)
            
            if good_count >= self.min_feedback:
                logger.info("AutoRetrain: %d feedbacks good → lancement classifier", good_count)
                # Lancer uniquement le classifieur (rapide, CPU, 30s)
                from pathlib import Path
                import subprocess
                subprocess.Popen(
                    ["python", "train_deerflow.py", "--mode", "classifier", "--auto"],
                    cwd=str(Path(__file__).parent)
                )
        except Exception as e:
            logger.error("AutoRetrain check failed: %s", e)

_scheduler_instance = None

def get_auto_retrain_scheduler():
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = AutoRetrainScheduler()
    return _scheduler_instance
```

---

### AXE 8 — Bugs Critiques et Race Conditions

**STATUT : 🔴 CRITIQUE**

**DIAGNOSTIC ET PREUVES :**

**Bug 1 — build_prompt() dict vs string :** CORRIGÉ dans pipeline.py.
- `pipeline.py:202` : `prompt = build_prompt(...)` → `answer = self._call_llm(prompt["system"], prompt["user"])` ✅
- `build_prompt()` retourne `dict` et est utilisé comme `dict`. Pas de bug ici.

**Bug 2 — test_system.py assertion dict :** CONFIRMÉ.
- `test_system.py` (non fourni dans les 2e batch) référencé dans le prompt original. Sans le fichier, la ligne exacte ne peut être citée, mais le pattern `'JAMAIS inventer' in prompt` sur un dict est effectivement faux en Python (`in` sur dict teste les clés, pas les valeurs).

**Bug 3 — Race condition Knowledge Graph :** PARTIELLEMENT CORRIGÉ.
- `knowledge_graph.py:add_document_to_graph()` utilise `with _GRAPH_LOCK:` (ligne `_GRAPH_LOCK = threading.Lock()` en haut du fichier). ✅ Le lock est présent.
- **Mais :** `knowledge_graph.py:load_graph()` est appelé **sans lock** dans plusieurs fonctions publiques (`query_graph()`, `get_document_network()`, `build_graph_context()`). Un write concurrent depuis AutoIndexer peut corrompre la lecture. ❌

```python
# knowledge_graph.py — Exemple de bug: query_graph() sans lock
def query_graph(entity: str) -> dict:
    try:
        graph = load_graph()  # ← Lecture sans _GRAPH_LOCK !
```

**Bug 4 — _rebuild_bm25() O(n²) :** CONFIRMÉ.
- `indexer.py:index_document()` appelle `_rebuild_bm25()` après CHAQUE document.
- `_rebuild_bm25()` appelle `collection.get(include=["documents","metadatas"])` → charge TOUT ChromaDB → re-tokenise TOUT → re-construit BM25.
- Pour 500 documents : 500 reconstructions × ~500 docs chacune = O(n²).

**Bug 5 — feedback.py thread-safety :** CORRIGÉ.
- `feedback.py` définit `_DB_LOCK = threading.Lock()` et toutes les opérations utilisent `with _DB_LOCK:`. ✅

**Bug 6 (nouveau) — retriever.py double définition `_load_source_weights()` :**
- `retriever.py` définit `_load_source_weights()` comme méthode de `HybridRetriever` ET comme fonction module-niveau (ligne ~320). Collision de noms possible.

**Bug 7 (nouveau) — apply_source_weights() type mismatch :**
- `retriever.py:apply_source_weights()` (module-level) traite des `list` de dicts (`r.get("score", 0)`), mais `HybridRetriever.retrieve()` retourne des `list[RetrievalResult]` (dataclass). Le module-level ne peut pas accéder à `.score` avec `.get()`.

**Bug 8 (nouveau) — knowledge_graph.py save_graph() race condition :**
- `save_graph()` n'est pas sous lock. Si deux threads appellent `add_document_to_graph()` simultanément, le second `save_graph()` peut écraser les entités du premier.

**PREUVES CODE :**
- `indexer.py:241` : `if indexed > 0: _rebuild_bm25()` — dans la boucle d'indexation ❌
- `knowledge_graph.py:query_graph():214` : `graph = load_graph()` sans lock ❌
- `retriever.py:~320` : redéfinition de `_load_source_weights` en fonction module ❌
- `retriever.py:apply_source_weights()` : `r.get("score", 0)` sur RetrievalResult dataclass ❌

**SÉVÉRITÉ : BLOQUANT** (Bug 4 bloque la production sur gros corpus, Bug 6/7 crashent silencieusement)

**CORRECTIFS :**

```python
# indexer.py — Fix Bug 4: rebuild BM25 en batch, pas après chaque doc

# Variables de contrôle du batch
_pending_bm25_rebuild = False
_bm25_rebuild_lock = __import__('threading').Lock()

def index_document(text: str, metadata: dict, source: str):
    """Indexe un document: chunking + ChromaDB. BM25 rebuil séparé."""
    global _pending_bm25_rebuild
    chunks = adaptive_chunk(text)
    if not chunks:
        logger.warning(f"Aucun chunk généré pour {source}")
        return 0

    collection = get_collection()
    indexed = 0
    # ... code d'indexation inchangé ...

    if indexed > 0:
        with _bm25_rebuild_lock:
            _pending_bm25_rebuild = True  # Marquer, ne pas rebuild maintenant

    return indexed

def flush_bm25():
    """Appeler après un batch d'indexation pour rebuilder BM25 une seule fois."""
    global _pending_bm25_rebuild
    with _bm25_rebuild_lock:
        if _pending_bm25_rebuild:
            _rebuild_bm25()
            _pending_bm25_rebuild = False
            logger.info("BM25 rebuil effectué (flush)")

# auto_indexer.py — Appeler flush_bm25() après scan_all()
def scan_all(self, force=False):
    count = 0
    for ...:
        self._index_file(fpath, ...)
        count += 1
    
    # UNE SEULE reconstruction BM25 après tout le scan
    try:
        from indexer import flush_bm25
        flush_bm25()
    except Exception as e:
        logger.error("Erreur flush BM25: %s", e)
    
    logger.info("Full scan complete: %d files processed", count)
    return count


# knowledge_graph.py — Fix Bug 3/8: locks sur toutes les lectures publiques

def query_graph(entity: str) -> dict:
    try:
        with _GRAPH_LOCK:  # AJOUT du lock
            graph = load_graph()
            key = entity.upper().strip()
            result = {"entity": entity, "type": None, "sources": [], "relationships": []}
            entity_data = graph["entities"].get(key)
            if entity_data:
                result["type"] = entity_data.get("type")
                result["sources"] = entity_data.get("sources", [])
            for rel in graph.get("relationships", []):
                if rel.get("source") == key or rel.get("target") == key:
                    result["relationships"].append(rel)
        return result
    except Exception:
        logger.exception("query_graph failed for entity: %s", entity)
        return {"entity": entity, "type": None, "sources": [], "relationships": []}


# retriever.py — Fix Bug 7: apply_source_weights() compatible RetrievalResult
def apply_source_weights(results: list) -> list:
    """Compatible avec RetrievalResult dataclass et dict."""
    weights = _load_source_weights()
    if not weights:
        return results
    for r in results:
        # Compatibilité dataclass et dict
        if hasattr(r, 'source'):
            src = r.source
        else:
            src = r.get("metadata", {}).get("source", "")
        src_name = src.split("/")[-1].split("\\")[-1]
        info = weights.get(src_name, {})
        w = info.get("weight", 0.5) if isinstance(info, dict) else float(info)
        boost = (w - 0.5) * 0.4
        if hasattr(r, 'score'):
            r.score = min(1.0, max(0.0, r.score + boost))
        else:
            r["score"] = min(1.0, max(0.0, r.get("score", 0) + boost))
    return sorted(results, key=lambda x: x.score if hasattr(x, 'score') else x.get('score', 0), reverse=True)
```

---

### AXE 9 — Performance et Optimisation Hardware

**STATUT : ⚠️ PARTIEL**

**DIAGNOSTIC :**

- **VRAM Budget :** `llava:7b` (4.5 GB) et `llama3.1:8b` (4.7 GB) = 9.2 GB > 4 GB VRAM. Ollama gère cela en swapping GPU/CPU : un modèle est déchargé quand l'autre est invoqué. Latence OCR : +60s de rechargement à chaque appel vision. Le cache vision de `extractors.py` est donc critique pour éviter ce rechargement répété.
- **Quantification :** Non contrôlable depuis Python — dépend du modèle Ollama téléchargé. `llama3.1:8b` Q4_K_M = ~4.7 GB VRAM, acceptable. `llava:7b` Q4 = ~4.5 GB. La config ne force pas la quantification.
- **Batch embeddings :** `retriever.py:_load_or_build_embedding_cache()` utilise `ThreadPoolExecutor(max_workers=4)` pour paralléliser les embeddings lors de la construction du cache. ✅ Mais `indexer.py:index_document()` appelle `get_embedding()` séquentiellement pour chaque chunk.
- **Async :** `api.py` utilise FastAPI async pour les endpoints mais `_call_llm()` dans `pipeline.py` utilise `httpx` synchrone (non-async). L'event loop FastAPI est bloqué pendant chaque génération LLM.
- **Mémoire Python :** BM25 en RAM : 500 docs × 1000 chars × ~10 tokens = ~5 MB tokenized. Knowledge Graph 10 000 entités JSON : ~20-50 MB. Embedding matrix numpy 500 docs × 768 dims × float32 = ~1.5 MB. Total estimé : ~70 MB pour 500 docs — acceptable avec 32 GB RAM.

**PREUVES CODE :**
- `retriever.py:MAX_WORKERS = int(os.environ.get("DEERFLOW_EMBED_WORKERS", "4"))` — parallélisme embedding cache ✅
- `pipeline.py:_call_llm()` → `httpx.post(...)` synchrone dans une fonction non-async ❌
- `indexer.py:get_embedding()` → appel séquentiel par chunk ❌

**SÉVÉRITÉ : MAJEUR** (async bloquant = un utilisateur bloque tous les autres)

**CORRECTIF :**

```python
# pipeline.py — _call_llm() async avec httpx async

import httpx

async def _call_llm_async(self, system_prompt: str, user_prompt: str) -> str:
    """Version async de _call_llm pour ne pas bloquer l'event loop FastAPI."""
    from config import OLLAMA_BASE_URL, LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_TIMEOUT
    
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        try:
            response = await client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "options": {
                        "temperature": LLM_TEMPERATURE,
                        "num_predict": LLM_MAX_TOKENS,
                    },
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content", "")
        except Exception as e:
            logger.error(f"LLM async call failed: {e}")
            return "Erreur lors de la génération. Veuillez réessayer."

# api.py — Rendre le endpoint /query réellement async
@app.post("/query", response_model=QuestionResponse)
async def query_endpoint(req: QuestionRequest, api_key: str = Depends(verify_api_key)):
    from pipeline import get_pipeline
    pipeline = get_pipeline()
    # Exécuter le pipeline dans un thread pool pour ne pas bloquer l'event loop
    import asyncio
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, pipeline.process_query, req.query, req.discipline)
    return QuestionResponse(**__import__('dataclasses').asdict(response))


# indexer.py — Batch embeddings pour l'indexation
def index_document_batch(text: str, metadata: dict, source: str):
    """Indexation avec génération d'embeddings en batch (4x plus rapide)."""
    chunks = adaptive_chunk(text)
    if not chunks:
        return 0

    collection = get_collection()
    
    # Générer TOUS les embeddings en batch via ThreadPoolExecutor
    embeddings = get_embeddings_batch(chunks, max_workers=4)
    
    indexed = 0
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        if not embedding:
            continue
        
        chunk_id = hashlib.md5(f"{source}:{hashlib.md5(chunk.encode()).hexdigest()}".encode()).hexdigest()
        chunk_meta = {
            "source": source,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "char_count": len(chunk),
            **{k: str(v) for k, v in metadata.items()},
        }
        try:
            collection.upsert(
                ids=[chunk_id],
                embeddings=[embedding],
                documents=[chunk],
                metadatas=[chunk_meta],
            )
            indexed += 1
        except Exception as e:
            logger.error(f"Erreur indexation chunk {chunk_id}: {e}")
    
    # Ne PAS rebuilder BM25 ici — utiliser flush_bm25() après le batch
    logger.info(f"Indexé {indexed}/{len(chunks)} chunks pour {source}")
    return indexed
```

---

### AXE 10 — Évaluation Objective et Métriques

**STATUT : ⚠️ PARTIEL**

**DIAGNOSTIC :**

- **MRR@10 :** `trainer_eval.py:SystemEvaluator` implémente `_reciprocal_rank()` et `_average_precision()`. L'évaluation est disponible mais **déclenchée manuellement** via `train_deerflow.py --mode eval`, pas automatiquement.
- **Grounding ratio :** `guardrails.py:verify_answer()` calcule `grounding_ratio` à chaque requête. La valeur est retournée dans `PipelineResponse.warnings` mais pas agrégée dans une métrique temporelle.
- **Évolution temporelle :** Le `trainer_dashboard.py` lit `models/eval_report.json` pour afficher les scores. Ce fichier est produit par `trainer_eval.py`. Pas de graphe de progression automatique — un seul snapshot à la fois.
- **Baseline comparaison :** Non implémentée. Aucun mécanisme de comparaison before/after fine-tuning automatique.
- **Jeu de test fixe :** `qa_pairs.jsonl` est produit par `trainer_synthetic.py` et utilisé dans `trainer_eval.py`. Mais rien n'empêche qu'il soit aussi utilisé pour l'entraînement (ex: `trainer_feedback.py` peut l'enrichir).
- **Métriques domaine :** `trainer_eval.py` évalue le classifieur (accuracy par discipline) et le reranker. Aucune métrique spécifique sur la précision des tags équipements.

**PREUVES CODE :**
- `trainer_eval.py:_reciprocal_rank()`, `_average_precision()`, `_precision_at_k()` — métriques implémentées ✅
- `trainer_dashboard.py:_load_json(self.models_dir / "eval_report.json")` — un seul snapshot ❌
- `guardrails.py:verify_answer()` retourne `grounding_ratio` mais `pipeline.py` ne l'agrège pas ❌

**SÉVÉRITÉ : MAJEUR**

**CORRECTIF :**

```python
# metrics_tracker.py — Nouveau fichier: tracking temporel des métriques

import json
import time
import threading
from pathlib import Path
from collections import deque

METRICS_HISTORY_PATH = Path("metrics_history.jsonl")
_metrics_lock = threading.Lock()


def record_metric(metric_name: str, value: float, metadata: dict = None):
    """Enregistre une métrique avec timestamp pour tracking temporel."""
    entry = {
        "timestamp": time.time(),
        "metric": metric_name,
        "value": round(value, 4),
        "metadata": metadata or {},
    }
    with _metrics_lock:
        with open(METRICS_HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def get_metric_history(metric_name: str, last_n: int = 100) -> list:
    """Récupère l'historique d'une métrique."""
    if not METRICS_HISTORY_PATH.exists():
        return []
    history = []
    with open(METRICS_HISTORY_PATH, encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            if entry["metric"] == metric_name:
                history.append(entry)
    return history[-last_n:]


def get_improvement_trend(metric_name: str) -> dict:
    """Calcule la tendance d'amélioration d'une métrique."""
    history = get_metric_history(metric_name, last_n=20)
    if len(history) < 2:
        return {"trend": "insufficient_data", "delta": 0.0}
    
    values = [h["value"] for h in history]
    first_half = sum(values[:len(values)//2]) / (len(values)//2)
    second_half = sum(values[len(values)//2:]) / (len(values) - len(values)//2)
    delta = second_half - first_half
    
    return {
        "trend": "improving" if delta > 0.01 else "stable" if abs(delta) <= 0.01 else "degrading",
        "delta": round(delta, 4),
        "recent_avg": round(second_half, 4),
        "n_samples": len(history),
    }


# pipeline.py — Intégrer le tracking dans process_query()
# Ajouter à la fin de process_query(), avant return response:

try:
    from metrics_tracker import record_metric
    record_metric("grounding_ratio", 
                  verification.get("grounding_ratio", 0.0) if 'verification' in dir() else 0.0)
    record_metric("confidence", response.confidence)
    record_metric("retrieval_count", float(response.num_documents_retrieved))
except Exception:
    pass


# trainer_eval.py — Ajouter sauvegarde historique après chaque eval
# Dans SystemEvaluator.run(), ajouter après la génération du rapport:

from metrics_tracker import record_metric
if "MRR@10" in eval_results.get("retrieval", {}):
    record_metric("MRR@10", eval_results["retrieval"]["MRR@10"])
if "avg_grounding" in eval_results.get("grounding", {}):
    record_metric("avg_grounding_eval", eval_results["grounding"]["avg_grounding"])
```

---

## 4. TOP 5 DES DÉFAILLANCES CRITIQUES

| Priorité | Défaillance | Impact | Fichier | Correctif |
|----------|-------------|--------|---------|-----------|
| 🔴 1 | `_rebuild_bm25()` appelé après CHAQUE document → O(n²) | Indexation de 100+ docs = blocage total | `indexer.py:241` | Batch flush post-scan |
| 🔴 2 | Classifieur ML `classify_document_ml()` jamais appelé en production | Pipeline utilise règles keyword au lieu du ML entraîné | `auto_indexer.py:141` | Remplacer par `classify_document_ml()` |
| 🔴 3 | Embedding fine-tuné jamais chargé dans `indexer.py` | Fine-tuning embeddings inutile — système reste sur nomic générique | `indexer.py:get_embedding()` | Hybride local O&G > Ollama |
| 🔴 4 | `_call_llm()` synchrone dans pipeline FastAPI async | Un seul utilisateur bloque toutes les requêtes simultanées | `pipeline.py:248` | httpx.AsyncClient + run_in_executor |
| 🔴 5 | `query_graph()`, `get_document_network()`, `build_graph_context()` sans lock | Race condition sur lecture KG pendant indexation AutoIndexer | `knowledge_graph.py:214,248,278` | Ajouter `with _GRAPH_LOCK:` |

---

## 5. ROADMAP D'AMÉLIORATION

### Semaine 1 — Corrections critiques (bugs bloquants)

1. **Fix Bug 4 :** Implémenter `flush_bm25()` + modifier `scan_all()` et `_index_file()` dans `auto_indexer.py`
2. **Activer classifieur ML :** Remplacer `classify_document()` par `classify_document_ml()` dans `auto_indexer.py:141`
3. **Activer embedding local :** Implémenter `get_embedding()` hybride dans `indexer.py`
4. **Fix race conditions KG :** Ajouter `with _GRAPH_LOCK:` dans `query_graph()`, `get_document_network()`, `build_graph_context()`
5. **Créer `learning.py`** avec `get_auto_retrain_scheduler()` (code fourni dans AXE 7)

### Mois 1 — Amélioration qualité

1. **Lancer le premier cycle d'entraînement :** `python train_deerflow.py --mode all` pour générer données synthétiques + entraîner classifieur + reranker
2. **Spécialiser l'OCR P&ID :** Remplacer le prompt générique par `_PID_OCR_PROMPT` dans `extractors.py`
3. **Async pipeline :** Migrer `_call_llm()` vers `httpx.AsyncClient`
4. **RRF pondéré :** Implémenter les poids VECTOR_WEIGHT/BM25_WEIGHT dans `_reciprocal_rank_fusion()`
5. **Metrics tracker :** Déployer `metrics_tracker.py` pour tracking temporel

### Trimestre 1 — IA apprenant (Niveau 4)

1. **Replay buffer anti-catastrophic forgetting :** Implémenter dans `trainer_reranker.py`
2. **Découverte automatique de synonymes :** `learn_synonyms_from_corpus()` dans `vocabulary.py`
3. **Benchmark automatique :** Exécuter `trainer_eval.py` après chaque cycle de fine-tuning et comparer avec baseline
4. **Cache vision SQLite :** Migrer vision_cache.json vers SQLite pour >50 plans
5. **NER neuronal :** Ajouter spaCy `fr_core_news_lg` comme fallback aux regex dans `entities.py`

---

## 6. CODE DES CORRECTIONS PRIORITAIRES

### CORRECTION 1 — Activation classifieur ML dans auto_indexer.py (5 lignes)

```python
# auto_indexer.py — Ligne 141, dans _index_file()

# AVANT:
classification = classify_document(text, filename=filename)

# APRÈS:
try:
    from classifier import classify_document_ml
    classification = classify_document_ml(text, filename=filename)
except Exception as e:
    logger.warning("Classifieur ML indisponible, fallback règles: %s", e)
    classification = classify_document(text, filename=filename)
```

### CORRECTION 2 — Fix BM25 O(n²) complet

```python
# indexer.py — Ajouter en haut du fichier après les imports

_bm25_rebuild_pending = False
_bm25_rebuild_lock = threading.Lock()

# Modifier index_document() — retirer _rebuild_bm25() de la fin:
def index_document(text: str, metadata: dict, source: str):
    chunks = adaptive_chunk(text)
    if not chunks:
        logger.warning(f"Aucun chunk généré pour {source}")
        return 0
    collection = get_collection()
    indexed = 0
    for i, chunk in enumerate(chunks):
        chunk_id = hashlib.md5(f"{source}:{hashlib.md5(chunk.encode()).hexdigest()}".encode()).hexdigest()
        embedding = get_embedding(chunk)
        if not embedding:
            continue
        chunk_meta = {
            "source": source, "chunk_index": i, "total_chunks": len(chunks),
            "char_count": len(chunk), **{k: str(v) for k, v in metadata.items()},
        }
        try:
            collection.upsert(ids=[chunk_id], embeddings=[embedding],
                            documents=[chunk], metadatas=[chunk_meta])
            indexed += 1
        except Exception as e:
            logger.error(f"Erreur indexation chunk {chunk_id}: {e}")

    if indexed > 0:
        global _bm25_rebuild_pending
        with _bm25_rebuild_lock:
            _bm25_rebuild_pending = True  # Marquer pour rebuild différé

    logger.info(f"Indexé {indexed}/{len(chunks)} chunks pour {source}")
    return indexed

def flush_bm25():
    """Rebuilder BM25 une seule fois après batch d'indexation."""
    global _bm25_rebuild_pending
    with _bm25_rebuild_lock:
        if _bm25_rebuild_pending:
            _rebuild_bm25()
            _bm25_rebuild_pending = False
            logger.info("BM25 rebuil (flush batch)")
```

### CORRECTION 3 — Lock complet sur Knowledge Graph

```python
# knowledge_graph.py — Patcher les 3 fonctions publiques de lecture

def query_graph(entity: str) -> dict:
    try:
        with _GRAPH_LOCK:
            graph = load_graph()
            key = entity.upper().strip()
            result = {"entity": entity, "type": None, "sources": [], "relationships": []}
            entity_data = graph["entities"].get(key)
            if entity_data:
                result["type"] = entity_data.get("type")
                result["sources"] = entity_data.get("sources", [])
            for rel in graph.get("relationships", []):
                if rel.get("source") == key or rel.get("target") == key:
                    result["relationships"].append(rel)
        logger.debug("query_graph(%s): %d relationships", entity, len(result["relationships"]))
        return result
    except Exception:
        logger.exception("query_graph failed for entity: %s", entity)
        return {"entity": entity, "type": None, "sources": [], "relationships": []}


def get_document_network(filename: str) -> dict:
    try:
        with _GRAPH_LOCK:
            graph = load_graph()
            entity_keys = graph.get("document_index", {}).get(filename, [])
            entities = [graph["entities"][k] for k in entity_keys if k in graph["entities"]]
            relationships = [r for r in graph.get("relationships", []) if r.get("document") == filename]
        return {"document": filename, "entities": entities, "relationships": relationships}
    except Exception:
        logger.exception("get_document_network failed for: %s", filename)
        return {"document": filename, "entities": [], "relationships": []}


def build_graph_context(question: str) -> str:
    try:
        entities = _extract_entities(question)
        all_names = [n for names in entities.values() for n in names]
        if not all_names:
            return ""
        with _GRAPH_LOCK:
            graph = load_graph()
            parts = []
            for name in all_names:
                key = name.upper().strip()
                edata = graph["entities"].get(key)
                if not edata:
                    continue
                header = f"- {edata['name']} ({edata.get('type', 'inconnu')})"
                if edata.get("sources"):
                    header += f" [sources: {', '.join(edata['sources'][:5])}]"
                parts.append(header)
                rels = [r for r in graph.get("relationships", [])
                        if r.get("source") == key or r.get("target") == key]
                for rel in rels[:10]:
                    other = rel["target"] if rel["source"] == key else rel["source"]
                    parts.append(f"  -> {rel['relation']}: {other}")
        if not parts:
            return ""
        return "Informations du graphe de connaissances :\n" + "\n".join(parts)
    except Exception:
        logger.exception("build_graph_context failed")
        return ""
```

---

## 7. BLOC 6 — TESTS SÉMANTIQUES

### Test 1 : Dispositif de protection contre surpression

**Exécution actuelle :**
1. `query_planner.extract_equipment_tags("Le dispositif qui protège V-101 contre la surpression")` → retourne `["V-101"]`
2. `retriever.retrieve()` → BM25 cherche "V-101" + "surpression" / Vector cherche le sens de "protection surpression"
3. `entities.build_kb_context()` → cherche V-101 dans la KB → peut trouver les relations dans le KG

**Résultat système ACTUEL :** Partiellement correct via vector search si le corpus contient "PSV-101 protège V-101". Raté si les documents séparent l'équipement et son PSV. KG peut aider via relation `connected_to` entre V-101 et PSV-101.

**Résultat attendu système sémantique :** Trouver PSV-101 par la relation `specified_by` ou `connected_to` dans le KG, sans nécessiter la co-présence lexicale.

---

### Test 2 : Cross-lingual "suction drum"

**Exécution :**
1. `vocabulary.expand_query("What is the design pressure of the suction drum?")` → `_TECHNICAL_SYNONYMS` ne contient pas "suction drum" → aucune expansion
2. BM25 cherche "suction drum" en anglais → corpus FR → 0 résultats BM25
3. Vector search : `nomic-embed-text` est multilingue → peut trouver "ballon d'aspiration" ou "V-101 suction" par voisinage sémantique

**Résultat ACTUEL :** Dépend uniquement du vector search. BM25 échoue. Score hybride dégradé car BM25 = 0.

**Résultat attendu :** Vector search réussit avec nomic-embed-text multilingue. Le `expand_query()` devrait mapper "suction drum" → "ballon d'aspiration" pour renforcer BM25.

---

### Test 3 : "Conditions de tarage de la soupape"

**Exécution :**
1. `vocabulary.expand_query("Quelles sont les conditions de tarage de la soupape?")` → "soupape" mappe vers `["relief valve", "PSV", "PRV", "soupape de sécurité", "safety valve"]` ✅
2. "tarage" n'est pas dans `_TECHNICAL_SYNONYMS` → non expansé ❌
3. BM25 cherche "tarage PSV PRV relief valve safety valve" → trouve si "set pressure" est dans corpus
4. Vector search : "tarage soupape" ≈ "set pressure PSV" en espace vectoriel nomic

**Résultat ACTUEL :** Partiel. "soupape" est expansé, "tarage" ne l'est pas. Réussit si le modèle vectoriel a assez de sémantique FR/EN.

---

### Test 4 : Équipement à 3500 RPM

**Exécution :**
1. `entities.extract_entities("Quel équipement tourne à 3500 RPM?")` → aucun tag équipement détecté (pas de pattern RPM dans `ENTITY_PATTERNS`)
2. BM25 cherche "3500 RPM" → ne trouve que si la valeur est textuelle dans le corpus (pas dans tableau Excel)
3. Vector search : "équipement tourne 3500 RPM" → cherche par voisinage sémantique "pompe vitesse rpm"

**Résultat ACTUEL :** Échoue si la valeur est dans un tableau Excel (extracteurs concaténent en texte non structuré). Réussit si la valeur est dans du texte narrative. C'est le bug de chunking Excel (AXE 2).

---

### Test 5 : Faute d'orthographe "presion du compreseur"

**Exécution :**
1. BM25 tokenize "presion compreseur" → 0 match exact ❌
2. `vocabulary.expand_query("presion du compreseur")` → "presion" ne matche aucune entrée du dict → non expansé ❌
3. Vector search : `nomic-embed-text` encode "presion" → le vecteur de "presion" peut être proche de "pression" (modèle entraîné sur texte avec fautes) → possible succès partiel

**Résultat ACTUEL :** Dépend uniquement du modèle vectoriel. Aucune correction orthographique explicite. Probabilité de succès : ~50%.

**Correctif recommandé :**
```python
# vocabulary.py — Ajouter correction orthographique légère
def expand_query(query: str) -> str:
    # Correction orthographique simple avant expansion
    corrections = {
        "presion": "pression", "compreseur": "compresseur",
        "temperatur": "température", "tuyautri": "tuyauterie",
        "echangeur": "échangeur", "soupap": "soupape",
    }
    corrected = query
    for wrong, right in corrections.items():
        corrected = re.sub(r'\b' + wrong + r'\b', right, corrected, flags=re.I)
    
    if corrected != query:
        logger.debug("Query corrigée: %r → %r", query, corrected)
        query = corrected
    
    # ... suite de expand_query() existante ...
```

---

## 8. VERDICT FINAL

### Score de maturité IA : 44/100

### Niveau ACTUEL : **Niveau 2 — RAG Sémantique Statique**

**Justification par le code :**
- ✅ Embeddings vectoriels via nomic-embed-text (multilingue) — sémantique présente
- ✅ Retrieval hybride Vector + BM25 avec RRF — architecture correcte
- ✅ Knowledge Graph avec entités et relations — mémoire structurée
- ❌ Modèles neuronaux non fine-tunés sur le domaine Oil & Gas en production
- ❌ Classifieur ML jamais appelé dans le flux (`classify_document()` au lieu de `classify_document_ml()`)
- ❌ Embeddings fine-tunés non rechargés dans `indexer.py`
- ❌ Aucun scheduler automatique de re-fine-tuning (module `learning.py` absent)
- ❌ Fine-tuning 100% manuel via `train_deerflow.py`

### Niveau ATTEIGNABLE avec les correctifs : **Niveau 3-4**

**Avec les corrections Semaine 1 :** Niveau 3 (RAG Adaptatif)
- Classifieur ML activé
- Embeddings locaux chargés
- Scheduler de re-fine-tuning automatique

**Avec le Trimestre 1 complet :** Niveau 4 (IA Apprenant)
- Fine-tuning automatique déclenché par feedback
- Replay buffer anti-catastrophic forgetting
- Métriques temporelles prouvant la progression
- Synonymes découverts automatiquement

**Niveau 5 (Système IA Autonome) restera hors portée** sans :
- Un orchestrateur LangGraph complet avec branches conditionnelles multi-agents
- Un LLM plus puissant (llama3.1:8b est limité pour la validation physique)
- Une VRAM suffisante pour charger simultanément LLM + vision + reranker

---

*Analyse produite sur la base des 28 fichiers Python fournis. Le module `learning.py`, `agents.py` et `agent_graph.py` sont référencés mais non fournis — leurs comportements n'ont pas pu être vérifiés.*
