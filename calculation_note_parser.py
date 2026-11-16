"""
calculation_note_parser.py
===========================
Parser universel pour notes de calcul électrique (Caneco BT, ETAP, Elec Calc, Excel/CSV).
Extrait les départs, longueurs de calcul, sections imposées, chutes de tension et calibres.
Conforme aux standards d'ingénierie IEC 60364 / NF C 15-100.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import openpyxl

from tag_normalizer import normalize_tag

logger = logging.getLogger("arkan.calc_note_parser")

# Synonymes de colonnes pour identification dynamique robuste
COL_SYNONYMS = {
    "tag": [
        "repere", "repère", "tag", "cable", "cable_tag", "circuit", "depart",
        "départ", "feeder", "nom_du_circuit", "identifiant"
    ],
    "source": [
        "amont", "source", "from", "origine", "tableau", "armoire", "panneau", "tgbt"
    ],
    "destination": [
        "aval", "destination", "to", "recepteur", "récepteur", "charge", "appareil"
    ],
    "section": [
        "section", "sec", "cable_section", "section_phase", "section_retenue",
        "dimension", "cross_section"
    ],
    "length": [
        "longueur", "longueur_m", "length", "len", "longueur_calcul", "l_m", "distance"
    ],
    "voltage_drop": [
        "du", "du_%", "chute_de_tension", "chute_tension", "delta_u", "delta_u_%",
        "voltage_drop", "du_pct", "chute"
    ],
    "ib": [
        "ib", "courant_emploi", "ib_a", "i_b", "i_emploi", "courant_service"
    ],
    "in_rating": [
        "in", "calibre", "disjoncteur", "i_n", "rating", "protection", "calibre_a"
    ],
    "cable_type": [
        "type", "type_cable", "nature_cable", "cable_type", "reference", "designation",
        "isolant", "spec"
    ],
    "conductor_material": [
        "ame", "âme", "metal", "conducteur", "material", "cu_al"
    ],
}


def _clean_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _normalize_header(header: str) -> str:
    """Normalise un en-tête de colonne en minuscules sans accents ni caractères spéciaux."""
    h = header.lower().strip()
    h = re.sub(r"[éèêë]", "e", h)
    h = re.sub(r"[àâä]", "a", h)
    h = re.sub(r"[ùûü]", "u", h)
    h = re.sub(r"[ôö]", "o", h)
    h = re.sub(r"[îï]", "i", h)
    h = re.sub(r"[^a-z0-9_]", "_", h)
    return re.sub(r"_+", "_", h).strip("_")


def _find_column_mapping(headers: List[str]) -> Dict[str, int]:
    """Associe chaque champ standard à l'indice de colonne correspondant."""
    norm_headers = [_normalize_header(h) for h in headers]
    mapping: Dict[str, int] = {}

    for field, synonyms in COL_SYNONYMS.items():
        for syn in synonyms:
            syn_norm = _normalize_header(syn)
            # 1. Correspondance exacte
            for idx, h in enumerate(norm_headers):
                if h == syn_norm:
                    mapping[field] = idx
                    break
            if field in mapping:
                break
        # 2. Correspondance partielle (si pas encore trouvé)
        if field not in mapping:
            for syn in synonyms:
                syn_norm = _normalize_header(syn)
                for idx, h in enumerate(norm_headers):
                    if syn_norm in h:
                        mapping[field] = idx
                        break
                if field in mapping:
                    break

    return mapping


def _parse_float(val: Any) -> Optional[float]:
    """Parse un flottant robuste (gère virgules, unités, pourcentages)."""
    if val is None:
        return None
    s = str(val).strip().replace(" ", "").replace(",", ".")
    # Nettoie %, m, A
    s = re.sub(r"[^\d\.-]", "", s)
    if not s or s == "." or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


