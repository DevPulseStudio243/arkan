# ============================================================
#  DEERFLOW LITE - Extraction d'entités Oil & Gas
#  Regex entity extraction avec filtrage anti-pollution
#  + Compréhension sémantique des requêtes KB
# ============================================================

import re
import json
import logging
from pathlib import Path
from config import KNOWLEDGE_DB_PATH

import threading
logger = logging.getLogger(__name__)

# ── Décodeur de types d'équipements Oil & Gas ──────────────
_EQUIPMENT_TYPE_DESCRIPTIONS = {
    "K": "Compresseur",
    "C": "Colonne / Absorbeur",
    "E": "Échangeur de chaleur",
    "V": "Vessel / Ballon / Séparateur",
    "P": "Pompe",
    "T": "Réservoir / Bac",
    "H": "Chauffe / Réchauffeur",
    "R": "Réacteur",
    "F": "Filtre / Stripper",
    "D": "Dryer / Sécheur",
    "L": "Ligne / Tuyauterie",
    "M": "Mélangeur",
    "S": "Silencieux / Scrubber",
    "FA": "Filtre Anti-retour",
    "PSV": "Soupape de sécurité (PSV)",
    "PSE": "Disque de rupture (PSE)",
    "XV": "Vanne d'arrêt d'urgence (XV)",
    "SDV": "Vanne de sécurité (SDV)",
    "BDV": "Vanne de dépressurisation (BDV)",
    "ESD": "Arrêt d'urgence (ESD)",
    "ESDV": "Vanne d'arrêt d'urgence (ESDV)",
    "FV": "Vanne de régulation de débit (FV)",
    "TV": "Vanne de régulation de température (TV)",
    "PV": "Vanne de régulation de pression (PV)",
    "LV": "Vanne de régulation de niveau (LV)",
    "FIT": "Transmetteur de débit (FIT)",
    "PIT": "Transmetteur de pression (PIT)",
    "LIT": "Transmetteur de niveau (LIT)",
    "TIT": "Transmetteur de température (TIT)",
}

def _get_equipment_description(tag: str) -> str:
    """Déduit la description d'un équipement depuis son tag."""
    tag_upper = tag.upper().strip()
    # Tester les préfixes multi-lettres en premier (PSV, SDV...)
    for prefix in sorted(_EQUIPMENT_TYPE_DESCRIPTIONS.keys(), key=len, reverse=True):
        if tag_upper.startswith(prefix):
            return _EQUIPMENT_TYPE_DESCRIPTIONS[prefix]
    return ""


# Verrou pour les operations sur la KB
_KB_LOCK = threading.Lock()

# ── Sources exclues (pollution KB) ──────────────────────────

EXCLUDED_PATTERNS = [
    r"README",
    r"CLAUDE",
    r"SETUP",
    r"GUARDRAILS",
    r"SKILL",
    r"titanic",
    r"\.md$",
    r"\.txt$",
    r"package\.json",
    r"node_modules",
    r"__pycache__",
    r"\.git",
    r"\.env",
]


def _is_from_excluded_source(filename: str) -> bool:
    """Vérifie si un fichier est une source à exclure de la KB."""
    if not filename:
        return True
    for pattern in EXCLUDED_PATTERNS:
        if re.search(pattern, filename, re.IGNORECASE):
            return True
    return False


# ── Patterns d'extraction ───────────────────────────────────

