# -*- coding: utf-8 -*-
"""
config_loader.py  (version corrigée – audit ARKAN v3)

Corrections par rapport à la version auditée :
  1. YAML présent mais invalide  -> ConfigError (plus de repli silencieux sur des valeurs en dur).
     YAML absent                 -> valeurs NEUTRES (aucune donnée client, aucune marge inventée)
                                    + avertissement + source "DEFAULTS" exposée à l'export Excel.
     Variable ARKAN_CONFIG_STRICT=1 : un YAML absent est aussi une erreur.
  2. Marges par CATÉGORIE d'article (`procurement_margins.by_category`), pas par sous-chaîne
     du nom de discipline. Les anciennes clés plates (cables_power, cable_trays, …) restent lues.
  3. Une marge non définie renvoie (0.0, False) : l'appelant la signale (A_VALIDER) au lieu
     d'appliquer 5 % par défaut.
  4. Arrondi des quantités unitaires (EA) : au plus proche par défaut, jamais « +1 » automatique.
  5. Rechargement automatique si le fichier change (mtime) ; copie profonde renvoyée.
  6. Chemin configurable : variable ARKAN_PROJECT_CONFIG ou argument `path`.
  7. Empreinte (sha256) + version de schéma exposées via get_config_info().
"""

import copy
import hashlib
import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger("config_loader")

SCHEMA_VERSION = 2
ENV_PATH = "ARKAN_PROJECT_CONFIG"
ENV_STRICT = "ARKAN_CONFIG_STRICT"

UNIT_COUNT = {"EA", "U", "PCS", "NR", "PC", "UN"}


class ConfigError(Exception):
    pass


# Valeurs NEUTRES : rien de client, aucune marge supposée.
NEUTRAL_DEFAULTS: Dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "project_metadata": {"project_id": "", "project_name": "", "client": "", "revision_default": "0"},
    "paths": {},
    "thresholds": {"confidence_min_threshold": 0.85, "confidence_warning_threshold": 0.70,
                   "dwg_conversion_timeout_sec": 60, "dwg_max_entities_memory_cap": 100000},
    "procurement_margins": {"by_category": {}, "default": None, "rounding": {"EA": "nearest"}},
    "normative_rules": {},
    "synonyms_dictionary": {},
    "tag_normalization": {"default_unit_prefix": "", "valid_equipment_types": [], "aliases": {}},
    # Extraction CAD / SLD : noms de calques et motifs propres à chaque projet (modifiables, jamais inventés par le code)
    "ie_extraction": {
        "layers": {
            "cable_tray": ["CABLETRAY", "CHEMIN DE CABLE", "CHEMIN DE CBLE"],
            "earthing": ["MALT", "TERRE", "EARTH"],
            "conduit": ["FOURREAU", "BUSE"],
            "ignore_text": ["LEGENDE", "LEGEND", "CARTOUCHE", "TITLE", "TABLEAU"],
        },
        "assumed_units": None,                     # "mm" | "cm" | "m" | "in" | "ft" : seulement si $INSUNITS = 0
        "skip_hidden_layers": True,
        "tray_drawing_convention": "auto",         # auto | double_rail | single_line
        "tray_width_range_mm": [50, 800],
        "annotation_radius_m": 5.0,
        "tag_match_radius_m": 5.0,
        "pull_box_cluster_radius_m": 1.5,
        "pull_box_block_patterns": ["CHAMBRE", "PULL", "REGARD"],
        "pull_box_tag_regex": r"\b\d{2,4}-EL-\d{2,5}\b",
        "earth_rod_block_patterns": ["PIQUET", "EARTH_ROD", "ROD"],
        "earthing_default_section_mm2": None,      # section supposée si non annotée (la ligne reste « à valider »)
        "sld_tag_patterns": [r"\b(?:\d{2,4}-[A-Z0-9][A-Z0-9\-_]*)\b", r"\b(?:TRP|UPS|TGBT|MCC)-\d+\b",
                             r"\bQF\d+\b", r"\b[A-Z]{1,3}-\d{2,5}[A-Z]?\b"],
        "reference_weights": {},                   # ex. {"pull_box_kg": 320, "tgbt_cell_kg": 600} : fiches constructeur
    },
    "router": {"max_upload_mb": 200, "preview_dpi": 150, "preview_max_pages": 25, "output_ttl_hours": 24,
               "max_export_items": 50000},
}

