# -*- coding: utf-8 -*-
"""
tag_normalizer.py  (version corrigée – audit ARKAN v3)

Normalisation et appariement des TAGs techniques d'ingénierie EPC.

Corrections par rapport à la version auditée :
  1. Le préfixe d'unité est CONSERVÉ : 300-P-101A != 400-P-101A.
     Un tag sans préfixe reste apparié à un tag avec préfixe (score réduit).
  2. Plus de fuzzy sur des tags structurés : FV-0102 != FV-0103, PT-0102 != PT-0103.
     Le fuzzy n'est utilisé que si un des tags n'est pas décomposable, et
     jamais si les chiffres diffèrent.
  3. Le préfixe câble (C-/CBL-/W-) n'est retiré que pour un VRAI tag câble
     (ex. C-300-P-101A-PWR). `K-101` et `C-101A` (compresseurs) restent intacts.
  4. Les alias viennent de la config projet (tag_normalization.aliases), plus
     de données client codées en dur.
  5. `valid_equipment_types` est l'UNION de la liste par défaut et de la config :
     la config ne supprime plus les types d'instrumentation.
  6. Plus d'instanciation au chargement du module (singleton paresseux).
"""

import re
import difflib
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_EQUIPMENT_TYPES = (
    "P", "C", "K", "TRP", "UPS", "TGBT", "MCC", "THVAC", "GE", "EL", "CDC", "JB", "SW",
    "PT", "TT", "FT", "LT", "FV", "PV", "XV", "MOV", "PSV", "ESDV", "UV", "TV", "PDT",
)

# Fonctions de câble reconnues en suffixe d'un tag de liaison (carnet de câbles)
CABLE_FUNCTIONS = ("PWR", "CTL", "CMD", "SIG", "INS", "COM", "FO", "PE", "EQ")

_CABLE_TAG_RE = re.compile(
    r"^(?:C|CBL|W)-(?P<eq>.+?)-(?P<fn>(?:%s)\d{0,2})$" % "|".join(CABLE_FUNCTIONS)
)
_P_FULL = re.compile(r"^(?P<prefix>\d{2,4})-?(?P<type>[A-Z]{1,5})-?(?P<number>\d{1,5})(?P<suffix>[A-Z])?$")
_P_TYPED = re.compile(r"^(?P<type>[A-Z]{1,5})-(?P<number>\d{1,5})(?P<suffix>[A-Z])?$")
_P_COMPACT = re.compile(r"^(?P<type>[A-Z]{1,5})(?P<number>\d{2,5})(?P<suffix>[A-Z])?$")
_TAG_IN_TEXT = re.compile(r"\b(?:\d{2,4}-)?[A-Z]{1,5}-?\d{2,5}[A-Z]?\b")


def _clean(raw: Any) -> str:
    s = str(raw or "").strip().upper()
    s = re.sub(r"[\s_]+", "-", s)      # "P 101 A", "P_101A" -> "P-101-A", "P-101A"
    s = re.sub(r"-{2,}", "-", s)
    # "P-101-A" -> "P-101A" (suffixe isolé par un séparateur)
    s = re.sub(r"(\d)-([A-Z])$", r"\1\2", s)
    return s


def _empty(canonical: str, raw: str) -> Dict[str, Any]:
    return {"raw": raw, "prefix": "", "type": "", "number": "", "suffix": "",
            "canonical": canonical, "cable_function": "", "structured": False, "type_known": False}