ENTITY_PATTERNS = {
    "equipment_tag": [
        # Tags standard Oil & Gas: P-101, V-301A, E-201, K-401, etc.
        r"\b([PVEKCTDFHRLMS]-\d{3,4}[A-Z]?(?:/[A-Z])?)\b",
        # Tags avec préfixe numérique: 21-P-101
        r"\b(\d{2}-[PVEKCTDFHRLMS]-\d{3,4}[A-Z]?)\b",
        # Tags multi-lettres: PSV-101, XV-301, SDV-100, FIT-201, PIT-301, etc.
        r"\b((?:ESD|ESDV|PSV|PSE|XV|SDV|BDV|RD|FA|FV|TV|PV|LV|HV|FIT|PIT|LIT|TIT|AIT|PDT|FIC|PIC|LIC|TIC|AIC|PIR|TIR|FIR|LIR|AIR|PSHH|PSLL|LSHH|LSLL|TSH|TSL|PSH|PSL|LSH|LSL|FSH|FSL)-?\d{3,5}[A-Z]?(?:/[A-Z])?)\b",
        # Tags avec préfixe numérique + multi-lettres: 21-PSV-101
        r"\b(\d{2}-(?:ESD|ESDV|PSV|PSE|XV|SDV|BDV|FIT|PIT|LIT|TIT|AIT|FV|TV|PV|LV|HV)-?\d{3,5}[A-Z]?)\b",
    ],
    "pressure": [
        r"(\d+(?:\.\d+)?\s*(?:bar[ag]?|psi[ag]?|kPa|MPa|kg/cm2))\b",
        r"(?:pression|pressure)\s*(?:de\s+)?(?:design|opér|oper|max|min|test)\w*\s*[:=]?\s*(\d+(?:\.\d+)?\s*(?:bar[ag]?|psi[ag]?|kPa|MPa))",
    ],
    "temperature": [
        r"(\-?\d+(?:\.\d+)?\s*°[CF])\b",
        r"(?:température|temperature)\s*(?:de\s+)?(?:design|opér|oper|max|min)\w*\s*[:=]?\s*(\-?\d+(?:\.\d+)?\s*°[CF])",
    ],
    "flow_rate": [
        r"(\d+(?:\.\d+)?\s*(?:m3/h|m³/h|l/min|kg/h|t/h|MMSCFD|BOPD|GPM))\b",
    ],
    "norm_standard": [
        r"\b((?:API|ASME|ASTM|ISO|EN|NF|IEC|NFPA|ATEX)\s*\d+[\w\-\.]*)\b",
        r"\b((?:TEMA|EJMA|PED|DESP)\s*[\d\w\-\.]*)\b",
    ],
    "document_number": [
        r"\b(D-\d{3}-\d{4}-\d{3})\b",
        r"\b([A-Z]{2,4}-\d{4,6}-\d{2,4})\b",
    ],
    "material": [
        r"\b((?:ASTM|SA|A)\s*\d{3,4}(?:\s*Gr\.?\s*\w+)?)\b",
        r"\b((?:SS|CS)\s*\d{3}[A-Z]?)\b",
        r"\b((?:Inconel|Monel|Hastelloy|Duplex|Super\s*Duplex)\s*\d*)\b",
    ],
    "pipe_class": [
        r"\b(Class\s+\d{3,4})\b",
        r"\b([A-Z]\d[A-Z]-\d{2,4})\b",
    ],
    "dimension": [
        r'(\d+(?:\.\d+)?(?:\s*"|\'|\s*inch(?:es)?|\s*mm|\s*DN\s*\d+))\b',
        r"\b(DN\s*\d+)\b",
        r"\b(NPS\s*\d+(?:\.\d+)?)\b",
    ],
    "hardness": [
        r"\b(\d+)\s*(?:hb|hrc|hcv)\b",
        r"\b(?:dureté|hardness)\b.*?\b(\d+)\s*(?:hb|hrc)\b",
    ],
}


def extract_entities(text: str) -> dict:
    """
    Extrait les entités techniques d'un texte Oil & Gas.
    Retourne {entity_type: [list of matches]}
    """
    results = {}
    for entity_type, patterns in ENTITY_PATTERNS.items():
        matches = set()
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                # Prendre le premier groupe capturant non-None
                value = None
                for g in match.groups():
                    if g is not None:
                        value = g.strip()
                        break
                if value:
                    matches.add(value)
        if matches:
            results[entity_type] = sorted(matches)
    return results


def extract_equipment_tags(text: str) -> list:
    """Extraction rapide des tags équipement uniquement."""
    tags = set()
    for pattern in ENTITY_PATTERNS["equipment_tag"]:
        for match in re.finditer(pattern, text):
            for g in match.groups():
                if g:
                    tags.add(g.strip())
    return sorted(tags)


# ── Knowledge Base ──────────────────────────────────────────

def load_kb() -> list:
    """Charge la knowledge base depuis le fichier JSON."""
    with _KB_LOCK:
        try:
            path = Path(KNOWLEDGE_DB_PATH)
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            return []
        except Exception as e:
            logger.error(f"Erreur chargement KB: {e}")
            return []


