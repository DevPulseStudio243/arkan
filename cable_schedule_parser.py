"""
cable_schedule_parser.py
========================
Parser universel pour Carnets de Câbles (Cable Schedule EPC / Listes de Câbles Excel/CSV).
Extrait les câbles déclarés avec tenant/aboutissant, section déclarée et métré prévu.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import openpyxl

from tag_normalizer import normalize_tag

logger = logging.getLogger("arkan.cable_schedule_parser")

CS_COL_SYNONYMS = {
    "tag": [
        "repere_du_cable", "repere_cable", "cable_tag", "tag_cable", "num_cable", "cable_no",
        "n_cable", "ref_cable", "cable_id", "circuit_id", "repere", "repère", "tag", "cable", "circuit"
    ],
    "source": [
        "tenant_repere", "tenant", "amont", "source", "from", "origine", "de", "depart", "armoire",
        "tableau", "tgbt"
    ],
    "destination": [
        "aboutissant_repere", "aboutissant", "aval", "destination", "to", "recepteur", "récepteur",
        "vers", "charge", "appareil", "equipement"
    ],
    "section": [
        "section_mm2", "section", "sec", "cable_section", "dimension", "cross_section", "calibre_cable",
        "taille"
    ],
    "length": [
        "longueur_m", "longueur", "length", "len", "l_m", "distance", "metrage",
        "metrage_m", "quantite", "qty"
    ],
    "cable_type": [
        "typologie_complete_retenue", "type_requis", "type", "type_cable", "nature_cable", "cable_type", "reference", "designation",
        "spec", "spec_cable", "norme"
    ],
    "description": [
        "description", "designation", "service", "libelle", "fonction", "nom"
    ]
}


def _clean_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _normalize_header(header: str) -> str:
    h = header.lower().strip()
    h = re.sub(r"[éèêë]", "e", h)
    h = re.sub(r"[àâä]", "a", h)
    h = re.sub(r"[ùûü]", "u", h)
    h = re.sub(r"[ôö]", "o", h)
    h = re.sub(r"[îï]", "i", h)
    h = re.sub(r"[^a-z0-9_]", "_", h)
    return re.sub(r"_+", "_", h).strip("_")


def _find_cs_column_mapping(headers: List[str]) -> Dict[str, int]:
    norm_headers = [_normalize_header(h) for h in headers]
    mapping: Dict[str, int] = {}

    # Exact matches first
    for field, synonyms in CS_COL_SYNONYMS.items():
        for syn in synonyms:
            syn_norm = _normalize_header(syn)
            for idx, h in enumerate(norm_headers):
                if h == syn_norm:
                    if field == "tag" and any(k in h for k in ["tenant", "aboutissant", "presse", "gland", "amont", "aval"]):
                        continue
                    if field in ["source", "destination"] and any(k in h for k in ["presse", "gland", "service"]):
                        continue
                    mapping[field] = idx
                    break
            if field in mapping:
                break

    # Substring matches second
    for field, synonyms in CS_COL_SYNONYMS.items():
        if field in mapping:
            continue
        for syn in synonyms:
            syn_norm = _normalize_header(syn)
            for idx, h in enumerate(norm_headers):
                if syn_norm in h:
                    if field == "tag" and any(k in h for k in ["tenant", "aboutissant", "presse", "gland", "amont", "aval", "touret"]):
                        continue
                    if field in ["source", "destination"] and any(k in h for k in ["presse", "gland", "service"]):
                        continue
                    mapping[field] = idx
                    break
            if field in mapping:
                break

    return mapping


def _detect_headers_and_start(rows: List[Any]) -> Tuple[List[str], int]:
    """Détecte les en-têtes (mono-ligne ou hiérarchiques sur 2 lignes) et l'indice de début des données."""
    for idx in range(min(15, max(0, len(rows) - 1))):
        r1_str = " ".join([_clean_str(c).lower() for c in rows[idx] if c is not None])
        r2_str = " ".join([_clean_str(c).lower() for c in rows[idx + 1] if c is not None]) if idx + 1 < len(rows) else ""

        # Détection 2-lignes hiérarchiques (ex: ligne 1 = TENANT/ABOUTISSANT, ligne 2 = REPERE/SECTION/LONGUEUR)
        has_super = any(s in r1_str for s in ["tenant", "aboutissant", "source", "destination", "from", "to", "caracteristique"])
        has_sub = any(s in r2_str for s in ["repere", "repère", "tag", "cable", "section", "longueur", "core"])

        if has_super and has_sub:
            filled_super = []
            curr = ""
            for c in rows[idx]:
                val = _clean_str(c)
                if val:
                    curr = val
                filled_super.append(curr)
            combined = []
            for sup, sub in zip(filled_super, rows[idx + 1]):
                sup_c = _clean_str(sup)
                sub_c = _clean_str(sub)
                if sup_c and sub_c and sup_c.lower() not in sub_c.lower():
                    combined.append(f"{sup_c}_{sub_c}")
                else:
                    combined.append(sub_c or sup_c)
            return combined, idx + 2

        # Détection mono-ligne standard
        if any(s in r1_str for s in ["repere", "repère", "tag", "cable", "circuit", "tenant", "from"]):
            return [_clean_str(c) for c in rows[idx]], idx + 1

    return [], 0