class TagNormalizer:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if config is None:
            try:
                from config_loader import load_project_config
                config = load_project_config()
            except Exception:           # config absente : le normaliseur reste utilisable
                config = {}
        tn = (config or {}).get("tag_normalization", {}) or {}
        self.default_prefix: str = str(tn.get("default_unit_prefix") or "")
        self.valid_types = set(DEFAULT_EQUIPMENT_TYPES) | {str(t).upper() for t in (tn.get("valid_equipment_types") or [])}
        self.aliases: Dict[str, str] = {
            _clean(k): _clean(v) for k, v in (tn.get("aliases") or {}).items()
        }

    # ------------------------------------------------------------------ décomposition
    def decompose_tag(self, raw_tag: Any) -> Dict[str, Any]:
        raw = str(raw_tag or "")
        clean = _clean(raw)
        cable_function = ""

        m = _CABLE_TAG_RE.match(clean)               # ex. C-300-P-101A-PWR
        if m:
            clean, cable_function = m.group("eq"), m.group("fn")

        clean = self.aliases.get(clean, clean)

        for pattern in (_P_FULL, _P_TYPED, _P_COMPACT):
            p = pattern.match(clean)
            if p:
                g = p.groupdict()
                prefix = g.get("prefix") or ""
                typ, num, suf = g["type"], g["number"], g.get("suffix") or ""
                core = f"{typ}-{num}{suf}"
                return {
                    "raw": raw, "prefix": prefix, "type": typ, "number": num, "suffix": suf,
                    "canonical": f"{prefix}-{core}" if prefix else core,
                    "cable_function": cable_function, "structured": True,
                    "type_known": typ in self.valid_types,
                }
        d = _empty(clean, raw)
        d["cable_function"] = cable_function
        return d

    def canonical_tag(self, raw_tag: Any) -> str:
        """Forme canonique, préfixe d'unité conservé. Pour l'équipement d'un câble, tag de l'équipement."""
        return self.decompose_tag(raw_tag)["canonical"]

    def extract_tags(self, text: Any) -> List[str]:
        """Retourne les tags canoniques trouvés dans un libellé libre (ex. 'POMPE REFRIGERANT P101A')."""
        found: List[str] = []
        for tok in _TAG_IN_TEXT.findall(_clean(text)):
            d = self.decompose_tag(tok)
            if d["structured"] and d["canonical"] not in found:
                found.append(d["canonical"])
        return found

    # ------------------------------------------------------------------ appariement
    def match_tags(self, tag1: Any, tag2: Any, threshold: float = 0.90) -> Tuple[bool, float, str]:
        """
        Retourne (is_match, score, match_type).
          EXACT / ALIAS_MATCH / CANONICAL_EXACT / UNIT_PREFIX_MISSING / NUMBER_PADDING /
          PARTIAL_SUFFIX_MATCH / FUZZY_MATCH   -> match
          DIFFERENT_UNIT / DIFFERENT_TYPE / DIFFERENT_NUMBER / DIFFERENT_SUFFIX / NO_MATCH -> pas de match
        Un match avec score < 0.95 doit être traité comme « à valider » par l'appelant.
        """
        t1, t2 = str(tag1 or "").strip().upper(), str(tag2 or "").strip().upper()
        if not t1 or not t2:
            return False, 0.0, "NO_MATCH"
        if t1 == t2:
            return True, 1.0, "EXACT"

        d1, d2 = self.decompose_tag(t1), self.decompose_tag(t2)

        if d1["structured"] and d2["structured"]:
            if d1["canonical"] == d2["canonical"]:
                via_alias = _clean(t1) in self.aliases or _clean(t2) in self.aliases
                return True, (0.98 if via_alias else 0.97), ("ALIAS_MATCH" if via_alias else "CANONICAL_EXACT")
            if d1["type"] != d2["type"]:
                return False, 0.0, "DIFFERENT_TYPE"
            if d1["prefix"] and d2["prefix"] and d1["prefix"] != d2["prefix"]:
                return False, 0.0, "DIFFERENT_UNIT"
            if int(d1["number"]) != int(d2["number"]):
                return False, 0.0, "DIFFERENT_NUMBER"          # jamais de fuzzy ici
            unit_missing = not (d1["prefix"] and d2["prefix"])
            padding = d1["number"] != d2["number"]
            if d1["suffix"] and d2["suffix"] and d1["suffix"] != d2["suffix"]:
                return False, 0.0, "DIFFERENT_SUFFIX"          # P-101A != P-101B
            if not d1["suffix"] or not d2["suffix"]:
                if d1["suffix"] != d2["suffix"]:
                    return True, 0.85, "PARTIAL_SUFFIX_MATCH"  # P-101 ~ P-101A : ambigu
            if padding:
                return True, 0.90, "NUMBER_PADDING"
            if unit_missing:
                return True, 0.92, "UNIT_PREFIX_MISSING"
            return True, 0.97, "CANONICAL_EXACT"

        # Au moins un tag non structuré (libellé libre) : fuzzy prudent
        if _clean(t1) in self.aliases or _clean(t2) in self.aliases:
            a1 = self.aliases.get(_clean(t1), _clean(t1))
            a2 = self.aliases.get(_clean(t2), _clean(t2))
            if a1 == a2:
                return True, 0.98, "ALIAS_MATCH"
        c1, c2 = d1["canonical"], d2["canonical"]
        if re.findall(r"\d+", c1) != re.findall(r"\d+", c2):
            return False, 0.0, "NO_MATCH"                      # un chiffre diffère -> jamais le même objet
        ratio = difflib.SequenceMatcher(None, c1, c2).ratio()
        if ratio >= threshold:
            return True, round(ratio, 2), "FUZZY_MATCH"
        return False, round(ratio, 2), "NO_MATCH"


# ---------------------------------------------------------------------- API module
_DEFAULT_NORMALIZER: Optional[TagNormalizer] = None


def get_default_normalizer(force_reload: bool = False) -> TagNormalizer:
    global _DEFAULT_NORMALIZER
    if _DEFAULT_NORMALIZER is None or force_reload:
        _DEFAULT_NORMALIZER = TagNormalizer()
    return _DEFAULT_NORMALIZER


def normalize_tag(tag: Any) -> str:
    return get_default_normalizer().canonical_tag(tag)


def compare_tags(tag1: Any, tag2: Any, threshold: float = 0.90) -> Tuple[bool, float, str]:
    return get_default_normalizer().match_tags(tag1, tag2, threshold)
