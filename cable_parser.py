# -*- coding: utf-8 -*-
"""
cable_parser.py
===============
Parseur normatif de désignations de câbles industriels (CEI 60502-1, EN 50288-7, BS 5308).
Décompose les sections de conducteurs (phases, neutre, PE/G), identifie la famille
(énergie, contrôle, instrumentation) et estime le diamètre extérieur et le poids linéique.

Supporte :
  - nXs : n conducteurs de section s, sans vert/jaune (ex: 3X120 = 3 phases)
  - nGs : n conducteurs dont une âme verte/jaune PE (ex: 4G25, 5G6 = 3P+N+PE)
  - nXs+r : n conducteurs + 1 conducteur réduit r (ex: 3X120+70) -> rôle UNSPECIFIED
  - nXs+PEr / nXs+Nr : rôle explicite PE ou N (ex: 3X120+PE70, 3X50+N25)
  - kX(nXs) : k liaisons en parallèle (ex: 2X(3X240))
  - nPs / nTs : n paires ou triades d'instrumentation (ex: 12P0.75, 1T1.5)
  - Unipolaires : 1X240, 1X95, 50 mm² MALT
"""

import math
import re
from typing import Any, Dict, Optional, Tuple

_NUM = r"\d+(?:[.,]\d+)?"

# Regex pour câbles d'énergie et contrôle : ex 2X(3X240), 3x120+70, 4G25, 5x6, 1x240, 3x50+N25
_POWER_RE = re.compile(
    rf"^(?:(?P<par>\d+)\s*[X\*]\s*\(?)?(?P<n>\d+)\s*(?P<kind>[XG\*xXgG])\s*(?P<s>{_NUM})"
    rf"(?:\s*\+\s*(?P<role>PE|P|N)?\s*(?P<extra>{_NUM}))?\)?$",
    re.IGNORECASE
)

# Regex pour câbles instrumentation multipaires / multitriades : ex 1P1.5, 12P0.75, 4Tx0.75
_PAIR_TRIAD_RE = re.compile(
    rf"^(?:(?P<np>\d+)\s*(?P<kind>[PTpt])\s*[xX]?\s*(?P<s>{_NUM})|(?P<s2>{_NUM})\s*(?P<kind2>[PTpt])\s*(?P<np2>\d+))$",
    re.IGNORECASE
)

# Regex pour conducteur unique ou terre nue : ex 1x120, 1x240 mm² ou 50 mm² MALT
_SINGLE_RE = re.compile(
    rf"^(?:1\s*[xX]\s*)?(?P<s>{_NUM})\s*(?:mm[²2])?$",
    re.IGNORECASE
)

_ESTIMATED_DIAMETERS: Dict[Tuple[int, float], float] = {
    # 1 conducteur (unipolaire)
    (1, 16.0): 11.5, (1, 25.0): 13.0, (1, 35.0): 14.5, (1, 50.0): 16.0,
    (1, 70.0): 18.0, (1, 95.0): 20.5, (1, 120.0): 22.0, (1, 150.0): 24.0,
    (1, 185.0): 26.5, (1, 240.0): 29.5, (1, 300.0): 33.0,
    # 3 conducteurs
    (3, 1.5): 11.0, (3, 2.5): 12.0, (3, 4.0): 13.5, (3, 6.0): 15.0,
    (3, 10.0): 17.5, (3, 16.0): 20.0, (3, 25.0): 24.0, (3, 35.0): 27.0,
    (3, 50.0): 30.0, (3, 70.0): 34.0, (3, 95.0): 39.0, (3, 120.0): 43.0,
    (3, 150.0): 47.0, (3, 185.0): 53.0, (3, 240.0): 60.0, (3, 300.0): 66.0,
    # 4 conducteurs
    (4, 1.5): 12.0, (4, 2.5): 13.0, (4, 4.0): 15.0, (4, 6.0): 16.5,
    (4, 10.0): 19.0, (4, 16.0): 22.0, (4, 25.0): 26.5, (4, 35.0): 30.0,
    (4, 50.0): 34.0, (4, 70.0): 38.5, (4, 95.0): 44.0, (4, 120.0): 49.0,
    (4, 150.0): 54.0, (4, 185.0): 60.0, (4, 240.0): 68.0,
    # 5 conducteurs
    (5, 1.5): 13.0, (5, 2.5): 14.5, (5, 4.0): 16.5, (5, 6.0): 18.5,
    (5, 10.0): 21.0, (5, 16.0): 24.5, (5, 25.0): 29.5, (5, 35.0): 33.5,
    (5, 50.0): 38.0,
}


def _f(x: str) -> float:
    return float(x.replace(",", "."))


def estimate_cable_outer_diameter(n_conductors: int, section_mm2: float, extra_section_mm2: Optional[float] = None) -> float:
    """Estime le diamètre extérieur d'un câble en mm selon les standards constructeurs."""
    if (n_conductors, section_mm2) in _ESTIMATED_DIAMETERS:
        base_d = _ESTIMATED_DIAMETERS[(n_conductors, section_mm2)]
        if extra_section_mm2 and extra_section_mm2 > 0:
            base_d *= 1.05
        return round(base_d, 1)

    core_d = 1.15 * math.sqrt(section_mm2) + 1.5
    if n_conductors == 1:
        outer = core_d + 5.0
    elif n_conductors == 2:
        outer = 2.0 * core_d + 6.0
    elif n_conductors in (3, 4):
        outer = 2.4 * core_d + 7.0
    elif n_conductors == 5:
        outer = 2.7 * core_d + 8.0
    else:
        outer = 1.25 * math.sqrt(n_conductors) * core_d + 8.0

    if extra_section_mm2:
        outer += 2.0
    return round(max(outer, 8.0), 1)


