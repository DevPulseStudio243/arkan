"""
DeerFlow Lite - Technical Vocabulary v2.0
Cached, domain-validated, with learned synonym support.
"""
import re
import json
import math
import logging
from pathlib import Path
from collections import Counter, defaultdict
from typing import Optional

logger = logging.getLogger(__name__)

# Paths
VOCABULARY_PATH = Path("vocabulary.json")
LEARNED_VOCAB_PATH = Path("learning_data/learned_vocabulary.json")

# Bilingual Oil & Gas synonym dictionary
_TECHNICAL_SYNONYMS: dict[str, list[str]] = {
    # Piping
    "tuyauterie": ["piping", "pipe", "conduite", "ligne", "line"],
    "bride": ["flange", "bride à collerette", "weld neck flange", "slip-on flange", "RTJ", "RF", "inlet flange", "outlet flange", "rating", "facing"],
    "vanne": ["valve", "robinet", "vanne à opercule", "gate valve"],
    "clapet": ["check valve", "clapet anti-retour", "non-return valve"],
    "joint": ["gasket", "joint d'étanchéité", "joint spiralé", "spiral wound gasket"],
    "raccord": ["fitting", "raccordement", "connection"],
    "soudure": ["weld", "soudage", "welding", "cordon de soudure"],
    "isométrique": ["isometric", "ISO drawing", "isometric drawing"],

    # Process
    "échangeur": ["heat exchanger", "échangeur de chaleur", "cooler", "heater", "condenser"],
    "pompe": ["pump", "pompe centrifuge", "centrifugal pump"],
    "compresseur": ["compressor", "turbocompresseur", "turbocompressor"],
    "colonne": ["column", "colonne de distillation", "distillation column", "tower"],
    "ballon": ["drum", "ballon séparateur", "separator drum", "vessel"],
    "séparateur": ["separator", "séparateur triphasique", "three-phase separator"],
    "réacteur": ["reactor", "réacteur catalytique", "catalytic reactor"],
    "chaudière": ["boiler", "chaudière à vapeur", "steam boiler"],
    "turbine": ["turbine", "turbine à gaz", "gas turbine", "turbine à vapeur"],

    # Instrumentation
    "capteur": ["sensor", "détecteur", "detector", "transmetteur", "transmitter"],
    "régulation": ["control", "contrôle", "asservissement", "regulation"],
    "boucle": ["loop", "boucle de régulation", "control loop"],
    "automate": ["PLC", "programmable logic controller", "automate programmable"],
    "vanne de régulation": ["control valve", "vanne régulatrice", "CV"],

    # Mechanical
    "roulement": ["bearing", "palier", "roulement à billes", "ball bearing"],
    "garniture": ["seal", "garniture mécanique", "mechanical seal"],
    "accouplement": ["coupling", "accouplement flexible", "flexible coupling"],
    "alignement": ["alignment", "lignage", "shaft alignment"],

    # Electrical
    "câble": ["cable", "conducteur", "conductor", "fil"],
    "disjoncteur": ["circuit breaker", "breaker"],
    "transformateur": ["transformer", "transfo"],
    "mise à la terre": ["earthing", "grounding", "mise à la masse"],

    # HSE
    "soupape": ["relief valve", "PSV", "PRV", "soupape de sécurité", "safety valve"],
    "HAZOP": ["hazard and operability", "étude HAZOP", "HAZOP study"],
    "zone ATEX": ["ATEX zone", "classified area", "zone classée"],

    # Materials
    "acier carbone": ["carbon steel", "CS", "A106", "A105"],
    "acier inoxydable": ["stainless steel", "SS", "inox", "316L", "304L"],
    "acier allié": ["alloy steel", "chrome-moly", "CrMo", "A335"],
    "duplex": ["duplex stainless steel", "2205", "S31803", "A995", "F51", "hardness", "dureté", "HB"],
    "inconel": ["Inconel", "alliage 625", "alloy 625", "alliage 825"],

    # General Oil & Gas
    "pression": ["pressure", "pression de service", "operating pressure", "pression de design"],
    "température": ["temperature", "température de service", "operating temperature"],
    "débit": ["flow rate", "flowrate", "débit massique", "mass flow"],
    "corrosion": ["corrosion", "corrosion allowance", "surépaisseur de corrosion"],
    "épaisseur": ["thickness", "wall thickness", "épaisseur de paroi"],
    "bruit": ["noise", "sound pressure level", "dBA", "sound level", "allowable limit", "pression acoustique", "niveau de bruit"],
}

# In-memory cache
_vocab_cache: Optional[dict] = None
_learned_cache: Optional[dict] = None
_cache_timestamp: float = 0