def save_to_kb(entities: dict, source_file: str, context_snippet: str = ""):
    """
    Sauvegarde les entités dans la KB avec filtrage anti-pollution.
    Refuse les entrées provenant de sources exclues.
    """
    if _is_from_excluded_source(source_file):
        logger.info(f"Source exclue de la KB: {source_file}")
        return

    with _KB_LOCK:
        kb = []
        # Re-charger la KB a l'interieur du lock pour eviter de perdre des donnees
        try:
            path = Path(KNOWLEDGE_DB_PATH)
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    kb = json.load(f)
        except Exception:
            pass

        changed = False
        for entity_type, values in entities.items():
            for value in values:
                exists = any(
                    e.get("value") == value
                    and e.get("type") == entity_type
                    and e.get("source") == source_file
                    for e in kb
                )
                if not exists:
                    kb.append({
                        "type": entity_type,
                        "value": value,
                        "source": source_file,
                        "context": context_snippet[:200] if context_snippet else "",
                    })
                    changed = True

        if not changed:
            return

        for _retry in range(3):
            try:
                tmp_path = Path(str(KNOWLEDGE_DB_PATH) + '.tmp')
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(kb, f, ensure_ascii=False, indent=2)
                
                if Path(KNOWLEDGE_DB_PATH).exists():
                    try:
                        tmp_path.replace(KNOWLEDGE_DB_PATH)
                    except OSError:
                        import time as _time
                        _time.sleep(0.1)
                        tmp_path.replace(KNOWLEDGE_DB_PATH)
                else:
                    tmp_path.replace(KNOWLEDGE_DB_PATH)
                break
            except Exception as e:
                if _retry == 2:
                    logger.error(f"KB save error after 3 retries: {e}")
                import time as _time
                _time.sleep(0.2)


# ── Compréhension sémantique des requêtes ──────────────────

# Mapping : mots-clés d'intention → types d'entités KB concernés
_INTENT_TO_KB_TYPES = {
    # Quand l'utilisateur parle d'équipements en général
    "equipment": {
        "keywords": [
            "equipement", "équipement", "equipment", "machine", "appareil",
            "compresseur", "compressor", "pompe", "pump", "échangeur",
            "exchanger", "ballon", "vessel", "drum", "séparateur",
            "separator", "réservoir", "tank", "colonne", "column",
            "turbine", "réacteur", "reactor", "chaudière", "boiler",
            "filtre", "filter", "vanne", "valve", "tag",
        ],
        "kb_types": ["equipment_tag"],
    },
    # Quand l'utilisateur parle de normes / standards
    "norms": {
        "keywords": [
            "norme", "standard", "code", "réglementation", "regulation",
            "api", "asme", "astm", "iso", "iec", "nfpa", "atex", "en",
            "conformité", "compliance", "certification",
        ],
        "kb_types": ["norm_standard"],
    },
    # Quand l'utilisateur parle de matériaux
    "materials": {
        "keywords": [
            "matériau", "materiaux", "material", "acier", "steel",
            "inox", "alliage", "alloy", "inconel", "monel", "duplex",
            "revêtement", "coating", "peinture", "painting",
        ],
        "kb_types": ["material"],
    },
    # Quand l'utilisateur parle de conditions opératoires
    "conditions": {
        "keywords": [
            "pression", "pressure", "température", "temperature",
            "débit", "flow", "condition", "opératoire", "operating",
            "design", "service",
        ],
        "kb_types": ["pressure", "temperature", "flow_rate"],
    },
    # Quand l'utilisateur parle de tuyauterie / dimensions
    "piping": {
        "keywords": [
            "tuyauterie", "piping", "pipe", "ligne", "line",
            "diamètre", "diameter", "dimension", "taille", "size",
            "classe", "class", "bride", "flange",
        ],
        "kb_types": ["pipe_class", "dimension"],
    },
    # Quand l'utilisateur parle de documents
    "documents": {
        "keywords": [
            "document", "référence", "reference", "numéro", "number",
            "plan", "dessin", "drawing", "fiche", "datasheet",
            "rapport", "report",
        ],
        "kb_types": ["document_number"],
    },
    # Question générale sur le projet → tout montrer
    "project": {
        "keywords": [
            "projet", "project", "installation", "unité", "unit",
            "usine", "plant", "site", "boosting", "ldbp",
            "tout", "tous", "toutes", "résumé", "summary",
            "vue d'ensemble", "overview", "général", "general",
        ],
        "kb_types": ["equipment_tag", "norm_standard", "pressure",
                      "temperature"],
    },
}