def estimate_cable_weight_kg_m(n_conductors: int, section_mm2: float, extra_section_mm2: Optional[float] = None) -> float:
    """Estime le poids linéique d'un câble en kg/m (cuivre: 8.9 kg/dm3 + isolant/gaine/armure)."""
    total_copper_section = n_conductors * section_mm2 + (extra_section_mm2 or 0.0)
    copper_weight = total_copper_section * 0.0089  # kg/m
    total_weight = copper_weight * 1.5 + 0.15 + (0.02 * n_conductors)
    return round(max(total_weight, 0.08), 3)


def parse_cable(spec: Any) -> Optional[Dict[str, Any]]:
    """
    Parse une spécification de câble brute (ex: '3x120+70', '4G25', '12P0.75', '2X(3X240)', '1X240 mm²').
    Retourne un dictionnaire normalisé ou None si la chaîne n'est pas reconnue.
    """
    if not spec:
        return None
    raw = str(spec).strip()
    if not raw or raw.upper() in ("NONE", "N/A", "-", "NULL", "CANALISATION"):
        return None

    # Nettoyage des unités et suffixes de désignation
    cleaned = re.sub(r'(?i)\s*(?:mm[²2]|cu|al|r2v|xlpe|pvc|gsta|swa).*$', '', raw).strip()
    cleaned = cleaned.replace(" ", "")

    # 1. Test Câble d'énergie ou de contrôle
    m = _POWER_RE.match(cleaned)
    if m:
        par_str = m.group("par")
        parallel_runs = int(par_str) if par_str else 1
        n = int(m.group("n"))
        kind = m.group("kind").upper()
        s = _f(m.group("s"))
        extra_str = m.group("extra")
        extra = _f(extra_str) if extra_str else None
        role = (m.group("role") or "").upper()
        role_norm = {"PE": "PE", "P": "PE", "N": "N"}.get(role, "UNSPECIFIED" if extra is not None else None)
        has_pe_core = (kind == "G")
        has_earth = has_pe_core or (role_norm == "PE")

        family = "CONTROL" if (n >= 7 or (n >= 5 and s <= 2.5)) else "POWER"
        norm_spec = f"{n}{kind}{int(s) if s.is_integer() else s}"
        if extra:
            role_label = role_norm if role_norm in ("PE", "N") else ""
            norm_spec += f"+{role_label}{int(extra) if extra.is_integer() else extra}"
        if parallel_runs > 1:
            norm_spec = f"{parallel_runs}X({norm_spec})"

        d_ext = estimate_cable_outer_diameter(n, s, extra)
        w_lin = estimate_cable_weight_kg_m(n, s, extra) * parallel_runs

        return {
            "family": family,
            "spec": cleaned,
            "parallel_runs": parallel_runs,
            "n_conductors": n,
            "section_mm2": s,
            "has_pe_core": has_pe_core,
            "has_earth": has_earth,
            "reduced_section_mm2": extra,
            "reduced_role": role_norm,
            "outer_diameter_mm": d_ext,
            "linear_weight_kg_m": w_lin,
            "raw_spec": raw,
            "normalized_spec": norm_spec
        }

    # 2. Test Instrumentation multi-paires / multitriades
    mp = _PAIR_TRIAD_RE.match(cleaned)
    if mp:
        k = (mp.group("kind") or mp.group("kind2") or "P").upper()
        np = int(mp.group("np") or mp.group("np2") or 1)
        s = _f(mp.group("s") or mp.group("s2"))
        is_pair = (k == "P")
        n_cond = np * (2 if is_pair else 3)
        d_ext = round((7.0 if is_pair else 8.0) + math.sqrt(np) * (2.0 + math.sqrt(s)), 1)
        w_lin = round((0.08 if is_pair else 0.10) + np * s * (0.025 if is_pair else 0.035), 3)
        return {
            "family": "INSTRUMENT",
            "spec": cleaned,
            "parallel_runs": 1,
            "n_conductors": n_cond,
            "n_pairs": np if is_pair else None,
            "n_triples": np if not is_pair else None,
            "section_mm2": s,
            "has_pe_core": False,
            "has_earth": True,  # blindage drain
            "reduced_section_mm2": None,
            "reduced_role": None,
            "outer_diameter_mm": d_ext,
            "linear_weight_kg_m": w_lin,
            "raw_spec": raw,
            "normalized_spec": f"{np}{k}{int(s) if s.is_integer() else s}"
        }

    # 3. Test Unipolaire simple ou conducteur de terre
    ms = _SINGLE_RE.match(cleaned)
    if ms:
        s = _f(ms.group("s"))
        d_ext = estimate_cable_outer_diameter(1, s)
        w_lin = estimate_cable_weight_kg_m(1, s)
        return {
            "family": "POWER",
            "spec": cleaned,
            "parallel_runs": 1,
            "n_conductors": 1,
            "section_mm2": s,
            "has_pe_core": False,
            "has_earth": False,
            "reduced_section_mm2": None,
            "reduced_role": None,
            "outer_diameter_mm": d_ext,
            "linear_weight_kg_m": w_lin,
            "raw_spec": raw,
            "normalized_spec": f"1X{int(s) if s.is_integer() else s}"
        }

    return None