def _parse_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip().replace(" ", "").replace(",", ".")
    s = re.sub(r"[^\d\.-]", "", s)
    if not s or s == "." or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


class CableScheduleParser:
    """Parser universel pour Carnets de Câbles (Cable Schedule EPC)."""

    @classmethod
    def parse_file(cls, file_path: Union[str, Path]) -> List[Dict[str, Any]]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Fichier de carnet de câbles introuvable : {path}")

        suffix = path.suffix.lower()
        if suffix in [".xlsx", ".xlsm", ".xltx"]:
            return cls._parse_excel(path)
        elif suffix in [".csv", ".txt"]:
            return cls._parse_csv(path)
        else:
            raise ValueError(f"Format non supporté ({suffix}). Formats requis : .xlsx, .csv")

    @classmethod
    def _parse_excel(cls, path: Path) -> List[Dict[str, Any]]:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        results: List[Dict[str, Any]] = []

        for sname in wb.sheetnames:
            sheet = wb[sname]
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                continue

            headers, start_row = _detect_headers_and_start(rows)
            if not headers:
                continue

            mapping = _find_cs_column_mapping(headers)
            if "tag" not in mapping:
                continue

            sheet_cables = 0
            for row in rows[start_row:]:
                if not row or all(c is None for c in row):
                    continue
                item = cls._extract_item_from_row(row, mapping)
                if item and item.get("raw_tag"):
                    results.append(item)
                    sheet_cables += 1

            if sheet_cables > 0:
                logger.info(f"[CableScheduleParser] {sheet_cables} câbles extraits de l'onglet '{sname}' dans {path.name}")

        wb.close()
        logger.info(f"[CableScheduleParser] Total {len(results)} câbles extraits de {path.name} (Excel)")
        return results

    @classmethod
    def _parse_csv(cls, path: Path) -> List[Dict[str, Any]]:
        encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
        content = None
        for enc in encodings:
            try:
                content = path.read_text(encoding=enc)
                break
            except UnicodeDecodeError:
                continue

        if not content:
            raise ValueError(f"Impossible de lire le fichier CSV {path.name}")

        first_lines = "\n".join(content.splitlines()[:5])
        dialect = ";" if first_lines.count(";") >= first_lines.count(",") else ","

        reader = csv.reader(content.splitlines(), delimiter=dialect)
        rows = list(reader)
        if not rows:
            return []

        headers, start_row = _detect_headers_and_start(rows)
        if not headers:
            return []

        mapping = _find_cs_column_mapping(headers)
        if "tag" not in mapping:
            logger.warning(f"Colonne 'TAG' non trouvée dans le CSV {path.name}")
            return []

        results: List[Dict[str, Any]] = []
        for row in rows[start_row:]:
            if not row or all(not str(c).strip() for c in row):
                continue
            item = cls._extract_item_from_row(row, mapping)
            if item and item.get("raw_tag"):
                results.append(item)

        logger.info(f"[CableScheduleParser] {len(results)} câbles extraits de {path.name} (CSV)")
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
        if not raw_tag or raw_tag.lower() in ["total", "sous-total", "subtotal", "page", "n°", "no", "item"]:
            return None

        norm_tag = normalize_tag(raw_tag)
        section = get_val("section")
        length = _parse_float(get_val("length"))
        cable_type = get_val("cable_type")
        source = get_val("source")
        destination = get_val("destination")
        desc = get_val("description")

        return {
            "tag": norm_tag,
            "raw_tag": raw_tag,
            "description": desc or f"Câble pour {norm_tag}",
            "source": source,
            "destination": destination,
            "declared_section": section,
            "declared_length_m": length,
            "cable_type": cable_type,
            "source_type": "CABLE_SCHEDULE",
        }