# Anciennes clés plates -> catégories d'article
LEGACY_MARGIN_KEYS = {
    "cables_power": ("CABLE_POWER",),
    "cables_control": ("CABLE_CONTROL",),
    "cables_instrumentation": ("CABLE_INSTRUMENT",),
    "bare_copper_earthing": ("EARTHING",),
    "cable_trays": ("CABLE_TRAY",),
    "conduits_pvc": ("CONDUIT",),
    "lighting_luminaires": ("LIGHTING",),
    "lighting_bulbs": ("LIGHTING_SPARES",),
    "accessories_hardware": ("HARDWARE",),
}

# Catégories d'article (extracteurs) -> clé de marge
CATEGORY_TO_MARGIN_KEY = {
    "CABLE": "CABLE_POWER", "CABLE_POWER": "CABLE_POWER", "CABLE_CONTROL": "CABLE_CONTROL",
    "CABLE_INSTRUMENT": "CABLE_INSTRUMENT", "CABLE_INSTRUMENTATION": "CABLE_INSTRUMENT",
    "CABLE_TRAY": "CABLE_TRAY", "CHEMIN_CABLE": "CABLE_TRAY", "CDC": "CABLE_TRAY",
    "CONDUIT": "CONDUIT", "BUSE": "CONDUIT", "FOURREAU": "CONDUIT",
    "EARTHING": "EARTHING", "MALT": "EARTHING", "TERRE": "EARTHING",
    "LIGHTING": "LIGHTING", "ECLAIRAGE": "LIGHTING",
    "BOLT": "HARDWARE", "BOLTS": "HARDWARE", "FASTENERS": "HARDWARE", "ACCESSORY": "HARDWARE",
}

# Disciplines -> clé de marge, utilisé seulement si la catégorie est inconnue
DISCIPLINE_TO_MARGIN_KEY = {
    "CARNET_DE_CABLES": "CABLE_POWER",
    "RESEAU_TERRE_FOUDRE": "EARTHING",
    "ECLAIRAGE_ET_PRISES": "LIGHTING",
    "BOLT": "HARDWARE",
}

# Équipements commandés à l'unité exacte : marge 0 % par défaut (pièces de rechange sur ligne séparée).
EQUIPMENT_ZERO_MARGIN = {
    "PULL_BOX", "SWITCHGEAR_FEEDER", "PANEL", "TGBT", "MCC", "UPS", "CELLULE_MT", "JUNCTION_BOX",
    "INSTRUMENT", "INSTRUMENTS", "TRANSMITTER", "INDICATOR", "SWITCH", "PRIMARY_ELEMENT",
    "CONTROL_VALVE", "SAFETY_VALVE", "TRANSFORMER",
}