class CalculationNoteParser:
    """Parser universel pour notes de calcul (Caneco BT / ETAP / Elec Calc)."""

    @classmethod
    def parse_file(cls, file_path: Union[str, Path]) -> List[Dict[str, Any]]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Fichier de note de calcul introuvable : {path}")

        suffix = path.suffix.lower()
        if suffix in [".xlsx", ".xlsm", ".xltx"]:
            return cls._parse_excel(path)
        elif suffix in [".csv", ".txt"]:
            return cls._parse_csv(path)
        else:
            raise ValueError(f"Format de note de calcul non supporté ({suffix}). Formats requis : .xlsx, .csv")

    @classmethod
    def _parse_excel(cls, path: Path) -> List[Dict[str, Any]]:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        # Prendre la première feuille active
        sheet = wb.active
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            return []

        # Recherche de la ligne d'en-tête (première ligne contenant un synonyme de tag ou repère)
        header_row_idx = -1
        for idx, row in enumerate(rows[:15]):  # Scanner les 15 premières lignes
            row_str = " ".join([_clean_str(c).lower() for c in row if c is not None])
            if any(syn in row_str for syn in ["repere", "repère", "circuit", "tag", "cable", "depart", "départ"]):
                header_row_idx = idx
                break

        if header_row_idx == -1:
            header_row_idx = 0

        headers = [_clean_str(c) for c in rows[header_row_idx]]
        mapping = _find_column_mapping(headers)
        if "tag" not in mapping:
            logger.warning(f"Colonne 'TAG' ou 'Repère' non identifiée dans la note de calcul {path.name}")
            return []

        results: List[Dict[str, Any]] = []
        for row in rows[header_row_idx + 1:]:
            if not row or all(c is None for c in row):
                continue
            item = cls._extract_item_from_row(row, mapping)
            if item and item.get("tag"):
                results.append(item)

        wb.close()
        logger.info(f"[CalcNoteParser] {len(results)} départs extraits de {path.name} (Excel)")
        return results

    @classmethod
    def _parse_csv(cls, path: Path) -> List[Dict[str, Any]]:
        # Détection de l'encodage et délimiteur
        encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
        content = None
        for enc in encodings:
            try:
                content = path.read_text(encoding=enc)
                break
            except UnicodeDecodeError:
                continue

        if not content:
            raise ValueError(f"Impossible de lire le fichier CSV {path.name} avec les encodages testés.")

        # Détection délimiteur (; ou , ou \t)
        first_lines = "\n".join(content.splitlines()[:5])
        dialect = ";" if first_lines.count(";") >= first_lines.count(",") else ","

        reader = csv.reader(content.splitlines(), delimiter=dialect)
        rows = list(reader)
        if not rows:
            return []

        header_row_idx = 0
        for idx, row in enumerate(rows[:10]):
            row_str = " ".join([_clean_str(c).lower() for c in row])
            if any(syn in row_str for syn in ["repere", "repère", "circuit", "tag", "cable", "depart"]):
                header_row_idx = idx
                break

        headers = [_clean_str(c) for c in rows[header_row_idx]]
        mapping = _find_column_mapping(headers)
        if "tag" not in mapping:
            logger.warning(f"Colonne 'TAG' non identifiée dans le CSV {path.name}")
            return []

        results: List[Dict[str, Any]] = []
        for row in rows[header_row_idx + 1:]:
            if not row or all(not str(c).strip() for c in row):
                continue
            item = cls._extract_item_from_row(row, mapping)
            if item and item.get("tag"):
                results.append(item)

        logger.info(f"[CalcNoteParser] {len(results)} départs extraits de {path.name} (CSV)")
        return results

    @staticmethod
    def _extract_item_from_row(row: Union[tuple, list], mapping: Dict[str, int]) -> Optional[Dict[str, Any]]:
        def get_val(field: str) -> Optional[str]:
            idx = mapping.get(field)
            if idx is not None and idx < len(row):
                v = row[idx]
                return _clean_str(v) if v is not None else None
            return None

        raw_tag = get_val("tag")
        if not raw_tag:
            return None

        norm_tag = normalize_tag(raw_tag)
        section = get_val("section")
        length = _parse_float(get_val("length"))
        du_pct = _parse_float(get_val("voltage_drop"))
        ib = _parse_float(get_val("ib"))
        in_rating = _parse_float(get_val("in_rating"))
        cable_type = get_val("cable_type")
        source = get_val("source")
        destination = get_val("destination")
        material = get_val("conductor_material")

        # Déduire le matériau si non explicite
        if not material and section:
            if "AL" in section.upper() or "ALU" in (cable_type or "").upper():
                material = "AL"
            else:
                material = "CU"

        return {
            "tag": norm_tag,
            "raw_tag": raw_tag,
            "source": source,
            "destination": destination,
            "calc_section": section,
            "calc_length_m": length,
            "calc_du_pct": du_pct,
            "ib_a": ib,
            "in_rating_a": in_rating,
            "cable_type": cable_type,
            "conductor_material": material or "CU",
            "source_type": "CALCULATION_NOTE",
        }