def _load_vocabulary() -> dict:
    """Load vocabulary from file with caching."""
    global _vocab_cache, _cache_timestamp

    try:
        if VOCABULARY_PATH.exists():
            mtime = VOCABULARY_PATH.stat().st_mtime
            if _vocab_cache is None or mtime > _cache_timestamp:
                with open(VOCABULARY_PATH, 'r', encoding='utf-8') as f:
                    _vocab_cache = json.load(f)
                _cache_timestamp = mtime
                logger.debug(f"Vocabulary loaded: {len(_vocab_cache.get('terms', {}))} terms")
        else:
            _vocab_cache = {"terms": {}}
    except Exception as e:
        logger.error(f"Error loading vocabulary: {e}")
        _vocab_cache = {"terms": {}}

    return _vocab_cache


def _load_learned_vocabulary() -> dict:
    """Load learned vocabulary (synonyms discovered from feedback)."""
    global _learned_cache

    if _learned_cache is not None:
        return _learned_cache

    try:
        if LEARNED_VOCAB_PATH.exists():
            with open(LEARNED_VOCAB_PATH, 'r', encoding='utf-8') as f:
                _learned_cache = json.load(f)
        else:
            _learned_cache = {}
    except Exception:
        _learned_cache = {}

    return _learned_cache


def expand_query(query: str) -> str:
    """
    Expand a query with technical synonyms for better BM25 recall.
    1. Correction orthographique légère des fautes fréquentes
    2. Expansion par dictionnaire statique bilingue
    3. Expansion par synonymes appris (feedback corpus)

    Args:
        query: Original user query

    Returns:
        Expanded query with added synonyms
    """
    # ── Étape 1 : Correction orthographique ──────────────────
    _ORTHO_CORRECTIONS = {
        r'\bpresion\b':     'pression',
        r'\bpresión\b':     'pression',
        r'\bcompreseur\b':  'compresseur',
        r'\bcompresseur\b': 'compresseur',
        r'\btemperatur\b':  'température',
        r'\btemperature\b': 'température',
        r'\btuyautri\b':    'tuyauterie',
        r'\bechangeur\b':   'échangeur',
        r'\bsoupap\b':      'soupape',
        r'\bvannes?\b':     'vanne',
        r'\bpompes?\b':     'pompe',
        r'\bflange\b':      'bride',
        r'\bdiametr\b':     'diamètre',
        r'\bdiametre\b':    'diamètre',
        r'\bépaisseur\b':   'épaisseur',
        r'\bepaisseur\b':   'épaisseur',
        r'\bdebits?\b':     'débit',
    }
    corrected = query
    for pattern, replacement in _ORTHO_CORRECTIONS.items():
        corrected = re.sub(pattern, replacement, corrected, flags=re.IGNORECASE)
    if corrected != query:
        logger.debug("Correction ortho : %r → %r", query, corrected)
        query = corrected

    # ── Étape 2 : Expansion dictionnaire statique ─────────────
    query_lower = query.lower()
    expansions = set()

    for term, synonyms in _TECHNICAL_SYNONYMS.items():
        # Vérifier si le terme principal est dans la requête
        if re.search(r'\b' + re.escape(term.lower()) + r'\b', query_lower):
            for syn in synonyms[:3]:
                if ' ' not in syn:
                    expansions.add(syn)
                else:
                    discriminative = max(syn.split(), key=len)
                    if len(discriminative) >= 3:
                        expansions.add(discriminative)
        else:
            # Recherche inverse : un synonyme est dans la requête
            for syn in synonyms:
                if re.search(r'\b' + re.escape(syn.lower()) + r'\b', query_lower):
                    expansions.add(term)
                    for sibling in synonyms:
                        if sibling != syn and ' ' not in sibling:
                            expansions.add(sibling)
                    break

    # ── Étape 3 : Synonymes appris depuis le corpus ───────────
    learned = _load_learned_vocabulary()
    for term, syns in learned.items():
        if re.search(r'\b' + re.escape(term.lower()) + r'\b', query_lower):
            expansions.update(syns[:2])

    if expansions:
        expansion_str = " ".join(expansions)
        expanded = f"{query} {expansion_str}"
        logger.debug("Requête étendue : +%d termes", len(expansions))
        return expanded

    return query