def _detect_query_intent(query: str) -> list:
    """
    Détecte l'intention sémantique d'une requête.
    Retourne les types KB à consulter.
    """
    q_lower = query.lower()
    matched_types = set()

    for intent_name, intent_config in _INTENT_TO_KB_TYPES.items():
        for keyword in intent_config["keywords"]:
            if keyword in q_lower:
                matched_types.update(intent_config["kb_types"])
                break  # Un seul match par catégorie suffit

    return list(matched_types)


def build_kb_context(query: str) -> str:
    """
    Construit un contexte à partir de la KB pour enrichir la recherche.

    Fonctionne en deux modes :
    1. Mode précis : si la requête contient des entités spécifiques (V-101, API 520),
       retourne les infos KB pour ces entités exactes.
    2. Mode sémantique : si la requête exprime une intention (lister les équipements,
       quelles normes, etc.), retourne toutes les entités KB du type demandé.

    Filtre les entrées provenant de sources exclues.
    """
    kb = load_kb()
    if not kb:
        return ""

    relevant = []

    # ── Mode 1 : Recherche par entités exactes ──────────────
    query_entities = extract_entities(query)
    query_tags = set()
    for values in query_entities.values():
        query_tags.update(v.upper() for v in values)

    if query_tags:
        for entry in kb:
            if _is_from_excluded_source(entry.get("source", "")):
                continue
            if entry.get("value", "").upper() in query_tags:
                relevant.append(entry)

    # ── Mode 2 : Recherche par intention sémantique ─────────
    if not relevant:
        intended_types = _detect_query_intent(query)

        if intended_types:
            # Collecter les entités KB des types demandés
            seen_values = set()  # Dédupliquer par valeur
            for entry in kb:
                if _is_from_excluded_source(entry.get("source", "")):
                    continue
                entry_type = entry.get("type", "")
                entry_value = entry.get("value", "")

                if entry_type in intended_types and entry_value not in seen_values:
                    # Filtrer les faux positifs (codes FWBS A100/A200 ne sont pas des matériaux)
                    if entry_type == "material" and re.match(r"^A\d{3}$", entry_value):
                        continue
                    # Filtrer "pedestrians"/"Pedestal" comme norme
                    if entry_type == "norm_standard" and entry_value.lower() in (
                        "pedestrians", "pedestal",
                    ):
                        continue

                    seen_values.add(entry_value)
                    relevant.append(entry)

            logger.info(
                "KB sémantique: intention=%s, %d entités trouvées",
                intended_types, len(relevant),
            )

    if not relevant:
        return ""

    # ── Formatage du contexte KB ────────────────────────────
    # Grouper par type pour une lecture claire
    by_type = {}
    for entry in relevant:
        etype = entry.get("type", "other")
        by_type.setdefault(etype, []).append(entry)

    _TYPE_LABELS = {
        "equipment_tag": "Équipements du projet",
        "norm_standard": "Normes et standards applicables",
        "material": "Matériaux",
        "pressure": "Pressions",
        "temperature": "Températures",
        "flow_rate": "Débits",
        "pipe_class": "Classes de tuyauterie",
        "dimension": "Dimensions",
        "hardness": "Duretés",
        "document_number": "Documents de référence",
    }

    lines = ["[Informations extraites des documents du projet]"]

    for etype, entries in by_type.items():
        label = _TYPE_LABELS.get(etype, etype)
        lines.append(f"\n{label}:")

        # Limiter à 20 entrées par type, dédupliquées
        shown = set()
        count = 0
        for entry in entries:
            val = entry.get("value", "")
            if val in shown or count >= 20:
                continue
            shown.add(val)
            count += 1

            source = entry.get("source", "N/A")

            # Pour les équipements, ajouter la description déduite du tag
            if etype == "equipment_tag":
                eq_desc = _get_equipment_description(val)
                if eq_desc:
                    lines.append(f"  - {val} : {eq_desc} (source: {source})")
                else:
                    lines.append(f"  - {val} (source: {source})")
            else:
                # Pour les autres types, inclure un extrait court du contexte
                ctx = entry.get("context", "")
                if ctx:
                    # Nettoyer et tronquer à 120 caractères
                    ctx_clean = ctx.replace("\n", " ").strip()
                    ctx_clean = re.sub(r"\s+", " ", ctx_clean)  # Comprimer les espaces
                    if len(ctx_clean) > 120:
                        ctx_clean = ctx_clean[:120] + "..."
                    lines.append(f"  - {val} (source: {source}) — {ctx_clean}")
                else:
                    lines.append(f"  - {val} (source: {source})")

    return "\n".join(lines)