# ------------------------------------------------------------------ chemin, chargement
def get_config_path(path: Optional[str] = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get(ENV_PATH)
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "project_config.yaml"


_CACHE: Dict[str, Dict[str, Any]] = {}   # clé: chemin résolu -> {mtime, cfg, info}


def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate_config(cfg: Dict[str, Any]) -> List[str]:
    """Retourne la liste des erreurs (vide si valide)."""
    errs: List[str] = []
    if not isinstance(cfg, dict):
        return ["la racine du YAML doit être un dictionnaire"]

    pm = cfg.get("procurement_margins") or {}
    if not isinstance(pm, dict):
        errs.append("procurement_margins doit être un dictionnaire")
    else:
        for k, v in pm.items():
            if k in ("by_category", "default", "rounding"):
                continue
            if not _is_num(v) or not 0.0 <= float(v) <= 0.5:
                errs.append(f"procurement_margins.{k} = {v!r} : attendu un nombre entre 0 et 0.5 (ex. 0.08 pour 8 %)")
        for k, v in (pm.get("by_category") or {}).items():
            if not _is_num(v) or not 0.0 <= float(v) <= 0.5:
                errs.append(f"procurement_margins.by_category.{k} = {v!r} : attendu entre 0 et 0.5")
        d = pm.get("default")
        if d is not None and (not _is_num(d) or not 0.0 <= float(d) <= 0.5):
            errs.append(f"procurement_margins.default = {d!r} : null ou entre 0 et 0.5")
        for u, mode in (pm.get("rounding") or {}).items():
            if mode not in ("nearest", "ceil", "none"):
                errs.append(f"procurement_margins.rounding.{u} = {mode!r} : nearest | ceil | none")

    th = cfg.get("thresholds") or {}
    for k in ("confidence_min_threshold", "confidence_warning_threshold"):
        if k in th and (not _is_num(th[k]) or not 0.0 <= float(th[k]) <= 1.0):
            errs.append(f"thresholds.{k} = {th[k]!r} : attendu entre 0 et 1")
    if _is_num(th.get("confidence_min_threshold")) and _is_num(th.get("confidence_warning_threshold")):
        if th["confidence_warning_threshold"] > th["confidence_min_threshold"]:
            errs.append("thresholds.confidence_warning_threshold doit être <= confidence_min_threshold")

    ie = cfg.get("ie_extraction") or {}
    if ie.get("tray_drawing_convention", "auto") not in ("auto", "double_rail", "single_line"):
        errs.append("ie_extraction.tray_drawing_convention : auto | double_rail | single_line")
    if ie.get("assumed_units") not in (None, "mm", "cm", "m", "in", "ft"):
        errs.append("ie_extraction.assumed_units : null | mm | cm | m | in | ft")
    for k in ("annotation_radius_m", "tag_match_radius_m", "pull_box_cluster_radius_m"):
        if k in ie and (not _is_num(ie[k]) or float(ie[k]) <= 0):
            errs.append(f"ie_extraction.{k} = {ie[k]!r} : nombre > 0 attendu")
    twr = ie.get("tray_width_range_mm")
    if twr is not None and not (isinstance(twr, (list, tuple)) and len(twr) == 2 and all(_is_num(x) for x in twr) and twr[0] < twr[1]):
        errs.append("ie_extraction.tray_width_range_mm : [min, max] avec min < max")
    rt = cfg.get("router") or {}
    for k in ("max_upload_mb", "preview_dpi", "preview_max_pages", "output_ttl_hours", "max_export_items"):
        if k in rt and (not _is_num(rt[k]) or float(rt[k]) <= 0):
            errs.append(f"router.{k} = {rt[k]!r} : nombre > 0 attendu")

    for sec, rule in (cfg.get("normative_rules") or {}).items():
        if not isinstance(rule, dict):
            continue
        for k, v in rule.items():
            if "ratio" in k and (not _is_num(v) or not 0.0 < float(v) <= 1.0):
                errs.append(f"normative_rules.{sec}.{k} = {v!r} : ratio attendu dans ]0, 1]")
    return errs


def _info(source: str, raw_bytes: bytes, cfg: Dict[str, Any], warning: str = "") -> Dict[str, Any]:
    return {
        "source": source,
        "sha256": hashlib.sha256(raw_bytes).hexdigest()[:12] if raw_bytes else "",
        "schema_version": cfg.get("schema_version", 1),
        "warning": warning,
    }


def _load(path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if not path.exists():
        if os.environ.get(ENV_STRICT) == "1":
            raise ConfigError(f"Fichier de configuration introuvable : {path}")
        msg = (f"project_config.yaml introuvable ({path}) : valeurs NEUTRES utilisées, aucune marge "
               f"définie. Les lignes concernées seront marquées « à valider ».")
        logger.error(msg)
        cfg = copy.deepcopy(NEUTRAL_DEFAULTS)
        return cfg, _info("DEFAULTS", b"", cfg, warning=msg)

    raw = path.read_bytes()
    try:
        loaded = yaml.safe_load(raw.decode("utf-8")) or {}
    except Exception as exc:
        raise ConfigError(f"YAML illisible ({path}) : {exc}") from exc
    errs = validate_config(loaded)
    if errs:
        raise ConfigError(f"Configuration invalide ({path}) :\n - " + "\n - ".join(errs))
    cfg = _deep_merge(NEUTRAL_DEFAULTS, loaded)
    unknown = sorted(set(loaded) - set(NEUTRAL_DEFAULTS))
    warn = f"clés de premier niveau inconnues ignorées : {unknown}" if unknown else ""
    if warn:
        logger.warning(warn)
    return cfg, _info(str(path), raw, cfg, warning=warn)


def load_project_config(force_reload: bool = False, path: Optional[str] = None) -> Dict[str, Any]:
    p = get_config_path(path)
    key = str(p.resolve()) if p.exists() else str(p)
    mtime = p.stat().st_mtime if p.exists() else None
    entry = _CACHE.get(key)
    if entry is None or force_reload or entry["mtime"] != mtime:
        cfg, info = _load(p)
        entry = {"mtime": mtime, "cfg": cfg, "info": info}
        _CACHE[key] = entry
        logger.info("Configuration chargée : %s (sha256=%s)", info["source"], info["sha256"])
    load_project_config._last_key = key  # type: ignore[attr-defined]
    return copy.deepcopy(entry["cfg"])


def get_config_info(path: Optional[str] = None) -> Dict[str, Any]:
    """Source, empreinte, version de schéma et avertissement éventuel (à imprimer dans l'Excel)."""
    load_project_config(path=path)
    return copy.deepcopy(_CACHE[load_project_config._last_key]["info"])  # type: ignore[attr-defined]


def get_threshold(name: str, default: Optional[float] = None) -> Optional[float]:
    v = (load_project_config().get("thresholds") or {}).get(name, default)
    return v


# ------------------------------------------------------------------ marges
def effective_margins(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    cfg = cfg or load_project_config()
    pm = cfg.get("procurement_margins") or {}
    out: Dict[str, float] = {}
    for legacy, cats in LEGACY_MARGIN_KEYS.items():          # anciennes clés plates
        if legacy in pm and _is_num(pm[legacy]):
            for c in cats:
                out[c] = float(pm[legacy])
    for k, v in (pm.get("by_category") or {}).items():       # nouveau format prioritaire
        out[str(k).upper()] = float(v)
    if "CONDUIT" in out:                                      # buses/fourreaux suivent les conduits
        out.setdefault("BUSE", out["CONDUIT"])
    return out


def resolve_margin(category: Optional[str], discipline: Optional[str] = None,
                   cable_kind: Optional[str] = None) -> Tuple[float, bool]:
    """
    Retourne (marge, definie).  definie=False -> l'appelant doit signaler la ligne (A_VALIDER).
    Ordre : catégorie exacte -> clé associée -> type de câble -> discipline -> défaut explicite
    -> équipement (0 %) -> non défini.
    """
    cfg = load_project_config()
    margins = effective_margins(cfg)
    cat = str(category or "").upper().strip()

    if cat in margins:
        return margins[cat], True
    key = CATEGORY_TO_MARGIN_KEY.get(cat)
    if cat in ("CABLE", "CABLE_POWER") and cable_kind:
        key = {"CONTROL": "CABLE_CONTROL", "INSTRUMENT": "CABLE_INSTRUMENT",
               "INSTRUMENTATION": "CABLE_INSTRUMENT"}.get(str(cable_kind).upper(), key)
    if key and key in margins:
        return margins[key], True
    dkey = DISCIPLINE_TO_MARGIN_KEY.get(str(discipline or "").upper())
    if not key and dkey and dkey in margins:
        return margins[dkey], True
    default = (cfg.get("procurement_margins") or {}).get("default")
    if default is not None:
        return float(default), True
    if cat in EQUIPMENT_ZERO_MARGIN:
        return 0.0, True
    return 0.0, False


def get_margin_for_category(category: str) -> float:
    """Compatibilité : renvoie seulement la marge (0.0 si non définie). Préférer resolve_margin."""
    return resolve_margin(category, discipline=category)[0]


def apply_margin(q_net: float, margin: float, unit: Optional[str]) -> float:
    """Quantité à commander. Unités entières : arrondi au plus proche (par défaut) des pièces de rechange."""
    q_net = float(q_net or 0.0)
    if margin <= 0 or q_net <= 0:
        return round(q_net, 2)
    u = str(unit or "EA").upper().strip()
    if u in UNIT_COUNT:
        mode = ((load_project_config().get("procurement_margins") or {}).get("rounding") or {}).get("EA", "nearest")
        spares = q_net * margin
        if mode == "ceil":
            spares = math.ceil(spares - 1e-9)
        elif mode == "none":
            return round(q_net + spares, 2)
        else:
            spares = math.floor(spares + 0.5)
        return float(q_net + spares)
    return round(q_net * (1.0 + margin), 2)


def get_section(name: str) -> Dict[str, Any]:
    """Section de la config (copie), ex. get_section("ie_extraction")."""
    return copy.deepcopy(load_project_config().get(name) or {})