def build_vocabulary(documents: list[str], min_df: int = 2) -> dict:
    """
    Build term frequency vocabulary from document corpus.
    Only includes validated Oil & Gas terms.

    Args:
        documents: List of document texts
        min_df: Minimum document frequency to include a term

    Returns:
        Vocabulary dict with term frequencies
    """
    term_doc_freq = defaultdict(int)
    term_freq = Counter()

    for doc in documents:
        tokens = _tokenize_for_vocab(doc)
        unique_tokens = set(tokens)

        for token in tokens:
            term_freq[token] += 1

        for token in unique_tokens:
            term_doc_freq[token] += 1

    # Filter: minimum document frequency + domain validation
    vocab = {}
    for term, freq in term_freq.items():
        if term_doc_freq[term] >= min_df and _is_domain_term(term):
            vocab[term] = {
                "frequency": freq,
                "doc_frequency": term_doc_freq[term],
                "idf": _compute_idf(len(documents), term_doc_freq[term]),
            }

    result = {
        "terms": vocab,
        "num_documents": len(documents),
        "num_terms": len(vocab),
    }

    # Save
    with open(VOCABULARY_PATH, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Invalidate cache
    global _vocab_cache, _cache_timestamp
    _vocab_cache = None
    _cache_timestamp = 0

    logger.info(f"Vocabulary built: {len(vocab)} terms from {len(documents)} documents")
    return result


def get_term_frequency(term: str = "", top_n: int = 0) -> float | list:
    """
    Get the frequency of a term, or return the top-N most frequent terms.

    Args:
        term:  If provided, return the frequency (float) of this specific term.
        top_n: If > 0 and term is empty, return list of (term, freq) tuples.

    Returns:
        float if term provided, list of (term, freq) if top_n > 0, else 0.
    """
    vocab = _load_vocabulary()
    terms = vocab.get("terms", {})

    if term:
        entry = terms.get(term.lower())
        return entry.get("frequency", 0) if entry else 0

    if top_n > 0:
        sorted_terms = sorted(
            terms.items(),
            key=lambda x: x[1].get("frequency", 0),
            reverse=True,
        )
        return [(t, info.get("frequency", 0)) for t, info in sorted_terms[:top_n]]

    return 0


def invalidate_cache():
    """Force reload of vocabulary on next access."""
    global _vocab_cache, _learned_cache, _cache_timestamp
    _vocab_cache = None
    _learned_cache = None
    _cache_timestamp = 0


def _tokenize_for_vocab(text: str) -> list[str]:
    """Tokenize text for vocabulary building."""
    tokens = re.findall(r'\b[a-zA-Z\u00C0-\u017F0-9]{2,}\b', text.lower())
    # Remove stopwords
    stopwords = {"le", "la", "les", "de", "du", "des", "un", "une", "et", "en",
                 "est", "sont", "pour", "par", "sur", "dans", "avec", "qui", "que",
                 "ce", "cette", "ces", "au", "aux", "ne", "pas", "ou", "se", "sa",
                 "the", "is", "are", "of", "and", "in", "to", "for", "with", "on",
                 "il", "elle", "ils", "nous", "vous", "ont", "etre", "avoir", "fait"}
    return [t for t in tokens if t not in stopwords and len(t) >= 2]


def _is_domain_term(term: str) -> bool:
    """Check if a term is relevant to Oil & Gas domain."""
    # Reject programming/generic terms
    reject = {"float64", "float32", "int64", "int32", "string", "boolean", "null",
              "copyright", "license", "software", "import", "export", "function",
              "class", "def", "return", "http", "https", "www", "html", "css",
              "json", "xml", "yaml", "pip", "npm", "git", "docker", "python",
              "true", "false", "none", "self", "args", "kwargs", "init"}
    return term.lower() not in reject


def learn_synonyms_from_corpus(documents: list[str], min_cooccurrence: int = 3) -> dict:
    """
    Découvre des synonymes candidats par cooccurrence dans le même document.
    Les termes techniques qui apparaissent ensemble régulièrement sont
    probablement liés sémantiquement.

    Args:
        documents:        Liste de textes de documents indexés.
        min_cooccurrence: Nombre minimum de co-occurrences pour former une paire.

    Returns:
        Dictionnaire {terme: [synonymes candidats]} sauvegardé dans learned_vocabulary.json.
    """
    import re
    from collections import defaultdict, Counter

    # Pattern pour termes techniques Oil & Gas
    tech_pattern = re.compile(
        r'\b(?:PSV|PRV|ESD|SIS|SIL|PFD|HMB|EPC|FEED|HAZOP|ATEX|'
        r'(?:[A-Z]{1,4}-\d{2,5}[A-Z]?)|'
        r'(?:API|ASME|ISO|EN|IEC|NFPA|ASTM)\s*\d[\w\-\.]*)\b'
    )

    cooccurrence: dict = defaultdict(Counter)

    for doc in documents:
        terms_found = list(dict.fromkeys(tech_pattern.findall(doc)))
        for i, t1 in enumerate(terms_found):
            for t2 in terms_found[i + 1:i + 10]:  # Fenêtre de 10 termes
                if t1 != t2:
                    cooccurrence[t1][t2] += 1
                    cooccurrence[t2][t1] += 1

    synonyms = {}
    for term, counts in cooccurrence.items():
        candidates = [t for t, c in counts.most_common(5) if c >= min_cooccurrence]
        if candidates:
            synonyms[term] = candidates

    # Sauvegarder
    LEARNED_VOCAB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEARNED_VOCAB_PATH, 'w', encoding='utf-8') as f:
        json.dump(synonyms, f, ensure_ascii=False, indent=2)

    # Invalider le cache pour forcer le rechargement
    global _learned_cache
    _learned_cache = None

    logger.info("Synonymes appris depuis le corpus : %d termes", len(synonyms))
    return synonyms


def _compute_idf(num_docs: int, doc_freq: int) -> float:
    """Compute standard IDF: log(N / df)."""
    if doc_freq == 0:
        return 0.0
    return math.log(num_docs / doc_freq)
